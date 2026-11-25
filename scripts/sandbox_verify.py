#!/usr/bin/env python3
"""Verify contributions without ever building one outside a sandbox.

    sandbox_verify.py trusted-build
    sandbox_verify.py record [--only M,M,...] [--shard K/N] [--jobs N] [--replay-only]
    sandbox_verify.py contribution <kind> <ident> <file>
    common options: [--no-sandbox] [--skip-scan-for-tests]

Trust split. Only the maintainer-written modules QPCP.Defs, QPCP.Qudit and
QPCP.Statements, and Mathlib, are ever built outside a sandbox
(`trusted-build`). Every contributed module, under QPCP/Lemmas, QPCP/Proofs or
QPCP/Refutations, merged or new, is handled only inside bubblewrap:

  compile   lean, in import order, one module per sandbox; the only writable
            directory is that module's own output folder, and earlier outputs
            are mounted read-only, so no module can change another's result;
  replay    leanchecker on the module, in a fresh sandbox (an early reject);
  export    leanexport of the module's result constant, to text.

The text export is then checked by trusted code, each step in a fresh
sandbox of its own as well, so that a flaw in a parser cannot reach the host:

  canon     scripts/verify_export.py reads the export strictly and writes it
            again in canonical form; every later step reads only that file;
  nanoda    nanoda_bin, an independent kernel, type-checks the canonical
            export with only propext, Classical.choice and Quot.sound;
  verify    scripts/verify_export.py compares it with a reference exported
            (outside the sandbox, from trusted files only) from the
            maintainer-written modules: the statement, the axioms, the Quot
            declarations and Not, with their whole dependency closure, and,
            for a lemma, everything its definition refers to. Lemmas are
            verified first. A proof or refutation of a contributed lemma is
            then compared with that lemma's verified canonical export as
            well, which is how a contributed statement becomes a trusted
            reference.

No untrusted .olean is read outside a sandbox. A sandbox sees none of the
host beyond an explicit list of read-only mounts (see SYSTEM_MOUNTS and
run_sandboxed): the system's /usr, Lean's toolchain, the Mathlib build, the
step's own input files and its one writable directory, all under /qpcp and
/usr. Nothing from /home, /root, /run, /var, /etc, the checkout or its .git
is visible. Every sandboxed step has a hard timeout (the whole process group
is killed) and a file-size limit (RLIMIT_FSIZE, set by scripts/limit_exec.py,
which then execs the sandbox, so no Python runs between fork and exec), and
every file taken out of a sandbox is size-checked. Every sandboxed step is
listed in logs/steps.log, for the tests.

`record` verifies every contribution in the tree (CI: the maintainer's pull
requests and verify-main). `contribution` verifies one new file, with the
merged modules it imports (CI: contributors' pull requests). --no-sandbox runs
the sandboxed steps unisolated, for development on machines without
bubblewrap; CI never passes it. --skip-scan-for-tests skips the source scanner
so that tests can model a merged file that got past it.

Exit 0 if everything is ACCEPTED, 1 if anything is REJECTED, 2 on a FAULT.
"""

import concurrent.futures as cf
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUSTED_MODULES = ["QPCP.Defs", "QPCP.Qudit", "QPCP.Statements"]
FIXED = ["propext", "Classical.choice", "Quot.sound", "Quot", "Quot.mk", "Quot.lift", "Quot.ind", "Not"]
CONTRIB_FOLDERS = {"lemma": "QPCP/Lemmas", "proof": "QPCP/Proofs", "refutation": "QPCP/Refutations"}
TARGET_NS = {"lemma": "QPCP.Lemma", "proof": "QPCP.Proof", "refutation": "QPCP.Refutation"}

# Limits for sandboxed steps: (timeout seconds, largest file the step may write).
LIMITS = {
    "compile": (1500, 1_000_000_000),
    "replay": (900, 100_000_000),
    "export": (900, 1_000_000_000),
    "canon": (1800, 1_100_000_000),
    "nanoda": (1800, 100_000_000),
    "verify": (1800, 100_000_000),
    "preview": (600, 10_000_000),
}
TRUSTED_EXPORT_TIMEOUT = 1800

