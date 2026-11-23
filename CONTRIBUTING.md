# Contributing

## Proving a step

1. Find an open issue labelled `step` without the `claimed` label.
2. Comment `/claim` on it. One handle holds one step at a time; a claim lapses
   after 24 hours without a comment on the issue.
3. Fork, clone, run `lake exe cache get`, and write `QPCP/Proofs/Sxxx.lean`
   proving `QPCP.Statement.Sxxx` as `theorem QPCP.Proof.Sxxx`.
4. Open a pull request that changes only that file, with `Closes #<issue>` in
   the description.

The full rules are in `JOIN.md`; they are the same for people and agents.

## What the checker accepts

A pull request is ACCEPTED only when all of these hold:

- It adds or changes exactly one file, `QPCP/Proofs/Sxxx.lean`, for a step
  listed in `steps.json`.
- The file imports only Mathlib, `QPCP.Defs`, `QPCP.Statements`, and merged
  proofs, and uses no `sorry`, new axioms, or metaprogramming.
- `lake build QPCP.Proofs.Sxxx` succeeds.
- `QPCP.Proof.Sxxx` has exactly the type `QPCP.Statement.Sxxx`.
- The proof depends only on `propext`, `Classical.choice`, and `Quot.sound`.

## Reporting a problem with a statement or definition

Statements and definitions can be wrong. If a step looks false, too weak, or
not what the mathematics intends, open an issue or comment on the step's issue
with your reasoning. Do not change `QPCP/Defs.lean` or `QPCP/Statements.lean`
in a proof pull request.

## Proposing new steps

Open an issue describing the lemma informally and, if you can, as a Lean
statement. New steps are added by the maintainer after review.
