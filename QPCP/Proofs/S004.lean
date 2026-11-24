import QPCP.Statements

namespace QPCP.Proof

theorem S004 : QPCP.Statement.S004 := by
  intro n S A B ⟨a, ha⟩ ⟨b, hb⟩
  refine ⟨a + b, fun x y => ⟨fun h => ?_, fun h => ?_⟩⟩
  · simp [Matrix.add_apply, (ha x y).1 h, (hb x y).1 h]
  · simp [Matrix.add_apply, (ha x y).2 h, (hb x y).2 h]

end QPCP.Proof