# What a sandbox sees of the host system, read-only, and why. Everything else
# it sees is mounted by run_sandboxed under /qpcp: the toolchain, the Mathlib
# build, the step's inputs and its one writable directory. On a merged-/usr
# system (Ubuntu) /bin, /sbin, /lib, /lib64 are symlinks into /usr and are
# recreated as symlinks; on others they are mounted read-only.
SYSTEM_MOUNTS = [
    "/usr",    # the C library, the dynamic loader's libraries, sleep and the
               # system Python with its standard library (verify_export.py)
    "/bin",    # (symlink) /bin/sh-style paths some tools use
    "/sbin",   # (symlink) kept so the merged-/usr layout is complete
    "/lib",    # (symlink) libraries Lean's binaries load (libc, libm, libstdc++)
    "/lib64",  # (symlink) the dynamic loader /lib64/ld-linux-x86-64.so.2
]
SANDBOX = "/qpcp"
# Under the work directory: the only folders a sandbox is ever given writable,
# and the host-only folders the host writes captures and logs to. The host never
# opens a path inside a sandbox-writable directory except through take().
WRITABLE_ROOTS = ("out", "exp", "scratch")
HOST_ONLY = ("src", "lib", "staged", "logs", "capture", "ref", "result", "canon")
LIMIT_EXEC = ROOT / "scripts" / "limit_exec.py"
MAX_DEPS = 5000

spec = importlib.util.spec_from_file_location("qpcp_check", ROOT / "scripts" / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
log_safe = check.log_safe


class Reject(Exception):
    pass


class Fault(Exception):
    pass


def open_new(path):
    """A fresh file for the host to write, created exclusively, never through a symlink."""
    path = Path(path)
    path.unlink(missing_ok=True)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)


