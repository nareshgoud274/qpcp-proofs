#!/usr/bin/env python3
"""Build status.json, the single file the project site reads.

Runs in GitHub Actions on a checkout of main, with GH_TOKEN and
GITHUB_REPOSITORY set. It combines:

  * the latest verification record (scripts/verification_record.py), the only
    source of "proved" and "refuted": a result counts when the record lists it
    as ACCEPTED with the same path and Git blob as the file on main. A proof or
    refutation file on main that no successful record covers is "pending"
    (pending verification) and is not counted as proved. The feed names the
    verified commit and run for each result, and for the record as a whole;
  * the working tree: steps.json, programs.json, retired.json, and the files
    under QPCP/Lemmas, QPCP/Proofs and QPCP/Refutations (with their Git blobs);
  * the GitHub API: issues (claims, reports, proposals), pull requests
    (credit, work in the checker) and releases (updates). These update
    immediately; only verdicts wait for verification.

For agents (#117), each step also carries its difficulty, its prerequisites
with their current states, its active claim, and, when it is open or claimed,
a submission card made from its own issue number (submission_card); each open
proposal carries a statement card (statement_card).

Visitors' browsers fetch only the resulting file, so the site keeps working
however many people are watching and however large the record grows.

Credit for a proof, refutation or statement comes from its file (#115): the
commit on main that added QPCP/Proofs/<ID>.lean (or Refutations, or
Lemmas/L<N>.lean), then the merged pull request containing that commit, whose
author is credited. Without one, the commit's author is credited, marked "no
pull request found". Titles are never matched for credit, and a proposal's
review link is only an open pull request that adds its lemma file. Needs a
checkout with full history.

Usage: build_status.py <output-path> <record.json> [<previous status.json>]
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID = r"(?:S\d{3,6}|L\d{1,9})"
REPORT_RE = re.compile(rf"^\s*report\s+({ID})\s*:?\s*", re.I)
MAX_FEED = 200


def api(path, token, repo):
    """Fetch every page of a GitHub REST list endpoint."""
    url = f"https://api.github.com/repos/{repo}{path}"
    url += ("&" if "?" in url else "?") + "per_page=100"
    out = []
    while url:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qpcp-status",
        })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    out.extend(json.load(r))
                    link = r.headers.get("Link", "")
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def api_one(path, token, repo):
    """Fetch one GitHub REST object."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}{path}", headers={
        "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "qpcp-status"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def labels(issue):
    return {l["name"] for l in issue.get("labels", [])}


def login(obj):
    return (obj.get("user") or {}).get("login", "")


def git_files(root, folder):
    """{id: {"path", "blob"}} for the committed files of one contribution folder at HEAD."""
    r = subprocess.run(["git", "-C", str(root), "ls-tree", "HEAD", "--", folder + "/"],
                       capture_output=True, text=True, check=True)
    out = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        if path.endswith(".lean"):
            out[Path(path).stem] = {"path": path, "blob": meta.split()[2]}
    return out


CONTRIB_FILE = re.compile(r"^QPCP/(?:(Proofs|Refutations)/(S\d{3,6}|L[1-9]\d{0,8})|Lemmas/(L[1-9]\d{0,8}))\.lean$")


def canonical_lemma(sid):
    """L<N> with no leading zero: the only spelling that names issue #N (#115)."""
    return re.fullmatch(r"L[1-9]\d{0,8}", sid) is not None


def added_commits(root, paths):
    """{path: the most recent commit on HEAD's history that added that path}.

    Credit for a contribution comes from the commit that added its file, never
    from a pull request's title (#115)."""
    out = {}
    for path in paths:
        r = subprocess.run(["git", "-C", str(root), "log", "-1", "--diff-filter=A", "--format=%H", "HEAD", "--", path],
                           capture_output=True, text=True, check=True)
        if r.stdout.strip():
            out[path] = r.stdout.strip()
    return out


def pick_pull(pulls):
    """The merged pull request into main that contains a commit: the earliest merged."""
    merged = [p for p in pulls or [] if p.get("merged_at") and (p.get("base") or {}).get("ref") == "main"]
    return min(merged, key=lambda p: p["merged_at"]) if merged else None


def resolve_credits(added, pulls_of, author_of, previous=None):
    """{path: credit} for every contribution file, from the commit that added it.

    pulls_of(sha) lists the pull requests that contain the commit (GitHub's
    /commits/<sha>/pulls); author_of(sha) gives the commit's author (a GitHub
    login when GitHub knows one, else the Git author name). If no merged pull
    request contains the commit, the commit's author is credited and the
    credit says "no pull request found". `previous` holds the credits of the
    last published feed: an entry for the same path and commit that found a
    pull request is reused (a merged commit's pull request does not change),
    so each run asks the API only about new files.
    """
    old = {c["path"]: c for c in (previous or []) if c.get("path")}
    out = {}
    for path, sha in sorted(added.items()):
        prev = old.get(path)
        if prev and prev.get("commit") == sha and prev.get("pr"):
            out[path] = prev
            continue
        pr = pick_pull(pulls_of(sha))
        if pr:
            out[path] = {"path": path, "commit": sha, "pr": pr["number"], "prUrl": pr["html_url"],
                         "who": login(pr), "mergedAt": pr["merged_at"], "note": ""}
        else:
            out[path] = {"path": path, "commit": sha, "pr": None, "prUrl": "", "who": author_of(sha),
                         "mergedAt": "", "note": "no pull request found"}
    return out


def previous_credits(status):
    """The credits recorded in a previously published status.json."""
    out = []
    for s in (status or {}).get("steps", []):
        out += [c for c in (s.get("credit"), s.get("statedCredit")) if isinstance(c, dict)]
    return out


def read_tree(root=ROOT):
    """Everything the status needs from the working tree."""
    def load(name, default):
        p = root / name
        return json.loads(p.read_text()) if p.is_file() else default

    lemmas = []
    for path in sorted((root / "QPCP" / "Lemmas").glob("L*.lean"), key=lambda p: int(p.stem[1:])):
        src = path.read_text(errors="replace")
        program = re.search(r"^\s*PROGRAM:\s*([a-z0-9-]+)\s*$", src, re.M)
        plain = re.search(r"^\s*PLAIN:\s*(.+?)\s*$", src, re.M)
        lemmas.append({
            "id": path.stem,
            "program": program.group(1) if program else "",
            "title": plain.group(1) if plain else path.stem,
        })
    return {
        "steps": load("steps.json", []),
        "programs": load("programs.json", []),
        "retired": set(load("retired.json", [])),
        "reviewers": load("reviewers.json", []),
        "barriers": load("barriers.json", []),
        "lemmas": lemmas,
        "proofs": git_files(root, "QPCP/Proofs"),
        "refutations": git_files(root, "QPCP/Refutations"),
        "lemmaFiles": git_files(root, "QPCP/Lemmas"),
        "commit": subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                 text=True, check=True).stdout.strip(),
    }


