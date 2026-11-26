#!/usr/bin/env python3
"""A contribution must be a regular file, and is never read past its bound.

    python3 -I tests/test_contribution_files.py

Runs anywhere with git (no Lean, no bubblewrap). Every case runs in a
disposable git repository made from this checkout's tracked scripts and data
files, under a temporary directory; the real working tree is never written.

  1. A symlink to a host canary, submitted as a proof: the gate
     (scripts/ci_contribution.sh gate) rejects it from its Git mode before
     reading anything, `check.py scan` rejects it too, `scan-file` on the link
     and `scan-all` with it committed reject it, and the canary's token appears
     in none of the output.
  2. A 50 MB file: `scan` (from the Git blob) and `scan-file` (from the working
     copy) reject it without reading it in full; the bytes actually read are
     counted.
  3. A file with Git mode 100755, and a submodule entry (160000): the gate
     rejects both, and so do `scan` and `scan-all`.
  4. A FIFO given to `scan-file` is rejected without blocking.
  5. A fixture id (S900000-S999999, L900000-L999999) is rejected by the gate,
     and no founding step in steps.json uses one.
  5c. One spelling per id (#115): a lemma id with a leading zero (L0777, as a
     statement or as a proof) is rejected by the gate; L777 passes it.
  6. A regular proof file still passes the gate and the scan.
"""

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
GIT_ID = ["-c", "user.name=qpcp-test", "-c", "user.email=qpcp-test@example.invalid", "-c", "commit.gpgsign=false"]


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:400]}"))


def sh(cwd, *cmd, timeout=120):
    r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def git(cwd, *args):
    code, out = sh(cwd, "git", *GIT_ID, *args)
    if code != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out}")
    return out


