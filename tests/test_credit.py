#!/usr/bin/env python3
"""Credit and review links come from files, never from titles (#115). No network.

    python3 -I tests/test_credit.py

Synthetic Git history and synthetic GitHub data:

  1. The commit that added a file: a contribution merged with a merge commit
     is credited to the branch commit that added it, not to the merge; a file
     deleted and added again is credited to the latest addition.
  2. An earlier merged pull request titled "Phase 2 statements (S030-S056)"
     and a later one that adds QPCP/Proofs/S030.lean: S030 is credited to the
     later one's author, with its link.
  3. A documentation pull request whose title mentions S001 gets no credit
     for S001; when no pull request contains the commit that added S001's
     file, the commit's author is credited, marked "no pull request found".
  4. A contributed lemma is credited to the pull request that added
     QPCP/Lemmas/L<N>.lean.
  5. An unrelated open pull request mentioning L777 is not proposal #777's
     review link; one that adds QPCP/Lemmas/L778.lean is #778's; one that adds
     L0777.lean is nobody's.
  6. One spelling per id: a file L0777 does not map to issue #777.
  7. Credits already found are reused from the previous feed for the same
     file and commit; a changed commit, or one that found no pull request,
     is looked up again.
  8. The browser fallback credits no pull request from titles.
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
GIT_ID = ["-c", "user.name=Commit Author", "-c", "user.email=author@example.invalid", "-c", "commit.gpgsign=false"]


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:500]}"))


spec = importlib.util.spec_from_file_location("build_status", ROOT / "scripts" / "build_status.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def git(cwd, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def pull(n, user, title, merged_at=None, base="main"):
    return {"number": n, "user": {"login": user}, "title": title, "merged_at": merged_at,
            "base": {"ref": base}, "html_url": f"https://example.invalid/pull/{n}", "created_at": "2026-11-20T00:00:00Z"}


def issue(n, title, labels=("step",), state="open"):
    return {"number": n, "title": title, "state": state, "labels": [{"name": l} for l in labels],
            "html_url": f"https://example.invalid/issues/{n}", "assignees": [], "created_at": "2026-11-20T00:00:00Z"}


def item(ident, path, blob):
    return {"kind": "proof", "id": ident, "declaration": f"QPCP.Proof.{ident}", "path": path, "blob": blob,
            "verdict": "ACCEPTED", "statementDigest": "d" * 64, "dependsOn": [],
            "statementPath": "QPCP/Statements.lean", "statementLine": 1}


def run_js(expr):
    site = (ROOT / "docs" / "assets" / "site.js").read_text()
    if shutil.which("node"):
        r = subprocess.run(["node", "-e", "var window = {};\n" + site + "\nconsole.log(" + expr + ");"],
                           capture_output=True, text=True, timeout=60)
    elif shutil.which("osascript"):
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", "var window = {};\n" + site + "\n" + expr + ";"],
                           capture_output=True, text=True, timeout=60)
    else:
        raise RuntimeError("no JavaScript runtime (node or osascript)")
    return json.loads(r.stdout.strip())


def main():
    print("Credit and review links from files (#115)")
    base = Path(tempfile.mkdtemp(prefix="qpcp-credit-"))
    try:
        # 1. Synthetic history: main, a docs commit, a branch that adds S030 merged with --no-ff.
        repo = base / "repo"
        (repo / "QPCP" / "Proofs").mkdir(parents=True)
        (repo / "README.md").write_text("x\n")
        git(base, "init", "-q", "-b", "main", str(repo))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Phase 2 statements (S030-S056)")
        phase2 = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "-b", "prove-S030")
        (repo / "QPCP" / "Proofs" / "S030.lean").write_text("proof\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "Prove S030")
        adds_s030 = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #156", "prove-S030")
        merge = git(repo, "rev-parse", "HEAD")
        (repo / "QPCP" / "Proofs" / "S001.lean").write_text("v1\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "S001 first")
        git(repo, "rm", "-q", "QPCP/Proofs/S001.lean")
        git(repo, "commit", "-q", "-m", "S001 removed")
        (repo / "QPCP" / "Proofs" / "S001.lean").write_text("v2\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "S001 again")
        readds_s001 = git(repo, "rev-parse", "HEAD")
        added = bs.added_commits(repo, ["QPCP/Proofs/S030.lean", "QPCP/Proofs/S001.lean"])
        check("1. a file merged with a merge commit is credited to the branch commit that added it",
              added["QPCP/Proofs/S030.lean"] == adds_s030 and adds_s030 not in (merge, phase2), added)
        check("1. a file deleted and added again is credited to the latest addition",
              added["QPCP/Proofs/S001.lean"] == readds_s001, added)

        # 2-4. Credits, with the pull requests GitHub would list for each commit.
        phase2_pr = pull(60, "maintainer", "Phase 2 statements (S030-S056)", "2026-11-24T08:13:07Z")
        s030_pr = pull(156, "ApoorvaKatragadda", "Prove S030", "2026-11-26T17:16:50Z")
        docs_pr = pull(70, "docs-writer", "Docs: explain S001", "2026-11-25T00:00:00Z")
        lemma_pr = pull(801, "lemma-author", "A statement", "2026-11-25T12:00:00Z")
        pulls = {"c-s030": [s030_pr, pull(157, "x", "Prove S030 (draft)", None), pull(158, "y", "Prove S030", "2026-11-26T00:00:00Z", base="dev")],
                 "c-s001": [], "c-l800": [lemma_pr]}
        asked = []

        def pulls_of(sha):
            asked.append(sha)
            return pulls.get(sha, [])
        credits = bs.resolve_credits(
            {"QPCP/Proofs/S030.lean": "c-s030", "QPCP/Proofs/S001.lean": "c-s001", "QPCP/Lemmas/L800.lean": "c-l800",
             "QPCP/Lemmas/L0777.lean": "c-l0777"},
            pulls_of, lambda sha: "commit-author-login")
        check("2. S030 is credited to the merged pull request into main that contains the adding commit",
              credits["QPCP/Proofs/S030.lean"]["pr"] == 156 and credits["QPCP/Proofs/S030.lean"]["who"] == "ApoorvaKatragadda",
              credits["QPCP/Proofs/S030.lean"])
        check("3. with no pull request, the commit's author is credited and it says so",
              credits["QPCP/Proofs/S001.lean"] == {"path": "QPCP/Proofs/S001.lean", "commit": "c-s001", "pr": None, "prUrl": "",
                                                   "who": "commit-author-login", "mergedAt": "", "note": "no pull request found"},
              credits["QPCP/Proofs/S001.lean"])

        tree = {"steps": [{"id": i, "title": i, "section": "S", "difficulty": 1, "deps": [], "program": "foundations"}
                          for i in ("S001", "S030", "S031")],
                "programs": [{"id": "foundations", "title": "Foundations", "open": True}],
                "retired": set(), "barriers": [], "commit": "f" * 40,
                "lemmas": [{"id": "L800", "program": "foundations", "title": "A lemma"},
                           {"id": "L0777", "program": "foundations", "title": "Odd spelling"}],
                "proofs": {"S030": {"path": "QPCP/Proofs/S030.lean", "blob": "3" * 40},
                           "S001": {"path": "QPCP/Proofs/S001.lean", "blob": "1" * 40}},
                "refutations": {}, "lemmaFiles": {}, "credits": credits}
        record = {"format": 1, "run": {"url": "u", "attempt": 1}, "verifiedAt": "t", "evidence": {
            "commit": "f" * 40, "toolchain": "", "mathlib": "",
            "items": [item("S030", "QPCP/Proofs/S030.lean", "3" * 40), item("S001", "QPCP/Proofs/S001.lean", "1" * 40)]}}
        issues = [issue(61, "S030: x"), issue(2, "S001: x"), issue(62, "S031: x"),
                  issue(800, "L800: A lemma"), issue(777, "Proposal: something", ("proposal",)),
                  issue(778, "Proposal: another", ("proposal",))]
        open_pulls = [
            dict(pull(900, "someone", "Fix a typo near L777"), files=[{"filename": "README.md", "status": "modified"}]),
            dict(pull(901, "proposer", "State L778"), files=[{"filename": "QPCP/Lemmas/L778.lean", "status": "added"}]),
            dict(pull(902, "odd", "State L777"), files=[{"filename": "QPCP/Lemmas/L0777.lean", "status": "added"}]),
        ]
        # Titles that would have been matched before: they must change nothing now.
        closed = [phase2_pr, docs_pr, s030_pr]
        doc = bs.assemble(tree, issues, closed, open_pulls, [], record=record)
        s = {x["id"]: x for x in doc["steps"]}
        check("2. the earlier 'Phase 2 statements (S030-S056)' pull request gets no credit for S030",
              s["S030"]["who"] == "ApoorvaKatragadda" and s["S030"]["prUrl"] == "https://example.invalid/pull/156", s["S030"])
        check("2. the credit names the adding commit", s["S030"]["credit"]["commit"] == "c-s030", s["S030"]["credit"])
        check("2. the contributors list credits the later author, not the earlier one",
              doc["people"].get("ApoorvaKatragadda", {}).get("proved") == ["S030"] and "maintainer" not in doc["people"],
              doc["people"])
        check("3. a documentation pull request mentioning S001 gets no credit for S001",
              s["S001"]["who"] == "commit-author-login" and s["S001"]["prUrl"] == ""
              and s["S001"]["credit"]["note"] == "no pull request found" and "docs-writer" not in doc["people"], s["S001"])
        check("4. a lemma is credited to the pull request that added its file",
              s["L800"]["statedBy"] == "lemma-author" and doc["people"].get("lemma-author", {}).get("stated") == ["L800"],
              (s["L800"]["statedBy"], doc["people"]))
        props = {p["id"]: p for p in doc["proposals"]}
        check("5. an unrelated open pull request mentioning L777 is not proposal #777's review link",
              props["L777"]["prUrl"] == "", props["L777"])
        check("5. an open pull request that adds QPCP/Lemmas/L778.lean is proposal #778's review link",
              props["L778"]["prUrl"] == "https://example.invalid/pull/901", props["L778"])
        check("6. a file spelled L0777 does not map to issue #777", s["L0777"]["issue"] is None and s["L0777"]["url"] == "",
              s["L0777"])

        # 7. Reuse of credits already found.
        asked.clear()
        prev = bs.previous_credits(doc)
        again = bs.resolve_credits({"QPCP/Proofs/S030.lean": "c-s030", "QPCP/Proofs/S001.lean": "c-s001",
                                    "QPCP/Lemmas/L800.lean": "c-l800-new"}, pulls_of, lambda sha: "a", prev)
        check("7. a credit already found for the same file and commit is reused without a lookup",
              "c-s030" not in asked and again["QPCP/Proofs/S030.lean"]["pr"] == 156, asked)
        check("7. a file whose adding commit changed is looked up again", "c-l800-new" in asked, asked)
        check("7. a credit that found no pull request is looked up again", "c-s001" in asked, asked)

        # 8. The browser fallback.
        js = run_js("JSON.stringify(window.QPCP._buildFromApi(" + json.dumps(tree["steps"]) + ", " +
                    json.dumps([issue(61, "S030: x")]) + ", " + json.dumps([phase2_pr, s030_pr, docs_pr]) +
                    ", []).steps.map(function (x) { return x.prUrl; }))")
        check("8. without the feed, no step is linked to a pull request from its title", js == ["", "", ""], js)
        page = (ROOT / "docs" / "assets" / "site.js").read_text()
        check("8. the fallback no longer fetches closed pull requests", "pulls?state=closed" not in page)
    except Exception as e:  # a crash is a failure, never a skip
        check("the test ran to completion", False, repr(e))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
