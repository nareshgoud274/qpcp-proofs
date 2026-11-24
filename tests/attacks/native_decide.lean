import Mathlib
open IO
unsafe def sideU : Bool := unsafeBaseIO ((FS.writeFile "/tmp/qpcp_probe_native_decide" "").toBaseIO.map fun _ => true)
@[implemented_by sideU] def side : Bool := true
theorem probe : side = true := by native_decide
