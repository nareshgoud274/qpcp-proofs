#!/usr/bin/env python3
"""The "Reproduce this check" command on step pages is correct (needs Linux, Lean and bubblewrap).

    python3 -I tests/test_reproduce_command.py [<ID>]

Picks a proved step at random from the proofs in the tree (or takes <ID>),
asks scripts/build_status.py for the command and the expected line, exactly as
the feed publishes them, runs that command from the repository root, and
checks that it exits 0 and that its last line is the expected one. It also
checks that REPRODUCE.md shows the same command and line for S059. It FAILS
rather than skips when it cannot run the command (no bubblewrap, not Linux).

Runs in the attack-tests job (as-is tree), after elan, the Mathlib cache and
bubblewrap are installed: the setup REPRODUCE.md describes.
"""

import importlib.util
import os
import random
import shlex
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
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[-1500:]}"))


def main(argv):
    print("The reproduce command on step pages")
    spec = importlib.util.spec_from_file_location("build_status", ROOT / "scripts" / "build_status.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)

    example = bs.reproduce_check("proof", "S059")
    doc = (ROOT / "REPRODUCE.md").read_text()
    check("REPRODUCE.md shows the feed's command and expected line for S059",
          example["command"] in doc and f"`{example['expect']}`" in doc, example)

    proofs = sorted(bs.git_files(ROOT, "QPCP/Proofs"))
    sid = argv[1] if len(argv) > 1 else random.SystemRandom().choice(proofs)
    rp = bs.reproduce_check("proof", sid)
    print(f"  step picked: {sid}  (of {len(proofs)} proofs)")
    print(f"  command:     {rp['command']}")
    print(f"  expect:      {rp['expect']}")
    if not sys.platform.startswith("linux") or not shutil.which("bwrap"):
        check("Linux with bubblewrap, to run the command", False, f"{sys.platform}, bwrap={shutil.which('bwrap')}")
        return 1
    base = Path(os.environ.get("RUNNER_TEMP") or (ROOT / ".lake"))
    work = Path(tempfile.mkdtemp(prefix="qpcp-reproduce-", dir=base)) / "work"  # must not exist yet
    env = dict(os.environ, QPCP_WORK=str(work))
    r = subprocess.run(shlex.split(rp["command"]), cwd=ROOT, capture_output=True, text=True, env=env, timeout=5400)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    print("\n".join("  | " + l for l in lines[-5:]))
    check(f"the command exits 0 for {sid}", r.returncode == 0, (r.returncode, r.stdout[-800:], r.stderr[-800:]))
    check(f"its last line is exactly {rp['expect']!r}", last == rp["expect"], last)
    # The evidence carries the location Lean reports for a one-name statement (#155 review, 1a).
    import json
    ev = json.loads((work / "result" / "record-items.json").read_text())
    loc = next((i.get("statementDefinition") for i in ev["items"] if i["id"] == sid), None)
    check("the run's Lean location query ran", ev.get("locatedByLean") is True, ev.get("locatedByLean"))
    vspec = importlib.util.spec_from_file_location("verification_record", ROOT / "scripts" / "verification_record.py")
    vr = importlib.util.module_from_spec(vspec)
    vspec.loader.exec_module(vr)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    spath, sline = vr.statement_location(ROOT, head, "proof", sid)
    shown = vr.statement_definition(ROOT, head, spath, sline, loc, True)
    one_name = vr.ONE_NAME.match(" ".join(l.strip() for l in vr.strip_comments(
        subprocess.run(["git", "-C", str(ROOT), "show", f"{head}:{spath}"], capture_output=True, text=True).stdout
    ).split("\n")[sline - 1:sline]))
    if one_name:
        check(f"{sid} is one name: Lean located {one_name.group(1)} and its source is shown from those lines",
              loc and loc["name"] == one_name.group(1) and shown and shown["located"] == "lean"
              and f"def {one_name.group(1).rsplit('.', 1)[-1]}" in shown["source"], (loc, shown))
    else:
        check(f"{sid} is not one name: no location and nothing shown", loc is None and shown is None, (loc, shown))
    shutil.rmtree(work.parent, ignore_errors=True)
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
