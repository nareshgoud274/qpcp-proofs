# qpcp-proofs

An open, machine-checked effort to formalize the foundations around the
**quantum PCP conjecture** in Lean 4, built by people and AI coding agents.

**Contributing happens in a disposable workspace.** Everything, including
cloning and reading this repository, is done in a fresh container or virtual
machine with no credentials (`JOIN.md`, "Two places"). Contributed files are
code written by strangers, and building them runs it.

**One maintainer, manual merging.** The maintainer aims to respond to a pull
request within two days. After that, comment on the pull request; do not open
another.

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

- **With an AI coding agent:** first check that your machine can host the
  agent's workspace. This takes about a minute, in an ordinary terminal, in
  three separate steps. Download the script (any older copy is removed
  first, and the file gets its name only once it is complete, so a failed
  or interrupted download leaves nothing to run):

  ```
  mkdir -p ~/qpcp-setup && cd ~/qpcp-setup && rm -f workspace_check.sh workspace_check.sh.part
  curl -fsSL -o workspace_check.sh.part https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/c3fb1c2d71a971f75afe40566eaef04b6746c2b8/scripts/workspace_check.sh && mv workspace_check.sh.part workspace_check.sh
  ```

  Read it (`less ~/qpcp-setup/workspace_check.sh`): it installs nothing, and
  only looks, apart from one throwaway guest of its own, which it creates and
  deletes. The Ubuntu image that guest starts from stays for the workspace to
  reuse (with Lima, about 3 GB in Lima's cache, removed by `limactl prune`;
  with Docker, the `ubuntu:24.04` image, removed by `docker image rm
  ubuntu:24.04`). Then run it:

  ```
  cd ~/qpcp-setup && bash workspace_check.sh
  ```

  It checks for Docker or Lima, about 25 GB free (the workspace plus image
  downloads), an HTTPS request to github.com from your terminal, and, from
  inside a guest, that the download hosts' names resolve and their ports
  open. Every `FAIL` says what to do next; after fixing one, run it again. A
  Mac with neither Docker nor Lima can use a pinned, checksum-checked copy of
  Lima without installing anything system-wide (JOIN.md, "A machine with
  nothing installed"). If your agent's own terminal cannot reach github.com,
  the agent's sandbox may be blocking access; a working browser does not
  establish the cause (JOIN.md, "Network"). Then give it this instruction:

  ```
  Fetch and follow the instructions at
  https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/c3fb1c2d71a971f75afe40566eaef04b6746c2b8/JOIN.md
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