def open_regular(path):
    """(fd, size) of a regular file, opened without following a symlink and without
    blocking on a FIFO; None if it is anything else."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        return None
    return fd, st.st_size


def read_tail(path, n):
    """The last n bytes of a file, decoded; read from the end, never the whole file."""
    got = open_regular(path)
    if got is None:
        return ""
    fd, size = got
    try:
        os.lseek(fd, max(0, size - n), os.SEEK_SET)
        chunks, left = [], min(n, size)
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def read_head(path, n):
    """The first n bytes of a file, decoded."""
    got = open_regular(path)
    if got is None:
        return ""
    fd, _ = got
    try:
        chunks, left = [], n
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def take(src, dest, limit):
    """Copy a file a sandbox produced, in its writable directory, to a host-only dest.

    Runs only after that sandbox has exited (bubblewrap's PID namespace ends with
    it, so nothing in it still runs). The file must be a regular file opened
    without following a symlink, its directory must not be a symlink, and its
    size must be within the limit, all checked on the open descriptor before a
    byte is read. Returns None, or why it was refused."""
    src = Path(src)
    if src.parent.is_symlink() or not src.parent.is_dir():
        return "its directory is not a plain directory"
    got = open_regular(src)
    if got is None:
        return "it is missing, a symlink or not a regular file"
    fd, size = got
    try:
        if size > limit:
            return f"it is larger than {limit} bytes"
        out = open_new(dest)
        try:
            copied = 0
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                copied += len(b)
                if copied > limit:
                    return f"it is larger than {limit} bytes"
                os.write(out, b)
        finally:
            os.close(out)
    finally:
        os.close(fd)
    return None


# ---------------------------------------------------------------- environment

class Env:
    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.work = Path(os.environ.get("RUNNER_TEMP") or (ROOT / ".lake")) / "qpcp-verify"
        if str(self.work).startswith("/tmp"):
            raise Fault("the work directory must not be under /tmp, which the sandbox replaces")
        if sandbox:
            self.bwrap = shutil.which("bwrap")
            if not self.bwrap:
                raise Fault("bubblewrap (bwrap) is not installed; refusing to build untrusted code unsandboxed")
            if not shutil.rmtree.avoids_symlink_attacks:
                raise Fault("this Python's shutil.rmtree can follow symlinks; refusing to delete sandbox output with it")
        self.lock = threading.Lock()
        self.rw_ever = set()  # every directory ever given to a sandbox writable, for the life of the Env

    def lake(self, *args, timeout=3600):
        r = subprocess.run(["lake", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return r

    def setup(self):
        r = self.lake("env", "printenv", "LEAN_SYSROOT")
        if r.returncode != 0:
            raise Fault("cannot locate the toolchain")
        self.sysroot = Path(r.stdout.strip()).resolve()
        self.bin = self.sysroot / "bin"
        for tool in ("lean", "leanchecker", "leanexport", "nanoda_bin"):
            if not os.access(self.bin / tool, os.X_OK):
                raise Fault(f"the toolchain has no {tool}")
        r = self.lake("env", "printenv", "LEAN_PATH")
        if r.returncode != 0:
            raise Fault("cannot read LEAN_PATH")
        self.repo_lib = ROOT / ".lake" / "build" / "lib" / "lean"
        entries = [e for e in r.stdout.strip().split(":") if e]
        if str(self.repo_lib) not in entries:
            raise Fault(f"LEAN_PATH does not contain {self.repo_lib}")
        self.trusted_lean_path = ":".join(entries)
        self.package_entries = [e for e in entries if e != str(self.repo_lib)]
        # Every entry must lie, once symlinks are resolved, in this repository's packages
        # or build, or in the toolchain; anything else is a fault, never skipped.
        allowed = [(ROOT / ".lake" / "packages").resolve(), (ROOT / ".lake" / "build").resolve(), self.sysroot]
        for e in self.package_entries:
            resolved = Path(e).resolve()
            if not any(resolved.is_relative_to(a) for a in allowed):
                raise Fault(f"LEAN_PATH entry {e} (resolved: {resolved}) is outside .lake/packages, "
                            f".lake/build and the toolchain; refusing to mount it")
        if self.work.exists():
            shutil.rmtree(self.work)
        for d in (*WRITABLE_ROOTS, *HOST_ONLY):
            (self.work / d).mkdir(parents=True)
        self.lib = self.work / "lib"
        # Inside a sandbox, package i's build is mounted at /qpcp/pkg/i. An allowed entry
        # that does not exist (a package with nothing built, such as Cli) holds no module,
        # so it is not mounted; it is listed in self.absent_entries.
        present = [Path(e).resolve() for e in self.package_entries if Path(e).is_dir()]
        self.absent_entries = [e for e in self.package_entries if not Path(e).is_dir()]
        self.packages = [(p, f"{SANDBOX}/pkg/{i}") for i, p in enumerate(present)]
        if self.sandbox:
            self.sandbox_lean_path = ":".join([p for _, p in self.packages] + [self.inside(self.lib)])
            py = Path(sys.executable).resolve()
            if not py.is_relative_to("/usr") or py.is_relative_to("/usr/local"):
                raise Fault(f"the sandbox runs Python from /usr (not /usr/local) only, not {sys.executable}")
        else:
            self.sandbox_lean_path = ":".join(self.package_entries + [str(self.lib)])

    # ------------------------------------------------------------ trusted build

    def trusted_build(self):
        r = self.lake("build", *TRUSTED_MODULES)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-3000:])
            raise Fault("main's maintainer-written modules do not build")
        # A private copy of exactly those compiled modules seeds the sandbox library.
        for m in TRUSTED_MODULES:
            rel = Path(*m.split("."))
            src_dir = self.repo_lib / rel.parent
            for f in src_dir.glob(rel.name + ".*"):
                if f.is_file():
                    (self.lib / rel.parent).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, self.lib / rel.parent / f.name)

    # ---------------------------------------------------------------- sandbox

    def log_path(self, name):
        """A step's stderr log: in logs/, which no sandbox ever sees."""
        return self.work / "logs" / name

    def capture_path(self, name):
        """A step's stdout capture: in capture/, which no sandbox ever sees writable."""
        return self.work / "capture" / name

    def fresh_dir(self, root, name):
        """A new, empty directory for one sandbox to write, under one of WRITABLE_ROOTS."""
        if root not in WRITABLE_ROOTS:
            raise Fault(f"{root} is not a sandbox-writable folder")
        d = self.work / root / name
        if d.exists() or d.is_symlink():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def inside(self, path):
        """Where a host path is seen inside a sandbox (the same path without one)."""
        path = Path(path)
        if not self.sandbox:
            return str(path)
        for host, mount in ((self.sysroot, f"{SANDBOX}/toolchain"), (self.work, f"{SANDBOX}/work"),
                            (ROOT / "scripts", f"{SANDBOX}/scripts"), (Path("/usr"), "/usr")):
            if path.is_relative_to(host):
                return str(Path(mount) / path.relative_to(host))
        raise Fault(f"{path} is not visible inside the sandbox")

    def mounts(self, ro, rw, lean):
        """bubblewrap's mount arguments: SYSTEM_MOUNTS, the toolchain, for a Lean step
        the Mathlib build and the shared library, the inputs `ro` and the writable `rw`."""
        args = []
        for d in SYSTEM_MOUNTS:
            if os.path.islink(d):
                args += ["--symlink", os.readlink(d), d]
            elif os.path.isdir(d):
                args += ["--ro-bind", d, d]
        # /usr/local holds what the runner image adds (other Pythons, tools); no step uses
        # it, so an empty read-only tmpfs covers it.
        if os.path.isdir("/usr/local"):
            args += ["--tmpfs", "/usr/local", "--remount-ro", "/usr/local"]
        args += ["--ro-bind", str(self.sysroot), f"{SANDBOX}/toolchain"]
        if lean:
            for host, mount in self.packages:
                args += ["--ro-bind", str(host), mount]
            args += ["--ro-bind", str(self.lib), self.inside(self.lib)]
        for f in ro:
            if not Path(f).exists() or Path(f).is_symlink():
                raise Fault(f"sandbox input {f} is missing or a symlink")
            args += ["--ro-bind", str(f), self.inside(f)]
        for d in rw:
            args += ["--bind", str(d), self.inside(d)]
        return args

    def run_sandboxed(self, step, argv, rw, log, stdout_path=None, ro=(), lean=False):
        """Run argv in a fresh sandbox. Returns (ok, reason).

        argv's paths must already be the sandbox's (Env.inside). `ro` lists the
        host files and directories the step reads, `rw` its one writable
        directory, and `lean` mounts the Mathlib build and the shared library."""
        timeout, fsize = LIMITS[step]
        log = Path(log)
        # The host never opens a path inside a directory any sandbox could ever write.
        with self.lock:
            for d in rw:
                d = Path(d)
                if d.is_symlink() or not any(d.parent == self.work / r for r in WRITABLE_ROOTS):
                    raise Fault(f"{d} is not a fresh directory under {', '.join(WRITABLE_ROOTS)}")
                self.rw_ever.add(d.resolve())
            for kind, pth, root in (("log", log, "logs"), ("stdout_path", stdout_path, "capture")):
                if pth is None:
                    continue
                rp = Path(pth).resolve()
                if any(rp.is_relative_to(d) for d in self.rw_ever):
                    raise Fault(f"{kind} {pth} lies inside a directory a sandbox was given writable")
                if rp.parent != (self.work / root).resolve():
                    raise Fault(f"{kind} {pth} is not in the host-only folder {root}/")
        with self.lock, open(self.work / "logs" / "steps.log", "a") as fh:
            fh.write(f"{step} {'sandboxed' if self.sandbox else 'UNSANDBOXED'} {Path(argv[0]).name}"
                     f" {' '.join(Path(a).name for a in argv[1:4])}\n")
        env = {"PATH": f"{self.inside(self.bin)}:/usr/bin", "LEAN_PATH": self.sandbox_lean_path}
        if self.sandbox:
            cmd = [self.bwrap, *self.mounts(ro, rw, lean), "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                   "--remount-ro", "/", "--chdir", "/tmp", "--unshare-all", "--die-with-parent", "--new-session",
                   "--cap-drop", "ALL", "--clearenv"]
            for k, v in {**env, "HOME": "/tmp"}.items():
                cmd += ["--setenv", k, v]
            cmd += ["--", *argv]
            run_env, cwd = {"PATH": "/usr/bin:/bin"}, "/"
        else:
            cmd, run_env, cwd = argv, {**env, "HOME": str(rw[0])}, str(rw[0])
        # The limits are set by a separate launcher that then execs the sandbox:
        # no preexec_fn, which is unsafe in the thread-pool workers that call this.
        # The launcher reports its own failure only in this file, which no sandbox can see.
        status = Path(log).with_suffix(".launcher")
        status.unlink(missing_ok=True)
        cmd = [sys.executable, "-I", str(LIMIT_EXEC), str(fsize), str(status), "--", *cmd]

        # Both are created exclusively (O_EXCL, O_NOFOLLOW, mode 0600) in host-only
        # folders, and the sandbox gets only the descriptors.
        out = open_new(stdout_path) if stdout_path else subprocess.DEVNULL
        err = open_new(log)
        try:
            try:
                p = subprocess.Popen(cmd, stdout=out, stderr=err, env=run_env, cwd=cwd, start_new_session=True)
            except OSError as e:
                raise Fault(f"cannot start the sandbox: {e}")
            try:
                code = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                return False, f"{step} timed out after {timeout} s"
        finally:
            os.close(err)
            if stdout_path:
                os.close(out)
        if status.exists():
            raise Fault(f"the {step} sandbox could not start: {self.tail_of(status)}")
        if code == -signal.SIGXFSZ or code == 128 + signal.SIGXFSZ:
            return False, f"{step} wrote a file larger than {fsize} bytes"
        if code != 0:
            return False, f"{step} failed (exit {code})"
        return True, ""

    def tail_of(self, path, n=400):
        return read_tail(path, n).strip()


