#!/usr/bin/env python3
"""Checker for qpcp-proofs.

Two modes:

  check.py pr <base-ref>   Check a pull request: it may add or change exactly
                           one file, QPCP/Proofs/Sxxx.lean, and that file must
                           prove QPCP.Statement.Sxxx with only standard axioms.

  check.py all             Re-check every proof file present in QPCP/Proofs.

Verdicts are printed as ACCEPTED or REJECTED with a reason. Exit code 0 means
accepted, 1 means rejected, 2 means the checker itself failed (FAULT).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROOF_DIR = "QPCP/Proofs"
PROOF_RE = re.compile(r"^QPCP/Proofs/(S\d{3})\.lean$")
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
ALLOWED_IMPORT_RE = re.compile(
    r"^(Mathlib(\.[A-Za-z0-9_]+)*|QPCP\.Defs|QPCP\.Qudit|QPCP\.Statements|QPCP\.Proofs\.S\d{3})$"
)
# Text-level guards. The axiom check below is the real gate; these keep proof
# files plain (no metaprogramming, no code execution at build time).
FORBIDDEN_TOKENS = [
    "sorry", "admit", "axiom", "native_decide", "unsafe", "implemented_by",
    "extern", "run_cmd", "run_elab", "run_meta", "#eval", "#exit", "initialize",
    "elab", "elab_rules", "macro", "macro_rules", "syntax", "notation",
    "declare_syntax_cat", "set_option", "IO.", "debug.skipKernelTC",
]
MAX_BYTES = 200_000


class Rejected(Exception):
    pass


class Fault(Exception):
    pass


def run(cmd, timeout=1500):
    try:
        return subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise Rejected(f"`{' '.join(cmd)}` did not finish within {timeout} seconds")
    except FileNotFoundError as e:
        raise Fault(f"command not found: {e}")


def step_ids():
    try:
        steps = json.loads((ROOT / "steps.json").read_text())
    except Exception as e:  # noqa: BLE001
        raise Fault(f"cannot read steps.json: {e}")
    return {s["id"] for s in steps}


def retired_ids():
    try:
        steps = json.loads((ROOT / "steps.json").read_text())
    except Exception as e:  # noqa: BLE001
        raise Fault(f"cannot read steps.json: {e}")
    return {s["id"] for s in steps if s.get("retired") is True}


def strip_comments(src):
    """Remove Lean comments and string literals so token scans see only code."""
    out = []
    i, n, depth = 0, len(src), 0
    while i < n:
        two = src[i:i + 2]
        if depth > 0:
            if two == "/-":
                depth += 1
                i += 2
            elif two == "-/":
                depth -= 1
                i += 2
            else:
                i += 1
        elif two == "/-":
            depth = 1
            i += 2
        elif two == "--":
            while i < n and src[i] != "\n":
                i += 1
        elif src[i] == '"':
            i += 1
            while i < n and src[i] != '"':
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append('""')
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def scan_source(step, path):
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise Rejected(f"{path.name} is larger than {MAX_BYTES} bytes")
    try:
        src = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected(f"{path.name} is not valid UTF-8")
    code = strip_comments(src)

    for line in code.splitlines():
        m = re.match(r"^\s*(?:public\s+|private\s+|meta\s+)*import\s+(.*)$", line)
        if not m:
            continue
        for mod in m.group(1).split():
            if not ALLOWED_IMPORT_RE.match(mod):
                raise Rejected(f"import of `{mod}` is not allowed")
            if mod == f"QPCP.Proofs.{step}":
                raise Rejected("a proof file cannot import itself")

    for tok in FORBIDDEN_TOKENS:
        if tok[0].isalpha() and tok[-1].isalnum():
            pattern = r"(?<![A-Za-z0-9_.'])" + re.escape(tok) + r"(?![A-Za-z0-9_'])"
        else:
            pattern = re.escape(tok)
        if re.search(pattern, code):
            raise Rejected(f"`{tok}` is not allowed in a proof file")

    if not re.search(r"\btheorem\s+(QPCP\.Proof\.)?" + step + r"\b", code):
        raise Rejected(f"the file must declare `theorem QPCP.Proof.{step}`")


def parse_axioms(output):
    """Return the set of axioms reported by `#print axioms`, or None."""
    if re.search(r"does not depend on any axioms", output):
        return set()
    m = re.search(r"depends on axioms:\s*\[(.*?)\]", output, re.S)
    if not m:
        return None
    return {a.strip() for a in m.group(1).replace("\n", " ").split(",") if a.strip()}


def check_step(step):
    path = ROOT / PROOF_DIR / f"{step}.lean"
    if not path.is_file():
        raise Rejected(f"{PROOF_DIR}/{step}.lean does not exist")
    scan_source(step, path)

    build = run(["lake", "build", f"QPCP.Proofs.{step}"])
    if build.returncode != 0:
        tail = (build.stdout + build.stderr)[-4000:]
        raise Rejected(f"`lake build QPCP.Proofs.{step}` failed:\n{tail}")

    check_file = ROOT / f"Check_{step}.lean"
    check_file.write_text(
        f"import QPCP.Proofs.{step}\n\n"
        f"theorem QPCP.Check.result : QPCP.Statement.{step} := QPCP.Proof.{step}\n\n"
        f"#print axioms QPCP.Check.result\n"
    )
    try:
        res = run(["lake", "env", "lean", check_file.name], timeout=600)
    finally:
        check_file.unlink(missing_ok=True)
    out = res.stdout + res.stderr
    if res.returncode != 0:
        raise Rejected(
            f"QPCP.Proof.{step} does not prove QPCP.Statement.{step}:\n{out[-4000:]}"
        )
    axioms = parse_axioms(out)
    if axioms is None:
        raise Fault(f"could not read the axiom report:\n{out[-2000:]}")
    extra = axioms - ALLOWED_AXIOMS
    if extra:
        raise Rejected("the proof depends on disallowed axioms: " + ", ".join(sorted(extra)))


def changed_files(base):
    res = run(["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD"])
    if res.returncode != 0:
        raise Fault(f"git diff failed: {res.stderr.strip()}")
    files = []
    for line in res.stdout.splitlines():
        if line.strip():
            status, name = line.split("\t", 1)
            files.append((status, name))
    return files


def mode_pr(base):
    files = changed_files(base)
    if len(files) != 1:
        names = ", ".join(n for _, n in files) or "none"
        raise Rejected(
            "a proof pull request must change exactly one file, "
            f"{PROOF_DIR}/Sxxx.lean; this one changes: {names}"
        )
    status, name = files[0]
    m = PROOF_RE.match(name)
    if not m:
        raise Rejected(f"`{name}` is not a proof file ({PROOF_DIR}/Sxxx.lean)")
    if status not in ("A", "M"):
        raise Rejected(f"`{name}` must be added or modified, not `{status}`")
    step = m.group(1)
    if step not in step_ids():
        raise Rejected(f"{step} is not a step listed in steps.json")
    if step in retired_ids():
        raise Rejected(f"{step} is retired; see its issue for the reason")
    check_step(step)
    return [step]


def mode_all():
    known = step_ids()
    done = []
    for path in sorted((ROOT / PROOF_DIR).glob("*.lean")):
        m = PROOF_RE.match(f"{PROOF_DIR}/{path.name}")
        if not m or m.group(1) not in known:
            raise Rejected(f"unexpected file {PROOF_DIR}/{path.name}")
        check_step(m.group(1))
        done.append(m.group(1))
    return done


def main(argv):
    try:
        if len(argv) == 3 and argv[1] == "pr":
            steps = mode_pr(argv[2])
        elif len(argv) == 2 and argv[1] == "all":
            steps = mode_all()
        else:
            print(__doc__)
            return 2
    except Rejected as e:
        print(f"REJECTED: {e}")
        return 1
    except Fault as e:
        print(f"FAULT: {e}")
        return 2
    print("ACCEPTED: " + (", ".join(steps) if steps else "no proofs to check"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
