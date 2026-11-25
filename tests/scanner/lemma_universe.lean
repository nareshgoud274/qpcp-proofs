-- expect: the command `universe`
-- as: lemma L900001
/-
PROGRAM: foundations
PLAIN: an example lemma statement that is long enough.
-/
import QPCP.Statements

namespace QPCP.Lemma
def L900001 : Prop := True
universe u
end QPCP.Lemma
