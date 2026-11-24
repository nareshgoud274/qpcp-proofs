import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S011 : QPCP.Statement.S011 := by
  intro n k H
  unfold LocalHamiltonian.toOp
  induction H.terms with
  | nil => simp
  | cons t ts ih => simpa using t.isHermitian.add ih

end QPCP.Proof