def record_url(sha):
    return f"records/{sha}.json"


def reproduce_check(kind, sid):
    """The command that re-runs one result's sandboxed check, and the line it must print.

    tests/test_reproduce_command.py runs exactly this, for a step picked at
    random, on Linux CI; see REPRODUCE.md for the setup it needs.
    """
    module = {"proof": "QPCP.Proofs", "refutation": "QPCP.Refutations"}[kind]
    return {"command": f"python3 -I scripts/sandbox_verify.py record --only {module}.{sid}",
            "expect": f"ACCEPTED: {kind} {sid}"}


def submission_card(sid, issue_number):
    """What a volunteer copies to submit a proof or refutation of `sid`.

    Built only from the step's id and the number of its own issue, never from a
    guess: a founding step's issue number is unrelated to its id (S060 is #146).
    """
    if sid.startswith("S"):
        statement, source, imp = f"QPCP.Statement.{sid}", "QPCP/Statements.lean", "QPCP.Statements"
    else:
        statement, source, imp = f"QPCP.Lemma.{sid}", f"QPCP/Lemmas/{sid}.lean", f"QPCP.Lemmas.{sid}"
    closes = f"Closes #{issue_number}"
    card = {"id": sid, "issue": issue_number, "statement": statement, "statementSource": source,
            "import": imp, "closes": closes}
    lines = [f"{sid}  (issue #{issue_number})",
             f"statement   {statement}   in {source}",
             f"import      import {imp}   (and any merged QPCP.Proofs.<ID> it uses)"]
    for kind, folder, ns, verb, typ in (
            ("proof", "QPCP/Proofs", "QPCP.Proof", "Prove", statement),
            ("refutation", "QPCP/Refutations", "QPCP.Refutation", "Refute", f"¬ {statement}")):
        k = {"path": f"{folder}/{sid}.lean", "declaration": f"{ns}.{sid}", "type": typ,
             "build": f"lake build {folder.replace('/', '.')}.{sid}", "title": f"{verb} {sid}"}
        card[kind] = k
        lines += ["", f"{kind}:",
                  f"  file      {k['path']}",
                  f"  theorem   {k['declaration']} : {typ}",
                  f"  build     {k['build']}",
                  f"  PR title  {k['title']}",
                  f"  PR body   {closes}"]
    card["text"] = "\n".join(lines)
    return card


