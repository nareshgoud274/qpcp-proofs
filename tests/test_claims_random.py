#!/usr/bin/env python3
"""Randomized invariants for claims (scripts/triage.py), in-process against an in-memory GitHub. No network.

    python3 -I tests/test_claims_random.py [--seed N] [--cases N] [--orders N]
    python3 -I tests/test_claims_random.py --replay '<history JSON printed by a failure>'

Each case is a random history of /claim, /renew, /release and ordinary
comments by several accounts on several steps, with their own timestamps
(some equal), over about three days. In some, a step's issue is closed and
reopened, up to four times, at random moments: deliberately sometimes several in
one second, and sometimes in a comment's very second. Each transition keeps its
real sequence (an event id); comments may come while the issue is closed. The history is then processed in many
random schedules, as GitHub Actions might run it: each comment's run comes
late by a random delay (minutes to more than a day), some run twice, some
never run, hourly and random sweeps interleave, and runs with the same time
come in random order. A run sees the comments that exist at its time.

After every run, and after a final sweep, it asserts:
  - at most one holder per step;
  - at most one step per account;
  - no claim outlives 24 hours from its holder's own last comment on that
    issue;
and that the state is the same in every schedule of the history at two
common checkpoints: one hour after the last event, while claims are still
live, and after a final sweep. After every run the state must also equal an
independent reference model of the rules (below), so a consistent but wrong
rule (such as re-deciding history when an issue closes or reopens) is caught
too. The rules apply to open issues: a closed step's issue holds no claim.

Not covered here: event history that lags an issue's state (tests/test_claims.py
case 16), and concurrent interleavings of API calls within runs (runs here are
sequential; case 1 there runs two at once).

The seed is printed; a failing history is printed as JSON for --replay.
"""

import argparse
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
H = 3600
T0 = 1_800_000_000
BOT = "github-actions[bot]"
ACCOUNTS = ["ann", "ben", "cat", "dov"]
STEPS = [901, 902, 903]


