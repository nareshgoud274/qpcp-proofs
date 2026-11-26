#!/usr/bin/env python3
"""The site reports verified results only (#113, #114, #133). No network.

    python3 -I tests/test_verification_record.py

Synthetic Git repositories, records and GitHub data; a local bare repository
stands in for the site-data branch. The browser fallback runs the real
docs/assets/site.js under node (CI) or `osascript -l JavaScript` (macOS);
with neither it FAILS, it does not skip.

  1. A new proof file on main while verification is pending: the counts stay
     at the last verified numbers and the new step is "pending".
  2. A failed verification run: no record is built, and the last verified
     record stays the published one and the one the site shows.
  3. A step issue closed as "not planned" with no proof is never "proved",
     with the feed (build_status) and without it (site.js fallback).
  4. An existing record is never overwritten: an identical second run is a
     no-op, a different verdict or digest is a fault; latest.json moves only
     forward along main's history; a commit not on main gets no record.
  5. Every step belongs to a displayed program, and the program counts sum to
     the totals.
  6. The record builder refuses partial runs, missing shards, a missing or
     extra contribution, a blob that is not the file on main, and any verdict
     other than ACCEPTED.
  8. A proof the record lists whose file has since been deleted from main is
     not proved: the counts, overall and per program, drop by one, the step
     keeps "was verified at <commit>" for its page only, and the browser's
     guard takes any verdict without a verified file out of the counts.
  9. Publication: fetch-latest names the site-data commit that added each
     record and the first record that accepted each exact file; the feed's
     citation link is pinned to that commit.
 10. S059's page data, built from the real tree: the definition its one-line
     statement names (source and lines), the pinned citation, and the
     reproduce command with its expected output.
  7. The workflows: the verify job is read-only; only the publish job can
     write, it needs the verify job, is limited to main and runs no Lean; the
     status workflow no longer re-creates or force-pushes site-data.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
GIT_ID = ["-c", "user.name=qpcp-test", "-c", "user.email=qpcp-test@example.invalid", "-c", "commit.gpgsign=false"]


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:400]}"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bs, vr, sd = load("build_status"), load("verification_record"), load("site_data")


def git(cwd, *args):
    r = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def blob_of(data):
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ------------------------------------------------------------ synthetic data

STATEMENTS = "namespace QPCP.Statement\n\n/-- One. -/\ndef S001 : Prop := True\n\n/-- Two. -/\ndef S002 : Prop := True\n\nend QPCP.Statement\n"
PROOF = "import QPCP.Statements\n\nnamespace QPCP.Proof\n\ntheorem {i} : QPCP.Statement.{i} := trivial\n\nend QPCP.Proof\n"
MATHLIB = "a" * 40


def make_main(base):
    """A repository with S001 proved; returns (path, commit)."""
    repo = base / "main"
    (repo / "QPCP" / "Proofs").mkdir(parents=True)
    (repo / "QPCP" / "Statements.lean").write_text(STATEMENTS)
    (repo / "QPCP" / "Proofs" / "S001.lean").write_text(PROOF.format(i="S001"))
    # Not contributions: as on main.
    (repo / "QPCP" / "Proofs" / "README.md").write_text("Proofs go here.\n")
    (repo / "QPCP" / "Lemmas").mkdir(parents=True)
    (repo / "QPCP" / "Lemmas" / ".gitkeep").write_text("")
    (repo / "lean-toolchain").write_text("leanprover/lean4:v4.36.0\n")
    (repo / "lake-manifest.json").write_text(json.dumps({"packages": [{"name": "mathlib", "rev": MATHLIB}]}))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c1")
    return repo, git(repo, "rev-parse", "HEAD")


def evidence_for(repo, sha, verdict="ACCEPTED", digest="d" * 64, **mode):
    items = []
    for line in git(repo, "ls-tree", "-r", sha, "--", "QPCP/Proofs").splitlines():
        meta, path = line.split("\t", 1)
        if not path.endswith(".lean"):
            continue
        ident = Path(path).stem
        items.append({"kind": "proof", "id": ident, "declaration": f"QPCP.Proof.{ident}", "path": path,
                      "blob": meta.split()[2], "verdict": verdict, "statementDigest": digest,
                      "dependsOn": ["QPCP.Config"]})
    doc = {"format": 1, "only": None, "shard": [1, 1], "replayOnly": False, "items": items}
    doc.update(mode)
    return doc


def record_for(repo, sha, url="https://github.com/o/r/actions/runs/1/attempts/1", **kw):
    return vr.build_record([evidence_for(repo, sha, **kw)], repo, sha, url, 1)


def steps_json(*ids):
    return [{"id": i, "title": f"Step {i}", "section": "S", "difficulty": 1, "deps": [], "program": "foundations"}
            for i in ids]


def tree_with(proofs, commit="c" * 40, steps=None):
    return {"steps": steps or steps_json("S001", "S002", "S003"),
            "programs": [{"id": "foundations", "title": "Foundations", "open": True}],
            "retired": set(), "barriers": [], "lemmas": [], "proofs": proofs, "refutations": {}, "commit": commit}


def issue(n, ident, state="open", reason=None, labels=("step",)):
    return {"number": n, "title": f"{ident}: x", "state": state, "state_reason": reason,
            "labels": [{"name": l} for l in labels], "html_url": f"https://example.invalid/issues/{n}",
            "assignees": []}


def status(tree, record, issues=()):
    return bs.assemble(tree, list(issues), [], [], [], record=record)


def by_id(doc):
    return {s["id"]: s for s in doc["steps"]}


# ------------------------------------------------------------ the browser fallback

def run_js(expr):
    """Evaluate site.js and then `expr` (which yields a JSON string); returns the parsed value."""
    site = (ROOT / "docs" / "assets" / "site.js").read_text()
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "-e", "var window = {};\n" + site + "\nconsole.log(" + expr + ");"],
                           capture_output=True, text=True, timeout=60)
    elif shutil.which("osascript"):
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", "var window = {};\n" + site + "\n" + expr + ";"],
                           capture_output=True, text=True, timeout=60)
    else:
        raise RuntimeError("no JavaScript runtime (node or osascript): the fallback test cannot run")
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return json.loads(r.stdout.strip())


def main():
    base = Path(tempfile.mkdtemp(prefix="qpcp-records-"))
    try:
        repo, c1 = make_main(base)
        rec1 = record_for(repo, c1)
        b1 = rec1["evidence"]["items"][0]["blob"]
        check("the record for a fully accepted run is built from the tree at its commit",
              rec1["evidence"]["commit"] == c1 and rec1["evidence"]["mathlib"] == MATHLIB
              and rec1["evidence"]["items"][0]["statementLine"] == 4)

        # 1. A new proof on main, not yet verified.
        tree = tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": b1},
                          "S002": {"path": "QPCP/Proofs/S002.lean", "blob": blob_of(b"new")}}, commit="f" * 40)
        doc = status(tree, rec1)
        steps = by_id(doc)
        check("1. counts stay at the last verified numbers (1 proved)", doc["count"]["proved"] == 1, doc["count"])
        check("1. the new proof is pending verification, not proved",
              steps["S002"]["status"] == "pending" and doc["count"]["pending"] == 1, steps["S002"])
        check("1. the verified step names its commit and run",
              steps["S001"]["verified"]["commit"] == c1 and steps["S001"]["verified"]["runUrl"].endswith("/attempts/1"))
        check("1. the feed says the newest commit is not verified",
              doc["verification"]["commit"] == c1 and doc["verification"]["current"] is False)
        tampered = tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": blob_of(b"changed")}})
        check("1. a file whose bytes differ from the verified blob is pending, not proved",
              by_id(status(tampered, rec1))["S001"]["status"] == "pending")

        # 8. The same record, after S001's file was deleted from main.
        kept = status(tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": b1}}), rec1)
        gone = status(tree_with({}), rec1)
        s1 = by_id(gone)["S001"]
        check("8. a deleted proof is not proved, though the record lists it",
              s1["status"] == "open" and s1["verified"] is None, s1)
        check("8. the overall count drops by one when the file is deleted",
              kept["count"]["proved"] == 1 and gone["count"]["proved"] == 0, (kept["count"], gone["count"]))
        check("8. the program's count drops by one too",
              kept["programs"][0]["count"]["proved"] == 1 and gone["programs"][0]["count"]["proved"] == 0,
              (kept["programs"][0]["count"], gone["programs"][0]["count"]))
        check("8. the step keeps 'was verified at <commit>' for its page, and nothing else",
              s1["formerlyVerified"] == {"status": "proved", "commit": c1, "path": "QPCP/Proofs/S001.lean", "blob": b1,
                                         "record": f"records/{c1}.json", "runUrl": rec1["run"]["url"]}
              and by_id(kept)["S001"]["formerlyVerified"] is None, s1["formerlyVerified"])
        check("8. no credit is given for the deleted proof", gone["people"] == {}, gone["people"])
        ok = run_js("JSON.stringify(window.QPCP._enforceVerified(" + json.dumps(gone) + ").count)")
        check("8. browser: the guard leaves a consistent feed's counts alone", ok == gone["count"], ok)
        forged = json.loads(json.dumps(kept))
        forged["steps"][0]["verified"] = None  # "proved", but no verified file named
        js = run_js("JSON.stringify((function () { var d = window.QPCP._enforceVerified(" + json.dumps(forged) + ");"
                    " return { s: d.steps[0].status, n: d.count.proved, p: d.programs[0].count.proved }; })())")
        check("8. browser: a verdict without a verified file is shown as unknown and leaves both counts",
              js == {"s": "unknown", "n": 0, "p": 0}, js)

        # Site-data stand-in: a bare repository, and main's history for ancestry.
        remote = base / "site-data.git"
        git(base, "init", "-q", "--bare", str(remote))
        git(repo, "update-ref", "refs/remotes/origin/main", c1)
        is_anc = sd.ancestry(repo)

        def publish(record):
            return sd.write_with_retry(str(remote), lambda d: sd.apply_record(d, record, is_anc), "test")

        def remote_file(path):
            r = subprocess.run(["git", "--git-dir", str(remote), "show", f"site-data:{path}"],
                               capture_output=True, text=True)
            return r.stdout if r.returncode == 0 else None

        check("4. the first record is published", publish(rec1) is True)
        latest = json.loads(remote_file("latest.json"))
        check("4. latest.json points at it", latest["commit"] == c1 and latest["record"] == f"records/{c1}.json")

        # 2. A failed run on a later commit.
        (repo / "QPCP" / "Proofs" / "S002.lean").write_text(PROOF.format(i="S002"))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "c2")
        c2 = git(repo, "rev-parse", "HEAD")
        git(repo, "update-ref", "refs/remotes/origin/main", c2)
        try:
            record_for(repo, c2, verdict="REJECTED")
            check("2. a run that rejected something yields no record", False, "built")
        except vr.Fault as e:
            check(f"2. a run that rejected something yields no record ({e})", "REJECTED" in str(e))
        check("2. the last verified record stays published", json.loads(remote_file("latest.json"))["commit"] == c1)
        out = base / "fetched.json"
        sd.cmd_fetch_latest(str(remote), str(out))
        fetched = json.loads(out.read_text())
        doc = status(tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": b1},
                                "S002": {"path": "QPCP/Proofs/S002.lean", "blob": blob_of(PROOF.format(i="S002").encode())}},
                               commit=c2), fetched)
        check("2. the site keeps showing the last verified record, with its commit and date",
              doc["verification"]["commit"] == c1 and doc["verification"]["verifiedAt"] == rec1["verifiedAt"]
              and doc["count"]["proved"] == 1 and by_id(doc)["S002"]["status"] == "pending")

        # 4. Immutability, and latest.json only moving forward.
        again = record_for(repo, c1, url="https://github.com/o/r/actions/runs/2/attempts/1")
        before = remote_file(f"records/{c1}.json")
        check("4. a second run with identical evidence changes nothing", publish(again) is False
              and remote_file(f"records/{c1}.json") == before)
        for desc, rec in (("verdict-relevant digest", record_for(repo, c1, digest="e" * 64)),):
            try:
                publish(rec)
                check(f"4. a second run with a different {desc} is a fault", False, "published")
            except sd.Fault as e:
                check(f"4. a second run with a different {desc} is a fault ({str(e)[:60]}...)", "never overwritten" in str(e))
        changed = json.loads(json.dumps(rec1))
        changed["evidence"]["items"][0]["verdict"] = "REJECTED"
        try:
            publish(changed)
            check("4. a second run with a different verdict is a fault", False, "published")
        except sd.Fault:
            check("4. a second run with a different verdict is a fault", True)
        check("4. the existing record is unchanged", remote_file(f"records/{c1}.json") == before)
        rec2 = record_for(repo, c2)
        publish(rec2)
        check("4. latest.json moves to a descendant", json.loads(remote_file("latest.json"))["commit"] == c2)
        publish(again)
        check("4. publishing an older commit's record does not move latest.json back",
              json.loads(remote_file("latest.json"))["commit"] == c2)
        log = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline", "site-data"],
                             capture_output=True, text=True).stdout.splitlines()
        check(f"4. site-data keeps its history ({len(log)} commits)", len(log) == 2, log)

        # 9. Publication data, from site-data's own history.
        def added_in(path):
            return subprocess.run(["git", "--git-dir", str(remote), "log", "--diff-filter=A", "--format=%H",
                                   "site-data", "--", path], capture_output=True, text=True).stdout.strip()
        sd.cmd_fetch_latest(str(remote), str(out))
        fetched = json.loads(out.read_text())
        pub = fetched["publication"]
        check("9. fetch-latest names the site-data commit that added the latest record",
              pub["recordCommit"] == added_in(f"records/{c2}.json") != "", pub["recordCommit"])
        check("9. S001's file is unchanged since c1: first verified at c1, in the commit that added c1's record",
              [(f["commit"], f["recordCommit"]) for f in pub["firstVerified"]["proof:S001"]]
              == [(c1, added_in(f"records/{c1}.json"))], pub["firstVerified"])
        check("9. S002 first verified at c2", [f["commit"] for f in pub["firstVerified"]["proof:S002"]] == [c2])
        check("9. the record's own bytes are unchanged by fetching", "publication" not in json.loads(remote_file(f"records/{c2}.json")))
        b2 = blob_of(PROOF.format(i="S002").encode())
        doc = bs.assemble(tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": b1},
                                     "S002": {"path": "QPCP/Proofs/S002.lean", "blob": b2}}, commit=c2),
                          [], [], [], [], record=fetched, repo="o/r")
        v1 = by_id(doc)["S001"]["verified"]
        check("9. the citation link is pinned to the site-data commit that published the record",
              v1["citeUrl"] == f"https://raw.githubusercontent.com/o/r/{pub['recordCommit']}/records/{c2}.json", v1["citeUrl"])
        check("9. the page's first verification is c1, with its own pinned record",
              v1["firstVerified"]["commit"] == c1 and v1["firstVerified"]["recordUrl"]
              == f"https://raw.githubusercontent.com/o/r/{added_in(f'records/{c1}.json')}/records/{c1}.json", v1["firstVerified"])
        git(repo, "checkout", "-q", "-b", "side", c1)
        (repo / "x.txt").write_text("x")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "side")
        side = git(repo, "rev-parse", "HEAD")
        side_rec = record_for(repo, side)
        (base / "side.json").write_text(json.dumps(side_rec))
        try:
            sd.cmd_publish_record(str(base / "side.json"), str(remote), str(repo))
            check("4. a commit that is not on main gets no record", False, "published")
        except sd.Fault as e:
            check("4. a commit that is not on main gets no record", "not on main" in str(e), e)
        check("4. ...and nothing was written for it", remote_file(f"records/{side}.json") is None)
        git(repo, "checkout", "-q", "main")

        # 3. A step issue closed as not planned, with no proof.
        closed = [issue(3, "S003", state="closed", reason="not_planned")]
        for desc, rec in (("with the feed and a record", rec1), ("with the feed and no record", None)):
            s3 = by_id(status(tree_with({"S001": {"path": "QPCP/Proofs/S001.lean", "blob": b1}}), rec, closed))["S003"]
            check(f"3. a closed, not-planned issue is not proved ({desc}): {s3['status']}", s3["status"] != "proved")
        js = run_js("JSON.stringify((function () { var d = window.QPCP._buildFromApi(" + json.dumps(steps_json("S001", "S003")) +
                    ", " + json.dumps([issue(3, "S003", state="closed", reason="not_planned"),
                                       issue(1, "S001", state="closed", reason="completed")]) +
                    ", [], []); return { s: d.steps.map(function (x) { return x.status; }), proved: d.count.proved, v: d.verification.available }; })())")
        check(f"3. without the feed, no closed issue is shown as proved ({js})",
              js["proved"] == 0 and "proved" not in js["s"] and js["s"] == ["unknown", "unknown"] and js["v"] is False, js)
        line = run_js("JSON.stringify(window.QPCP.verificationLine({ available: false }))")
        check("3. without the feed the site says verification status is unavailable", "unavailable" in line, line)

        # 5. Programs.
        real = bs.read_tree(ROOT)
        ids = {p["id"] for p in real["programs"]}
        missing = [s["id"] for s in real["steps"] if s.get("program") not in ids]
        check(f"5. every step names a displayed program ({len(real['steps'])} steps)", not missing, missing)
        fake = {"format": 1, "run": {"url": "u", "attempt": 1}, "verifiedAt": "t", "evidence": {
            "commit": real["commit"], "toolchain": "", "mathlib": "", "items": [
                {"kind": "proof", "id": i, "declaration": f"QPCP.Proof.{i}", "path": f["path"], "blob": f["blob"],
                 "verdict": "ACCEPTED", "statementDigest": "d" * 64, "dependsOn": [],
                 "statementPath": "QPCP/Statements.lean", "statementLine": 1}
                for i, f in sorted(real["proofs"].items())]}}
        doc = bs.assemble(real, [], [], [], [], record=fake)
        for key in ("proved", "refuted", "pending", "claimed", "open", "retired"):
            total = sum(p["count"][key] for p in doc["programs"])
            check(f"5. program counts sum to the total: {key} {total} = {doc['count'][key]}", total == doc["count"][key])
        check(f"5. with every proof on main verified, {doc['count']['proved']} proved and none pending",
              doc["count"]["proved"] == len(real["proofs"]) and doc["count"]["pending"] == 0)

        # 10. S059's page data, from a record built from the real tree at HEAD.
        head = git(ROOT, "rev-parse", "HEAD")
        contribs = vr.tree_contributions(ROOT, head)
        kinds = {v: k for k, v in vr.KINDS.items()}
        items = [{"kind": kinds[str(Path(p).parent)], "id": Path(p).stem,
                  "declaration": f"{vr.DECL_NS[kinds[str(Path(p).parent)]]}.{Path(p).stem}", "path": p, "blob": b,
                  "verdict": "ACCEPTED", "statementDigest": "d" * 64, "dependsOn": []} for p, b in contribs.items()]
        real_rec = vr.build_record([{"format": 1, "only": None, "shard": [1, 1], "replayOnly": False, "items": items}],
                                   ROOT, head, "https://github.com/o/r/actions/runs/1/attempts/1", 1)
        s059_blob = contribs["QPCP/Proofs/S059.lean"]
        real_rec["publication"] = {"recordCommit": "b" * 40, "firstVerified": {"proof:S059": [
            {"path": "QPCP/Proofs/S059.lean", "blob": s059_blob, "commit": head, "verifiedAt": "t",
             "record": f"records/{head}.json", "recordCommit": "b" * 40}]}}
        page = by_id(bs.assemble(bs.read_tree(ROOT), [], [], [], [], record=real_rec, repo="nareshgoud274/qpcp-proofs"))
        v59 = page["S059"]["verified"] or {}
        d59 = v59.get("statementDefinition") or {}
        check("10. S059: the definition its statement names, with its source and lines",
              d59.get("name") == "QPCP.Promise.BoolGroundEnergy" and d59.get("path") == "QPCP/Promise.lean"
              and "def BoolGroundEnergy : Prop :=" in d59.get("source", "") and d59.get("line", 0) <= d59.get("endLine", -1), d59)
        promise = (ROOT / "QPCP" / "Promise.lean").read_text().splitlines()
        check("10. S059: those lines are the definition's source in QPCP/Promise.lean at the verified commit",
              d59 and "\n".join(promise[d59["line"] - 1:d59["endLine"]]) == d59["source"])
        check("10. S060, a statement written out in full, names no definition",
              (page["S060"]["verified"] or {}).get("statementDefinition", "x") is None)
        check("10. S059: the citation is pinned to the publishing site-data commit",
              v59.get("citeUrl") == f"https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/{'b' * 40}/records/{head}.json", v59.get("citeUrl"))
        check("10. S059: the reproduce command and its expected output",
              v59.get("reproduce") == {"command": "python3 -I scripts/sandbox_verify.py record --only QPCP.Proofs.S059",
                                       "expect": "ACCEPTED: proof S059", "commit": head}, v59.get("reproduce"))
        check("10. S059: the first verification of this exact file", (v59.get("firstVerified") or {}).get("blob") == s059_blob)

        # 6. The builder refuses anything but a complete, accepted run at the commit.
        cases = [
            ("an --only run", [evidence_for(repo, c2, only=["QPCP.Proofs.S001"])], "partial"),
            ("a replay-only run", [evidence_for(repo, c2, replayOnly=True)], "replay-only"),
            ("one shard of two", [evidence_for(repo, c2, shard=[1, 2])], "do not cover"),
            ("a missing contribution", [dict(evidence_for(repo, c2), items=evidence_for(repo, c2)["items"][:1])], "missing"),
            ("a blob that is not the file on main",
             [dict(evidence_for(repo, c2), items=[dict(i, blob="0" * 40) for i in evidence_for(repo, c2)["items"]])], "verified bytes"),
            ("a wrong declaration",
             [dict(evidence_for(repo, c2), items=[dict(i, declaration="QPCP.Proof.X") for i in evidence_for(repo, c2)["items"]])], "declaration"),
        ]
        for desc, docs, want in cases:
            try:
                vr.build_record(docs, repo, c2, "u", 1)
                check(f"6. refuses {desc}", False, "built")
            except vr.Fault as e:
                check(f"6. refuses {desc}", want in str(e), e)

        # 7. The workflows.
        vm = (ROOT / ".github" / "workflows" / "verify-main.yml").read_text()
        jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", vm.split("\njobs:\n", 1)[1]))
        check("7. verify-main: the workflow default is read-only", re.search(r"(?m)^permissions:\n  contents: read$", vm))
        check("7. verify-main: the verify job asks for no write permission", "write" not in jobs.get("verify", "write"))
        pub = jobs.get("publish", "")
        check("7. verify-main: only the publish job can write, and it needs verify",
              "contents: write" in pub and re.search(r"(?m)^    needs: verify$", pub) is not None
              and sum("write" in body for body in jobs.values()) == 1)
        check("7. verify-main: publish runs on main only and never with always()",
              "github.ref == 'refs/heads/main'" in pub and "always()" not in pub)
        check("7. verify-main: publish runs no Lean, lake, elan or sandbox",
              not re.search(r"\b(lake|lean|elan|bwrap|install_sandbox|install_elan|sandbox_verify)\b", pub))
        st = (ROOT / ".github" / "workflows" / "status.yml").read_text()
        check("7. status: site-data is no longer re-created or force-pushed",
              "git init" not in st and not re.search(r"git push[^\n]*(\s-f\b|--force)", st))
        sdp = (ROOT / "scripts" / "site_data.py").read_text()
        check("7. site_data.py never force-pushes",
              not re.search(r'"push"[^\n]*("-f"|"--force"|\+HEAD)', sdp) and '"push", "-q", "origin", f"HEAD:' in sdp)
        check("7. status: rebuilds when verify-main completes", "workflow_run" in st and "verify-main" in st)
    except Exception as e:  # a crash is a failure, never a skip
        check("crashed", False, f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f"failed {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
