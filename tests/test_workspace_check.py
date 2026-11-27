#!/usr/bin/env python3
"""The front door: the owner's prerequisite check, the no-install Lima route, and the early stop. No network.

    python3 -I tests/test_workspace_check.py

  1. scripts/workspace_check.sh, run with stand-in uname, df, curl, docker
     and limactl: every failure (no Docker or Lima, on a Mac and on Linux;
     Docker installed but not running; too little disk; no network; a guest
     that does not start; a guest that cannot reach a download host) prints
     FAIL with a "Next:" line and exits non-zero; Docker or Lima working end to end prints only PASS and exits 0, and
     each probe is labelled for what it measures.
  2. The network check never passes falsely: on the host, curl -f (an HTTP
     error fails); in the guest, the probe must exit 0 and report exactly
     one line per expected host (a missing, repeated or unexpected line, or
     a non-zero exit after a success, is a FAIL); every probe has a limit.
     The guest is this run's own (a unique name; others are never touched),
     none is created when the disk check fails, it is deleted when the run
     is interrupted, a failed deletion is reported with the exact name and
     command, and two runs at once do not interfere.
  3. scripts/get_lima.sh pins a Lima release and a SHA-256 per Mac
     architecture; it fetches that architecture's archive and checks that
     hash; it stops, running nothing, if ~/qpcp-setup/lima exists; it
     installs only after the checksum and unpacking succeed, so a failed or
     interrupted extraction leaves nothing half-installed; Linux and other
     architectures are refused before any download.
  4. JOIN.md checks the machine before anything else and stops there if it
     cannot host a workspace (the no-network stop is not final on the manual
     route); it says the sandbox MAY be the cause; it never tells an agent to
     use a sandbox override or a full-access mode; README.md, JOIN.md and the
     homepage download, read and run each script as separate steps.
  5. JOIN.md "Network" (b): the reviewer's boundary and resumption text, and
     the owner's network-dependent steps in order.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
HOSTS = [("github.com", 443), ("raw.githubusercontent.com", 443), ("release-assets.githubusercontent.com", 443),
         ("cache.mathlib.org", 443), ("ports.ubuntu.com", 80)]


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:700]}"))


# The only real programs the scripts may find: a machine's own docker, limactl, curl and the
# like must never leak into a test (a CI runner has Docker installed).
BASIC = ["sh", "bash", "awk", "grep", "tr", "tail", "head", "cat", "mkdir", "rm", "mktemp", "tar", "sleep", "mv",
         "ls", "touch", "chmod", "printf"]


def stubs(t, tools):
    b = t / "bin"
    b.mkdir(exist_ok=True)
    for name in BASIC:
        real = shutil.which(name)
        if real and name not in tools:
            (b / name).symlink_to(real)
    for name, body in tools.items():
        (b / name).write_text("#!/bin/sh\n" + body)
        (b / name).chmod(0o755)
    return b


def probe_output(failing=(), unresolved=(), skip=(), extra=(), then=""):
    """The guest's probe output: one line per host, then a shell command (for example an exit status)."""
    lines = ""
    for h, port in HOSTS:
        if h in skip:
            continue
        d = "FAILED" if h in unresolved else "ok"
        c = "FAILED" if h in failing or h in unresolved else "ok"
        lines += f"echo 'probe {h} resolve={d} tcp{port}={c}'\n"
    for h in extra:
        lines += f"echo 'probe {h} resolve=ok tcp443=ok'\n"
    return lines + then + "\n"


def fakes(t, docker=None, lima=None, nodelete=False):
    """Stand-in docker and limactl that keep their guests as files in t/guests, and log every call."""
    log, guests = t / "calls", t / "guests"
    guests.mkdir(exist_ok=True)
    tools = {}
    rm = ":" if nodelete else 'rm -f "$G/$x"'
    if docker is not None:
        (t / "guest.sh").write_text("" if docker == "stopped" else docker)
        tools["docker"] = (f'G="{guests}"; echo "docker $*" >> "{log}"\n'
                           'for a; do x="$a"; done\n'
                           'case "$1" in\n'
                           '  info) ' + ("exit 1" if docker == "stopped" else "exit 0") + ';;\n'
                           '  container) [ -e "$G/$x" ];;\n'
                           '  create) shift; shift; touch "$G/$1";;\n'
                           f'  start) sh "{t}/guest.sh";;\n'
                           f'  rm) {rm};;\n'
                           'esac\n')
    if lima is not None:
        (t / "guest.sh").write_text("" if lima in ("nostart", "partial") else lima)
        create = {"nostart": "exit 1", "partial": 'touch "$G/$n"; exit 1'}.get(lima, 'touch "$G/$n"')
        tools["limactl"] = (f'G="{guests}"; echo "limactl $*" >> "{log}"\n'
                            'for a; do x="$a"; done\n'
                            'case "$1" in\n'
                            '  list) ls "$G";;\n'
                            '  create) for a; do case "$a" in --name=*) n="${a#--name=}";; esac; done; ' + create + ';;\n'
                            '  start) exit 0;;\n'
                            f'  shell) sh "{t}/guest.sh";;\n'
                            f'  delete) {rm};;\n'
                            'esac\n')
    return tools


