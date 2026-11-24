import Mathlib
open IO
macro "probe_macro" : command => `(run_cmd (FS.writeFile "/tmp/qpcp_probe_macro" "" : IO Unit))
probe_macro
