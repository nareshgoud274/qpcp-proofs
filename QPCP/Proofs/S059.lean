import QPCP.Statements
import QPCP.Proofs.S027

namespace QPCP.Proof

open QPCP QPCP.Promise

theorem S059 : QPCP.Statement.S059 := by
  intro n k cs _hcs
  let f : Config n → ℝ := fun x => (violationCount cs x : ℝ)
  have hd : (boolHamiltonian cs).toOp = costOp f := by
    rw [boolSumDiagonal]
    simp [costOp, f]
  have he : groundEnergyOn (costOp f) = groundEnergy (costOp f) := rfl
  rw [hd, he, QPCP.Proof.S027]
  have hm : 0 ≤ (cs.length : ℝ) := by positivity
  obtain ⟨w, hw⟩ := Finite.exists_min f
  have least : (⨅ x, f x) = f w :=
    le_antisymm (ciInf_le (Set.finite_range f).bddBelow w) (le_ciInf hw)
  rw [least]
  change f w / (cs.length : ℝ) = ⨅ x, f x / (cs.length : ℝ)
  exact le_antisymm (le_ciInf fun x => div_le_div_of_nonneg_right (hw x) hm)
    (ciInf_le (Set.finite_range _).bddBelow w)

end QPCP.Proof
