#!/usr/bin/env python3
"""Checker for qpcp-proofs.

A contribution is one new Lean file of one of three kinds:

  QPCP/Proofs/<ID>.lean        proves the statement <ID>
  QPCP/Refutations/<ID>.lean   proves the negation of the statement <ID>
  QPCP/Lemmas/L<N>.lean        states a new lemma (a proposition, no proof)

<ID> is either a founding step S001, S002, ... (statement
QPCP.Statement.<ID>, listed in steps.json) or a contributed lemma L<N>
(statement QPCP.Lemma.L<N>, stated in QPCP/Lemmas/L<N>.lean).

Modes:

  check.py scan <base-ref>   CI: every check on a contributor's pull request
                             that runs no Lean (one new file, allowed kind,
                             statement exists, source scanner). Lean checks
                             follow in scripts/contribution_check.sh.
  check.py scan-file <kind> <id> <path>
                             Tests: run the source scanner on any file.
  check.py pr <base-ref>     Local only: scan, then build and check the
                             contribution without a sandbox.
  check.py all               Re-check every contribution on the current tree.

Verdicts are printed as ACCEPTED or REJECTED with a reason. Exit code 0 means
accepted, 1 means rejected, 2 means the checker itself failed (FAULT).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ID = r"(?:S\d{3,6}|L\d{1,9})"
KINDS = {
    "proof": ("QPCP/Proofs", "QPCP.Proofs", "QPCP.Proof"),
    "refutation": ("QPCP/Refutations", "QPCP.Refutations", "QPCP.Refutation"),
    "lemma": ("QPCP/Lemmas", "QPCP.Lemmas", "QPCP.Lemma"),
}
PATH_RES = {
    "proof": re.compile(rf"^QPCP/Proofs/({ID})\.lean$"),
    "refutation": re.compile(rf"^QPCP/Refutations/({ID})\.lean$"),
    "lemma": re.compile(r"^QPCP/Lemmas/(L\d{1,9})\.lean$"),
}

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
BASE_IMPORTS = r"Mathlib(\.[A-Za-z0-9_]+)*|QPCP\.Defs|QPCP\.Qudit|QPCP\.Statements"
# A statement may use Mathlib and the project's definitions, nothing else.
LEMMA_IMPORT_RE = re.compile(rf"^({BASE_IMPORTS})$")
# A proof or refutation may also use stated lemmas and settled results.
PROOF_IMPORT_RE = re.compile(
    rf"^({BASE_IMPORTS}|QPCP\.Lemmas\.L\d{{1,9}}|QPCP\.Proofs\.{ID}|QPCP\.Refutations\.{ID})$"
)

# Text-level guards. Lean runs code while it elaborates a file, so a contributed
# file must not reach any evaluation entry point, and must not name anything
# that performs effects. This is a deny-list: it blocks every route found so far
# (see tests/attacks/), but it cannot be proven complete.
FORBIDDEN_TOKENS = [
    # Proof holes and trust escapes.
    "sorry", "admit", "axiom", "set_option", "debug.skipKernelTC",
    # Evaluation entry points.
    "run_tac", "by_elab", "run_cmd", "run_elab", "run_meta", "eval%", "test_extern",
    "simproc", "simproc_decl", "dsimproc", "dsimproc_decl",
    "elab", "elab_rules", "macro", "macro_rules", "syntax", "declare_syntax_cat",
    "notation", "notation3", "prefix", "infix", "infixl", "infixr", "postfix",
    "initialize", "builtin_initialize",
    # Code-shaped constructs a proof does not need.
    "do", "`(", "unsafe", "implemented_by", "extern", "opaque", "partial",
    "IO", "BaseIO", "EIO", "unsafeBaseIO", "unsafeIO", "unsafeEIO", "unsafeCast",
    # External tools and native code.
    "polyrith", "native_decide", "+native", "bv_decide", "include_str",
    # Name quoting, which could spell any forbidden name.
    "«",
]
# Namespaces that hold effectful or meta-level code. Refused as a qualified
# name (`IO.FS...`, `_root_.IO...`) and after `open`, `export` or `namespace`.
EFFECT_NAMESPACES = ["Lean", "IO", "System", "Elab", "Meta", "Core", "Macro", "Syntax", "FS", "Process"]
# The only attributes a contributed file may use.
ALLOWED_ATTRIBUTES = {"simp", "ext"}
QUOTE = "\u0000quote\u0000"
# A statement file holds one proposition and must not change how files that
# import it behave, so declarations other than its single `def` are refused.
LEMMA_FORBIDDEN_TOKENS = [
    "theorem", "lemma", "example", "instance", "attribute", "structure",
    "inductive", "class", "abbrev", "opaque", "deriving", "local", "scoped",
    "variable", "@[", "prefix", "infix", "infixl", "infixr", "postfix",
]
MAX_BYTES = 200_000
MIN_PLAIN_CHARS = 20


class Rejected(Exception):
    pass


class Fault(Exception):
    pass


def run(cmd, timeout=1500):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Rejected(f"`{' '.join(cmd)}` did not finish within {timeout} seconds")
    except FileNotFoundError as e:
        raise Fault(f"command not found: {e}")


def read_json(name, default=None):
    path = ROOT / name
    if not path.is_file():
        if default is not None:
            return default
        raise Fault(f"{name} is missing")
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        raise Fault(f"cannot read {name}: {e}")


def founding_ids():
    return {s["id"] for s in read_json("steps.json")}


def retired_ids():
    """Founding steps flagged in steps.json, plus any id listed in retired.json."""
    out = {s["id"] for s in read_json("steps.json") if s.get("retired") is True}
    out |= set(read_json("retired.json", default=[]))
    return out


def open_programs():
    return {p["id"] for p in read_json("programs.json", default=[]) if p.get("open") is True}


def statement_name(ident):
    return f"QPCP.Statement.{ident}" if ident.startswith("S") else f"QPCP.Lemma.{ident}"


def file_of(kind, ident):
    return ROOT / KINDS[kind][0] / f"{ident}.lean"


def statement_exists(ident):
    if ident.startswith("S"):
        return ident in founding_ids()
    return file_of("lemma", ident).is_file()


def strip_comments(src):
    """Remove Lean comments so token scans see only code.

    Contributed files may not contain string literals at all: every `"` outside
    a comment is replaced by a marker that the scanner refuses. Strings are
    never skipped over, so no literal (a char literal '"', a raw string, an
    interpolated string such as s!"{...}" or dbg_trace "{...}") can hide code
    from the scan.
    """
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
            out.append(QUOTE)
            i += 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def has_token(code, tok):
    if tok[0].isalpha() and tok[-1].isalnum():
        pattern = r"(?<![A-Za-z0-9_.'])" + re.escape(tok) + r"(?![A-Za-z0-9_'])"
    else:
        pattern = re.escape(tok)
    return re.search(pattern, code) is not None


NS_ALT = "|".join(EFFECT_NAMESPACES)
# `IO.x`, `_root_.IO.x`, `Foo.Lean.x`: an effect namespace as any name component.
QUALIFIED_NS_RE = re.compile(rf"(?<![A-Za-z0-9_'])(?:{NS_ALT})\.")
SCOPE_LINE_RE = re.compile(r"(?<![A-Za-z0-9_.'])(open|export|namespace)(?![A-Za-z0-9_'])([^\n]*)")
ATTR_RE = re.compile(r"@\[([^\]]*)\]")
ATTRIBUTE_CMD_RE = re.compile(r"(?<![A-Za-z0-9_.'])attribute\s*\[([^\]]*)\]")
HASH_CMD_RE = re.compile(r"#[A-Za-z!]")
ASCII_BIND_RE = re.compile(r"<-(?!>)")  # `<-` but not the ASCII iff `<->`


def forbidden_construct(code, kind):
    """The first forbidden construct in comment-stripped `code`, or None."""
    if QUOTE in code:
        return "a string literal (`\"`)"
    if re.search(r"\bnative\s*:=", code):
        return "`native :=`"
    tokens = FORBIDDEN_TOKENS + (LEMMA_FORBIDDEN_TOKENS if kind == "lemma" else [])
    for tok in tokens:
        if has_token(code, tok):
            return f"`{tok}`"
    if ASCII_BIND_RE.search(code):
        return "`<-`"
    # `←` is a bind in `do` code. In a proof it only reverses a rewrite rule,
    # `rw [← h]` or `simp [a, ← b]`, so it is allowed only right after `[` or `,`.
    # This is the one exception to the H2 rules; see MAINTAINERS.md.
    for m in re.finditer("←", code):
        before = code[:m.start()].rstrip()
        if not before or before[-1] not in "[,":
            return "`←` outside a rewrite rule list"
    if HASH_CMD_RE.search(code):
        return f"the command `{HASH_CMD_RE.search(code).group(0)}...`"
    m = QUALIFIED_NS_RE.search(code)
    if m:
        return f"the namespace `{m.group(0)[:-1]}`"
    for m in SCOPE_LINE_RE.finditer(code):
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_'.]*", m.group(2)):
            if any(part in EFFECT_NAMESPACES for part in word.split(".")):
                return f"`{m.group(1)} {word}`"
    if kind != "lemma":
        for m in list(ATTR_RE.finditer(code)) + list(ATTRIBUTE_CMD_RE.finditer(code)):
            items = [a.strip() for a in m.group(1).split(",")]
            bad = [a for a in items if a not in ALLOWED_ATTRIBUTES]
            if bad:
                return f"the attribute `{bad[0]}` (only {', '.join(sorted(ALLOWED_ATTRIBUTES))} are allowed)"
        if re.search(r"(?<![A-Za-z0-9_.'])attribute(?![A-Za-z0-9_'])", code) and not ATTRIBUTE_CMD_RE.search(code):
            return "`attribute`"
    return None


def lemma_header(src):
    """Return (program, plain) from the `PROGRAM:` and `PLAIN:` header lines."""
    program = re.search(r"^\s*PROGRAM:\s*([a-z0-9-]+)\s*$", src, re.M)
    plain = re.search(r"^\s*PLAIN:\s*(.+?)\s*$", src, re.M)
    return (program.group(1) if program else None, plain.group(1) if plain else None)


def scan_source(kind, ident, path=None):
    path = Path(path) if path else file_of(kind, ident)
    rel = f"{KINDS[kind][0]}/{ident}.lean"
    if not path.is_file():
        raise Rejected(f"{rel} does not exist")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise Rejected(f"{rel} is larger than {MAX_BYTES} bytes")
    try:
        src = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected(f"{rel} is not valid UTF-8")
    code = strip_comments(src)

    import_re = LEMMA_IMPORT_RE if kind == "lemma" else PROOF_IMPORT_RE
    own_module = f"{KINDS[kind][1]}.{ident}"
    for line in code.splitlines():
        m = re.match(r"^\s*(?:public\s+|private\s+|meta\s+)*import\s+(.*)$", line)
        if not m:
            continue
        for mod in m.group(1).split():
            if not import_re.match(mod):
                raise Rejected(f"import of `{mod}` is not allowed in a {kind} file")
            if mod == own_module:
                raise Rejected("a file cannot import itself")

    reason = forbidden_construct(code, kind)
    if reason:
        raise Rejected(f"{reason} is not allowed in a {kind} file")

    if kind == "lemma":
        defs = re.findall(r"(?<![A-Za-z0-9_.'])def\s+([^\s:(\[{]+)", code)
        if defs not in ([ident], [f"QPCP.Lemma.{ident}"]):
            raise Rejected(
                f"a lemma file must contain exactly one definition, `def {ident} : Prop`, "
                f"inside `namespace QPCP.Lemma`; found: {', '.join(defs) or 'none'}"
            )
        if not re.search(rf"def\s+(QPCP\.Lemma\.)?{ident}\s*:\s*Prop\s*:=", code):
            raise Rejected(f"the definition must read `def {ident} : Prop := ...` with no arguments")
        program, plain = lemma_header(src)
        if program is None:
            raise Rejected("the header comment needs a line `PROGRAM: <program id>`")
        if program not in open_programs():
            raise Rejected(f"`{program}` is not an open program in programs.json")
        if plain is None or len(plain) < MIN_PLAIN_CHARS:
            raise Rejected(
                "the header comment needs a line `PLAIN: <the statement in plain words>` "
                f"of at least {MIN_PLAIN_CHARS} characters"
            )
    else:
        name = "Proof" if kind == "proof" else "Refutation"
        if not re.search(rf"\btheorem\s+(QPCP\.{name}\.)?{ident}\b", code):
            raise Rejected(f"the file must declare `theorem QPCP.{name}.{ident}`")


def check_lines(kind, ident):
    """Lean lines that pin the contribution to its exact type and print its axioms."""
    stmt = statement_name(ident)
    if kind == "proof":
        name = f"QPCP.Check.P_{ident}"
        return name, [f"theorem {name} : {stmt} := QPCP.Proof.{ident}", f"#print axioms {name}"]
    if kind == "refutation":
        name = f"QPCP.Check.R_{ident}"
        return name, [f"theorem {name} : ¬ {stmt} := QPCP.Refutation.{ident}", f"#print axioms {name}"]
    name = f"QPCP.Check.L_{ident}"
    return name, [f"def {name} : Prop := {stmt}", f"#print axioms {name}"]


def parse_axioms(output, name):
    """Axioms `#print axioms` reported for `name`, or None if no report is found."""
    m = re.search(rf"'{re.escape(name)}'\s+does not depend on any axioms", output)
    if m:
        return set()
    m = re.search(rf"'{re.escape(name)}'\s+depends on axioms:\s*\[(.*?)\]", output, re.S)
    if not m:
        return None
    return {a.strip() for a in m.group(1).replace("\n", " ").split(",") if a.strip()}


def lean_check(items, build_targets):
    """Build, then verify exact types and axioms for every (kind, ident) in items."""
    if not items:
        return
    build = run(["lake", "build", *build_targets])
    if build.returncode != 0:
        raise Rejected("`lake build` failed:\n" + (build.stdout + build.stderr)[-4000:])

    lines, names = [], []
    for kind, ident in items:
        lines.append(f"import {KINDS[kind][1]}.{ident}")
    lines.append("")
    for kind, ident in items:
        name, body = check_lines(kind, ident)
        names.append((name, kind, ident))
        lines.extend(body)
    check_file = ROOT / "Check_all.lean"
    check_file.write_text("\n".join(lines) + "\n")
    try:
        res = run(["lake", "env", "lean", check_file.name], timeout=1500)
    finally:
        check_file.unlink(missing_ok=True)
    out = res.stdout + res.stderr
    if res.returncode != 0:
        raise Rejected("a contribution does not have its required type:\n" + out[-4000:])
    for name, kind, ident in names:
        axioms = parse_axioms(out, name)
        if axioms is None:
            raise Fault(f"no axiom report for the {kind} of {ident}:\n{out[-2000:]}")
        extra = axioms - ALLOWED_AXIOMS
        if extra:
            raise Rejected(
                f"the {kind} of {ident} depends on disallowed axioms: " + ", ".join(sorted(extra))
            )


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


def classify(name):
    for kind, rx in PATH_RES.items():
        m = rx.match(name)
        if m:
            return kind, m.group(1)
    return None, None


def precheck(base):
    """Every check on a contributor's pull request that runs no Lean."""
    files = changed_files(base)
    if len(files) != 1:
        names = ", ".join(n for _, n in files) or "none"
        raise Rejected(
            "a contribution must add exactly one file under QPCP/Proofs, "
            f"QPCP/Refutations or QPCP/Lemmas; this one changes: {names}"
        )
    status, name = files[0]
    kind, ident = classify(name)
    if kind is None:
        raise Rejected(f"`{name}` is not a proof, refutation or lemma file")
    if status != "A":
        raise Rejected(f"`{name}` already exists; contributions add new files only")

    if kind in ("proof", "refutation"):
        if not statement_exists(ident):
            raise Rejected(f"there is no statement {ident} on main")
        if ident in retired_ids():
            raise Rejected(f"{ident} is retired; see its issue for the reason")
        other = "refutation" if kind == "proof" else "proof"
        if file_of(other, ident).is_file():
            raise Rejected(f"{ident} is already settled by a {other}")
    scan_source(kind, ident)
    return kind, ident, name


