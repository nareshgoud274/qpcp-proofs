import QPCP.Lemmas.L900002

namespace QPCP.Refutation

open QPCP Matrix

theorem L900002 : ¬ QPCP.Lemma.L900002 := by
  intro h
  have h0 := h 0 (fun _ => 0)
  simp [energy, basisState, dotProduct, Pi.single_apply] at h0
  rw [if_pos (Subsingleton.elim _ _)] at h0
  norm_num at h0

end QPCP.Refutation
