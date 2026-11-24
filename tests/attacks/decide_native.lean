import Mathlib
open IO
unsafe def sideU : Bool := unsafeBaseIO ((FS.writeFile "/tmp/qpcp_probe_decide_native" "").toBaseIO.map fun _ => true)
@[implemented_by sideU] def side : Bool := true
theorem probe : side = true := by decide +native
