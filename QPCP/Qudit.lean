import QPCP.Defs

/-!
# QPCP phase 2: qudits, normalized terms, and the relative gap

STATUS: DRAFT. Not yet reviewed by a specialist in Hamiltonian complexity.

These definitions follow the reference formulation of the quantum PCP
conjecture: `n` qudits of local dimension `q`, `m` terms that are positive
semidefinite, bounded above by the identity, and act on at most `k` qudits,
with thresholds `a * m` and `b * m`.

The energy notions are stated for an arbitrary finite index type, so they apply
to qubits (phase 1) and qudits alike.
-/

namespace QPCP

open Matrix

noncomputable section

/-! ## Energy over an arbitrary finite index type -/

/-- `ψ` is a normalized vector. -/
def IsStateOn {ι : Type} [Fintype ι] (ψ : ι → ℂ) : Prop :=
  dotProduct (star ψ) ψ = 1

/-- The energy `⟨ψ| A |ψ⟩` (real part). -/
def energyOn {ι : Type} [Fintype ι] (A : Matrix ι ι ℂ) (ψ : ι → ℂ) : ℝ :=
  (dotProduct (star ψ) (A.mulVec ψ)).re

/-- The ground energy: the infimum of the energy over normalized vectors. -/
def groundEnergyOn {ι : Type} [Fintype ι] (A : Matrix ι ι ℂ) : ℝ :=
  sInf (energyOn A '' {ψ | IsStateOn ψ})

/-! ## Qudits -/

/-- Classical configurations of `n` qudits of local dimension `q`. -/
abbrev QConfig (q n : ℕ) : Type := Fin n → Fin q

/-- Operators on `n` qudits of local dimension `q`. -/
abbrev QOp (q n : ℕ) : Type := Matrix (QConfig q n) (QConfig q n) ℂ

/-- Configurations of the qudits lying in `S`. -/
abbrev QSubConfig (q : ℕ) {n : ℕ} (S : Finset (Fin n)) : Type :=
  {i : Fin n // i ∈ S} → Fin q

/-- Restriction of a configuration to the qudits in `S`. -/
def qrestrict {q n : ℕ} (S : Finset (Fin n)) (x : QConfig q n) : QSubConfig q S :=
  fun i => x i.1

/-- Two configurations agree on every qudit outside `S`. -/
def QAgreeOff {q n : ℕ} (S : Finset (Fin n)) (x y : QConfig q n) : Prop :=
  ∀ i : Fin n, i ∉ S → x i = y i

/-- `A` acts nontrivially only on the qudits in `S`. -/
def QActsOn {q n : ℕ} (S : Finset (Fin n)) (A : QOp q n) : Prop :=
  ∃ a : Matrix (QSubConfig q S) (QSubConfig q S) ℂ, ∀ x y : QConfig q n,
    (QAgreeOff S x y → A x y = a (qrestrict S x) (qrestrict S y)) ∧
    (¬ QAgreeOff S x y → A x y = 0)

/-! ## Normalized local Hamiltonians -/

open scoped ComplexOrder in
/-- A term `0 ≤ op ≤ 1` acting on at most `k` of the `n` qudits. -/
structure NormalizedTerm (q n k : ℕ) where
  /-- The qudits the term acts on. -/
  support : Finset (Fin n)
  /-- The term touches at most `k` qudits. -/
  card_le : support.card ≤ k
  /-- The term as an operator on all `n` qudits. -/
  op : QOp q n
  /-- The term is positive semidefinite. -/
  posSemidef : op.PosSemidef
  /-- The term is bounded above by the identity. -/
  le_one : (1 - op).PosSemidef
  /-- The term acts only on its support. -/
  actsOn : QActsOn support op

/-- A normalized `k`-local Hamiltonian on `n` qudits of local dimension `q`. -/
structure NormalizedHamiltonian (q n k : ℕ) where
  /-- The local terms. -/
  terms : List (NormalizedTerm q n k)

/-- The Hamiltonian as a single operator: the sum of its terms. -/
def NormalizedHamiltonian.toOp {q n k : ℕ} (H : NormalizedHamiltonian q n k) : QOp q n :=
  (H.terms.map NormalizedTerm.op).sum

/-- The number of terms `m`. -/
def NormalizedHamiltonian.numTerms {q n k : ℕ} (H : NormalizedHamiltonian q n k) : ℕ :=
  H.terms.length

/-- Yes-instance with relative threshold `a`: ground energy at most `a * m`. -/
def RelYes {q n k : ℕ} (H : NormalizedHamiltonian q n k) (a : ℝ) : Prop :=
  groundEnergyOn H.toOp ≤ a * (H.numTerms : ℝ)

/-- No-instance with relative threshold `b`: ground energy at least `b * m`. -/
def RelNo {q n k : ℕ} (H : NormalizedHamiltonian q n k) (b : ℝ) : Prop :=
  b * (H.numTerms : ℝ) ≤ groundEnergyOn H.toOp

end

end QPCP
