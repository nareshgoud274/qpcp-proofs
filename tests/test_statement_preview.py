#!/usr/bin/env python3
"""Tests for scripts/statement_preview.py against a stub `gh` (no network).

    python3 -I tests/test_statement_preview.py

The stub logs every call. Besides what is posted, each case checks whether the
artifact was downloaded at all: it must not be unless the pull request was
first validated through the API.
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
import json, os, shutil, sys
d = os.environ["STUB_DIR"]
open(os.path.join(d, "calls.log"), "a").write(" ".join(sys.argv[1:3]) + "\n")
if sys.argv[1:3] == ["pr", "list"]:
    print(open(os.path.join(d, "list.json")).read())
elif sys.argv[1:3] == ["pr", "view"]:
    print(open(os.path.join(d, "view.json")).read())
elif sys.argv[1:3] == ["run", "download"]:
    dest = sys.argv[sys.argv.index("-D") + 1]
    shutil.copyfile(os.path.join(d, "preview.json"), os.path.join(dest, "preview.json"))
elif sys.argv[1] == "api":
    print(open(os.path.join(d, "comments.txt")).read())
'''


def run(d, prs, preview, view=None, comments="", run_sha=SHA):
    Path(d, "list.json").write_text(json.dumps(prs))
    Path(d, "view.json").write_text(json.dumps(view if view is not None else (prs[0] if prs else {})))
    Path(d, "preview.json").write_text(preview if isinstance(preview, str) else json.dumps(preview))
    Path(d, "comments.txt").write_text(comments)
    for f in ("calls.log", "comment.md"):
        Path(d, f).unlink(missing_ok=True)
    work = Path(d, "work")
    if work.exists():
        for f in work.iterdir():
            f.unlink()
    env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "STUB_DIR": d, "RUN_SHA": run_sha,
           "RUN_ID": "77", "GH_REPO": "o/r"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "statement_preview.py"), "run",
                        str(work), str(Path(d, "comment.md"))], capture_output=True, text=True, env=env)
    calls = Path(d, "calls.log").read_text() if Path(d, "calls.log").exists() else ""
    text = Path(d, "comment.md").read_text() if Path(d, "comment.md").exists() else ""
    return r.returncode, r.stdout.strip(), text, "run download" in calls


def main():
    pr = {"number": 12, "state": "OPEN", "headRefOid": SHA,
          "files": [{"path": "QPCP/Lemmas/L70.lean", "changeType": "ADDED"}]}
    good = {"pr": 12, "head_sha": SHA, "ident": "L70", "text": "def QPCP.Lemma.L70 :\n  Prop := True"}
    other_file = {"path": "README.md", "changeType": "MODIFIED"}
    # (description, open pull requests at the commit, preview, view, comments, run sha,
    #  (exit code, printed pr, text in comment, downloaded?))
    cases = [
        ("posts for a matching one-file lemma pull request", [pr], good, None, "", SHA,
         (0, "12", "Kernel statement of L70", True)),
        ("no pull request at the commit: nothing downloaded", [], good, None, "", SHA, (0, "", "", False)),
        ("the pull request moved on: nothing downloaded", [dict(pr, headRefOid="c" * 40)], good, None, "", SHA,
         (0, "", "", False)),
        ("closed: nothing downloaded", [dict(pr, state="CLOSED")], good, None, "", SHA, (0, "", "", False)),
        ("another file too: nothing downloaded", [dict(pr, files=pr["files"] + [other_file])], good, None, "", SHA,
         (0, "", "", False)),
        ("only a workflow file: nothing downloaded",
         [dict(pr, files=[{"path": ".github/workflows/check.yml", "changeType": "MODIFIED"}])], good, None, "", SHA,
         (0, "", "", False)),
        ("modifies rather than adds: nothing downloaded",
         [dict(pr, files=[{"path": "QPCP/Lemmas/L70.lean", "changeType": "MODIFIED"}])], good, None, "", SHA,
         (0, "", "", False)),
        ("a proof, not a lemma: nothing downloaded",
         [dict(pr, files=[{"path": "QPCP/Proofs/S030.lean", "changeType": "ADDED"}])], good, None, "", SHA,
         (0, "", "", False)),
        ("two pull requests at the commit: nothing downloaded", [pr, dict(pr, number=13)], good, None, "", SHA,
         (0, "", "", False)),
        ("a malformed run sha: nothing downloaded", [pr], good, None, "", "not-a-sha", (1, "", "", False)),
        ("the artifact names another pull request", [pr], dict(good, pr=99), None, "", SHA, (1, "", "", True)),
        ("the artifact names another lemma", [pr], dict(good, ident="L71"), None, "", SHA, (1, "", "", True)),
        ("the artifact names another commit", [pr], dict(good, head_sha="b" * 40), None, "", SHA, (1, "", "", True)),
        ("ids come from the API: an artifact with only text is enough", [pr], {"text": "def X : Prop := True"},
         None, "", SHA, (0, "12", "Kernel statement of L70", True)),
        ("the pull request moved on before posting", [pr], good, dict(pr, headRefOid="d" * 40), "", SHA,
         (0, "", "", True)),
        ("not twice", [pr], good, None, f"<!-- qpcp-statement-preview {SHA} -->", SHA, (0, "", "", True)),
        ("refuses a non-JSON preview", [pr], "not json", None, "", SHA, (1, "", "", True)),
        ("refuses an oversized preview", [pr], dict(good, text="x" * 200_000), None, "", SHA, (1, "", "", True)),
    ]
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        Path(d, "gh").write_text(STUB)
        os.chmod(Path(d, "gh"), 0o755)
        for desc, prs, preview, view, comments, run_sha, (want_code, want_pr, want_text, want_dl) in cases:
            code, got_pr, text, downloaded = run(d, prs, preview, view, comments, run_sha)
            okay = (code == want_code and got_pr == want_pr and downloaded == want_dl
                    and (want_text in text if want_text else text == ""))
            fails += not okay
            print(f"  {'ok  ' if okay else 'FAIL'}  {desc}: exit {code}, pr [{got_pr}], downloaded {downloaded}")
        code, got_pr, text, _ = run(d, [pr], dict(good, text="```\nend of block\n``` injected"))
        okay = code == 0 and text.count("```") == 2
        fails += not okay
        print(f"  {'ok  ' if okay else 'FAIL'}  code fences in the text cannot close the comment's block")
    wf = (ROOT / ".github" / "workflows" / "statement-preview.yml").read_text()
    okay = "gh run download" not in wf and "statement_preview.py run" in wf
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  the workflow downloads only through the script, after validation")
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
