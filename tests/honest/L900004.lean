import QPCP.Promise

/-!
PROGRAM: foundations
PLAIN: Test A of the promise specification has three terms, counted with repetition.
-/

namespace QPCP.Lemma

def L900004 : Prop :=
  (QPCP.Promise.boolHamiltonian QPCP.Promise.testA).numTerms = 3

end QPCP.Lemma
