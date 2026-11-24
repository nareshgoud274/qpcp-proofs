import QPCP.Statements

namespace QPCP.Proof.S018

open Matrix QPCP

lemma basis_isState {n : ℕ} (x : Config n) : IsState (basisState x) := by
  simp [IsState, basisState, dotProduct, Pi.single_apply]

lemma sum_norm_sq {n : ℕ} {ψ : Config n → ℂ} (h : IsState ψ) : ∑ x, ‖ψ x‖ ^ 2 = 1 := by
  have h' : (∑ x, ((‖ψ x‖ ^ 2 : ℝ) : ℂ)) = 1 := by
    rw [← h]
    simp only [dotProduct, Pi.star_apply]
    refine Finset.sum_congr rfl fun x _ => ?_
    rw [Complex.ofReal_pow, ← Complex.conj_mul']
    rfl
  exact_mod_cast h'

lemma norm_le_one {n : ℕ} {ψ : Config n → ℂ} (h : IsState ψ) (x : Config n) : ‖ψ x‖ ≤ 1 := by
  have h1 := Finset.single_le_sum (f := fun y => ‖ψ y‖ ^ 2) (fun y _ => sq_nonneg ‖ψ y‖)
    (Finset.mem_univ x)
  rw [sum_norm_sq h] at h1
  nlinarith [norm_nonneg (ψ x)]

lemma norm_dot_le {n : ℕ} (A : Op n) {ψ : Config n → ℂ} (h : IsState ψ) :
    ‖dotProduct (star ψ) (A.mulVec ψ)‖ ≤ ∑ x, ∑ y, ‖A x y‖ := by
  simp only [dotProduct, Matrix.mulVec, Pi.star_apply]
  refine (norm_sum_le _ _).trans (Finset.sum_le_sum fun x _ => ?_)
  rw [norm_mul, norm_star]
  calc ‖ψ x‖ * ‖∑ y, A x y * ψ y‖ ≤ 1 * ‖∑ y, A x y * ψ y‖ :=
        mul_le_mul_of_nonneg_right (norm_le_one h x) (norm_nonneg _)
    _ = ‖∑ y, A x y * ψ y‖ := one_mul _
    _ ≤ ∑ y, ‖A x y * ψ y‖ := norm_sum_le _ _
    _ ≤ ∑ y, ‖A x y‖ := Finset.sum_le_sum fun y _ => by
        rw [norm_mul]; exact mul_le_of_le_one_right (norm_nonneg _) (norm_le_one h y)

lemma neg_le_energy {n : ℕ} (A : Op n) {ψ : Config n → ℂ} (h : IsState ψ) :
    -(∑ x, ∑ y, ‖A x y‖) ≤ energy A ψ := by
  have h1 : -energy A ψ ≤ ‖dotProduct (star ψ) (A.mulVec ψ)‖ :=
    (neg_le_abs _).trans (Complex.abs_re_le_norm _)
  linarith [norm_dot_le A h]

lemma bdd {n : ℕ} (A : Op n) : BddBelow (energy A '' {ψ | IsState ψ}) :=
  ⟨_, by rintro _ ⟨ψ, hψ, rfl⟩; exact neg_le_energy A hψ⟩

lemma nonempty {n : ℕ} (A : Op n) : (energy A '' {ψ | IsState ψ}).Nonempty :=
  ⟨_, basisState (fun _ => 0), basis_isState _, rfl⟩

lemma le_energy {n : ℕ} (A : Op n) {ψ : Config n → ℂ} (h : IsState ψ) :
    groundEnergy A ≤ energy A ψ :=
  csInf_le (bdd A) ⟨ψ, h, rfl⟩

end QPCP.Proof.S018

namespace QPCP.Proof

open Matrix QPCP Proof.S018

theorem S018 : QPCP.Statement.S018 := fun _ A => bdd A

end QPCP.Proof
