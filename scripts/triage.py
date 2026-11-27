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
    state: each run replays the comments of ALL step issues in one pass, with
    their closings and reopenings, in the order of their own timestamps, and
    makes every open issue's assignee match. A closing ends a claim for good;
    a reopening allows only a fresh claim. So
    delayed, duplicated, simultaneous and out-of-order runs agree. The earliest
    /claim wins; a /claim by an account already holding a step is not taken.
  - A claim lapses 24 hours after the HOLDER's last comment, judged by the
    comments' own times; /renew is an explicit one. Other people's comments
    do not renew it.
  - Only pull requests into main are acted on, and only while the proof is on
    main. A pull request that is disputed or flagged needs-maintainer, or
    whose step's issue is disputed, is never closed automatically.

Talks to GitHub only through `gh api` (GH_REPO, GH_TOKEN), so the tests can
stand in a fake `gh`. QPCP_NOW (epoch seconds) overrides the clock in tests.
"""

import calendar
import functools
import json
import os
import re
import subprocess
import sys
import time
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
    """Epoch seconds of GitHub's `YYYY-MM-DDTHH:MM:SSZ`."""
    if len(iso) != 20 or iso[4] != "-" or iso[10] != "T" or iso[19] != "Z":
        raise Fault(f"unexpected timestamp {iso!r}")
    return float(calendar.timegm((int(iso[0:4]), int(iso[5:7]), int(iso[8:10]),
                                  int(iso[11:13]), int(iso[14:16]), int(iso[17:19]))))


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


@functools.lru_cache(maxsize=1)
def exercises():
    try:
        steps = json.loads((ROOT / "steps.json").read_text())
    except (OSError, ValueError):
        return frozenset()
    return frozenset(s.get("id") for s in steps if s.get("exercise") is True)


def is_exercise(sid):
    return sid in exercises()


# ------------------------------------------------------------------ claims
#
# The comments are the state, and the state is computed GLOBALLY. Each run
# reads the comments of every step issue and replays all of them in one
# pass, in the order of their own timestamps (ties by comment id, which GitHub
# assigns in creation order). It then makes every issue's assignee match.
#
# One pass over all issues, not a replay per issue, because the one-step-per-
# account rule spans issues: a per-issue replay that voids a claim can hand the
# step to someone whose own account rule it never checked. In the global pass
# both rules are checked at the moment of every /claim, against the state at
# that comment's own time, so every holder the pass introduces satisfies both,
# and the result depends only on the comments and the clock: never on which
# runs happened, in what order, how late, or how often.
#
# At each comment, in time order:
#   - first, every claim whose holder's last comment on that issue is more than
#     24 hours before this comment's time lapses (step and account freed);
#   - the holder's /release frees the step; any other comment by the holder
#     renews it (/renew and /claim say so explicitly);
#   - a /claim by someone else is taken if the step is held, refused if the
#     account already holds another step, and granted otherwise.
# Claims still held are then lapsed as of now. Exercises take no part.
#
# Closing and reopening are events too, read from each issue's own event history
# and replayed in the same time order. A closing ends the step's claim
# permanently: the holder is free from that moment. While an issue is closed its
# comments count for nothing. A reopening only makes the step available for a
# FRESH /claim; it never revives a claim that a closing ended. So closing or
# reopening an issue never changes what was decided, before it, on any issue.
#
# ORDER (one policy, `order_key`, used by transitions_of and by compute):
#   - Timestamps have one-second resolution, so time alone cannot order events.
#   - Closings and reopenings of one issue keep their REAL sequence: GitHub's
#     event id, which increases in creation order. They are never ordered by
#     their names or kinds. (Without ids, the API's own order is kept.)
#   - Comments keep their order by comment id.
#   - A comment and a transition in the same second are genuinely ambiguous:
#     their ids come from different sequences and cannot be compared. Policy:
#     all transitions of that second come first, then its comments. A comment is
#     judged against the issue's state at the end of its second. Why: GitHub's
#     "close with comment" and "reopen and comment" put a comment and a
#     transition in the same second. A comment that closes the issue makes no
#     difference either way (the closing ends any claim). A /claim that comes
#     with a reopening, which is what a person reopening and claiming means,
#     counts.
# After the replay, each issue's replayed state (open or closed) must agree with
# its observed state. A mismatch is a fault naming the issue, never a silent
# result.
#
# After writing, a run reads everything again and repeats until a read needs no
# write, so a run that read before a later comment existed does not leave its
# stale view behind. Replies carry `<!-- qpcp:re <comment id> -->`, so a
# comment processed twice is answered once.

BOT = "github-actions[bot]"
RE = "<!-- qpcp:re {} -->"


TRANSITION, COMMENT = 0, 1  # within one second: transitions (in their sequence), then comments


def order_key(t, phase, seq):
    """THE ordering of replayed events: time, then transitions before comments in the same
    second, then each one's own sequence (event id, or comment id)."""
    return (t, phase, seq)


