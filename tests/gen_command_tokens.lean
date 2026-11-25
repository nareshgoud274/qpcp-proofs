/-
Prints every token that can begin a Lean command, with Mathlib and the
project's maintainer-written modules loaded: the leading tokens of the
`command` parser category. scripts/command_tokens.txt is this output; the
source scanner refuses every one of these tokens that is not on its
allowlist (scripts/check.py). tests/test_command_tokens.sh regenerates it
and fails if the committed table is out of date, for example after a
Mathlib or toolchain update.

    lake env lean tests/gen_command_tokens.lean

Maintainer-written; it is not part of the QPCP library and runs only in the
attack-tests job.
-/
import Mathlib
import QPCP.Statements

open Lean Parser in
#eval show CoreM Unit from do
  let cats := (parserExtension.getState (← getEnv)).categories
  let some cat := cats.find? `command | throwError "no command category"
  unless cat.tables.leadingParsers.isEmpty do
    throwError "some command parsers are not indexed by a leading token"
  let toks := cat.tables.leadingTable.toList.map (fun (tk, _) => tk.toString (escape := false))
  for t in toks.toArray.qsort (· < ·) |>.toList.eraseDups do
    IO.println t
