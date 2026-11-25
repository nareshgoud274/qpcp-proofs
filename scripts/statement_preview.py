#!/usr/bin/env python3
"""Decide whether, and what, to post as a lemma statement's kernel preview.

    statement_preview.py run <work-dir> <comment.md>

Run by the statement-preview workflow, from main, with GH_TOKEN, GH_REPO,
RUN_ID (the `check` run) and RUN_SHA (the commit it checked) set.

  1. Before anything is downloaded, the pull request is found and validated
     through the API alone: exactly one open pull request whose head is
     RUN_SHA, and it adds exactly QPCP/Lemmas/L<N>.lean and nothing else,
     which means the `check` workflow that ran on it was main's own. The
     pull request number and the lemma id come from the API, never from the
     artifact.
  2. Only then is the run's `statement-preview` artifact downloaded. It is
     data: only its `text` is used. If it names a pull request, commit or
     lemma, they must be the ones found in step 1.
  3. Just before the comment is written, the pull request is read again and
     must still be open at RUN_SHA with the same single file, and the same
     preview must not have been posted already.

Prints the pull request number to post on, or nothing. Exit 0 either way;
exit 1 on a malformed or mismatched preview.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_PREVIEW = 100_000
MAX_TEXT = 20_000
LEMMA_PATH = re.compile(r"QPCP/Lemmas/(L\d{1,9})\.lean")


class Mismatch(Exception):
    pass


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return r.stdout


def lemma_of(info, sha):
    """The lemma id if this pull request is open at `sha` and adds exactly one lemma file."""
    files = [(f.get("path"), f.get("changeType")) for f in info.get("files") or []]
    if info.get("state") != "OPEN" or info.get("headRefOid") != sha or len(files) != 1:
        return None
    path, change = files[0]
    m = LEMMA_PATH.fullmatch(path or "")
    return m.group(1) if m and change == "ADDED" else None


def find_pull_request(sha):
    """(number, ident) of the one open pull request at `sha` that adds one lemma file, or None."""
    found = json.loads(gh("pr", "list", "--state", "open", "--search", sha, "--limit", "20",
                          "--json", "number,headRefOid,files,state") or "[]")
    at_sha = [p for p in found if p.get("headRefOid") == sha]
    if len(at_sha) != 1:
        return None, f"{len(at_sha)} open pull requests are at {sha[:7]}; not posting"
    pr = at_sha[0]
    number = pr.get("number")
    if type(number) is not int or number <= 0:
        return None, "malformed pull request number"
    ident = lemma_of(pr, sha)
    if ident is None:
        return None, f"pull request #{number} does not add exactly one lemma file; not posting"
    return (number, ident), "found"


def read_preview(path, number, ident, sha):
    if not path.is_file() or path.is_symlink():
        raise Mismatch("the run has no statement preview")
    if path.stat().st_size > MAX_PREVIEW:
        raise Mismatch("preview too large")
    p = json.loads(path.read_text(encoding="utf-8"))
    if type(p) is not dict or type(p.get("text")) is not str:
        raise Mismatch("malformed preview")
    for key, want in (("pr", number), ("ident", ident), ("head_sha", sha)):
        if key in p and p[key] != want:
            raise Mismatch(f"the preview's `{key}` is not this pull request's")
    return p["text"]


def run(work, comment_path, sha, run_id, repo):
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not re.fullmatch(r"\d{1,20}", run_id):
        raise Mismatch("bad RUN_SHA or RUN_ID")
    found, why = find_pull_request(sha)
    if found is None:
        return None, why
    number, ident = found
    work.mkdir(parents=True, exist_ok=True)
    gh("run", "download", run_id, "-n", "statement-preview", "-D", str(work))
    text = read_preview(work / "preview.json", number, ident, sha)
    info = json.loads(gh("pr", "view", str(number), "--json", "headRefOid,files,state"))
    if lemma_of(info, sha) != ident:
        return None, "the pull request has moved on; not posting"
    marker = f"<!-- qpcp-statement-preview {sha} -->"
    if marker in gh("api", f"repos/{repo}/issues/{number}/comments", "--paginate", "--jq", ".[].body"):
        return None, "already posted"
    clean = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)[:MAX_TEXT]
    clean = clean.replace("```", "`​`​`")
    with open(comment_path, "w", encoding="utf-8") as fh:
        fh.write(f"{marker}\n**Kernel statement of {ident}**, as the checker verified it "
                 f"(rendered by nanoda from the export of commit `{sha[:7]}`). "
                 "A reviewer should check that this says what the `PLAIN:` sentence says.\n\n"
                 f"```\n{clean.strip()}\n```\n")
    return number, "posting"


def main(argv):
    if len(argv) != 4 or argv[1] != "run":
        print(__doc__)
        return 2
    try:
        pr, why = run(Path(argv[2]), argv[3], os.environ["RUN_SHA"], os.environ["RUN_ID"], os.environ["GH_REPO"])
    except (Mismatch, KeyError, ValueError, OSError) as e:
        print(f"not posting: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"not posting: `gh {e.cmd[1]} {e.cmd[2]}` failed", file=sys.stderr)
        return 1
    print(why, file=sys.stderr)
    if pr:
        print(pr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