# ------------------------------------------------------------------- modules

def module_of(kind, ident):
    return f"{CONTRIB_FOLDERS[kind].replace('/', '.')}.{ident}"


def target_of(kind, ident):
    return f"{TARGET_NS[kind]}.{ident}"


def imports_of(source_text):
    code = check.strip_comments(source_text)
    out = []
    for line in code.splitlines():
        m = re.match(r"^\s*(?:public\s+|private\s+|meta\s+)*import\s+(.*)$", line)
        if m:
            out += m.group(1).split()
    return out


class Module:
    def __init__(self, kind, ident, src_path):
        self.kind, self.ident, self.src = kind, ident, Path(src_path)
        self.name = module_of(kind, ident)
        self.rel = Path(CONTRIB_FOLDERS[kind]) / f"{ident}.lean"
        self.imports = imports_of(self.src.read_text(encoding="utf-8", errors="replace"))
        self.verdict, self.reason = None, ""
        self.export = None          # path of the verified export, once ACCEPTED
        self.deps = []              # for a lemma: what its definition refers to

    def __repr__(self):
        return self.name


def tree_modules():
    mods = {}
    for kind, folder in CONTRIB_FOLDERS.items():
        for path in sorted((ROOT / folder).glob("*.lean")):
            k, ident = check.classify(f"{folder}/{path.name}")
            if k == kind:
                m = Module(kind, ident, path)
                mods[m.name] = m
    return mods


