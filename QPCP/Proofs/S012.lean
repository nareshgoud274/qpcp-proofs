import QPCP.Statements

namespace QPCP.Proof

open Matrix QPCP

theorem S012 : QPCP.Statement.S012 := by
  intro n k k' H hk
  refine ⟨⟨H.terms.map fun t =>
    ⟨t.support, t.card_le.trans hk, t.op, t.isHermitian, t.actsOn⟩⟩, ?_⟩
  simp [LocalHamiltonian.toOp, Function.comp_def]

end QPCP.Proof
