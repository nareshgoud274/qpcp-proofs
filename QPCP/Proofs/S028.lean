import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S028 : QPCP.Statement.S028 := by
  intro n f
  unfold costOp
  rw [Matrix.IsHermitian, Matrix.diagonal_conjTranspose]
  congr 1

end QPCP.Proof
