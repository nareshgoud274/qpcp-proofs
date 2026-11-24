import QPCP.Statements

namespace QPCP.Proof.S023

open Matrix QPCP

end QPCP.Proof.S023

namespace QPCP.Proof

open Matrix QPCP Proof.S023

open scoped ComplexOrder in
theorem S023 : QPCP.Statement.S023 := by
  intro n A hA
  refine Real.sInf_nonneg ?_
  rintro _ ⟨ψ, -, rfl⟩
  exact (Complex.nonneg_iff.mp (hA.dotProduct_mulVec_nonneg ψ)).1

end QPCP.Proof
