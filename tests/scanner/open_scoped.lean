-- expect: ACCEPTED
import QPCP.Statements

namespace QPCP.Proof
open scoped ComplexOrder in
theorem S030 : True := by
  refine ?_
  trivial
end QPCP.Proof
