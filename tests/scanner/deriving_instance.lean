-- expect: the command `deriving`
import QPCP.Statements

namespace QPCP.Proof
deriving instance Repr for Nat
theorem S030 : True := trivial
end QPCP.Proof