def check_env(t, system="Darwin", machine="arm64", free_gb=100, net="ok", **kw):
    tools = {
        "uname": f'case "$1" in -s) echo {system};; -m) echo {machine};; *) echo {system};; esac\n',
        "df": f'echo "Filesystem 1024-blocks Used Available Capacity Mounted"; '
              f'echo "/dev/x 999999999 1 {free_gb * 1024 * 1024} 1% /"\n',
        # "http-error": the server answers, with an error status: only curl -f turns that into a failure.
        "curl": {"ok": "exit 0\n",
                 "down": "echo 'curl: (6) Could not resolve host: github.com' >&2; exit 6\n",
                 "http-error": 'for a; do case "$a" in --*) ;; -*f*) exit 22;; esac; done; exit 0\n'}[net],
    }
    tools.update(fakes(t, **kw))
    b = stubs(t, tools)
    (t / "home").mkdir(exist_ok=True)
    return {"PATH": str(b), "HOME": str(t / "home")}


def run_check(pre=(), **kw):
    """docker/lima: None (absent), "stopped"/"nostart"/"partial", or the guest's probe script. pre: guests
    that exist before the run, and must still exist after it."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        env = check_env(t, **kw)
        for g in pre:
            (t / "guests" / g).touch()
        r = subprocess.run([shutil.which("bash"), str(ROOT / "scripts" / "workspace_check.sh")], env=env,
                           capture_output=True, text=True, timeout=60)
        r.calls = (t / "calls").read_text() if (t / "calls").exists() else ""
        r.guests = sorted(p.name for p in (t / "guests").iterdir())
        return r


def created(calls):
    return re.findall(r"(?:create --name |create --yes --name=)(\S+)", calls)


def test_check():
    r = run_check()
    check("1. a Mac with neither Docker nor Lima: FAIL, pointing to get_lima.sh, non-zero",
          r.returncode != 0 and "FAIL  workspace tool: neither Docker nor Lima is on this Mac" in r.stdout
          and "get_lima.sh" in r.stdout, r.stdout)
    r = run_check(system="Linux", machine="x86_64")
    check("1. Linux with neither: FAIL, pointing to Docker Engine", r.returncode != 0 and "docker.io" in r.stdout,
          r.stdout)
    r = run_check(docker="stopped")
    check("1. Docker installed but not running: FAIL, start it", r.returncode != 0 and "not running" in r.stdout,
          r.stdout)
    for tool in ("docker", "lima"):
        r = run_check(free_gb=22, **{tool: probe_output()})
        check(f"1. 22 GB free (the volunteer's machine), {tool}: FAIL disk, with the honest breakdown, "
              "and no guest is created",
              r.returncode != 0 and "FAIL  disk: 22 GB free" in r.stdout and "about 15 GB" in r.stdout
              and "about 3 GB" in r.stdout and "no test guest was created" in r.stdout and not created(r.calls)
              and " start" not in r.calls and " shell" not in r.calls, (r.stdout, r.calls))
    r = run_check(net="down", docker=probe_output())
    check("1. this terminal cannot reach github.com: FAIL network, naming the possible cause",
          r.returncode != 0 and "FAIL  network (this terminal)" in r.stdout and "may be blocking" in r.stdout
          and "Network" in r.stdout, r.stdout)
    r = run_check(net="http-error", docker=probe_output())
    check("1. github.com answers with an HTTP error: FAIL (the check uses curl -f), labelled an HTTPS request",
          r.returncode != 0 and "FAIL  network (this terminal): an HTTPS request to github.com failed" in r.stdout,
          r.stdout)

    for tool in ("docker", "lima"):
        r = run_check(pre=("qpcp", "qpcp-check"), **{tool: probe_output()})
        names = created(r.calls)
        check(f"1. {tool}, guest reaches every host: only PASS, exit 0, each probe labelled for what it measures",
              r.returncode == 0 and "FAIL" not in r.stdout and "name resolves and its TCP port opens" in r.stdout
              and "no HTTPS request is made from the guest" in r.stdout, (r.stdout, r.calls))
        check(f"1. {tool}: one guest, under a name of this run's own, is created and deleted; others are untouched",
              len(names) == 1 and re.fullmatch(r"qpcp-check-\d+-\d+", names[0]) is not None
              and r.guests == ["qpcp", "qpcp-check"] and "delete -f qpcp-check\n" not in r.calls
              and "rm -f qpcp-check\n" not in r.calls and "qpcp-check" + "\n" not in "".join(
                  l.split()[-1] + "\n" for l in r.calls.splitlines() if " delete " in l or " rm " in l),
              (names, r.guests, r.calls))
        check(f"1. {tool}: the output says the Ubuntu image stays, and how to remove it",
              ("limactl prune" if tool == "lima" else "docker image rm ubuntu:24.04") in r.stdout, r.stdout)
    r = run_check(lima=probe_output())
    check("1. the Lima guest has no host folders and no agent forwarding",
          ".mounts = [] | .ssh.forwardAgent = false" in r.calls, r.calls)

    for tool in ("docker", "lima"):
        bad = {
            "reports success for one host, then exits non-zero":
                "echo 'probe github.com resolve=ok tcp443=ok'; exit 3\n",
            "reports every host, then exits non-zero": probe_output(then="exit 1"),
            "leaves out one host's line": probe_output(skip=("cache.mathlib.org",)),
            "reports one host twice": probe_output(extra=("github.com",)),
            "reports a host it was not asked about": probe_output(extra=("example.com",)),
            "prints nothing": "exit 0\n",
        }
        for what, guest in bad.items():
            r = run_check(**{tool: guest})
            check(f"2. {tool}: a guest that {what}: FAIL guest network, never PASS",
                  r.returncode != 0 and "FAIL  guest network: the probe did not report cleanly" in r.stdout
                  and "PASS  guest network" not in r.stdout and r.guests == [], (r.stdout, r.guests))
        r = run_check(**{tool: probe_output(failing=("cache.mathlib.org",))})
        check(f"2. {tool}: cache.mathlib.org's TCP port does not open: FAIL, naming it and what failed",
              r.returncode != 0 and "FAIL  guest network: cache.mathlib.org (TCP port does not open)" in r.stdout,
              r.stdout)
        r = run_check(**{tool: probe_output(unresolved=("github.com",))})
        check(f"2. {tool}: github.com does not resolve in the guest: FAIL, saying so",
              r.returncode != 0 and "github.com (name does not resolve)" in r.stdout, r.stdout)
    text = (ROOT / "scripts" / "workspace_check.sh").read_text()
    check("2. every probe has a time limit (curl --max-time on the host; timeout in the guest)",
          "--max-time 15" in text and text.count("timeout 10 ") == 2 and "curl -fsS" in text, "")

    r = run_check(lima="nostart")
    check("1. Lima that cannot create a guest: FAIL guest, and nothing is deleted that was not created",
          r.returncode != 0 and "FAIL  guest: lima could not start a guest" in r.stdout and " delete " not in r.calls,
          (r.stdout, r.calls))
    r = run_check(lima="partial", pre=("qpcp",))
    check("1. Lima whose create fails halfway: FAIL guest, and the half-made guest (this run's own) is deleted",
          r.returncode != 0 and "FAIL  guest" in r.stdout and r.guests == ["qpcp"], (r.stdout, r.guests, r.calls))
    for tool in ("docker", "lima"):
        r = run_check(nodelete=True, **{tool: probe_output()})
        n0 = (created(r.calls) or ["(none created)"])[0]
        how = f"docker rm -f {n0}" if tool == "docker" else f"delete -f {n0}"
        check(f"1. {tool}: a guest that cannot be deleted: FAIL cleanup, with its exact name and the command",
              r.returncode != 0 and f"FAIL  cleanup: the test guest {n0} could not be deleted" in r.stdout
              and how in r.stdout and "now deleted" not in r.stdout, r.stdout)

    # Interrupted while the guest runs: the run's own guest is deleted on the way out; others are untouched.
    for tool in ("docker", "lima"):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            env = check_env(t, **{tool: "sleep 3\n" + probe_output()})
            (t / "guests" / "qpcp").touch()
            p = subprocess.Popen([shutil.which("bash"), str(ROOT / "scripts" / "workspace_check.sh")], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(100):
                if len(list((t / "guests").iterdir())) > 1:
                    break
                time.sleep(0.1)
            time.sleep(0.3)
            p.send_signal(signal.SIGINT)
            out, _ = p.communicate(timeout=30)
            left = sorted(x.name for x in (t / "guests").iterdir())
            check(f"1. {tool}: interrupted while its guest runs: that guest is deleted, the other is not",
                  p.returncode == 130 and left == ["qpcp"], (p.returncode, left, out))

    # Two runs at once, against the same Docker or Lima: distinct guests, each deletes only its own.
    for tool in ("docker", "lima"):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            env = check_env(t, **{tool: "sleep 1\n" + probe_output()})
            (t / "guests" / "qpcp").touch()
            ps = [subprocess.Popen([shutil.which("bash"), str(ROOT / "scripts" / "workspace_check.sh")], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
            outs = [p.communicate(timeout=60)[0] for p in ps]
            calls = (t / "calls").read_text()
            names = created(calls)
            left = sorted(x.name for x in (t / "guests").iterdir())
            check(f"1. {tool}: two runs at once both pass, with two different guests, both deleted",
                  all(p.returncode == 0 for p in ps) and len(set(names)) == 2 and left == ["qpcp"],
                  (outs, names, left))


def run_get_lima(system="Darwin", machine="arm64", sha_ok=False, tar="ok", existing=False):
    """tar: "ok" (unpacks a limactl), "fails" (unpacks part, then fails), "interrupted" (unpacks part, and the
    run is interrupted), "empty" (unpacks no limactl)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        setup = t / "home" / "qpcp-setup"
        if existing:
            (setup / "lima" / "bin").mkdir(parents=True)
            (setup / "lima" / "bin" / "limactl").write_text(f'#!/bin/sh\ntouch "{t}/ran-existing"\n')
            (setup / "lima" / "bin" / "limactl").chmod(0o755)
        unpack = ('while [ $# -gt 0 ]; do [ "$1" = -C ] && { shift; d="$1"; }; shift; done\n'
                  'mkdir -p "$d/bin"; printf "#!/bin/sh\\necho limactl version 2.3.0\\n" > "$d/bin/limactl"; '
                  'chmod 755 "$d/bin/limactl"\n')
        b = stubs(t, {
            "uname": f'case "$1" in -s) echo {system};; -m) echo {machine};; esac\n',
            "curl": f'for a in "$@"; do last="$a"; done; echo "$last" >> "{t}/urls"\n'
                    'while [ $# -gt 0 ]; do [ "$1" = -o ] && { shift; echo x > "$1"; }; shift; done\n',
            "shasum": f'cat >> "{t}/checked"; exit {0 if sha_ok else 1}\n',
            "tar": {"ok": unpack, "fails": unpack + "exit 1\n", "interrupted": unpack + "kill -TERM $PPID\n",
                    "empty": 'exit 0\n'}[tar],
        })
        env = {"PATH": str(b), "HOME": str(t / "home")}
        r = subprocess.run([shutil.which("bash"), str(ROOT / "scripts" / "get_lima.sh")], env=env, capture_output=True,
                           text=True, timeout=60)
        read = lambda n: (t / n).read_text() if (t / n).exists() else ""
        r.urls, r.checked = read("urls"), read("checked")
        r.installed = (setup / "lima" / "bin" / "limactl").exists()
        r.leftover = sorted(p.name for p in setup.iterdir() if p.name.startswith(".get_lima")) if setup.exists() else []
        r.ran_existing = (t / "ran-existing").exists()
        return r


