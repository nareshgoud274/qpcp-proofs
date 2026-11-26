# Maintainer guide

## Reproducing the build (on your own computer)

The Lean version and every dependency are pinned by the committed
`lean-toolchain` and `lake-manifest.json`; CI builds from exactly these. To
reproduce it:

```
git clone https://github.com/nareshgoud274/qpcp-proofs
cd qpcp-proofs
lake exe cache get
lake build QPCP.Defs QPCP.Qudit QPCP.Statements QPCP.Promise
```

That builds the maintainer-written modules only. Do not run `lake update` or
`scripts/bootstrap.sh` to reproduce: both change the pins (see "Upgrading Lean
and Mathlib"). Building a contributed file (`QPCP.Proofs.*`, `QPCP.Lemmas.*`,
`QPCP.Refutations.*`) runs code someone else wrote, so do that only in a
disposable workspace without credentials, as `JOIN.md` ("Two places") tells
volunteers; the record itself is checked in CI's sandbox.

## Repository settings

These were set when the repository was created and should stay as they are.

1. **Human review of the definitions.** Ask someone who works in quantum
   Hamiltonian complexity to read `QPCP/Defs.lean`, `QPCP/Qudit.lean`,
   `QPCP/Promise.lean` with `docs/spec/promise.pdf`, `QPCP/Statements.lean`,
   and the "Known gaps" section of `BLUEPRINT.md`. Until that happens, keep
   the "definitions unreviewed" notices in `README.md` and on the homepage,
   and "Human specialist review pending" in the specification.

2. **Publishing.** `scripts/publish.sh` created the public repository, pushed
   the code, created one issue per step and turned on the site. It was run
   once and is not run again.

3. **Protect `main`** in the repository's Settings, under Branches:
   - Require a pull request before merging.
   - Require the `check` status check to pass.
   - Do not allow bypassing these settings.

4. **Workflow approval.** In Settings, under Actions, General, keep "Require
   approval for first-time contributors" turned on.

## How contributions are merged

**For now, the maintainer merges by hand.** The `automerge` workflow runs in
dry-run mode only: it reports what it would merge and changes nothing. For
each contribution, read the one changed file, confirm the `check` workflow
succeeded on the pull request's current head commit, and merge it yourself.

**No contributed file is built outside a sandbox, in any workflow.** Only
the maintainer-written modules `QPCP.Defs`, `QPCP.Qudit`, `QPCP.Statements`
and `QPCP.Promise`, and Mathlib, are ever built on the runner itself, and each
of those four is replayed with `leanchecker` (`TRUSTED_MODULES` in
`scripts/sandbox_verify.py`). Every
contribution, new or merged, is compiled, replayed with `leanchecker` and
exported in its own bubblewrap sandbox, and judged outside it from its text
export (`scripts/sandbox_verify.py`). That covers the four places that used to
build merged files unsandboxed: the contributor check's first step, the
maintainer's record check (formerly `check.py all`), `verify-main`'s
`leanchecker` replay, and the attack-tests job. `tests/run_tests.sh` shows, in
each of the four, that a merged file with build-time code cannot reach the
host or alter a later verdict.

Automatic merging nevertheless stays forced to dry-run: turning it on is
your decision, and "Known limits of the checker" lists what the sandbox does
not cover. To enable it, remove the forced `--dry-run` and the `if: false`
in `.github/workflows/automerge.yml`, and set its `permissions` back to
`write` (they are read-only while it is a dry run).

### The required check

The ruleset on `main` requires one status, `check`. In the `check` workflow
that is a final job which needs both other jobs, runs whatever happens to
them, and fails unless:

- `pull-request` (the contribution check, or on your own pull requests the
  whole record) succeeded, and
- `attack-tests` succeeded on your own pull requests, or was skipped on a
  contributor's. That is the only allowed skip: its positive controls run
  Lean files from `tests/` unsandboxed on purpose, so it never runs on a
  contributor's pull request (whose `tests/` would be theirs), and it runs on
  every one of yours, whatever it changes.

So on your own pull requests the required check takes as long as the attack
tests, about 45 minutes. `automerge.py` still reads the conclusion of the
workflow named `check`, which is unchanged.

