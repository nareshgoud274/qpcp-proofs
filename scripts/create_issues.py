#!/usr/bin/env python3
"""Create one GitHub issue per step in steps.json that has no issue yet.

Uses the signed-in `gh` CLI and the repository of the current folder.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def gh(*args):
    res = subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{res.stderr}")
    return res.stdout


def main():
    steps = json.loads((ROOT / "steps.json").read_text())
    existing = json.loads(
        gh("issue", "list", "--label", "step", "--state", "all",
           "--limit", "1000", "--json", "title")
    )
    have = {i["title"].split(":")[0].strip() for i in existing}

    for s in steps:
        if s.get("retired") is True:
            continue
        if s["id"] in have:
            continue
        deps = ", ".join(s["deps"]) if s["deps"] else "none"
        body = (
            f"**Step {s['id']}** ({s['section']})\n\n"
            f"{s['title']}.\n\n"
            f"- Statement: `QPCP.Statement.{s['id']}` in `QPCP/Statements.lean`\n"
            f"- Proof file to add: `QPCP/Proofs/{s['id']}.lean`\n"
            f"- Difficulty: {s['difficulty']} of 3\n"
            f"- Depends on: {deps}\n\n"
            "To work on this step, comment `/claim`. Instructions are in "
            "`JOIN.md` (agents) and `CONTRIBUTING.md` (people).\n\n"
            "If the statement looks false or wrongly formalized, say so here."
        )
        gh("issue", "create", "--title", f"{s['id']}: {s['title']}",
           "--body", body, "--label", "step")
        print(f"created {s['id']}")
        time.sleep(2)


if __name__ == "__main__":
    main()
