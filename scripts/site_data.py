#!/usr/bin/env python3
"""Read and write the `site-data` branch, which keeps its history (#113).

    site_data.py publish-record <record.json> <remote> <repo>
        Adds records/<commit>.json and moves latest.json to it, if <commit> is
        on main's history (origin/main in <repo>) and descends from the commit
        latest.json names. A record is never overwritten: if one exists for the
        commit, an identical `evidence` part is a no-op and a different one is
        a fault (exit 2).
    site_data.py fetch-latest <remote> <out.json>
        Writes the record latest.json points at to <out.json>; if there is no
        record yet, writes nothing and says so (exit 0). It adds one key the
        record file does not have, `publication`, read from the branch's own
        history: the site-data commit that added each record (so a citation
        can name bytes that never change), and for each result the earliest
        record that accepted the same file (path and Git blob).
    site_data.py publish-status <status.json> <remote>
        Replaces status.json.

<remote> is a path or URL. `github:<owner>/<repo>` means that repository on
GitHub, with the token in $GH_TOKEN (never printed). Each write clones the tip
of the branch, changes only its own files, commits, and pushes without force;
if another writer pushed first, it starts again from the new tip.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BRANCH = "site-data"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
TRIES = 6
IDENTITY = ["-c", "user.name=qpcp-status", "-c", "user.email=qpcp-status@users.noreply.github.com",
            "-c", "commit.gpgsign=false"]


class Fault(Exception):
    pass


def remote_url(remote):
    if remote.startswith("github:"):
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise Fault("GH_TOKEN is not set")
        return f"https://x-access-token:{token}@github.com/{remote[len('github:'):]}.git"
    return remote


def redact(text):
    token = os.environ.get("GH_TOKEN")
    return text.replace(token, "***") if token else text


def run(*args, cwd=None, check=True):
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        # The command may contain a token URL: report only the git subcommand.
        sub = next((a for a in args[1:] if not a.startswith("-") and "://" not in a), "")
        raise Fault(f"git {sub} failed: {redact(r.stderr.strip())[:300]}")
    return r


def checkout(url, into):
    """A clone of the branch's tip, or a new empty branch if it does not exist yet."""
    r = run("git", "clone", "-q", "--branch", BRANCH, "--single-branch", url, str(into), check=False)
    if r.returncode != 0:
        if "not found" not in r.stderr and "Remote branch" not in r.stderr:
            raise Fault(f"git clone failed: {redact(r.stderr.strip())[:300]}")
        Path(into).mkdir(parents=True, exist_ok=True)
        run("git", "init", "-q", "-b", BRANCH, cwd=into)
        run("git", "remote", "add", "origin", url, cwd=into)
    return Path(into)


def write_with_retry(url, change, message):
    """Clone, apply change(dir) -> bool (changed?), commit and push; retry on a lost race."""
    for attempt in range(TRIES):
        with tempfile.TemporaryDirectory(prefix="qpcp-site-data-") as tmp:
            d = checkout(url, Path(tmp) / "site")
            if not change(d):
                return False
            run("git", "add", "-A", cwd=d)
            run("git", *IDENTITY, "commit", "-q", "-m", message, cwd=d)
            r = run("git", "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=d, check=False)
            if r.returncode == 0:
                return True
            if "rejected" not in r.stderr and "fetch first" not in r.stderr and "non-fast-forward" not in r.stderr:
                raise Fault(f"git push failed: {redact(r.stderr.strip())[:300]}")
        time.sleep(2 + 3 * attempt)
    raise Fault(f"could not push to {BRANCH} after {TRIES} tries")


def dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def apply_record(d, record, is_ancestor):
    """Add the record to the checkout d. Returns True if anything changed."""
    sha = record["evidence"]["commit"]
    if not HEX40.match(sha):
        raise Fault(f"bad commit id {sha!r}")
    rec_path = d / "records" / f"{sha}.json"
    changed = False
    if rec_path.exists():
        old = json.loads(rec_path.read_text())
        if old.get("evidence") != record["evidence"]:
            raise Fault(f"records/{sha}.json exists with different evidence; a record is never overwritten "
                        "(a second run on the same commit reached a different result)")
    else:
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(dump(record))
        changed = True
    latest_path = d / "latest.json"
    latest = json.loads(latest_path.read_text()) if latest_path.exists() else None
    move = latest is None or (latest["commit"] != sha and is_ancestor(latest["commit"], sha))
    if move:
        latest_path.write_text(dump({
            "commit": sha, "record": f"records/{sha}.json",
            "verifiedAt": record["verifiedAt"], "run": record["run"],
        }))
        changed = True
    elif latest["commit"] != sha:
        print(f"latest.json stays at {latest['commit'][:7]}: {sha[:7]} does not descend from it")
    return changed


def ancestry(repo):
    def is_ancestor(a, b):
        r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b], capture_output=True)
        if r.returncode in (0, 1):
            return r.returncode == 0
        raise Fault(f"cannot compare {a[:7]} and {b[:7]} in {repo}")
    return is_ancestor


