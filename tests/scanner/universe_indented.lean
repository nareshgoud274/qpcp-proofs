-- expect: the command `universe`
import QPCP.Statements

namespace QPCP.Proof
  universe u
theorem S030 : True := trivial
end QPCP.Proof
