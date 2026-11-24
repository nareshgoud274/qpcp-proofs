#!/usr/bin/env python3
"""Build status.json, the single file the project site reads.

Runs in GitHub Actions on a checkout of main, with GH_TOKEN and
GITHUB_REPOSITORY set. It combines:

  * the working tree: steps.json, programs.json, retired.json, and the files
    under QPCP/Lemmas, QPCP/Proofs and QPCP/Refutations. Files on main are the
    record: a step is proved or refuted exactly when its file exists;
  * the GitHub API: issues (claims, reports, proposals), pull requests
    (credit, work in the checker) and releases (updates).

Visitors' browsers fetch only the resulting file, so the site keeps working
however many people are watching and however large the record grows.

Usage: build_status.py <output-path>
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID = r"(?:S\d{3,6}|L\d{1,9})"
ID_RE = re.compile(rf"\b({ID})\b")
CANON_RE = re.compile(rf"^\s*(Prove|Refute|State)\s+({ID})\s*$", re.I)
REPORT_RE = re.compile(rf"^\s*report\s+({ID})\s*:?\s*", re.I)
VERB_KIND = {"prove": "proved", "refute": "refuted", "state": "stated"}
MAX_FEED = 200


def api(path, token, repo):
    """Fetch every page of a GitHub REST list endpoint."""
    url = f"https://api.github.com/repos/{repo}{path}"
    url += ("&" if "?" in url else "?") + "per_page=100"
    out = []
    while url:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qpcp-status",
        })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    out.extend(json.load(r))
                    link = r.headers.get("Link", "")
                break
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 500, 502, 503) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def labels(issue):
    return {l["name"] for l in issue.get("labels", [])}


def login(obj):
    return (obj.get("user") or {}).get("login", "")


def read_tree(root=ROOT):
    """Everything the status needs from the working tree."""
    def load(name, default):
        p = root / name
        return json.loads(p.read_text()) if p.is_file() else default

    lemmas = []
    for path in sorted((root / "QPCP" / "Lemmas").glob("L*.lean"), key=lambda p: int(p.stem[1:])):
        src = path.read_text(errors="replace")
        program = re.search(r"^\s*PROGRAM:\s*([a-z0-9-]+)\s*$", src, re.M)
        plain = re.search(r"^\s*PLAIN:\s*(.+?)\s*$", src, re.M)
        lemmas.append({
            "id": path.stem,
            "program": program.group(1) if program else "",
            "title": plain.group(1) if plain else path.stem,
        })
    return {
        "steps": load("steps.json", []),
        "programs": load("programs.json", []),
        "retired": set(load("retired.json", [])),
        "barriers": load("barriers.json", []),
        "lemmas": lemmas,
        "proofs": {p.stem for p in (root / "QPCP" / "Proofs").glob("*.lean")},
        "refutations": {p.stem for p in (root / "QPCP" / "Refutations").glob("*.lean")},
    }


def assemble(tree, issues, closed_pulls, open_pulls, releases, now=None):
    """Pure function: the tree and raw GitHub data in, the status document out."""
    step_issue, reports, proposals, mandates, by_number = {}, [], [], [], {}
    for i in issues:
        if "pull_request" in i:
            continue
        by_number[i["number"]] = i
        names = labels(i)
        if "report" in names:
            reports.append(i)
        elif "mandate" in names:
            mandates.append(i)
        elif "proposal" in names:
            proposals.append(i)
        elif "step" in names:
            m = re.match(rf"^({ID}):", i.get("title") or "")
            if m:
                step_issue[m.group(1)] = i

    # Credit comes from merged pull requests. The automerge workflow gives each
    # one a canonical title: "Prove <ID>", "Refute <ID>" or "State <ID>".
    credit = {}
    for p in sorted(closed_pulls, key=lambda p: p.get("merged_at") or ""):
        if not p.get("merged_at") or not login(p):
            continue
        title = p.get("title") or ""
        m = CANON_RE.match(title)
        if m:
            key = (VERB_KIND[m.group(1).lower()], m.group(2).upper())
        else:
            loose = ID_RE.search(title)
            if not loose:
                continue
            key = ("proved", loose.group(1))
        credit.setdefault(key, p)

    program_title = {p["id"]: p["title"] for p in tree["programs"]}
    rows = [{
        "id": s["id"], "title": s["title"], "section": s["section"], "program": "founding",
        "retired": s.get("retired") is True, "replacedBy": s.get("replaced_by", ""),
    } for s in tree["steps"]]
    rows += [{
        "id": l["id"], "title": l["title"], "program": l["program"],
        "section": program_title.get(l["program"], l["program"] or "Other"),
        "retired": False, "replacedBy": "",
    } for l in tree["lemmas"]]

    people = {}

    def give(who, kind, sid):
        if who:
            people.setdefault(who, {"proved": [], "refuted": [], "stated": []})[kind].append(sid)

    count = {"proved": 0, "refuted": 0, "claimed": 0, "open": 0, "retired": 0, "disputed": 0,
             "humanReviewed": 0}
    per_program, out_steps = {}, []
    for r in rows:
        sid = r["id"]
        issue = step_issue.get(sid) or (by_number.get(int(sid[1:])) if sid.startswith("L") else None)
        names = labels(issue) if issue else set()
        status, who, when, pr = "open", "", "", None
        if r["retired"] or sid in tree["retired"] or "retired" in names:
            status = "retired"
            when = (issue or {}).get("closed_at") or ""
        elif sid in tree["proofs"]:
            status, pr = "proved", credit.get(("proved", sid))
        elif sid in tree["refutations"]:
            status, pr = "refuted", credit.get(("refuted", sid))
        elif "claimed" in names:
            status = "claimed"
            who = ", ".join(a["login"] for a in issue.get("assignees", []))
            when = issue.get("updated_at") or ""
        if status in ("proved", "refuted"):
            who = login(pr) if pr else ""
            when = (pr or {}).get("merged_at") or (issue or {}).get("closed_at") or ""
            give(who, status, sid)
        stated = credit.get(("stated", sid))
        if stated:
            give(login(stated), "stated", sid)
        disputed = status != "retired" and "disputed" in names
        # Review by a human specialist is tracked separately from Lean's verdict.
        reviewed = "human-reviewed" in names
        if reviewed:
            count["humanReviewed"] += 1
        count[status] += 1
        if disputed:
            count["disputed"] += 1
        tally = per_program.setdefault(r["program"], {"proved": 0, "refuted": 0, "claimed": 0, "open": 0, "retired": 0})
        tally[status] += 1
        out_steps.append({
            "id": sid, "title": r["title"], "section": r["section"], "program": r["program"],
            "status": status, "who": who, "when": when, "disputed": disputed, "reviewed": reviewed,
            "replacedBy": r["replacedBy"], "statedBy": login(stated) if stated else "",
            "url": issue["html_url"] if issue else "",
            "prUrl": pr["html_url"] if pr else "",
        })

    out_programs = [{
        "id": p["id"], "title": p["title"], "open": p.get("open") is True,
        "goal": p.get("goal", ""), "wanted": p.get("wanted", ""),
        "count": per_program.get(p["id"], {"proved": 0, "refuted": 0, "claimed": 0, "open": 0, "retired": 0}),
    } for p in tree["programs"]]

    open_by_lemma = {}
    for p in open_pulls:
        m = re.search(r"\bL(\d{1,9})\b", p.get("title") or "")
        if m:
            open_by_lemma.setdefault(int(m.group(1)), p)
    out_proposals = []
    for i in sorted(proposals, key=lambda i: i.get("created_at") or "", reverse=True):
        if i.get("state") != "open":
            continue
        pr = open_by_lemma.get(i["number"])
        out_proposals.append({
            "id": f"L{i['number']}",
            "title": re.sub(r"^\s*proposal\s*:?\s*", "", i.get("title") or "", flags=re.I) or "(untitled)",
            "user": login(i), "created_at": i.get("created_at") or "", "url": i["html_url"],
            "prUrl": pr["html_url"] if pr else "",
        })

    # Mandates: lines of work held by an orchestrator. Outcome labels are set
    # only by the mandate workflow or the maintainer.
    out_mandates = []
    for i in sorted(mandates, key=lambda i: i.get("created_at") or "", reverse=True):
        names = labels(i)
        body = i.get("body") or ""
        if i.get("state") == "open":
            state = "active"
        elif "milestone" in names:
            state = "milestone"
        elif "dead" in names:
            state = "dead"
        else:
            state = "closed"
        program = re.search(r"^\s*Program:\s*([a-z0-9-]+)", body, re.M)
        finding = re.search(r"^FINDING:\s*(.+?)\s*$", body, re.M) if state in ("milestone", "dead") else None
        out_mandates.append({
            "number": i["number"],
            "title": re.sub(r"^\s*mandate\s*:?\s*", "", i.get("title") or "", flags=re.I) or "(untitled)",
            "program": program.group(1) if program else "",
            "user": login(i), "state": state,
            "finding": finding.group(1)[:300] if finding else "",
            "barriers": sorted(n.split(":", 1)[1] for n in names if n.startswith("barrier:")),
            "created_at": i.get("created_at") or "", "closed_at": i.get("closed_at") or "",
            "url": i["html_url"],
        })
    count["mandates"] = sum(1 for m in out_mandates if m["state"] == "active")
    count["milestones"] = sum(1 for m in out_mandates if m["state"] == "milestone")
    count["dead"] = sum(1 for m in out_mandates if m["state"] == "dead")

    out_reports = []
    for i in sorted(reports, key=lambda i: i.get("created_at") or "", reverse=True):
        names = labels(i)
        if i.get("state") == "open":
            verdict = "open"
        elif "confirmed" in names:
            verdict = "confirmed"
        elif "dismissed" in names:
            verdict = "dismissed"
        else:
            verdict = "unresolved"
        title = i.get("title") or ""
        m = REPORT_RE.match(title)
        out_reports.append({
            "number": i["number"], "step": m.group(1).upper() if m else "",
            "summary": REPORT_RE.sub("", title) or "(no summary)",
            "verdict": verdict, "user": login(i),
            "created_at": i.get("created_at") or "", "closed_at": i.get("closed_at") or "",
            "url": i["html_url"],
        })

    out_open = [{
        "title": p.get("title") or "", "user": login(p),
        "created_at": p.get("created_at") or "", "url": p["html_url"],
    } for p in sorted(open_pulls, key=lambda p: p.get("created_at") or "", reverse=True)[:MAX_FEED]]

    out_releases = [{
        "name": r.get("name") or r.get("tag_name") or "", "tag": r.get("tag_name") or "",
        "published_at": r.get("published_at") or "", "body": r.get("body") or "",
        "url": r["html_url"],
    } for r in releases if not r.get("draft")][:30]

    count["proposals"] = len(out_proposals)
    return {
        "generated_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": count,
        "openPullCount": len(open_pulls),
        "programs": out_programs,
        "steps": out_steps,
        "people": people,
        "proposals": out_proposals[:MAX_FEED],
        "mandates": out_mandates,
        "barriers": tree.get("barriers", []),
        "openPulls": out_open,
        "reports": out_reports,
        "releases": out_releases,
    }


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GH_TOKEN and GITHUB_REPOSITORY must be set", file=sys.stderr)
        return 2
    status = assemble(
        read_tree(),
        api("/issues?state=all", token, repo),
        api("/pulls?state=closed", token, repo),
        api("/pulls?state=open", token, repo),
        api("/releases", token, repo),
    )
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, separators=(",", ":")))
    print(f"wrote {out}: {len(status['steps'])} steps, {status['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
