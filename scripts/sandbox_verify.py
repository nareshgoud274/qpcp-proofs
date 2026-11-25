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

Outside the sandbox, trusted code reads only those text exports:

  * nanoda_bin, an independent kernel, type-checks each export with only
    propext, Classical.choice and Quot.sound;
  * scripts/verify_export.py compares it with a reference exported from the
    maintainer-written modules: the statement and the axioms with their whole
    dependency closure, and, for a lemma, everything its definition refers to.
    Lemmas are verified first. A proof or refutation of a contributed lemma is
    then compared with that lemma's verified export as well, which is how a
    contributed statement becomes a trusted reference.

No untrusted .olean is read outside a sandbox. Every sandboxed step has a hard
timeout (the whole process group is killed) and a file-size limit set with
RLIMIT_FSIZE, and every file taken out of a sandbox is size-checked.

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
import resource
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUSTED_MODULES = ["QPCP.Defs", "QPCP.Qudit", "QPCP.Statements"]
FIXED = ["propext", "Classical.choice", "Quot.sound", "Quot", "Quot.mk", "Quot.lift", "Quot.ind"]
CONTRIB_FOLDERS = {"lemma": "QPCP/Lemmas", "proof": "QPCP/Proofs", "refutation": "QPCP/Refutations"}
TARGET_NS = {"lemma": "QPCP.Lemma", "proof": "QPCP.Proof", "refutation": "QPCP.Refutation"}

# Limits for sandboxed steps: (timeout seconds, largest file the step may write).
LIMITS = {
    "compile": (1500, 1_000_000_000),
    "replay": (900, 100_000_000),
    "export": (900, 1_000_000_000),
}
NANODA_TIMEOUT = 1800
VERIFY_TIMEOUT = 1800
TRUSTED_EXPORT_TIMEOUT = 1800
MAX_DEPS = 5000

