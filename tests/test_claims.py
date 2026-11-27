#!/usr/bin/env python3
"""Claims and settled-step pull requests (scripts/triage.py) against a stand-in gh. No network.

    python3 -I tests/test_claims.py

  1. Two simultaneous /claim comments on one step: both runs read it
     unclaimed and both write; exactly one holder remains (the earlier
     comment), and the other is reverted with a comment.
  2. One account claims two steps at once: it ends up holding one (the
     earlier claim); the other is reverted.
  3. The clock runs from the HOLDER's last comment: an unrelated comment by
     someone else does not renew; the holder's own comment does; /renew is
     explicit; a late /renew cannot revive a lapsed claim; only the holder
     can renew.
  4. An exercise needs no claim: /claim on it assigns nobody.
  5. A proof for a step already proved on main is closed, naming the pull
     request that settled it (from the commit that added the file).
  6. A refutation of a proved step is kept open and flagged.
  7. When a proof merges, a late duplicate proof is closed naming it, and an
     open refutation of that step is flagged, not closed. Two open proofs of
     an unsettled step are both left open (never closed for arriving second).
  8. (#158 review) A merge into another branch (staging) closes nothing; a
     merge whose proof is no longer on main closes nothing; a pull request
     into another branch is not acted on when opened.
  9. (#158 review) The dispute state holds in both closing paths: a pull
     request labelled disputed or needs-maintainer, or one whose step's issue
     is disputed, is never closed automatically.
 10. (#158 review) A proof deleted and added again ([new add, deletion, old
     add] on main) is "settled by" the pull request that added the current
     file, from the same provenance code as the site's credit.
 11. (#158 review) Timeliness comes from a comment's own time: a /renew
     written five minutes before expiry and processed five minutes after it
     renews; two comments processed in reverse order end as if processed in
     order (a /claim then /release leaves no holder; of two /claims, the
     earlier wins).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
NOW = 1_800_000_000  # a fixed clock
H = 3600


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:600]}"))


def iso(t):
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def issue(n, title, labels=("step",), assignees=(), comments=()):
    return {"number": n, "title": title, "state": "open", "created_at": iso(NOW - 100 * H),
            "labels": [{"name": l} for l in labels], "assignees": [{"login": a} for a in assignees],
            "comments": [{"id": cid, "user": {"login": who}, "body": body, "created_at": iso(t)}
                         for cid, who, body, t in comments]}


class Env:
    def __init__(self, base, state):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        self.state = base / "state.json"
        self.state.write_text(json.dumps(state))
        b = base / "bin"
        b.mkdir(exist_ok=True)
        (b / "gh").write_text(f"#!/bin/sh\nexec {sys.executable} -I {ROOT / 'tests' / 'fake_gh.py'} \"$@\"\n")
        (b / "gh").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", GH_REPO="o/r", GH_TOKEN="x",
                        FAKE_GH_STATE=str(self.state), QPCP_NOW=str(NOW))

    def run(self, *args, extra=None):
        return subprocess.Popen([sys.executable, "-I", str(ROOT / "scripts" / "triage.py"), *map(str, args)],
                                env=dict(self.env, **(extra or {})), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def call(self, *args):
        p = self.run(*args)
        out, err = p.communicate(timeout=60)
        return out.strip(), err

    def together(self, *calls):
        """Run several triage.py calls at once, each held at its first write until all have reached theirs."""
        bar = Path(tempfile.mkdtemp(dir=self.base))
        procs = [self.run(*c, extra={"FAKE_GH_BARRIER": str(bar), "FAKE_GH_BARRIER_N": str(len(calls)),
                                     "FAKE_GH_RUN": f"run{i}"}) for i, c in enumerate(calls)]
        return [p.communicate(timeout=60) for p in procs]

    def get(self):
        return json.loads(self.state.read_text())


def holders(st, n):
    i = st["issues"][str(n)]
    return sorted(a["login"] for a in i["assignees"]) if "claimed" in [l["name"] for l in i["labels"]] else []


def bot_says(st, n):
    return [c["body"] for c in st["issues"][str(n)]["comments"] if c["user"]["login"] == "github-actions[bot]"]


def main():
    print("Claims and settled-step pull requests")
    base = Path(tempfile.mkdtemp(prefix="qpcp-claims-"))
    try:
        exercise = next(s["id"] for s in json.loads((ROOT / "steps.json").read_text()) if s.get("exercise"))
        regular = next(s["id"] for s in json.loads((ROOT / "steps.json").read_text()) if not s.get("exercise"))

        # 1. Two simultaneous /claim comments.
        e = Env(base / "c1", {"issues": {"61": issue(61, f"{regular}: x", comments=[
            (10, "alice", "/claim", NOW - 60), (11, "bob", "/claim", NOW - 59)])}})
        outs = e.together(("claim-comment", 61, 10), ("claim-comment", 61, 11))
        st = e.get()
        check("1. two simultaneous claims leave exactly one holder: the earlier comment's", holders(st, 61) == ["alice"],
              (holders(st, 61), outs))
        check("1. the loser is reverted with a comment naming the winner",
              any("@bob: @alice claimed this step first" in b for b in bot_says(st, 61)), bot_says(st, 61))
        check("1. both runs wrote (they really were simultaneous)",
              sum(1 for m, p, b in st["log"] if m == "POST" and p.endswith("/assignees")) == 2, st["log"])

        # 2. One account, two steps at once.
        e = Env(base / "c2", {"issues": {
            "62": issue(62, "S900062: x", comments=[(20, "alice", "/claim", NOW - 60)]),
            "63": issue(63, "S900063: x", comments=[(21, "alice", "/claim", NOW - 59)])}})
        e.together(("claim-comment", 62, 20), ("claim-comment", 63, 21))
        st = e.get()
        check("2. one account never holds two steps: it keeps the earlier claim",
              holders(st, 62) == ["alice"] and holders(st, 63) == [], (holders(st, 62), holders(st, 63)))
        check("2. the other is reverted with a comment", any("already holds #62" in b for b in bot_says(st, 63)), bot_says(st, 63))

        # 3. The clock runs from the holder's last comment.
        e = Env(base / "c3", {"issues": {
            "64": issue(64, "S900064: x", ("step", "claimed"), ["alice"],
                        [(30, "alice", "/claim", NOW - 30 * H), (31, "carol", "Nice step, any hints?", NOW - 1 * H)]),
            "65": issue(65, "S900065: x", ("step", "claimed"), ["dave"],
                        [(40, "dave", "/claim", NOW - 30 * H), (41, "dave", "Working on the n = 0 case.", NOW - 10 * H)])}})
        out, _ = e.call("sweep")
        st = e.get()
        check("3. an unrelated comment by someone else does not renew: alice's claim lapses",
              holders(st, 64) == [] and "64:alice" in out, (holders(st, 64), out))
        check("3. the holder's own comment renews: dave keeps his", holders(st, 65) == ["dave"], holders(st, 65))
        e = Env(base / "c3b", {"issues": {
            "66": issue(66, "S900066: x", ("step", "claimed"), ["erin"],
                        [(50, "erin", "/claim", NOW - 20 * H), (51, "erin", "/renew", NOW - 10)]),
            "67": issue(67, "S900067: x", ("step", "claimed"), ["fay"],
                        [(60, "fay", "/claim", NOW - 30 * H), (61, "fay", "/renew", NOW - 10)]),
            "68": issue(68, "S900068: x", ("step", "claimed"), ["gus"],
                        [(70, "gus", "/claim", NOW - 2 * H), (71, "hal", "/renew", NOW - 10)])}})
        r66, _ = e.call("claim-comment", 66, 51)
        r67, _ = e.call("claim-comment", 67, 61)
        r68, _ = e.call("claim-comment", 68, 71)
        st = e.get()
        check("3. /renew by the holder renews", r66 == "renewed" and holders(st, 66) == ["erin"], (r66, holders(st, 66)))
        check("3. a late /renew cannot revive a claim that had lapsed",
              holders(st, 67) == [] and any("had lapsed" in b for b in bot_says(st, 67)), (r67, holders(st, 67)))
        check("3. only the holder can renew", r68 == "ignored" and holders(st, 68) == ["gus"], (r68, holders(st, 68)))

        # 4. An exercise needs no claim.
        e = Env(base / "c4", {"issues": {"61": issue(61, f"{exercise}: x", comments=[(80, "ivy", "/claim", NOW - 5)])}})
        r, _ = e.call("claim-comment", 61, 80)
        st = e.get()
        check(f"4. /claim on the exercise {exercise} assigns nobody and says no claim is needed",
              r == "exercise" and holders(st, 61) == [] and any("needs no claim" in b for b in bot_says(st, 61)), (r, bot_says(st, 61)))

        # 5-10. Pull requests. Main's history is a real Git repository (QPCP_REPO), as in triage.yml's checkout.
        main_repo = base / "main-repo"
        main_repo.mkdir()
        def git(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "-c", "commit.gpgsign=false",
                                   "-C", str(main_repo), *a], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q", "-b", "main")
        (main_repo / "QPCP" / "Proofs").mkdir(parents=True)
        f30 = main_repo / "QPCP" / "Proofs" / "S900030.lean"
        f30.write_text("old proof\n")
        git("add", "-A"); git("commit", "-q", "-m", "old add")
        old_add = git("rev-parse", "HEAD")
        git("rm", "-q", str(f30.relative_to(main_repo))); git("commit", "-q", "-m", "deletion")
        f30.parent.mkdir(parents=True, exist_ok=True)  # git rm took the empty folder
        f30.write_text("new proof\n")
        (main_repo / "QPCP" / "Proofs" / "S900031.lean").write_text("x\n")
        git("add", "-A"); git("commit", "-q", "-m", "new add")
        new_add = git("rev-parse", "HEAD")

        def pr(n, path, state="open", merged_at=None, user="x", base_ref="main", labels=()):
            return {"number": n, "state": state, "merged_at": merged_at, "user": {"login": user},
                    "base": {"ref": base_ref}, "labels": [{"name": l} for l in labels],
                    "files": [{"filename": path, "status": "added"}]}
        pulls = {
            "200": pr(200, "QPCP/Proofs/S900031.lean", "closed", "2026-11-27T00:00:00Z"),
            "201": pr(201, "QPCP/Proofs/S900031.lean"),
            "202": pr(202, "QPCP/Refutations/S900031.lean"),
            "203": pr(203, "QPCP/Proofs/S900030.lean"),
            "204": pr(204, "QPCP/Refutations/S900030.lean"),
            "205": pr(205, "QPCP/Proofs/S900032.lean"),
            "206": pr(206, "QPCP/Proofs/S900032.lean"),
            # 8. other branches, and a proof no longer on main
            "210": pr(210, "QPCP/Proofs/S900033.lean", "closed", "2026-11-27T00:00:00Z", base_ref="staging"),
            "211": pr(211, "QPCP/Proofs/S900033.lean"),
            "212": pr(212, "QPCP/Proofs/S900030.lean", base_ref="staging"),
            "213": pr(213, "QPCP/Proofs/S900034.lean", "closed", "2026-11-27T00:00:00Z"),
            "214": pr(214, "QPCP/Proofs/S900034.lean"),
            # 9. held: labelled, or its step's issue disputed
            "220": pr(220, "QPCP/Proofs/S900030.lean", labels=("disputed",)),
            "221": pr(221, "QPCP/Proofs/S900031.lean", labels=("needs-maintainer",)),
            "222": pr(222, "QPCP/Proofs/S900035.lean"),
            "223": pr(223, "QPCP/Proofs/S900035.lean", "closed", "2026-11-27T00:00:00Z"),
            "224": pr(224, "QPCP/Proofs/S900030.lean", labels=("needs-maintainer",)),
            # 8. a merge into staging of a proof that IS on main; candidates into other branches
            "215": pr(215, "QPCP/Proofs/S900036.lean", "closed", "2026-11-27T00:00:00Z", base_ref="staging"),
            "216": pr(216, "QPCP/Proofs/S900036.lean"),
            "217": pr(217, "QPCP/Proofs/S900031.lean", base_ref="staging"),
        }
        state = {
            "issues": dict({str(n): issue(n, f"PR {n}", labels=tuple(l["name"] for l in pulls[str(n)]["labels"]))
                            for n in map(int, pulls)},
                           **{"300": issue(300, "S900035: x", labels=("step", "disputed"))}),
            "pulls": pulls,
            "main_files": ["QPCP/Proofs/S900030.lean", "QPCP/Proofs/S900031.lean", "QPCP/Proofs/S900035.lean",
                           "QPCP/Proofs/S900036.lean"],
            "commit_pulls": {old_add: [{"number": 60, "merged_at": "2026-11-24T00:00:00Z", "base": {"ref": "main"}}],
                             new_add: [{"number": 156, "merged_at": "2026-11-26T17:16:50Z", "base": {"ref": "main"}}]},
        }
        e = Env(base / "p", state)
        e.env["QPCP_REPO"] = str(main_repo)
        r203, _ = e.call("pr-opened", 203)
        r204, _ = e.call("pr-opened", 204)
        r206, _ = e.call("pr-opened", 206)
        st = e.get()
        check("5. a proof of a step already proved on main is closed",
              r203 == "closed" and st["pulls"]["203"]["state"] == "closed", (r203, st["pulls"]["203"]["state"]))
        check("10. deleted and added again: 'already settled by #156' (the current file's addition), not #60",
              any("already settled by #156" in b for b in bot_says(st, 203)) and not any("#60" in b for b in bot_says(st, 203)),
              bot_says(st, 203))
        check("6. a refutation of a proved step is kept open and flagged for the maintainer",
              r204 == "flagged" and st["pulls"]["204"]["state"] == "open"
              and "needs-maintainer" in [l["name"] for l in st["issues"]["204"]["labels"]], (r204, st["issues"]["204"]))
        check("7. two open proofs of an unsettled step: the later one is not closed for arriving second",
              r206 == "ignored" and st["pulls"]["206"]["state"] == "open" and st["pulls"]["205"]["state"] == "open")
        out, _ = e.call("pr-merged", 200)
        st = e.get()
        check("7. when a proof merges, a late duplicate proof is closed, naming the merged one",
              st["pulls"]["201"]["state"] == "closed" and any("#200, a proof of S900031, has merged" in b for b in bot_says(st, 201)),
              (out, bot_says(st, 201)))
        check("7. an open refutation of that step is flagged, never closed",
              st["pulls"]["202"]["state"] == "open" and "needs-maintainer" in [l["name"] for l in st["issues"]["202"]["labels"]],
              st["issues"]["202"])
        check("8. a candidate into another branch is never closed as a duplicate of a merge into main",
              st["pulls"]["217"]["state"] == "open", st["pulls"]["217"])
        check("7. pull requests for other steps are untouched by the merge",
              st["pulls"]["205"]["state"] == "open" and st["pulls"]["206"]["state"] == "open")
        check("9. a pull request flagged needs-maintainer is not closed when a proof of its step merges",
              st["pulls"]["221"]["state"] == "open", st["pulls"]["221"])
        out215, _ = e.call("pr-merged", 215)
        st = e.get()
        check("8. a merge into staging closes nothing, even when the proof is also on main",
              st["pulls"]["216"]["state"] == "open" and out215 == "nothing to close", out215)
        out, _ = e.call("pr-merged", 210)
        r212, _ = e.call("pr-opened", 212)
        out213, _ = e.call("pr-merged", 213)
        st = e.get()
        check("8. a merge into staging closes no pull request into main", st["pulls"]["211"]["state"] == "open" and out == "nothing to close", out)
        check("8. a pull request into staging is not acted on when opened", r212 == "ignored" and st["pulls"]["212"]["state"] == "open", r212)
        check("8. a manual replay of an old merge whose proof was since deleted from main closes nothing",
              st["pulls"]["214"]["state"] == "open" and out213 == "nothing to close", out213)
        r220, _ = e.call("pr-opened", 220)
        # A maintainer hold survives every event: opened, reopened and synchronize all run pr-opened
        # (checked below in triage.yml), and the merged path is checked after.
        holds = [e.call("pr-opened", 224)[0] for _ in ("opened", "reopened", "synchronize")]
        st = e.get()
        check("9. a needs-maintainer hold survives opened, reopened and synchronize: never closed",
              holds == ["held"] * 3 and st["pulls"]["224"]["state"] == "open", holds)
        wf = (ROOT / ".github" / "workflows" / "triage.yml").read_text()
        check("9. triage.yml runs the opened path for opened, reopened and synchronize, and the merged path on merge",
              "types: [opened, reopened, synchronize, closed]" in wf and "'merged'" in wf and "pr-opened" in wf
              and "github.event.pull_request.merged == true" in wf)
        e.call("pr-merged", 200)  # a merge of a proof of S900031 again: the held 221 must survive it too
        st = e.get()
        check("9. merged path: the needs-maintainer hold survives a merge event", st["pulls"]["221"]["state"] == "open")
        r222, _ = e.call("pr-opened", 222)
        out223, _ = e.call("pr-merged", 223)
        st = e.get()
        check("9. opened path: a pull request labelled disputed is not closed though its step is proved",
              r220 == "held" and st["pulls"]["220"]["state"] == "open", r220)
        check("9. opened path: a pull request whose step's issue is disputed is not closed",
              r222 == "held" and st["pulls"]["222"]["state"] == "open", r222)
        check("9. merged path: a pull request whose step's issue is disputed is not closed",
              st["pulls"]["222"]["state"] == "open" and "held #222" in out223, out223)

        # 11. Timeliness from the comment's own time, and out-of-order processing.
        e = Env(base / "t", {"issues": {
            "71": issue(71, "S900071: x", ("step", "claimed"), ["alice"],
                        [(10, "alice", "/claim", NOW - 24 * H - 300), (11, "alice", "/renew", NOW - 600)]),
            "72": issue(72, "S900072: x", comments=[(20, "bob", "/claim", NOW - 120), (21, "bob", "/release", NOW - 60)]),
            "73": issue(73, "S900073: x", comments=[(30, "carl", "/claim", NOW - 120), (31, "dora", "/claim", NOW - 60)])}})
        r71, _ = e.call("claim-comment", 71, 11)
        st = e.get()
        check("11. a /renew written 5 minutes before expiry and processed 5 minutes after it renews",
              r71 == "renewed" and holders(st, 71) == ["alice"], (r71, holders(st, 71), bot_says(st, 71)))
        late_release, _ = e.call("claim-comment", 72, 21)
        late_claim, _ = e.call("claim-comment", 72, 20)
        st = e.get()
        check("11. /claim then /release, processed in reverse order: no holder (the older /claim does not undo it)",
              holders(st, 72) == [] and late_claim == "superseded", (late_release, late_claim, holders(st, 72)))
        second, _ = e.call("claim-comment", 73, 31)
        first, _ = e.call("claim-comment", 73, 30)
        st = e.get()
        check("11. two /claims processed in reverse order: the earlier comment's author holds the step",
              holders(st, 73) == ["carl"] and second == "taken" and first == "claimed", (second, first, holders(st, 73)))
    except Exception as e:  # a crash is a failure, never a skip
        import traceback
        traceback.print_exc()
        check("the test ran to completion", False, repr(e))
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