def statement_card(number):
    """What a proposer copies to submit the statement for proposal issue #number.

    The lemma id is the issue's number by definition, and the issue stays open
    after the statement merges, for someone to prove or refute: no "Closes".
    """
    sid = f"L{number}"
    card = {"id": sid, "issue": number, "path": f"QPCP/Lemmas/{sid}.lean", "declaration": f"QPCP.Lemma.{sid}",
            "build": f"lake build QPCP.Lemmas.{sid}", "title": f"State {sid}", "body": f"Proposal #{number}"}
    card["text"] = "\n".join([
        f"{sid}  (proposal issue #{number}; it stays open: do not write Closes)",
        f"  file      {card['path']}",
        f"  def       {card['declaration']} : Prop",
        f"  build     {card['build']}",
        f"  PR title  {card['title']}",
        f"  PR body   {card['body']}"])
    return card


def verified_results(record):
    """{(kind, id): item} for every ACCEPTED proof and refutation in the record."""
    out = {}
    for it in (record or {}).get("evidence", {}).get("items", []):
        if it.get("verdict") == "ACCEPTED" and it.get("kind") in ("proof", "refutation"):
            out[(it["kind"], it["id"])] = it
    return out


def assemble(tree, issues, closed_pulls, open_pulls, releases, now=None, record=None, repo=""):
    """Pure function: the tree, raw GitHub data and the latest verification record in,
    the status document out. `repo` (owner/name) is used only to write citation links."""
    verified = verified_results(record)
    rec_commit = (record or {}).get("evidence", {}).get("commit", "")
    rec_run = (record or {}).get("run", {})
    pub = (record or {}).get("publication") or {}
    rec_pub = pub.get("recordCommit", "")

    def raw_at(commit, path):
        return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}" if repo and commit else ""

    def first_verified(kind, it):
        for f in pub.get("firstVerified", {}).get(f"{kind}:{it['id']}", []):
            if (f["path"], f["blob"]) == (it["path"], it["blob"]):
                return dict(f, recordUrl=raw_at(f["recordCommit"], f["record"]))
        return None
    step_issue, reports, proposals, mandates, by_number = {}, [], [], [], {}
    for i in issues:
        if "pull_request" in i:
            continue
        by_number[i["number"]] = i
        names = labels(i)
        if "report" in names:
            reports.append(i)
        elif "mandate" in names:
            mandates.append(i)
        elif "proposal" in names:
            proposals.append(i)
        elif "step" in names:
            m = re.match(rf"^({ID}):", i.get("title") or "")
            if m:
                step_issue[m.group(1)] = i

    # Credit comes from the file (#115): tree["credits"] maps each contribution
    # file to the merged pull request whose commit added it (resolve_credits).
    # Pull request titles are never read for credit; closed_pulls is unused.
    credits = tree.get("credits", {})

    def credit_for(sid, kinds):
        for folder in kinds:
            c = credits.get(f"QPCP/{folder}/{sid}.lean")
            if c:
                return c
        return None

    program_title = {p["id"]: p["title"] for p in tree["programs"]}
    rows = [{
        "id": s["id"], "title": s["title"], "section": s["section"], "program": s.get("program", ""),
        "retired": s.get("retired") is True, "replacedBy": s.get("replaced_by", ""),
        "exercise": s.get("exercise") is True,
        "difficulty": s.get("difficulty"), "deps": list(s.get("deps", [])),
        "background": list(s.get("background", [])),
    } for s in tree["steps"]]
    rows += [{
        "id": l["id"], "title": l["title"], "program": l["program"],
        "section": program_title.get(l["program"], l["program"] or "Other"),
        "retired": False, "replacedBy": "", "exercise": False,
        "difficulty": None, "deps": [], "background": [],
    } for l in tree["lemmas"]]

    people = {}

    def give(who, kind, sid):
        if who:
            people.setdefault(who, {"proved": [], "refuted": [], "stated": []})[kind].append(sid)

    count = {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0, "disputed": 0,
             "humanReviewed": 0}
    per_program, out_steps = {}, []
    for r in rows:
        sid = r["id"]
        # Only the canonical spelling L<N> names issue #N: L0777 is not L777 (#115).
        issue = step_issue.get(sid) or (by_number.get(int(sid[1:])) if canonical_lemma(sid) else None)
        names = labels(issue) if issue else set()
        status, who, when, pr, ver, claim, former = "open", "", "", None, None, None, None
        # A verdict comes only from the record, and only for the bytes on main: the
        # file must be on main now, at the record's path, with the record's blob.
        # A result the record lists whose file is gone from main is not proved now;
        # it is kept, for its page only, as "was verified at <commit>".
        for kind, done in (("proof", "proved"), ("refutation", "refuted")):
            it = verified.get((kind, sid))
            on_main = tree["proofs" if kind == "proof" else "refutations"].get(sid)
            if it and on_main is not None and (on_main["path"], on_main["blob"]) == (it["path"], it["blob"]):
                ver = (done, it, kind)
            elif it and on_main is None:
                former = {"status": done, "commit": rec_commit, "path": it["path"], "blob": it["blob"],
                          "record": record_url(rec_commit), "runUrl": rec_run.get("url", "")}
        on_main = tree["proofs"].get(sid) or tree["refutations"].get(sid)
        if r["retired"] or sid in tree["retired"] or "retired" in names:
            status = "retired"
            when = (issue or {}).get("closed_at") or ""
        elif ver:
            status = ver[0]
            pr = credit_for(sid, ("Proofs",) if status == "proved" else ("Refutations",))
        elif on_main:
            status = "pending"
            pr = credit_for(sid, ("Proofs",) if sid in tree["proofs"] else ("Refutations",))
        elif "claimed" in names:
            status = "claimed"
            who = ", ".join(a["login"] for a in issue.get("assignees", []))
            when = issue.get("updated_at") or ""
            # A claim lapses 24 hours after the issue's last comment (claim.yml).
            claim = {"by": [a["login"] for a in issue.get("assignees", [])], "lastActivity": when}
        if status in ("proved", "refuted", "pending"):
            who = (pr or {}).get("who", "")
            when = (pr or {}).get("mergedAt", "")
        if status in ("proved", "refuted"):
            give(who, status, sid)
        stated = credit_for(sid, ("Lemmas",)) if sid.startswith("L") else None
        if stated:
            give(stated["who"], "stated", sid)
        disputed = status != "retired" and "disputed" in names
        # Review by a human specialist is tracked separately from Lean's verdict.
        reviewed = "human-reviewed" in names
        if reviewed:
            count["humanReviewed"] += 1
        count[status] += 1
        if disputed:
            count["disputed"] += 1
        tally = per_program.setdefault(r["program"], {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0})
        tally[status] += 1
        out_steps.append({
            "id": sid, "title": r["title"], "section": r["section"], "program": r["program"],
            "status": status, "who": who, "when": when, "disputed": disputed, "reviewed": reviewed,
            "replacedBy": r["replacedBy"], "statedBy": stated["who"] if stated else "",
            "exercise": r["exercise"], "difficulty": r["difficulty"],
            # Filled in below, once every step's status is known.
            "deps": r["deps"], "background": r["background"],
            "claim": claim,
            # Only for work that can be submitted now, and only with the step's own issue.
            "submission": submission_card(sid, issue["number"]) if issue and status in ("open", "claimed") else None,
            "issue": issue["number"] if issue else None,
            "url": issue["html_url"] if issue else "",
            "prUrl": (pr or {}).get("prUrl", ""),
            # Where the credit comes from: the commit that added the file, and its pull request.
            "credit": pr, "statedCredit": stated,
            "verified": None if not ver else {
                "commit": rec_commit, "runUrl": rec_run.get("url", ""), "record": record_url(rec_commit),
                "declaration": ver[1]["declaration"], "path": ver[1]["path"], "blob": ver[1]["blob"],
                "statementPath": ver[1]["statementPath"], "statementLine": ver[1]["statementLine"],
                "statementDigest": ver[1]["statementDigest"], "dependsOn": ver[1]["dependsOn"],
                # The definition a one-line statement names, at the verified commit (absent from older records).
                "statementDefinition": ver[1].get("statementDefinition"),
                # The record's bytes at the site-data commit that published them: they never change.
                "citeUrl": raw_at(rec_pub, record_url(rec_commit)), "recordCommit": rec_pub,
                "firstVerified": first_verified(ver[2], ver[1]),
                "reproduce": dict(reproduce_check(ver[2], sid), commit=rec_commit),
            },
            # Not a verdict: the latest record verified a file that is no longer on main.
            "formerlyVerified": former if not ver else None,
        })

    # Prerequisites with their current state (#117): `deps` are the steps a proof
    # uses; `background` steps are worth reading first but a proof does not need them.
    state_of = {s["id"]: s["status"] for s in out_steps}
    for s in out_steps:
        s["deps"] = [{"id": d, "status": state_of.get(d, "unknown")} for d in s["deps"]]
        s["background"] = [{"id": d, "status": state_of.get(d, "unknown")} for d in s["background"]]

    out_programs = [{
        "id": p["id"], "title": p["title"], "open": p.get("open") is True,
        "goal": p.get("goal", ""), "wanted": p.get("wanted", ""),
        "count": per_program.get(p["id"], {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0}),
    } for p in tree["programs"]]

    # A proposal's review link is an open pull request that ADDS its lemma file
    # (each open pull's "files", attached by main()); never one whose title mentions it (#115).
    open_by_lemma = {}
    for p in open_pulls:
        for f in p.get("files", []):
            m = CONTRIB_FILE.match(f.get("filename", ""))
            if f.get("status") == "added" and m and m.group(3):
                open_by_lemma.setdefault(int(m.group(3)[1:]), p)
    out_proposals = []
    for i in sorted(proposals, key=lambda i: i.get("created_at") or "", reverse=True):
        if i.get("state") != "open":
            continue
        pr = open_by_lemma.get(i["number"])
        out_proposals.append({
            "id": f"L{i['number']}",
            "title": re.sub(r"^\s*proposal\s*:?\s*", "", i.get("title") or "", flags=re.I) or "(untitled)",
            "user": login(i), "created_at": i.get("created_at") or "", "url": i["html_url"],
            "prUrl": pr["html_url"] if pr else "",
            "submission": statement_card(i["number"]),
        })

    # Mandates: lines of work held by an orchestrator. Outcome labels are set
    # only by the mandate workflow or the maintainer.
    out_mandates = []
    for i in sorted(mandates, key=lambda i: i.get("created_at") or "", reverse=True):
        names = labels(i)
        body = i.get("body") or ""
        if i.get("state") == "open":
            state = "active"
        elif "milestone" in names:
            state = "milestone"
        elif "dead" in names:
            state = "dead"
        else:
            state = "closed"
        program = re.search(r"^\s*Program:\s*([a-z0-9-]+)", body, re.M)
        finding = re.search(r"^FINDING:\s*(.+?)\s*$", body, re.M) if state in ("milestone", "dead") else None
        out_mandates.append({
            "number": i["number"],
            "title": re.sub(r"^\s*mandate\s*:?\s*", "", i.get("title") or "", flags=re.I) or "(untitled)",
            "program": program.group(1) if program else "",
            "user": login(i), "state": state,
            "finding": finding.group(1)[:300] if finding else "",
            "barriers": sorted(n.split(":", 1)[1] for n in names if n.startswith("barrier:")),
            "created_at": i.get("created_at") or "", "closed_at": i.get("closed_at") or "",
            "url": i["html_url"],
        })
    count["mandates"] = sum(1 for m in out_mandates if m["state"] == "active")
    count["milestones"] = sum(1 for m in out_mandates if m["state"] == "milestone")
    count["dead"] = sum(1 for m in out_mandates if m["state"] == "dead")

    out_reports = []
    for i in sorted(reports, key=lambda i: i.get("created_at") or "", reverse=True):
        names = labels(i)
        if i.get("state") == "open":
            verdict = "open"
        elif "confirmed" in names:
            verdict = "confirmed"
        elif "dismissed" in names:
            verdict = "dismissed"
        else:
            verdict = "unresolved"
        title = i.get("title") or ""
        m = REPORT_RE.match(title)
        out_reports.append({
            "number": i["number"], "step": m.group(1).upper() if m else "",
            "summary": REPORT_RE.sub("", title) or "(no summary)",
            "verdict": verdict, "user": login(i),
            "created_at": i.get("created_at") or "", "closed_at": i.get("closed_at") or "",
            "url": i["html_url"],
        })

    out_open = [{
        "title": p.get("title") or "", "user": login(p),
        "created_at": p.get("created_at") or "", "url": p["html_url"],
    } for p in sorted(open_pulls, key=lambda p: p.get("created_at") or "", reverse=True)[:MAX_FEED]]

    out_releases = [{
        "name": r.get("name") or r.get("tag_name") or "", "tag": r.get("tag_name") or "",
        "published_at": r.get("published_at") or "", "body": r.get("body") or "",
        "url": r["html_url"],
    } for r in releases if not r.get("draft")][:30]

    count["proposals"] = len(out_proposals)
    return {
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": count,
        # Verdicts are as of this verified commit; `current` says whether it is main's newest.
        "verification": {
            "available": bool(record), "commit": rec_commit, "verifiedAt": (record or {}).get("verifiedAt", ""),
            "runUrl": rec_run.get("url", ""), "runAttempt": rec_run.get("attempt", 0),
            "record": record_url(rec_commit) if record else "",
            "toolchain": (record or {}).get("evidence", {}).get("toolchain", ""),
            "mathlib": (record or {}).get("evidence", {}).get("mathlib", ""),
            "mainCommit": tree.get("commit", ""), "current": bool(record) and rec_commit == tree.get("commit"),
        },
        # What can be accepted today (#134): proofs and refutations of open steps
        # always; a new statement only once a listed reviewer approves it.
        "accepting": {"proofs": True, "refutations": True, "statementReviewers": len(tree.get("reviewers", []))},
        "openPullCount": len(open_pulls),
        "programs": out_programs,
        "steps": out_steps,
        "people": people,
        "proposals": out_proposals[:MAX_FEED],
        "mandates": out_mandates,
        "barriers": tree.get("barriers", []),
        "openPulls": out_open,
        "reports": out_reports,
        "releases": out_releases,
    }


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    record = json.loads(Path(argv[2]).read_text())
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GH_TOKEN and GITHUB_REPOSITORY must be set", file=sys.stderr)
        return 2
    tree = read_tree()
    # Credit from the commit that added each contribution file (#115).
    added = added_commits(ROOT, [f["path"] for k in ("proofs", "refutations", "lemmaFiles") for f in tree[k].values()])
    previous = json.loads(Path(argv[3]).read_text()) if len(argv) > 3 and Path(argv[3]).is_file() else None

    def author_of(sha):
        c = api_one(f"/commits/{sha}", token, repo)
        name = (c.get("commit", {}).get("author") or {}).get("name", "")
        return (c.get("author") or {}).get("login") or name
    tree["credits"] = resolve_credits(added, lambda sha: api(f"/commits/{sha}/pulls", token, repo), author_of,
                                      previous_credits(previous))
    open_pulls = api("/pulls?state=open", token, repo)
    for p in open_pulls[:MAX_FEED]:
        p["files"] = api(f"/pulls/{p['number']}/files", token, repo)
    status = assemble(
        tree,
        api("/issues?state=all", token, repo),
        [],
        open_pulls,
        api("/releases", token, repo),
        record=record, repo=repo,
    )
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, separators=(",", ":")))
    print(f"wrote {out}: {len(status['steps'])} steps, {status['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
