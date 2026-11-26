import QPCP.Statements

namespace QPCP.Proof

open QPCP QPCP.Promise

theorem S058 : QPCP.Statement.S058 := by
  intro F I both
  have hm : 0 < I.1.terms.length := List.length_pos_iff_ne_nil.mpr I.2.1.1
  have count : I.hamiltonian.numTerms = I.1.terms.length := by
    simp [FamilyInstance.hamiltonian, RawInstance.hamiltonian, NormalizedHamiltonian.numTerms]
  have hm' : (0 : ℝ) < I.hamiltonian.numTerms := by rw [count]; exact_mod_cast hm
  have hab : (F.params.a : ℝ) < (F.params.b : ℝ) := by exact_mod_cast F.params.a_lt_b
  exact (not_le_of_gt (mul_lt_mul_of_pos_right hab hm')) (both.2.trans both.1)

end QPCP.Proof
