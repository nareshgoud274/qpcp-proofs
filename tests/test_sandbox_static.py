#!/usr/bin/env python3
"""No untrusted input reaches a process outside the sandbox (static check).

    python3 -I tests/test_sandbox_static.py

In scripts/sandbox_verify.py, processes are started in exactly three places:
Env.lake (lake on main's maintainer-written modules), Env.run_sandboxed (the
sandbox wrapper) and Verifier.trusted_reference (leanexport on main's trusted
build). nanoda_bin and verify_export.py must be started only through
run_sandboxed. tests/run_tests.sh checks the same at run time, from the
list of sandboxed steps (logs/steps.log).

Also: every `log` and `stdout_path` passed to run_sandboxed is built by
Env.log_path or Env.capture_path (directly, or through a variable or
Verifier.log assigned from them), which build paths in the host-only folders
logs/ and capture/; those folders are never sandbox-writable (not in
WRITABLE_ROOTS); and no such argument shares a variable with the call's `rw`
argument, so none is built from a directory that is also given writable.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "scripts" / "sandbox_verify.py").read_text()
tree = ast.parse(src)
fails = 0


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {detail}"))


starters = set()
for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef):
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id in ("subprocess", "os") and node.func.attr in (
                        "run", "Popen", "call", "check_call", "check_output", "system", "execv", "execvp", "spawnv"):
                    starters.add(fn.name)
check("processes are started only in lake, run_sandboxed and trusted_reference",
      starters == {"lake", "run_sandboxed", "trusted_reference"}, sorted(starters))

for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef) and fn.name == "trusted_reference":
        body = ast.get_source_segment(src, fn)
        check("trusted_reference runs only leanexport, with the trusted search path",
              "leanexport" in body and "nanoda" not in body and "verify_export" not in body
              and "trusted_lean_path" in body and "sandbox_lean_path" not in body)

for tool in ("nanoda_bin", "verify_export.py"):
    # Every outermost call whose arguments mention the tool must be run_sandboxed(...).
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and tool in (ast.get_source_segment(src, node) or ""):
            spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset,
                          ast.get_source_segment(src, node.func)))
    outer = [s for s in spans if not any(o is not s and (o[0], o[1]) <= (s[0], s[1]) and (o[2], o[3]) >= (s[2], s[3])
                                         for o in spans)]
    check(f"{tool} is started only through run_sandboxed ({len(outer)} call(s))",
          bool(outer) and all(f.endswith("run_sandboxed") for *_, f in outer), [f for *_, f in outer])

# ---- capture and log paths are host-only, never built from a writable directory
consts = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
            "WRITABLE_ROOTS", "HOST_ONLY"):
        consts[node.targets[0].id] = ast.literal_eval(node.value)
check("logs/ and capture/ are host-only and never sandbox-writable",
      {"logs", "capture"} <= set(consts.get("HOST_ONLY", ())) and not {"logs", "capture"} & set(consts.get("WRITABLE_ROOTS", ())),
      consts)
for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef) and fn.name in ("log_path", "capture_path", "log"):
        body = ast.get_source_segment(src, fn)
        want = {"log_path": '"logs"', "capture_path": '"capture"', "log": "log_path("}[fn.name]
        check(f"{fn.name} builds its path in {want}", want in body, body)


def assigned(fn, name, before):
    """The source of the last value assigned to `name` in fn before line `before`."""
    best = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and node.lineno < before:
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    best = (node.lineno, node.value)
                elif isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for el, val in zip(t.elts, node.value.elts):
                        if isinstance(el, ast.Name) and el.id == name:
                            best = (node.lineno, val)
    return best[1] if best else None


def names(expr):
    return {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)} - {"e", "env", "self", "m", "str", "Path", "f"}


calls = 0
for fn in ast.walk(tree):
    if not isinstance(fn, ast.FunctionDef):
        continue
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_sandboxed"):
            continue
        calls += 1
        args = {"rw": node.args[2] if len(node.args) > 2 else None, "log": node.args[3] if len(node.args) > 3 else None}
        args.update({k.arg: k.value for k in node.keywords})
        rw_names = names(args["rw"]) if args.get("rw") is not None else set()
        for kind, helper in (("log", ("log_path(", ".log(")), ("stdout_path", ("capture_path(",))):
            expr = args.get(kind)
            if expr is None:
                continue
            seen, frontier = set(), [expr]
            while frontier:  # follow simple variables back to what built them
                x = frontier.pop()
                if isinstance(x, ast.Name):
                    if x.id in seen:
                        continue
                    seen.add(x.id)
                    v = assigned(fn, x.id, node.lineno)
                    if v is not None:
                        frontier.append(v)
                        expr = v
            text = ast.get_source_segment(src, expr) or ""
            at = f"{fn.name}, line {node.lineno}"
            check(f"{at}: {kind} is a host-only path ({text})", any(h in text for h in helper), text)
            shared = names(expr) & rw_names
            check(f"{at}: {kind} shares nothing with rw", not shared, shared)
check(f"every run_sandboxed call was checked ({calls})", calls == src.count(".run_sandboxed(") and calls >= 6, calls)

print(f"failed {fails}")
sys.exit(1 if fails else 0)