def contributed(name):
    return any(name.startswith(f.replace("/", ".") + ".") for f in CONTRIB_FOLDERS.values())


def closure(selected, mods):
    """The selected modules plus every contributed module they import, transitively."""
    need, todo = set(), list(selected)
    while todo:
        n = todo.pop()
        if n in need or n not in mods:
            continue
        need.add(n)
        todo += [i for i in mods[n].imports if contributed(i)]
    return need


def levels(names, mods):
    """Topological levels of the contributed import graph (imports first)."""
    remaining, done, out = set(names), set(), []
    while remaining:
        ready = sorted(n for n in remaining
                       if all(i in done or not contributed(i) for i in mods[n].imports))
        if not ready:
            raise Fault(f"import cycle among {sorted(remaining)}")
        out.append(ready)
        done |= set(ready)
        remaining -= set(ready)
    return out


# --------------------------------------------------------------- pipeline

class Verifier:
    def __init__(self, env, mods, jobs):
        self.env, self.mods, self.jobs = env, mods, max(1, jobs)

    def log(self, name, step):
        return self.env.log_path(f"{name}.{step}.log")

    def tail(self, path, n=1500):
        return read_tail(path, n)

    def reject(self, m, reason):
        m.verdict, m.reason = "REJECTED", reason

    # ---- compile, in import order, one sandbox per module
    def compile_all(self, names):
        for level in levels(names, self.mods):
            todo = []
            for n in level:
                m = self.mods[n]
                missing = [i for i in m.imports if contributed(i) and i not in self.mods]
                bad_dep = [i for i in m.imports if contributed(i) and self.mods.get(i) and self.mods[i].verdict == "REJECTED"
                           and self.mods[i].reason.startswith("does not compile")]
                if missing:
                    self.reject(m, f"imports {missing[0]}, which is not in the record")
                elif bad_dep:
                    self.reject(m, f"does not compile: it imports {bad_dep[0]}, which does not compile")
                else:
                    todo.append(m)
            with cf.ThreadPoolExecutor(self.jobs) as pool:
                results = list(pool.map(self.compile_one, todo))
            # Only after the whole level: place its results in the shared library,
            # which every later sandbox sees read-only.
            for m, olean in zip(todo, results):
                if olean:  # a host-only copy, made by take()
                    dest = self.env.lib / m.rel.with_suffix(".olean")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(olean, dest)

    def compile_one(self, m):
        e = self.env
        src = e.work / "src" / m.rel
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m.src, src)
        out = e.fresh_dir("out", m.name)
        olean = out / "module.olean"
        ok, why = e.run_sandboxed("compile", [e.inside(e.bin / "lean"), f"--root={e.inside(e.work / 'src')}",
                                              "-o", e.inside(olean), e.inside(src)],
                                  [out], self.log(m.name, "compile"), ro=[src], lean=True)
        if not ok:
            self.reject(m, f"does not compile ({why}): {self.tail(self.log(m.name, 'compile'), 600).strip()}")
            return None
        staged = e.work / "staged" / f"{m.name}.olean"
        why = take(olean, staged, LIMITS["compile"][1])
        shutil.rmtree(out, ignore_errors=True)
        if why:
            self.reject(m, f"does not compile (the sandbox produced no usable compiled file: {why})")
            return None
        return staged

    # ---- replay and export, in a fresh sandbox each
    def replay_and_export(self, m, export=True):
        e = self.env
        # Separate fresh directories: nothing replay leaves behind is seen by export.
        replay_dir = e.fresh_dir("exp", f"{m.name}.replay")
        ok, why = e.run_sandboxed("replay", [e.inside(e.bin / "leanchecker"), m.name], [replay_dir],
                                  self.log(m.name, "replay"), lean=True)
        shutil.rmtree(replay_dir, ignore_errors=True)
        if not ok:
            raise Reject(f"leanchecker's kernel replay failed ({why}): {self.tail(self.log(m.name, 'replay'), 400).strip()}")
        if not export:
            return None
        export_dir = e.fresh_dir("exp", f"{m.name}.export")
        # stdout goes straight to a host-only file the host created; nothing is copied out.
        raw = e.capture_path(f"{m.name}.raw.ndjson")
        ok, why = e.run_sandboxed("export", [e.inside(e.bin / "leanexport"), m.name, "--", target_of(m.kind, m.ident)],
                                  [export_dir], self.log(m.name, "export"), stdout_path=raw, lean=True)
        shutil.rmtree(export_dir, ignore_errors=True)
        if not ok:
            raise Reject(f"cannot export {target_of(m.kind, m.ident)} ({why})")
        if "PANIC" in self.tail(self.log(m.name, "export"), 100000):
            raise Reject(f"cannot export {target_of(m.kind, m.ident)}: it does not exist")
        got = open_regular(raw)
        if got is None:
            raise Reject("the sandbox produced no export")
        os.close(got[0])
        if got[1] > LIMITS["export"][1]:
            raise Reject("the export is too large")
        return raw

    # ---- trusted code on the untrusted text, each in a sandbox of its own
    def scratch(self, m, step):
        return self.env.fresh_dir("scratch", f"{m.name}.{step}")

    def verify_export(self, m, step, *args, inputs=()):
        """scripts/verify_export.py in a sandbox that sees only `inputs` and its scratch
        directory; a Path argument is passed as the sandbox sees it. Returns
        (ok, output lines, scratch dir)."""
        e = self.env
        d = self.scratch(m, step)
        out = e.capture_path(f"{m.name}.{step}.out")
        argv = [e.inside(a) if isinstance(a, Path) else a for a in args]
        ok, why = e.run_sandboxed(step, [sys.executable, "-I", e.inside(ROOT / "scripts" / "verify_export.py"), *argv],
                                  [d], self.log(m.name, step), stdout_path=out,
                                  ro=[ROOT / "scripts" / "verify_export.py", *inputs])
        lines = self.tail(out, 2_000_000).strip().splitlines() or [""]
        if not ok and not lines[-1].startswith("REJECTED"):
            raise Reject(f"the export check ({step}) did not finish: {why}")
        return ok, lines, d

    def canonicalize(self, m, raw):
        # verify_export() recreates this directory and makes only it writable.
        d = self.env.work / "scratch" / f"{m.name}.canon"
        ok, lines, _ = self.verify_export(m, "canon", "canon", raw, d / "canonical.ndjson", inputs=[raw])
        if not ok:
            raise Reject(lines[-1].removeprefix("REJECTED: "))
        # Into a directory that no sandbox ever had writable.
        canon = self.env.work / "canon" / f"{m.name}.ndjson"
        why = take(d / "canonical.ndjson", canon, LIMITS["canon"][1])
        shutil.rmtree(d, ignore_errors=True)
        if why:
            raise Reject(f"the canonical export is unusable: {why}")
        return canon

    # ---- trusted checks on the text export
    def trusted_reference(self, m, names):
        e = self.env
        ref = e.work / "ref" / f"{m.name}.ndjson"
        names_file = e.work / "ref" / f"{m.name}.names"
        names_file.write_text("\n".join(names) + "\n")
        errf = self.log(m.name, "reference")
        with open(ref, "wb") as out, open(errf, "wb") as err:
            try:
                r = subprocess.run([str(e.bin / "leanexport"), "QPCP.Statements", "--", *names], stdout=out, stderr=err,
                                   env={"PATH": f"{e.bin}:/usr/bin:/bin", "LEAN_PATH": e.trusted_lean_path},
                                   timeout=TRUSTED_EXPORT_TIMEOUT)
            except subprocess.TimeoutExpired:
                raise Fault("the reference export timed out")
        text = self.tail(errf, 100000)
        if "PANIC" in text:
            missing = re.search(r"Constant (\S+) not found", text)
            raise Reject(f"refers to {missing.group(1) if missing else 'a constant'}, which main does not have")
        if r.returncode != 0:
            raise Fault(f"cannot export the reference from main: {text[-400:]}")
        return ref, names_file

    def nanoda(self, m, export):
        e = self.env
        cfg = e.work / "ref" / f"{m.name}.nanoda.json"
        cfg.write_text(json.dumps({
            "export_file_path": e.inside(export), "use_stdin": False,
            "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"],
            "unpermitted_axiom_hard_error": True, "nat_extension": True, "string_extension": True,
            "print_success_message": True}))
        logf, outf = self.log(m.name, "nanoda"), e.capture_path(f"{m.name}.nanoda.out")
        ok, why = e.run_sandboxed("nanoda", [e.inside(e.bin / "nanoda_bin"), e.inside(cfg)], [self.scratch(m, "nanoda")],
                                  logf, stdout_path=outf, ro=[cfg, export])
        text = self.tail(outf, 100000) + self.tail(logf, 100000)
        if not ok or "with no typechecker errors" not in text:
            raise Reject(f"the independent kernel (nanoda) rejects the export ({why or 'errors'}): {text[-400:].strip()}")

    def verify_one(self, m, replay_only=False):
        try:
            raw = self.replay_and_export(m, export=not replay_only)
            if replay_only:
                m.verdict = "ACCEPTED"
                return
            export = self.canonicalize(m, raw)
            refs, names = [], [*FIXED]
            if m.kind == "lemma":
                ok, out, _ = self.verify_export(m, "verify", "deps", m.ident, export, inputs=[export])
                if not ok:
                    raise Reject(out[-1].removeprefix("REJECTED: "))
                m.deps = [d for d in out if d]
                if len(m.deps) > MAX_DEPS:
                    raise Reject(f"the statement refers to more than {MAX_DEPS} constants")
                names += m.deps
            elif m.ident.startswith("S"):
                names.insert(0, f"QPCP.Statement.{m.ident}")
            else:
                lemma = self.mods.get(module_of("lemma", m.ident))
                if lemma is None:
                    raise Reject(f"its statement {m.ident} is not in the record")
                if lemma.verdict != "ACCEPTED" or lemma.export is None:
                    raise Reject(f"its statement {m.ident} is not verified ({lemma.reason or 'not checked'})")
                names += lemma.deps
                refs.append(lemma.export)
            ref, names_file = self.trusted_reference(m, names)
            self.nanoda(m, export)
            ok, out, _ = self.verify_export(m, "verify", m.kind, m.ident, export,
                                            ",".join(self.env.inside(p) for p in [ref, *refs]), names_file,
                                            inputs=[export, ref, *refs, names_file])
            if not ok or out[-1] != f"ACCEPTED: {m.kind} {m.ident}":
                raise Reject(out[-1].removeprefix("REJECTED: "))
            m.verdict, m.export = "ACCEPTED", export
        except Reject as r:
            self.reject(m, str(r))

    def verify_all(self, names, replay_only=False):
        order = sorted(names, key=lambda n: (self.mods[n].kind != "lemma", n))
        lemmas = [self.mods[n] for n in order if self.mods[n].kind == "lemma" and self.mods[n].verdict is None]
        others = [self.mods[n] for n in order if self.mods[n].kind != "lemma" and self.mods[n].verdict is None]
        for batch in (lemmas, others):
            with cf.ThreadPoolExecutor(self.jobs) as pool:
                list(pool.map(lambda m: self.verify_one(m, replay_only), batch))


