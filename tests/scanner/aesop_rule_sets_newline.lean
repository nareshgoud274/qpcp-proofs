-- expect: `aesop` with clauses
import QPCP.Statements

namespace QPCP.Proof
theorem S030 : True := by
  aesop?
    (rule_sets := [Mine])
end QPCP.Proof