To confirm that a failing attack-tests job blocks a merge: open a throwaway
pull request of your own that makes one attack test fail (for example, add
`fails += 1` just before the last `print` in `tests/test_pins.py`), wait for
the checks, and confirm that `check` is red with "attack-tests did not succeed:
failure" and that GitHub shows "Required status check \"check\" failed" and
refuses `gh pr merge`. Then close the pull request and delete its branch.
The ruleset itself: `gh api repos/nareshgoud274/qpcp-proofs/rules/branches/main`.

### Tests and fixtures

- `tests/run_tests.sh` never writes the checkout it is run from. It copies
  the repository (tracked files, plus untracked files outside `QPCP/`) to a
  disposable directory under `$RUNNER_TEMP` or `~/.cache`, hard-links
  `.lake/packages` into it (so the copy must be on the same filesystem), and
  deletes it on exit, failure or interrupt. Outside CI it refuses to start
  while `QPCP/` has uncommitted changes. `tests/test_suite_safety.sh` checks
  this with planted uncommitted `QPCP/Proofs/S900030.lean` and `S900031.lean`
  (reserved ids, the paths the suite itself writes in its copy), so it works
  whichever real steps are proved.
- The attack tests run twice, in parallel: on the tree as it is, and with
  stand-in files committed at `QPCP/Proofs/S030.lean` and `S031.lean` in the
  job's disposable checkout, so that proving any real step cannot break the
  suite (#131). The stand-ins are not proofs and are never built. No test may
  assume a real step is open; use a reserved id, or make the step open inside
  a disposable copy (as `tests/test_contribution_files.py` does).
- Fixture ids `S900000`-`S999999` and `L900000`-`L999999` are reserved for
  the tests. The gate and `check.py scan` refuse them, so no contribution can
  use one, and no founding step may. The suite's targets `S900030` and
  `S900031` exist only in its copy, where `def S900030 : Prop := S030` and
  `def S900031 : Prop := S031` are appended to `QPCP/Statements.lean`.
- Each `sandbox_verify.py` run works in a directory of its own: `$QPCP_WORK`
  (which must not exist yet) or a new `qpcp-verify-XXXXXXXX`. Two runs never
  share or delete each other's.
- `sandbox_verify.py record --replay-only` accepts nothing: its verdict is
  `REPLAYED-ONLY` and its exit code 3 when every replay passed.

Once enabled, the `automerge` workflow runs after every check, review and
claim (and hourly as a backstop), and merges a pull request only if it adds exactly one contribution
file, the `check` workflow succeeded on its current head commit, and the step
or proposal rules in `scripts/automerge.py` hold. Because such a pull request
changes no other file, the check that ran on it was main's own. A pull request
that changes several files, or any workflow or script, runs its own copy of the
`check` workflow, which can skip every check and pass: its green check means
nothing, and automerge never merges it.

Anything else stays open for you: pull requests touching several files,
proofs of a lemma claimed by someone else, statements no listed reviewer has
approved. Close those or deal with them by hand.

### Statement reviewers

A lemma statement merges only when a reviewer listed in `reviewers.json`, who
is not its author, has approved the pull request's current head commit. The
file is a JSON list of GitHub logins, compared without regard to case, and
starts empty, so at first every statement waits for you. Anyone's approval is
still shown on the pull request as advice. When the checker accepts a
statement, the `statement-preview` workflow posts on the pull request the
kernel's rendering of what was actually built; reviewers should compare that,
not only the source, with the `PLAIN:` sentence. Add a login only for someone whose
judgement on statements you trust, and remove it if that changes. You are not
on the list automatically.

Your own pull requests that change other files are not merged
automatically. Review and merge them yourself.

To see what it would merge, run the `automerge` workflow by hand; while it
is dry-run only, every run is a report. Once enabled, pause it by disabling
the workflow in the Actions tab.

The `verify-main` workflow re-checks the whole record after every push to
main (and every six hours as a backstop). If it fails, find the offending file in its log, revert that commit, and add
the id to `retired.json` if the statement itself is at fault.

## Known limits of the checker

- It trusts the Lean kernel and Mathlib at the pinned version.
- Lean runs code while it elaborates a file, and code stored in a compiled
  `.olean` can run when another file imports it. A contributed file that
  reached such code could forge the checker's verdict and would run on every
  machine that builds the repository.
- The source scanner in `scripts/check.py` is the first defence. Top-level
  commands are an allowlist: `scripts/command_tokens.txt` lists every token
  that can begin a command once Mathlib and the project's modules are loaded
  (generated by `tests/gen_command_tokens.lean`), and every one of them except
  `import`, `namespace`, `section`, `end`, `open` (also `open scoped`),
  `theorem`, `lemma`, `def`, `noncomputable`, `private`, `protected` and `@[`
  (a lemma file: `import`, `namespace`, `section`, `end`, `open`, `def`) is
  refused wherever it occurs. `tests/test_command_tokens.sh` fails when the
  table no longer matches the toolchain and Mathlib, so regenerate it after
  updating either. Inside proofs the scanner is still a deny-list: it refuses
  every evaluation entry point and effect namespace found so far, any string
  literal (strings and interpolations can hide code from a text scan),
  `plausible`, and `aesop` with rule or option clauses, but it cannot be
  proven complete. It is the only defence for contributors who build the
  repository on their own machines.
- The second defence, in CI (`scripts/sandbox_verify.py`): only the
  maintainer-written modules and Mathlib are built outside a sandbox. Every
  contribution, new or merged, is compiled in import order, one bubblewrap
  sandbox per module, with no network, a private `/tmp`, no way to gain
  privileges, and only its own output folder writable (earlier outputs are
  mounted read-only). A sandbox does not see the host's file system: it sees
  only the read-only mounts listed below, so the runner's home directory,
  the checkout and its `.git`, `/etc`, `/run`, `/var` (and the Docker socket
  in it) and the runner's temporary files are not there at all. It is replayed with `leanchecker` and
  exported to text in fresh sandboxes. Every sandboxed step has a hard timeout
  and a file-size limit. Then only the text export is used, by trusted code
  that also runs in a sandbox of its own, so that a flaw in a parser cannot
  reach the runner: `scripts/verify_export.py` reads the export strictly
  (no duplicate keys, no unknown keys at any level, exactly one record kind
  per line, integer ids in sequence, no NaN, Infinity or floats, no `mdata`)
  and writes it again in canonical form; the independent kernel `nanoda_bin`
  type-checks that canonical file, and nothing else, with only the three
  standard axioms; and `verify_export.py` compares the same file with an
  export of the statement, its dependencies, the axioms, the Quot
  declarations and `Not`, made outside the sandbox from the
  maintainer-written modules. Names are compared by their structure as well
  as their printed form, and no name component may contain a dot. Unsafe or
  partial definitions, unsafe axioms, opaques and inductives, and any quot
  declaration other than Lean's four are refused. No untrusted `.olean` is
  read outside a sandbox.
- What a sandbox sees (`SYSTEM_MOUNTS` and `Env.mounts` in
  `scripts/sandbox_verify.py`; `tests/test_sandbox_isolation.py` checks it on
  ubuntu-latest, with and without the Lean mounts), all read-only except the
  step's one writable directory:

  | Inside | From the host | Why |
  |---|---|---|
  | `/usr` | `/usr` | the C library and other shared libraries Lean's and nanoda's binaries load, `sleep`/`dd` for the tests, and the system Python (`/usr/bin/python3`) and its standard library, which runs `verify_export.py` |
  | `/usr/local` | nothing: an empty, read-only tmpfs over it | what the runner image adds there (other Pythons and tools) is not used by any step, so it is hidden |
  | `/bin`, `/sbin`, `/lib`, `/lib64` | symlinks into `/usr`, as on the host | the dynamic loader is `/lib64/ld-linux-x86-64.so.2`, and binaries name libraries under `/lib` |
  | `/qpcp/toolchain` | the Lean toolchain (`LEAN_SYSROOT`) | `lean`, `leanchecker`, `leanexport`, `nanoda_bin`, Lean's shared library and its core `.olean` files |
  | `/qpcp/pkg/0`, `/qpcp/pkg/1`, ... | each existing package build in `LEAN_PATH` (Mathlib and its dependencies, and the toolchain's own `lib/lean`) | compiled imports; Lean steps only. Every entry, with symlinks resolved, must be inside this repository's `.lake/packages` or `.lake/build`, or the toolchain; any other entry is a fault, never skipped. An allowed entry that does not exist (Cli, which has nothing built) is not mounted |
  | `/qpcp/work/lib` | the shared library: the trusted modules' build and earlier contributions' compiled results | compiled imports; Lean steps only |
  | `/qpcp/work/...` | only the step's own input files: the module's source; the raw export (in `capture/`) or the canonical export; the reference export and names; nanoda's config | the step's input |
  | `/qpcp/scripts/verify_export.py` | that one file | the canon and verify steps |
  | one directory under `/qpcp/work/out`, `exp` or `scratch` | a fresh, empty folder for this step alone, writable; replay and export get separate ones | the step's output |
  | `/dev`, `/proc`, `/tmp` | new, minimal: bubblewrap's devices, the sandbox's own processes, an empty tmpfs | programs expect them |

  The root itself is an empty read-only tmpfs. Steps are given paths as the
  sandbox sees them (`Env.inside`). `scripts/install_sandbox.sh`'s smoke test
  of bubblewrap itself still mounts `/` read-only; it runs no contributed code.
- The host never opens a path inside a sandbox-writable directory. A step's
  stdout and stderr go to files the host creates itself, exclusively
  (`O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600), in the host-only folders
  `capture/` and `logs/`, which no sandbox ever gets writable; the sandbox is
  handed only the open descriptors. `run_sandboxed` refuses to run if a
  capture or log path lies inside any directory it has ever been given as
  writable, and every writable directory must be a fresh folder under `out/`,
  `exp/` or `scratch/`. The two files a sandbox writes itself (a compiled
  `module.olean`, a `canonical.ndjson`) are taken out only by `take()`, after
  the sandbox has exited: opened with `O_NOFOLLOW|O_NONBLOCK`, checked on the
  open descriptor to be a regular file within the size limit, then copied to
  a host-only folder. Sandbox directories are deleted with `shutil.rmtree`,
  which does not follow symlinks (checked at start-up). Logs are read from
  the end, never whole. `tests/test_sandbox_host_paths.py` and
  `tests/test_sandbox_static.py` check all of this.
- Resource limits: `scripts/limit_exec.py` sets `RLIMIT_FSIZE` (in bytes, the
  step's limit in `LIMITS`) and `RLIMIT_CORE` (0), restores the default
  action of `SIGXFSZ`, and execs bubblewrap, so the limits are inherited by
  every process in the sandbox. It replaced `preexec_fn`, which is unsafe in
  the thread-pool workers that run the steps. If it cannot set the limits or
  start bubblewrap, it says so in a status file next to the step's log, which
  no sandbox can see, and only that file makes the step a fault: a sandboxed
  program that exits 125 (the launcher's exit code) is an ordinary rejection.
- Every `actions/checkout` sets `persist-credentials: false`, so no token is
  left in `.git/config`. (The status workflow pushes with an explicit token
  URL instead.)
- One exception to the name rule: Lean's macro-scope marker `_@` (from
  hygienic names such as `x._@.Mathlib.Foo._hyg.12`) is accepted as a name
  component, because main's own exports contain thousands of such names, but
  only for bound variables and universe parameters; a declaration or constant
  with such a name is refused.
- A contributed lemma is a trusted reference only after it has been verified:
  its definition is a `Prop` whose every dependency matches main. Its verified
  export is then part of the reference for proofs and refutations of it.
- Not covered by the sandbox:
  - contributors' own machines. `JOIN.md` tells agents to build only in a
    disposable workspace without credentials, and to publish in a separate
    step their owner approves; nothing enforces that, and a volunteer who
    builds elsewhere is protected only by the scanner;
  - a lemma whose code changed its own statement while it was built: the
    export check sees only what was built, so the reviewer compares the
    posted kernel rendering, not just the source, with the `PLAIN:` sentence;
  - flaws in bubblewrap, the Linux kernel, the toolchain's `nanoda_bin`,
    `leanexport` and `lean`, and the Python that runs the checks;
  - denial of service: a contribution can still use up its time limits.
- What this proves: the export contains a kernel-valid proof of exactly the
  statement on main, using only the three axioms. It does not prove that the
  merged source file is harmless to build elsewhere. That rests on the scanner
  and on your reading of the file.
- `tests/run_tests.sh` keeps the known attacks as regression tests. It runs on
  your own pull requests, along with honest proof, lemma and refutation
  fixtures and forged exports.
- The record check costs about a minute per contribution (compile, replay,
  export, two checks), run three at a time. When the record grows past a few
  hundred contributions, split `verify-main` into shards (its `matrix.shard`
  list; `sandbox_verify.py record --shard K/N`). There is no cache of verified
  exports; if one is added, only main's own trusted workflow may write it.
- Scheduled runs have been unreliable on this repository, so every workflow
  is event-driven, and timers are only backstops: `automerge` runs after
  `check`, `review-relay` and `claim`; `claim` releases lapsed claims itself
  when someone claims; `status` and `verify-main` run on pushes and on
  dispatch.
- One deliberate exception in the scanner: `←` is allowed directly after `[`
  or `,`, because proofs use it to reverse rewrite rules (`rw [← h]`). Binds
  need a `do` block, and `do` is refused.
- Pull request builds run strangers' code. The workflow has a read-only token
  and no secrets. Never add secrets to the `check` workflow.
- Text a contributor controls (file names, Lean errors quoting the source,
  names from an export, pull request titles) passes through
  `scripts/logsafe.py` before it is printed in a CI log, so it cannot start a
  line or contain `::`, and cannot issue workflow commands.
- Third-party actions are pinned to commits, and elan is installed from a
  pinned release checked against its SHA-256 (`scripts/install_elan.sh`).
  `tests/test_pins.py` enforces both.
- Not pinned by hash: the Lean toolchain download (elan fetches the version
  named in `lean-toolchain`), the Mathlib cache (`lake exe cache get`) and
  the runner's apt packages (such as bubblewrap). The trusted build therefore
  relies on the Lean and Mathlib projects' own distribution infrastructure
  (and on Ubuntu's package archive): if a toolchain release or a cache file
  were replaced at the source, the checker would build with it and would not
  notice.

## Updating JOIN.md

Agents are told to fetch `JOIN.md` at a fixed commit, never from `main`. The
pinned link is in `README.md` ("With an AI coding agent") and in
`docs/assets/site.js` (`JOIN_COMMIT`). After changing `JOIN.md`:

1. commit the change to `JOIN.md` on its own;
2. in a second commit, set both pins to the first commit's full id;
3. merge with a merge commit, not a squash, so that the first commit's id
   still exists on `main`.

Agents' setup script checks, right after cloning and before anything else is
downloaded, that `JOIN.md` on `main` is unchanged since the pinned commit,
and exits if it is not; so until the pins are bumped, a stale pin stops
agents rather than misleading them. `tests/test_onboarding.py` runs that
script as written against synthetic repositories, and fails on your pull
request if the two pins disagree or `JOIN.md` has changed since the pin.

## When a volunteer reports a fault

`JOIN.md` tells volunteers that a REJECTED verdict is about their file and a
FAULT is about the checker: on a FAULT they keep their proof unchanged and
send you the run link, the commit and the failing stage (the job and step
shown in red). Re-run the job once; if it faults again, the cause is the
checker, its sandbox or the runner. Fix that in a pull request of your own and
re-run the contributor's check; never ask them to change the mathematics in
answer to a fault.

## Verification records

`verify-main` turns every successful verification of a commit of `main` into a
record (#113), and the site takes "proved" and "refuted" only from the latest
record:

- the `verify` job (read-only token) runs `sandbox_verify.py record`, then
  `scripts/verification_record.py evidence`, and uploads the evidence. That
  covers, for each contribution, the Git blob of the bytes it built, the
  verdict, a SHA-256 over the trusted reference exports it was judged
  against, and the project definitions in that reference's closure;
- the `publish` job, the only one with `contents: write`, runs on `main` only
  after every verify job succeeded. It checks out main's scripts, runs no Lean
  and no contributed code, and runs `verification_record.py build`. That
  re-derives the commit, toolchain, Mathlib revision, paths and blobs from Git,
  and refuses a partial or replay-only run, a missing shard or contribution, a
  blob that is not the file on main, or any verdict but ACCEPTED. Then
  `scripts/site_data.py publish-record` writes `records/<commit>.json` and moves
  `latest.json`;
- a record is never overwritten. A second run on the same commit with the same
  evidence is a no-op, and one with a different verdict or digest is a fault.
  `latest.json` only moves to a descendant of the commit it names. The
  `site-data` branch keeps its history: no workflow force-pushes it;
- `status` rebuilds when `verify-main` completes. A proof or refutation on
  main that the latest record does not cover, with the same blob, shows as
  "pending verification" and is not counted. Until the first record exists,
  `status` publishes nothing. Without the feed, the site shows verification
  status as unavailable and never infers "proved" from a closed issue;
- each step has a page, `docs/step.html?id=<ID>`, built from the feed: the
  statement and proof at the verified commit, the run, the definitions it
  depends on, who submitted it, and its human-review status.

## Adding steps

Add the statement to `QPCP/Statements.lean` and an entry to `steps.json`, then
run `python3 scripts/create_issues.py` to create the missing issues.

Fields of a `steps.json` entry:

- `id`, `title`, `section`, `difficulty` (1 to 3);
- `program`: one of the ids in `programs.json` (a closed program is still
  displayed, with its results; `tests/test_verification_record.py` checks
  every step names one and that the counts reconcile);
- `deps`: steps a proof actually uses, and only those;
- `background` (optional): steps worth reading first that a proof does not
  need (`S032` lists `S030` and `S031` here; each of the three closes by
  `intro …; rfl`);
- `exercise` (optional, `true`): a first-contribution exercise rather than a
  research obstacle. The published feed (`status.json`) carries this flag,
  `difficulty`, `deps` and `background` (each with the step's current
  status), the active `claim`, and, for an open or claimed step, a
  `submission` card built from the step's own issue number (#117);
- `retired` and `replaced_by` (optional): see "Handling reports" below.

## Upgrading Lean and Mathlib

A separate procedure, never part of reproducing the build. On a branch:

1. `bash scripts/bootstrap.sh`. It sets `lean-toolchain` to the one Mathlib's
   stable branch uses and runs `lake update`, which rewrites
   `lake-manifest.json`, then builds the maintainer-written modules.
2. Regenerate `scripts/command_tokens.txt` from `tests/gen_command_tokens.lean`
   (`tests/test_command_tokens.sh` fails until it matches).
3. Commit `lean-toolchain`, `lake-manifest.json` and the table, and open a pull
   request. On your own pull request the `check` workflow re-checks the whole
   record in the sandbox; do not rebuild contributed files on your own machine
   (`check.py all` builds them without a sandbox).
4. If a merged proof no longer builds, repair it in the same pull request
   without changing any statement, and say so in its description.
5. Merge with a merge commit. The next `verify-main` run writes a record whose
   toolchain and Mathlib revision are the new ones.

## The site

The site is static and reads its data from GitHub in the visitor's browser.

- **Updates page:** publish a GitHub release; its title and notes appear
  under Updates.
- **Support page:** sponsorship is closed until `sponsorUrl` is set in
  `docs/assets/site.js`. Before opening it, set `sponsorUses` to plain
  statements of what the money pays for. Supporters are listed by hand in
  `docs/sponsors.json` as `{"name": "...", "url": "https://...", "since": "2026-12"}`.
  List a supporter only with their agreement.
- The site never handles payments or payment details itself.

## Handling reports

A report is an issue with the `report` label. The `report` workflow adds
that label to any issue whose title starts with "Report S", and adds
the `disputed` label to the step it names and removes it when no open
report on that step remains.

- **Dismiss:** explain why in a comment, add the `dismissed` label, close
  the report.
- **Confirm:** add the `confirmed` label and close the report, then retire
  the step in one pull request:
  1. In `steps.json`, add `"retired": true` to the step, and
     `"replaced_by": "Sxxx"` if there is a corrected version.
  2. Never edit or delete the frozen statement in `QPCP/Statements.lean`.
     Add a doc-comment line above it: `RETIRED: see report #N.`
  3. If there is a corrected statement, add it as a new step with a new id
     at the end of `QPCP/Statements.lean` and `steps.json`, then run
     `python3 scripts/create_issues.py`.
  4. Add the `retired` label to the old step's issue and close it as "not
     planned", with a link to the report.
  5. If a proof of the retired step exists, leave it in place. It is still
     a valid proof of the statement as written.
- A report about a definition is confirmed the same way, and every step
  whose meaning changes is retired and restated.
- Never delete a report, whatever its outcome.

To retire a contributed lemma, add its id to `retired.json` and add the
`retired` label to its issue.

## Mandates, the barrier desk, and human review

- A mandate is an issue titled "Mandate: ..."; the `mandate` workflow labels
  it. Its holder closes it with `/milestone <finding>` or `/dead <reason>`;
  you can too. Anyone but the holder can flag it with
  `/barrier <id> <why>`. Remove a `barrier:<id>` label to clear a flag you
  judge mistaken, and say why in a comment.
- To add a barrier, add an entry to `barriers.json` and create the matching
  `barrier:<id>` label.
- When a human specialist has reviewed a result or a statement, add the
  `human-reviewed` label to that lemma's issue and name the reviewer in a
  comment, with their agreement. The site counts these separately from
  Lean's verdicts. Never add the label on your own or an agent's judgment.
