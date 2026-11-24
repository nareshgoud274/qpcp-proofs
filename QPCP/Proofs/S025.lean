import QPCP.Statements

namespace QPCP.Proof

open scoped ComplexOrder

namespace S025

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



lemma smul_quad {n : ℕ} (A : Op n) (x : Config n → ℂ) (r : ℝ) :
    dotProduct (star ((r : ℂ) • x)) (A.mulVec ((r : ℂ) • x))
      = ((r ^ 2 : ℝ) : ℂ) * dotProduct (star x) (A.mulVec x) := by
  rw [star_smul, mulVec_smul, smul_dotProduct, dotProduct_smul]
  simp only [smul_eq_mul, Complex.star_def, Complex.conj_ofReal]
  push_cast; ring

lemma smul_dot {n : ℕ} (x : Config n → ℂ) (r : ℝ) :
    dotProduct (star ((r : ℂ) • x)) ((r : ℂ) • x)
      = ((r ^ 2 : ℝ) : ℂ) * dotProduct (star x) x := by
  rw [star_smul, smul_dotProduct, dotProduct_smul]
  simp only [smul_eq_mul, Complex.star_def, Complex.conj_ofReal]
  push_cast; ring

lemma sumsq_pos {n : ℕ} {x : Config n → ℂ} (hx : x ≠ 0) : 0 < ∑ i, ‖x i‖ ^ 2 := by
  obtain ⟨i, hi⟩ := Function.ne_iff.1 hx
  have : 0 < ‖x i‖ ^ 2 := pow_pos (norm_pos_iff.2 hi) 2
  exact lt_of_lt_of_le this
    (Finset.single_le_sum (f := fun j => ‖x j‖ ^ 2) (fun j _ => by positivity)
      (Finset.mem_univ i))

lemma energy_ge {n : ℕ} (A : Op n) {ψ : Config n → ℂ}
    (hmin : IsMinOn (energy A) (states n) ψ) (x : Config n → ℂ) :
    energy A ψ * (∑ i, ‖x i‖ ^ 2) ≤ (dotProduct (star x) (A.mulVec x)).re := by
  by_cases hx : x = 0
  · subst hx; simp
  set s := ∑ i, ‖x i‖ ^ 2 with hs
  have hspos : 0 < s := sumsq_pos hx
  set r : ℝ := (Real.sqrt s)⁻¹ with hr
  have hr2 : r ^ 2 * s = 1 := by
    rw [hr, inv_pow, Real.sq_sqrt hspos.le, inv_mul_cancel₀ hspos.ne']
  have hy : (r : ℂ) • x ∈ states n := by
    show dotProduct _ _ = 1
    rw [smul_dot, dot_self_eq, ← Complex.ofReal_sum, ← hs, ← Complex.ofReal_mul, hr2]
    simp
  have h1 : energy A ψ ≤ energy A ((r : ℂ) • x) := hmin hy
  unfold energy at h1 ⊢
  rw [smul_quad] at h1
  have h2 : ((((r ^ 2 : ℝ) : ℂ)) * dotProduct (star x) (A.mulVec x)).re
      = r ^ 2 * (dotProduct (star x) (A.mulVec x)).re :=
    Complex.re_ofReal_mul _ _
  rw [h2] at h1
  have := mul_le_mul_of_nonneg_right h1 hspos.le
  calc (dotProduct (star ψ) (A.mulVec ψ)).re * s
      ≤ r ^ 2 * (dotProduct (star x) (A.mulVec x)).re * s := this
    _ = (dotProduct (star x) (A.mulVec x)).re := by
      rw [mul_comm (r ^ 2), mul_assoc, hr2, mul_one]

end S025

theorem S025 : QPCP.Statement.S025 := by
  intro n A hA
  obtain ⟨ψ, hψ, hmin⟩ := S025.exists_min A
  have hE : QPCP.groundEnergy A = energy A ψ := by
    unfold QPCP.groundEnergy
    apply IsLeast.csInf_eq
    refine ⟨⟨ψ, hψ, rfl⟩, ?_⟩
    rintro _ ⟨φ, hφ, rfl⟩
    exact hmin hφ
  rw [hE]
  set E := energy A ψ with hEdef
  set B : Op n := A - (E : ℂ) • (1 : Op n) with hBdef
  have hquad : ∀ x : Config n → ℂ, dotProduct (star x) (B.mulVec x)
      = dotProduct (star x) (A.mulVec x) - (E : ℂ) * dotProduct (star x) x := by
    intro x
    rw [hBdef, Matrix.sub_mulVec, Matrix.smul_mulVec, Matrix.one_mulVec,
      dotProduct_sub, dotProduct_smul, smul_eq_mul]
  have hBh : B.IsHermitian := by
    rw [hBdef]
    refine hA.sub ?_
    simp [Matrix.IsHermitian, Matrix.conjTranspose_smul]
  have hBpsd : B.PosSemidef := by
    refine Matrix.PosSemidef.of_dotProduct_mulVec_nonneg hBh fun x => ?_
    rw [Complex.nonneg_iff]
    constructor
    · rw [hquad, S025.dot_self_eq]
      have := S025.energy_ge A hmin x
      simp only [Complex.sub_re, Complex.mul_re, Complex.ofReal_re, Complex.ofReal_im,
        zero_mul, sub_zero]
      rw [Complex.re_sum]
      simp only [Complex.ofReal_re]
      linarith
    · have := hBh.im_star_dotProduct_mulVec_self x
      exact (by simpa using this : _ = (0:ℝ)).symm
  have hzero : dotProduct (star ψ) (B.mulVec ψ) = 0 := by
    rw [hquad, show dotProduct (star ψ) ψ = 1 from hψ, mul_one]
    have him : (dotProduct (star ψ) (A.mulVec ψ)).im = 0 := by
      simpa using hA.im_star_dotProduct_mulVec_self ψ
    apply Complex.ext
    · simp [hEdef, energy]
    · simp [him]
  have hB0 := hBpsd.dotProduct_mulVec_zero_iff.1 hzero
  rw [hBdef, Matrix.sub_mulVec, Matrix.smul_mulVec, Matrix.one_mulVec,
    sub_eq_zero] at hB0
  exact ⟨ψ, hψ, hB0⟩

end QPCP.Proof
