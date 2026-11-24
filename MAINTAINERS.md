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
