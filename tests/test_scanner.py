#!/usr/bin/env python3
"""Source-scanner cases that need no Lean: tests/scanner/*.lean.

    python3 -I tests/test_scanner.py

Each file starts with `-- expect: <text>`: ACCEPTED, or a part of the reason
the scanner must give. An optional second line `-- as: <kind> <id>` scans it
as that contribution (default: proof S030). Also checks that the scanner's
output is safe to print in a CI log.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def scan(kind, ident, path):
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "check.py"), "scan-file", kind, ident, str(path)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def main():
    fails = 0
    for path in sorted((ROOT / "tests" / "scanner").glob("*.lean")):
        lines = path.read_text(encoding="utf-8").splitlines()
        expect = lines[0].removeprefix("-- expect: ")
        kind, ident = ("proof", "S030")
        if len(lines) > 1 and lines[1].startswith("-- as: "):
            kind, ident = lines[1].removeprefix("-- as: ").split()
        code, out = scan(kind, ident, path)
        if expect == "ACCEPTED":
            okay = code == 0 and out.startswith("ACCEPTED")
        else:
            okay = code == 1 and out.startswith("REJECTED") and expect in out
        fails += not okay
        print(f"  {'ok  ' if okay else 'FAIL'}  {path.name}: {out[:150]}")
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
