#!/usr/bin/env python3
"""Merge contributions that have passed the checker, with no human in the loop.

Runs in GitHub Actions from the main branch with GH_TOKEN and
GITHUB_REPOSITORY set. It never checks out or runs contributed code; it only
reads pull request metadata through the GitHub API and decides from that.

A pull request is merged only if ALL of these hold:

  * it targets main, is open and is not a draft;
  * it adds exactly one file, under QPCP/Proofs, QPCP/Refutations or
    QPCP/Lemmas, and changes nothing else. Because nothing else changed, the
    `check` workflow that ran on it was main's own, unmodified;
  * the `check` workflow succeeded on the pull request's current head commit;
  * for a proof or refutation: the step's issue is open, is labelled `step`,
    is not retired, and is not claimed by somebody else;
  * for a new lemma: the pull request author opened the proposal issue whose
    number the lemma carries, and a reviewer listed in reviewers.json (kept by
    the maintainer, read from main) other than the author has approved the
    pull request's current head commit. Approvals by anyone else are advisory:
    the statement waits for the maintainer.

Anything that does not qualify is left alone for a person to look at.

Usage: automerge.py [--dry-run]
"""

import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("qpcp_logsafe", ROOT / "scripts" / "logsafe.py")
_logsafe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_logsafe)
log_safe = _logsafe.log_safe

ID = r"(?:S\d{3,6}|L\d{1,9})"
PROOF_RE = re.compile(rf"^QPCP/Proofs/({ID})\.lean$")
REFUTATION_RE = re.compile(rf"^QPCP/Refutations/({ID})\.lean$")
LEMMA_RE = re.compile(r"^QPCP/Lemmas/L(\d{1,9})\.lean$")
BOT_LOGINS = {"github-actions[bot]", "github-actions"}


def trusted_reviewers(root=ROOT):
    """Logins in reviewers.json, lower-cased. A missing or malformed file trusts nobody."""
    try:
        data = json.loads((root / "reviewers.json").read_text())
    except (OSError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {r.strip().lower() for r in data if isinstance(r, str) and r.strip()}

QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, after: $cursor, baseRefName: "main") {
      pageInfo { hasNextPage endCursor }
      nodes {
        number isDraft changedFiles headRefOid
        author { login }
        files(first: 3) { nodes { path changeType } }
        reviews(states: APPROVED, first: 30) { nodes { author { login } commit { oid } } }
        commits(last: 1) { nodes { commit { oid checkSuites(first: 30) { nodes {
          conclusion
          workflowRun { event workflow { name } }
        } } } } }
      }
    }
  }
}
"""


class Api:
    def __init__(self, token, repo, dry_run):
        self.token, self.repo, self.dry_run = token, repo, dry_run
        self.owner, self.name = repo.split("/", 1)

    def call(self, method, url, body=None):
        if not url.startswith("https://"):
            url = f"https://api.github.com{url}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qpcp-automerge",
        })
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def write(self, method, path, body=None):
        """A call that changes something. Skipped, but logged, in a dry run."""
        if self.dry_run:
            print(log_safe(f"    [dry run] {method} {path} {json.dumps(body) if body else ''}"))
            return {}
        return self.call(method, f"/repos/{self.repo}{path}", body)

    def get(self, path):
        return self.call("GET", f"/repos/{self.repo}{path}")

    def open_pulls(self):
        cursor, out = None, []
        while True:
            res = self.call("POST", "/graphql", {
                "query": QUERY,
                "variables": {"owner": self.owner, "name": self.name, "cursor": cursor},
            })
            if res.get("errors"):
                raise RuntimeError(f"GraphQL: {res['errors']}")
            page = res["data"]["repository"]["pullRequests"]
            out.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return out
            cursor = page["pageInfo"]["endCursor"]

    def step_issue_for(self, ident, cache):
        """The issue of a step. Lemma L<N> is issue N; founding steps are found by title."""
        if ident.startswith("L"):
            try:
                return self.get(f"/issues/{ident[1:]}")
            except urllib.error.HTTPError:
                return None
        if "founding" not in cache:
            found, page = {}, 1
            while True:
                rows = self.get(f"/issues?labels=step&state=all&per_page=100&page={page}")
                for i in rows:
                    m = re.match(r"^(S\d{3,6}):", i.get("title") or "")
                    if m and "pull_request" not in i:
                        found[m.group(1)] = i
                if len(rows) < 100:
                    break
                page += 1
            cache["founding"] = found
        return cache["founding"].get(ident)


def labels(issue):
    return {l["name"] for l in issue.get("labels", [])}


def check_passed(pr):
    """True if main's `check` workflow succeeded on the current head commit."""
    commits = pr["commits"]["nodes"]
    if not commits or commits[0]["commit"]["oid"] != pr["headRefOid"]:
        return False
    for suite in commits[0]["commit"]["checkSuites"]["nodes"]:
        run = suite.get("workflowRun")
        if (run and run["workflow"]["name"] == "check" and run["event"] == "pull_request"
                and suite["conclusion"] == "SUCCESS"):
            return True
    return False


