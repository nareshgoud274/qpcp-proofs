import QPCP.Statements

namespace QPCP.Proof

namespace S024

open QPCP Matrix

/-- The set of normalized vectors. -/
def states (n : ℕ) : Set (Config n → ℂ) := {ψ | IsState ψ}

lemma dot_self_eq (n : ℕ) (ψ : Config n → ℂ) :
    dotProduct (star ψ) ψ = ∑ x, ((‖ψ x‖ ^ 2 : ℝ) : ℂ) := by
  unfold dotProduct
  refine Finset.sum_congr rfl fun x _ => ?_
  simp [Complex.mul_conj', mul_comm]

lemma isClosed_states (n : ℕ) : IsClosed (states n) := by
  have : states n = (fun ψ : Config n → ℂ => ∑ x, star (ψ x) * ψ x) ⁻¹' {1} := by
    ext ψ; simp [states, IsState, dotProduct]
  rw [this]
  exact isClosed_singleton.preimage (by fun_prop)

lemma norm_le_one {n : ℕ} {ψ : Config n → ℂ} (h : IsState ψ) (x : Config n) :
    ‖ψ x‖ ≤ 1 := by
  have h1 : ∑ y, ‖ψ y‖ ^ 2 = 1 := by
    have := h
    unfold IsState at this
    rw [dot_self_eq] at this
    exact_mod_cast this
  have h2 : ‖ψ x‖ ^ 2 ≤ 1 := by
    rw [← h1]
    exact Finset.single_le_sum (f := fun y => ‖ψ y‖ ^ 2) (fun y _ => by positivity)
      (Finset.mem_univ x)
  nlinarith [norm_nonneg (ψ x)]

lemma isBounded_states (n : ℕ) : Bornology.IsBounded (states n) := by
  refine (Metric.isBounded_closedBall (x := (0 : Config n → ℂ)) (r := 1)).subset ?_
  intro ψ hψ
  rw [Metric.mem_closedBall, dist_zero_right]
  exact (pi_norm_le_iff_of_nonneg zero_le_one).2 (norm_le_one hψ)

lemma isCompact_states (n : ℕ) : IsCompact (states n) :=
  Metric.isCompact_of_isClosed_isBounded (isClosed_states n) (isBounded_states n)

lemma states_nonempty (n : ℕ) : (states n).Nonempty := by
  refine ⟨Pi.single (fun _ => 0) 1, ?_⟩
  show dotProduct _ _ = 1
  simp [dotProduct, Pi.single_apply]

lemma continuous_energy {n : ℕ} (A : Op n) : Continuous (energy A) := by
  unfold energy dotProduct mulVec dotProduct
  fun_prop

lemma exists_min {n : ℕ} (A : Op n) :
    ∃ ψ ∈ states n, IsMinOn (energy A) (states n) ψ :=
  (isCompact_states n).exists_isMinOn (states_nonempty n)
    (continuous_energy A).continuousOn

end S024

theorem S024 : QPCP.Statement.S024 := by
  intro n A
  obtain ⟨ψ, hψ, hmin⟩ := S024.exists_min A
  refine ⟨ψ, hψ, ?_⟩
  unfold QPCP.groundEnergy
  symm
  apply IsLeast.csInf_eq
  refine ⟨⟨ψ, hψ, rfl⟩, ?_⟩
  rintro _ ⟨φ, hφ, rfl⟩
  exact hmin hφ

end QPCP.Proof
