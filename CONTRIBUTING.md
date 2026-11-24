# Contributing

There are four ways to contribute. `JOIN.md` has the exact commands; they are
the same for people and for AI agents.

| | What you do | What you add |
| --- | --- | --- |
| **Prove** | Claim an open lemma and prove it | `QPCP/Proofs/<ID>.lean` |
| **Refute** | Claim an open lemma and prove it false | `QPCP/Refutations/<ID>.lean` |
| **Propose** | State a new lemma for one of the programs | `QPCP/Lemmas/L<N>.lean` |
| **Review** | Check that someone else's proposed statement says what its plain sentence says | An approving review on their pull request |

Lemma ids: founding steps are `S001`, `S002`, ... and are stated in
`QPCP/Statements.lean`. Contributed lemmas are `L<N>`, where `N` is the number
of the lemma's issue.

## What the checker accepts

A pull request is ACCEPTED only when all of these hold:

- It adds exactly one new file of one of the three kinds above and changes
  nothing else.
- The file uses only allowed imports, and no `sorry`, new axioms, or
  metaprogramming.
- It builds under the pinned Lean and Mathlib.
- A proof has exactly the statement as its type; a refutation has exactly its
  negation.
- It depends only on `propext`, `Classical.choice`, and `Quot.sound`.
- A lemma file names an open program, gives the statement in plain words, and
  contains exactly one definition, of type `Prop`.

For now the maintainer merges accepted contributions by hand, after reading
the one changed file; automatic merging is switched off while the checker is
hardened. An accepted lemma is merged only after a reviewer listed in
`reviewers.json` (kept by the maintainer) other than its author has approved
it. Anyone else's approval is advice: it helps, but the statement waits for the
maintainer.

## Reviewing a statement

The checker cannot tell whether a Lean statement means what its plain sentence
says. That is the reviewer's job, and the project depends on it being done
honestly. Once the checker accepts a statement, it posts the kernel's
rendering of what was built; compare that, as well as the source, with the
plain sentence. Check quantifiers, hypotheses and edge cases; check that the claim is
not vacuous, not a duplicate, and serves its program. Approve only what you
have checked. Do not review your own proposals from another account.

Every honest review is welcome, but only an approval from a reviewer listed in
`reviewers.json` opens a statement. Other approvals are advisory, and such a
statement waits for the maintainer. The maintainer adds reviewers to that list
by hand.

## Reporting a problem with a statement or definition

A lemma that is false should be refuted in Lean. For a lemma that is true but
says the wrong thing, or a definition that looks wrong, use the "Report a
statement" issue form with the id in the title (`Report L123: ...`). The lemma
is marked as under review on the site until the report is resolved, and every
report stays in the public record whatever the outcome.

## What contributors cannot change

Definitions (`QPCP/Defs.lean`, `QPCP/Qudit.lean`), founding statements
(`QPCP/Statements.lean`), merged files, the checker, and the workflows. To
propose a new definition or a new program, open an issue describing it; those
are added by the maintainer after specialist review.
