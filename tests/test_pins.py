#!/usr/bin/env python3
"""Every third-party action and the elan installer are pinned.

    python3 -I tests/test_pins.py

  * every `uses:` in .github/workflows names a full 40-hex commit;
  * no workflow or script fetches anything from a branch (`master`, `main`)
    or a `latest` release, or pipes a download into a shell;
  * scripts/install_elan.sh downloads one fixed elan release and checks it
    against a fixed SHA-256 before running it, and every workflow that
    installs elan uses it. Run with stand-in uname, curl and sha256sum: on
    x86_64 and on aarch64 Linux it asks for that architecture's archive with
    that architecture's hash, and runs nothing that failed the check; any
    other architecture or system is refused before anything is downloaded.
"""

import os
import re
import subprocess
import sys
import tempfile
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
sums = dict(re.findall(r'^ELAN_SHA256_(X86_64|AARCH64)="([0-9a-f]{64})"$', elan, re.M))
check("install_elan.sh pins a release and a SHA-256 for each of x86_64 and aarch64",
      re.search(r'^ELAN_VERSION="v\d+\.\d+\.\d+"$', elan, re.M) is not None
      and set(sums) == {"X86_64", "AARCH64"} and len(set(sums.values())) == 2
      and "sha256sum -c" in elan and elan.index("sha256sum -c") < elan.index('"$dir/elan-init"'), sums)


def run_installer(system, machine):
    """install_elan.sh with stand-ins: uname reports (system, machine); curl records its URL and
    writes a dummy archive; sha256sum records what it was asked to check and fails."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for name, body in {
            "uname": f'case "$1" in -s) echo {system};; -m) echo {machine};; *) echo {system};; esac\n',
            "curl": f'for a in "$@"; do last="$a"; done; echo "$last" >> "{t}/urls"\n'
                    'while [ $# -gt 0 ]; do [ "$1" = -o ] && { shift; echo x > "$1"; }; shift; done\n',
            "sha256sum": f'cat >> "{t}/checked"; exit 1\n',
        }.items():
            (t / name).write_text("#!/bin/sh\n" + body)
            (t / name).chmod(0o755)
        env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}", HOME=str(t / "home"))
        r = subprocess.run(["bash", str(ROOT / "scripts" / "install_elan.sh")], env=env,
                           capture_output=True, text=True, timeout=60)
        read = lambda n: (t / n).read_text() if (t / n).exists() else ""
        return r, read("urls"), read("checked"), (t / "home" / ".elan").exists()


check("install_elan.sh says, after the check and before running anything, that the SHA-256 was checked",
      elan.index("sha256sum -c") < elan.find("SHA-256 checked") < elan.index('"$dir/elan-init"'))
for machine, arch, key in (("x86_64", "x86_64", "X86_64"), ("aarch64", "aarch64", "AARCH64")):
    r, urls, checked, installed = run_installer("Linux", machine)
    check(f"install_elan.sh on {machine}: fetches the {arch} archive, checks it against the {arch} hash, "
          "and stops when the check fails",
          urls.strip().endswith(f"/elan-{arch}-unknown-linux-gnu.tar.gz") and sums.get(key, "?") in checked
          and r.returncode != 0 and not installed, (r.returncode, urls, checked, r.stderr))
for system, machine in (("Linux", "riscv64"), ("Darwin", "arm64")):
    r, urls, checked, installed = run_installer(system, machine)
    check(f"install_elan.sh on {system} {machine}: refused before any download",
          r.returncode != 0 and urls == "" and not installed, (r.returncode, urls, r.stderr))
for wf in workflows:
    text = wf.read_text()
    if "elan" in text:
        check(f"{wf.name}: installs elan only through scripts/install_elan.sh",
              "scripts/install_elan.sh" in text and "elan-init" not in text)
print(f"failed {fails}")
sys.exit(1 if fails else 0)
