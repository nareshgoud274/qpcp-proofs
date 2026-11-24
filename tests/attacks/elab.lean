import Mathlib
open IO
open Lean Elab Term in
elab "probe_elab" : term => do
  (FS.writeFile "/tmp/qpcp_probe_elab" "" : IO Unit)
  return Lean.mkNatLit 0
def probe : Nat := probe_elab
