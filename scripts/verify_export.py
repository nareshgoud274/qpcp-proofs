#!/usr/bin/env python3
"""Check an untrusted Lean export against a trusted reference export.

    verify_export.py <kind> <ident> <untrusted.ndjson> <reference.ndjson>[,<more.ndjson>...] [<names>]
    verify_export.py deps <ident> <untrusted.ndjson>

Both files are lean4export NDJSON (format 3.x). The untrusted file was produced
inside the sandbox from the contributed module and may be forged; it is read
as data only. The reference file was produced outside the sandbox, from main's
trusted build, for a fixed list of names chosen by this repository (the
statement and the permitted axioms), never from names read out of the
untrusted file. For a lemma statement, which has no statement on main, the
reference also covers the constants the new definition refers to: `deps` lists
those names from the untrusted export, main exports them (with their whole
dependency closure, as main has them) and the comparison then applies to all
of them. A name that main does not have is refused.

Several reference files may be given, separated by commas: the export made
from main's maintainer-written modules, and, for a proof or refutation of a
contributed lemma, that lemma's own export once it has been verified. Where two
references declare the same name, they must agree.

<names> is the file of names the reference was requested for. Every one of
them must be declared in the reference, so that an export that silently came
out incomplete (leanexport exits 0 even when a name is missing) is refused.

Checks, all of which must hold:

  * the untrusted export is well formed, every id is defined before use, and
    no declaration name (including constructors and recursors) occurs twice;
  * every declaration in the reference (the statement's whole dependency
    closure, the axioms and, for a lemma, the closure of everything it refers
    to) occurs in the untrusted export with the same name and an identical
    structure, up to renaming of bound variables (kind, universe parameters,
    type, value, constructors), so all of it means exactly what it means on
    main;
  * the only axioms are propext, Classical.choice and Quot.sound;
  * the contribution's constant exists with exactly the required type:
      proof       theorem QPCP.Proof.<ID>       : <statement>
      refutation  theorem QPCP.Refutation.<ID>  : Not <statement>
      lemma       definition QPCP.Lemma.L<N>    : Prop
    with no universe parameters.

Type checking itself is done separately, by an independent kernel (nanoda_bin)
on the same untrusted file. Prints one line, ACCEPTED or REJECTED: <reason>, and
exits 0 or 1.
"""

import json
import re
import sys

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
DECL_KINDS = ("thm", "def", "axiom", "opaque", "quot", "inductive")
MAX_LINE = 50_000_000


class Bad(Exception):
    pass