def load_triage():
    spec = importlib.util.spec_from_file_location("qpcp_triage", ROOT / "scripts" / "triage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tri = load_triage()


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class World:
    """GitHub as triage.py sees it through `api`: step issues, their comments, assignees and labels."""

    def __init__(self, history):
        self.clock = T0
        self.next_id = 10_000_000
        self.issues = {n: {"number": n, "title": f"S9{n:05d}: x", "state": "open", "labels": [{"name": "step"}],
                           "assignees": [], "comments": []} for n in STEPS}
        self.transitions = {n: transitions(history, n) for n in STEPS}
        for c in history:  # human comments exist from their own time on; a transition happens at its time
            if c.get("event"):
                continue
            self.issues[c["issue"]]["comments"].append(
                {"id": c["id"], "user": {"login": c["who"]}, "body": c["body"], "created_at": iso(c["t"]), "_t": c["t"]})

    def seen(self, n):
        return [(t, q, e) for t, q, e in self.transitions[n] if t <= self.clock]

    def is_open(self, n):
        s = self.seen(n)
        return not s or s[-1][2] == "reopened"

    def public(self, i):
        out = {k: v for k, v in i.items() if k != "comments"}
        if not self.is_open(i["number"]):
            out.update(state="closed", closed_at=iso(self.seen(i["number"])[-1][0]))
        return out

    def visible(self, n):
        return [c for c in self.issues[n]["comments"] if c["_t"] <= self.clock]

    def api(self, method, path, body=None, paginate=False, missing_ok=False):
        path, _, query = path.partition("?")
        seg = path.split("/")
        if seg == ["issues"] and method == "GET":
            label = dict(kv.split("=", 1) for kv in query.split("&")).get("labels")
            return [self.public(i) for i in self.issues.values()
                    if not label or label in [l["name"] for l in i["labels"]]]
        i = self.issues[int(seg[1])]
        if len(seg) == 2 and method == "GET":
            return self.public(i)
        if seg[2] == "comments" and method == "GET":
            return self.visible(i["number"])
        if seg[2] == "events" and method == "GET":
            # Each event carries its id (its real sequence). They are returned newest first, so
            # triage.py must order them by id, not by the order or the names it is given.
            return [{"id": q, "event": e, "created_at": iso(t)} for t, q, e in reversed(self.seen(i["number"]))]
        if seg[2] == "comments" and method == "POST":
            self.next_id += 1
            i["comments"].append({"id": self.next_id, "user": {"login": BOT}, "body": body["body"],
                                  "created_at": iso(self.clock), "_t": self.clock})
            return {"id": self.next_id}
        if seg[2] == "assignees":
            for who in body["assignees"]:
                if method == "POST" and who not in [a["login"] for a in i["assignees"]]:
                    i["assignees"].append({"login": who})
                if method == "DELETE":
                    i["assignees"] = [a for a in i["assignees"] if a["login"] != who]
            return {}
        if seg[2] == "labels" and method == "POST":
            for name in body["labels"]:
                if name not in [l["name"] for l in i["labels"]]:
                    i["labels"].append({"name": name})
            return []
        if seg[2] == "labels" and method == "DELETE":
            i["labels"] = [l for l in i["labels"] if l["name"] != seg[3]]
            return []
        raise AssertionError(f"unexpected {method} {path}")

    def holders(self):
        """Holders of the open step issues (a closed issue keeps whatever it last had, and holds no claim)."""
        return {n: sorted(a["login"] for a in i["assignees"]) if "claimed" in [l["name"] for l in i["labels"]] else []
                for n, i in self.issues.items() if self.is_open(n)}

    def violations(self):
        out = []
        hs = self.holders()
        for n, i in self.issues.items():
            if not self.is_open(n):
                continue
            assigned = sorted(a["login"] for a in i["assignees"])
            if len(assigned) > 1:
                out.append(f"#{n} has {len(assigned)} holders: {assigned}")
            if ("claimed" in [l["name"] for l in i["labels"]]) != bool(assigned):
                out.append(f"#{n}: the claimed label and the assignee disagree ({assigned})")
        owners = {}
        for n, h in hs.items():
            for who in h:
                owners.setdefault(who, []).append(n)
        out += [f"{who} holds {ns}" for who, ns in owners.items() if len(ns) > 1]
        for n, h in hs.items():
            for who in h:
                own = [c["_t"] for c in self.visible(n) if c["user"]["login"] == who]
                if not own or self.clock - max(own) > tri.LAPSE:
                    out.append(f"#{n}: {who}'s claim outlives 24 hours from their last comment")
        return out


def transitions(history, n):
    """Issue n's closings and reopenings as (time, sequence, kind), in their real order: the
    sequence they were made in (several can share a second)."""
    return sorted(((c["t"], c["seq"], c["event"]) for c in history if c.get("event") and c["issue"] == n),
                  key=lambda x: x[1])


def reference(history, at):
    """The rules, written out on their own: holders of the open steps at time `at`.

    Second by second. In each second, first that second's closings and
    reopenings in the sequence they were made in (never by their kind), then
    that second's comments by id: a comment is judged against the issue's state
    at the end of its second (the stated policy for that ambiguous tie). A claim
    lapses when its holder has not commented on that issue for more than 24
    hours; a closing ends the claim on that step for good, and while the issue
    is closed its comments count for nothing; a reopening only lets a new /claim
    in; the holder's /release frees the step and any other comment by the holder
    renews it; anyone else's /claim is granted only if the step is free and the
    account holds no other step."""
    seconds = sorted({c["t"] for c in history if c["t"] <= at})
    timeline = []
    for sec in seconds:
        timeline += sorted((c for c in history if c["t"] == sec and c.get("event")), key=lambda c: c["seq"])
        timeline += sorted((c for c in history if c["t"] == sec and not c.get("event")), key=lambda c: c["id"])
    step, shut = {}, set()  # step: issue -> [holder, time of their last comment there]
    for c in timeline:
        t = c["t"]
        step = {n: h for n, h in step.items() if t - h[1] <= tri.LAPSE}
        n = c["issue"]
        if c.get("event") == "closed":
            shut.add(n)
            step.pop(n, None)
            continue
        if c.get("event") == "reopened":
            shut.discard(n)
            continue
        if n in shut:
            continue
        first = c["body"].split()[0] if c["body"].split() else ""
        if n in step and step[n][0] == c["who"]:
            if first == "/release":
                del step[n]
            else:
                step[n][1] = t
        elif first == "/claim" and n not in step and c["who"] not in [h[0] for h in step.values()]:
            step[n] = [c["who"], t]
    step = {n: h for n, h in step.items() if at - h[1] <= tri.LAPSE}
    return {n: ([step[n][0]] if n in step else []) for n in STEPS if n not in shut}


def history_of(rng):
    """A random history: comments with their own times, ids in creation order."""
    n = rng.randint(3, 16)
    times = sorted(T0 + rng.choice([rng.randint(0, 72 * H), rng.randint(0, 72 * H) // 3600 * 3600]) for _ in range(n))
    bodies = ["/claim"] * 5 + ["/renew"] * 2 + ["/release"] * 2 + ["Working on it.", "/claim please"]
    out = [{"id": 1000 + k, "issue": rng.choice(STEPS), "who": rng.choice(ACCOUNTS), "body": rng.choice(bodies), "t": t}
           for k, t in enumerate(times)]
    seq = 50_000  # event ids, in creation order across all issues
    for n in STEPS:  # some issues close and reopen, up to four times
        if rng.random() < 0.4:
            ts_ = []
            for _ in range(rng.randint(1, 4)):
                pick = rng.random()
                if ts_ and pick < 0.35:
                    ts_.append(ts_[-1])                    # deliberately in the same second as the last one
                elif pick < 0.6:
                    ts_.append(rng.choice(times))          # in a comment's very second
                else:
                    ts_.append(rng.randint(T0, times[-1] + H))
            ts_.sort()  # equal times kept: never sorted(set(...))
            for k, t in enumerate(ts_):
                seq += 1
                out.append({"issue": n, "event": ("closed", "reopened")[k % 2], "t": t, "seq": seq})
    return out


def schedule_of(rng, history):
    """Runs (time, kind, issue, comment id): delayed, duplicated, dropped, with sweeps; ties in random order."""
    runs = []
    for c in history:
        if not c.get("event") and tri.command({"body": c["body"]}):
            for _ in range(rng.choice([0, 1, 1, 1, 2, 3])):
                delay = rng.choice([0, 0, 60, rng.randint(0, 2 * H), rng.randint(0, 30 * H)])
                runs.append((c["t"] + delay, "claim", c["issue"], c["id"]))
    last = max(c["t"] for c in history)
    end = last + 2 * H
    runs += [(t, "sweep", None, None) for t in range(T0, end, H) if rng.random() < 0.7]
    runs += [(rng.randint(T0, end), "sweep", None, None) for _ in range(rng.randint(0, 3))]
    runs.append((last + H, "checkpoint", None, None))  # claims made in the last day are still live here
    rng.shuffle(runs)
    runs.sort(key=lambda r: r[0])  # stable: equal times keep their shuffled order
    return runs, end + 30 * H


def run_schedule(history, runs, final):
    w = World(history)
    tri.api = w.api
    tri.now = lambda: w.clock
    checkpoint = None
    for t, kind, n, cid in runs:
        w.clock = max(w.clock, t)
        if kind == "claim":
            tri.claim_comment(n, cid)
        else:
            tri.sweep()
        if kind == "checkpoint":
            checkpoint = w.holders()
        bad = w.violations()
        want = reference(history, w.clock)
        if w.holders() != want:
            bad.append(f"holders {w.holders()} but the rules say {want}")
        if bad:
            return None, f"after {kind} {n or ''} {cid or ''} at T0+{(w.clock - T0) / H:.2f}h: {bad}"
    w.clock = final
    tri.sweep()
    bad = w.violations()
    if w.holders() != reference(history, final):
        bad.append(f"holders {w.holders()} but the rules say {reference(history, final)}")
    if bad:
        return None, f"after the final sweep: {bad}"
    return (checkpoint, w.holders()), None


def check_case(history, rng, orders):
    seen = None
    for k in range(orders):
        runs, final = schedule_of(rng, history)
        got, err = run_schedule(history, runs, final)
        if err:
            return f"schedule {k}: {err}", runs
        if seen is None:
            seen = got
        elif got != seen:
            return f"schedule {k}: state (checkpoint, final) {got} differs from schedule 0's {seen}", runs
    return None, None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261127)
    ap.add_argument("--cases", type=int, default=1000)
    ap.add_argument("--orders", type=int, default=8)
    ap.add_argument("--replay")
    a = ap.parse_args(argv)
    print(f"Claims: randomized invariants ({'one replayed history' if a.replay else f'seed {a.seed}, {a.cases} histories'}"
          f" x {a.orders} schedules)")
    rng = random.Random(a.seed)
    started = time.time()
    if a.replay:
        case = json.loads(a.replay)
        histories = [case["history"]]
        rng = random.Random(case["schedule_seed"])
    else:
        histories = None
    fails = 0
    for k in range(1 if histories else a.cases):
        history = histories[0] if histories else history_of(rng)
        schedule_seed = rng.randrange(2**32) if not histories else case["schedule_seed"]
        err, runs = check_case(history, random.Random(schedule_seed), a.orders)
        if err:
            fails += 1
            print(f"  FAIL  case {k}: {err}")
            print("  replay with: python3 -I tests/test_claims_random.py --orders %d --replay '%s'"
                  % (a.orders, json.dumps({"history": history, "schedule_seed": schedule_seed})))
            if fails >= 3:
                break
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s) in {time.time() - started:.1f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
