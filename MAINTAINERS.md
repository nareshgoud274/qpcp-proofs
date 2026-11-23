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

## Merging a proof pull request

Before approving a workflow run or merging, open the pull request's "Files
changed" tab and confirm:

- Exactly one file changed, and it is `QPCP/Proofs/Sxxx.lean`.
- Nothing under `.github/`, `scripts/`, `QPCP/Defs.lean`,
  `QPCP/Statements.lean`, `steps.json`, or the Lake files changed.

Then merge only if `check` is green. This manual look matters: a pull request
can edit the workflow that checks it, and the green mark alone would not show
that. After the merge, `verify-main` re-checks every proof with the checker on
`main`. If it fails, revert the merge.

## Known limits of the checker

- It trusts the Lean kernel and Mathlib at the pinned version.
- The text scan for forbidden keywords is a guard, not a proof of safety. The
  binding checks are the exact-type check and the axiom report.
- Pull request builds run strangers' code. The workflow has a read-only token
  and no secrets. Never add secrets to the `check` workflow.
- An independent re-check of compiled proofs with an external kernel checker is
  a worthwhile later addition.

## Adding steps

Add the statement to `QPCP/Statements.lean` and an entry to `steps.json`, then
run `python3 scripts/create_issues.py` to create the missing issues.

## Updating Mathlib

Run `bash scripts/bootstrap.sh` again on a branch, rebuild everything with
`python3 scripts/check.py all`, repair any proofs that broke, and merge.
