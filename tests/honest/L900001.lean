import QPCP.Statements

/-!
PROGRAM: foundations
PLAIN: Every computational basis state has energy one under the identity operator.
-/

namespace QPCP.Lemma

def L900001 : Prop :=
  ∀ (n : ℕ) (x : QPCP.Config n), QPCP.energy (1 : QPCP.Op n) (QPCP.basisState x) = 1

end QPCP.Lemma
