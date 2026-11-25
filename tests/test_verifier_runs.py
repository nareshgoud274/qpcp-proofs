#!/usr/bin/env python3
"""Verifier runs do not share state, and a replay-only run accepts nothing.

    python3 -I tests/test_verifier_runs.py

Needs `lake` (for Env.setup), not bubblewrap.

  1. Two Env instances, as two local runs would make, get different work
     directories, and setting up the second leaves the first's files alone.
  2. QPCP_WORK naming a directory that already exists is a Fault, and its
     contents are untouched.
  3. A replay-only report prints REPLAYED-ONLY, never ACCEPTED, and returns 3;
     a failed replay is still REJECTED with 1.
  4. No workflow, script or document treats REPLAYED-ONLY as acceptance: the
     word appears only in sandbox_verify.py, the tests and MAINTAINERS.md.
"""

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:300]}"))


def load():
    spec = importlib.util.spec_from_file_location("sandbox_verify", ROOT / "scripts" / "sandbox_verify.py")
    sv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sv)
    return sv


def main():
    sv = load()
    base = Path(tempfile.mkdtemp(prefix="qpcp-runs-", dir=Path.home()))
    saved = {k: os.environ.get(k) for k in ("RUNNER_TEMP", "QPCP_WORK")}
    try:
        os.environ["RUNNER_TEMP"] = str(base)
        os.environ.pop("QPCP_WORK", None)
        with contextlib.redirect_stderr(io.StringIO()):
            a = sv.Env(sandbox=False)
            a.setup()
            (a.work / "result" / "mine.txt").write_text("first run\n")
            b = sv.Env(sandbox=False)
            b.setup()
        check(f"1. two runs get different work directories ({a.work.name}, {b.work.name})", a.work != b.work)
        check("1. the second run's setup leaves the first run's files alone",
              (a.work / "result" / "mine.txt").read_text() == "first run\n")
        a.setup()
        check("1. a run's own setup clears only its own directory",
              not (a.work / "result" / "mine.txt").exists() and b.work.is_dir())

        taken = base / "taken"
        taken.mkdir()
        (taken / "keep.txt").write_text("someone else's\n")
        os.environ["QPCP_WORK"] = str(taken)
        try:
            sv.Env(sandbox=False)
            check("2. an existing QPCP_WORK is a fault", False, "accepted")
        except sv.Fault as f:
            check(f"2. an existing QPCP_WORK is a fault ({f})", "already exists" in str(f), f)
        check("2. its contents are untouched", (taken / "keep.txt").read_text() == "someone else's\n")
        os.environ["QPCP_WORK"] = str(base / "fresh")
        c = sv.Env(sandbox=False)
        check("2. a new QPCP_WORK is created and used", c.work == (base / "fresh").absolute() and c.work.is_dir())
        os.environ.pop("QPCP_WORK")

        src = base / "S001.lean"
        src.write_text("theorem QPCP.Proof.S001 : True := trivial\n")
        mods = {}
        for ident in ("S001", "S002"):
            m = sv.Module("proof", ident, src)
            mods[m.name] = m
        for m in mods.values():
            m.verdict = sv.REPLAYED_ONLY
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sv.report(sorted(mods), mods, replay_only=True)
        text = out.getvalue()
        check(f"3. a replay-only report returns 3 (got {rc})", rc == 3)
        check("3. it prints REPLAYED-ONLY and never ACCEPTED",
              "ACCEPTED" not in text and text.strip().splitlines()[-1].startswith("REPLAYED-ONLY:"), text)
        list(mods.values())[1].verdict, list(mods.values())[1].reason = "REJECTED", "replay failed"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sv.report(sorted(mods), mods, replay_only=True)
        check(f"3. a failed replay is still REJECTED with 1 (got {rc})",
              rc == 1 and out.getvalue().strip().splitlines()[-1].startswith("REJECTED"), out.getvalue())

        hits = subprocess.run(["git", "grep", "-l", "REPLAYED-ONLY"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        allowed = {"scripts/sandbox_verify.py", "MAINTAINERS.md", "tests/run_tests.sh", "tests/test_verifier_runs.py"}
        check(f"4. REPLAYED-ONLY appears only where it is defined, documented or tested ({sorted(hits)})",
              set(hits) <= allowed, sorted(set(hits) - allowed))
    except Exception as e:  # a crash is a failure, never a skip
        check("crashed", False, f"{type(e).__name__}: {e}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(base, ignore_errors=True)
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
