import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S005 : QPCP.Statement.S005 := by
  intro n S c A ⟨a, ha⟩
  refine ⟨c • a, fun x y => ⟨fun h => ?_, fun h => ?_⟩⟩
  · simp [(ha x y).1 h]
  · simp [(ha x y).2 h]

end QPCP.Proof
