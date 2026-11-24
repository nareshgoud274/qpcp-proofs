#!/usr/bin/env python3
"""Unit tests for the merge rules in scripts/automerge.py, on synthetic data.

    python3 -I tests/test_automerge.py

No network: a fake API answers the issue lookups.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("automerge", HERE.parent / "scripts" / "automerge.py")
am = importlib.util.module_from_spec(spec)
spec.loader.exec_module(am)

HEAD = "a" * 40


class FakeApi:
    def __init__(self, issues):
        self.issues = issues

    def get(self, path):
        n = int(path.rsplit("/", 1)[1])
        if n not in self.issues:
            raise am.urllib.error.HTTPError(path, 404, "not found", {}, None)
        return self.issues[n]

    def step_issue_for(self, ident, cache):
        if ident.startswith("L"):
            return self.issues.get(int(ident[1:]))
        return self.issues.get({"S030": 61, "S031": 62}.get(ident, -1))


def pr(path, author="alice", change="ADDED", files=1, check="SUCCESS", head=HEAD,
       reviews=(), draft=False):
    return {
        "number": 500, "isDraft": draft, "changedFiles": files, "headRefOid": head,
        "author": {"login": author},
        "files": {"nodes": [{"path": path, "changeType": change}]},
        "reviews": {"nodes": [{"author": {"login": who}, "commit": {"oid": oid}} for who, oid in reviews]},
        "commits": {"nodes": [{"commit": {"oid": head, "checkSuites": {"nodes": [
            {"conclusion": check, "workflowRun": {"event": "pull_request", "workflow": {"name": "check"}}}]}}}]},
    }


def issue(number, labels, user="alice", state="open", assignees=()):
    return {"number": number, "state": state, "labels": [{"name": l} for l in labels],
            "user": {"login": user}, "assignees": [{"login": a} for a in assignees], "title": "Proposal: x"}


ISSUES = {
    61: issue(61, ["step"]),                                   # S030, open, unclaimed
    62: issue(62, ["step", "claimed"], assignees=["bob"]),      # S031, claimed by bob
    70: issue(70, ["proposal"], user="alice"),                  # proposal by alice -> L70
    71: issue(71, ["proposal"], user="bob"),                    # proposal by bob   -> L71
    72: issue(72, ["step", "retired"]),                        # retired lemma L72
}
API = FakeApi(ISSUES)

CASES = [
    # (description, pull request, reviewers.json, expected action, text expected in the detail)
    ("proof of an open unclaimed step", pr("QPCP/Proofs/S030.lean"), [], "proof", ""),
    ("proof of a step claimed by someone else", pr("QPCP/Proofs/S031.lean"), [], "skip", "claimed by bob"),
    ("proof by the claim holder", pr("QPCP/Proofs/S031.lean", author="bob"), [], "proof", ""),
    ("proof of a retired lemma", pr("QPCP/Proofs/L72.lean"), [], "skip", "not open"),
    ("check failed", pr("QPCP/Proofs/S030.lean", check="FAILURE"), [], "skip", "check has not succeeded"),
    ("two files", pr("QPCP/Proofs/S030.lean", files=2), [], "skip", "changes 2 files"),
    ("modified, not added", pr("QPCP/Proofs/S030.lean", change="MODIFIED"), [], "skip", "not added"),
    ("draft", pr("QPCP/Proofs/S030.lean", draft=True), [], "skip", "draft"),
    ("not a contribution path", pr("scripts/check.py"), [], "skip", "not a contribution file"),
    ("lemma with no approval", pr("QPCP/Lemmas/L70.lean"), ["carol"], "skip", "no approving statement review"),
    ("lemma approved only by an unlisted user", pr("QPCP/Lemmas/L70.lean", reviews=[("mallory", HEAD)]),
     ["carol"], "skip", "advisory"),
    ("lemma approved by an unlisted user, empty reviewers.json", pr("QPCP/Lemmas/L70.lean", reviews=[("carol", HEAD)]),
     [], "skip", "advisory"),
    ("lemma approved by a listed reviewer", pr("QPCP/Lemmas/L70.lean", reviews=[("carol", HEAD)]),
     ["carol"], "lemma", ""),
    ("listed reviewer, login case differs", pr("QPCP/Lemmas/L70.lean", reviews=[("Carol", HEAD)]),
     ["cAROL"], "lemma", ""),
    ("listed reviewer approved an older commit", pr("QPCP/Lemmas/L70.lean", reviews=[("carol", "b" * 40)]),
     ["carol"], "skip", "no approving statement review"),
    ("author is listed and approves own lemma", pr("QPCP/Lemmas/L70.lean", reviews=[("alice", HEAD)]),
     ["alice"], "skip", "no approving statement review"),
    ("author approves own lemma under other case", pr("QPCP/Lemmas/L70.lean", reviews=[("ALICE", HEAD)]),
     ["alice"], "skip", "no approving statement review"),
    ("bot approval does not count", pr("QPCP/Lemmas/L70.lean", reviews=[("github-actions[bot]", HEAD)]),
     ["github-actions[bot]"], "skip", "no approving statement review"),
    ("lemma for someone else's proposal", pr("QPCP/Lemmas/L71.lean", reviews=[("carol", HEAD)]),
     ["carol"], "skip", "opened by someone else"),
]


def main():
    fails = 0
    for desc, p, allowed, want, text in CASES:
        action, detail = am.decide(p, API, {}, {a.lower() for a in allowed})
        detail_s = detail if isinstance(detail, str) else json.dumps(detail)
        good = action == want and text in detail_s
        fails += not good
        print(f"  {'ok  ' if good else 'FAIL'}  {desc}: {action} ({detail_s[:90]})")

    with tempfile.TemporaryDirectory() as d:
        for content, want in [("[]", set()), ('["Carol", " dave ", 3, ""]', {"carol", "dave"}),
                              ("not json", set()), ('{"carol": true}', set())]:
            Path(d, "reviewers.json").write_text(content)
            got = am.trusted_reviewers(Path(d))
            good = got == want
            fails += not good
            print(f"  {'ok  ' if good else 'FAIL'}  reviewers.json {content!r} -> {sorted(got)}")
        Path(d, "reviewers.json").unlink()
        good = am.trusted_reviewers(Path(d)) == set()
        fails += not good
        print(f"  {'ok  ' if good else 'FAIL'}  missing reviewers.json trusts nobody")
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
