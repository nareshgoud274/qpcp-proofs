import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S007 : QPCP.Statement.S007 := by
  intro n S A ⟨a, ha⟩
  refine ⟨a.conjTranspose, fun x y => ⟨fun h => ?_, fun h => ?_⟩⟩
  · have h' : AgreeOff S y x := fun i hi => (h i hi).symm
    simp [Matrix.conjTranspose_apply, (ha y x).1 h']
  · have h' : ¬ AgreeOff S y x := fun h'' => h (fun i hi => (h'' i hi).symm)
    simp [Matrix.conjTranspose_apply, (ha y x).2 h']

end QPCP.Proof
