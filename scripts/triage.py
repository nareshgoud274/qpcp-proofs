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
  - One holder per step and one claimed step per account. The comments are the
    state: each run replays an issue's comments in the order of their own
    timestamps and makes the assignee match, so delayed, simultaneous and
    out-of-order runs agree. The earliest /claim wins.
  - A claim lapses 24 hours after the HOLDER's last comment, judged by the
    comments' own times; /renew is an explicit one. Other people's comments
    do not renew it.
  - Only pull requests into main are acted on, and only while the proof is on
    main. A pull request that is disputed or flagged needs-maintainer, or
    whose step's issue is disputed, is never closed automatically.

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


def step_of(issue):
    m = re.match(r"^(S\d{3,6}|L[1-9]\d{0,8}):", issue.get("title") or "")
    return m.group(1) if m else ""


def is_exercise(sid):
    try:
        steps = json.loads((ROOT / "steps.json").read_text())
    except (OSError, ValueError):
        return False
    return any(s.get("id") == sid and s.get("exercise") is True for s in steps)


def claimed_by(who):
    return [i for i in api("GET", f"issues?state=open&labels=claimed&per_page=100", paginate=True) or []
            if "pull_request" not in i and who in holders(i)]


# ------------------------------------------------------------------ claims
#
# The comments are the state. Each run REPLAYS an issue's comments in the order
# of their own timestamps and works out who holds the step now, then makes the
# issue's assignee match. So a comment's effect depends on when it was written,
# not on when its workflow ran: a /renew written inside the window counts even
# if processed late, a lapsed claim is not revived, and two runs processing
# comments in either order reach the same state.
#
# The one rule that spans issues (one claimed step per account) is recorded in
# the issue itself: when a claim is reverted because the account already holds
# an earlier claim elsewhere, the bot's comment carries `<!-- qpcp:void <id> -->`
# for that /claim comment, and every later replay skips it. Only comments by
# the bot account are read for markers.

BOT = "github-actions[bot]"
VOID = re.compile(r"<!-- qpcp:void (\d+) -->")


def replay(comments, at=None):
    """(holder, claim comment id, {comment id: effect}, [lapsed holders]) as of time `at`."""
    at = now() if at is None else at
    voided = {int(v) for c in comments if c["user"]["login"] == BOT for v in VOID.findall(c.get("body") or "")}
    holder, claim_id, last, effects, lapsed = None, None, None, {}, []
    people = sorted((c for c in comments if c["user"]["login"] != BOT), key=lambda c: (ts(c["created_at"]), c["id"]))
    for c in people:
        t, who, cmd = ts(c["created_at"]), c["user"]["login"], command(c)
        if holder and t - last > LAPSE:
            lapsed.append(holder)
            holder = None
        if who == holder:
            if cmd == "/release":
                holder, effects[c["id"]] = None, "released"
            else:
                last = t  # any comment by the holder renews; /renew and /claim say so explicitly
                effects[c["id"]] = "renewed" if cmd in ("/renew", "/claim") else "activity"
        elif cmd == "/claim":
            if c["id"] in voided:
                effects[c["id"]] = "void"
            elif holder is None:
                holder, claim_id, last, effects[c["id"]] = who, c["id"], t, "claimed"
            else:
                effects[c["id"]] = ("taken", holder, claim_id)
        elif cmd in ("/renew", "/release"):
            effects[c["id"]] = "not-holder"
    if holder and at - last > LAPSE:
        lapsed.append(holder)
        holder = None
    return holder, claim_id, effects, lapsed


def reconcile(n):
    """Make issue n's holder the one its comments say. Returns (holder, claim id, effects, issue)."""
    issue = api("GET", f"issues/{n}")
    cs = comments_of(n)
    if is_exercise(step_of(issue)):
        want, claim_id, effects, lapsed = None, None, {}, []
    else:
        want, claim_id, effects, lapsed = replay(cs)
    have = holders(issue)
    for h in have:
        if h != want:
            api("DELETE", f"issues/{n}/assignees", {"assignees": [h]})
            if h in lapsed:
                comment(n, f"The claim by @{h} had lapsed: no comment from them for 24 hours."
                        + ("" if want else " This step is open again."))
    if want and want not in [a["login"] for a in issue.get("assignees", [])]:
        api("POST", f"issues/{n}/assignees", {"assignees": [want]})
    names = {l["name"] for l in issue.get("labels", [])}
    if want and "claimed" not in names:
        api("POST", f"issues/{n}/labels", {"labels": ["claimed"]})
    if not want and "claimed" in names:
        api("DELETE", f"issues/{n}/labels/claimed", missing_ok=True)
    return want, claim_id, effects, issue


def resolve_account(who):
    """One account, several claimed steps: the earliest current /claim is kept; the
    others are voided in their issues (a marker the replay honours) and released."""
    held = {}
    for i in claimed_by(who):
        holder, claim_id, _, _ = replay(comments_of(i["number"]))
        if holder == who and claim_id is not None:
            held[i["number"]] = claim_id
    if len(held) < 2:
        return
    keep = min(held, key=lambda n: (held[n], n))
    for n in sorted(held):
        if n == keep:
            continue
        cs = comments_of(n)
        if not any(c["user"]["login"] == BOT and f"<!-- qpcp:void {held[n]} -->" in (c.get("body") or "") for c in cs):
            comment(n, f"@{who} already holds #{keep} (claimed first), and one account holds one step at a time, "
                       f"so this claim is reverted. <!-- qpcp:void {held[n]} -->")
        reconcile(n)


