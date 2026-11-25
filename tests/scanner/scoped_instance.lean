-- expect: the command `
import QPCP.Statements

namespace QPCP.Proof
scoped instance : Inhabited Nat := ⟨0⟩
theorem S030 : True := trivial
end QPCP.Proof
