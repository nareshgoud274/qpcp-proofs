-- expect: the command `variable`
import QPCP.Statements

namespace QPCP.Proof
variable (n : Nat)
theorem S030 : True := trivial
end QPCP.Proof
