import Mathlib
open IO
open Lean Elab Tactic in
theorem probe : True := by
  run_tac (FS.writeFile "/tmp/qpcp_probe_run_tac" "" : IO Unit)
  trivial