def decide(pr, api, cache, reviewers_allowed=None):
    """Return (action, detail). action is 'skip' or a kind: proof, refutation, lemma."""
    author = (pr.get("author") or {}).get("login")
    if not author or pr["isDraft"]:
        return "skip", "draft or no author"
    files = pr["files"]["nodes"]
    if pr["changedFiles"] != 1 or len(files) != 1:
        return "skip", f"changes {pr['changedFiles']} files"
    path, change = files[0]["path"], files[0]["changeType"]
    if change != "ADDED":
        return "skip", f"{path} is {change.lower()}, not added"
    if not check_passed(pr):
        return "skip", "check has not succeeded on the head commit"

    m = PROOF_RE.match(path) or REFUTATION_RE.match(path)
    if m:
        kind = "proof" if PROOF_RE.match(path) else "refutation"
        ident = m.group(1)
        issue = api.step_issue_for(ident, cache)
        if not issue or "pull_request" in issue:
            return "skip", f"no step issue for {ident}"
        names = labels(issue)
        if issue["state"] != "open" or "step" not in names or "retired" in names:
            return "skip", f"step {ident} is not open"
        holders = {a["login"] for a in issue.get("assignees", [])}
        if holders and author not in holders:
            return "skip", f"step {ident} is claimed by {', '.join(sorted(holders))}"
        return kind, {"ident": ident, "issue": issue["number"], "author": author}

    m = LEMMA_RE.match(path)
    if m:
        number = int(m.group(1))
        try:
            issue = api.get(f"/issues/{number}")
        except urllib.error.HTTPError:
            return "skip", f"no proposal issue #{number}"
        if "pull_request" in issue or issue["state"] != "open" or "proposal" not in labels(issue):
            return "skip", f"issue #{number} is not an open proposal"
        if (issue.get("user") or {}).get("login") != author:
            return "skip", f"proposal #{number} was opened by someone else"
        # The approval must be on the commit being merged, by someone else,
        # and by a reviewer the maintainer has listed in reviewers.json.
        approvers = {
            (r.get("author") or {}).get("login")
            for r in pr["reviews"]["nodes"]
            if (r.get("commit") or {}).get("oid") == pr["headRefOid"]
        } - {None} - BOT_LOGINS
        approvers = {a for a in approvers if a.lower() != author.lower()}
        allowed = trusted_reviewers() if reviewers_allowed is None else reviewers_allowed
        reviewers = {a for a in approvers if a.lower() in allowed}
        if not reviewers:
            if approvers:
                return "skip", ("waiting for the maintainer: approvals by "
                                f"{', '.join(sorted(approvers))} are advisory (not in reviewers.json)")
            return "skip", "no approving statement review by a listed reviewer yet"
        return "lemma", {
            "ident": f"L{number}", "issue": number, "author": author,
            "reviewers": sorted(reviewers), "title": issue.get("title") or "",
        }
    return "skip", f"{path} is not a contribution file"


def apply(pr, kind, d, api):
    n, issue, ident = pr["number"], d["issue"], d["ident"]
    # A canonical title, so the record can credit the right step to the author.
    verb = {"proof": "Prove", "refutation": "Refute", "lemma": "State"}[kind]
    try:
        api.write("PATCH", f"/pulls/{n}", {"title": f"{verb} {ident}"})
        api.write("PUT", f"/pulls/{n}/merge", {"sha": pr["headRefOid"], "merge_method": "squash"})
    except urllib.error.HTTPError as e:
        print(f"    merge refused ({e.code}); leaving it for a person")
        return False

    if kind == "lemma":
        title = re.sub(r"^\s*proposal\s*:?\s*", "", d["title"], flags=re.I).strip() or "(untitled)"
        api.write("PATCH", f"/issues/{issue}", {"title": f"{ident}: {title}"[:250]})
        api.write("POST", f"/issues/{issue}/labels", {"labels": ["step"]})
        try:
            api.write("DELETE", f"/issues/{issue}/labels/proposal")
        except urllib.error.HTTPError:
            pass
        api.write("POST", f"/issues/{issue}/comments", {"body": (
            f"Lemma **{ident}** is now stated in `QPCP/Lemmas/{ident}.lean` (pull request #{n}), "
            f"statement reviewed by {', '.join('@' + r for r in d['reviewers'])}. "
            "It is open: comment `/claim` to prove it or to refute it."
        )})
        return True

    verdict = "proved" if kind == "proof" else "refuted"
    api.write("POST", f"/issues/{issue}/labels", {"labels": [verdict]})
    try:
        api.write("DELETE", f"/issues/{issue}/labels/claimed")
    except urllib.error.HTTPError:
        pass
    api.write("POST", f"/issues/{issue}/comments", {"body": (
        f"**{ident}** was {verdict} by @{d['author']} in pull request #{n}. "
        "The checker accepted it and it has been merged into the record."
    )})
    api.write("PATCH", f"/issues/{issue}", {"state": "closed", "state_reason": "completed"})
    return True


def main(argv):
    dry_run = "--dry-run" in argv
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GH_TOKEN and GITHUB_REPOSITORY must be set", file=sys.stderr)
        return 2
    api, cache, merged = Api(token, repo, dry_run), {}, 0
    allowed = trusted_reviewers()
    print(f"listed statement reviewers: {', '.join(sorted(allowed)) or 'none'}")
    for pr in api.open_pulls():
        kind, detail = decide(pr, api, cache, allowed)
        if kind == "skip":
            # File names in `detail` are the contributor's: make them safe to log.
            print(log_safe(f"#{pr['number']}: left alone ({detail})"))
            continue
        print(log_safe(f"#{pr['number']}: merging {kind} of {detail['ident']} by {detail['author']}"))
        if apply(pr, kind, detail, api):
            merged += 1
    print(f"merged {merged} pull request(s){' (dry run)' if dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
