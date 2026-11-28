#!/usr/bin/env python3
"""A volunteer's first hour: the mechanical rules in JOIN.md and the feed. No network.

    python3 -I tests/test_onboarding.py

  1. The setup block in JOIN.md stops, non-zero and before any `lake` command
     runs, when JOIN.md differs from the pinned commit or the pinned commit
     does not exist, and before cloning when /out is missing or not writable
     (a fresh virtual machine); when it is unchanged it records the checkout's commit in
     /out/base-commit and goes on. It runs the block exactly as written, with
     only the clone URL and /out redirected, against synthetic repositories
     and a stand-in `lake` that records whether it was called.
  2. The submission card comes from the step's own issue: S060's card names
     issue #146, not #60; a lemma's names its own issue; a step without an
     issue, or one already proved, has no card; its paths and build commands
     are the ones the checker uses; a proposal's card has no "Closes". The
     feed carries difficulty, prerequisites with their states, and claims.
  3. JOIN.md's worked submission example no longer relies on an id and an
     issue number that happen to match.
  4. The JOIN.md pins in README.md and docs/assets/site.js agree, and JOIN.md
     is unchanged since the pinned commit (so a merged pin never stops agents).
  5. The proposal bot says what can be accepted today: with no listed
     reviewer it says the statement waits; it never tells the proposer to
     close the issue.
  6. The manual route, "Network" option (b) (#169): the status file and
     every submission or claim refresh go back to the owner, who saves a
     dated snapshot inside the workspace, and a passing S060 is never said
     to make choosing a step or publishing network-free; a resuming agent
     confirms, with one command run as written, that it reaches the guest
     and that it is the prepared one, and neither redoes the setup nor asks
     again for approvals; the practice run comes before choosing a role or
     claiming.
  7. The owner-relayed pilot: marked a pilot, for exercises only, S031 only;
     the exception to "read only inside the workspace" stated exactly; the
     owner's transfer commands, run as written: the sheet is made in the
     guest only while the sources are unchanged since the sheet's commit;
     only a regular, UTF-8 file of at most 16 KiB passes the owner's check;
     the result names the candidate's SHA-256, gives the first error, and is
     at most 4 KiB. No helper script, and no per-command approval route.
  9. The relay's transfers (the review of #171), run as written with stand-in
     limactl and less, under bash and (where installed) zsh: a file coming
     in never follows a link at its fixed name in the agent's folder (a link
     to a file, to a folder, or to nothing), it is checked in a folder of the
     owner's and renamed into place; the candidate going out is copied
     without following a link and only that checked copy is sent, even if
     the agent changes its file meanwhile; the result is at most 4096 bytes
     and ends at a whole character.
 10. The #173 guide round: step 6 refuses a result that is missing, empty,
     without its "candidate sha256:" line, or for another candidate than the
     one step 4 sent and recorded, with a STOP saying to wait for step 5, and
     nothing reaches the agent's folder; a good result is delivered. Step 5
     never leaves an empty result visible while the build runs. Step 4's
     staged copy never holds more than 16385 bytes, and it records the
     SHA-256 sent. The wording points (a) to (g) and the observed result.
  8. docs/pilot/S031.txt, written by hand: every declaration in it, the
     statement's body above all, is the source at the commit it records
     (the volunteer's /out/base-commit), unchanged at this checkout.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails = 0
GIT_ID = ["-c", "user.name=qpcp-test", "-c", "user.email=qpcp-test@example.invalid", "-c", "commit.gpgsign=false"]
UPSTREAM = "https://github.com/nareshgoud274/qpcp-proofs"


def check(desc, okay, detail=""):
    global fails
    fails += not okay
    print(f"  {'ok  ' if okay else 'FAIL'}  {desc}" + ("" if okay else f": {str(detail)[:600]}"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(cwd, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def section(text, heading):
    start = text.index(heading)
    nxt = re.search(r"(?m)^## ", text[start + len(heading):])
    return text[start:start + len(heading) + (nxt.start() if nxt else len(text))]


def setup_block(join):
    body = section(join, "## Set up (once)")
    blocks = re.findall(r"(?ms)^```\n(.*?)^```$", body)
    return blocks[0]


def update_block(join):
    body = section(join, "## Set up (once)")
    return next(b for b in re.findall(r"(?ms)^```\n(.*?)^```$", body) if "<<'UPDATE'" in b)


def stub(bindir, name, script):
    path = bindir / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


# ------------------------------------------------------------------ 1. the stop

def run_setup(block, work, join_sha, url, out_state="ready", keep=False):
    out = work / "out"
    if out_state != "missing" and not out.exists():
        out.mkdir()
    if out_state == "read-only":
        out.chmod(0o555)
    bindir = work / "bin"
    bindir.mkdir(exist_ok=True)
    calls = work / "lake-calls"
    if not keep:
        for f in (calls, work / "elan-calls"):
            f.unlink(missing_ok=True)
    # Reads its stdin, as a real program may: the setup block must not lose its
    # remaining lines to it (the block itself arrives on bash's stdin).
    stub(bindir, "lake", f'cat > /dev/null\necho "$*" >> "{calls}"\n')
    text = block.replace("<the pinned commit id>", join_sha).replace(UPSTREAM, url).replace("/out/", f"{out}/")
    # HOME is the workspace's home folder: the block clones into ~ (here work/ws).
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GIT_CONFIG_GLOBAL=os.devnull,
               HOME=str(work / "ws"), QPCP_TEST_ELAN_LOG=str(work / "elan-calls"))
    r = subprocess.run(["bash", "-c", text], cwd=work / "ws", capture_output=True, text=True, env=env, timeout=60)
    lake = calls.read_text().splitlines() if calls.exists() else []
    base = (out / "base-commit").read_text().strip() if (out / "base-commit").exists() else None
    return r, lake, base


def elan_ran(work):
    return (work / "elan-calls").exists()


def test_stop(tmp):
    join = (ROOT / "JOIN.md").read_text()
    block = setup_block(join)
    check_at = block.find('git diff --quiet "$join_sha" HEAD -- JOIN.md')
    first_download = min(i for i in (block.find("lake "), block.find("elan "), block.find("curl ")) if i >= 0)
    check("1. the setup block compares JOIN.md with the pinned commit before any lake, elan or curl",
          0 <= check_at < first_download, block)
    check("1. the comparison exits non-zero on a difference", re.search(r'JOIN\.md \|\| \{[^}]*exit 1; \}', block), block)
    check("1. the checkout's commit is recorded separately", "git rev-parse HEAD > /out/base-commit" in block, block)
    elan_at = block.find("bash scripts/install_elan.sh")
    check("1. elan is installed by the pinned installer, inside the setup block, after the JOIN.md check "
          "and before any lake", 0 <= check_at < elan_at < block.find("lake "), block)
    check("1. JOIN.md never fetches the elan installer from a branch or runs elan-init.sh itself",
          "elan-init" not in join and not re.search(r"https?://\S*/(?:master|main)/\S*elan", join), "")
    check("1. the setup block clones into the home folder, so later steps can find ~/qpcp-proofs",
          block.find("cd ~") >= 0 and block.find("cd ~") < block.find("git clone"), block)

    # A synthetic upstream: commit A (the pin), then an unrelated commit B.
    up = tmp / "upstream" / "qpcp-proofs"  # cloned into ./qpcp-proofs, as from GitHub
    up.mkdir(parents=True)
    git(up, "init", "-q", "-b", "main")
    (up / "JOIN.md").write_text("instructions v1\n")
    # A stand-in for the pinned installer: it records that it ran, and installs nothing.
    (up / "scripts").mkdir()
    (up / "scripts" / "install_elan.sh").write_text('echo ran >> "$QPCP_TEST_ELAN_LOG"\n')
    git(up, "add", "JOIN.md", "scripts/install_elan.sh")
    git(up, "commit", "-q", "-m", "JOIN")
    pin = git(up, "rev-parse", "HEAD")
    (up / "README.md").write_text("pin bump\n")
    git(up, "add", "README.md")
    git(up, "commit", "-q", "-m", "pins")
    head = git(up, "rev-parse", "HEAD")

    def fresh(name):
        w = tmp / name
        (w / "ws").mkdir(parents=True)
        return w

    r, lake, base = run_setup(block, fresh("same"), pin, str(up))
    check("1. unchanged JOIN.md: setup succeeds, installs elan, and goes on to lake",
          r.returncode == 0 and lake == ["exe cache get", "build QPCP.Statements"] and elan_ran(tmp / "same"),
          (r.returncode, lake, r.stderr))
    check("1. unchanged JOIN.md: /out/base-commit is the checkout's commit, not the pin",
          base == head and base != pin, (base, head, pin))

    (up / "JOIN.md").write_text("instructions v2\n")
    git(up, "commit", "-q", "-am", "JOIN changed")
    r, lake, base = run_setup(block, fresh("changed"), pin, str(up))
    check("1. changed JOIN.md: setup exits non-zero", r.returncode != 0, (r.returncode, r.stdout))
    check("1. changed JOIN.md: nothing is downloaded (neither elan nor lake runs)",
          lake == [] and not elan_ran(tmp / "changed"), lake)
    check("1. changed JOIN.md: no base commit is recorded", base is None, base)
    check("1. changed JOIN.md: it says STOP", "STOP" in r.stdout, r.stdout)

    r, lake, base = run_setup(block, fresh("missing"), "0" * 40, str(up))
    check("1. a pin that is not in the history: non-zero, and lake never runs",
          r.returncode != 0 and lake == [] and base is None, (r.returncode, lake, base))

    # /out missing, or not writable by the working user (a fresh Lima VM): stop before cloning.
    now_pin = git(up, "rev-parse", "HEAD")  # JOIN.md unchanged since this pin: only /out can stop it
    for state in ("missing", "read-only"):
        if state == "read-only" and os.geteuid() == 0:
            continue  # root can write anywhere: the read-only case cannot be shown as root
        w = fresh(f"out-{state}")
        r, lake, base = run_setup(block, w, now_pin, str(up), out_state=state)
        check(f"1. /out {state}: setup says STOP, exits non-zero, clones nothing and never runs lake",
              r.returncode != 0 and "STOP: /out is missing or not writable" in r.stdout and lake == []
              and not (w / "ws" / "qpcp-proofs").exists(), (r.returncode, r.stdout, r.stderr, lake))
        if state == "read-only":
            (w / "out").chmod(0o755)

    # A run that failed partway leaves the clone: a second run says STOP, and runs nothing.
    w = fresh("rerun")
    run_setup(block, w, now_pin, str(up))
    r, lake, base = run_setup(block, w, now_pin, str(up))
    check("1. setup run again over an existing clone: says STOP (delete it and rerun), runs neither elan nor lake",
          r.returncode != 0 and "STOP: ~/qpcp-proofs already exists" in r.stdout and lake == [],
          (r.returncode, r.stdout, lake))
    check("1. JOIN.md says how to recover from a partial setup",
          "rm -rf ~/qpcp-proofs" in join, "")

    # The update block, from a fresh shell: it sets join_sha itself.
    upd = update_block(join)
    check("1. the update block sets join_sha itself (a new shell has no variables)",
          "join_sha=<the pinned commit id>" in upd and upd.index("join_sha=") < upd.index('"$join_sha"'), upd)

    def run_update(work, sha):
        text = upd.replace("<the pinned commit id>", sha).replace("/out/", f"{work / 'out'}/")
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, HOME=str(work / "ws"))
        return subprocess.run(["bash", "-c", text], cwd="/", capture_output=True, text=True, env=env, timeout=60)

    (up / "README.md").write_text("another unrelated change\n")
    git(up, "commit", "-q", "-am", "unrelated")
    r = run_update(w, now_pin)
    check("1. update after an unrelated commit: records the new base commit",
          r.returncode == 0 and (w / "out" / "base-commit").read_text().strip() == git(up, "rev-parse", "HEAD"),
          (r.returncode, r.stdout, r.stderr))
    (up / "JOIN.md").write_text("instructions v3\n")
    git(up, "commit", "-q", "-am", "JOIN changed again")
    r = run_update(w, now_pin)
    check("1. update after JOIN.md changed: says STOP and exits non-zero",
          r.returncode != 0 and "STOP: JOIN.md has changed" in r.stdout, (r.returncode, r.stdout))

    # Every later block starts from a fresh shell's state.
    practice = re.findall(r"(?ms)^```\n(.*?)^```$", section(join, "## Practice run"))[0]
    check("1. the practice run starts with the new-shell line (folder and PATH)",
          practice.startswith('cd ~/qpcp-proofs && export PATH="$HOME/.elan/bin:$PATH"'), practice)
    check("1. JOIN.md gives the new-shell line once for every new shell",
          'cd ~/qpcp-proofs && export PATH="$HOME/.elan/bin:$PATH"' in section(join, "## Set up (once)"), "")


# ------------------------------------------------------- 1b. the workspace checks

def test_workspace(tmp):
    join = (ROOT / "JOIN.md").read_text()
    two = section(join, "## Two places")
    blocks = re.findall(r"(?ms)^   ```\n(.*?)^   ```$", two)
    checks = next(b for b in blocks if "SSH_AUTH_SOCK" in b)
    mount_cmd = next(l.strip() for l in checks.splitlines() if l.strip().startswith("mount "))
    mount_cmd = mount_cmd.split("   #")[0]

    def mount_check(lines):
        fake = tmp / "mount-bin"
        fake.mkdir(exist_ok=True)
        (fake / "mount").write_text("#!/bin/sh\ncat <<'EOF'\n" + "\n".join(lines) + "\nEOF\n")
        (fake / "mount").chmod(0o755)
        r = subprocess.run(["bash", "-c", mount_cmd], capture_output=True, text=True,
                           env=dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}"), timeout=30)
        return r.stdout.strip()

    clean_vm = ["/dev/vda1 on / type ext4 (rw,relatime)",
                "fusectl on /sys/fs/fuse/connections type fusectl (rw,nosuid,nodev,noexec,relatime)",
                "/dev/sr0 on /mnt/lima-cidata type iso9660 (ro,relatime)"]
    check("1b. mount check on a clean Lima VM (fusectl is present): prints nothing", mount_check(clean_vm) == "",
          mount_check(clean_vm))
    docker = ["overlay on / type overlay (rw)", "/run/host_mark/Users on /out type fakeowner (rw)",
              "/dev/vda1 on /out type ext4 (rw)"]
    check("1b. mount check in a container: the /out mount itself is not flagged", mount_check(docker) == "",
          mount_check(docker))
    for bad in ("mount0 on /Users type virtiofs (rw)", "host on /mnt/host type 9p (rw)",
                "me@host:/ on /mnt/x type fuse.sshfs (rw)", "/dev/fuse on /mnt/y type fuse (rw)"):
        check(f"1b. mount check flags a host share: {bad.split(' type ')[1].split()[0]}",
              mount_check(clean_vm + [bad]) != "", bad)
    tools = [b for b in blocks if "apt-get install" in b]
    vm = next((b for b in tools if "sudo" in b), "")
    check("1b. the VM's tools line puts sudo in front of each apt-get",
          vm.count("apt-get ") == 2 and vm.count("sudo apt-get ") == 2, vm)
    check("1b. every apt-get line keeps its input from the next commands (</dev/null)",
          all(b.count("</dev/null") >= 2 for b in tools) and len(tools) == 2, tools)
    check("1b. the VM is stopped before it is deleted",
          "limactl stop qpcp\n   limactl delete qpcp" in two or "limactl stop qpcp\nlimactl delete qpcp" in "\n".join(blocks), "")
    check("1b. Lima's current template syntax (template:, not template://)",
          "template:ubuntu-24.04" in two and "template://" not in two, "")
    check("1b. limactl create runs without an interactive prompt (--yes)",
          re.search(r"limactl create --yes ", two) is not None, "")
    check("1b. Docker: a host-side check that the container shares exactly one host folder",
          "docker inspect qpcp-work" in two and "qpcp-out -> /out" in two, "")
    check("1b. Docker: the root-owned output is taken (chown) before it is deleted",
          0 <= two.find('sudo chown -R "$USER" ~/qpcp-work/qpcp-out') < two.find("rm -rf ~/qpcp-work"), "")

    # Every lake build in a block an agent runs keeps its input (</dev/null).
    runnable = re.findall(r"(?ms)^\s*```\n(.*?)^\s*```$", join)
    builds = [l.strip() for b in runnable for l in b.splitlines() if l.strip().startswith("lake build")]
    check("1b. every `lake build` line in a command block has </dev/null",
          builds and all("</dev/null" in l for l in builds), [l for l in builds if "</dev/null" not in l])
    check("1b. the task folder /out/<ID> is created before it is used (section A and Budget)",
          section(join, "## A. Prove").count("mkdir -p /out/<ID>") >= 1
          and section(join, "## Budget and stopping").count("mkdir -p /out/<ID>") >= 1, "")

    # The card and claim commands, run against a sample status file instead of the network.
    status = tmp / "status.json"
    status.write_text(json.dumps({"steps": [
        {"id": "S060", "status": "proved", "exercise": False, "claim": None, "submission": None},
        {"id": "S031", "status": "open", "exercise": True, "claim": None,
         "submission": {"text": "S031  (issue #62)\nproof:\n  file      QPCP/Proofs/S031.lean"}}]}))
    a_sec = section(join, "## A. Prove")
    cmds = [b for b in re.findall(r"(?ms)^```\n(.*?)^```$", a_sec) if "site-data/status.json" in b]

    def run_cmd(block, sid):
        text = re.sub(r"curl -s \S+status\.json", f"cat {status}", block).replace(" S060\n", f" {sid}\n")
        r = subprocess.run(["bash", "-c", text if text.endswith("\n") else text + "\n"], capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip()

    check("1b. section A gives the card command and the claim command", len(cmds) == 2, len(cmds))
    if len(cmds) == 2:
        check("1b. the card command prints the card, or 'no card' for a proved step",
              run_cmd(cmds[0], "S031").startswith("S031  (issue #62)")
              and run_cmd(cmds[0], "S060") == "no card: the step is proved", (run_cmd(cmds[0], "S031"),))
        check("1b. the claim command prints status, exercise and claim",
              run_cmd(cmds[1], "S031") == "status: open | exercise: True | claim: None", run_cmd(cmds[1], "S031"))


# ----------------------------------------------------------- 2. the card and feed

def test_card():
    bs, ck = load("build_status"), load("check")
    tree = bs.read_tree(ROOT)
    for sid in ("S059", "S060"):
        tree["proofs"].pop(sid, None)
    tree["lemmas"].append({"id": "L700", "program": "foundations", "title": "A lemma"})

    def issue(n, title, labels=("step",), assignees=()):
        return {"number": n, "title": title, "state": "open", "labels": [{"name": l} for l in labels],
                "html_url": f"https://example.invalid/issues/{n}", "assignees": [{"login": a} for a in assignees],
                "updated_at": "2026-11-26T00:00:00Z", "created_at": "2026-11-25T00:00:00Z"}

    issues = [issue(146, "S060: Test A"), issue(145, "S059: milestone", ("step", "claimed"), ("volunteer",)),
              issue(700, "L700: A lemma"), issue(701, "Proposal: something", ("proposal",))]
    doc = bs.assemble(tree, issues, [], [], [], record=None)
    s = {x["id"]: x for x in doc["steps"]}

    c = s["S060"]["submission"]
    check("2. S060's card names its own issue, #146, not #60",
          c and c["issue"] == 146 and c["closes"] == "Closes #146" and "#60" not in c["text"], c)
    check("2. S060's card: statement, import, paths, declarations, build commands and titles",
          c["statement"] == "QPCP.Statement.S060" and c["import"] == "QPCP.Statements"
          and c["proof"] == {"path": "QPCP/Proofs/S060.lean", "declaration": "QPCP.Proof.S060",
                             "type": "QPCP.Statement.S060", "build": "lake build QPCP.Proofs.S060", "title": "Prove S060"}
          and c["refutation"]["path"] == "QPCP/Refutations/S060.lean"
          and c["refutation"]["type"] == "¬ QPCP.Statement.S060"
          and c["refutation"]["build"] == "lake build QPCP.Refutations.S060"
          and c["refutation"]["title"] == "Refute S060", c)
    for kind in ("proof", "refutation"):
        folder, module, ns = ck.KINDS[kind]
        check(f"2. the card's {kind} path, module and namespace are the checker's",
              c[kind]["path"] == f"{folder}/S060.lean" and c[kind]["build"] == f"lake build {module}.S060"
              and c[kind]["declaration"] == f"{ns}.S060", (c[kind], ck.KINDS[kind]))
    check("2. every value on the card appears in its copyable text",
          all(v in c["text"] for v in ("#146", "QPCP.Statement.S060", "QPCP/Proofs/S060.lean", "lake build QPCP.Proofs.S060",
                                       "Prove S060", "Closes #146", "Refute S060", "QPCP/Refutations/S060.lean")), c["text"])
    check("2. a claimed step still has a card, and its claim", s["S059"]["submission"]["issue"] == 145
          and s["S059"]["claim"] == {"by": ["volunteer"], "lastActivity": "2026-11-26T00:00:00Z", "lapsesAt": ""}, s["S059"])
    issues[1]["holderLastComment"] = "2026-11-26T05:00:00Z"
    held = {x["id"]: x for x in bs.assemble(tree, issues, [], [], [], record=None)["steps"]}["S059"]["claim"]
    check("2. a claim's clock is the holder's own last comment, and it says when it lapses",
          held == {"by": ["volunteer"], "lastActivity": "2026-11-26T05:00:00Z", "lapsesAt": "2026-11-27T05:00:00Z"}, held)
    l = s["L700"]["submission"]
    check("2. a lemma's card: its issue, QPCP.Lemma, the lemma's import",
          l and l["issue"] == 700 and l["statement"] == "QPCP.Lemma.L700" and l["import"] == "QPCP.Lemmas.L700"
          and l["proof"]["path"] == "QPCP/Proofs/L700.lean", l)
    no_issue = [x for x in doc["steps"] if x["issue"] is None]
    check("2. a step without an issue has no card (nothing is guessed)",
          no_issue and all(x["submission"] is None for x in no_issue), [x["id"] for x in no_issue][:5])
    check("2. a step that is not open (S027, pending here) has no card", s["S027"]["submission"] is None, s["S027"]["status"])
    check("2. the feed carries difficulty and real dependencies with their states",
          s["S060"]["difficulty"] in (1, 2, 3) and s["S060"]["deps"] == [{"id": "S027", "status": s["S027"]["status"]}], s["S060"])
    check("2. background steps are separate from dependencies",
          s["S032"]["deps"] == [] and [d["id"] for d in s["S032"]["background"]] == ["S030", "S031"], s["S032"])
    check("2. an unclaimed step's claim is null", s["S060"]["claim"] is None)
    p = doc["proposals"][0]["submission"]
    check("2. a proposal's card: State L701, Proposal #701, and no Closes",
          p["title"] == "State L701" and p["body"] == "Proposal #701" and p["path"] == "QPCP/Lemmas/L701.lean"
          and "Closes #" not in p["text"], p)
    check("2. the feed says how many statement reviewers are listed",
          doc["accepting"] == {"proofs": True, "refutations": True,
                               "statementReviewers": len(json.loads((ROOT / "reviewers.json").read_text()))}, doc["accepting"])
    page = (ROOT / "docs" / "step.html").read_text()
    check("2. the step page shows the feed's card text and has no card of its own making",
          "s.submission.text" in page and "Closes #" not in page, "")
    site = (ROOT / "docs" / "assets" / "site.js").read_text()
    check("2. the site passes the feed's `accepting` through to the pages", "accepting: s.accepting" in site)


# ---------------------------------------------------------------- 3. the example

def test_example():
    join = (ROOT / "JOIN.md").read_text()
    a = section(join, "## A. Prove or refute a lemma")
    closes = re.findall(r"Closes #(\d+)", a)
    ids = re.findall(r"\b[SL]0*(\d+)\b", a)
    check("3. section A's example closes an issue whose number differs from the step's id",
          closes and all(n not in ids for n in closes), (closes, sorted(set(ids))))
    check("3. section A no longer uses L123 and #123", "L123" not in a and "#123" not in a)
    check("3. section A takes its values from the submission card", re.search(r"submission\s+card", a))
    bs = load("build_status")
    issue = re.search(r"S060's issue is #(\d+)", a)
    check("3. the example's issue number for S060 is the card's", issue and issue.group(1) == "146"
          and f"--body \"{bs.submission_card('S060', 146)['closes']}\"" in a, issue)


# ------------------------------------------------------------------- 4. the pins

def test_pins():
    readme = (ROOT / "README.md").read_text()
    site = (ROOT / "docs" / "assets" / "site.js").read_text()
    r = re.findall(r"qpcp-proofs/([0-9a-f]{40})/JOIN\.md", readme)
    s = re.findall(r'JOIN_COMMIT = "([0-9a-f]{40})"', site)
    check("4. README.md and site.js pin the same JOIN.md commit", len(r) == 1 and r == s, (r, s))
    if r:
        have = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", r[0] + "^{commit}"], capture_output=True)
        check("4. the pinned commit is in this checkout's history (needs a full clone)", have.returncode == 0, r[0])
        if have.returncode == 0:
            same = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", r[0], "HEAD", "--", "JOIN.md"])
            check("4. JOIN.md is unchanged since the pinned commit (bump the pins, MAINTAINERS.md)",
                  same.returncode == 0, r[0])


# ------------------------------------------------------------ 5. the proposal bot

def test_bot(tmp):
    wf = (ROOT / ".github" / "workflows" / "proposal.yml").read_text()
    m = re.search(r"(?ms)^      - name: Label and explain\n        run: \|\n(.*)", wf)
    script = "\n".join(line[10:] for line in m.group(1).splitlines())
    check("5. the bot runs no checkout", "actions/checkout" not in wf)

    def run(reviewers, api_ok=True):
        d = Path(tempfile.mkdtemp(dir=tmp))
        bindir = d / "bin"
        bindir.mkdir()
        (d / "reviewers.json").write_text(reviewers)
        stub(bindir, "gh", f'''case "$1" in
  api) {"cat " + str(d / "reviewers.json") if api_ok else "exit 1"} ;;
  issue) if [ "$2" = comment ]; then shift 3; [ "$1" = --body ] && printf '%s' "$2" > "{d}/comment"; fi ;;
esac
''')
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", NUMBER="7", GH_REPO="o/r")
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=30)
        return r, (d / "comment").read_text() if (d / "comment").exists() else ""

    r, body = run("[]")
    check("5. no listed reviewer: the bot says the statement waits",
          r.returncode == 0 and "No reviewer is listed" in body and "cannot open today" in body, (r.stderr, body))
    check("5. it says proofs and refutations of existing steps are accepted today",
          "Proofs and refutations of the existing open steps are accepted" in body, body)
    check("5. it gives the statement's title and body, and says not to close the issue",
          "State L7" in body and "Proposal #7" in body and "Do not write `Closes #7`" in body, body)
    check("5. it never says another contributor's approval opens the lemma",
          "approving review opens" not in body.lower(), body)
    r, body = run('["a", "b"]')
    check("5. two listed reviewers: the bot says so", r.returncode == 0 and "2 reviewers are listed" in body, (r.stderr, body))
    r, body = run("[]", api_ok=False)
    check("5. reviewers.json unreadable: the bot says so and still comments",
          r.returncode == 0 and "could not read" in body, (r.returncode, r.stderr, body))


# ----------------------------------------------- 6. the manual route, option (b) (#169)

GUEST = "limactl shell qpcp -- "


def flat(x):
    return re.sub(r"\s+", " ", x)


def guest_script(line):
    """The script inside `limactl shell qpcp -- bash -lc '...'` (or bash -c), as the guest's bash receives it."""
    m = re.match(r"limactl shell qpcp -- bash -l?c '(.*)'(?: < .*)?$", line, re.S)
    return m and m.group(1)


