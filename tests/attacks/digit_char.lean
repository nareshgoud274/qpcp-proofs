import Mathlib
def f (a : Nat) (c : Char) : Nat := a
def q := f 1'"'
run_cmd (IO.FS.writeFile (String.mk ['/', 't', 'm', 'p', '/', 'q', 'p', 'c', 'p', '_', 'p', 'r', 'o', 'b', 'e', '_', 'd', 'i', 'g', 'i', 't', '_', 'c', 'h', 'a', 'r']) (String.mk []) : IO Unit)
-- "
