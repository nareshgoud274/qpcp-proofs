#!/usr/bin/env python3
"""Check an untrusted Lean export against a trusted reference export.

    verify_export.py canon <untrusted.ndjson> <canonical.ndjson>
    verify_export.py <kind> <ident> <untrusted.ndjson> <reference.ndjson>[,<more.ndjson>...] [<names>]
    verify_export.py deps <ident> <untrusted.ndjson>

Both files are lean4export NDJSON (format 3.x). The untrusted file was produced
inside the sandbox from the contributed module and may be forged; it is read
as data only. The reference file was produced outside the sandbox, from main's
trusted build, for a fixed list of names chosen by this repository (the
statement, the permitted axioms, the Quot declarations and `Not`), never from
names read out of the untrusted file. For a lemma statement, which has no
statement on main, the reference also covers the constants the new definition
refers to: `deps` lists those names from the untrusted export, main exports
them (with their whole dependency closure, as main has them) and the
comparison then applies to all of them. A name that main does not have is
refused.

Strict reading. Every line is parsed strictly, and the file is refused unless:

  * every line is one JSON object with no duplicate keys, no NaN or Infinity
    and no floating-point numbers;
  * every record has exactly the keys of one record kind, at every level of
    nesting, with values of exactly the right JSON type (no `true` or `"1"`
    for a number), and ids are integers numbered 0, 1, 2, ... (names and
    levels from 1) in order, each defined before it is used;
  * the meta record comes first and only once; `mdata` is refused;
  * every string component of a name matches NAME_SEGMENT (so no component
    contains a dot). The one exception is Lean's macro-scope marker `_@`:
    a name that contains it may name a bound variable or a universe
    parameter, which the comparison ignores or checks structurally, and
    nothing else;
  * every definition is `safe`; no axiom, opaque or inductive is unsafe; the
    only quot declarations are Quot, Quot.mk, Quot.lift and Quot.ind.

`canon` writes the strictly read file again in a canonical form, built field
by field from the validated values only. The independent kernel (nanoda_bin)
reads that canonical file and nothing else, so the two checkers cannot be
shown different files or read one file differently.

Several reference files may be given, separated by commas: the export made
from main's maintainer-written modules, and, for a proof or refutation of a
contributed lemma, that lemma's own (canonical, verified) export. Where two
references declare the same name, they must agree.

<names> is the file of names the reference was requested for. Every one of
them, and always the axioms, the Quot declarations and `Not`, must be
declared in the reference, so that an export that silently came out
incomplete (leanexport exits 0 even when a name is missing) is refused.

The comparison, all of which must hold:

  * no declaration name (including constructors and recursors) occurs twice;
  * every declaration in the reference occurs in the untrusted export under
    the same canonical name id and the same dotted name, with an identical
    structure up to renaming of bound variables (kind, universe parameters,
    type, value, constructors), so all of it means exactly what it means on
    main;
  * the only axioms are propext, Classical.choice and Quot.sound;
  * the contribution's constant exists with exactly the required type:
      proof       theorem QPCP.Proof.<ID>       : <statement>
      refutation  theorem QPCP.Refutation.<ID>  : Not <statement>
      lemma       definition QPCP.Lemma.L<N>    : Prop
    with no universe parameters. Expected names are built from fixed strings,
    component by component, never looked up by their printed form.

Prints one line, ACCEPTED or REJECTED: <reason>, and exits 0 or 1.
"""

import json
import re
import sys

ALLOWED_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
QUOT_DECLS = {"Quot": "type", "Quot.mk": "ctor", "Quot.lift": "lift", "Quot.ind": "ind"}
ALWAYS_REQUIRED = (*ALLOWED_AXIOMS, *QUOT_DECLS, "Not")
MAX_LINE = 50_000_000
MAX_NAT_DIGITS = 100_000
NAME_SEGMENT = re.compile(r"(?:[A-Za-z_]|[^\x00-\x7f\s])(?:[A-Za-z0-9_'!?]|[^\x00-\x7f\s])*")
MACRO_SCOPE = "_@"
ANON = ("anon",)
LZERO = ("lzero",)
BINDER_INFOS = {"default", "implicit", "strictImplicit", "instImplicit"}
SAFETIES = {"safe", "unsafe", "partial"}