spec = importlib.util.spec_from_file_location("qpcp_check", ROOT / "scripts" / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Reject(Exception):
    pass


class Fault(Exception):
    pass


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
        self.lock = threading.Lock()

    def lake(self, *args, timeout=3600):
        r = subprocess.run(["lake", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return r

    def setup(self):
        r = self.lake("env", "printenv", "LEAN_SYSROOT")
        if r.returncode != 0:
            raise Fault("cannot locate the toolchain")
        self.bin = Path(r.stdout.strip()) / "bin"
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
        if self.work.exists():
            shutil.rmtree(self.work)
        for d in ("src", "out", "lib", "exp", "logs", "ref", "result"):
            (self.work / d).mkdir(parents=True)
        self.lib = self.work / "lib"
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

    def run_sandboxed(self, step, argv, rw, log, stdout_path=None):
        """Run argv in a fresh sandbox. Returns (ok, reason)."""
        timeout, fsize = LIMITS[step]
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "LEAN_PATH": self.sandbox_lean_path}
        if self.sandbox:
            cmd = [self.bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
            for d in rw:
                cmd += ["--bind", str(d), str(d)]
            cmd += ["--chdir", "/tmp", "--unshare-all", "--die-with-parent", "--new-session",
                    "--cap-drop", "ALL", "--clearenv"]
            for k, v in {**env, "HOME": "/tmp"}.items():
                cmd += ["--setenv", k, v]
            cmd += ["--", *argv]
            run_env, cwd = {"PATH": "/usr/bin:/bin"}, "/"
        else:
            cmd, run_env, cwd = argv, {**env, "HOME": str(rw[0])}, str(rw[0])

        def limits():
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        out = open(stdout_path, "wb") if stdout_path else subprocess.DEVNULL
        with open(log, "wb") as err:
            try:
                p = subprocess.Popen(cmd, stdout=out, stderr=err, env=run_env, cwd=cwd,
                                     preexec_fn=limits, start_new_session=True)
            except OSError as e:
                raise Fault(f"cannot start the sandbox: {e}")
            try:
                code = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                return False, f"{step} timed out after {timeout} s"
            finally:
                if stdout_path:
                    out.close()
        if code == -signal.SIGXFSZ or code == 128 + signal.SIGXFSZ:
            return False, f"{step} wrote a file larger than {fsize} bytes"
        if code != 0:
            return False, f"{step} failed (exit {code})"
        return True, ""


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
        return self.env.work / "logs" / f"{name}.{step}.log"

    def tail(self, path, n=1500):
        try:
            return path.read_text(errors="replace")[-n:]
        except OSError:
            return ""

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
                if olean:
                    dest = self.env.lib / m.rel.with_suffix(".olean")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(olean, dest)

    def compile_one(self, m):
        e = self.env
        src = e.work / "src" / m.rel
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m.src, src)
        out = e.work / "out" / m.name
        out.mkdir(parents=True)
        olean = out / "module.olean"
        ok, why = e.run_sandboxed("compile", [str(e.bin / "lean"), f"--root={e.work / 'src'}", "-o", str(olean), str(src)],
                                  [out], self.log(m.name, "compile"))
        if not ok:
            self.reject(m, f"does not compile ({why}): {self.tail(self.log(m.name, 'compile'), 600).strip()}")
            return None
        if not olean.is_file() or olean.is_symlink():
            self.reject(m, "does not compile (the sandbox produced no compiled file)")
            return None
        return olean

    # ---- replay and export, in a fresh sandbox each
    def replay_and_export(self, m, export=True):
        e = self.env
        scratch = e.work / "exp" / m.name
        scratch.mkdir(parents=True, exist_ok=True)
        ok, why = e.run_sandboxed("replay", [str(e.bin / "leanchecker"), m.name], [scratch], self.log(m.name, "replay"))
        if not ok:
            raise Reject(f"leanchecker's kernel replay failed ({why}): {self.tail(self.log(m.name, 'replay'), 400).strip()}")
        if not export:
            return None
        path = scratch / "export.ndjson"
        ok, why = e.run_sandboxed("export", [str(e.bin / "leanexport"), m.name, "--", target_of(m.kind, m.ident)],
                                  [scratch], self.log(m.name, "export"), stdout_path=path)
        if not ok:
            raise Reject(f"cannot export {target_of(m.kind, m.ident)} ({why})")
        if "PANIC" in self.tail(self.log(m.name, "export"), 100000):
            raise Reject(f"cannot export {target_of(m.kind, m.ident)}: it does not exist")
        if not path.is_file() or path.is_symlink():
            raise Reject("the sandbox produced no export")
        if path.stat().st_size > LIMITS["export"][1]:
            raise Reject("the export is too large")
        # Take the export out of the sandbox's reach before using it.
        taken = e.work / "result" / f"{m.name}.ndjson"
        shutil.copyfile(path, taken)
        shutil.rmtree(scratch, ignore_errors=True)
        return taken

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
            "export_file_path": str(export), "use_stdin": False,
            "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"],
            "unpermitted_axiom_hard_error": True, "nat_extension": True, "string_extension": True,
            "print_success_message": True}))
        logf = self.log(m.name, "nanoda")
        with open(logf, "wb") as out:
            try:
                r = subprocess.run([str(e.bin / "nanoda_bin"), str(cfg)], stdout=out, stderr=subprocess.STDOUT,
                                   timeout=NANODA_TIMEOUT)
            except subprocess.TimeoutExpired:
                raise Reject(f"the independent kernel (nanoda) timed out after {NANODA_TIMEOUT} s")
        if r.returncode != 0 or "with no typechecker errors" not in self.tail(logf, 100000):
            raise Reject(f"the independent kernel (nanoda) rejects the export: {self.tail(logf, 400).strip()}")

    def verify_export(self, *args):
        try:
            r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "verify_export.py"), *map(str, args)],
                               capture_output=True, text=True, timeout=VERIFY_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise Reject("the export comparison timed out")
        return r.returncode, (r.stdout.strip().splitlines() or [""])

    def verify_one(self, m, replay_only=False):
        try:
            export = self.replay_and_export(m, export=not replay_only)
            if replay_only:
                m.verdict = "ACCEPTED"
                return
            refs, names = [], [*FIXED]
            if m.kind == "lemma":
                code, out = self.verify_export("deps", m.ident, export)
                if code != 0:
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
            code, out = self.verify_export(m.kind, m.ident, export, ",".join(map(str, [ref, *refs])), names_file)
            if code != 0:
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
        print(f"  {m.verdict or 'NOT CHECKED':9} {m.kind} {m.ident}" + (f": {m.reason}" if m.reason else ""))
    if rejected:
        m = rejected[0]
        print(f"REJECTED: {m.kind} {m.ident}: {m.reason or 'not checked'}"
              + (f" (and {len(rejected) - 1} more)" if len(rejected) > 1 else ""))
        return 1
    print("ACCEPTED: " + check.summarize([f"{mods[n].kind} {mods[n].ident}" for n in selected]))
    return 0


def cmd_record(env, opts):
    if not opts["skip_scan"]:
        try:
            check.record_items()
        except check.Rejected as e:
            print(f"REJECTED: {e}")
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
        "export": str(new.export or env.work / "result" / f"{new.name}.ndjson"),
        "references": sorted(str(p) for p in (env.work / "ref").glob(f"{new.name}.ndjson"))
        + ([str(mods[module_of('lemma', ident)].export)] if kind != "lemma" and ident.startswith("L")
           and mods[module_of('lemma', ident)].export else []),
    }))
    if new.verdict == "ACCEPTED":
        print(f"ACCEPTED: {kind} {ident}")
        return 0
    print(f"REJECTED: {new.reason}")
    return 1


def write_preview(env, m):
    """The kernel's own rendering of a verified statement, for the reviewer.

    nanoda_bin, outside the sandbox, prints the declaration from the verified
    export; the statement-preview workflow posts it on the pull request."""
    cfg = env.work / "ref" / "preview.nanoda.json"
    out = env.work / "result" / "statement-preview.txt"
    cfg.write_text(json.dumps({
        "export_file_path": str(m.export), "use_stdin": False,
        "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"],
        "unpermitted_axiom_hard_error": True, "nat_extension": True, "string_extension": True,
        "pp_declars": [target_of(m.kind, m.ident)], "pp_to_stdout": True,
        "pp_options": {"all": False, "explicit": False, "universes": False, "notation": True,
                       "proofs": False, "indent": 2, "width": 100},
        "print_success_message": False}))
    try:
        r = subprocess.run([str(env.bin / "nanoda_bin"), str(cfg)], capture_output=True, text=True,
                           timeout=NANODA_TIMEOUT)
        text = r.stdout if r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        text = ""
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
        print(f"FAULT: {e}")
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
