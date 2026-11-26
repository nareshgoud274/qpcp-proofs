#!/usr/bin/env python3
"""Claims on step issues, and pull requests for settled steps (#116, #117).

    triage.py claim-comment <issue> <comment-id>
        claim.yml: handles /claim, /renew and /release in that comment.
    triage.py sweep
        expire-claims.yml (and every /claim): releases each holder whose own
        last comment on the issue is more than 24 hours old.
    triage.py pr-opened <pr>
        triage.yml: a pull request that adds a proof of a step already
        settled on main by a proof is closed, naming the pull request that
        settled it. A refutation, or a proof of a refuted step, is never
        closed: it is flagged for the maintainer.
    triage.py pr-merged <pr>
        triage.yml: when a PROOF merges, other open pull requests that add a
        proof of the same step are closed as confirmed duplicates, naming the
        merged one. Refutations of that step are flagged, never closed.

Rules (JOIN.md, "Claims"):
  - A claim is a courtesy, not a lock. Exercises need no claim.
  - One holder per step and one claimed step per account. Two runs can write
    at once (GitHub keeps only one pending run per concurrency group, so the
    claim workflow has none): after writing, each run re-reads and resolves
    conflicts the same way, so they agree. The earliest current /claim
    comment wins; the loser is reverted with a comment.
  - A claim lapses 24 hours after the HOLDER's last comment on the issue;
    /renew is an explicit one. Other people's comments do not renew it.

Talks to GitHub only through `gh api` (GH_REPO, GH_TOKEN), so the tests can
stand in a fake `gh`. QPCP_NOW (epoch seconds) overrides the clock in tests.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAPSE = 24 * 3600
COMMANDS = ("/claim", "/renew", "/release")
CONTRIB = re.compile(r"^QPCP/(Proofs|Refutations)/(S\d{3,6}|L[1-9]\d{0,8})\.lean$")
FLAG = "needs-maintainer"


class Fault(Exception):
    pass


def repo():
    r = os.environ.get("GH_REPO")
    if not r:
        raise Fault("GH_REPO is not set")
    return r


def api(method, path, body=None, paginate=False, missing_ok=False):
    args = ["gh", "api", "-X", method, f"repos/{repo()}/{path}"]
    if paginate:
        args += ["--paginate", "--slurp"]
    if body is not None:
        args += ["--input", "-"]
    r = subprocess.run(args, input=json.dumps(body) if body is not None else None, capture_output=True, text=True)
    if r.returncode != 0:
        if missing_ok and ("404" in r.stderr or "Not Found" in r.stderr):
            return None
        raise Fault(f"gh api {method} {path}: {r.stderr.strip()[:200]}")
    out = r.stdout.strip()
    if not out:
        return None
    data = json.loads(out)
    if paginate:
        return [x for page in data for x in page]
    return data


def now():
    return float(os.environ.get("QPCP_NOW") or time.time())


def ts(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def comment(issue, text):
    api("POST", f"issues/{issue}/comments", {"body": text})


def holders(issue):
    if "claimed" not in {l["name"] for l in issue.get("labels", [])}:
        return []
    return sorted(a["login"] for a in issue.get("assignees", []))


def comments_of(n):
    return api("GET", f"issues/{n}/comments?per_page=100", paginate=True) or []


def command(c):
    first = (c.get("body") or "").strip().splitlines()[:1]
    word = first[0].split()[0] if first and first[0].split() else ""
    return word if word in COMMANDS else ""


def current_claim(comments, who):
    """The comment id of `who`'s latest /claim on this issue (their current attempt)."""
    ids = [c["id"] for c in comments if c["user"]["login"] == who and command(c) == "/claim"]
    return max(ids) if ids else None


def step_of(issue):
    m = re.match(r"^(S\d{3,6}|L[1-9]\d{0,8}):", issue.get("title") or "")
    return m.group(1) if m else ""


def is_exercise(sid):
    try:
        steps = json.loads((ROOT / "steps.json").read_text())
    except (OSError, ValueError):
        return False
    return any(s.get("id") == sid and s.get("exercise") is True for s in steps)


def unassign(n, who, remaining):
    api("DELETE", f"issues/{n}/assignees", {"assignees": [who]})
    if not remaining:
        api("DELETE", f"issues/{n}/labels/claimed", missing_ok=True)


def claimed_by(who):
    return [i for i in api("GET", f"issues?state=open&labels=claimed&per_page=100", paginate=True) or []
            if "pull_request" not in i and who in holders(i)]


# ------------------------------------------------------------------ claims

