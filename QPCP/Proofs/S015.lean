import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S015 : QPCP.Statement.S015 := by
  intro n c A ψ
  simp [energy, Matrix.smul_mulVec, dotProduct_smul]

end QPCP.Proof
