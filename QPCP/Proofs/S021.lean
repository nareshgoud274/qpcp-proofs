import QPCP.Statements

namespace QPCP.Proof.S021

open Matrix QPCP

lemma energy_smul {n : ℕ} (c : ℝ) (A : Op n) (ψ : Config n → ℂ) :
    energy ((c : ℂ) • A) ψ = c * energy A ψ := by
  simp [energy, Matrix.smul_mulVec, dotProduct_smul]

end QPCP.Proof.S021

namespace QPCP.Proof

open Matrix QPCP Proof.S021

theorem S021 : QPCP.Statement.S021 := by
  intro n c A hc
  have h : energy ((c : ℂ) • A) = fun ψ => c • energy A ψ :=
    funext fun ψ => by rw [energy_smul, smul_eq_mul]
  rw [groundEnergy, groundEnergy, h, ← Set.image_image (fun e : ℝ => c • e), Set.image_smul,
    Real.sInf_smul_of_nonneg hc, smul_eq_mul]

end QPCP.Proof
