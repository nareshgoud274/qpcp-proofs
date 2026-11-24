#!/usr/bin/env python3
"""Write forged copies of an honest export, each of which must be REJECTED.

    forge_exports.py <kind> <ident> <honest.ndjson> <reference.ndjson>[,<more>...] <out-dir>

<kind> is proof, refutation or lemma; the honest export and the reference are
the ones scripts/contribution_check.sh produced for that contribution. The
reference is read only to choose real dependencies of the statement to tamper
with. Each forgery models an attacker who controls the export the sandbox
hands back. Prints the names of the files written.
"""

import json
import sys
from pathlib import Path

DECL_KINDS = ("thm", "def", "axiom", "opaque", "quot")


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def dump(rows, path):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")


def names(rows):
    """Export name id -> dotted string."""
    out = {0: ""}
    for r in rows:
        if "in" in r:
            pre, val = (r["str"]["pre"], r["str"]["str"]) if "str" in r else (r["num"]["pre"], r["num"]["i"])
            out[r["in"]] = (out[pre] + "." if out[pre] else "") + str(val)
    return out


def decls(rows, nm):
    """Dotted name -> (row index, kind) for every plain declaration; inductive type names too."""
    out = {}
    for i, r in enumerate(rows):
        for k in DECL_KINDS:
            if k in r:
                out[nm[r[k]["name"]]] = (i, k)
        if "inductive" in r:
            for t in r["inductive"].get("types", []):
                out[nm[t["name"]]] = (i, "inductive")
    return out


def pick(candidates, preferred):
    for p in preferred:
        if p in candidates:
            return p
    if not candidates:
        raise SystemExit("no candidate declaration to tamper with")
    return sorted(candidates)[0]


def earlier_expr(rows, i, avoid):
    """An expression id defined before row i, other than `avoid`."""
    for r in rows[:i]:
        if "ie" in r and r["ie"] != avoid:
            return r["ie"]
    raise SystemExit("no earlier expression")


def copy(rows):
    return [json.loads(json.dumps(r)) for r in rows]


def forge(kind, ident, honest, reference, out):
    rows = load(honest)
    nm = names(rows)
    have, ref_have = decls(rows, nm), {}
    for ref_path in [r for r in reference.split(",") if r]:   # several references allowed
        ref_rows = load(ref_path)
        ref_have.update(decls(ref_rows, names(ref_rows)))
    out.mkdir(parents=True, exist_ok=True)
    max_n = max(r["in"] for r in rows if "in" in r)
    stmt = f"QPCP.Statement.{ident}" if ident.startswith("S") else f"QPCP.Lemma.{ident}"
    target = {"proof": f"QPCP.Proof.{ident}", "refutation": f"QPCP.Refutation.{ident}",
              "lemma": f"QPCP.Lemma.{ident}"}[kind]
    written = []

    def emit(name, f):
        dump(f, out / f"{name}.ndjson")
        written.append(name)

    def change_value(f, decl_name):
        i, k = decls(f, nm)[decl_name]
        f[i][k]["value"] = earlier_expr(f, i, f[i][k]["value"])

    # Dependencies of the statement on main, as the reference has them.
    ref_defs = {n for n, (_, k) in ref_have.items() if k == "def" and n in have and have[n][1] == "def"}
    qpcp_dep = pick({n for n in ref_defs if n.startswith("QPCP.") and n != stmt},
                    ["QPCP.groundEnergy", "QPCP.energy", "QPCP.ActsOn", "QPCP.IsState"])
    core_dep = pick({n for n in ref_defs if not n.startswith("QPCP.")},
                    ["Matrix.mulVec", "dotProduct", "Finset.sum", "Matrix.diagonal", "Function.comp"])
    ind_dep = pick({n for n, (_, k) in ref_have.items() if k == "inductive" and n in have},
                   ["Fin", "Subtype", "Prod", "Nat"])

    # 1. A QPCP definition the statement depends on is changed.
    f = copy(rows); change_value(f, qpcp_dep); emit(f"dep_qpcp_def_changed__{qpcp_dep}", f)

    # 2. A Mathlib or core definition the statement depends on is changed.
    f = copy(rows); change_value(f, core_dep); emit(f"dep_core_def_changed__{core_dep}", f)

    # 3. An inductive type the statement depends on gets an extra constructor.
    f = copy(rows)
    i, _ = decls(f, nm)[ind_dep]
    ind = f[i]["inductive"]
    tdef = next(t for t in ind["types"] if nm[t["name"]] == ind_dep)
    model = next(c for c in ind["ctors"] if c["induct"] == tdef["name"])
    f.insert(i, {"in": max_n + 1, "str": {"pre": tdef["name"], "str": "forged"}})
    extra = dict(model, name=max_n + 1, cidx=len(tdef["ctors"]))
    ind["ctors"].append(extra)
    tdef["ctors"].append(max_n + 1)
    emit(f"dep_inductive_extra_ctor__{ind_dep}", f)

    # 4. The statement itself is redefined as `True` (proofs and refutations;
    #    a lemma's own definition is the contribution, not something on main).
    if kind != "lemma":
        f = copy(rows)
        true_c = next(r["ie"] for r in f if "const" in r and nm.get(r["const"]["name"]) == "True")
        i, k = decls(f, nm)[stmt]
        if true_c < max(r["ie"] for r in f[:i] if "ie" in r):
            f[i][k]["value"] = true_c
        else:
            f[i][k]["value"] = earlier_expr(f, i, f[i][k]["value"])
        emit("statement_is_True", f)

    # 5. `propext` keeps its name but gets another type.
    f = copy(rows)
    i, k = decls(f, nm)["propext"]
    f[i][k]["type"] = earlier_expr(f, i, f[i][k]["type"])
    emit("propext_retyped", f)

    # 6. The contribution's type is replaced by another expression.
    f = copy(rows)
    i, k = decls(f, nm)[target]
    f[i][k]["type"] = earlier_expr(f, i, f[i][k]["type"])
    emit("wrong_type", f)

    # 7. An extra axiom, `<target>.cheat`, typed by an expression defined earlier.
    f = copy(rows)
    tid = next(r["in"] for r in rows if "in" in r and nm[r["in"]] == target)
    f.append({"in": max_n + 1, "str": {"pre": tid, "str": "cheat"}})
    f.append({"axiom": {"isUnsafe": False, "levelParams": [], "name": max_n + 1,
                        "type": next(r["ie"] for r in rows if "ie" in r)}})
    emit("extra_axiom", f)

    # 8. A second declaration of the contribution's name.
    f = copy(rows)
    i, _ = decls(f, nm)[target]
    f.append(json.loads(json.dumps(f[i])))
    emit("duplicate_name", f)

    # 9. The contribution is missing.
    f = copy(rows)
    i, _ = decls(f, nm)[target]
    del f[i]
    emit("missing", f)

    # 10. An expression id is used before it is defined.
    f = copy(rows)
    i, k = decls(f, nm)[target]
    f[i][k]["type"] = max(r["ie"] for r in rows if "ie" in r) + 10
    emit("dangling_id", f)

    # 11. Not JSON at all.
    (out / "not_json.ndjson").write_text("this is not an export\n")
    written.append("not_json")
    return written


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] not in ("proof", "refutation", "lemma"):
        print(__doc__)
        sys.exit(2)
    for name in forge(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])):
        print(name)