class Bad(Exception):
    pass


# ------------------------------------------------------------ strict JSON

def _no_duplicates(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise Bad(f"duplicate key `{k}`")
        obj[k] = v
    return obj


def _no_constant(name):
    raise Bad(f"`{name}` is not allowed")


def _no_float(text):
    raise Bad(f"the number {text[:20]} is not an integer")


def strict_json(line):
    try:
        return json.loads(line, object_pairs_hook=_no_duplicates,
                          parse_constant=_no_constant, parse_float=_no_float)
    except ValueError:
        raise Bad("not JSON")


def is_nat(v):
    return type(v) is int and v >= 0


def plain_str(v):
    if type(v) is not str:
        return False
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:   # a lone surrogate
        return False
    return True


def exact_keys(o, keys, what):
    if type(o) is not dict:
        raise Bad(f"{what} is not an object")
    if set(o) != set(keys):
        extra, missing = sorted(set(o) - set(keys)), sorted(set(keys) - set(o))
        raise Bad(f"{what} has unexpected keys" + (f" {extra}" if extra else "")
                  + (f", lacks {missing}" if missing else ""))


# ------------------------------------------------------------ export

RECORD_KINDS = {
    "in": ("str", "num"),
    "il": ("succ", "max", "imax", "param"),
    "ie": ("bvar", "sort", "const", "app", "lam", "forallE", "letE", "natVal", "strVal", "proj", "mdata"),
}
DECL_KINDS = ("thm", "def", "axiom", "opaque", "quot", "inductive")


class Export:
    """One export file, read strictly, with every node interned into a shared table."""

    def __init__(self, path, table, sink=None):
        self.table = table          # shared: structural key -> canonical int
        self.names, self.levels, self.exprs = {0: ANON}, {0: LZERO}, {}
        self.raw_names = {0: None}  # export id -> (pre, component)
        self.scoped = set()         # export ids of names with a `_@` component
        self.next = {"in": 1, "il": 1, "ie": 0}
        self.decls = {}             # canonical name id -> declaration key
        self.decl_names = {}        # canonical name id -> dotted string
        self.by_string = {}         # dotted string -> canonical name id
        self.quots = []             # (dotted name, kind)
        self.lean = None
        self.sink = sink
        self.read(path)

    def intern(self, key):
        return self.table.setdefault(key, len(self.table))

    # ---- ids
    def name(self, nid, use="name"):
        if not is_nat(nid):
            raise Bad(f"a name id ({nid!r}) is not a natural number")
        if nid not in self.names:
            raise Bad(f"name {nid} used before it is defined")
        if use != "bound" and nid in self.scoped:
            raise Bad(f"the macro-scoped name `{self.name_str(nid)}` is used as a {use}")
        return self.names[nid]

    def level(self, lid):
        if not is_nat(lid):
            raise Bad(f"a level id ({lid!r}) is not a natural number")
        if lid not in self.levels:
            raise Bad(f"level {lid} used before it is defined")
        return self.levels[lid]

    def expr(self, eid):
        if not is_nat(eid):
            raise Bad(f"an expression id ({eid!r}) is not a natural number")
        if eid not in self.exprs:
            raise Bad(f"expression {eid} used before it is defined")
        return self.exprs[eid]

    def name_str(self, nid):
        parts = []
        while nid != 0:
            pre, val = self.raw_names[nid]
            parts.append(str(val))
            nid = pre
        return ".".join(reversed(parts))

    def nat_list(self, v, what):
        if type(v) is not list:
            raise Bad(f"{what} is not a list")
        return v

    # ---- reading
    def read(self, path):
        with open(path, "r", encoding="utf-8", errors="strict") as fh:
            lineno = 0
            for lineno, line in enumerate(fh, 1):
                if len(line) > MAX_LINE:
                    raise Bad(f"line {lineno} is too long")
                try:
                    o = strict_json(line)
                    if type(o) is not dict:
                        raise Bad("not an object")
                    canon = self.record(o, lineno)
                except Bad as e:
                    raise Bad(f"line {lineno}: {e}")
                if self.sink is not None:
                    self.sink.write(json.dumps(canon, separators=(",", ":"), ensure_ascii=False) + "\n")
            if lineno == 0 or self.lean is None:
                raise Bad("the export is empty or has no meta record")
        # `quot` declarations are built into the kernel; only Lean's own four may exist.
        for name, kind in self.quots:
            if QUOT_DECLS.get(name) != kind:
                raise Bad(f"declares `{name}` as a quot declaration ({kind}); only "
                          + ", ".join(QUOT_DECLS) + " may be")

    def record(self, o, lineno):
        """Validate one record; return its canonical form, built from validated fields only."""
        if "meta" in o:
            if lineno != 1:
                raise Bad("the meta record must be the first line, and only once")
            exact_keys(o, ["meta"], "the meta record")
            m = o["meta"]
            exact_keys(m, ["exporter", "format", "lean"], "the meta record")
            exact_keys(m["exporter"], ["name", "version"], "meta.exporter")
            exact_keys(m["format"], ["version"], "meta.format")
            exact_keys(m["lean"], ["githash", "version"], "meta.lean")
            vals = [m["exporter"]["name"], m["exporter"]["version"], m["format"]["version"],
                    m["lean"]["githash"], m["lean"]["version"]]
            if not all(plain_str(v) for v in vals):
                raise Bad("the meta record has a non-string value")
            if not m["format"]["version"].startswith("3."):
                raise Bad(f"export format {m['format']['version']} is not 3.x")
            self.lean = m["lean"]["version"]
            return {"meta": {"exporter": {"name": vals[0], "version": vals[1]},
                             "format": {"version": vals[2]},
                             "lean": {"githash": vals[3], "version": vals[4]}}}
        if lineno == 1:
            raise Bad("the meta record must be the first line")
        present = [k for k in (*RECORD_KINDS, *DECL_KINDS) if k in o]
        if len(present) > 1:
            raise Bad(f"a record must be of exactly one kind; this one has {sorted(o)[:6]}")
        if not present:
            raise Bad(f"unknown record with keys {sorted(o)[:6]}")
        kind = present[0]
        if kind in RECORD_KINDS:
            forms = [f for f in RECORD_KINDS[kind] if f in o]
            if len(forms) != 1:
                raise Bad(f"a `{kind}` record must have exactly one form; this one has {sorted(o)[:6]}")
            if set(o) != {kind, forms[0]}:
                raise Bad(f"a `{kind}` record has unexpected keys {sorted(set(o) - {kind, forms[0]})[:6]}")
            rid = o[kind]
            if not is_nat(rid):
                raise Bad(f"the id {rid!r} is not a natural number")
            if rid != self.next[kind]:
                raise Bad(f"`{kind}` id {rid} is out of sequence (expected {self.next[kind]})")
            self.next[kind] += 1
            return {kind: rid, **getattr(self, "rec_" + {"in": "name", "il": "level", "ie": "expr"}[kind])(rid, forms[0], o[forms[0]])}
        exact_keys(o, [kind], f"a `{kind}` record")
        return {kind: self.decl(kind, o[kind])}

    def rec_name(self, nid, form, v):
        if form == "str":
            exact_keys(v, ["pre", "str"], "a name")
            pre, s = v["pre"], v["str"]
            if not plain_str(s):
                raise Bad("a name component is not a string")
            parent = self.name(pre, use="bound")
            if s == MACRO_SCOPE or pre in self.scoped:
                self.scoped.add(nid)
            if s != MACRO_SCOPE and ("." in s or not NAME_SEGMENT.fullmatch(s)):
                raise Bad(f"the name component `{s[:80]}` is not allowed"
                          + (" (it contains a dot)" if "." in s else ""))
            self.raw_names[nid] = (pre, s)
            self.names[nid] = self.intern(("nstr", parent, s))
            return {"str": {"pre": pre, "str": s}}
        exact_keys(v, ["i", "pre"], "a name")
        pre, i = v["pre"], v["i"]
        if not is_nat(i):
            raise Bad("a numeric name component is not a natural number")
        parent = self.name(pre, use="bound")
        if pre in self.scoped:
            self.scoped.add(nid)
        self.raw_names[nid] = (pre, i)
        self.names[nid] = self.intern(("nnum", parent, i))
        return {"num": {"i": i, "pre": pre}}

    def rec_level(self, lid, form, v):
        if form == "succ":
            key, out = ("lsucc", self.level(v)), v
        elif form in ("max", "imax"):
            if type(v) is not list or len(v) != 2:
                raise Bad(f"`{form}` needs two levels")
            key, out = ("l" + form, self.level(v[0]), self.level(v[1])), [v[0], v[1]]
        else:
            key, out = ("lparam", self.name(v, use="bound")), v
        self.levels[lid] = self.intern(key)
        return {form: out}

    def rec_expr(self, eid, form, v):
        key, out = self.expr_key(form, v)
        self.exprs[eid] = self.intern(key)
        return {form: out}

    def expr_key(self, form, v):
        if form == "bvar":
            if not is_nat(v):
                raise Bad("a bound variable index is not a natural number")
            return ("bvar", v), v
        if form == "sort":
            return ("sort", self.level(v)), v
        if form == "const":
            exact_keys(v, ["name", "us"], "a constant")
            us = self.nat_list(v["us"], "a constant's universes")
            return (("const", self.name(v["name"], use="constant"), tuple(self.level(u) for u in us)),
                    {"name": v["name"], "us": list(us)})
        if form == "app":
            exact_keys(v, ["arg", "fn"], "an application")
            return ("app", self.expr(v["fn"]), self.expr(v["arg"])), {"arg": v["arg"], "fn": v["fn"]}
        if form in ("lam", "forallE"):
            exact_keys(v, ["binderInfo", "body", "name", "type"], f"a `{form}`")
            if v["binderInfo"] not in BINDER_INFOS:
                raise Bad(f"unknown binder annotation {str(v['binderInfo'])[:40]!r}")
            # Binder names and annotations are ignored, as the kernel ignores
            # them: terms are compared up to renaming of bound variables.
            self.name(v["name"], use="bound")
            return ((form, self.expr(v["type"]), self.expr(v["body"])),
                    {"binderInfo": v["binderInfo"], "body": v["body"], "name": v["name"], "type": v["type"]})
        if form == "letE":
            exact_keys(v, ["body", "name", "nondep", "type", "value"], "a `letE`")
            if type(v["nondep"]) is not bool:
                raise Bad("`nondep` is not a boolean")
            self.name(v["name"], use="bound")
            return (("letE", self.expr(v["type"]), self.expr(v["value"]), self.expr(v["body"]), v["nondep"]),
                    {"body": v["body"], "name": v["name"], "nondep": v["nondep"], "type": v["type"], "value": v["value"]})
        if form == "natVal":
            if type(v) is not str or len(v) > MAX_NAT_DIGITS or not re.fullmatch(r"0|[1-9][0-9]*", v):
                raise Bad("a natural number literal is not in canonical decimal form")
            return ("nat", v), v
        if form == "strVal":
            if not plain_str(v):
                raise Bad("a string literal is not a string")
            return ("str", v), v
        if form == "proj":
            exact_keys(v, ["idx", "struct", "typeName"], "a projection")
            if not is_nat(v["idx"]):
                raise Bad("a projection index is not a natural number")
            return (("proj", self.name(v["typeName"], use="structure name"), v["idx"], self.expr(v["struct"])),
                    {"idx": v["idx"], "struct": v["struct"], "typeName": v["typeName"]})
        raise Bad("`mdata` is not accepted")

    # ---- declarations
    def add_decl(self, name_id):
        canon = self.name(name_id, use="declaration name")
        dotted = self.name_str(name_id)
        if canon in self.decls or dotted in self.by_string:
            raise Bad(f"`{dotted}` is declared twice")
        self.by_string[dotted] = canon
        self.decl_names[canon] = dotted
        return canon

    def name_list(self, v, what, use="name"):
        v = self.nat_list(v, what)
        return [self.name(n, use=use) for n in v] and list(v)

    def bool_field(self, d, k):
        if type(d[k]) is not bool:
            raise Bad(f"`{k}` is not a boolean")
        return d[k]

    def nat_field(self, d, k):
        if not is_nat(d[k]):
            raise Bad(f"`{k}` is not a natural number")
        return d[k]

    def decl(self, kind, d):
        if kind == "inductive":
            return self.inductive(d)
        fields = {"thm": ["all", "levelParams", "name", "type", "value"],
                  "def": ["all", "hints", "levelParams", "name", "safety", "type", "value"],
                  "axiom": ["isUnsafe", "levelParams", "name", "type"],
                  "opaque": ["all", "isUnsafe", "levelParams", "name", "type", "value"],
                  "quot": ["kind", "levelParams", "name", "type"]}[kind]
        exact_keys(d, fields, f"a `{kind}` declaration")
        lps = self.name_list(d["levelParams"], "levelParams", use="bound")
        out = {"levelParams": lps, "name": d["name"], "type": d["type"]}
        key = [kind, tuple(self.names[n] for n in lps), self.expr(d["type"])]
        if "all" in d:
            out["all"] = self.name_list(d["all"], "`all`", use="declaration name")
        if "value" in d:
            out["value"] = d["value"]
            key.append(self.expr(d["value"]))
        if kind == "def":
            h = d["hints"]
            if h in ("abbrev", "opaque"):
                hint_key = h
            elif type(h) is dict and set(h) == {"regular"} and is_nat(h["regular"]):
                hint_key, h = ("regular", h["regular"]), {"regular": h["regular"]}
            else:
                raise Bad("unknown reducibility hints")
            if d["safety"] not in SAFETIES:
                raise Bad("unknown definition safety")
            if d["safety"] != "safe":
                raise Bad(f"the definition `{self.name_str(d['name'])}` is {d['safety']}, not safe")
            out["hints"], out["safety"] = h, d["safety"]
            key += [hint_key, d["safety"]]
        if kind in ("axiom", "opaque"):
            if self.bool_field(d, "isUnsafe"):
                raise Bad(f"the {kind} `{self.name_str(d['name'])}` is unsafe")
            out["isUnsafe"] = False
            key.append(False)
        if kind == "quot":
            if d["kind"] not in ("type", "ctor", "lift", "ind"):
                raise Bad("unknown quot kind")
            out["kind"] = d["kind"]
            key.append(d["kind"])
            self.quots.append((self.name_str(d["name"]), d["kind"]))
        canon = self.add_decl(d["name"])
        self.decls[canon] = tuple(key)
        return out

    def inductive(self, d):
        exact_keys(d, ["ctors", "recs", "types"], "an inductive declaration")
        parts = {"types": ["all", "ctors", "isRec", "isReflexive", "isUnsafe", "levelParams", "name",
                           "numIndices", "numNested", "numParams", "type"],
                 "ctors": ["cidx", "induct", "isUnsafe", "levelParams", "name", "numFields", "numParams", "type"],
                 "recs": ["all", "isUnsafe", "k", "levelParams", "name", "numIndices", "numMinors",
                          "numMotives", "numParams", "rules", "type"]}
        out, key = {}, []
        for part, fields in parts.items():
            out[part] = []
            for item in self.nat_list(d[part], part):
                exact_keys(item, fields, f"an inductive's {part[:-1]}")
                o = {}
                for f in fields:
                    v = item[f]
                    if f in ("isRec", "isReflexive", "isUnsafe", "k"):
                        o[f] = self.bool_field(item, f)
                    elif f.startswith("num") or f == "cidx":
                        o[f] = self.nat_field(item, f)
                    elif f == "levelParams":
                        o[f] = self.name_list(v, f, use="bound")
                    elif f in ("all", "ctors"):
                        o[f] = self.name_list(v, f, use="declaration name")
                    elif f in ("name", "induct"):
                        self.name(v, use="declaration name")
                        o[f] = v
                    elif f == "type":
                        self.expr(v)
                        o[f] = v
                    elif f == "rules":
                        o[f] = []
                        for r in self.nat_list(v, "rules"):
                            exact_keys(r, ["ctor", "nfields", "rhs"], "a recursor rule")
                            self.name(r["ctor"], use="declaration name")
                            self.nat_field(r, "nfields")
                            self.expr(r["rhs"])
                            o[f].append({"ctor": r["ctor"], "nfields": r["nfields"], "rhs": r["rhs"]})
                if o["isUnsafe"]:
                    raise Bad(f"the inductive {part[:-1]} `{self.name_str(o['name'])}` is unsafe")
                out[part].append(o)
        if not (out["types"] or out["ctors"] or out["recs"]):
            raise Bad("empty inductive record")
        # One record holds the types, constructors and recursors of a mutual
        # block; each gets its own entry, keyed by everything in the block.
        whole = self.intern(("inductive", json.dumps(self.canon_json(out), sort_keys=True)))
        for part, tag in (("types", "inductive-type"), ("ctors", "inductive-ctor"), ("recs", "inductive-rec")):
            for item in out[part]:
                self.decls[self.add_decl(item["name"])] = (tag, whole)
        return out

    def canon_json(self, v, field=None):
        """Replace export ids inside an inductive record by canonical ids."""
        if isinstance(v, dict):
            return {k: self.canon_json(x, k) for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [self.canon_json(x, field) for x in v]
        if type(v) is int:
            if field in ("name", "induct", "ctor", "all", "levelParams", "ctors"):
                return ["n", self.names[v]]
            if field in ("type", "rhs"):
                return ["e", self.exprs[v]]
        return v


def name_id(table, dotted):
    """Canonical id of a dotted name, built component by component from a fixed string."""
    cur = ANON
    for part in dotted.split("."):
        cur = table.get(("nstr", cur, part))
        if cur is None:
            return None
    return cur


class MergedReference:
    """Several reference exports seen as one: their declarations, by canonical name id."""

    def __init__(self, exports):
        self.lean = exports[0].lean
        self.decls, self.decl_names = {}, {}
        for e in exports:
            if e.lean != self.lean:
                raise Bad("the reference exports were made by different Lean versions")
            for nid, key in e.decls.items():
                if nid in self.decls and self.decls[nid] != key:
                    raise Bad(f"the references disagree on `{e.decl_names[nid]}`")
                self.decls[nid], self.decl_names[nid] = key, e.decl_names[nid]


def required_type(kind, ident):
    stmt = f"QPCP.Statement.{ident}" if ident.startswith("S") else f"QPCP.Lemma.{ident}"
    if kind == "lemma":
        return f"QPCP.Lemma.{ident}", "def", stmt
    return (f"QPCP.Proof.{ident}" if kind == "proof" else f"QPCP.Refutation.{ident}"), "thm", stmt


def verify(kind, ident, untrusted_path, reference_path, names_path=None):
    table = {}
    ref = MergedReference([Export(p, table) for p in reference_path.split(",") if p])
    unt = Export(untrusted_path, table)
    if ref.lean is None or unt.lean != ref.lean:
        raise Bad(f"export was made by Lean {unt.lean}, expected {ref.lean}")
    requested = list(ALWAYS_REQUIRED)
    if names_path:
        requested += [line.strip() for line in open(names_path, encoding="utf-8") if line.strip()]
    for n in requested:
        nid = name_id(table, n)
        if nid is None or nid not in ref.decls:
            raise Bad(f"main has no `{n}` (the reference export is incomplete)")

    for nid, key in ref.decls.items():
        name = ref.decl_names[nid]
        if nid not in unt.decls:
            raise Bad(f"`{name}` from main is missing")
        if unt.decl_names[nid] != name or unt.by_string.get(name) != nid:
            raise Bad(f"`{name}` is not named as on main")
        if unt.decls[nid] != key:
            raise Bad(f"`{name}` differs from main's")

    allowed = {name_id(table, a) for a in ALLOWED_AXIOMS}
    for nid, key in unt.decls.items():
        if key[0] == "axiom" and nid not in allowed:
            raise Bad(f"declares the axiom `{unt.decl_names[nid]}`")

    target, want_kind, stmt = required_type(kind, ident)
    tid = name_id(table, target)
    if tid is None or tid not in unt.decls:
        raise Bad(f"`{target}` is missing")
    got = unt.decls[tid]
    if got[0] != want_kind or got[1] != ():
        raise Bad(f"`{target}` is not a {'definition' if want_kind == 'def' else 'theorem'} without universe parameters")
    if kind == "lemma":
        want_type = table.get(("sort", LZERO))
    else:
        sid = name_id(table, stmt)
        if sid is None or sid not in ref.decls:
            raise Bad(f"the reference does not contain `{stmt}`")
        c = table.get(("const", sid, ()))
        if kind == "proof":
            want_type = c
        else:
            not_c = table.get(("const", name_id(table, "Not"), ()))
            want_type = table.get(("app", not_c, c)) if not_c is not None and c is not None else None
    if want_type is None or got[2] != want_type:
        raise Bad(f"`{target}` does not have exactly the required type")


def lemma_deps(ident, untrusted_path):
    """Names outside the lemma that QPCP.Lemma.<ident> refers to, directly or
    through constants of its own (QPCP.Lemma.<ident>.*)."""
    table = {}
    unt = Export(untrusted_path, table)
    inv = {i: k for k, i in table.items()}
    strings = {}
    for nid in unt.raw_names:
        if nid:
            strings.setdefault(unt.names[nid], unt.name_str(nid))
    own = f"QPCP.Lemma.{ident}"
    mine = lambda n: n == own or n.startswith(own + ".")
    own_id = name_id(table, own)
    if own_id is None or own_id not in unt.decls:
        raise Bad(f"`{own}` is missing")
    out, seen_decls, todo = set(), set(), [own_id]
    while todo:
        d = todo.pop()
        if d in seen_decls:
            continue
        seen_decls.add(d)
        key = unt.decls[d]
        if key[0] not in ("def", "thm", "opaque"):
            raise Bad(f"`{unt.decl_names[d]}` is not a definition or theorem")
        stack, seen = [key[2], key[3]], set()  # type and value
        while stack:
            c = stack.pop()
            if not isinstance(c, int) or c in seen or c not in inv:
                continue
            seen.add(c)
            k = inv[c]
            if k[0] == "const":
                n = strings.get(k[1])
                if n is None:
                    raise Bad("a constant has no name")
                if mine(n):
                    if k[1] not in unt.decls:
                        raise Bad(f"`{n}` is used but not declared")
                    todo.append(k[1])
                else:
                    out.add(n)
            elif k[0] in ("app", "lam", "forallE"):
                stack.extend((k[1], k[2]))
            elif k[0] == "letE":
                stack.extend((k[1], k[2], k[3]))
            elif k[0] == "proj":
                stack.append(k[3])
    for n in out:
        if not all(NAME_SEGMENT.fullmatch(s) for s in n.split(".")):
            raise Bad(f"refers to `{n}`, a name this checker does not accept")
    return sorted(out)


def canonicalize(untrusted_path, out_path):
    with open(out_path, "w", encoding="utf-8") as sink:
        Export(untrusted_path, {}, sink=sink)


def main(argv):
    try:
        if len(argv) == 4 and argv[1] == "canon":
            canonicalize(argv[2], argv[3])
            print("CANONICAL")
            return 0
        if len(argv) == 4 and argv[1] == "deps":
            print("\n".join(lemma_deps(argv[2], argv[3])))
            return 0
        if len(argv) not in (5, 6) or argv[1] not in ("proof", "refutation", "lemma"):
            print(__doc__)
            return 2
        verify(argv[1], argv[2], argv[3], argv[4], argv[5] if len(argv) == 6 else None)
    except Bad as e:
        print(f"REJECTED: {e}")
        return 1
    except UnicodeDecodeError:
        print("REJECTED: the export is not valid UTF-8")
        return 1
    except (OSError, RecursionError, MemoryError) as e:
        print(f"REJECTED: cannot read the export ({type(e).__name__})")
        return 1
    print(f"ACCEPTED: {argv[1]} {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