def blocks_after(text, marker):
    """The command blocks (with list indentation removed) after marker in text."""
    at = text.index(marker)
    out = []
    for m in re.finditer(r"(?m)^( *)```\n(.*?)^\1```$", text[at:], re.S):
        out.append("\n".join(l[len(m.group(1)):] for l in m.group(2).split("\n")).strip())
    return out


def test_manual_route(tmp):
    join = (ROOT / "JOIN.md").read_text()
    net = join[join.index("## Network"):join.index("## Which revision")]
    manual = net[net.index("**The manual route, (b).**"):net.index("One documented example")]
    after = flat(manual[manual.index("The practice run needs no network."):])

    # Point 1: what goes back to the owner, and a dated snapshot in the workspace.
    check("6. (#169.1) option (b): the status file, and every refresh of a submission card or claim status, are "
          "among the steps that go back to the owner",
          "`site-data/status.json`" in after and "submission card or claim status" in after
          and "goes back to your owner" in after, after[:300])
    snap = [b for b in blocks_after(manual, "The practice run needs no network.") if "status.json" in b]
    check("6. (#169.1) the owner saves a dated snapshot of it inside the workspace (run in the guest), and the agent "
          "reads that copy", len(snap) == 1 and snap[0].startswith(GUEST) and "$(date -u +%Y-%m-%d" in snap[0]
          and "-o ~/status/status-" in snap[0] and "you read that copy, never a live one" in after
          and "read your owner's dated snapshot instead" in flat(join)
          and "`limactl shell qpcp -- bash -c 'ls ~/status'`" in flat(join) and "`ls ~/status`)" not in join, snap)
    implies = re.search(r"(S060|practice run)[^.]*(enables|lets you|allows you|so you can|without the network)", flat(join))
    check("6. (#169.1) a passing S060 is never said to make step selection or publishing network-free; it is said "
          "not to", implies is None and "a passing practice run does not change that" in after
          and "choosing a step needs the project's status file, and publishing needs GitHub" in after,
          implies and implies.group(0))

    # Point 5: the resuming agent's one confirmation, run as written.
    resume = manual[manual.index("Then your owner tells you it is done."):manual.index("The practice run needs no network.")]
    lines = [l for b in blocks_after(resume, "Then your owner tells you it is done.") for l in b.split("\n")
             if "prepared guest: ok" in l]
    script = guest_script(lines[0]) if len(lines) == 1 else None
    check("6. (#169.5) the resuming agent neither redoes the setup nor asks again for approvals already given",
          "Do not run the setup again, create another guest, or ask again for approvals your owner has already given"
          in flat(resume) and "do not repair or redo the setup yourself" in flat(resume), "")

    def confirm(state):
        w = tmp / f"resume-{state}"
        home, out = w / "home", w / "out"
        home.mkdir(parents=True); out.mkdir()
        repo = home / "qpcp-proofs"
        if state != "no-clone":
            repo.mkdir()
            git(repo, "init", "-q")
            (repo / "f").write_text("x")
            git(repo, "add", "f"); git(repo, "commit", "-qm", "base")
        if state not in ("no-elan", "no-clone"):
            (home / ".elan" / "bin").mkdir(parents=True)
            stub(home / ".elan" / "bin", "lake", "exit 0\n")
        if state != "no-clone":
            (out / "base-commit").write_text(("0" * 40 if state == "other-commit" else git(repo, "rev-parse", "HEAD")) + "\n")
        env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull)
        r = subprocess.run(["bash", "-c", script.replace("/out/", f"{out}/")], env=env, capture_output=True,
                           text=True, cwd=w, timeout=60)
        return "prepared guest: ok" in r.stdout
    results = {s: confirm(s) for s in ("prepared", "other-commit", "no-elan", "no-clone")} if script else {}
    check("6. (#169.5) the confirmation, run as written: \"prepared guest: ok\" for the prepared guest only (the clone "
          "at /out/base-commit, with elan), never for a guest at another commit, without elan, or without the clone",
          results == {"prepared": True, "other-commit": False, "no-elan": False, "no-clone": False}, (lines, results))

    # Point 6: the practice run comes first.
    roles = section(join, "## Roles")
    choose = section(join, "## Choose what to do")
    check("6. (#169.6) the practice run comes before choosing a role, a step, or claiming",
          "Do the practice run first" in roles and "before choosing a role, choosing a step, or claiming" in flat(roles)
          and roles.index("Do the practice run first") < roles.index("Then take one role per session")
          and "Once the setup and the practice run have passed" in choose, "")


