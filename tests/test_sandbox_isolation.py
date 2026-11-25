#!/usr/bin/env python3
"""What a sandbox of scripts/sandbox_verify.py can and cannot reach. Needs real bubblewrap.

    python3 -I tests/test_sandbox_isolation.py

Runs on ubuntu-latest in the attack-tests job. Without bubblewrap it FAILS
(it does not skip): these properties cannot be checked any other way.

  1. read canary: a random token written to the runner's home directory and to
     the checkout's .git directory cannot be read inside the sandbox and
     appears nowhere in the step's output or log;
  2. sockets: a listening Unix socket on the host (in /tmp, and in the work
     directory's parent, which the sandbox does not mount) cannot be
     connected to, nor can a listening abstract-namespace Unix socket (no
     file at all: only the sandbox's own network namespace keeps it out),
     and /var/run/docker.sock and /run/docker.sock do not exist;
  3. the sandbox's / contains only the expected entries;
  4. a step that writes past its file-size limit is reported as "wrote a file
     larger than N bytes", and the file stops at exactly N bytes;
  5. steps that sleep forever, run from thread-pool workers (several at
     once), are killed and reported as timed out, and leave no process behind;
  6. a sandboxed program that exits 125 on purpose (and prints what the
     launcher would) is a rejection, "failed (exit 125)", not a fault; only
     a real launcher failure, reported in its status file, is a fault.
"""

import concurrent.futures as cf
import faulthandler
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
faulthandler.dump_traceback_later(900, exit=True)  # a hung Popen fails the test instead of the job
fails = 0


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {detail}"))


PROBE = r'''
import json, os, socket, sys
args = json.loads(sys.argv[1])
res = {"read": {}, "connect": {}, "exists": {}}
for p in args["read"]:
    try:
        res["read"][p] = open(p).read()
    except OSError as e:
        res["read"][p] = f"error: {type(e).__name__}"
for p in args["connect"]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect("\0" + p[1:] if p.startswith("@") else p)
        res["connect"][p] = "connected"
    except OSError as e:
        res["connect"][p] = f"error: {type(e).__name__}"
    finally:
        s.close()
for p in args["exists"]:
    res["exists"][p] = os.path.lexists(p)
res["root"] = sorted(os.listdir("/"))
res["env"] = dict(os.environ)
print(json.dumps(res))
'''