# ------------------------------------------------------------------ commands

def replay_trusted(env):
    for m in TRUSTED_MODULES:
        r = env.lake("env", "leanchecker", m, timeout=1800)
        if r.returncode != 0:
            raise Fault(f"leanchecker found a problem in {m}: {(r.stdout + r.stderr)[-400:]}")


def report(selected, mods):
    rejected = [mods[n] for n in selected if mods[n].verdict != "ACCEPTED"]
    for n in selected:
        m = mods[n]
        print(log_safe(f"  {m.verdict or 'NOT CHECKED':9} {m.kind} {m.ident}" + (f": {m.reason}" if m.reason else "")))
    if rejected:
        m = rejected[0]
        print(log_safe(f"REJECTED: {m.kind} {m.ident}: {m.reason or 'not checked'}"
                       + (f" (and {len(rejected) - 1} more)" if len(rejected) > 1 else "")))
        return 1
    print("ACCEPTED: " + check.summarize([f"{mods[n].kind} {mods[n].ident}" for n in selected]))
    return 0


def cmd_record(env, opts):
    if not opts["skip_scan"]:
        try:
            check.record_items()
        except check.Rejected as e:
            print(log_safe(f"REJECTED: {e}"))
            return 1
    env.setup()
    env.trusted_build()
    replay_trusted(env)
    mods = tree_modules()
    selected = sorted(mods)
    if opts["only"]:
        unknown = [n for n in opts["only"] if n not in mods]
        if unknown:
            raise Fault(f"not in the record: {unknown}")
        selected = sorted(opts["only"])
    if opts["shard"]:
        k, n = opts["shard"]
        others = [s for s in selected if mods[s].kind != "lemma"]
        mine = [s for i, s in enumerate(others) if i % n == k - 1]
        # Lemmas: all of them in shard 1; elsewhere only those this shard's results need.
        need_lemmas = {module_of("lemma", mods[s].ident) for s in mine if mods[s].ident.startswith("L")}
        lemmas = [s for s in selected if mods[s].kind == "lemma" and (k == 1 or s in need_lemmas)]
        selected = sorted(set(mine) | set(lemmas))
    needed = closure(selected, mods)
    # A proof of a lemma needs the lemma verified, even outside this selection.
    needed |= {module_of("lemma", mods[s].ident) for s in selected
               if mods[s].ident.startswith("L") and module_of("lemma", mods[s].ident) in mods}
    v = Verifier(env, mods, opts["jobs"])
    v.compile_all(needed)
    v.verify_all(needed, opts["replay_only"])
    return report(selected, mods)