def mode_scan(base):
    """Pre-Lean checks for CI. Prints `kind ident path` for the sandboxed check."""
    kind, ident, name = precheck(base)
    print(f"CONTRIBUTION: {kind} {ident} {name}")
    return [f"{kind} {ident} (scan only)"]


def mode_scan_file(kind, ident, path):
    """Scan one file at any path as a contribution of the given kind (for tests)."""
    if kind not in KINDS or not re.fullmatch(ID if kind != "lemma" else r"L\d{1,9}", ident):
        raise Rejected(f"bad kind or id: {kind} {ident}")
    scan_source(kind, ident, path)
    return [f"{kind} {ident} (scan only)"]


def mode_pr(base):
    """Local use only: checks a pull request by building it WITHOUT a sandbox.

    CI uses `scan` followed by scripts/contribution_check.sh, which builds the
    contribution in a sandbox and verifies an export of it instead.
    """
    kind, ident, _ = precheck(base)
    lean_check([(kind, ident)], [f"{KINDS[kind][1]}.{ident}"])
    return [f"{kind} {ident}"]


def mode_all():
    items = []
    for kind, (folder, _, _) in KINDS.items():
        for path in sorted((ROOT / folder).glob("*.lean")):
            got_kind, ident = classify(f"{folder}/{path.name}")
            if got_kind != kind:
                raise Rejected(f"unexpected file {folder}/{path.name}")
            if kind != "lemma" and not statement_exists(ident):
                raise Rejected(f"{folder}/{path.name} has no statement {ident}")
            scan_source(kind, ident)
            items.append((kind, ident))
    settled = {}
    for kind, ident in items:
        if kind == "lemma":
            continue
        if ident in settled:
            raise Rejected(f"{ident} has both a proof and a refutation")
        settled[ident] = kind
    # One build of the whole library, then one Lean run that checks everything.
    lean_check(items, ["QPCP"])
    return [f"{kind} {ident}" for kind, ident in items]


def summarize(done):
    if not done:
        return "nothing to check"
    if len(done) <= 40:
        return ", ".join(done)
    counts = {}
    for d in done:
        counts[d.split()[0]] = counts.get(d.split()[0], 0) + 1
    return ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in sorted(counts.items()))


def main(argv):
    try:
        if len(argv) == 3 and argv[1] == "pr":
            done = mode_pr(argv[2])
        elif len(argv) == 3 and argv[1] == "scan":
            done = mode_scan(argv[2])
        elif len(argv) == 5 and argv[1] == "scan-file":
            done = mode_scan_file(argv[2], argv[3], argv[4])
        elif len(argv) == 2 and argv[1] == "all":
            done = mode_all()
        else:
            print(__doc__)
            return 2
    except Rejected as e:
        print(f"REJECTED: {e}")
        return 1
    except Fault as e:
        print(f"FAULT: {e}")
        return 2
    print("ACCEPTED: " + summarize(done))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
