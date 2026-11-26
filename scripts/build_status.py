#!/usr/bin/env python3
"""Build status.json, the single file the project site reads.

Runs in GitHub Actions on a checkout of main, with GH_TOKEN and
GITHUB_REPOSITORY set. It combines:

  * the latest verification record (scripts/verification_record.py), the only
    source of "proved" and "refuted": a result counts when the record lists it
    as ACCEPTED with the same path and Git blob as the file on main. A proof or
    refutation file on main that no successful record covers is "pending"
    (pending verification) and is not counted as proved. The feed names the
    verified commit and run for each result, and for the record as a whole;
  * the working tree: steps.json, programs.json, retired.json, and the files
    under QPCP/Lemmas, QPCP/Proofs and QPCP/Refutations (with their Git blobs);
  * the GitHub API: issues (claims, reports, proposals), pull requests
    (credit, work in the checker) and releases (updates). These update
    immediately; only verdicts wait for verification.

For agents (#117), each step also carries its difficulty, its prerequisites
with their current states, its active claim, and, when it is open or claimed,
a submission card made from its own issue number (submission_card); each open
proposal carries a statement card (statement_card).

Visitors' browsers fetch only the resulting file, so the site keeps working
however many people are watching and however large the record grows.

Usage: build_status.py <output-path> <record.json>
"""

import json
import os
import re
import subprocess
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


def git_files(root, folder):
    """{id: {"path", "blob"}} for the committed files of one contribution folder at HEAD."""
    r = subprocess.run(["git", "-C", str(root), "ls-tree", "HEAD", "--", folder + "/"],
                       capture_output=True, text=True, check=True)
    out = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        if path.endswith(".lean"):
            out[Path(path).stem] = {"path": path, "blob": meta.split()[2]}
    return out


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
        "reviewers": load("reviewers.json", []),
        "barriers": load("barriers.json", []),
        "lemmas": lemmas,
        "proofs": git_files(root, "QPCP/Proofs"),
        "refutations": git_files(root, "QPCP/Refutations"),
        "commit": subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                 text=True, check=True).stdout.strip(),
    }


def record_url(sha):
    return f"records/{sha}.json"


def submission_card(sid, issue_number):
    """What a volunteer copies to submit a proof or refutation of `sid`.

    Built only from the step's id and the number of its own issue, never from a
    guess: a founding step's issue number is unrelated to its id (S060 is #146).
    """
    if sid.startswith("S"):
        statement, source, imp = f"QPCP.Statement.{sid}", "QPCP/Statements.lean", "QPCP.Statements"
    else:
        statement, source, imp = f"QPCP.Lemma.{sid}", f"QPCP/Lemmas/{sid}.lean", f"QPCP.Lemmas.{sid}"
    closes = f"Closes #{issue_number}"
    card = {"id": sid, "issue": issue_number, "statement": statement, "statementSource": source,
            "import": imp, "closes": closes}
    lines = [f"{sid}  (issue #{issue_number})",
             f"statement   {statement}   in {source}",
             f"import      import {imp}   (and any merged QPCP.Proofs.<ID> it uses)"]
    for kind, folder, ns, verb, typ in (
            ("proof", "QPCP/Proofs", "QPCP.Proof", "Prove", statement),
            ("refutation", "QPCP/Refutations", "QPCP.Refutation", "Refute", f"¬ {statement}")):
        k = {"path": f"{folder}/{sid}.lean", "declaration": f"{ns}.{sid}", "type": typ,
             "build": f"lake build {folder.replace('/', '.')}.{sid}", "title": f"{verb} {sid}"}
        card[kind] = k
        lines += ["", f"{kind}:",
                  f"  file      {k['path']}",
                  f"  theorem   {k['declaration']} : {typ}",
                  f"  build     {k['build']}",
                  f"  PR title  {k['title']}",
                  f"  PR body   {closes}"]
    card["text"] = "\n".join(lines)
    return card


def statement_card(number):
    """What a proposer copies to submit the statement for proposal issue #number.

    The lemma id is the issue's number by definition, and the issue stays open
    after the statement merges, for someone to prove or refute: no "Closes".
    """
    sid = f"L{number}"
    card = {"id": sid, "issue": number, "path": f"QPCP/Lemmas/{sid}.lean", "declaration": f"QPCP.Lemma.{sid}",
            "build": f"lake build QPCP.Lemmas.{sid}", "title": f"State {sid}", "body": f"Proposal #{number}"}
    card["text"] = "\n".join([
        f"{sid}  (proposal issue #{number}; it stays open: do not write Closes)",
        f"  file      {card['path']}",
        f"  def       {card['declaration']} : Prop",
        f"  build     {card['build']}",
        f"  PR title  {card['title']}",
        f"  PR body   {card['body']}"])
    return card


def verified_results(record):
    """{(kind, id): item} for every ACCEPTED proof and refutation in the record."""
    out = {}
    for it in (record or {}).get("evidence", {}).get("items", []):
        if it.get("verdict") == "ACCEPTED" and it.get("kind") in ("proof", "refutation"):
            out[(it["kind"], it["id"])] = it
    return out


