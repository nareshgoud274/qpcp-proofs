# Blueprint

## The conjecture, informally

The quantum PCP conjecture asks whether estimating the ground energy of a
local Hamiltonian remains QMA-hard when the locality is a fixed constant and
the gap between the yes and no thresholds is a fixed constant fraction of the
number of terms. It is open.

This repository does not contain a formal statement of the conjecture yet.
Stating it needs complexity classes (QMA, reductions) that the pilot does not
define.

The target formulation for this project is the one recorded in the QIQCOP Zoo (https://qiqc-op.com/problem/op_bca77ec42ddd1d5c/): n qudits of local dimension q, m = poly(n) positive semidefinite terms each bounded by the identity and acting on at most k qudits, with thresholds a·m and b·m for constants a < b. The "Known gaps" below are measured against that formulation.

## Pilot scope: foundations

The pilot has 29 steps in five sections. See `steps.json` and
`QPCP/Statements.lean`.

| Section | Steps | Content |
| --- | --- | --- |
| Locality | S001 to S010 | Operators acting on a set of qubits: closure under sums, products, adjoints; disjoint supports commute |
| Local Hamiltonians | S011, S012 | Hermiticity; monotonicity in the locality |
| States and energy | S013 to S018 | Normalized vectors, expectation values, boundedness |
| Ground energy | S019 to S025 | Lower bound, superadditivity, scaling, shift, attainment, eigenvalue |
| Classical cost functions | S026 to S029 | Diagonal Hamiltonians; ground energy equals minimum cost |

The last section is the bridge to the classical setting: a constraint
satisfaction problem is a diagonal local Hamiltonian, and its ground energy is
the minimum number of violated constraints.

## Phase 2 scope

| Section | Steps | Content |
| --- | --- | --- |
| Bridge to general index types | S030 to S033 | Phase 1 notions agree with the general ones |
| Ground energy, general | S034 to S043 | Bounds, attainment, monotonicity, diagonal operators |
| Qudit locality | S044 to S048 | Locality for local dimension q |
| Normalized Hamiltonians | S049 to S056 | Terms between 0 and 1, the relative gap, classical terms |

## Known gaps in the draft definitions

These need a decision by a specialist reviewer before the project grows:

- **Normalization.** The conjecture is stated for terms of bounded norm with
  the gap measured relative to the number of terms. `LocalTerm` has no norm
  bound, and `YesInstance` / `NoInstance` use absolute thresholds.
- **Qubits only.** Local dimension is fixed to 2; qudits are not covered.
- **Terms as a list.** A Hamiltonian is a list of terms, so the number of terms
  is `terms.length`; weighted Hamiltonians are not modelled.
- **No complexity classes.** QMA, promise problems as languages, and
  reductions are not defined.
- **Reuse.** Existing Lean quantum information libraries may already provide
  reviewed versions of some of these notions. Building on them is preferable
  to maintaining separate definitions.

Normalization, qudits, and the relative gap are now drafted in
`QPCP/Qudit.lean` and await review.

## After the pilot

In rough order of size. Each needs its own blueprint written with a specialist.

1. Review and fix the definitions; add normalization and the relative gap.
2. Tensor product structure: partial trace, reduced states, product states.
3. Commuting and stabilizer Hamiltonians; quantum error-correcting codes.
4. A formal statement of the local Hamiltonian problem and of the conjecture.
5. Known theorems: QMA-completeness of the local Hamiltonian problem (Kitaev);
   the NLTS theorem (Anshu, Breuckmann, Nirkhe).

For the research frontier itself, see the informal map at
[Proof Atlas](https://www.proofatlas.ai/collaboration/quantum-pcp-conjecture/).
