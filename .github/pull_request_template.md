<!--
Keep the ONE section below that matches your pull request and delete the
other two. Copy the values from the step's submission card (its page on the
site, or `submission` in status.json) rather than typing them: a founding
step's issue number is not its id (S060 is issue #146).
-->

<!-- ===== A proof. Title: Prove <ID> ===== -->
Closes #<the step's issue number, from its submission card>

- [ ] This pull request adds exactly one file, `QPCP/Proofs/<ID>.lean`, and changes nothing else.
- [ ] `lake build QPCP.Proofs.<ID>` succeeds in a disposable workspace (JOIN.md, "Two places").
- [ ] No `sorry`, no new axioms, no metaprogramming.

<!-- ===== A refutation. Title: Refute <ID> ===== -->
Closes #<the step's issue number, from its submission card>

- [ ] This pull request adds exactly one file, `QPCP/Refutations/<ID>.lean`, proving `¬ <the statement>`, and changes nothing else.
- [ ] `lake build QPCP.Refutations.<ID>` succeeds in a disposable workspace.
- [ ] No `sorry`, no new axioms, no metaprogramming.

<!-- ===== A new statement. Title: State L<N> ===== -->
Proposal #<N>

<!-- Do NOT write "Closes": the proposal issue stays open after the statement
merges, so that someone can prove or refute it. -->

- [ ] This pull request adds exactly one file, `QPCP/Lemmas/L<N>.lean`, and comes from the account that opened issue #<N>.
- [ ] `lake build QPCP.Lemmas.L<N>` succeeds in a disposable workspace.
- [ ] I understand it opens only after a reviewer listed in `reviewers.json` approves it, and that none may be listed yet.
