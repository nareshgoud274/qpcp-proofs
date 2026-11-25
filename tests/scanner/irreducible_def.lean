-- expect: the command `irreducible_def`
import QPCP.Statements

namespace QPCP.Proof
irreducible_def k : Nat := 1
theorem S030 : True := trivial
end QPCP.Proof
