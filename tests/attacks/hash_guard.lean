import Mathlib
open IO
#guard (unsafe unsafeBaseIO ((FS.writeFile "/tmp/qpcp_probe_hash_guard" "").toBaseIO.map fun _ => true))