def compute(comments_by_issue, at=None, transitions=None, observed=None):
    """Claim state from the comments and the issues' close/reopen history.

    `transitions`: {issue: [(time, sequence, "closed" | "reopened"), ...]}. `observed`: {issue:
    "open" | "closed"}, checked against the replayed state. Returns (holder by issue, {comment
    id: effect}, {issue: [accounts whose claim lapsed]}, {comment id: the claim it made or
    renewed}, {issue: the claim holding it now})."""
    at = now() if at is None else at
    transitions = transitions or {}
    events = [(order_key(ts(c["created_at"]), COMMENT, c["id"]), n, c, None)
              for n, cs in comments_by_issue.items() for c in cs if c["user"]["login"] != BOT]
    events += [(order_key(t, TRANSITION, seq), n, None, kind)
               for n, tr in transitions.items() for t, seq, kind in tr]
    events.sort(key=lambda e: e[0])
    closed_now = set()
    holder, last, claim_id, owns, effects, of_claim = {}, {}, {}, {}, {}, {}
    lapsed = {n: [] for n in comments_by_issue}

    def expire(t):
        for n in sorted(holder):
            if t - last[n] > LAPSE:
                lapsed[n].append(holder[n])
                del owns[holder[n]], holder[n], last[n], claim_id[n]

    for key, n, c, kind in events:
        t = key[0]
        expire(t)
        if kind == "closed":
            closed_now.add(n)
            if n in holder:  # the step is closed: its claim ends for good, and the account is free
                del owns[holder[n]], holder[n], last[n], claim_id[n]
            continue
        if kind == "reopened":
            closed_now.discard(n)  # open for a fresh claim; nothing is revived
            continue
        if n in closed_now:
            continue  # a comment on a closed issue counts for nothing
        cid = c["id"]
        who, cmd = c["user"]["login"], command(c)
        if holder.get(n) == who:
            if cmd == "/release":
                effects[cid] = "released"
                del owns[who], holder[n], last[n], claim_id[n]
            else:
                last[n] = t
                effects[cid] = "renewed" if cmd in ("/renew", "/claim") else "activity"
                of_claim[cid] = claim_id[n]
        elif cmd == "/claim":
            if n in holder:
                effects[cid] = ("taken", holder[n], claim_id[n])
            elif who in owns:
                effects[cid] = ("holds", owns[who])
            else:
                holder[n], last[n], claim_id[n], owns[who] = who, t, cid, n
                effects[cid] = "claimed"
                of_claim[cid] = cid
        elif cmd in ("/renew", "/release"):
            effects[cid] = "not-holder"
    expire(at)
    for n, state in sorted((observed or {}).items()):
        replayed = "closed" if n in closed_now else "open"
        if replayed != state:
            raise Fault(f"#{n}: its close/reopen history replays to {replayed}, but the issue is {state}")
    return holder, effects, lapsed, of_claim, claim_id


def step_issues():
    """Step issues, open and closed, that take part in claims (not exercises)."""
    out = []
    for i in api("GET", "issues?state=all&labels=step&per_page=100", paginate=True) or []:
        if "pull_request" in i:
            continue
        sid = step_of(i)
        if sid and not is_exercise(sid):
            out.append(i)
    return out


def transitions_of(issue):
    """The issue's closings and reopenings as [(time, sequence, kind)], in `order_key` order,
    from its own event history. The sequence is GitHub's event id (the API's own order if any
    event lacks one). If the history has not caught up with the issue's state yet, the state is
    taken as starting now (at the latest), after every recorded event."""
    n = issue["number"]
    raw = [e for e in api("GET", f"issues/{n}/events?per_page=100", paginate=True) or []
           if e.get("event") in ("closed", "reopened")]
    by_id = all(isinstance(e.get("id"), int) for e in raw)
    out = sorted(((ts(e["created_at"]), e["id"] if by_id else k, e["event"]) for k, e in enumerate(raw)),
                 key=lambda x: order_key(x[0], TRANSITION, x[1]))
    shown = out[-1][2] if out else "reopened"
    nxt = max([s for _, s, _ in out], default=0) + 1
    latest = max([t for t, _, _ in out], default=0)
    if issue.get("state") == "closed" and shown != "closed":
        at = ts(issue["closed_at"]) if issue.get("closed_at") else now()
        out.append((max(at, latest), nxt, "closed"))
    elif issue.get("state") == "open" and shown == "closed":
        out.append((max(now(), latest), nxt, "reopened"))
    return out


def read_all():
    """(open issues, comments by issue, {issue: closings and reopenings}). An issue listed with no
    comments is not fetched: with no comments it holds no claim, whatever its history."""
    issues, cs, tr, seen = {}, {}, {}, {}
    for i in step_issues():
        n = i["number"]
        if i.get("state") == "open":
            issues[n] = i
        if i.get("comments") == 0:
            continue
        cs[n] = comments_of(n)
        tr[n] = transitions_of(i)
        seen[n] = "closed" if i.get("state") == "closed" else "open"
    for n in issues:
        cs.setdefault(n, [])
    return issues, cs, tr, seen


