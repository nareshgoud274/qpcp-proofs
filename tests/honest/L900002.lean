import QPCP.Statements

/-!
PROGRAM: foundations
PLAIN: Every computational basis state has energy two under the identity operator.
-/

namespace QPCP.Lemma

def L900002 : Prop :=
  ∀ (n : ℕ) (x : QPCP.Config n), QPCP.energy (1 : QPCP.Op n) (QPCP.basisState x) = 2

end QPCP.Lemma
