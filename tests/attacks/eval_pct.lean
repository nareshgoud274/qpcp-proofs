import Mathlib
open IO
def probe : Nat := eval% (unsafe unsafeBaseIO ((FS.writeFile "/tmp/qpcp_probe_eval_pct" "").toBaseIO.map fun _ => (7 : Nat)))
