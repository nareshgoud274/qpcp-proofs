import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S002 : QPCP.Statement.S002 := by
  intro n
  refine ⟨1, fun x y => ⟨fun h => ?_, fun h => ?_⟩⟩
  · have hxy : x = y := funext fun i => h i (Finset.notMem_empty i)
    subst hxy
    simp
  · have hxy : x ≠ y := fun e => h (fun i _ => e ▸ rfl)
    simp [Matrix.one_apply_ne hxy]

end QPCP.Proof
