import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S026 : QPCP.Statement.S026 := by
  intro n f x
  simp [energy, costOp, basisState, dotProduct, Matrix.mulVec_diagonal, Pi.single_apply]

end QPCP.Proof
