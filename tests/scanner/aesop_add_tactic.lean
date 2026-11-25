-- expect: `aesop` with clauses
import QPCP.Statements

namespace QPCP.Proof
theorem S030 : True := by aesop (add safe tactic (by trivial))
end QPCP.Proof
