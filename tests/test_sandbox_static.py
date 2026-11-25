#!/usr/bin/env python3
"""No untrusted input reaches a process outside the sandbox (static check).

    python3 -I tests/test_sandbox_static.py

In scripts/sandbox_verify.py, processes are started in exactly three places:
Env.lake (lake on main's maintainer-written modules), Env.run_sandboxed (the
sandbox wrapper) and Verifier.trusted_reference (leanexport on main's trusted
build). nanoda_bin and verify_export.py must be started only through
run_sandboxed. tests/run_tests.sh checks the same at run time, from the
list of sandboxed steps (logs/steps.log).
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

print(f"failed {fails}")
sys.exit(1 if fails else 0)