def resolve_issue(n):
    """More than one holder: the earliest current /claim wins; the others are reverted."""
    issue = api("GET", f"issues/{n}")
    hs = holders(issue)
    if len(hs) < 2:
        return
    cs = comments_of(n)
    order = sorted(hs, key=lambda h: (current_claim(cs, h) is None, current_claim(cs, h) or 0, h))
    winner = order[0]
    for loser in order[1:]:
        if loser in holders(api("GET", f"issues/{n}")):  # re-read: another run may have done it
            unassign(n, loser, True)
            comment(n, f"@{loser}: @{winner} claimed this step first (comment {current_claim(cs, winner)}), "
                       "so your claim is reverted. A claim is a courtesy, not a lock: you may still submit, "
                       "but please pick another open step.")


def resolve_account(who):
    """One account, several claimed steps: the earliest current /claim is kept."""
    held = claimed_by(who)
    if len(held) < 2:
        return
    first = {i["number"]: current_claim(comments_of(i["number"]), who) for i in held}
    keep = min(first, key=lambda n: (first[n] is None, first[n] or 0, n))
    for n in sorted(first):
        if n == keep:
            continue
        issue = api("GET", f"issues/{n}")
        if who in holders(issue):
            unassign(n, who, [h for h in holders(issue) if h != who])
            comment(n, f"@{who} already holds #{keep} (claimed first), and one account holds one step at a "
                       "time, so this claim is reverted.")


def sweep(except_issue=None):
    """Release every holder whose own last comment on the issue is over 24 hours old."""
    released = []
    for issue in api("GET", "issues?state=open&labels=claimed&per_page=100", paginate=True) or []:
        n = issue["number"]
        if "pull_request" in issue or n == except_issue:
            continue
        hs = holders(issue)
        cs = comments_of(n)
        for h in hs:
            mine = [ts(c["created_at"]) for c in cs if c["user"]["login"] == h]
            last = max(mine) if mine else ts(issue["created_at"])
            if last < now() - LAPSE:
                rest = [x for x in holders(api("GET", f"issues/{n}")) if x != h]
                unassign(n, h, rest)
                comment(n, f"The claim by @{h} lapsed: no comment from them for 24 hours. "
                           + ("This step is open again." if not rest else ""))
                released.append(f"{n}:{h}")
    return released


def claim_comment(n, comment_id):
    sweep(except_issue=n)
    cs = comments_of(n)
    c = next((x for x in cs if x["id"] == comment_id), None)
    if c is None:
        raise Fault(f"no comment {comment_id} on #{n}")
    who, cmd = c["user"]["login"], command(c)
    issue = api("GET", f"issues/{n}")
    if issue.get("state") != "open" or not cmd:
        return "ignored"
    hs = holders(issue)
    sid = step_of(issue)
    # This issue's holders are judged by their comments BEFORE this one, so a late
    # /renew or /claim cannot revive a claim that had already lapsed.
    for h in list(hs):
        before = [ts(x["created_at"]) for x in cs if x["user"]["login"] == h and x["id"] != comment_id]
        last = max(before) if before else ts(issue["created_at"])
        if last < now() - LAPSE and not (h == who and cmd == "/release"):
            hs = [x for x in hs if x != h]
            unassign(n, h, hs)
            comment(n, f"The claim by @{h} had lapsed: no comment from them for 24 hours.")
    if cmd == "/release":
        if who in hs:
            unassign(n, who, [h for h in hs if h != who])
            comment(n, f"Released by @{who}. This step is open again.")
            return "released"
        return "ignored"
    if cmd == "/renew":
        if who in hs:
            comment(n, f"Claim renewed for @{who}: the 24-hour clock restarts from this comment.")
            return "renewed"
        comment(n, f"@{who}: only the holder can renew a claim, and you do not hold this one.")
        return "ignored"
    # /claim
    if is_exercise(sid):
        comment(n, f"{sid} is a first-contribution exercise: it needs no claim and is first-come. "
                   "Prepare it, check it in your workspace, and submit it.")
        return "exercise"
    if who in hs:
        comment(n, f"Claim renewed for @{who}.")
        return "renewed"
    if hs:
        comment(n, f"This step is already claimed by @{', @'.join(hs)}. A claim is a courtesy, not a lock: "
                   "a correct proof from anyone is not rejected for it, but please pick another open step.")
        return "taken"
    if claimed_by(who):
        comment(n, f"@{who} already holds a claimed step. Finish it or comment `/release` there first.")
        return "refused"
    api("POST", f"issues/{n}/assignees", {"assignees": [who]})
    api("POST", f"issues/{n}/labels", {"labels": ["claimed"]})
    # Another run may have written at the same time: re-read and resolve, the same way it will.
    resolve_issue(n)
    resolve_account(who)
    if who in holders(api("GET", f"issues/{n}")):
        comment(n, f"Claimed by @{who}. The claim lapses 24 hours after your last comment here; comment "
                   "`/renew` to restart the clock and `/release` to give it up. Other people's comments do "
                   "not renew it.")
        return "claimed"
    return "lost"


