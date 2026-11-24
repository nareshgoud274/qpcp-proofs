# Maintainer guide

## First-time setup (once, on your own computer)

1. **Build.** Nothing in this repository has been compiled yet.

   ```
   bash scripts/bootstrap.sh
   ```

   This pins the Lean version to Mathlib's, downloads Mathlib, and builds
   `QPCP/Defs.lean` and `QPCP/Statements.lean`. Fix any errors before going
   further. Fixes must not change what a statement means.

2. **Get the definitions reviewed.** Ask someone who works in quantum
   Hamiltonian complexity to read `QPCP/Defs.lean`, `QPCP/Statements.lean`,
   and the "Known gaps" section of `BLUEPRINT.md`. Until that happens, keep
   the "definitions unreviewed" notice in `README.md`.

3. **Publish.**

   ```
   bash scripts/publish.sh
   ```

   This creates the public repository `qpcp-proofs` under your GitHub account,
   pushes the code, creates one issue per step, and turns on the project site.

4. **Protect `main`** in the repository's Settings, under Branches:
   - Require a pull request before merging.
   - Require the `check` status check to pass.
   - Do not allow bypassing these settings.

5. **Workflow approval.** In Settings, under Actions, General, keep "Require
   approval for first-time contributors" turned on.

## How contributions are merged

**For now, the maintainer merges by hand.** The `automerge` workflow runs in
dry-run mode only: it reports what it would merge and changes nothing. For
each contribution, read the one changed file, confirm the `check` workflow
succeeded on the pull request's current head commit, and merge it yourself.

**No contributed file is built outside a sandbox, in any workflow.** Only
the maintainer-written modules `QPCP.Defs`, `QPCP.Qudit` and
`QPCP.Statements`, and Mathlib, are ever built on the runner itself. Every
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
in `.github/workflows/automerge.yml`.

Once enabled, the `automerge` workflow runs after every check, review and
claim (and hourly as a backstop), and merges a pull request only if it adds exactly one contribution
file, the `check` workflow succeeded on its current head commit, and the step
or proposal rules in `scripts/automerge.py` hold. Because such a pull request
changes no other file, the check that ran on it was main's own.

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
- The source scanner in `scripts/check.py` is the first defence. It is a
  deny-list: it refuses every evaluation entry point and effect namespace
  found so far, and any string literal (strings and interpolations can hide
  code from a text scan), but it cannot be proven complete. It is the only
  defence for contributors who build the repository on their own machines.
- The second defence, in CI (`scripts/sandbox_verify.py`): only the
  maintainer-written modules and Mathlib are built outside a sandbox. Every
  contribution, new or merged, is compiled in import order, one bubblewrap
  sandbox per module, with no network, a read-only system, a private `/tmp`,
  no way to gain privileges, and only its own output folder writable (earlier
  outputs are mounted read-only). It is replayed with `leanchecker` and
  exported to text in fresh sandboxes. Every sandboxed step has a hard timeout
  and a file-size limit. Outside the sandbox, only the text exports are used:
  the independent kernel `nanoda_bin` type-checks each with only the three
  standard axioms, and `scripts/verify_export.py` compares it with an export
  of the statement, its dependencies and the axioms made from the
  maintainer-written modules. No untrusted `.olean` is read outside a sandbox.
- A contributed lemma is a trusted reference only after it has been verified:
  its definition is a `Prop` whose every dependency matches main. Its verified
  export is then part of the reference for proofs and refutations of it.
- Not covered by the sandbox:
  - contributors' own machines, which build contributed files with plain
    `lake build`; only the scanner, and JOIN.md's warning, protect them;
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

## Adding steps

Add the statement to `QPCP/Statements.lean` and an entry to `steps.json`, then
run `python3 scripts/create_issues.py` to create the missing issues.

## Updating Mathlib

Run `bash scripts/bootstrap.sh` again on a branch, rebuild everything with
`python3 scripts/check.py all`, repair any proofs that broke, and merge.

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
