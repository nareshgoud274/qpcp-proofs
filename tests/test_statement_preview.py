#!/usr/bin/env python3
"""Tests for scripts/statement_preview.py against a stub `gh` (no network).

    python3 -I tests/test_statement_preview.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHA = "a" * 40
STUB = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["STUB_DIR"]
if sys.argv[1:3] == ["pr", "view"]:
    print(open(os.path.join(d, "pr.json")).read())
elif sys.argv[1] == "api":
    print(open(os.path.join(d, "comments.txt")).read())
'''


def run(d, preview, pr_info, comments="", run_sha=SHA):
    Path(d, "preview.json").write_text(preview if isinstance(preview, str) else json.dumps(preview))
    Path(d, "pr.json").write_text(json.dumps(pr_info))
    Path(d, "comments.txt").write_text(comments)
    out = Path(d, "comment.md")
    if out.exists():
        out.unlink()
    env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "STUB_DIR": d, "RUN_SHA": run_sha, "GH_REPO": "o/r"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "statement_preview.py"),
                        str(Path(d, "preview.json")), str(out)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout.strip(), out.read_text() if out.exists() else ""


def main():
    good = {"pr": 12, "head_sha": SHA, "ident": "L70", "text": "def QPCP.Lemma.L70 :\n  Prop := True"}
    pr_ok = {"state": "OPEN", "headRefOid": SHA, "files": [{"path": "QPCP/Lemmas/L70.lean", "changeType": "ADDED"}]}
    cases = [
        ("posts for a matching one-file lemma pull request", good, pr_ok, "", SHA, (0, "12", "Kernel statement of L70")),
        ("not for another commit than the one checked", good, pr_ok, "", "b" * 40, (1, "", "")),
        ("not if the pull request moved on", good, dict(pr_ok, headRefOid="c" * 40), "", SHA, (0, "", "")),
        ("not if the pull request is closed", good, dict(pr_ok, state="CLOSED"), "", SHA, (0, "", "")),
        ("not if it changes another file too", good,
         dict(pr_ok, files=pr_ok["files"] + [{"path": "README.md", "changeType": "MODIFIED"}]), "", SHA, (0, "", "")),
        ("not if it modifies rather than adds", good,
         dict(pr_ok, files=[{"path": "QPCP/Lemmas/L70.lean", "changeType": "MODIFIED"}]), "", SHA, (0, "", "")),
        ("not for a different lemma's file", dict(good, ident="L71"), pr_ok, "", SHA, (0, "", "")),
        ("not twice", good, pr_ok, f"<!-- qpcp-statement-preview {SHA} -->", SHA, (0, "", "")),
        ("refuses a malformed id", dict(good, ident="L70; rm"), pr_ok, "", SHA, (1, "", "")),
        ("refuses a non-JSON preview", "not json", pr_ok, "", SHA, (1, "", "")),
        ("refuses an oversized preview", dict(good, text="x" * 200_000), pr_ok, "", SHA, (1, "", "")),
    ]
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        Path(d, "gh").write_text(STUB)
        os.chmod(Path(d, "gh"), 0o755)
        for desc, preview, info, comments, run_sha, (want_code, want_pr, want_text) in cases:
            code, pr, text = run(d, preview, info, comments, run_sha)
            okay = code == want_code and pr == want_pr and (want_text in text if want_text else text == "")
            fails += not okay
            print(f"  {'ok  ' if okay else 'FAIL'}  {desc}: exit {code}, pr [{pr}]")
        code, pr, text = run(d, dict(good, text="```\nend of block\n``` injected"), pr_ok)
        okay = code == 0 and text.count("```") == 2
        fails += not okay
        print(f"  {'ok  ' if okay else 'FAIL'}  code fences in the text cannot close the comment's block")
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
