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
"""

import importlib.util
import json
import os
import re
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
    except Exception as e:  # a crash is a failure, never a skip
        check("the test ran to completion", False, repr(e))
    print(f"{'FAILED' if fails else 'passed'}: {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