def test_get_lima():
    text = (ROOT / "scripts" / "get_lima.sh").read_text()
    sums = dict(re.findall(r'^LIMA_SHA256_(ARM64|X86_64)="([0-9a-f]{64})"$', text, re.M))
    check("3. get_lima.sh pins a Lima version and a SHA-256 for each Mac architecture",
          re.search(r'^LIMA_VERSION="\d+\.\d+\.\d+"$', text, re.M) is not None and set(sums) == {"ARM64", "X86_64"}
          and len(set(sums.values())) == 2, sums)
    check("3. get_lima.sh never uses sudo, Homebrew or a shell startup file",
          not re.search(r"\bsudo\b|\bbrew\b|\.zshrc|\.bash_profile|\.profile", text.split("set -euo pipefail", 1)[1]),
          "")
    for machine, key in (("arm64", "ARM64"), ("x86_64", "X86_64")):
        r = run_get_lima(machine=machine)
        check(f"3. get_lima.sh on a {machine} Mac: fetches that archive, checks that hash, installs nothing on failure",
              r.urls.strip().endswith(f"/lima-2.3.0-Darwin-{machine}.tar.gz") and sums[key] in r.checked
              and r.returncode != 0 and not r.installed and r.leftover == [], (r.returncode, r.urls, r.checked, r.stderr))
    for system, machine in (("Linux", "x86_64"), ("Darwin", "ppc")):
        r = run_get_lima(system, machine)
        check(f"3. get_lima.sh on {system} {machine}: refused before any download",
              r.returncode != 0 and r.urls == "" and not r.installed, (r.returncode, r.urls, r.stderr))
    r = run_get_lima(sha_ok=True)
    check("3. get_lima.sh, checksum and unpacking good: installed, runs the new limactl, no temporary folder left",
          r.returncode == 0 and r.installed and "SHA-256 checked" in r.stdout and "limactl version 2.3.0" in r.stdout
          and r.leftover == [], (r.returncode, r.stdout, r.stderr, r.leftover))
    r = run_get_lima(sha_ok=True, existing=True)
    check("3. get_lima.sh with ~/qpcp-setup/lima already there: stops, downloads nothing, runs nothing from it",
          r.returncode != 0 and "already exists" in r.stderr and r.urls == "" and not r.ran_existing,
          (r.returncode, r.stderr, r.urls, r.ran_existing))
    for tar, what in (("fails", "an extraction that fails partway"), ("interrupted", "an interrupted extraction"),
                      ("empty", "an archive with no limactl")):
        r = run_get_lima(sha_ok=True, tar=tar)
        check(f"3. get_lima.sh after {what}: nothing half-installed, no temporary folder left",
              r.returncode != 0 and not r.installed and r.leftover == [], (r.returncode, r.stderr, r.installed, r.leftover))