# ---------------------------------------------------------- 7. the owner-relayed pilot

def test_pilot(tmp):
    join = (ROOT / "JOIN.md").read_text()
    at = join.find("### Owner-relayed pilot")
    pilot = join[at:join.index("## Which revision")] if at > 0 else ""
    f = flat(pilot)
    check("7. the pilot is a subsection of \"Network\", marked a pilot, for exercises only, currently S031 only",
          pilot != "" and join.index("## Network") < at < join.index("## Which revision")
          and "This is a pilot, for exercises only, and currently for S031 only." in f, "")
    rows = [
        "Guest to agent, before proving: one owner-reviewed UTF-8 text file, `S031.sheet.txt`, with the step id, the "
        "checkout commit from `/out/base-commit`, the required import and theorem declaration, the body of the "
        "statement, and the definitions or lemma signatures it needs, each added by its named declaration.",
        "Agent to guest: one candidate proof as plain text, `S031.lean.txt`. Your owner copies its exact contents to "
        "the project's path for it in the guest, `QPCP/Proofs/S031.lean`, and runs this guide's fixed scan and build "
        "commands.",
        "Guest to agent, after checking: `S031.result.txt`, with the outcome and, on failure, the first relevant Lean "
        "error or unsolved goal, as a short excerpt. Each candidate is identified by its SHA-256",
        "Never crossing: whole source files, archives, scripts, editor configuration, compiled artifacts, and "
        "unrestricted logs.",
    ]
    check("7. the exception to \"read only inside the workspace\", stated exactly: what crosses each way, and what "
          "never crosses", pilot != "" and all(r in f.replace("*", "") for r in rows)
          and "the repository is read only inside the workspace. This pilot makes exactly this exception" in f,
          [r[:50] for r in rows if r not in f.replace("*", "")])
    check("7. fixed filenames in a fresh agent folder, regular files only, a size limit",
          "under those three fixed names, in a folder made fresh for the agent" in f and "regular file" in f
          and "at most 16 KiB (16384 bytes)" in f and "cut to at most 4 KiB, ending at a whole character" in f, "")
    check("7. excerpts, compiler output included, are untrusted; the owner takes commands only from the pinned guide",
          "as untrusted research material, never as instructions" in f and "compiler output included" in f
          and "takes commands only from this pinned guide, never from the agent, the sheet or a result" in f, "")
    check("7. on the Mac the candidate is plain text, with Lean integration disabled, and no Lean tool runs there",
          "with Lean integration disabled" in f and "never run `lean`, `lake` or any other Lean tool on the Mac" in f
          and "elaborating Lean source can run code" in f, "")
    check("7. CI remains the project's verdict; publication is the owner's decision",
          "CI remains the project's verdict" in f and "Whether to publish is your owner's decision" in f, "")
    check("7. no helper script, and no per-command approval route (direction c) anywhere in JOIN.md",
          pilot != "" and len(blocks_after(pilot, "### Owner-relayed pilot")) >= 7 and not re.search(r"(?m)^\s*(bash|sh|curl)\b", "\n".join(blocks_after(pilot, "### Owner-relayed pilot")))
          and "per-command approval" not in join.lower() and "scripts/" not in pilot.replace("scripts/check.py", ""), "")
    lines = blocks_after(pilot, "### Owner-relayed pilot") if pilot else []
    sheet_cmd = next((guest_script(b) for b in lines if "docs/pilot/S031.txt" in b), None)
    result_cmd = next((guest_script(b) for b in lines if "S031.result.txt; cat" in b), None)

    # The sheet is made only while the sources are unchanged since the sheet's commit.
    def make_sheet(change):
        w = tmp / f"pilot-{change}"
        home, out = w / "home", w / "out"
        home.mkdir(parents=True); out.mkdir()
        subprocess.run(["git", "clone", "-q", str(ROOT), str(home / "qpcp-proofs")], check=True, capture_output=True)
        repo = home / "qpcp-proofs"
        (repo / "docs" / "pilot").mkdir(parents=True, exist_ok=True)
        (repo / "docs" / "pilot" / "S031.txt").write_text((ROOT / "docs" / "pilot" / "S031.txt").read_text())
        if change:
            p = repo / "QPCP" / "Defs.lean"
            p.write_text(p.read_text() + "\n-- changed\n")
            git(repo, "commit", "-qam", "change")
        (out / "base-commit").write_text(git(repo, "rev-parse", "HEAD") + "\n")
        r = subprocess.run(["bash", "-c", sheet_cmd.replace("/out/", f"{out}/")], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull), timeout=60)
        made = out / "S031.sheet.txt"
        return r.stdout, made.read_text() if made.exists() else None, git(repo, "rev-parse", "HEAD")
    if sheet_cmd and (ROOT / "docs" / "pilot" / "S031.txt").exists():
        stdout, made, head = make_sheet(False)
        check("7. the sheet command, run as written: the maintainer's sheet plus the checkout commit",
              "sheet made" in stdout and made is not None
              and made == (ROOT / "docs" / "pilot" / "S031.txt").read_text() + f"checkout commit: {head}\n", stdout)
        stdout, made, _ = make_sheet(True)
        check("7. the sheet command stops, making nothing, when a source changed since the sheet's commit",
              "STOP: the sources changed since the sheet was written" in stdout and made is None, stdout)
    else:
        for what in ("the maintainer's sheet plus the checkout commit", "stops, making nothing, when a source changed"):
            check(f"7. the sheet command, run as written: {what}", False, "no sheet command or no sheet")

    # The result: the candidate's SHA-256, the outcome, the first error, at most 4 KiB.
    def result(scan_ok, build_out):
        w = tmp / f"result-{scan_ok}-{len(build_out)}"
        home, out, bindir = w / "home", w / "out", w / "bin"
        for d in (home / "qpcp-proofs" / "QPCP" / "Proofs", out, bindir, home / ".elan" / "bin"):
            d.mkdir(parents=True)
        (home / "qpcp-proofs" / "QPCP" / "Proofs" / "S031.lean").write_text("theorem S031 : QPCP.Statement.S031 := by\n  simp\n")
        scan = "echo ACCEPTED\n" if scan_ok else "echo 'REJECTED: proof S031: forbidden'; exit 1\n"
        stub(bindir, "python3", f'[ "$1" = -c ] && exec "{sys.executable}" "$@"\n' + scan)
        build = w / "build.txt"
        build.write_text(build_out)
        stub(home / ".elan" / "bin", "lake", f'cat "{build}"; exit 1\n')
        # Only the guest's two log files move; the test's own folders may themselves be under /tmp.
        text = result_cmd.replace("/tmp/scan.log", f"{w}/scan.log").replace("/tmp/build.log", f"{w}/build.log")
        text = text.replace("/out/", f"{out}/")
        r = subprocess.run(["bash", "-c", text], capture_output=True, timeout=60,
                           env=dict(os.environ, HOME=str(home), PATH=f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin"))
        sha = subprocess.run(["shasum", "-a", "256", str(home / "qpcp-proofs" / "QPCP" / "Proofs" / "S031.lean")],
                             capture_output=True, text=True).stdout[:64]
        made = out / "S031.result.txt"
        return (made.read_bytes() if made.exists() else b""), sha
    if result_cmd:
        noise = "".join(f"info: building module {i}\n" for i in range(400))
        err = ("error: QPCP/Proofs/S031.lean:2:2: unsolved goals\nn : ℕ\nA : Op n\nψ : Config n → ℂ\n"
               "⊢ energy A ψ = energyOn A ψ\n")
        got, sha = result(True, noise + err + noise)
        text = got.decode("utf-8", "replace")
        check("7. the result, made as written: the candidate's SHA-256, \"Lean build FAILED\", and the first error with "
              "its unsolved goal, not the build's other output",
              text.startswith(f"candidate sha256: {sha}\n") and "source scan passed" in text
              and "Lean build FAILED" in text and "unsolved goals" in text and "⊢ energy A ψ" in text
              and "info: building module" not in text, text[:400])
        got, _ = result(True, "error: x\n" + "y" * 20000)
        check("7. the result is cut to 4 KiB before it leaves the guest", 0 < len(got) <= 4096, len(got))
        # A long error whose multibyte characters straddle byte 4096, at each of the three offsets.
        bad = []
        for pad in range(4):
            got, _ = result(True, "error: " + "x" * pad + "⊢ψ" * 2000 + "\n")
            try:
                got.decode("utf-8")
                ok = 4000 < len(got) <= 4096
            except UnicodeDecodeError as e:
                ok = False
            if not ok:
                bad.append((pad, len(got), got[-6:]))
        check("9. (review, defect 2) a long error with multibyte characters across byte 4096: the result is at most "
              "4096 bytes and decodes as strict UTF-8, at every offset", not bad, bad)
        got, _ = result(False, "")
        check("7. a scan failure is reported as such, with no build", b"source scan FAILED" in got
              and b"Lean build" not in got, got[:300])
    else:
        for what in ("the candidate's SHA-256, the outcome and the first error", "cut to 4 KiB", "a scan failure",
                     "(review, defect 2) strict UTF-8 at most 4096 bytes"):
            check(f"7. the result, made as written: {what}", False, "no result command")


# ------------------------------------------------------- 8. the S031 sheet (docs/pilot)

SHEET_COMMIT = "bf22b099d7696b51a05145a0653c50c3e75ba526"   # the volunteer's /out/base-commit (#167)


def test_sheet():
    path = ROOT / "docs" / "pilot" / "S031.txt"
    raw = path.read_bytes() if path.exists() else b""
    sheet = raw.decode("utf-8")
    rec = re.search(r"(?m)^recorded at: ([0-9a-f]{40})$", sheet)
    have = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", SHEET_COMMIT + "^{commit}"], capture_output=True)
    check("8. the sheet records the volunteer's checkout commit, which is in this checkout's history (needs a full "
          "clone), and is UTF-8 and at most 16 KiB", rec is not None and rec.group(1) == SHEET_COMMIT
          and have.returncode == 0 and len(raw) <= 16384 and "step: S031" in sheet, rec and rec.group(1))
    show = lambda rev, p: subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{p}"], capture_output=True,
                                         text=True, check=True).stdout
    decls = re.findall(r"(?ms)^--- (\S+) \((\S+)\) ---\n(.*?)(?=\n\n|\n*\Z)", sheet)
    names = [d[0] for d in decls]
    check("8. the sheet adds, by named declaration, the statement and each definition it uses",
          names == ["QPCP.Statement.S031", "QPCP.Config", "QPCP.Op", "QPCP.energy", "QPCP.energyOn"], names)
    for name, src, body in decls if have.returncode == 0 else []:
        short = name.rsplit(".", 1)[1]
        at_rec, at_head = show(SHEET_COMMIT, src), show("HEAD", src)
        m = re.search(rf"(?ms)^(?:def|abbrev|theorem|lemma) {re.escape(short)}\b.*?(?=\n\n|\n/--|\n-/|\Z)", at_rec)
        check(f"8. {name}: the sheet's text is the source at {SHEET_COMMIT[:7]} ({src}), and that is unchanged at "
              "this checkout", m is not None and m.group(0).rstrip() == body.rstrip() and body in at_head,
              (body, m and m.group(0)))
    stmt = dict((d[0], d[2]) for d in decls).get("QPCP.Statement.S031", "")
    src = show(SHEET_COMMIT, "QPCP/Statements.lean") if have.returncode == 0 else ""
    want = re.search(r"(?ms)^def S031 : Prop :=\n(.*?)(?=\n\n)", src)
    got = stmt.split(":=\n", 1)[1] if ":=\n" in stmt else None
    check("8. the statement's body in the sheet equals QPCP.Statement.S031's body at the recorded commit",
          want is not None and got is not None and got.rstrip() == want.group(1).rstrip(), (got, want and want.group(1)))
    check("8. the sheet gives the required import and theorem declaration, as S031's submission card has them",
          "import QPCP.Statements" in sheet and "theorem S031 : QPCP.Statement.S031 :=" in sheet
          and "namespace QPCP.Proof" in sheet and "QPCP/Proofs/S031.lean" in sheet
          and "lake build QPCP.Proofs.S031" in sheet, "")
    check("8. the sheet holds no proof (it is a sheet, not a submission)",
          sheet != "" and not re.search(r":= by|\brfl\b|\bsimp\b|\bexact\b", sheet), "")


# ------------------------------------------------- 9. the relay's transfers (review of #171)

def pilot_step(pilot, start, end):
    """All command blocks of one pilot step, joined, as the owner would run them in one terminal."""
    a, b = pilot.find(start), pilot.find(end)
    return "\n".join(blocks_after(pilot[a:b], start)) if -1 < a < b else None


def shells():
    return [s for s in ("bash", "zsh") if shutil.which(s)]


def run_transfer(script, shell, home, fixture=None, swap=False):
    """script with stand-ins: limactl prints the fixture (a file coming in) or records its input (one going out);
    less is a reader that, with swap, has the agent rewrite its candidate while the owner reads."""
    bindir = home.parent / "bin"
    bindir.mkdir(exist_ok=True)
    recv = home.parent / "received"
    stub(bindir, "limactl", f'if [ -n "$QPCP_FIXTURE" ]; then cat "$QPCP_FIXTURE"; else cat > "{recv}"; '
                            'echo "guest got it"; fi\n')
    stub(bindir, "less", f'[ -n "$QPCP_SWAP" ] && printf "swapped by the agent\\n" > "{home}/qpcp-relay/S031.lean.txt"\n'
                         'exit 0\n')
    env = dict(os.environ, HOME=str(home), PATH=f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
               QPCP_FIXTURE=str(fixture) if fixture else "", QPCP_SWAP="1" if swap else "")
    try:
        r = subprocess.run([shell, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess([shell], 124, "", "timed out")
    return r, (recv.read_bytes() if recv.exists() else None)


def fresh_home(tmp, tag):
    w = tmp / tag
    if w.exists():
        shutil.rmtree(w)
    home = w / "home"
    (home / "qpcp-relay").mkdir(parents=True)
    (home / "qpcp-owner").mkdir(mode=0o700)
    (w / "sentinel").write_text("the owner's file, never to be overwritten\n")
    (w / "sentinel-dir").mkdir()
    (home / "qpcp-owner" / "S031.sent.sha256").write_text(SENT + "\n")   # what step 4 records
    return home


SENT = "5b5dfeb5e35910e6ed4888b1ed5c6740e65f795ea961d0afe0ddc82fa1b4ef80"
FIRST = f"candidate sha256: {SENT}\n".encode()


def no_staging(home):
    return [p.name for p in (home / "qpcp-owner").iterdir() if p.name.startswith(("in.", "out."))] == []


def plant(home, name, kind):
    dest = home / "qpcp-relay" / name
    target = {"a link to a file": home.parent / "sentinel", "a link to a folder": home.parent / "sentinel-dir",
              "a dangling link": home.parent / "nothing-here"}[kind]
    dest.symlink_to(target)
    return dest, target


def test_transfers(tmp):
    join = (ROOT / "JOIN.md").read_text()
    at = join.find("### Owner-relayed pilot")
    pilot = join[at:join.index("## Which revision")] if at > 0 else ""
    steps = {"S031.sheet.txt": pilot_step(pilot, "3. Bring the sheet", "4. When the agent"),
             "S031.result.txt": pilot_step(pilot, "\n6. ", "\n7. ")}
    out_step = pilot_step(pilot, "4. When the agent", "5. Check it")
    for shell in shells() or ["bash"]:
        # Coming in: a link planted at the fixed name is never followed.
        for name, script in steps.items():
            # A result is delivered only if its first line names the candidate sent (section 10).
            good = (FIRST.decode() if name == "S031.result.txt" else "") + "step: S031\nψ ⊢ energy A ψ\n"
            head = FIRST if name == "S031.result.txt" else b""
            bad = []
            for kind in ("a link to a file", "a link to a folder", "a dangling link"):
                home = fresh_home(tmp, f"in-{shell}-{name}-{kind.replace(' ', '-')}")
                dest, target = plant(home, name, kind)
                fx = home.parent / "fixture"
                fx.write_text(good)
                r, _ = run_transfer(script or "false", shell, home, fixture=fx)
                sentinel_ok = (home.parent / "sentinel").read_text() == "the owner's file, never to be overwritten\n"
                dir_ok = list((home.parent / "sentinel-dir").iterdir()) == []
                nothing_made = not (home.parent / "nothing-here").exists()
                replaced = dest.exists() and not dest.is_symlink() and dest.read_text() == good
                if not (sentinel_ok and dir_ok and nothing_made and (replaced or r.returncode != 0)):
                    bad.append((kind, r.returncode, sentinel_ok, dir_ok, nothing_made, replaced, r.stderr[-200:]))
            check(f"9. (review, defect 1, {shell}) {name} coming in, as written, with a link planted at its name in the "
                  "agent's folder (to a file, to a folder, dangling): the target is never written, and the link itself "
                  "is replaced or the command fails", script is not None and not bad, bad)
            # And a normal transfer still works, checks UTF-8 and size, and leaves nothing in the owner's folder.
            results = {}
            for what, data, want in (("a short UTF-8 file", good.encode(), True),
                                     ("invalid UTF-8", head + b"x \xff\n", False),
                                     ("over 16 KiB", head + b"x" * 16385, False)):
                home = fresh_home(tmp, f"in-{shell}-{name}-{what.replace(' ', '-')}")
                fx = home.parent / "fixture"
                fx.write_bytes(data)
                r, _ = run_transfer(script or "false", shell, home, fixture=fx)
                dest = home / "qpcp-relay" / name
                got = (f"{name}: ok" in r.stdout and dest.is_file() and dest.read_bytes() == data)
                results[what] = (got == want and (want or not dest.exists()) and no_staging(home))
            check(f"9. (review, defect 1, {shell}) {name} coming in, as written: a short UTF-8 file arrives; invalid "
                  "UTF-8 or over 16 KiB never reaches the agent's folder; the owner's temporary folder is removed",
                  script is not None and all(results.values()), results)

        # Going out: only the checked copy is sent, and never through a link.
        bad = []
        for kind in ("a link to a file", "a link to a folder", "a dangling link"):
            home = fresh_home(tmp, f"out-{shell}-{kind.replace(' ', '-')}")
            plant(home, "S031.lean.txt", kind)
            r, sent = run_transfer(out_step or "false", shell, home)
            if sent is not None or r.returncode == 0:
                bad.append((kind, r.returncode, sent))
        home = fresh_home(tmp, f"out-{shell}-fifo")
        os.mkfifo(home / "qpcp-relay" / "S031.lean.txt")
        r, sent = run_transfer(out_step or "false", shell, home)
        if sent is not None or r.returncode in (0, 124):
            bad.append(("a FIFO", r.returncode, sent))
        check(f"9. (review, outbound, {shell}) the candidate going out, as written, with a link (to a file, to a folder, "
              "dangling) or a FIFO at its name: nothing is sent, nothing hangs, and the command fails",
              out_step is not None and not bad, bad)
        home = fresh_home(tmp, f"out-{shell}-swap")
        cand = "import QPCP.Statements\n-- ψ candidate\n".encode()
        (home / "qpcp-relay" / "S031.lean.txt").write_bytes(cand)
        r, sent = run_transfer(out_step or "false", shell, home, swap=True)
        sha = hashlib.sha256(cand).hexdigest()
        check(f"9. (review, outbound, {shell}) the bytes sent are the bytes checked and hashed, even if the agent "
              "rewrites its file while the owner reads: the guest gets the checked copy, whose SHA-256 was printed",
              out_step is not None and sent == cand and sha in r.stdout
              and no_staging(home), (r.returncode, sent, r.stdout[-300:]))


# ------------------------------------------------------------ 10. the #173 guide round

def test_round3(tmp):
    join = (ROOT / "JOIN.md").read_text()
    at = join.find("### Owner-relayed pilot")
    pilot = join[at:join.index("## Which revision")] if at > 0 else ""
    f = flat(pilot)
    step6 = pilot_step(pilot, "\n6. ", "\n7. ")
    step4 = pilot_step(pilot, "4. When the agent", "5. Check it")
    for shell in shells() or ["bash"]:
        # Step 6: only a complete result for the candidate sent is delivered.
        cases = {"missing in the guest": None, "empty": b"", "without the sha line": b"source scan passed\n",
                 "for another candidate": f"candidate sha256: {'0' * 64}\nsource scan passed\n".encode(),
                 "with nothing recorded at step 4": FIRST + b"source scan passed\n"}
        bad = {}
        for what, data in cases.items():
            home = fresh_home(tmp, f"r3-{shell}-{what.replace(' ', '-')}")
            if what == "with nothing recorded at step 4":
                (home / "qpcp-owner" / "S031.sent.sha256").unlink()
            fx = home.parent / ("nothing-there" if data is None else "fixture")
            if data is not None:
                fx.write_bytes(data)
            r, _ = run_transfer(step6 or "false", shell, home, fixture=fx)
            dest = home / "qpcp-relay" / "S031.result.txt"
            if not (r.returncode != 0 and "STOP: the result is not ready" in r.stdout and not dest.exists()
                    and not dest.is_symlink() and no_staging(home)):
                bad[what] = (r.returncode, r.stdout[-160:])
        home = fresh_home(tmp, f"r3-{shell}-good")
        fx = home.parent / "fixture"
        fx.write_bytes(FIRST + b"source scan passed\nLean build passed\n")
        r, _ = run_transfer(step6 or "false", shell, home, fixture=fx)
        dest = home / "qpcp-relay" / "S031.result.txt"
        good = (r.returncode == 0 and "S031.result.txt: ok" in r.stdout and dest.is_file()
                and dest.read_bytes() == fx.read_bytes())
        check(f"10. (#173 h, {shell}) step 6 refuses a result that is missing, empty, without its \"candidate "
              "sha256:\" line, for another candidate, or with nothing recorded at step 4 (STOP, wait for step 5, "
              "non-zero, nothing reaches the agent's folder), and delivers a result whose first line names the "
              "candidate step 4 sent", step6 is not None and not bad and good, (bad, good, r.stdout[-160:]))

        # Step 4: the staged copy never exceeds 16385 bytes; the SHA-256 sent is recorded, and only then.
        home = fresh_home(tmp, f"r3-{shell}-big")
        bindir = home.parent / "bin"
        bindir.mkdir(exist_ok=True)
        sizes = home.parent / "sizes"
        stub(bindir, "wc", f'"{shutil.which("wc")}" "$@" | tee -a "{sizes}"\n')
        (home / "qpcp-relay" / "S031.lean.txt").write_bytes(b"x" * 200000)
        r, sent = run_transfer(step4 or "false", shell, home)
        seen = [int(v) for v in sizes.read_text().split()] if sizes.exists() else []
        check(f"10. (#173 c, {shell}) a 200000-byte candidate: the staged copy holds at most 16385 bytes, and nothing "
              "is sent or recorded", seen and max(seen) <= 16385 and sent is None and r.returncode != 0
              and not (home / "qpcp-owner" / "S031.sent.sha256").exists(), (seen, r.returncode, sent))
        home = fresh_home(tmp, f"r3-{shell}-record")
        cand = "import QPCP.Statements\n-- ψ\n".encode()
        (home / "qpcp-relay" / "S031.lean.txt").write_bytes(cand)
        r, sent = run_transfer(step4 or "false", shell, home)
        rec = home / "qpcp-owner" / "S031.sent.sha256"
        check(f"10. (#173 h, {shell}) step 4 records the SHA-256 it sent, for step 6 to check against",
              r.returncode == 0 and sent == cand and rec.exists()
              and rec.read_text().strip() == hashlib.sha256(cand).hexdigest(), (r.returncode, rec.exists()))

    # Step 5: no empty result is visible while the build runs.
    blocks = blocks_after(pilot, "### Owner-relayed pilot") if pilot else []
    result_cmd = next((guest_script(b) for b in blocks if "S031.result.txt; cat" in b), None)
    w = tmp / "r3-step5"
    home, out, bindir = w / "home", w / "out", w / "bin"
    for d in (home / "qpcp-proofs" / "QPCP" / "Proofs", out, bindir, home / ".elan" / "bin"):
        d.mkdir(parents=True)
    (home / "qpcp-proofs" / "QPCP" / "Proofs" / "S031.lean").write_text("theorem S031 : QPCP.Statement.S031 := by\n  simp\n")
    (out / "S031.result.txt").write_text(f"candidate sha256: {'1' * 64}\nthe last candidate's result\n")
    stub(bindir, "python3", f'[ "$1" = -c ] && exec "{sys.executable}" "$@"\necho ACCEPTED\n')
    during = w / "during"
    stub(home / ".elan" / "bin", "lake", f'r="{out}/S031.result.txt"\n'
         f'if [ -e "$r" ] && [ ! -s "$r" ]; then echo empty >> "{during}"; '
         f'elif [ -e "$r" ]; then echo stale >> "{during}"; else echo absent >> "{during}"; fi\n'
         'echo "error: x"; exit 1\n')
    if result_cmd:
        text = result_cmd.replace("/tmp/scan.log", f"{w}/scan.log").replace("/tmp/build.log", f"{w}/build.log")
        text = text.replace("/out/", f"{out}/")
        subprocess.run(["bash", "-c", text], capture_output=True, timeout=60,
                       env=dict(os.environ, HOME=str(home), PATH=f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin"))
    seen = during.read_text().split() if during.exists() else []
    final = (out / "S031.result.txt").read_bytes() if (out / "S031.result.txt").exists() else b""
    check("10. (#173 h) step 5, run as written: while the build runs the guest's result name is neither empty nor the "
          "last candidate's result (it is absent), and the finished result appears under it, starting with its "
          "candidate sha256 line", seen == ["absent"] and final.startswith(b"candidate sha256: ")
          and not (out / ".S031.result.part").exists(), (seen, final[:80]))

    # The wording points and the observed result.
    two = join[join.index("## Two places"):join.index("## What your owner should know first")]
    setup = join[join.index("## Set up (once)"):join.index("## Practice run")]
    net = join[join.index("**The manual route, (b).**"):join.index("One documented example")]
    tested = join[join.index("**Tested so far:**"):join.index("## Network")]
    texts = {
        "(a) the owner-only folder is a workflow rule, resting on the agent's own restrictions":
            "keeping the agent out of it is a rule of this workflow, and holds only as far as the agent's own "
            "restrictions keep it out" in f,
        "(b) a real non-empty folder makes the rename fail, safely":
            "a real folder there, not empty, makes it fail with `Is a directory`, and nothing is delivered" in f,
        "(d) the relay folder is one the agent can already write; the tested way; stop otherwise":
            "must be one the agent can write in under its existing restrictions" in f
            and "The tested way is to open the agent with `~/qpcp-relay` as its working folder" in f
            and "If it cannot write there, stop: never change the agent's permissions" in f,
        "(e) an older guest runs the update flow first, and /out/base-commit then changes":
            "A guest built before this pilot existed has no `docs/pilot/S031.txt`" in f and "update flow" in f
            and "`/out/base-commit`, and so the sheet's `checkout commit:` line, is the new commit" in f,
        "(h) the agent reads the result only once told it is delivered; missing or empty is never passed":
            "Read `S031.result.txt` only after your owner tells you the result is delivered" in f
            and 'A missing or empty file means "not yet", never "passed"' in f,
        "(f1) less needs an interactive terminal; q lets the command go on":
            "it needs an interactive terminal, and pressing q quits it and lets the command go on" in f,
        "(f2) Two places gives the wrapped checks itself":
            "*Run in the guest (Lima, from the Mac):*" in two and "limactl shell qpcp -- ls /Users" in two,
        "(f3) Lima's harmless error line on stop":
            "`use of closed network connection`; it is harmless" in flat(two),
        "(f4) the owner's yes does not cover installing elan":
            "does not cover installing elan" in flat(two),
        "(f5) choosing an exercise is the Builder role":
            "Proving a step, an exercise included, is the Builder role" in flat(join),
        "(g) the setup script: the Lima form and the order before the block":
            "type the `pbpaste` line below, but do not press Return yet" in flat(net)
            and -1 < net.find("pbpaste > ~/qpcp-setup/setup.sh") < net.find("<<'SETUP'"),
        "(g) the UPDATE block: the Lima form and the order before the block":
            "type the `pbpaste` line below, but do not press Return yet" in flat(setup)
            and -1 < setup.find("pbpaste > ~/qpcp-setup/update.sh") < setup.find("<<'UPDATE'"),
        "Tested so far and the pilot: the relay completed for S031, one configuration, not submitted":
            "the \"Owner-relayed pilot\" (in \"Network\") then completed for S031" in flat(tested)
            and "the candidate has not been submitted" in flat(tested)
            and "the relay completed for S031, and candidate 1 passed the local scan and build. That is one "
                "configuration on one machine, and the candidate has not been submitted." in f
            and "This is a pilot, for exercises only, and currently for S031 only." in f,
    }
    for what, ok in texts.items():
        check(f"10. (#173) {what}", ok, "")


def main():
    print("A volunteer's first hour")
    try:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            test_stop(tmp)
            test_workspace(tmp)
            test_card()
            test_example()
            test_pins()
            test_bot(tmp)
            test_manual_route(tmp)
            test_pilot(tmp)
            test_sheet()
            test_transfers(tmp)
            test_round3(tmp)
    except Exception as e:  # a crash is a failure, never a skip
        check("the test ran to completion", False, repr(e))
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
