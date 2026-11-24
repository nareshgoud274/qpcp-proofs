import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S016 : QPCP.Statement.S016 := by
  intro n ψ h
  unfold IsState at h
  simp [energy, h]

end QPCP.Proof
