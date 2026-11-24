import QPCP.Statements

namespace QPCP.Proof.S017

open Matrix QPCP

end QPCP.Proof.S017

namespace QPCP.Proof

open Matrix QPCP Proof.S017

theorem S017 : QPCP.Statement.S017 := by
  intro n A ψ hA
  have h := hA.star_dotProduct_mulVec_comm ψ ψ
  have h2 := congrArg Complex.im h
  rw [Complex.star_def, Complex.conj_im] at h2
  linarith

end QPCP.Proof
