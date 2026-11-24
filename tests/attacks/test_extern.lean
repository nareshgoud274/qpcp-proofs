import Mathlib
import Lean.Util.TestExtern
open IO
test_extern Nat.add (unsafe unsafeBaseIO ((FS.writeFile "/tmp/qpcp_probe_test_extern" "").toBaseIO.map fun _ => (1 : Nat))) 1
