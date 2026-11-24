import Mathlib
open IO
open Lean Elab Term in
def probe : Nat := by_elab do
  (FS.writeFile "/tmp/qpcp_probe_by_elab" "" : IO Unit)
  return Lean.mkNatLit 0
