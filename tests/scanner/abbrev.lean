-- expect: the command `abbrev`
import QPCP.Statements

namespace QPCP.Proof
abbrev T := True
theorem S030 : T := trivial
end QPCP.Proof