def make_repo(base):
    """A git repository holding this checkout's tracked files outside .lake (small: scripts, data, QPCP)."""
    repo = base / "repo"
    repo.mkdir()
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    for f in files:
        if not f:
            continue
        rel = f.decode()
        src = ROOT / rel
        if not src.is_file() or src.is_symlink():
            continue
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    # The cases submit PROOF as a new file, so its step must be open in this
    # copy even once main has proved or refuted it (#131).
    for settled in (repo / PROOF, repo / PROOF.replace("Proofs", "Refutations")):
        settled.unlink(missing_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def submit(repo, base_sha, branch, add):
    """Commit one change on a new branch from base_sha; `add(repo)` stages it."""
    git(repo, "checkout", "-q", "-B", branch, base_sha)
    add(repo)
    git(repo, "commit", "-q", "-m", branch)


def gate(repo, base_sha):
    return sh(repo, "bash", "scripts/ci_contribution.sh", "gate", base_sha)


def scan(repo, base_sha):
    return sh(repo, sys.executable, "-I", "scripts/check.py", "scan", base_sha)


def load_check(repo):
    spec = importlib.util.spec_from_file_location("qpcp_check_under_test", repo / "scripts" / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROOF = "QPCP/Proofs/S030.lean"   # made open in the disposable copy (make_repo), whatever main has


def main():
    base = Path(tempfile.mkdtemp(prefix="qpcp-contribfiles-"))
    try:
        repo, base_sha = make_repo(base)
        token = secrets.token_hex(16)
        canary = base / "canary.txt"
        canary.write_text(f"theorem canary_{token} : True := trivial\n")
        honest = (ROOT / "QPCP" / "Proofs" / "S019.lean").read_text().replace("S019", "S030")

        # 1. A symlink to a host canary.
        def add_link(r):
            (r / PROOF).symlink_to(canary)
            git(r, "add", PROOF)
        submit(repo, base_sha, "symlink", add_link)
        code, out = gate(repo, base_sha)
        check("1. gate rejects a symlink from its Git mode", code == 1 and "REJECTED" in out and "120000" in out, out)
        outputs = [out]
        code, out = scan(repo, base_sha)
        check("1. scan rejects the symlink", code == 1 and "symbolic link" in out, out)
        outputs.append(out)
        code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-file", "proof", "S030", PROOF)
        check("1. scan-file refuses to follow the symlink", code == 1 and "symbolic link" in out, out)
        outputs.append(out)
        code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-all")
        check("1. scan-all rejects the committed symlink", code == 1 and "symbolic link" in out, out)
        outputs.append(out)
        check("1. the canary's token appears in none of the output", not any(token in o for o in outputs),
              [o for o in outputs if token in o])

        # 2. A 50 MB file.
        big = 50 * 1024 * 1024
        def add_big(r):
            with open(r / PROOF, "wb") as f:
                f.write(honest.encode())
                f.write(b"-- " + b"x" * (big - len(honest) - 4) + b"\n")
            git(r, "add", PROOF)
        submit(repo, base_sha, "big", add_big)
        code, out = gate(repo, base_sha)
        check("2. the gate passes a 50 MB regular file on to the scan (mode 100644)", code == 0, out)
        code, out = scan(repo, base_sha)
        check("2. scan rejects the 50 MB file", code == 1 and "larger than" in out, out)
        chk = load_check(repo)
        reads, blob_reads = [0], []
        real_read, real_git = os.read, chk.git
        def counting_read(fd, n):
            b = real_read(fd, n)
            reads[0] += len(b)
            return b
        def counting_git(*args):
            if args[:1] == ("cat-file",) and args[1] == "blob":
                blob_reads.append(args)
            return real_git(*args)
        chk.os.read, chk.git = counting_read, counting_git
        try:
            for desc, call in (("scan-file", lambda: chk.mode_scan_file("proof", "S030", str(repo / PROOF))),
                               ("scan", lambda: chk.precheck(base_sha))):
                chk.ROOT = repo
                reads[0] = 0
                blob_reads.clear()
                try:
                    call()
                    check(f"2. {desc} rejects the 50 MB file", False, "accepted")
                except chk.Rejected as e:
                    check(f"2. {desc} rejects the 50 MB file without reading it in full "
                          f"({reads[0]} bytes read by os.read, {len(blob_reads)} blob reads)",
                          "larger than" in str(e) and reads[0] <= chk.MAX_BYTES + 1 and not blob_reads, e)
        finally:
            chk.os.read, chk.git = real_read, real_git

        # 3. An executable file and a submodule entry.
        def add_exec(r):
            (r / PROOF).write_text(honest)
            os.chmod(r / PROOF, 0o755)
            git(r, "add", PROOF)
        submit(repo, base_sha, "exec", add_exec)
        code, out = gate(repo, base_sha)
        check("3. gate rejects a file with Git mode 100755", code == 1 and "100755" in out, out)
        code, out = scan(repo, base_sha)
        check("3. scan rejects the executable file", code == 1 and "executable" in out, out)
        code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-file", "proof", "S030", PROOF)
        check("3. scan-file rejects the executable file", code == 1 and "executable" in out, out)

        def add_submodule(r):
            git(r, "update-index", "--add", "--cacheinfo", f"160000,{base_sha},{PROOF}")
        submit(repo, base_sha, "submodule", add_submodule)
        code, out = gate(repo, base_sha)
        check("3. gate rejects a submodule entry", code == 1 and "160000" in out, out)
        code, out = scan(repo, base_sha)
        check("3. scan rejects the submodule entry", code == 1 and "submodule" in out, out)
        code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-all")
        check("3. scan-all rejects the committed submodule entry", code == 1 and "submodule" in out, out)

        # 4. A FIFO.
        git(repo, "checkout", "-q", "-f", "main")
        fifo = base / "fifo.lean"
        os.mkfifo(fifo)
        try:
            code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-file", "proof", "S030", str(fifo), timeout=20)
            check("4. scan-file rejects a FIFO without blocking", code == 1 and "not a regular file" in out, out)
        except subprocess.TimeoutExpired:
            check("4. scan-file rejects a FIFO without blocking", False, "blocked")

        # 5. A fixture id.
        def add_fixture(r):
            (r / "QPCP/Proofs/S900030.lean").write_text(honest.replace("S030", "S900030"))
            git(r, "add", "QPCP/Proofs/S900030.lean")
        submit(repo, base_sha, "fixture", add_fixture)
        code, out = gate(repo, base_sha)
        check("5. gate rejects a fixture id", code == 1 and "reserved" in out, out)

        # 5b. No founding step uses a fixture id.
        chk_main = load_check(ROOT)
        real_ids = [st["id"] for st in __import__("json").loads((ROOT / "steps.json").read_text())]
        clash = [i for i in real_ids if chk_main.FIXTURE_ID.match(i)]
        check(f"5. no founding step in steps.json uses a fixture id ({len(real_ids)} steps)", not clash, clash)

        # 5c. One spelling per id: L0777 must not name issue #777.
        lemma = "import QPCP.Statements\n\n/-!\nPROGRAM: foundations\nPLAIN: True.\n-/\n\nnamespace QPCP.Lemma\n\ndef {i} : Prop := True\n\nend QPCP.Lemma\n"
        for desc, path, text in (
                ("a statement L0777", "QPCP/Lemmas/L0777.lean", lemma.format(i="L0777")),
                ("a proof of L0777", "QPCP/Proofs/L0777.lean", honest.replace("S030", "L0777")),
                ("a statement L00777", "QPCP/Lemmas/L00777.lean", lemma.format(i="L00777"))):
            def add_odd(r, path=path, text=text):
                (r / path).parent.mkdir(parents=True, exist_ok=True)
                (r / path).write_text(text)
                git(r, "add", path)
            submit(repo, base_sha, "odd-" + Path(path).stem, add_odd)
            code, out = gate(repo, base_sha)
            check(f"5c. gate rejects {desc}, naming the canonical spelling",
                  code == 1 and "leading zeros" in out and "(L777, not" in out, out)

        def add_canonical(r):
            (r / "QPCP/Lemmas/L777.lean").write_text(lemma.format(i="L777"))
            git(r, "add", "QPCP/Lemmas/L777.lean")
        submit(repo, base_sha, "canonical-L777", add_canonical)
        code, out = gate(repo, base_sha)
        check("5c. gate passes the canonical spelling L777", code == 0, out)

        # 6. A regular file still passes.
        def add_honest(r):
            (r / PROOF).write_text(honest)
            git(r, "add", PROOF)
        submit(repo, base_sha, "honest", add_honest)
        code, out = gate(repo, base_sha)
        check("6. gate passes a regular proof file", code == 0 and "gate: one new contribution file" in out, out)
        code, out = scan(repo, base_sha)
        check("6. scan passes it", code == 0 and "CONTRIBUTION: proof S030 QPCP/Proofs/S030.lean" in out, out)
        code, out = sh(repo, sys.executable, "-I", "scripts/check.py", "scan-all")
        check("6. scan-all passes the record with it", code == 0 and out.startswith("ACCEPTED"), out)
    except Exception as e:  # a crash is a failure, never a skip
        check("crashed", False, f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