def apply(issue, want, lapsed):
    """Make one issue's assignee and label match `want`. True if anything was written."""
    n, wrote = issue["number"], False
    have = sorted(a["login"] for a in issue.get("assignees", []))
    for h in have:
        if h != want:
            api("DELETE", f"issues/{n}/assignees", {"assignees": [h]})
            wrote = True
            if h in lapsed:
                comment(n, f"The claim by @{h} had lapsed: no comment from them for 24 hours."
                        + ("" if want else " This step is open again."))
    if want and want not in have:
        api("POST", f"issues/{n}/assignees", {"assignees": [want]})
        wrote = True
    names = {l["name"] for l in issue.get("labels", [])}
    if want and "claimed" not in names:
        api("POST", f"issues/{n}/labels", {"labels": ["claimed"]})
        wrote = True
    if not want and "claimed" in names:
        api("DELETE", f"issues/{n}/labels/claimed", missing_ok=True)
        wrote = True
    return wrote


def settle(rounds=5):
    """Compute the global claim state and write it, re-reading until a read needs no write.
    Returns (holder by issue, effects, comments by issue, issues as last read, released,
    {comment id: the claim it made or renewed}, {issue: the claim holding it now})."""
    released = []
    for _ in range(rounds):
        issues, cs, tr, seen = read_all()
        holder, effects, lapsed, of_claim, current = compute(cs, transitions=tr, observed=seen)
        wrote = False
        for n in sorted(issues):
            before = holders(issues[n])
            if apply(issues[n], holder.get(n), lapsed[n]):
                wrote = True
                released += [f"{n}:{h}" for h in before if h != holder.get(n)]
        if not wrote:
            return holder, effects, cs, issues, released, of_claim, current
    raise Fault(f"claim state did not settle in {rounds} rounds")


def sweep():
    """Release every claim whose holder has not commented for 24 hours (by the comments' own times)."""
    return settle()[4]


def reply(n, cs, comment_id, text):
    """Answer comment `comment_id` once, however often it is processed."""
    mark = RE.format(comment_id)
    if any(c["user"]["login"] == BOT and mark in (c.get("body") or "") for c in cs):
        return
    comment(n, f"{text} {mark}")


def claim_comment(n, comment_id):
    issue = api("GET", f"issues/{n}")
    cs = comments_of(n)
    c = next((x for x in cs if x["id"] == comment_id), None)
    if c is None:
        raise Fault(f"no comment {comment_id} on #{n}")
    who, cmd = c["user"]["login"], command(c)
    if issue.get("state") != "open" or not cmd:
        settle()
        return "ignored"
    sid = step_of(issue)
    if is_exercise(sid):
        if cmd == "/claim":
            reply(n, cs, comment_id, f"{sid} is a first-contribution exercise: it needs no claim and is "
                  "first-come. Prepare it, check it in your workspace, and submit it.")
        apply(issue, None, [])
        settle()
        return "exercise"
    holder, effects, all_cs, _, _, of_claim, current = settle()
    cs = all_cs.get(n, cs)
    want, effect = holder.get(n), effects.get(comment_id)
    # Still in force only if the claim it made or renewed is the one holding the step now
    # (not an earlier claim of the same account, ended by a closing or a release).
    live = comment_id in of_claim and current.get(n) == of_claim[comment_id]
    if effect == "claimed":
        if live:
            reply(n, cs, comment_id, f"Claimed by @{who}. The claim lapses 24 hours after your last comment "
                  "here; comment `/renew` to restart the clock and `/release` to give it up. Other people's "
                  "comments do not renew it.")
            return "claimed"
        return "superseded"  # a later comment decided otherwise (a /release, or the claim lapsed)
    if effect == "renewed":
        if live:
            reply(n, cs, comment_id, f"Claim renewed for @{who}: the 24-hour clock restarts from this "
                  "comment's own time.")
            return "renewed"
        return "superseded"
    if effect == "released":
        if want != who:
            reply(n, cs, comment_id, f"Released by @{who}. This step is open again.")
        return "released"
    if isinstance(effect, tuple) and effect[0] == "taken":
        reply(n, cs, comment_id, f"@{who}: @{effect[1]} claimed this step first (comment {effect[2]}), so "
              "your claim is not taken. A claim is a courtesy, not a lock: a correct proof from anyone is "
              "not rejected for it, but please pick another open step.")
        return "taken"
    if isinstance(effect, tuple) and effect[0] == "holds":
        reply(n, cs, comment_id, f"@{who} already holds #{effect[1]} (claimed first), and one account holds "
              "one step at a time, so this claim is not taken. `/release` that one first.")
        return "holds-other"
    if effect == "not-holder" and cmd == "/renew":
        reply(n, cs, comment_id, f"@{who}: only the holder can renew a claim, and you do not hold this one.")
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
            # Re-read just before closing, and never ignore a change it shows: closed, retargeted
            # away from main, or held are skipped; a new head means its files are read again.
            current = api("GET", f"pulls/{other['number']}")
            if current.get("state") != "open" or not into_main(current):
                done.append(f"changed #{other['number']}")
                continue
            if (current.get("head") or {}).get("sha") != (other.get("head") or {}).get("sha") \
                    and contribution(other["number"]) != ("proof", sid):
                done.append(f"changed #{other['number']}")
                continue
            if held(current, sid):
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
