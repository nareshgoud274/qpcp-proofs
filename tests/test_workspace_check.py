#!/usr/bin/env python3
"""The front door: the owner's prerequisite check, the no-install Lima route, and the early stop. No network.

    python3 -I tests/test_workspace_check.py

  1. scripts/workspace_check.sh, run with stand-in uname, df, curl, docker
     and limactl: every failure (no Docker or Lima, on a Mac and on Linux;
     Docker installed but not running; too little disk; no network; a guest
     that does not start; a guest that cannot reach a download host) prints
     FAIL with a "Next:" line and exits non-zero; Docker or Lima working
     end to end prints only PASS and exits 0; the Lima check deletes its
     throwaway guest.
  2. scripts/get_lima.sh pins a Lima release and a SHA-256 per Mac
     architecture; with stand-ins it fetches that architecture's archive,
     checks that hash, and unpacks nothing when the check fails; Linux and
     other architectures are refused before any download.
  3. JOIN.md checks the machine before anything else and stops there if it
     cannot host a workspace; it never tells an agent to use a sandbox
     override or a full-access mode; README.md and the homepage show the
     owner's check beside the agent instruction, at the same pin.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
HOSTS = ["github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com", "cache.mathlib.org",
         "ports.ubuntu.com"]


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:700]}"))


def stubs(t, tools):
    b = t / "bin"
    b.mkdir(exist_ok=True)
    for name, body in tools.items():
        (b / name).write_text("#!/bin/sh\n" + body)
        (b / name).chmod(0o755)
    return b


def probe_output(failing=()):
    return "".join(f"echo 'reach {h} {'FAILED' if h in failing else 'ok'}'\n" for h in HOSTS)


def run_check(system="Darwin", machine="arm64", free_gb=100, net=True, docker=None, lima=None):
    """docker: None (absent), "stopped", or the guest's probe output; lima likewise, or "nostart"."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        log = t / "calls"
        tools = {
            "uname": f'case "$1" in -s) echo {system};; -m) echo {machine};; *) echo {system};; esac\n',
            "df": f'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; '
                  f'echo "/dev/x 999999999 1 {free_gb * 1024 * 1024} 1% /"\n',
            "curl": "exit 0\n" if net else "echo 'curl: (6) Could not resolve host: github.com' >&2; exit 6\n",
        }
        if docker is not None:
            tools["docker"] = (f'echo "docker $*" >> "{log}"\n'
                               'case "$1" in info) ' + ("exit 1" if docker == "stopped" else "exit 0") + ';; '
                               'run) ' + (docker if docker != "stopped" else "exit 1") + ';; esac\n')
        if lima is not None:
            tools["limactl"] = (f'echo "limactl $*" >> "{log}"\n'
                                'case "$1" in create) ' + ("exit 1" if lima == "nostart" else "exit 0") + ';; '
                                'start|delete) exit 0;; shell) ' + (lima if lima != "nostart" else "exit 1") + ';; esac\n')
        b = stubs(t, tools)
        env = {"PATH": f"{b}:/usr/bin:/bin", "HOME": str(t / "home")}
        (t / "home").mkdir()
        r = subprocess.run(["bash", str(ROOT / "scripts" / "workspace_check.sh")], env=env,
                           capture_output=True, text=True, timeout=60)
        return r, log.read_text() if log.exists() else ""


