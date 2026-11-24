#!/usr/bin/env python3
"""Decide whether, and what, to post as a lemma statement's kernel preview.

    statement_preview.py <preview.json> <comment.md>

Run by the statement-preview workflow, from main, with GH_TOKEN, GH_REPO and
RUN_SHA (the commit the `check` run checked) set. The preview file comes from
that run's artifact and is treated as data. A comment is written to
<comment.md> only if:

  * the preview is well formed and is for the commit that was checked;
  * the pull request is open, its head is still that commit, and it adds
    exactly QPCP/Lemmas/<ident>.lean and nothing else, which means the
    `check` workflow that made the preview was main's own;
  * the same preview has not been posted already.

Prints the pull request number to post on, or nothing. Exit 0 either way;
exit 1 on a malformed or mismatched preview.
"""

import json
import os
import re
import subprocess
import sys

MAX_PREVIEW = 100_000
MAX_TEXT = 20_000


def gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return r.stdout


def decide(preview_path, comment_path, run_sha, repo):
    if os.path.getsize(preview_path) > MAX_PREVIEW:
        raise ValueError("preview too large")
    p = json.load(open(preview_path, encoding="utf-8"))
    pr, sha, ident, text = p.get("pr"), p.get("head_sha"), p.get("ident"), p.get("text")
    if not (isinstance(pr, int) and not isinstance(pr, bool) and pr > 0
            and isinstance(sha, str) and isinstance(ident, str) and isinstance(text, str)):
        raise ValueError("malformed preview")
    if not re.fullmatch(r"L\d{1,9}", ident) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("malformed preview")
    if sha != run_sha:
        raise ValueError("the preview is not for the commit that was checked")
    info = json.loads(gh_json("pr", "view", str(pr), "--json", "headRefOid,files,state"))
    files = [(f.get("path"), f.get("changeType")) for f in info.get("files", [])]
    if info.get("state") != "OPEN" or info.get("headRefOid") != sha:
        return None, "the pull request has moved on; not posting"
    if files != [(f"QPCP/Lemmas/{ident}.lean", "ADDED")]:
        return None, f"the pull request does not add exactly QPCP/Lemmas/{ident}.lean; not posting"
    marker = f"<!-- qpcp-statement-preview {sha} -->"
    if marker in gh_json("api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq", ".[].body"):
        return None, "already posted"
    clean = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)[:MAX_TEXT]
    clean = clean.replace("```", "`​`​`")
    with open(comment_path, "w", encoding="utf-8") as fh:
        fh.write(f"{marker}\n**Kernel statement of {ident}**, as the checker verified it "
                 f"(rendered by nanoda from the export of commit `{sha[:7]}`). "
                 "A reviewer should check that this says what the `PLAIN:` sentence says.\n\n"
                 f"```\n{clean.strip()}\n```\n")
    return pr, "posting"


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    try:
        pr, why = decide(argv[1], argv[2], os.environ["RUN_SHA"], os.environ["GH_REPO"])
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as e:
        print(f"not posting: {e}", file=sys.stderr)
        return 1
    print(why, file=sys.stderr)
    if pr:
        print(pr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
