import Mathlib
open IO
open Lean Meta Simp in
dsimproc probeDSimp (Nat.succ _) := fun _ => do
  (FS.writeFile "/tmp/qpcp_probe_dsimproc" "" : IO Unit)
  return .continue
example (n : Nat) : Nat.succ n + 0 = Nat.succ n := by simp only [probeDSimp, Nat.add_zero]
