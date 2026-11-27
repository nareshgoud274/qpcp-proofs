#!/usr/bin/env python3
"""The verification record of one commit of main (#113).

    verification_record.py evidence <work-dir> <out.json>
        In the verify-main job (read-only token), after
        `sandbox_verify.py record` succeeded: turns the verifier's
        result/record-items.json into the evidence artifact, adding for each
        item the project definitions its statement depends on (read from the
        trusted reference exports, which only maintainer-written modules made).

    verification_record.py build --evidence-dir <dir> --sha <commit> --repo <checkout>
                                 --run-url <url> --attempt <n> --out <record.json>
        In the publish job (write token, runs no contributed code and no Lean):
        validates the evidence strictly and builds the record. The commit, the
        toolchain, the Mathlib revision, every path and Git blob id are taken
        from Git at <commit>, not from the artifact; from the artifact come only
        the verdicts, declarations, statement digests and dependencies. Refuses
        a partial run (--only, a missing shard, replay-only), a missing or extra
        contribution, a blob that differs from the tree, or any verdict other
        than ACCEPTED. When a statement is one name (S057-S059), the record's
        `display.statementDefinitions` gives that definition's source and
        lines, from a maintainer-written module (QPCP/*.lean) at <commit>.
        `display` is not evidence: two runs on one commit may locate a
        definition differently, and that is never a different result.

A record is evidence about one commit. Its `evidence` part (everything except
the run, the attempt and the time) must be identical on every run for that
commit; scripts/site_data.py refuses to publish a second record that differs.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 1
KINDS = {"proof": "QPCP/Proofs", "refutation": "QPCP/Refutations", "lemma": "QPCP/Lemmas"}
DECL_NS = {"proof": "QPCP.Proof", "refutation": "QPCP.Refutation", "lemma": "QPCP.Lemma"}
ID_RE = re.compile(r"^(S\d{3,6}|L\d{1,9})$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Auxiliary names Lean generates (match_1, proof_2, _private ...), left out of "depends on".
AUX = re.compile(r"(^_|_\d+$|^match_|^proof_|^eq_\d+$)")
DECL_LINES = ('{"def"', '{"inductive"', '{"opaque"')


class Fault(Exception):
    pass


# ------------------------------------------------------------------ evidence

def project_definitions(ref_paths, own):
    """QPCP.* definitions and inductive types declared in the reference exports."""
    found = set()
    for path in ref_paths:
        names = {0: None}
        decls = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith('{"in"'):
                    o = json.loads(line)
                    v = o.get("str") or o.get("num")
                    names[o["in"]] = (v["pre"], v.get("str", v.get("i")))
                elif line.startswith(DECL_LINES):
                    o = json.loads(line)
                    kind = next(iter(o))
                    d = o[kind]
                    decls += [t["name"] for t in d.get("types", [])] if kind == "inductive" else [d["name"]]

        def dotted(n):
            parts = []
            while n:
                pre, comp = names[n]
                parts.append(str(comp))
                n = pre
            return ".".join(reversed(parts))
        for n in decls:
            s = dotted(n)
            if s.startswith("QPCP.") and s != own and not any(AUX.search(p) for p in s.split(".")):
                found.add(s)
    return sorted(found)


def statement_constant(kind, ident):
    if kind == "lemma" or ident.startswith("L"):
        return f"QPCP.Lemma.{ident}"
    return f"QPCP.Statement.{ident}"


def statement_digest(refs):
    """One SHA-256 over the reference exports a result was judged against, in order."""
    return hashlib.sha256("\n".join(r["sha256"] for r in refs).encode()).hexdigest()


def cmd_evidence(work, out):
    data = json.loads((Path(work) / "result" / "record-items.json").read_text())
    items = []
    for it in data["items"]:
        refs = it["references"]
        items.append({
            "kind": it["kind"], "id": it["id"], "declaration": it["declaration"], "path": it["path"],
            "blob": it["blob"], "verdict": it["verdict"],
            "statementDigest": statement_digest(refs) if refs else "",
            "dependsOn": project_definitions([r["path"] for r in refs], statement_constant(it["kind"], it["id"])),
            "statementDefinition": it.get("statementDefinition"),
        })
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({"format": FORMAT, "only": data["only"], "shard": data["shard"],
                                     "replayOnly": data["replayOnly"], "locatedByLean": bool(data.get("locatedByLean")),
                                     "items": items}, indent=1))
    print(f"evidence: {len(items)} items, {sum(i['verdict'] == 'ACCEPTED' for i in items)} accepted")


# ------------------------------------------------------------------ build

def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise Fault(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def tree_contributions(repo, sha):
    """{path: blob} for every Lean file under the contribution folders at <sha>
    (other files there, such as README.md or .gitkeep, are not contributions)."""
    out = {}
    for line in git(repo, "ls-tree", "-r", sha, "--", *KINDS.values()).splitlines():
        meta, path = line.split("\t", 1)
        if not path.endswith(".lean"):
            continue
        mode, typ, blob = meta.split()
        if mode != "100644" or typ != "blob":
            raise Fault(f"{path} at {sha[:7]} is not a regular file (mode {mode})")
        out[path] = blob
    return out


def statement_location(repo, sha, kind, ident):
    """Where the statement a result is judged against is written, at <sha>."""
    if ident.startswith("S"):
        path = "QPCP/Statements.lean"
        pattern = re.compile(rf"^def {ident}\b")
    else:
        path = f"QPCP/Lemmas/{ident}.lean"
        pattern = re.compile(rf"^def {ident}\b")
    # Comments are blanked first, so a commented-out `def` is never taken for the statement.
    code = strip_comments(git(repo, "show", f"{sha}:{path}")).split("\n")
    found = [n for n, line in enumerate(code, 1) if pattern.match(line)]
    if len(found) != 1:
        raise Fault(f"{len(found)} declarations `def {ident}` in {path} at {sha[:7]}; expected exactly one")
    return path, found[0]


ONE_NAME = re.compile(r"^def\s+[SL]\d+\s*:\s*Prop\s*:=\s*([A-Za-z_][\w.']*)\s*$")
DECL_RE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:noncomputable|private|protected)\s+)*"
                     r"(?:def|abbrev|structure|inductive|class)\s+([A-Za-z_][\w.']*)")
LEAN_LOC_KEYS = {"name", "module", "line", "endLine"}


def strip_comments(text):
    """`text` with every comment and string literal blanked out: line comments,
    nested block comments (doc comments included) and "..." strings. Every
    newline and column stays where it was, so line numbers still refer to the
    original. Used so that nothing inside a comment is ever read as code."""
    out, i, n, depth = [], 0, len(text), 0
    blank = lambda chunk: "".join("\n" if ch == "\n" else " " for ch in chunk)
    while i < n:
        if depth:
            if text.startswith("/-", i):
                depth, step = depth + 1, 2
            elif text.startswith("-/", i):
                depth, step = depth - 1, 2
            else:
                step = 1
            out.append(blank(text[i:i + step]))
            i += step
        elif text.startswith("/-", i):
            depth = 1
            out.append("  ")
            i += 2
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(blank(text[i:j]))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def declaration_extent(lines, code, i):
    """(first, last) line indexes of the declaration starting at line i: its
    doc-comment if one ends on the line just above, then every line up to the
    next line that starts a new command at column 0 (`code` is the comment-free
    copy of `lines`)."""
    start = i
    if i > 0 and lines[i - 1].rstrip().endswith("-/"):
        k = i - 1
        while k >= 0 and not lines[k].lstrip().startswith("/-"):
            k -= 1
        if k >= 0 and lines[k].lstrip().startswith("/--") and all(not code[j].strip() for j in range(k, i)):
            start = k
    last = i
    for j in range(i + 1, len(lines)):
        if not code[j].strip():
            continue
        if not code[j][:1].isspace():
            break
        last = j
    return start, last


def top_level_modules(repo, sha):
    return sorted(l.split("\t", 1)[1] for l in git(repo, "ls-tree", sha, "--", "QPCP/").splitlines()
                  if l.split()[1] == "blob" and l.endswith(".lean"))


def lean_definition(repo, sha, loc):
    """The source at the location Lean reported, checked against the file at <sha>:
    a maintainer-written module, lines in range, and a declaration of that name
    starting inside them. None if any check fails: never a guess."""
    path = "/".join(loc["module"].split(".")) + ".lean"
    if path not in top_level_modules(repo, sha):
        return None
    lines = git(repo, "show", f"{sha}:{path}").splitlines()
    code = strip_comments("\n".join(lines)).split("\n")
    a, b = loc["line"], loc["endLine"]
    if not 1 <= a <= b <= len(lines):
        return None
    short = loc["name"].rsplit(".", 1)[-1]
    if not any((d := DECL_RE.match(code[j])) and d.group(1).rsplit(".", 1)[-1] == short for j in range(a - 1, b)):
        return None
    return {"name": loc["name"], "path": path, "line": a, "endLine": b,
            "source": "\n".join(lines[a - 1:b]), "located": "lean", "files": [path]}


def text_definition(repo, sha, name):
    """Fallback when Lean's locations are not in the evidence: a strict text
    search of the maintainer-written modules with comments removed. Exactly one
    declaration of that full name is a match; none or several is "not found",
    with the files to look at, and no source."""
    wanted = {name, f"QPCP.{name}", f"QPCP.Statement.{name}"}
    hits = []
    for path in top_level_modules(repo, sha):
        lines = git(repo, "show", f"{sha}:{path}").splitlines()
        code = strip_comments("\n".join(lines)).split("\n")
        scopes = []  # namespace components per open scope; a section opens an empty one
        for i, line in enumerate(code):
            mm = re.match(r"^\s*(?:noncomputable\s+)?(namespace|section|end)\b\s*([\w.']*)", line)
            if mm:
                if mm.group(1) == "namespace":
                    scopes.append(mm.group(2).split("."))
                elif mm.group(1) == "section":
                    scopes.append([])
                elif scopes:
                    scopes.pop()
                continue
            d = DECL_RE.match(line)
            if d:
                full = ".".join([c for sc in scopes for c in sc] + [d.group(1)])
                if full in wanted:
                    hits.append((path, lines, code, i, full))
    if len(hits) != 1:
        return {"name": name, "path": None, "line": None, "endLine": None, "source": None,
                "located": "not found" if not hits else "ambiguous", "files": sorted({h[0] for h in hits})}
    path, lines, code, i, full = hits[0]
    a, b = declaration_extent(lines, code, i)
    return {"name": full, "path": path, "line": a + 1, "endLine": b + 1,
            "source": "\n".join(lines[a:b + 1]), "located": "text", "files": [path]}


def statement_definition(repo, sha, spath, sline, lean_loc=None, lean_ran=False):
    """For a statement that is one name (`def S059 : Prop := QPCP.Promise.BoolGroundEnergy`),
    that definition, at <sha>. Lean's own location (from the sandboxed verification's
    evidence) is preferred; without it, the strict text search. None when the
    statement is not one name (if Lean ran, that is Lean's answer)."""
    if lean_loc:
        found = lean_definition(repo, sha, lean_loc)
        return found or {"name": lean_loc["name"], "path": None, "line": None, "endLine": None,
                         "source": None, "located": "not found", "files": []}
    if lean_ran:
        return None
    lines = git(repo, "show", f"{sha}:{spath}").splitlines()
    code = strip_comments("\n".join(lines)).split("\n")
    _, e = declaration_extent(lines, code, sline - 1)
    m = ONE_NAME.match(" ".join(l.strip() for l in code[sline - 1:e + 1]))
    return text_definition(repo, sha, m.group(1)) if m else None


def validate_item(it):
    want = {"kind", "id", "declaration", "path", "blob", "verdict", "statementDigest", "dependsOn"}
    if not isinstance(it, dict) or set(it) not in (want, want | {"statementDefinition"}):
        raise Fault(f"malformed evidence item: {sorted(it) if isinstance(it, dict) else it!r}")
    if it["kind"] not in KINDS or not isinstance(it["id"], str) or not ID_RE.match(it["id"]):
        raise Fault(f"bad kind or id: {it.get('kind')} {it.get('id')}")
    if it["kind"] == "lemma" and not it["id"].startswith("L"):
        raise Fault(f"a lemma id must start with L: {it['id']}")
    if it["declaration"] != f"{DECL_NS[it['kind']]}.{it['id']}":
        raise Fault(f"{it['id']}: declaration {it['declaration']!r} is not {DECL_NS[it['kind']]}.{it['id']}")
    if it["path"] != f"{KINDS[it['kind']]}/{it['id']}.lean":
        raise Fault(f"{it['id']}: path {it['path']!r} is not {KINDS[it['kind']]}/{it['id']}.lean")
    if not isinstance(it["verdict"], str) or not re.fullmatch(r"[A-Z][A-Z -]{1,30}", it["verdict"]):
        raise Fault(f"{it['id']}: malformed verdict")
    digest_ok = HEX64.match(str(it["statementDigest"])) or (it["verdict"] != "ACCEPTED" and it["statementDigest"] == "")
    if not HEX40.match(str(it["blob"])) or not digest_ok:
        raise Fault(f"{it['id']}: malformed blob id or statement digest")
    if not isinstance(it["dependsOn"], list) or not all(
            isinstance(d, str) and re.fullmatch(r"QPCP(\.[A-Za-z0-9_']+)+", d) for d in it["dependsOn"]):
        raise Fault(f"{it['id']}: malformed dependsOn")
    loc = it.get("statementDefinition")
    if loc is not None and not (
            isinstance(loc, dict) and set(loc) == LEAN_LOC_KEYS
            and isinstance(loc["name"], str) and re.fullmatch(r"QPCP(\.[A-Za-z_][\w']*)+", loc["name"])
            and isinstance(loc["module"], str) and re.fullmatch(r"QPCP\.[A-Za-z_]\w*", loc["module"])
            and all(isinstance(loc[k], int) and not isinstance(loc[k], bool) for k in ("line", "endLine"))
            and 1 <= loc["line"] <= loc["endLine"] and it["id"].startswith("S")):
        raise Fault(f"{it['id']}: malformed statementDefinition")


def build_record(evidence_docs, repo, sha, run_url, attempt, now=None):
    if not HEX40.match(sha):
        raise Fault(f"not a full commit id: {sha!r}")
    if not evidence_docs:
        raise Fault("no evidence")
    items, shards = {}, set()
    # Lean's locations count only if every shard's query ran; otherwise the text search for all.
    lean_ran = all(doc.get("locatedByLean") is True for doc in evidence_docs)
    for doc in evidence_docs:
        if doc.get("format") != FORMAT:
            raise Fault(f"unknown evidence format {doc.get('format')!r}")
        if doc.get("only") or doc.get("replayOnly"):
            raise Fault("a partial (--only) or replay-only run is never a record")
        shard = doc.get("shard") or [1, 1]
        shards.add(tuple(shard))
        for it in doc["items"]:
            validate_item(it)
            prev = items.get(it["path"])
            if prev is not None and prev != it:
                raise Fault(f"{it['path']}: two shards disagree")
            items[it["path"]] = it
    totals = {n for _, n in shards}
    if len(totals) != 1 or {k for k, _ in shards} != set(range(1, next(iter(totals)) + 1)):
        raise Fault(f"shards {sorted(shards)} do not cover the whole record")
    tree = tree_contributions(repo, sha)
    missing, extra = sorted(set(tree) - set(items)), sorted(set(items) - set(tree))
    if missing or extra:
        raise Fault(f"the evidence does not match the tree at {sha[:7]}: missing {missing}, not in the tree {extra}")
    out, display = [], {}
    for path in sorted(items, key=lambda p: (items[p]["kind"] != "lemma", items[p]["id"])):
        it = items[path]
        if it["blob"] != tree[path]:
            raise Fault(f"{path}: the verified bytes (blob {it['blob'][:7]}) are not the file at {sha[:7]} "
                        f"(blob {tree[path][:7]})")
        if it["verdict"] != "ACCEPTED":
            raise Fault(f"{it['kind']} {it['id']} is {it['verdict']}; a record is made only of a run that accepted everything")
        spath, sline = statement_location(repo, sha, it["kind"], it["id"])
        loc = it.get("statementDefinition")
        out.append({**{k: v for k, v in it.items() if k != "statementDefinition"},
                    "statementPath": spath, "statementLine": sline})
        shown = statement_definition(repo, sha, spath, sline, loc, lean_ran)
        if shown is not None:
            display[f"{it['kind']}:{it['id']}"] = shown
    manifest = json.loads(git(repo, "show", f"{sha}:lake-manifest.json"))
    mathlib = next((p for p in manifest.get("packages", []) if p.get("name") == "mathlib"), None)
    if not mathlib or not HEX40.match(mathlib.get("rev", "")):
        raise Fault("lake-manifest.json names no Mathlib revision")
    return {
        "format": FORMAT,
        "evidence": {
            "commit": sha,
            "toolchain": git(repo, "show", f"{sha}:lean-toolchain").strip(),
            "mathlib": mathlib["rev"],
            "items": out,
        },
        # Display only, OUTSIDE the evidence: how a definition was found (Lean's
        # location or the text fallback) can differ between two runs on the same
        # commit, and must never make a second publication a fault. site_data.py
        # compares only `evidence`; the first publication's display is kept.
        "display": {"statementDefinitions": display},
        "run": {"url": run_url, "attempt": int(attempt)},
        "verifiedAt": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def cmd_build(argv):
    args = dict(zip(argv[::2], argv[1::2]))
    need = {"--evidence-dir", "--sha", "--repo", "--run-url", "--attempt", "--out"}
    if set(args) != need or len(argv) != 2 * len(need):
        raise Fault("usage: build " + " ".join(f"{k} <...>" for k in sorted(need)))
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/actions/runs/\d+(/attempts/\d+)?", args["--run-url"]):
        raise Fault(f"unexpected run URL {args['--run-url']!r}")
    docs = [json.loads(p.read_text()) for p in sorted(Path(args["--evidence-dir"]).glob("*.json"))]
    record = build_record(docs, args["--repo"], args["--sha"], args["--run-url"], args["--attempt"])
    Path(args["--out"]).write_text(json.dumps(record, indent=1) + "\n")
    print(f"record for {args['--sha'][:7]}: {len(record['evidence']['items'])} results, all ACCEPTED")


def main(argv):
    try:
        if len(argv) == 4 and argv[1] == "evidence":
            cmd_evidence(argv[2], argv[3])
            return 0
        if len(argv) > 1 and argv[1] == "build":
            cmd_build(argv[2:])
            return 0
        print(__doc__)
        return 2
    except Fault as e:
        print(f"FAULT: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
