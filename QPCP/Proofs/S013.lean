import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S013 : QPCP.Statement.S013 := by
  intro n x
  simp [IsState, basisState, dotProduct, Pi.single_apply]

end QPCP.Proof
