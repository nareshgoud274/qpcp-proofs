#!/usr/bin/env python3
"""Every third-party action and the elan installer are pinned.

    python3 -I tests/test_pins.py

  * every `uses:` in .github/workflows names a full 40-hex commit;
  * no workflow or script fetches anything from a branch (`master`, `main`)
    or a `latest` release, or pipes a download into a shell;
  * scripts/install_elan.sh downloads one fixed elan release and checks it
    against a fixed SHA-256 before running it, and every workflow that
    installs elan uses it.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {detail}"))


workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
scripts = sorted((ROOT / "scripts").glob("*.sh"))
for wf in workflows:
    text = wf.read_text()
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.M)
    bad = [u for u in uses if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u)]
    check(f"{wf.name}: {len(uses)} action(s), all pinned to a commit", not bad, bad)
for f in workflows + scripts:
    text = f.read_text()
    floating = re.findall(r"https?://\S*(?:/master/|/main/|/latest/|/latest\b)\S*", text)
    piped = re.findall(r"curl[^\n|]*\|\s*(?:sh|bash)\b", text)
    check(f"{f.name}: no download from a branch or `latest`, none piped into a shell", not floating and not piped,
          floating + piped)
elan = (ROOT / "scripts" / "install_elan.sh").read_text()
check("install_elan.sh pins a release and its SHA-256",
      re.search(r'^ELAN_VERSION="v\d+\.\d+\.\d+"$', elan, re.M) is not None
      and re.search(r'^ELAN_SHA256="[0-9a-f]{64}"$', elan, re.M) is not None
      and "sha256sum -c" in elan and elan.index("sha256sum -c") < elan.index('"$dir/elan-init"'))
for wf in workflows:
    text = wf.read_text()
    if "elan" in text:
        check(f"{wf.name}: installs elan only through scripts/install_elan.sh",
              "scripts/install_elan.sh" in text and "elan-init" not in text)
fails += 1  # THROWAWAY: proves a failing attack-tests job blocks a merge; never merge
print(f"failed {fails}")
sys.exit(1 if fails else 0)