def cmd_contribution(env, opts, kind, ident, file):
    if kind not in CONTRIB_FOLDERS:
        raise Fault("kind must be proof, refutation or lemma")
    if not re.fullmatch(r"S\d{3,6}|L\d{1,9}", ident) or (kind == "lemma" and not ident.startswith("L")):
        raise Fault(f"bad id: {ident}")
    src = Path(file)
    if not src.is_file() or src.is_symlink():
        raise Fault(f"no such regular file: {file}")
    if (ROOT / CONTRIB_FOLDERS[kind] / f"{ident}.lean").exists():
        raise Fault(f"{CONTRIB_FOLDERS[kind]}/{ident}.lean is in the tree; move it aside first")
    env.setup()
    env.trusted_build()
    mods = tree_modules()
    new = Module(kind, ident, src)
    mods[new.name] = new
    needed = closure([new.name], mods)
    if kind != "lemma" and ident.startswith("L"):
        lemma = module_of("lemma", ident)
        if lemma not in mods:
            print(f"REJECTED: there is no statement {ident} on main")
            return 1
        needed |= closure([lemma], mods)
    v = Verifier(env, mods, opts["jobs"])
    v.compile_all(needed)
    # Verify the statement this result is about (if contributed), then the result.
    if kind != "lemma" and ident.startswith("L"):
        v.verify_all([module_of("lemma", ident)])
    if new.verdict is None:
        v.verify_one(new)
    if kind == "lemma" and new.verdict == "ACCEPTED":
        write_preview(env, new)
    (env.work / "result" / "contribution.json").write_text(json.dumps({
        "kind": kind, "ident": ident, "verdict": new.verdict,
        "export": str(new.export or env.work / "canon" / f"{new.name}.ndjson"),
        "references": sorted(str(p) for p in (env.work / "ref").glob(f"{new.name}.ndjson"))
        + ([str(mods[module_of('lemma', ident)].export)] if kind != "lemma" and ident.startswith("L")
           and mods[module_of('lemma', ident)].export else []),
    }))
    if new.verdict == "ACCEPTED":
        print(f"ACCEPTED: {kind} {ident}")
        return 0
    print(log_safe(f"REJECTED: {new.reason}"))
    return 1