def assemble(tree, issues, closed_pulls, open_pulls, releases, now=None, record=None):
    """Pure function: the tree, raw GitHub data and the latest verification record in,
    the status document out."""
    verified = verified_results(record)
    rec_commit = (record or {}).get("evidence", {}).get("commit", "")
    rec_run = (record or {}).get("run", {})
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
        "id": s["id"], "title": s["title"], "section": s["section"], "program": s.get("program", ""),
        "retired": s.get("retired") is True, "replacedBy": s.get("replaced_by", ""),
        "exercise": s.get("exercise") is True,
        "difficulty": s.get("difficulty"), "deps": list(s.get("deps", [])),
        "background": list(s.get("background", [])),
    } for s in tree["steps"]]
    rows += [{
        "id": l["id"], "title": l["title"], "program": l["program"],
        "section": program_title.get(l["program"], l["program"] or "Other"),
        "retired": False, "replacedBy": "", "exercise": False,
        "difficulty": None, "deps": [], "background": [],
    } for l in tree["lemmas"]]

    people = {}

    def give(who, kind, sid):
        if who:
            people.setdefault(who, {"proved": [], "refuted": [], "stated": []})[kind].append(sid)

    count = {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0, "disputed": 0,
             "humanReviewed": 0}
    per_program, out_steps = {}, []
    for r in rows:
        sid = r["id"]
        issue = step_issue.get(sid) or (by_number.get(int(sid[1:])) if sid.startswith("L") else None)
        names = labels(issue) if issue else set()
        status, who, when, pr, ver, claim = "open", "", "", None, None, None
        # A verdict comes only from the record, and only for the bytes on main.
        for kind, done in (("proof", "proved"), ("refutation", "refuted")):
            it = verified.get((kind, sid))
            on_main = tree["proofs" if kind == "proof" else "refutations"].get(sid)
            if it and (on_main is None or (on_main["path"], on_main["blob"]) == (it["path"], it["blob"])):
                ver = (done, it)
        on_main = tree["proofs"].get(sid) or tree["refutations"].get(sid)
        if r["retired"] or sid in tree["retired"] or "retired" in names:
            status = "retired"
            when = (issue or {}).get("closed_at") or ""
        elif ver:
            status = ver[0]
            pr = credit.get((status, sid))
        elif on_main:
            status = "pending"
            pr = credit.get(("proved" if sid in tree["proofs"] else "refuted", sid))
        elif "claimed" in names:
            status = "claimed"
            who = ", ".join(a["login"] for a in issue.get("assignees", []))
            when = issue.get("updated_at") or ""
            # A claim lapses 24 hours after the issue's last comment (claim.yml).
            claim = {"by": [a["login"] for a in issue.get("assignees", [])], "lastActivity": when}
        if status in ("proved", "refuted", "pending"):
            who = login(pr) if pr else ""
            when = (pr or {}).get("merged_at") or ""
        if status in ("proved", "refuted"):
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
        tally = per_program.setdefault(r["program"], {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0})
        tally[status] += 1
        out_steps.append({
            "id": sid, "title": r["title"], "section": r["section"], "program": r["program"],
            "status": status, "who": who, "when": when, "disputed": disputed, "reviewed": reviewed,
            "replacedBy": r["replacedBy"], "statedBy": login(stated) if stated else "",
            "exercise": r["exercise"], "difficulty": r["difficulty"],
            # Filled in below, once every step's status is known.
            "deps": r["deps"], "background": r["background"],
            "claim": claim,
            # Only for work that can be submitted now, and only with the step's own issue.
            "submission": submission_card(sid, issue["number"]) if issue and status in ("open", "claimed") else None,
            "issue": issue["number"] if issue else None,
            "url": issue["html_url"] if issue else "",
            "prUrl": pr["html_url"] if pr else "",
            "verified": None if not ver else {
                "commit": rec_commit, "runUrl": rec_run.get("url", ""), "record": record_url(rec_commit),
                "declaration": ver[1]["declaration"], "path": ver[1]["path"], "blob": ver[1]["blob"],
                "statementPath": ver[1]["statementPath"], "statementLine": ver[1]["statementLine"],
                "statementDigest": ver[1]["statementDigest"], "dependsOn": ver[1]["dependsOn"],
            },
        })

    # Prerequisites with their current state (#117): `deps` are the steps a proof
    # uses; `background` steps are worth reading first but a proof does not need them.
    state_of = {s["id"]: s["status"] for s in out_steps}
    for s in out_steps:
        s["deps"] = [{"id": d, "status": state_of.get(d, "unknown")} for d in s["deps"]]
        s["background"] = [{"id": d, "status": state_of.get(d, "unknown")} for d in s["background"]]

    out_programs = [{
        "id": p["id"], "title": p["title"], "open": p.get("open") is True,
        "goal": p.get("goal", ""), "wanted": p.get("wanted", ""),
        "count": per_program.get(p["id"], {"proved": 0, "refuted": 0, "pending": 0, "claimed": 0, "open": 0, "retired": 0}),
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
            "submission": statement_card(i["number"]),
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
        # Verdicts are as of this verified commit; `current` says whether it is main's newest.
        "verification": {
            "available": bool(record), "commit": rec_commit, "verifiedAt": (record or {}).get("verifiedAt", ""),
            "runUrl": rec_run.get("url", ""), "runAttempt": rec_run.get("attempt", 0),
            "record": record_url(rec_commit) if record else "",
            "toolchain": (record or {}).get("evidence", {}).get("toolchain", ""),
            "mathlib": (record or {}).get("evidence", {}).get("mathlib", ""),
            "mainCommit": tree.get("commit", ""), "current": bool(record) and rec_commit == tree.get("commit"),
        },
        # What can be accepted today (#134): proofs and refutations of open steps
        # always; a new statement only once a listed reviewer approves it.
        "accepting": {"proofs": True, "refutations": True, "statementReviewers": len(tree.get("reviewers", []))},
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
    if len(argv) != 3:
        print(__doc__)
        return 2
    record = json.loads(Path(argv[2]).read_text())
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
        record=record,
    )
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, separators=(",", ":")))
    print(f"wrote {out}: {len(status['steps'])} steps, {status['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
