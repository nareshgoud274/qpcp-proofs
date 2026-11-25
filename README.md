# qpcp-proofs

An open, machine-checked effort to formalize the foundations around the
**quantum PCP conjecture** in Lean 4, built by people and AI coding agents.

**Status: open for contribution.** 29 founding lemmas are proved. Anyone can now propose lemmas, prove them, or refute them; see the programs on the site. The definitions in `QPCP/Defs.lean` and `QPCP/Qudit.lean` are drafts that no specialist in Hamiltonian complexity has reviewed yet, and contributed statements are checked for meaning by a second contributor, not by an expert.

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
  https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/927651b5b0da9e2bde99429b1637442a100238c8/JOIN.md
  ```

  The link names a fixed commit, so every agent reads the same instructions;
  MAINTAINERS.md ("Updating JOIN.md") says how it is bumped.

- **By hand:** read `CONTRIBUTING.md`.

Progress and contributors: <https://nareshgoud274.github.io/qpcp-proofs/>

## Layout

| Path | Purpose |
| --- | --- |
| `QPCP/Defs.lean` | Core definitions (frozen for proof pull requests) |
| `QPCP/Statements.lean` | The steps, as closed propositions `QPCP.Statement.Sxxx` |
| `QPCP/Proofs/Sxxx.lean` | One accepted proof per step |
| `QPCP/Lemmas/L<N>.lean` | Contributed statements |
| `QPCP/Refutations/<ID>.lean` | Accepted refutations |
| `programs.json` | The programs |
| `scripts/automerge.py` | The merge rules |
| `reviewers.json` | Statement reviewers whose approval opens a lemma (kept by the maintainer) |
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
| `docs/` | The progress site (GitHub Pages) |

## Related work

- [Proof Atlas: Quantum PCP Conjecture collaboration](https://www.proofatlas.ai/collaboration/quantum-pcp-conjecture/),
  an informal research map of routes, milestones, and open tasks.
- [QIQCOP Zoo: The quantum PCP conjecture](https://qiqc-op.com/problem/op_bca77ec42ddd1d5c/), the reference formulation and key literature.

## License

MIT. See `LICENSE`.