def sweep(except_issue=None):
    """Release every claim whose holder has not commented for 24 hours (by the comments' own times)."""
    released = []
    for issue in api("GET", "issues?state=open&labels=claimed&per_page=100", paginate=True) or []:
        n = issue["number"]
        if "pull_request" in issue or n == except_issue:
            continue
        before = holders(issue)
        want, _, _, _ = reconcile(n)
        released += [f"{n}:{h}" for h in before if h != want]
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
    sid = step_of(issue)
    if is_exercise(sid):
        if cmd == "/claim":
            comment(n, f"{sid} is a first-contribution exercise: it needs no claim and is first-come. "
                       "Prepare it, check it in your workspace, and submit it.")
        reconcile(n)
        return "exercise"
    want, _, effects, _ = reconcile(n)
    effect = effects.get(comment_id)
    if effect == "claimed":
        # Another run may have written at the same time: re-read, and apply the account rule.
        resolve_account(who)
        want, _, effects, _ = reconcile(n)
        if want == who:
            comment(n, f"Claimed by @{who}. The claim lapses 24 hours after your last comment here; comment "
                       "`/renew` to restart the clock and `/release` to give it up. Other people's comments do "
                       "not renew it.")
            return "claimed"
        return "superseded"  # a later comment (or an earlier claim elsewhere) decided otherwise
    if effect == "renewed":
        if want == who:
            comment(n, f"Claim renewed for @{who}: the 24-hour clock restarts from this comment's own time.")
            return "renewed"
        return "superseded"
    if effect == "released":
        if want != who:
            comment(n, f"Released by @{who}. This step is open again.")
        return "released"
    if isinstance(effect, tuple) and effect[0] == "taken":
        comment(n, f"@{who}: @{effect[1]} claimed this step first (comment {effect[2]}), so your claim is not "
                   "taken. A claim is a courtesy, not a lock: a correct proof from anyone is not rejected for "
                   "it, but please pick another open step.")
        return "taken"
    if effect == "not-holder" and cmd == "/renew":
        comment(n, f"@{who}: only the holder can renew a claim, and you do not hold this one.")
    return "ignored"


# ------------------------------------------------------------------ pull requests
#
# The authoritative dispute state (one rule, used by both closing paths): a pull
# request is HELD, and never closed automatically, if it carries the `disputed`
# or `needs-maintainer` label, or if its step's issue carries `disputed` (the
# report workflow's label while a report on that step is open). Only pull
# requests into main are acted on, and only while the proof is on main now.

HOLD = {"disputed", FLAG}


def contribution(pr_number):
    files = api("GET", f"pulls/{pr_number}/files?per_page=100", paginate=True) or []
    if len(files) != 1 or files[0].get("status") != "added":
        return None
    m = CONTRIB.match(files[0]["filename"])
    return ("proof" if m.group(1) == "Proofs" else "refutation", m.group(2)) if m else None


def on_main(kind, sid):
    folder = "Proofs" if kind == "proof" else "Refutations"
    return api("GET", f"contents/QPCP/{folder}/{sid}.lean?ref=main", missing_ok=True) is not None


def into_main(pr):
    return (pr.get("base") or {}).get("ref") == "main"


def held(pr, sid):
    """True if the pull request or its step is disputed or flagged for the maintainer."""
    if HOLD & {l["name"] for l in pr.get("labels", [])}:
        return True
    disputed = api("GET", "issues?state=open&labels=disputed&per_page=100", paginate=True) or []
    return any(step_of(i) == sid for i in disputed if "pull_request" not in i)


def build_status():
    import importlib.util
    spec = importlib.util.spec_from_file_location("qpcp_build_status", ROOT / "scripts" / "build_status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def settled_by(kind, sid):
    """The merged pull request into main whose commit ADDED the file now on main, or None.

    The same provenance as the site's credit (build_status.added_commits and
    pick_pull: the latest commit on main's history that added the path), so a
    deleted and re-added file names the pull request that added the current one."""
    bs = build_status()
    folder = "Proofs" if kind == "proof" else "Refutations"
    path = f"QPCP/{folder}/{sid}.lean"
    repo_dir = Path(os.environ.get("QPCP_REPO") or ROOT)
    adding = bs.added_commits(repo_dir, [path]).get(path)
    return bs.pick_pull(api("GET", f"commits/{adding}/pulls")) if adding else None


def flag(n, text):
    pr = api("GET", f"pulls/{n}")
    if FLAG in {l["name"] for l in pr.get("labels", [])}:
        return  # already flagged: no second comment
    api("POST", f"issues/{n}/labels", {"labels": [FLAG]})
    comment(n, text)


def pr_opened(n):
    pr = api("GET", f"pulls/{n}")
    if pr.get("state") != "open" or not into_main(pr):
        return "ignored"
    got = contribution(n)
    if not got:
        return "ignored"
    kind, sid = got
    proved, refuted = on_main("proof", sid), on_main("refutation", sid)
    if kind == "proof" and proved:
        if held(pr, sid):
            return "held"
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
    if not pr.get("merged_at") or not into_main(pr):
        return []
    got = contribution(n)
    if not got or got[0] != "proof":
        return []
    sid = got[1]
    if not on_main("proof", sid):
        return []  # not on main now (for example, deleted since): nothing is settled
    done = []
    for other in api("GET", "pulls?state=open&per_page=100", paginate=True) or []:
        if other["number"] == n or not into_main(other):
            continue
        theirs = contribution(other["number"])
        if theirs == ("proof", sid):
            current = api("GET", f"pulls/{other['number']}")  # re-read just before closing
            if current.get("state") != "open" or held(current, sid):
                done.append(f"held #{other['number']}")
                continue
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