# ------------------------------------------------------------------ pull requests

def contribution(pr_number):
    files = api("GET", f"pulls/{pr_number}/files?per_page=100", paginate=True) or []
    if len(files) != 1 or files[0].get("status") != "added":
        return None
    m = CONTRIB.match(files[0]["filename"])
    return ("proof" if m.group(1) == "Proofs" else "refutation", m.group(2)) if m else None


def on_main(kind, sid):
    folder = "Proofs" if kind == "proof" else "Refutations"
    return api("GET", f"contents/QPCP/{folder}/{sid}.lean?ref=main", missing_ok=True) is not None


def settled_by(kind, sid):
    """The merged pull request whose commit added the file on main, or None (never a guess from titles)."""
    folder = "Proofs" if kind == "proof" else "Refutations"
    commits = api("GET", f"commits?sha=main&path=QPCP/{folder}/{sid}.lean&per_page=100", paginate=True) or []
    if not commits:
        return None
    adding = commits[-1]["sha"]  # newest first: the last one added it
    pulls = [p for p in api("GET", f"commits/{adding}/pulls") or []
             if p.get("merged_at") and (p.get("base") or {}).get("ref") == "main"]
    return min(pulls, key=lambda p: p["merged_at"]) if pulls else None


def flag(n, text):
    api("POST", f"issues/{n}/labels", {"labels": [FLAG]})
    comment(n, text)


def pr_opened(n):
    pr = api("GET", f"pulls/{n}")
    if pr.get("state") != "open":
        return "ignored"
    got = contribution(n)
    if not got:
        return "ignored"
    kind, sid = got
    proved, refuted = on_main("proof", sid), on_main("refutation", sid)
    if kind == "proof" and proved:
        by = settled_by("proof", sid)
        ref = f"#{by['number']}" if by else "a commit with no pull request"
        comment(n, f"{sid} is already settled by {ref}: `QPCP/Proofs/{sid}.lean` is on main. Closing this "
                   "pull request as a duplicate. If you believe the merged proof or the statement is wrong, "
                   "open a report issue (`Report " + sid + ": ...`).")
        api("PATCH", f"pulls/{n}", {"state": "closed"})
        return "closed"
    if proved or refuted:
        other = "a proof" if proved else "a refutation"
        flag(n, f"Flagged for the maintainer: this {kind} of {sid} conflicts with {other} already on main. "
                "Refutations and disputed results are never closed automatically.")
        return "flagged"
    return "ignored"


def pr_merged(n):
    pr = api("GET", f"pulls/{n}")
    if not pr.get("merged_at"):
        return []
    got = contribution(n)
    if not got or got[0] != "proof":
        return []
    sid = got[1]
    done = []
    for other in api("GET", "pulls?state=open&per_page=100", paginate=True) or []:
        if other["number"] == n:
            continue
        theirs = contribution(other["number"])
        if theirs == ("proof", sid):
            comment(other["number"], f"Closed as a confirmed duplicate: #{n}, a proof of {sid}, has merged. "
                                     "Thank you; if yours takes a different route worth keeping, say so here.")
            api("PATCH", f"pulls/{other['number']}", {"state": "closed"})
            done.append(f"closed #{other['number']}")
        elif theirs == ("refutation", sid):
            flag(other["number"], f"Flagged for the maintainer: #{n}, a proof of {sid}, has merged while this "
                                  "refutation is open. It is not closed automatically.")
            done.append(f"flagged #{other['number']}")
    return done


def main(argv):
    try:
        if len(argv) == 4 and argv[1] == "claim-comment":
            print(claim_comment(int(argv[2]), int(argv[3])))
        elif len(argv) == 2 and argv[1] == "sweep":
            print("\n".join(sweep()) or "nothing lapsed")
        elif len(argv) == 3 and argv[1] == "pr-opened":
            print(pr_opened(int(argv[2])))
        elif len(argv) == 3 and argv[1] == "pr-merged":
            print("\n".join(pr_merged(int(argv[2]))) or "nothing to close")
        else:
            print(__doc__)
            return 2
        return 0
    except Fault as e:
        print(f"FAULT: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
