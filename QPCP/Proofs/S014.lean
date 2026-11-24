import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S014 : QPCP.Statement.S014 := by
  intro n A B ψ
  simp [energy, Matrix.add_mulVec, dotProduct_add]

end QPCP.Proof
