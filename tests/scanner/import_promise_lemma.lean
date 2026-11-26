-- expect: ACCEPTED
-- as: lemma L900001
/-
PROGRAM: foundations
PLAIN: an example lemma statement that imports the promise-problem definitions.
-/
import QPCP.Promise

namespace QPCP.Lemma
def L900001 : Prop := QPCP.Promise.testA.length = 3
end QPCP.Lemma