def main():
    if not shutil.which("bwrap"):
        print("FAIL  bubblewrap (bwrap) is not installed: these tests need a real sandbox and cannot run here")
        return 1
    home = Path.home()
    base = Path(tempfile.mkdtemp(prefix="qpcp-isolation-", dir=home))
    os.environ["RUNNER_TEMP"] = str(base)  # Env's work directory: base/qpcp-verify
    spec = importlib.util.spec_from_file_location("sandbox_verify", ROOT / "scripts" / "sandbox_verify.py")
    sv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sv)
    sv.LIMITS.update({"probe": (120, 10_000_000), "fsize": (120, 1_000_000), "sleep": (5, 1_000_000)})
    env = sv.Env(sandbox=True)
    env.setup()

    token = secrets.token_hex(16)
    canaries = [home / f"qpcp_canary_{token[:8]}", ROOT / ".git" / f"qpcp_canary_{token[:8]}"]
    for c in canaries:
        c.write_text(token)
    servers, sockets = [], [Path(f"/tmp/qpcp-sock-{token[:8]}"), base / f"sock-{token[:8]}"]
    for path in sockets:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(path))
        s.listen(5)
        servers.append(s)
    abstract = f"@qpcp-abstract-{token[:8]}"  # "@" stands for the leading NUL byte
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind("\0" + abstract[1:])
    s.listen(5)
    servers.append(s)
    try:
        # The host side really is reachable, so the sandbox's failures mean something.
        for c in canaries:
            check(f"(host) the canary {c} is readable outside", c.read_text() == token)
        for path in sockets:
            t = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                t.connect(str(path))
                check(f"(host) the socket {path} accepts connections outside", True)
            except OSError as e:
                check(f"(host) the socket {path} accepts connections outside", False, e)
            finally:
                t.close()
        t = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            t.connect("\0" + abstract[1:])
            check(f"(host) the abstract socket {abstract} accepts connections outside", True)
        except OSError as e:
            check(f"(host) the abstract socket {abstract} accepts connections outside", False, e)
        finally:
            t.close()

        probe_dir = env.work / "probe"
        probe_dir.mkdir()
        probe = probe_dir / "probe.py"
        probe.write_text(PROBE)
        rw = env.work / "scratch" / "probe"
        rw.mkdir(parents=True)
        out, log = env.work / "logs" / "probe.out", env.work / "logs" / "probe.log"
        args = {"read": [str(c) for c in canaries] + [f"/proc/1/root{c}" for c in canaries]
                + [str(ROOT / ".git" / "config"), str(home / ".gitconfig")],
                "connect": [str(p) for p in sockets] + [abstract, "/var/run/docker.sock", "/run/docker.sock"],
                "exists": ["/var/run/docker.sock", "/run/docker.sock", "/home", "/root", "/run", "/var", "/etc",
                           "/mnt", "/media", "/srv", str(home), str(ROOT), str(ROOT / ".git")]}
        ok, why = env.run_sandboxed("probe", [sys.executable, "-I", env.inside(probe), json.dumps(args)], [rw], log,
                                    stdout_path=out, ro=[probe])
        check("the probe ran in the sandbox", ok, f"{why}: {env.tail_of(log)}")
        res = json.loads(out.read_text()) if ok else {"read": {}, "connect": {}, "exists": {}, "root": []}

        # 1. read canary
        for p in args["read"]:
            got = res["read"].get(p, "")
            check(f"1. cannot read {p} ({got})", got.startswith("error"), got[:80])
        seen = [f for f in (out, log) if token in f.read_text(errors="replace")]
        seen += [f for f in rw.rglob("*") if f.is_file() and token in f.read_text(errors="replace")]
        check("1. the token appears nowhere in the step's output, log or directory", not seen, seen)
        # LC_CTYPE: Python itself sets it at startup under the C locale (PEP 538 locale coercion).
        check("1. the step's environment is only what run_sandboxed sets (and Python's own LC_CTYPE)",
              set(res.get("env", {})) <= {"PATH", "LEAN_PATH", "HOME", "PWD", "LC_CTYPE"}, sorted(res.get("env", {})))

        # 2. sockets
        for p in args["connect"]:
            got = res["connect"].get(p, "")
            check(f"2. cannot connect to {p} ({got})", got.startswith("error"), got)
        for p in ("/var/run/docker.sock", "/run/docker.sock"):
            check(f"2. {p} does not exist inside", res["exists"].get(p) is False, res["exists"].get(p))
        if os.path.exists("/var/run/docker.sock"):
            check("2. (host) /var/run/docker.sock exists outside, so the check above means something", True)
        else:
            print("  note  /var/run/docker.sock does not exist on this host; only its absence inside was checked")
        for p in args["exists"][2:]:
            check(f"2./3. {p} is not visible inside", res["exists"].get(p) is False, res["exists"].get(p))

        # 3. directory listing
        expected = {"usr", "dev", "proc", "tmp", "qpcp"} | {d for d in ("bin", "sbin", "lib", "lib64")
                                                            if os.path.lexists(f"/{d}")}
        check(f"3. / inside is exactly {sorted(expected)}", set(res["root"]) == expected, res["root"])
        ok2, _ = env.run_sandboxed("probe", ["/usr/bin/ls", "-A", f"{sv.SANDBOX}", f"{sv.SANDBOX}/work"], [rw],
                                   log, stdout_path=out)
        check(f"3. /qpcp holds only the toolchain and the step's work files: {out.read_text().split()}",
              ok2 and set(out.read_text().split()) <= {"/qpcp:", "/qpcp/work:", "toolchain", "work", "scratch"},
              out.read_text())

        # 4. file-size limit (in bytes, as before: LIMITS["fsize"] = 1_000_000)
        big = rw / "big"
        ok, why = env.run_sandboxed("fsize", ["/usr/bin/dd", "if=/dev/zero", f"of={env.inside(big)}", "bs=500000",
                                              "count=4"], [rw], log)
        check(f"4. writing past the limit is reported ({why})",
              not ok and why == "fsize wrote a file larger than 1000000 bytes", why)
        check("4. the file stops at exactly the limit, in bytes",
              big.is_file() and big.stat().st_size == 1_000_000, big.stat().st_size if big.exists() else None)
        big.unlink(missing_ok=True)
        ok, why = env.run_sandboxed("fsize", ["/usr/bin/dd", "if=/dev/zero", f"of={env.inside(big)}", "bs=500000",
                                              "count=2"], [rw], log)
        check("4. writing exactly the limit is allowed", ok and big.stat().st_size == 1_000_000, why)

        # 5. timeout, from thread-pool workers, several at once
        marker = str(900000 + secrets.randbelow(99999))
        start = time.monotonic()
        with cf.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda i: env.run_sandboxed("sleep", ["/usr/bin/sleep", marker], [rw],
                                                                env.work / "logs" / f"sleep{i}.log"), range(4)))
        took = time.monotonic() - start
        check(f"5. four sleeping steps in a thread pool all time out ({results[0][1]}, {took:.0f} s)",
              all(r == (False, "sleep timed out after 5 s") for r in results) and took < 60, results)
        time.sleep(1)
        left = subprocess.run(["pgrep", "-f", f"sleep {marker}"], capture_output=True, text=True).stdout.split()
        check("5. no sleeping process is left behind", not left, left)

        # 6. exit 125 from the sandboxed program is the program's, not the launcher's
        try:
            got = env.run_sandboxed("probe", ["/usr/bin/sh", "-c", "echo 'limit_exec: OSError: forged' >&2; exit 125"],
                                    [rw], log)
            check(f"6. a sandboxed program exiting 125 is a rejection ({got[1]})",
                  got == (False, "probe failed (exit 125)"), got)
        except sv.Fault as f:
            check("6. a sandboxed program exiting 125 is a rejection", False, f"raised a fault: {f}")
        real, env.bwrap = env.bwrap, str(base / "no-such-bwrap")
        try:
            got = env.run_sandboxed("probe", ["/usr/bin/true"], [rw], log)
            check("6. a launcher that cannot start the sandbox is a fault", False, f"returned {got}")
        except sv.Fault as f:
            check(f"6. a launcher that cannot start the sandbox is a fault ({f})", "could not start" in str(f), f)
        finally:
            env.bwrap = real
    finally:
        for s in servers:
            s.close()
        for p in sockets:
            p.unlink(missing_ok=True)
        for c in canaries:
            c.unlink(missing_ok=True)
        shutil.rmtree(base, ignore_errors=True)
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
