#!/usr/bin/env python3
"""Write forged copies of an honest export, each of which must be REJECTED.

    forge_exports.py <kind> <ident> <honest.ndjson> <reference.ndjson>[,<more>...] <out-dir>

<kind> is proof, refutation or lemma; the honest export and the reference are
the ones scripts/contribution_check.sh produced for that contribution. The
reference is read only to choose real dependencies of the statement to tamper
with. Each forgery models an attacker who controls the export the sandbox
hands back. Prints one line per file written: its name, a tab, and a part of
the reason verify_export.py must give when it rejects it (empty: any reason).
Each of the newer forgeries inserts exactly one defect into the honest
export, so the expected reason shows which check caught it.
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
    max_e = max(r["ie"] for r in rows if "ie" in r)

    def emit(name, f, expect=""):
        dump(f, out / f"{name}.ndjson")
        written.append((name, expect))

    def emit_text(name, lines, expect):
        (out / f"{name}.ndjson").write_text("".join(l + "\n" for l in lines), encoding="utf-8", errors="surrogatepass")
        written.append((name, expect))

    text = [json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in rows]
    app_i = next(i for i, r in enumerate(rows) if "app" in r)
    const_i = next(i for i, r in enumerate(rows) if "const" in r)
    lam_i = next(i for i, r in enumerate(rows) if "lam" in r)
    app = rows[app_i]

    def with_line(i, line):
        return text[:i] + [line] + text[i + 1:]

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
    f = copy(rows); change_value(f, qpcp_dep); emit(f"dep_qpcp_def_changed__{qpcp_dep}", f, "differs from main's")

    # 2. A Mathlib or core definition the statement depends on is changed.
    f = copy(rows); change_value(f, core_dep); emit(f"dep_core_def_changed__{core_dep}", f, "differs from main's")

    # 3. An inductive type the statement depends on gets an extra constructor.
    f = copy(rows)
    i, _ = decls(f, nm)[ind_dep]
    ind = f[i]["inductive"]
    tdef = next(t for t in ind["types"] if nm[t["name"]] == ind_dep)
    model = next(c for c in ind["ctors"] if c["induct"] == tdef["name"])
    # The new constructor's name must be defined before the record and ids stay
    # in sequence, so the record moves to the end, after one more name.
    del f[i]
    f.append({"in": max_n + 1, "str": {"pre": tdef["name"], "str": "forged"}})
    extra = dict(model, name=max_n + 1, cidx=len(tdef["ctors"]))
    ind["ctors"].append(extra)
    tdef["ctors"].append(max_n + 1)
    f.append({"inductive": ind})
    emit(f"dep_inductive_extra_ctor__{ind_dep}", f, "differs from main's")

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
        emit("statement_is_True", f, "differs from main's")

    # 5. `propext` keeps its name but gets another type.
    f = copy(rows)
    i, k = decls(f, nm)["propext"]
    f[i][k]["type"] = earlier_expr(f, i, f[i][k]["type"])
    emit("propext_retyped", f, "`propext` differs from main's")

    # 6. The contribution's type is replaced by another expression.
    f = copy(rows)
    i, k = decls(f, nm)[target]
    f[i][k]["type"] = earlier_expr(f, i, f[i][k]["type"])
    emit("wrong_type", f, "does not have exactly the required type")

    # 7. An extra axiom, `<target>.cheat`, typed by an expression defined earlier.
    f = copy(rows)
    tid = next(r["in"] for r in rows if "in" in r and nm[r["in"]] == target)
    f.append({"in": max_n + 1, "str": {"pre": tid, "str": "cheat"}})
    f.append({"axiom": {"isUnsafe": False, "levelParams": [], "name": max_n + 1,
                        "type": next(r["ie"] for r in rows if "ie" in r)}})
    emit("extra_axiom", f, "declares the axiom")

    # 8. A second declaration of the contribution's name.
    f = copy(rows)
    i, _ = decls(f, nm)[target]
    f.append(json.loads(json.dumps(f[i])))
    emit("duplicate_name", f, "declared twice")

    # 9. The contribution is missing.
    f = copy(rows)
    i, _ = decls(f, nm)[target]
    del f[i]
    emit("missing", f, "is missing")

    # 10. An expression id is used before it is defined.
    f = copy(rows)
    i, k = decls(f, nm)[target]
    f[i][k]["type"] = max(r["ie"] for r in rows if "ie" in r) + 10
    emit("dangling_id", f, "used before it is defined")

    # 11. Not JSON at all.
    (out / "not_json.ndjson").write_text("this is not an export\n")
    written.append(("not_json", "not JSON"))

    # ---- Malformed lines (strict reading).
    e = app["ie"]
    body = json.dumps(app["app"], separators=(",", ":"))
    emit_text("malformed_duplicate_key", with_line(app_i, f'{{"app":{body},"ie":{e},"ie":{e}}}'), "duplicate key")
    emit_text("malformed_nan_id", with_line(app_i, f'{{"app":{body},"ie":NaN}}'), "`NaN` is not allowed")
    emit_text("malformed_infinity_id", with_line(app_i, f'{{"app":{body},"ie":Infinity}}'), "`Infinity` is not allowed")
    emit_text("malformed_float_id", with_line(app_i, f'{{"app":{body},"ie":{e}.0}}'), "is not an integer")
    emit_text("malformed_string_id", with_line(app_i, f'{{"app":{body},"ie":"{e}"}}'), "is not a natural number")
    emit_text("malformed_bool_arg", with_line(app_i, f'{{"app":{{"arg":true,"fn":{app["app"]["fn"]}}},"ie":{e}}}'),
              "is not a natural number")
    emit_text("malformed_negative_arg", with_line(app_i, f'{{"app":{{"arg":-1,"fn":{app["app"]["fn"]}}},"ie":{e}}}'),
              "is not a natural number")
    emit_text("malformed_unknown_top_key", with_line(app_i, f'{{"app":{body},"ie":{e},"extra":0}}'), "unexpected keys")
    emit_text("malformed_unknown_nested_key",
              with_line(app_i, f'{{"app":{{"arg":{app["app"]["arg"]},"fn":{app["app"]["fn"]},"extra":0}},"ie":{e}}}'),
              "unexpected keys")
    lam = json.dumps(rows[lam_i]["lam"], separators=(",", ":"))
    emit_text("malformed_two_forms", with_line(app_i, f'{{"app":{body},"lam":{lam},"ie":{e}}}'), "exactly one form")
    thm_line = next(t for t, r in zip(text, rows) if "thm" in r)
    emit_text("malformed_two_kinds", with_line(app_i, thm_line[:-1] + f',"ie":{e}}}'), "exactly one kind")
    emit_text("malformed_unknown_record", text + ['{"zzz":1}'], "unknown record")
    emit_text("malformed_meta_twice", text + [text[0]], "meta record must be the first line")
    emit_text("malformed_no_meta", text[1:], "meta record must be the first line")
    emit_text("malformed_id_out_of_sequence", text[:app_i + 1] + [text[app_i]] + text[app_i + 1:], "out of sequence")
    emit_text("malformed_mdata", with_line(app_i, f'{{"ie":{e},"mdata":{{"data":{{}},"expr":{app["app"]["fn"]}}}}}'),
              "`mdata` is not accepted")
    lam_e = rows[lam_i]
    emit_text("malformed_binder_info",
              with_line(lam_i, json.dumps({"ie": lam_e["ie"], "lam": dict(lam_e["lam"], binderInfo="sneaky")},
                                          separators=(",", ":"))), "unknown binder annotation")
    emit_text("malformed_lone_surrogate", text + [f'{{"in":{max_n + 1},"str":{{"pre":0,"str":"\\ud800"}}}}'],
              "is not a string")

    # ---- Names (canonical name ids; no dots, NAME_SEGMENT).
    tid = next(r["in"] for r in rows if "in" in r and nm[r["in"]] == target)
    t_i, t_k = decls(rows, nm)[target]
    trow = rows[t_i][t_k]

    def append_name(f, s, pre=0):
        nid = max(r["in"] for r in f if "in" in r) + 1
        f.append({"in": nid, "str": {"pre": pre, "str": s}})
        return nid

    f = copy(rows)
    n1 = append_name(f, target)  # one component, spelled with dots
    f.append({t_k: dict(trow, name=n1)})
    emit("name_component_with_dots", f, "contains a dot")
    f = copy(rows)
    append_name(f, "two words")
    emit("name_component_bad_segment", f, "is not allowed")
    f = copy(rows)
    scoped = append_name(f, "_@", pre=tid)
    f.append({t_k: dict(trow, name=scoped)})
    emit("macro_scoped_declaration_name", f, "macro-scoped name")
    f = copy(rows)
    scoped = append_name(f, "_@", pre=tid)
    f.append({"ie": max_e + 1, "const": {"name": scoped, "us": []}})
    emit("macro_scoped_constant", f, "macro-scoped name")

    # ---- Safety and quot declarations.
    def_row = next(r for r in rows if "def" in r)
    for safety in ("unsafe", "partial"):
        f = copy(rows)
        n = append_name(f, f"forged_{safety}", pre=tid)
        f.append({"def": dict(def_row["def"], name=n, all=[n], safety=safety)})
        emit(f"definition_{safety}", f, f"is {safety}, not safe")
    f = copy(rows)
    i, k = decls(f, nm)["propext"]
    f[i][k]["isUnsafe"] = True
    emit("axiom_unsafe", f, "the axiom `propext` is unsafe")
    f = copy(rows)
    n = append_name(f, "forged_opaque", pre=tid)
    f.append({"opaque": {"all": [n], "isUnsafe": True, "levelParams": [], "name": n,
                         "type": trow["type"], "value": trow["value"]}})
    emit("opaque_unsafe", f, "is unsafe")
    f = copy(rows)
    i, _ = decls(f, nm)[ind_dep]
    f[i]["inductive"]["types"][0]["isUnsafe"] = True
    emit(f"inductive_unsafe__{ind_dep}", f, "is unsafe")
    f = copy(rows)
    n = append_name(f, "forged_quot", pre=tid)
    quot = next(r for r in rows if "quot" in r)
    f.append({"quot": dict(quot["quot"], name=n)})
    emit("extra_quot_declaration", f, "as a quot declaration")
    return written


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] not in ("proof", "refutation", "lemma"):
        print(__doc__)
        sys.exit(2)
    for name, expect in forge(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5])):
        print(f"{name}\t{expect}")