class Export:
    """One export file, with every node interned into a shared canonical table."""

    def __init__(self, path, table):
        self.table = table          # shared: structural key -> canonical int
        self.names, self.levels, self.exprs = {0: ("anon",)}, {0: ("lzero",)}, {}
        self.raw_names, self.raw_levels, self.raw_exprs = {0: None}, {0: None}, {}
        self.decls = {}             # name string -> canonical declaration key
        self.lean = None
        self.read(path)

    # Interning keeps identical structure identical across both files.
    def intern(self, key):
        return self.table.setdefault(key, len(self.table))

    def name_str(self, nid):
        parts = []
        while nid != 0:
            rec = self.raw_names.get(nid)
            if rec is None:
                raise Bad(f"name {nid} used before it is defined")
            kind, pre, val = rec
            parts.append(str(val))
            nid = pre
        return ".".join(reversed(parts))

    def name(self, nid):
        if nid not in self.names:
            raise Bad(f"name {nid} used before it is defined")
        return self.names[nid]

    def level(self, lid):
        if lid not in self.levels:
            raise Bad(f"level {lid} used before it is defined")
        return self.levels[lid]

    def expr(self, eid):
        if eid not in self.exprs:
            raise Bad(f"expression {eid} used before it is defined")
        return self.exprs[eid]

    def read(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if len(line) > MAX_LINE:
                    raise Bad(f"line {lineno} is too long")
                try:
                    o = json.loads(line)
                except ValueError:
                    raise Bad(f"line {lineno} is not JSON")
                if not isinstance(o, dict):
                    raise Bad(f"line {lineno} is not an object")
                try:
                    self.record(o)
                except (KeyError, TypeError, ValueError) as e:
                    raise Bad(f"line {lineno} is malformed ({type(e).__name__}: {e})")

    def record(self, o):
        if "meta" in o:
            self.lean = (o["meta"].get("lean") or {}).get("version")
            return
        if "in" in o:
            nid = o["in"]
            if nid in self.names:
                raise Bad(f"name id {nid} defined twice")
            if "str" in o:
                pre, val = o["str"]["pre"], o["str"]["str"]
                key = ("nstr", self.name(pre), str(val))
            else:
                pre, val = o["num"]["pre"], o["num"]["i"]
                key = ("nnum", self.name(pre), int(val))
            self.raw_names[nid] = ("s", pre, val)
            self.names[nid] = self.intern(key)
            return
        if "il" in o:
            lid = o["il"]
            if lid in self.levels:
                raise Bad(f"level id {lid} defined twice")
            if "succ" in o:
                key = ("lsucc", self.level(o["succ"]))
            elif "max" in o:
                a, b = o["max"]
                key = ("lmax", self.level(a), self.level(b))
            elif "imax" in o:
                a, b = o["imax"]
                key = ("limax", self.level(a), self.level(b))
            elif "param" in o:
                key = ("lparam", self.name(o["param"]))
            else:
                raise Bad(f"unknown level form {sorted(o)}")
            self.levels[lid] = self.intern(key)
            return
        if "ie" in o:
            eid = o["ie"]
            if eid in self.exprs:
                raise Bad(f"expression id {eid} defined twice")
            self.exprs[eid] = self.intern(self.expr_key(o))
            return
        kinds = [k for k in DECL_KINDS if k in o]
        if len(kinds) != 1:
            raise Bad(f"unknown record {sorted(o)[:4]}")
        self.decl(kinds[0], o[kinds[0]])

    def expr_key(self, o):
        if "bvar" in o:
            return ("bvar", int(o["bvar"]))
        if "sort" in o:
            return ("sort", self.level(o["sort"]))
        if "const" in o:
            c = o["const"]
            return ("const", self.name(c["name"]), tuple(self.level(u) for u in c["us"]))
        if "app" in o:
            a = o["app"]
            return ("app", self.expr(a["fn"]), self.expr(a["arg"]))
        # Binder names and binder annotations are ignored, as the kernel ignores
        # them: terms are compared up to renaming of bound variables. (Lean does
        # not always pick the same binder names, e.g. in recursor rules.)
        for binder in ("lam", "forallE"):
            if binder in o:
                b = o[binder]
                self.name(b["name"])  # must still be defined
                return (binder, self.expr(b["type"]), self.expr(b["body"]))
        if "letE" in o:
            b = o["letE"]
            self.name(b["name"])
            return ("letE", self.expr(b["type"]), self.expr(b["value"]),
                    self.expr(b["body"]), bool(b["nondep"]))
        if "natVal" in o:
            return ("nat", str(o["natVal"]))
        if "strVal" in o:
            return ("str", str(o["strVal"]))
        if "mdata" in o:
            m = o["mdata"]
            return ("mdata", json.dumps(m.get("data"), sort_keys=True), self.expr(m["expr"]))
        if "proj" in o:
            p = o["proj"]
            return ("proj", self.name(p["typeName"]), int(p["idx"]), self.expr(p["struct"]))
        raise Bad(f"unknown expression form {sorted(o)}")

    def canon_name_strings(self):
        """Canonical name id -> dotted string, for every name in this export."""
        return {self.names[nid]: self.name_str(nid) for nid in self.raw_names if nid}

    def add_decl(self, name_id, key):
        name = self.name_str(name_id)
        if name in self.decls:
            raise Bad(f"`{name}` is declared twice")
        self.decls[name] = key

    def decl(self, kind, d):
        if kind == "inductive":
            # One record holds the types, constructors and recursors of a
            # mutual block; each gets its own entry, keyed by everything.
            whole = self.intern(("inductive", json.dumps(self.canon_json(d), sort_keys=True)))
            for t in d.get("types", []):
                self.add_decl(t["name"], ("inductive-type", whole))
            for c in d.get("ctors", []):
                self.add_decl(c["name"], ("inductive-ctor", whole))
            for r in d.get("recs", []):
                self.add_decl(r["name"], ("inductive-rec", whole))
            if not (d.get("types") or d.get("ctors") or d.get("recs")):
                raise Bad("empty inductive record")
            return
        lps = tuple(self.name(n) for n in d["levelParams"])
        key = [kind, lps, self.expr(d["type"])]
        if kind in ("thm", "def", "opaque"):
            key.append(self.expr(d["value"]))
        if kind == "def":
            key.append(json.dumps(d.get("hints"), sort_keys=True))
            key.append(str(d.get("safety")))
        if kind in ("axiom", "opaque"):
            key.append(bool(d.get("isUnsafe")))
        if kind == "quot":
            key.append(str(d.get("kind")))
        self.add_decl(d["name"], tuple(key))

    def canon_json(self, v, field=None):
        """Replace export ids inside an inductive record by canonical ids."""
        if isinstance(v, dict):
            return {k: self.canon_json(x, k) for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [self.canon_json(x, field) for x in v]
        if isinstance(v, int) and not isinstance(v, bool):
            if field in ("name", "induct", "ctor", "all", "levelParams", "ctors"):
                return ["n", self.name(v)]
            if field in ("type", "rhs"):
                return ["e", self.expr(v)]
        return v


def required_type(kind, ident, ref):
    stmt = f"QPCP.Statement.{ident}" if ident.startswith("S") else f"QPCP.Lemma.{ident}"
    if kind == "lemma":
        return f"QPCP.Lemma.{ident}", "def", ("sort", ref.levels[0]), stmt
    return (f"QPCP.Proof.{ident}" if kind == "proof" else f"QPCP.Refutation.{ident}"), "thm", stmt, stmt


class MergedReference:
    """Several reference exports seen as one: their declarations, levels and names."""

    def __init__(self, exports):
        self.parts = exports
        self.lean = exports[0].lean
        self.decls = {}
        for e in exports:
            if e.lean != self.lean:
                raise Bad("the reference exports were made by different Lean versions")
            for name, key in e.decls.items():
                if name in self.decls and self.decls[name] != key:
                    raise Bad(f"the references disagree on `{name}`")
                self.decls[name] = key
        self.levels = exports[0].levels

    def name_id(self, dotted):
        for e in self.parts:
            try:
                return ref_name_id(e, dotted)
            except Bad:
                continue
        raise Bad(f"the reference does not name `{dotted}`")


def verify(kind, ident, untrusted_path, reference_path, names_path=None):
    table = {}
    ref = MergedReference([Export(p, table) for p in reference_path.split(",") if p])
    unt = Export(untrusted_path, table)
    if ref.lean is None or unt.lean != ref.lean:
        raise Bad(f"export was made by Lean {unt.lean}, expected {ref.lean}")
    requested = set(ALLOWED_AXIOMS)
    if names_path:
        requested |= {line.strip() for line in open(names_path, encoding="utf-8") if line.strip()}
    missing = sorted(n for n in requested if n not in ref.decls)
    if missing:
        raise Bad(f"main has no `{missing[0]}` (the reference export is incomplete)")

    for name, key in ref.decls.items():
        if name not in unt.decls:
            raise Bad(f"`{name}` from main is missing")
        if unt.decls[name] != key:
            raise Bad(f"`{name}` differs from main's")

    for name, key in unt.decls.items():
        if key[0] == "axiom" and name not in ALLOWED_AXIOMS:
            raise Bad(f"declares the axiom `{name}`")

    target, want_kind, want, stmt = required_type(kind, ident, ref)
    if target not in unt.decls:
        raise Bad(f"`{target}` is missing")
    got = unt.decls[target]
    if got[0] != want_kind or got[1] != ():
        raise Bad(f"`{target}` is not a {'definition' if want_kind == 'def' else 'theorem'} without universe parameters")
    if kind == "lemma":
        want_type = table[("sort", ref.levels[0])]
    else:
        if stmt not in ref.decls:
            raise Bad(f"the reference does not contain `{stmt}`")
        # Build the expected type from the reference's own name table.
        stmt_name = ref.name_id(stmt)
        c = table.get(("const", stmt_name, ()))
        if c is None:
            raise Bad(f"`{target}` does not have type `{stmt}`")
        if kind == "proof":
            want_type = c
        else:
            not_name = ref.name_id("Not")
            not_c = table.get(("const", not_name, ()))
            want_type = table.get(("app", not_c, c)) if not_c is not None else None
    if want_type is None or got[2] != want_type:
        raise Bad(f"`{target}` does not have exactly the required type")


NAME_SEGMENT = re.compile(r"[A-Za-z_\u0080-\uffff][A-Za-z0-9_'!?\u0080-\uffff]*")


def lemma_deps(ident, untrusted_path):
    """Names outside the lemma that QPCP.Lemma.<ident> refers to, directly or
    through constants of its own (QPCP.Lemma.<ident>.*)."""
    table = {}
    unt = Export(untrusted_path, table)
    inv = {i: k for k, i in table.items()}
    names = unt.canon_name_strings()
    own = f"QPCP.Lemma.{ident}"
    mine = lambda n: n == own or n.startswith(own + ".")
    if own not in unt.decls:
        raise Bad(f"`{own}` is missing")
    out, seen_decls, todo = set(), set(), [own]
    while todo:
        d = todo.pop()
        if d in seen_decls:
            continue
        seen_decls.add(d)
        key = unt.decls[d]
        if key[0] not in ("def", "thm", "opaque"):
            raise Bad(f"`{d}` is not a definition or theorem")
        stack, seen = [key[2], key[3]], set()  # type and value
        while stack:
            c = stack.pop()
            if not isinstance(c, int) or c in seen or c not in inv:
                continue
            seen.add(c)
            k = inv[c]
            if k[0] == "const":
                n = names.get(k[1])
                if n is None:
                    raise Bad("a constant has no name")
                if mine(n):
                    if n not in unt.decls:
                        raise Bad(f"`{n}` is used but not declared")
                    todo.append(n)
                else:
                    out.add(n)
            elif k[0] in ("app", "lam", "forallE"):
                stack.extend((k[1], k[2]))
            elif k[0] == "letE":
                stack.extend((k[1], k[2], k[3]))
            elif k[0] == "mdata":
                stack.append(k[2])
            elif k[0] == "proj":
                stack.append(k[3])
    for n in out:
        if not all(NAME_SEGMENT.fullmatch(s) for s in n.split(".")):
            raise Bad(f"refers to `{n}`, a name this checker does not accept")
    return sorted(out)


def ref_name_id(ref, dotted):
    """Canonical id of a dotted name, built only from names in the reference."""
    for nid in ref.raw_names:
        if nid and ref.name_str(nid) == dotted:
            return ref.names[nid]
    raise Bad(f"the reference does not name `{dotted}`")


def main(argv):
    if len(argv) == 4 and argv[1] == "deps":
        try:
            print("\n".join(lemma_deps(argv[2], argv[3])))
        except Bad as e:
            print(f"REJECTED: {e}")
            return 1
        return 0
    if len(argv) not in (5, 6) or argv[1] not in ("proof", "refutation", "lemma"):
        print(__doc__)
        return 2
    try:
        verify(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) == 6 else None)
    except Bad as e:
        print(f"REJECTED: {e}")
        return 1
    except (OSError, RecursionError, MemoryError) as e:
        print(f"REJECTED: cannot read the export ({type(e).__name__})")
        return 1
    print(f"ACCEPTED: {argv[1]} {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
