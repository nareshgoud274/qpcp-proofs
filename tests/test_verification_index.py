#!/usr/bin/env python3
"""The verification index on site-data (#155 review, 1b). No network.

    python3 -I tests/test_verification_index.py

index.json lists, for each exact file (kind, id, Git blob), every commit of
main at which a record accepted it, ordered by position on main, with the first
and the last. "Formerly verified" and "first verified" are read from it.
Synthetic main repositories; local bare repositories stand in for site-data.

  1. The real sequence: record A has the proof; the file is deleted; record B
     is published without it. Before and after B the step is not proved,
     "formerly verified at A" remains, and its pinned citation resolves to
     record A's bytes.
  2. Backfill: records already on site-data without an index get one on the
     next publication, with their history; rebuilding the index from the
     records gives the same index (and `check-index` agrees).
  3. Idempotent retries: publishing the same record twice changes nothing.
  4. Out-of-order publication: an older commit's record published after a
     newer one leaves first and last ordered by position on main.
  5. Atomic update: every site-data commit that adds a record also writes
     index.json; when the push is rejected, the whole update is redone from
     the new tip, and both records end up in the index.
  6. Display is not evidence (#155 review 2): one commit published once with
     Lean's location for a one-name statement and once with the text fallback,
     in both orders, is a no-op the second time, and the page still shows the
     definition.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:500]}"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t = load("vr_fixtures", ROOT / "tests" / "test_verification_record.py")  # its fixtures; nothing runs on import
bs, sd = t.bs, t.sd
git = t.git


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", sha)
    return sha


def bare(base, name):
    remote = base / name
    git(base, "init", "-q", "--bare", str(remote))
    return remote


def show(remote, ref, path):
    r = subprocess.run(["git", "--git-dir", str(remote), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def log(remote):
    r = subprocess.run(["git", "--git-dir", str(remote), "log", "--format=%H %s", "site-data"], capture_output=True, text=True)
    return r.stdout.split("\n") if r.stdout.strip() else []


def files_in(remote, sha):
    r = subprocess.run(["git", "--git-dir", str(remote), "show", "--name-only", "--format=", sha], capture_output=True, text=True)
    return set(r.stdout.split())


def publish(remote, repo, record, base):
    path = base / f"rec-{record['evidence']['commit'][:7]}.json"
    path.write_text(json.dumps(record))
    sd.cmd_publish_record(str(path), str(remote), str(repo))


def fetch(remote, base, repo=None):
    out = base / "fetched.json"
    out.unlink(missing_ok=True)
    sd.cmd_fetch_latest(str(remote), str(out), str(repo) if repo else None)
    return json.loads(out.read_text())


def clone(remote, into):
    subprocess.run(["git", "clone", "-q", "--branch", "site-data", str(remote), str(into)], check=True, capture_output=True)
    return into


def main():
    print("The verification index on site-data")
    base = Path(tempfile.mkdtemp(prefix="qpcp-index-"))
    try:
        repo, c1 = t.make_main(base)
        git(repo, "update-ref", "refs/remotes/origin/main", c1)
        rec_a = t.record_for(repo, c1)
        b1 = rec_a["evidence"]["items"][0]["blob"]

        # 1. The real sequence.
        remote = bare(base, "site-data.git")
        publish(remote, repo, rec_a, base)
        (repo / "QPCP" / "Proofs" / "S001.lean").unlink()
        c2 = commit(repo, "remove S001's proof")
        gone = t.tree_with({}, commit=c2)

        def page(fetched):
            doc = bs.assemble(gone, [], [], [], [], record=fetched, repo="o/r")
            return t.by_id(doc)["S001"], doc

        before, doc_before = page(fetch(remote, base))
        rec_b = t.record_for(repo, c2)
        check("1. record B has no item for the deleted file", rec_b["evidence"]["items"] == [], rec_b["evidence"]["items"])
        publish(remote, repo, rec_b, base)
        fetched_b = fetch(remote, base)
        after, doc_after = page(fetched_b)
        check("1. latest.json is record B", fetched_b["evidence"]["commit"] == c2)
        for when, s1, doc in (("before B", before, doc_before), ("after B", after, doc_after)):
            check(f"1. {when}: the step is not proved and not counted",
                  s1["status"] == "open" and s1["verified"] is None and doc["count"]["proved"] == 0, s1["status"])
            fv = s1["formerlyVerified"] or {}
            check(f"1. {when}: 'formerly verified at A' remains", fv.get("commit") == c1 and fv.get("blob") == b1, fv)
        url = (after["formerlyVerified"] or {}).get("recordUrl", "")
        pinned = url.split("/o/r/", 1)[-1].split("/", 1) if url else ["", ""]
        check("1. its citation is pinned to the site-data commit that added record A",
              url == f"https://raw.githubusercontent.com/o/r/{pinned[0]}/records/{c1}.json" and pinned[0] != "", url)
        check("1. ...and that pinned link resolves to record A's bytes",
              pinned[0] and show(remote, pinned[0], f"records/{c1}.json") == show(remote, "site-data", f"records/{c1}.json")
              and json.loads(show(remote, pinned[0], f"records/{c1}.json"))["evidence"] == rec_a["evidence"])

        # 2. Backfill: records A and B on a site-data branch that has no index yet.
        old = bare(base, "old-site-data.git")
        for rec in (rec_a, rec_b):
            sd.write_with_retry(str(old), lambda d, rec=rec: sd.apply_record(d, rec, sd.ancestry(repo)), "pre-index record")
        check("2. before: records, no index", show(old, "site-data", "index.json") is None
              and show(old, "site-data", f"records/{c1}.json") is not None)
        no_index = fetch(old, base, repo)
        check("2. without index.json, fetch-latest (given the repository) builds it from the records",
              (no_index["publication"]["index"] or {}).get("entries", {}).get(f"proof:S001:{b1}", {}).get("first", {}).get("commit") == c1,
              no_index["publication"]["index"])
        (repo / "QPCP" / "Proofs" / "S001.lean").write_text(t.PROOF.format(i="S001"))
        c3 = commit(repo, "S001's proof again, same bytes")
        rec_c = t.record_for(repo, c3)
        publish(old, repo, rec_c, base)
        index = json.loads(show(old, "site-data", "index.json"))
        e = index["entries"].get(f"proof:S001:{b1}", {})
        check("2. the first publication after the change backfills: A's verification is in the index",
              [v["commit"] for v in e.get("verified", [])] == [c1, c3] and e["first"]["commit"] == c1
              and e["last"]["commit"] == c3, e)
        rebuilt = sd.index_from_records(clone(old, base / "old-clone"), sd.positions(repo))
        check("2. rebuilding the index from the records gives the same index", rebuilt == index)
        try:
            sd.cmd_check_index(str(old), str(repo))
            check("2. check-index agrees", True)
        except sd.Fault as err:
            check("2. check-index agrees", False, err)

        # 3. Idempotent retries.
        n = len(log(old))
        publish(old, repo, rec_c, base)
        again = t.record_for(repo, c3, url="https://github.com/o/r/actions/runs/9/attempts/2")
        publish(old, repo, again, base)
        check("3. publishing the same record twice (even from another run) changes nothing",
              len(log(old)) == n and json.loads(show(old, "site-data", "index.json")) == index, log(old)[:3])

        # 4. Out-of-order publication: C, then A, then B.
        ooo = bare(base, "ooo-site-data.git")
        for rec in (rec_c, rec_a, rec_b):
            publish(ooo, repo, rec, base)
        oi = json.loads(show(ooo, "site-data", "index.json"))
        oe = oi["entries"][f"proof:S001:{b1}"]
        check("4. published newest first: first is still A and last is C, by position on main",
              oe["first"]["commit"] == c1 and oe["last"]["commit"] == c3
              and [v["commit"] for v in oe["verified"]] == [c1, c3], oe)
        check("4. latest.json stays at the newest commit", json.loads(show(ooo, "site-data", "latest.json"))["commit"] == c3)
        check("4. the index lists every record it covers", set(oi["records"]) == {f"records/{c}.json" for c in (c1, c2, c3)}, oi["records"])
        check("4. the index matches one rebuilt from the records, whatever the order",
              oi == sd.index_from_records(clone(ooo, base / "ooo-clone"), sd.positions(repo)) == index)

        # 5. Atomic update.
        record_commits = [line.split()[0] for line in log(ooo) if "verification record" in line]
        check(f"5. every site-data commit that adds a record also writes index.json ({len(record_commits)} commits)",
              record_commits and all({"index.json"} <= files_in(ooo, c) and any(f.startswith("records/") for f in files_in(ooo, c))
                                     for c in record_commits), [files_in(ooo, c) for c in record_commits])
        race = bare(base, "race-site-data.git")
        publish(race, repo, rec_a, base)
        calls = []

        def change(d):
            if not calls:  # another writer gets in first, after this clone was made
                publish(race, repo, rec_b, base)
            calls.append(1)
            return sd.apply_record(d, rec_c, sd.ancestry(repo), sd.positions(repo))
        sd.write_with_retry(str(race), change, "verification record for race")
        ri = json.loads(show(race, "site-data", "index.json"))
        check("5. a rejected push is retried from the new tip, redoing the whole update",
              len(calls) == 2 and set(sorted({v["commit"] for e in ri["entries"].values() for v in e["verified"]})) == {c1, c3}
              and show(race, "site-data", f"records/{c2}.json") is not None, (len(calls), ri))
        check("5. after the race the index still matches the records",
              ri == sd.index_from_records(clone(race, base / "race-clone"), sd.positions(repo)))
        check("5. no site-data history was rewritten (every publication is a new commit)",
              len([l for l in log(race) if l]) == 3, log(race))
        # 6. The same commit, located by Lean and by the fallback.
        drepo, _ = t.make_main(base / "display")
        (drepo / "QPCP" / "Statements.lean").write_text(
            "namespace QPCP.Statement\n\ndef S001 : Prop := QPCP.Foo.Whole\n\nend QPCP.Statement\n")
        (drepo / "QPCP" / "Foo.lean").write_text("namespace QPCP.Foo\n\ndef Whole : Prop := True\n\nend QPCP.Foo\n")
        dsha = commit(drepo, "a one-name statement")
        e_lean = t.evidence_for(drepo, dsha, locatedByLean=True)
        e_lean["items"][0]["statementDefinition"] = {"name": "QPCP.Foo.Whole", "module": "QPCP.Foo", "line": 3, "endLine": 3}
        e_text = t.evidence_for(drepo, dsha, locatedByLean=False)
        r_lean = t.vr.build_record([e_lean], drepo, dsha, "https://github.com/o/r/actions/runs/1/attempts/1", 1)
        r_text = t.vr.build_record([e_text], drepo, dsha, "https://github.com/o/r/actions/runs/2/attempts/1", 1)
        check("6. the two routes locate the same definition, differently",
              r_lean["display"]["statementDefinitions"]["proof:S001"]["located"] == "lean"
              and r_text["display"]["statementDefinitions"]["proof:S001"]["located"] == "text")
        check("6. how a definition was located is not part of the evidence",
              r_lean["evidence"] == r_text["evidence"] and "statementDefinition" not in json.dumps(r_lean["evidence"]))
        for order, (first, second) in (("Lean first", (r_lean, r_text)), ("fallback first", (r_text, r_lean))):
            site = bare(base, f"display-{order.split()[0]}.git")
            publish(site, drepo, first, base)
            before = log(site)
            try:
                publish(site, drepo, second, base)
                ok = log(site) == before
                err = ""
            except sd.Fault as e2:
                ok, err = False, str(e2)
            check(f"6. {order}: publishing the same commit by the other route is a no-op", ok, err or log(site))
            shown = t.by_id(bs.assemble(t.tree_with({"S001": {"path": "QPCP/Proofs/S001.lean",
                                                              "blob": first["evidence"]["items"][0]["blob"]}}, commit=dsha),
                                        [], [], [], [], record=fetch(site, base), repo="o/r"))["S001"]["verified"]
            check(f"6. {order}: the page still shows the definition",
                  (shown.get("statementDefinition") or {}).get("source") == "def Whole : Prop := True", shown)
    except Exception as e:  # a crash is a failure, never a skip
        import traceback
        traceback.print_exc()
        check("the test ran to completion", False, repr(e))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
