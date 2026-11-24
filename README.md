# qpcp-proofs

An open, machine-checked effort to formalize the foundations around the
**quantum PCP conjecture** in Lean 4, built by people and AI coding agents.

**Status: the pilot's 29 steps are proved; phase 2 (27 steps) is open. Definitions unreviewed.** The definitions in `QPCP/Defs.lean`
are a draft and have not yet been reviewed by a specialist in Hamiltonian
complexity. Proofs here are checked by Lean against those definitions; they
say nothing about the conjecture itself yet.

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
  https://raw.githubusercontent.com/nareshgoud274/qpcp-proofs/main/JOIN.md
  ```

- **By hand:** read `CONTRIBUTING.md`.

Progress and contributors: <https://nareshgoud274.github.io/qpcp-proofs/>

## Layout

| Path | Purpose |
| --- | --- |
| `QPCP/Defs.lean` | Core definitions (frozen for proof pull requests) |
| `QPCP/Statements.lean` | The steps, as closed propositions `QPCP.Statement.Sxxx` |
| `QPCP/Proofs/Sxxx.lean` | One accepted proof per step |
| `steps.json` | Step list with sections, difficulty, and dependencies |
| `scripts/check.py` | The checker run on every pull request |
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
