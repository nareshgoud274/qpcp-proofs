-- expect: the command `instance`
import QPCP.Statements

namespace QPCP.Proof
instance : Inhabited Nat := ⟨0⟩
theorem S030 : True := trivial
end QPCP.Proof