def write_preview(env, m):
    """The kernel's own rendering of a verified statement, for the reviewer.

    nanoda_bin, in a sandbox of its own, prints the declaration from the
    verified canonical export; the statement-preview workflow posts it on the
    pull request."""
    cfg = env.work / "ref" / "preview.nanoda.json"
    out = env.work / "result" / "statement-preview.txt"
    cfg.write_text(json.dumps({
        "export_file_path": env.inside(m.export), "use_stdin": False,
        "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"],
        "unpermitted_axiom_hard_error": True, "nat_extension": True, "string_extension": True,
        "pp_declars": [target_of(m.kind, m.ident)], "pp_to_stdout": True,
        "pp_options": {"all": False, "explicit": False, "universes": False, "notation": True,
                       "proofs": False, "indent": 2, "width": 100},
        "print_success_message": False}))
    d = env.fresh_dir("scratch", "preview")
    raw = env.capture_path("preview.out")
    ok, _ = env.run_sandboxed("preview", [env.inside(env.bin / "nanoda_bin"), env.inside(cfg)], [d],
                              env.log_path("preview.log"), stdout_path=raw, ro=[cfg, m.export])
    text = read_head(raw, 200_000) if ok else ""
    # Keep only the statement itself (the axioms follow it, separated by a blank line).
    text = text.split("\n\n")[0].strip()[:20000]
    out.write_text((text or "(the kernel could not render this statement)") + "\n")


def main(argv):
    args = argv[1:]
    opts = {"sandbox": True, "skip_scan": False, "only": None, "shard": None,
            "jobs": int(os.environ.get("QPCP_JOBS", "3")), "replay_only": False}
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-sandbox":
            opts["sandbox"] = False
        elif a == "--skip-scan-for-tests":
            opts["skip_scan"] = True
        elif a == "--replay-only":
            opts["replay_only"] = True
        elif a in ("--only", "--shard", "--jobs") and i + 1 < len(args):
            i += 1
            if a == "--only":
                opts["only"] = [s for s in args[i].split(",") if s]
            elif a == "--shard":
                k, n = map(int, args[i].split("/"))
                if not 1 <= k <= n:
                    print("bad --shard")
                    return 2
                opts["shard"] = (k, n)
            else:
                opts["jobs"] = int(args[i])
        else:
            rest.append(a)
        i += 1
    if not opts["sandbox"]:
        print("WARNING: --no-sandbox: contributed files run WITHOUT isolation (development only).", file=sys.stderr)
    try:
        env = Env(opts["sandbox"])
        if rest == ["trusted-build"]:
            env.setup()
            env.trusted_build()
            print("trusted build: " + ", ".join(TRUSTED_MODULES))
            return 0
        if rest == ["record"]:
            return cmd_record(env, opts)
        if len(rest) == 4 and rest[0] == "contribution":
            return cmd_contribution(env, opts, rest[1], rest[2], rest[3])
    except Fault as e:
        print(log_safe(f"FAULT: {e}"))
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
