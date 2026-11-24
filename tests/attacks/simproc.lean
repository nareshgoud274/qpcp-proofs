import Mathlib
open IO
open Lean Meta Simp in
simproc probeSimp (Nat.succ _) := fun _ => do
  (FS.writeFile "/tmp/qpcp_probe_simproc" "" : IO Unit)
  return .continue
example (n : Nat) : Nat.succ n + 0 = Nat.succ n := by simp only [probeSimp, Nat.add_zero]
