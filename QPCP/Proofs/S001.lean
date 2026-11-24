import QPCP.Statements

namespace QPCP.Proof

theorem S001 : QPCP.Statement.S001 := by
  intro n S
  refine ⟨0, fun x y => ⟨fun _ => rfl, fun _ => rfl⟩⟩

end QPCP.Proof
