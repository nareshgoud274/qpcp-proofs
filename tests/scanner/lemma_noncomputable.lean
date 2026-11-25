-- expect: the command `noncomputable`
-- as: lemma L900001
/-
PROGRAM: foundations
PLAIN: an example lemma statement that is long enough.
-/
import QPCP.Statements

namespace QPCP.Lemma
noncomputable def L900001 : Prop := True
end QPCP.Lemma
