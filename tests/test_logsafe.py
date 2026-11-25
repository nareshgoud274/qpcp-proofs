#!/usr/bin/env python3
"""Contributor-controlled text cannot inject workflow commands into CI logs.

    python3 -I tests/test_logsafe.py

Checks scripts/logsafe.py itself, then every place that prints such text:
the scanner (a name that contains `::` and a line break), the sandboxed
verifier's report (a reject reason carrying a Lean error), automerge's
`left alone` line (a file name), and the gate in ci_contribution.sh (file
names in a pull request, in a throwaway git repository).
"""

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def safe(text):
    return "::" not in text and "\r" not in text and " " not in text


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {detail!r}"))


logsafe = load("logsafe", ROOT / "scripts" / "logsafe.py")
for raw in ["::error::forged", "a:::b", "x\n::add-mask::y", "p\r::stop-commands::q", "s ::warning::t",
            "::::", "c\x00d\x1be", ": :"]:
    out = logsafe.log_safe(raw)
    check(f"log_safe({raw!r})", safe(out) and "\n" not in out and "\x1b" not in out, out)
check("log_safe keeps ordinary text", logsafe.log_safe("REJECTED: `x` is missing") == "REJECTED: `x` is missing")

with tempfile.TemporaryDirectory() as d:
    # The scanner quotes an import name back.
    f = Path(d, "S030.lean")
    f.write_text("import Foo::error::injected\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "check.py"), "scan-file", "proof", "S030", str(f)],
                       capture_output=True, text=True)
    check("the scanner's rejection is one safe line", r.stdout.count("\n") == 1 and safe(r.stdout), r.stdout)

    # The verifier's report quotes a Lean error, which quotes the source.
    sv = load("sandbox_verify", ROOT / "scripts" / "sandbox_verify.py")
    m = sv.Module.__new__(sv.Module)
    m.kind, m.ident, m.verdict = "proof", "S030", "REJECTED"
    m.reason = "does not compile: error at line 2\n::error file=x::forged verdict\n::set-output name=v::ok"
    buf = io.StringIO()
    with redirect_stdout(buf):
        sv.report(["QPCP.Proofs.S030"], {"QPCP.Proofs.S030": m})
    out = buf.getvalue()
    check("the verifier's report prints the reason on one safe line",
          safe(out) and out.count("\n") == 2 and "forged verdict" in out, out)

    # automerge prints the file name of a pull request it leaves alone.
    am = load("automerge", ROOT / "scripts" / "automerge.py")
    buf = io.StringIO()
    with redirect_stdout(buf):
        print(am.log_safe("#5: left alone (QPCP/Proofs/::error::x.lean is modified, not added)"))
    check("automerge's lines are safe", safe(buf.getvalue()), buf.getvalue())
    src = (ROOT / "scripts" / "automerge.py").read_text()
    pr_lines = [l for l in src.splitlines() if "print(" in l and ("pr['number']" in l or "[dry run]" in l)]
    check("automerge passes every pull-request line through log_safe",
          len(pr_lines) == 3 and all("print(log_safe(" in l for l in pr_lines), pr_lines)

    # The gate prints the pull request's file names.
    repo = Path(d, "repo")
    (repo / "scripts").mkdir(parents=True)
    for s in ("ci_contribution.sh", "logsafe.py"):
        shutil.copy2(ROOT / "scripts" / s, repo / "scripts" / s)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, env=env, check=True)
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()
    (repo / "QPCP" / "Proofs").mkdir(parents=True)
    (repo / "QPCP" / "Proofs" / "::error::forged.lean").write_text("x\n")
    (repo / "QPCP" / "Proofs" / "a\n::warning::b.lean").write_text("x\n")
    git("add", ".")
    git("commit", "-qm", "pr")
    r = subprocess.run(["bash", str(repo / "scripts" / "ci_contribution.sh"), "gate", base],
                       capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    check("the gate rejects it and prints the file names safely", r.returncode == 1 and safe(out), out)

print(f"failed {fails}")
sys.exit(1 if fails else 0)