def test_docs():
    join = (ROOT / "JOIN.md").read_text()
    flat = lambda x: re.sub(r"\s+", " ", x)
    front = join.index("## Before anything else")
    check("4. JOIN.md checks the machine before anything else (before the revision check and Two places)",
          front < join.index("## Which revision") < join.index("## Two places"), "")
    sec = join[front:join.index("## A machine with nothing installed")]
    check("4. the first section tells the agent to stop there, before reading further, and names the options",
          "Otherwise stop here." in sec and 'Do not go past "Network"' in sec and "get_lima" in join
          and "Network" in sec, "")
    check("4. the first section's commands only read (docker info, limactl lookup, df, curl -f to github.com)",
          all(c in sec for c in ("docker info", "command -v limactl", "df -h ~", "curl -fsS -o /dev/null")), "")
    check("4. the guide says 25 GB on the host, workspace plus downloads",
          "25 GB" in sec and "about 3 GB" in join, "")
    check("4. the no-network stop is not final once the owner has chosen the manual route",
          "This stop is not final" in flat(sec) and "manual route" in flat(sec), "")
    net = join[join.index("## Network"):join.index("## Which revision")]
    check("4. Network: the sandbox MAY be the cause; a working browser does not establish it",
          "your own sandbox may be blocking access" in flat(net) and "does not establish it" in flat(net)
          and "almost always" not in join and "usual cause" not in join, "")
    check("4. Network: names both options, and forbids unapproved overrides",
          "Could not resolve host: github.com" in net and "(a)" in net and "(b)" in net
          and "never run a command in this guide with a sandbox override" in flat(net), "")
    boundary = ("Keep the agent's existing restrictions in place. If you choose the manual route, create the "
                "disposable workspace, verify its isolation, and complete the network-dependent setup inside it "
                "yourself. The agent may resume at the S060 practice run if its existing permissions allow local "
                "work in the prepared guest. If another step needs a download, return that step to the owner. If "
                "the agent cannot access the guest, stop. This handoff is untested with Codex.")
    check("5. Network (b): the boundary and the resumption point, as the reviewer gave them", boundary in flat(net), "")
    steps = [net.find(x) for x in ("1. **Check the machine", "2. **Create the guest", "3. **Verify its isolation",
                                    "4. **Install the tools", "5. **Clone, and download Lean and Mathlib")]
    check("5. Network (b): the owner's network-dependent steps, in order, with their commands",
          -1 not in steps and steps == sorted(steps) and "limactl create --yes --name=qpcp" in net and "sudo apt-get install" in net
          and '"Set up (once)"' in net and "resume at \"Practice run\"" in flat(net), steps)
    setups = re.findall(r"^```\nbash -euo pipefail -s <<'SETUP'\n.*?\nSETUP\n```$", join, re.S | re.M)
    check("5. Network (b) step 5 gives the setup script in full, identical to \"Set up (once)\", at column 0 (a "
          "heredoc's end must be)", len(setups) == 2 and setups[0] == setups[1]
          and -1 < net.find("5. **Clone") < net.find(setups[0]), len(setups))
    check("5. Network (b): the resuming agent reads the rest of the file first",
          "First read the rest of this file" in net, "")
    check("4. JOIN.md never tells an agent to use a full-access or bypass mode",
          not re.search(r"danger-full-access|--dangerously|--yolo|bypass.{0,20}sandbox", join, re.I), "")
    check("4. removing everything also removes ~/qpcp-out", "rm -rf ~/qpcp-setup ~/qpcp-out" in join, "")
    check("4. the guide and the check say to run the check again after a fix",
          "run it again" in sec and "run this again" in (ROOT / "scripts" / "workspace_check.sh").read_text(), "")
    check("4. the status file is read after setup, in the workspace",
          "Once the setup has run, look at the state of the project first, in the" in join, "")
    check("4. the untested cases are named (Windows, Intel Macs, Docker Desktop)",
          all(w in join for w in ("Windows", "Intel", "Docker Desktop")), "")
    check("1. the guide says Docker keeps its pulled image as Lima keeps its cache, and how to remove each",
          "limactl prune" in flat(sec) and "docker image rm ubuntu:24.04" in flat(sec), "")

    # Downloading, reading and running are separate steps; a failed download leaves nothing to run.
    def separated(text, script):
        blocks = re.findall(r"```\n(.*?)```", text.replace("\n  ", "\n"), re.S)
        dl = [b for b in blocks if f"/scripts/{script}" in b]
        run = [b for b in blocks if f"bash {script}" in b]
        return (len(dl) == 1 and len(run) == 1 and dl[0] != run[0] and f"rm -f {script} {script}.part" in dl[0]
                and f"curl -fsSL -o {script}.part " in dl[0] and f"&& mv {script}.part {script}\n" in dl[0]
                and dl[0].index(f"rm -f {script}") < dl[0].index("curl") and f"bash {script}" not in dl[0]
                and text.index(dl[0][:40]) < text.index(run[0]))
    for script in ("workspace_check.sh", "get_lima.sh"):
        check(f"4. JOIN.md: {script} is downloaded (after removing any old copy), read, then run, separately",
              separated(join, script) and f"less ~/qpcp-setup/{script}" in join, "")
    readme = (ROOT / "README.md").read_text()
    pins = set(re.findall(r"qpcp-proofs/([0-9a-f]{40})/(?:JOIN\.md|scripts/workspace_check\.sh)", readme))
    check("4. README.md shows the owner's check beside the agent instruction, at the same pin as JOIN.md",
          "scripts/workspace_check.sh" in readme and len(pins) == 1
          and readme.index("workspace_check.sh") < readme.index("Fetch and follow"), pins)
    check("4. README.md: the check is downloaded, read, then run, separately",
          separated(readme, "workspace_check.sh") and "less ~/qpcp-setup/workspace_check.sh" in readme, "")
    check("4. README.md: the sandbox MAY be blocking access",
          "the agent's sandbox may be blocking access; a working browser does not establish the cause" in flat(readme)
          and "is blocking the network" not in readme, "")
    index = (ROOT / "docs" / "index.html").read_text()
    script = index[index.index('getElementById("check-cmd")'):]
    script = script[:script.index(";\n")]
    check("4. the homepage: download (removing any old copy), read, then run, as separate blocks, before the agent "
          "instruction, from the same pinned commit",
          index.index('id="check-cmd"') < index.index('id="check-run"') < index.index('id="join-cmd"')
          and 'Q.joinUrl.replace(/JOIN\\.md$/, "scripts/workspace_check.sh")' in script
          and "rm -f workspace_check.sh workspace_check.sh.part" in script and "bash workspace_check.sh" not in script
          and '"curl -fsSL -o workspace_check.sh.part "' in script
          and '" && mv workspace_check.sh.part workspace_check.sh"' in script
          and "Read it before running it" in index, script)
    check("4. the homepage: the sandbox MAY be blocking access",
          "sandbox may be blocking access; a working browser does not establish the cause" in index
          and "is blocking the network" not in index, "")


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