def test_check():
    r, _ = run_check()
    check("1. a Mac with neither Docker nor Lima: FAIL, pointing to get_lima.sh, non-zero",
          r.returncode != 0 and "FAIL  workspace tool: neither Docker nor Lima is on this Mac" in r.stdout
          and "get_lima.sh" in r.stdout, r.stdout)
    r, _ = run_check(system="Linux", machine="x86_64")
    check("1. Linux with neither: FAIL, pointing to Docker Engine", r.returncode != 0 and "docker.io" in r.stdout,
          r.stdout)
    r, _ = run_check(docker="stopped")
    check("1. Docker installed but not running: FAIL, start it", r.returncode != 0 and "not running" in r.stdout,
          r.stdout)
    r, _ = run_check(free_gb=22, docker=probe_output())
    check("1. 22 GB free (the volunteer's machine): FAIL disk, with the honest breakdown",
          r.returncode != 0 and "FAIL  disk: 22 GB free" in r.stdout and "about 15 GB" in r.stdout
          and "about 3 GB" in r.stdout, r.stdout)
    r, _ = run_check(net=False, docker=probe_output())
    check("1. this terminal cannot reach github.com: FAIL network, naming the cause", r.returncode != 0
          and "FAIL  network" in r.stdout and "Network" in r.stdout, r.stdout)
    r, calls = run_check(docker=probe_output())
    check("1. Docker running, guest reaches every host: only PASS, exit 0",
          r.returncode == 0 and "FAIL" not in r.stdout and "PASS  guest network" in r.stdout
          and "docker run --rm ubuntu:24.04" in calls, (r.stdout, calls))
    r, _ = run_check(docker=probe_output(failing=("cache.mathlib.org",)))
    check("1. the guest cannot reach cache.mathlib.org: FAIL guest network, naming it",
          r.returncode != 0 and "FAIL  guest network: cannot reach: cache.mathlib.org" in r.stdout, r.stdout)
    r, calls = run_check(lima=probe_output())
    check("1. Lima, guest reaches every host: only PASS, exit 0, and the throwaway guest is deleted",
          r.returncode == 0 and "FAIL" not in r.stdout and "limactl create --yes --name=qpcp-check" in calls
          and calls.strip().splitlines()[-1].startswith("limactl delete -f qpcp-check"), (r.stdout, calls))
    check("1. the Lima guest has no host folders and no agent forwarding",
          ".mounts = [] | .ssh.forwardAgent = false" in calls, calls)
    r, calls = run_check(lima="nostart")
    check("1. Lima that cannot start a guest: FAIL guest, and nothing is left behind",
          r.returncode != 0 and "FAIL  guest" in r.stdout and "limactl delete -f qpcp-check" in calls,
          (r.stdout, calls))
    text = (ROOT / "scripts" / "workspace_check.sh").read_text()
    check("1. every FAIL in the script carries a Next: line",
          all("Next:" in r.stdout for r in [run_check()[0]]) and "fail() {" in text, "")


def run_get_lima(system, machine):
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        b = stubs(t, {
            "uname": f'case "$1" in -s) echo {system};; -m) echo {machine};; esac\n',
            "curl": f'for a in "$@"; do last="$a"; done; echo "$last" >> "{t}/urls"\n'
                    'while [ $# -gt 0 ]; do [ "$1" = -o ] && { shift; echo x > "$1"; }; shift; done\n',
            "shasum": f'cat >> "{t}/checked"; exit 1\n',
        })
        env = {"PATH": f"{b}:/usr/bin:/bin", "HOME": str(t / "home")}
        r = subprocess.run(["bash", str(ROOT / "scripts" / "get_lima.sh")], env=env, capture_output=True,
                           text=True, timeout=60)
        read = lambda n: (t / n).read_text() if (t / n).exists() else ""
        return r, read("urls"), read("checked"), (t / "home" / "qpcp-setup" / "lima" / "bin").exists()


