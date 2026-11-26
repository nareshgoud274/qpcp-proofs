# qpcp-proofs

An open, machine-checked effort to formalize the foundations around the
**quantum PCP conjecture** in Lean 4, built by people and AI coding agents.

**Status: open for contribution.** The current counts are on the
[site](https://nareshgoud274.github.io/qpcp-proofs/). What can be accepted
today: proofs and refutations of the existing open steps. A new statement
opens only after a reviewer listed in `reviewers.json` approves it, and none
is listed yet, so proposals wait.

## The precise question

Are there fixed integers q, k ≥ 2 and constants 0 ≤ a < b ≤ 1 for which the
following problem is QMA-hard? Given m = poly(n) terms on n qudits of local
dimension q, each positive semidefinite, bounded above by the identity, and
acting on at most k qudits, decide whether the smallest eigenvalue of their
sum is at most a·m or at least b·m.

- The promise problem in this question, with its exact input encoding, is
  specified in [`docs/spec/promise.pdf`](docs/spec/promise.pdf) (source
  [`promise.tex`](docs/spec/promise.tex)) and formalized in
  [`QPCP/Promise.lean`](QPCP/Promise.lean).
- Its first end-to-end result, the classical case, is
  [S059](https://nareshgoud274.github.io/qpcp-proofs/step.html?id=S059): the
  page shows the statement and proof at the verified commit and how they were
  checked.
- QMA, reductions and the conjecture itself are not formalized.

**Human review: none yet.** No human specialist has reviewed the
specification, `QPCP/Promise.lean`, or the definitions in `QPCP/Defs.lean` and
`QPCP/Qudit.lean`. Contributed statements are checked for meaning by a second
contributor, not by an expert. Lean checks that each proof proves its
statement; whether a statement means what it should is what awaits review.

## What this project is, and is not

- It **is** a library of small lemmas about local Hamiltonians, ground energy,
  and classical cost functions, each stated formally and proved one at a time
  by contributors. Every accepted proof is checked by the Lean kernel.
- It **is not** a proof of the quantum PCP conjecture, and it does not claim a
  route to one. The conjecture is open. See `BLUEPRINT.md` for what the pilot
  covers and what would come after it.

## Contribute

- **With an AI coding agent:** give it this instruction:

  ```
  Fetch and follow the instructions at
  https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/1a5869585645f5de2e73ba40b3ba9fc983404808/JOIN.md
  ```

  The link names a fixed commit, so every agent reads the same instructions;
  MAINTAINERS.md ("Updating JOIN.md") says how it is bumped.

  The agent checks a practice result first, then works within a time or
  spend limit you set, and asks before anything it publishes under your
  account.

- **By hand:** read `CONTRIBUTING.md`.

Progress and contributors: <https://nareshgoud274.github.io/qpcp-proofs/>

## Layout

| Path | Purpose |
| --- | --- |
| `QPCP/Defs.lean` | Core definitions (frozen for proof pull requests) |
| `QPCP/Promise.lean` | The promise problem of `docs/spec/promise.pdf` |
| `QPCP/Statements.lean` | The steps, as closed propositions `QPCP.Statement.Sxxx` |
| `QPCP/Proofs/Sxxx.lean` | One accepted proof per step |
| `QPCP/Lemmas/L<N>.lean` | Contributed statements |
| `QPCP/Refutations/<ID>.lean` | Accepted refutations |
| `programs.json` | The programs |
| `scripts/automerge.py` | The merge rules |
| `reviewers.json` | Statement reviewers whose approval opens a lemma (kept by the maintainer; empty for now) |
| `scripts/sandbox_verify.py` | Sandboxed build and export check of contributions (new and merged) |
| `scripts/contribution_check.sh` | One new contribution, through `sandbox_verify.py` |
| `tests/` | Attack probes and honest fixtures the checker must reject or accept |
| `steps.json` | Step list with sections, difficulty, and dependencies |
| `scripts/check.py` | The checker run on every pull request |
| `scripts/verify_export.py` | Strict reading, canonical form and comparison of an export with main's |
| `scripts/command_tokens.txt` | Every token that can begin a command; the scanner allows only a few |
| `JOIN.md` | Instructions for AI agents |
| `BLUEPRINT.md` | Scope of the pilot and the road beyond it |
| `MAINTAINERS.md` | Setup and merge rules for the maintainer |
| `REPRODUCE.md` | Re-running one result's sandboxed check on Linux |
| `docs/` | The progress site (GitHub Pages) |

## Related work

- [Proof Atlas: Quantum PCP Conjecture collaboration](https://www.proofatlas.ai/collaboration/quantum-pcp-conjecture/),
  an informal research map of routes, milestones, and open tasks.
- [QIQCOP Zoo: The quantum PCP conjecture](https://qiqc-op.com/problem/op_bca77ec42ddd1d5c/), the reference formulation and key literature.

## License

MIT. See `LICENSE`.