def cmd_publish_record(record_path, remote, repo):
    record = json.loads(Path(record_path).read_text())
    sha = record["evidence"]["commit"]
    is_ancestor = ancestry(repo)
    if not is_ancestor(sha, "refs/remotes/origin/main"):
        raise Fault(f"{sha[:7]} is not on main's history; only commits of main get a record")
    changed = write_with_retry(remote_url(remote), lambda d: apply_record(d, record, is_ancestor),
                               f"verification record for {sha[:7]}")
    print(f"records/{sha}.json: " + ("published" if changed else "already published, identical evidence"))


def cmd_fetch_latest(remote, out):
    with tempfile.TemporaryDirectory(prefix="qpcp-site-data-") as tmp:
        d = checkout(remote_url(remote), Path(tmp) / "site")
        latest = d / "latest.json"
        if not latest.exists():
            print("no verification record yet")
            return
        pointer = json.loads(latest.read_text())
        rec = d / pointer["record"]
        if not re.fullmatch(r"records/[0-9a-f]{40}\.json", pointer["record"]) or not rec.is_file():
            raise Fault(f"latest.json points at a missing record: {pointer['record']!r}")
        record = json.loads(rec.read_text())
        if record["evidence"]["commit"] != pointer["commit"]:
            raise Fault("latest.json and its record name different commits")
        record["publication"] = publication(d, record)
        Path(out).write_text(json.dumps(record, indent=1) + "\n")
        print(f"latest verified commit: {pointer['commit'][:7]} ({record['verifiedAt']})")


def publication(d, latest_record):
    """Where each record was published, and when each result's exact file was first verified."""
    log = run("git", "log", "--reverse", "--diff-filter=A", "--format=%H", "--name-only", "--", "records/",
              cwd=d).stdout.split("\n")
    added, commit = [], None
    for line in log:
        if HEX40.match(line):
            commit = line
        elif re.fullmatch(r"records/[0-9a-f]{40}\.json", line) and commit:
            added.append((line, commit))
    record_commit = {path: c for path, c in added}
    first = {}
    for path, c in added:  # in publication order, oldest first
        rec = json.loads((d / path).read_text())
        for it in rec["evidence"]["items"]:
            key = f"{it['kind']}:{it['id']}"
            if it.get("verdict") == "ACCEPTED" and key not in first:
                first[key] = []
            if it.get("verdict") == "ACCEPTED" and not any(f["blob"] == it["blob"] and f["path"] == it["path"]
                                                           for f in first[key]):
                first[key].append({"path": it["path"], "blob": it["blob"], "commit": rec["evidence"]["commit"],
                                   "verifiedAt": rec["verifiedAt"], "record": path, "recordCommit": c})
    own = f"records/{latest_record['evidence']['commit']}.json"
    return {"recordCommit": record_commit.get(own, ""),
            "firstVerified": {k: v for k, v in sorted(first.items())}}


def cmd_publish_status(status_path, remote):
    text = Path(status_path).read_text()
    json.loads(text)

    def change(d):
        target = d / "status.json"
        if target.exists() and target.read_text() == text:
            return False
        target.write_text(text)
        return True
    changed = write_with_retry(remote_url(remote), change, "status")
    print("status.json: " + ("published" if changed else "unchanged"))


def main(argv):
    try:
        if len(argv) == 5 and argv[1] == "publish-record":
            cmd_publish_record(argv[2], argv[3], argv[4])
        elif len(argv) == 4 and argv[1] == "fetch-latest":
            cmd_fetch_latest(argv[2], argv[3])
        elif len(argv) == 4 and argv[1] == "publish-status":
            cmd_publish_status(argv[2], argv[3])
        else:
            print(__doc__)
            return 2
        return 0
    except Fault as e:
        print(f"FAULT: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
