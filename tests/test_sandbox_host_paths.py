#!/usr/bin/env python3
"""The host never touches a path a sandbox could have planted (scripts/sandbox_verify.py).

    python3 -I tests/test_sandbox_host_paths.py

Runs in the attack-tests job on ubuntu-latest. Test (a) needs real bubblewrap
and FAILS without it (it does not skip); (b) and (e) run anywhere.

  a. symlink handoff: a fake toolchain whose lean, leanchecker, leanexport and
     nanoda_bin each plant, in every directory they can write, symlinks named
     like every file the host captures, copies or reads (export.ndjson,
     module.olean, canonical.ndjson, every capture and log name), all
     pointing at a canary file on the host. The real compile, replay, export,
     nanoda and preview steps then run with it, one after another. The
     canary's contents and size must be unchanged, its token must not reach
     any host-side file, and take() must refuse a planted canonical.ndjson;
  b. run_sandboxed refuses (a Fault) a stdout_path or log inside a directory
     that was ever given to a sandbox writable, and a writable directory
     outside out/, exp/ and scratch/;
  e. a LEAN_PATH entry outside .lake/packages, .lake/build and the toolchain
     is a Fault that names it, also when it is reached through a symlink
     inside .lake/packages.
"""

import hashlib
import importlib.util
import os
import secrets
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
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {detail}"))


def load():
    spec = importlib.util.spec_from_file_location("sandbox_verify", ROOT / "scripts" / "sandbox_verify.py")
    sv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sv)
    return sv


def new_env(sv, base, sandbox):
    os.environ["RUNNER_TEMP"] = str(base)
    env = sv.Env(sandbox=sandbox)
    env.setup()
    return env


PLANT = r'''#!/usr/bin/sh
# Plant symlinks to the canary under every name the host might open, in every
# directory this step can write.
for d in $(/usr/bin/find /qpcp /tmp -type d 2>/dev/null); do
  [ -w "$d" ] || continue
  for n in NAMES; do /usr/bin/ln -sfn "CANARY" "$d/$n" 2>/dev/null; done
done
'''


def test_handoff(sv, base):
    if not shutil.which("bwrap"):
        check("a. symlink handoff", False, "bubblewrap (bwrap) is not installed: this test needs a real sandbox")
        return
    env = new_env(sv, base, sandbox=True)
    token = secrets.token_hex(16)
    canary = base / "canary.txt"
    canary.write_text(f"canary {token}\n")
    before = (canary.stat().st_size, hashlib.sha256(canary.read_bytes()).hexdigest())

    mod = "QPCP.Proofs.S030"
    steps = ["compile", "replay", "export", "canon", "verify", "nanoda", "reference"]
    names = ["export.ndjson", "module.olean", "canonical.ndjson", "preview.out", "preview.log", "steps.log",
             f"{mod}.raw.ndjson", f"{mod}.olean", f"{mod}.ndjson", f"{mod}.nanoda.json"]
    names += [f"{mod}.{s}.{x}" for s in steps for x in ("out", "log", "launcher")]
    fake = base / "fake-toolchain"
    (fake / "bin").mkdir(parents=True)
    plant = PLANT.replace("NAMES", " ".join(names)).replace("CANARY", str(canary))
    for tool, tail in (("lean", "exit 0\n"), ("leanchecker", "exit 0\n"),
                       ("leanexport", 'echo \'{"meta":{}}\'\nexit 0\n'), ("nanoda_bin", "echo planted\nexit 0\n")):
        (fake / "bin" / tool).write_text(plant + tail)
        os.chmod(fake / "bin" / tool, 0o755)
    env.sysroot, env.bin = fake, fake / "bin"

    src = base / "S030.lean"
    src.write_text("theorem QPCP.Proof.S030 : True := trivial\n")
    m = sv.Module("proof", "S030", src)
    v = sv.Verifier(env, {m.name: m}, 1)

    staged = v.compile_one(m)
    check(f"a. compile: a planted module.olean is refused ({m.reason})",
          staged is None and "no usable compiled file" in m.reason, m.reason)
    raw = None
    try:
        raw = v.replay_and_export(m)
        check("a. replay then export: the export is the step's own stdout, in capture/",
              raw is not None and raw.parent == env.work / "capture" and not raw.is_symlink()
              and raw.read_text().startswith('{"meta"'), raw)
    except sv.Reject as r:
        check("a. replay then export", False, f"rejected: {r}")
    canon = env.work / "canon" / f"{mod}.ndjson"
    canon.write_text('{"meta":{}}\n')
    try:
        v.nanoda(m, canon)
        check("a. nanoda: the fake kernel's output is not an acceptance", False, "accepted")
    except sv.Reject:
        check("a. nanoda ran, and its output was read from capture/ only", True)
    m.export = canon
    sv.write_preview(env, m)
    check("a. preview: the rendering is the step's own stdout",
          (env.work / "result" / "statement-preview.txt").read_text().strip() == "planted",
          (env.work / "result" / "statement-preview.txt").read_text()[:80])

    # take() refuses a planted canonical.ndjson (the canon step's sandbox output).
    d = env.fresh_dir("scratch", f"{mod}.canon")
    (d / "canonical.ndjson").symlink_to(canary)
    why = sv.take(d / "canonical.ndjson", env.work / "canon" / "taken.ndjson", 10_000)
    check(f"a. take() refuses a symlinked canonical.ndjson ({why})",
          why is not None and not (env.work / "canon" / "taken.ndjson").exists(), why)
    os.mkfifo(d / "fifo.ndjson")
    why = sv.take(d / "fifo.ndjson", env.work / "canon" / "fifo.ndjson", 10_000)
    check(f"a. take() refuses a FIFO without blocking ({why})", why is not None, why)

    after = (canary.stat().st_size, hashlib.sha256(canary.read_bytes()).hexdigest())
    check("a. the canary's contents and size are unchanged", after == before, (before, after))
    leaked = [p for p in env.work.rglob("*") if p.is_file() and not p.is_symlink()
              and token in p.read_text(errors="replace")]
    check("a. the canary's token is in no host-side file", not leaked, leaked)
    planted = [p for p in env.work.rglob("*") if p.is_symlink()]
    print(f"  note  symlinks left in the work directory after the steps: {len(planted)}"
          f" (each step's directory is deleted after it; take()'s test directory remains)")