def test_get_lima():
    text = (ROOT / "scripts" / "get_lima.sh").read_text()
    sums = dict(re.findall(r'^LIMA_SHA256_(ARM64|X86_64)="([0-9a-f]{64})"$', text, re.M))
    check("2. get_lima.sh pins a Lima version and a SHA-256 for each Mac architecture",
          re.search(r'^LIMA_VERSION="\d+\.\d+\.\d+"$', text, re.M) is not None and set(sums) == {"ARM64", "X86_64"}
          and len(set(sums.values())) == 2, sums)
    check("2. get_lima.sh never uses sudo, Homebrew or a shell startup file",
          not re.search(r"\bsudo\b|\bbrew\b|\.zshrc|\.bash_profile|\.profile", text.split("set -euo pipefail", 1)[1]),
          "")
    for machine, key in (("arm64", "ARM64"), ("x86_64", "X86_64")):
        r, urls, checked, unpacked = run_get_lima("Darwin", machine)
        check(f"2. get_lima.sh on a {machine} Mac: fetches that archive, checks that hash, unpacks nothing on failure",
              urls.strip().endswith(f"/lima-2.3.0-Darwin-{machine}.tar.gz") and sums[key] in checked
              and r.returncode != 0 and not unpacked, (r.returncode, urls, checked, r.stderr))
    for system, machine in (("Linux", "x86_64"), ("Darwin", "ppc")):
        r, urls, _, unpacked = run_get_lima(system, machine)
        check(f"2. get_lima.sh on {system} {machine}: refused before any download",
              r.returncode != 0 and urls == "" and not unpacked, (r.returncode, urls, r.stderr))


def test_docs():
    join = (ROOT / "JOIN.md").read_text()
    front = join.index("## Before anything else")
    check("3. JOIN.md checks the machine before anything else (before the revision check and Two places)",
          front < join.index("## Which revision") < join.index("## Two places"), "")
    sec = join[front:join.index("## A machine with nothing installed")]
    check("3. the first section tells the agent to stop there, before reading further, and names the options",
          "Otherwise stop here." in sec and 'Do not go past "Network"' in sec and "get_lima" in join
          and "Network" in sec, "")
    check("3. the first section's commands only read (docker info, limactl lookup, df, curl to github.com)",
          all(c in sec for c in ("docker info", "command -v limactl", "df -h ~", "https://github.com")), "")
    check("3. the guide says 25 GB on the host, workspace plus downloads",
          "25 GB" in sec and "about 3 GB" in join, "")
    net = join[join.index("## Network"):join.index("## Which revision")]
    check("3. Network: names the sandbox cause, both options, and forbids unapproved overrides",
          "Could not resolve host: github.com" in net and "(a)" in net and "(b)" in net
          and "never run a command in" in net.replace("\n", " ") and "Untested" in net, "")
    check("3. JOIN.md never tells an agent to use a full-access or bypass mode",
          not re.search(r"danger-full-access|--dangerously|--yolo|bypass.{0,20}sandbox", join, re.I), "")
    check("3. removing everything also removes ~/qpcp-out", "rm -rf ~/qpcp-setup ~/qpcp-out" in join, "")
    check("3. the guide and the check say to run the check again after a fix",
          "run it again" in sec and "run this again" in (ROOT / "scripts" / "workspace_check.sh").read_text(), "")
    check("3. the status file is read after setup, in the workspace",
          "Once the setup has run, look at the state of the project first, in the" in join, "")
    check("3. the untested cases are named (Windows, Intel Macs, Docker Desktop)",
          all(w in join for w in ("Windows", "Intel", "Docker Desktop")), "")
    readme = (ROOT / "README.md").read_text()
    pins = set(re.findall(r"qpcp-proofs/([0-9a-f]{40})/(?:JOIN\.md|scripts/workspace_check\.sh)", readme))
    check("3. README.md shows the owner's check beside the agent instruction, at the same pin as JOIN.md",
          "scripts/workspace_check.sh" in readme and len(pins) == 1
          and readme.index("workspace_check.sh") < readme.index("Fetch and follow"), pins)
    index = (ROOT / "docs" / "index.html").read_text()
    check("3. the homepage shows the check before the agent instruction, from the same pinned commit",
          index.index('id="check-cmd"') < index.index('id="join-cmd"')
          and 'Q.joinUrl.replace(/JOIN\\.md$/, "scripts/workspace_check.sh")' in index, "")


def main():
    print("The front door: prerequisite check, no-install Lima, early stop")
    try:
        test_check()
        test_get_lima()
        test_docs()
    except Exception as e:  # a crash is a failure, never a skip
        import traceback
        traceback.print_exc()
        check("the test ran to completion", False, repr(e))
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
