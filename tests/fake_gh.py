#!/usr/bin/env python3
"""A stand-in `gh` for tests/test_claims.py: `gh api -X <M> repos/<R>/<path> [--paginate --slurp] [--input -]`.

State lives in the JSON file $FAKE_GH_STATE, read and written under an
exclusive lock, so several processes can share it. With $FAKE_GH_BARRIER=<dir>
and $FAKE_GH_BARRIER_N=<n>, each run ($FAKE_GH_RUN) waits at its first write
until n runs have reached theirs: two runs that both read an unclaimed issue
then both write, as two simultaneous GitHub Actions runs can. A pull request
listed in $FAKE_GH_STATE's "change_on_read" is changed (once) when it is first
read individually, after any listing: as if it were retargeted or pushed to
in between.
"""

import fcntl
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def barrier():
    d = os.environ.get("FAKE_GH_BARRIER")
    run = os.environ.get("FAKE_GH_RUN")
    if not d or not run:
        return
    marker = Path(d) / f"{run}.arrived"
    if marker.exists():
        return
    marker.write_text("1")
    n = int(os.environ.get("FAKE_GH_BARRIER_N", "2"))
    deadline = time.time() + 30
    while len(list(Path(d).glob("*.arrived"))) < n and time.time() < deadline:
        time.sleep(0.05)


def main(argv):
    if argv[:2] != ["api", "-X"]:
        print(f"fake gh: unsupported {argv}", file=sys.stderr)
        return 2
    method, full = argv[2], argv[3]
    slurp = "--slurp" in argv
    body = json.loads(sys.stdin.read() or "null") if "--input" in argv else None
    parts = urlsplit(full)
    path = parts.path.split("/", 3)[3]  # drop repos/<owner>/<repo>/
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    if method != "GET":
        barrier()
    with open(os.environ["FAKE_GH_STATE"], "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        st = json.load(f)
        out, code = handle(st, method, path, q, body)
        st.setdefault("log", []).append([method, full, body])
        f.seek(0)
        f.truncate()
        json.dump(st, f)
    if code == 404:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        return 1
    if out is not None:
        print(json.dumps([out] if slurp else out))
    return 0


def handle(st, method, path, q, body):
    seg = path.split("/")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(os.environ.get("QPCP_NOW") or time.time())))
    issues = st.setdefault("issues", {})
    pulls = st.setdefault("pulls", {})
    if seg[0] == "issues" and len(seg) == 1 and method == "GET":
        out = [dict(i, comments=None) for i in issues.values() if q.get("state", "open") in ("all", i["state"])
               and (not q.get("labels") or q["labels"] in [l["name"] for l in i["labels"]])]
        return [{k: v for k, v in i.items() if k != "comments"} for i in out], 200
    if seg[0] == "issues":
        i = issues.get(seg[1])
        if i is None:
            return None, 404
        if len(seg) == 2 and method == "GET":
            return {k: v for k, v in i.items() if k != "comments"}, 200
        if seg[2] == "comments" and method == "GET":
            return i["comments"], 200
        if seg[2] == "events" and method == "GET":
            return i.get("events", []), 200
        if seg[2] == "comments" and method == "POST":
            st["next_id"] = st.get("next_id", 1000) + 1
            i["comments"].append({"id": st["next_id"], "user": {"login": "github-actions[bot]"},
                                  "body": body["body"], "created_at": now})
            return {"id": st["next_id"]}, 200
        if seg[2] == "assignees":
            names = [a["login"] for a in i["assignees"]]
            for who in body["assignees"]:
                if method == "POST" and who not in names:
                    i["assignees"].append({"login": who})
                if method == "DELETE":
                    i["assignees"] = [a for a in i["assignees"] if a["login"] != who]
            return {}, 200
        if seg[2] == "labels" and method == "POST":
            for name in body["labels"]:
                if name not in [l["name"] for l in i["labels"]]:
                    i["labels"].append({"name": name})
            return [], 200
        if seg[2] == "labels" and method == "DELETE":
            if seg[3] not in [l["name"] for l in i["labels"]]:
                return None, 404
            i["labels"] = [l for l in i["labels"] if l["name"] != seg[3]]
            return [], 200
    if seg[0] == "pulls" and len(seg) == 1:
        return [{k: v for k, v in p.items() if k != "files"} for p in pulls.values() if p["state"] == q.get("state", "open")], 200
    if seg[0] == "pulls":
        p = pulls.get(seg[1])
        if p is None:
            return None, 404
        if len(seg) == 2 and method == "GET":
            # A change made between a listing and this individual read (retargeted, new head).
            p.update(st.get("change_on_read", {}).pop(seg[1], {}))
            return {k: v for k, v in p.items() if k != "files"}, 200
        if len(seg) == 2 and method == "PATCH":
            p.update(body)
            return {}, 200
        if seg[2] == "files":
            return p["files"], 200
    if seg[0] == "contents":
        return ({"path": "/".join(seg[1:])}, 200) if "/".join(seg[1:]) in st.get("main_files", []) else (None, 404)
    if seg[0] == "commits" and len(seg) == 1:
        return st.get("commits_by_path", {}).get(q.get("path"), []), 200
    if seg[0] == "commits" and seg[2] == "pulls":
        return st.get("commit_pulls", {}).get(seg[1], []), 200
    return None, 404


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
