#!/usr/bin/env python3
"""Randomized invariants for claims (scripts/triage.py), in-process against an in-memory GitHub. No network.

    python3 -I tests/test_claims_random.py [--seed N] [--cases N] [--orders N]
    python3 -I tests/test_claims_random.py --replay '<history JSON printed by a failure>'

Each case is a random history of /claim, /renew, /release and ordinary
comments by several accounts on several steps, with their own timestamps
(some equal), over about three days. The history is then processed in many
random schedules, as GitHub Actions might run it: each comment's run comes
late by a random delay (minutes to more than a day), some run twice, some
never run, hourly and random sweeps interleave, and runs with the same time
come in random order. A run sees the comments that exist at its time.

After every run, and after a final sweep, it asserts:
  - at most one holder per step;
  - at most one step per account;
  - no claim outlives 24 hours from its holder's own last comment on that
    issue;
and after the final sweep, that the final state is the same in every
schedule of the history.

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
        for c in history:  # human comments exist from their own time on
            self.issues[c["issue"]]["comments"].append(
                {"id": c["id"], "user": {"login": c["who"]}, "body": c["body"], "created_at": iso(c["t"]), "_t": c["t"]})

    def visible(self, n):
        return [c for c in self.issues[n]["comments"] if c["_t"] <= self.clock]

    def api(self, method, path, body=None, paginate=False, missing_ok=False):
        path, _, query = path.partition("?")
        seg = path.split("/")
        if seg == ["issues"] and method == "GET":
            label = dict(kv.split("=", 1) for kv in query.split("&")).get("labels")
            return [{k: v for k, v in i.items() if k != "comments"} for i in self.issues.values()
                    if not label or label in [l["name"] for l in i["labels"]]]
        i = self.issues[int(seg[1])]
        if len(seg) == 2 and method == "GET":
            return {k: v for k, v in i.items() if k != "comments"}
        if seg[2] == "comments" and method == "GET":
            return self.visible(i["number"])
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
        return {n: sorted(a["login"] for a in i["assignees"]) if "claimed" in [l["name"] for l in i["labels"]] else []
                for n, i in self.issues.items()}

    def violations(self):
        out = []
        hs = self.holders()
        for n, i in self.issues.items():
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


def history_of(rng):
    """A random history: comments with their own times, ids in creation order."""
    n = rng.randint(3, 16)
    times = sorted(T0 + rng.choice([rng.randint(0, 72 * H), rng.randint(0, 72 * H) // 3600 * 3600]) for _ in range(n))
    bodies = ["/claim"] * 5 + ["/renew"] * 2 + ["/release"] * 2 + ["Working on it.", "/claim please"]
    return [{"id": 1000 + k, "issue": rng.choice(STEPS), "who": rng.choice(ACCOUNTS), "body": rng.choice(bodies), "t": t}
            for k, t in enumerate(times)]


def schedule_of(rng, history):
    """Runs (time, kind, issue, comment id): delayed, duplicated, dropped, with sweeps; ties in random order."""
    runs = []
    for c in history:
        if tri.command({"body": c["body"]}):
            for _ in range(rng.choice([0, 1, 1, 1, 2, 3])):
                delay = rng.choice([0, 0, 60, rng.randint(0, 2 * H), rng.randint(0, 30 * H)])
                runs.append((c["t"] + delay, "claim", c["issue"], c["id"]))
    end = max(c["t"] for c in history) + 2 * H
    runs += [(t, "sweep", None, None) for t in range(T0, end, H) if rng.random() < 0.7]
    runs += [(rng.randint(T0, end), "sweep", None, None) for _ in range(rng.randint(0, 3))]
    rng.shuffle(runs)
    runs.sort(key=lambda r: r[0])  # stable: equal times keep their shuffled order
    return runs, end + 30 * H


def run_schedule(history, runs, final):
    w = World(history)
    tri.api = w.api
    tri.now = lambda: w.clock
    for t, kind, n, cid in runs:
        w.clock = max(w.clock, t)
        if kind == "claim":
            tri.claim_comment(n, cid)
        else:
            tri.sweep()
        bad = w.violations()
        if bad:
            return None, f"after {kind} {n or ''} {cid or ''} at T0+{(w.clock - T0) / H:.2f}h: {bad}"
    w.clock = final
    tri.sweep()
    bad = w.violations()
    if bad:
        return None, f"after the final sweep: {bad}"
    return w.holders(), None


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
            return f"schedule {k}: final state {got} differs from schedule 0's {seen}", runs
    return None, None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261127)
    ap.add_argument("--cases", type=int, default=1500)
    ap.add_argument("--orders", type=int, default=8)
    ap.add_argument("--replay")
    a = ap.parse_args(argv)
    print(f"Claims: randomized invariants (seed {a.seed}, {a.cases} histories x {a.orders} schedules)")
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