def test_assertion(sv, base):
    env = new_env(sv, base, sandbox=False)
    sv.LIMITS["t"] = (30, 1_000_000)
    d = env.fresh_dir("scratch", "first")
    ok, _ = env.run_sandboxed("t", ["/bin/sh", "-c", "exit 0"], [d], env.log_path("first.log"))
    check("b. an ordinary step runs", ok)
    for desc, kw in (("a stdout_path inside a directory that was writable before", dict(stdout_path=d / "x.out")),
                     ("a log inside a directory that was writable before", dict(log=d / "x.log")),
                     ("a stdout_path inside this step's own writable directory", "own"),
                     ("a stdout_path outside capture/", dict(stdout_path=env.work / "result" / "x.out")),
                     ("a writable directory outside out/, exp/ and scratch/", "rwlogs")):
        args = dict(log=env.log_path("second.log"))
        rw = [env.fresh_dir("scratch", "second")]
        if kw == "own":
            args["stdout_path"] = rw[0] / "x.out"
        elif kw == "rwlogs":
            rw = [env.work / "logs"]
        else:
            args.update(kw)
        try:
            got = env.run_sandboxed("t", ["/bin/sh", "-c", "exit 0"], rw, args.pop("log"), **args)
            check(f"b. refuses {desc}", False, f"ran: {got}")
        except sv.Fault as f:
            check(f"b. refuses {desc} ({f})", True)
    check("b. the refused paths were never created",
          not (d / "x.out").exists() and not (d / "x.log").exists() and not (env.work / "result" / "x.out").exists())


def test_lean_path(sv, base):
    env = sv.Env.__new__(sv.Env)
    os.environ["RUNNER_TEMP"] = str(base)
    env.__init__(sandbox=False)
    real = env.lake
    link = ROOT / ".lake" / "packages" / f"qpcp-test-link-{secrets.token_hex(4)}"
    outside = base / "outside-lib"
    outside.mkdir()
    try:
        link.symlink_to(outside)
        for desc, extra in (("an entry outside the allowed locations", "/opt/qpcp-not-allowed/lib/lean"),
                            ("an entry reached through a symlink in .lake/packages", str(link / "lib"))):
            def lake(*args, timeout=3600, extra=extra):
                r = real(*args, timeout=timeout)
                if args == ("env", "printenv", "LEAN_PATH"):
                    r = subprocess.CompletedProcess(r.args, r.returncode, r.stdout.strip() + ":" + extra + "\n", r.stderr)
                return r
            env.lake = lake
            try:
                env.setup()
                check(f"e. {desc} is a fault", False, "setup accepted it")
            except sv.Fault as f:
                check(f"e. {desc} is a fault that names it ({f})", extra in str(f), f)
        env.lake = real
        env.setup()
        check(f"e. the real LEAN_PATH is accepted: {len(env.packages)} mounted, "
              f"{len(env.absent_entries)} allowed but absent", bool(env.packages))
        for host, mount in env.packages:
            print(f"  note  {mount} <- {host}")
        for e in env.absent_entries:
            print(f"  note  not mounted (does not exist): {e}")
    finally:
        link.unlink(missing_ok=True)


def main():
    sv = load()
    for test in (test_handoff, test_assertion, test_lean_path):
        base = Path(tempfile.mkdtemp(prefix="qpcp-hostpaths-", dir=Path.home()))
        try:
            test(sv, base)
        except Exception as e:  # a crash is a failure, never a skip
            check(f"{test.__name__} crashed", False, f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(base, ignore_errors=True)
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
