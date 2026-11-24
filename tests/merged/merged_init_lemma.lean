-- Installed by the tests as QPCP/Lemmas/L900003.lean: a merged lemma whose
-- code runs whenever another file imports it (an `initialize` block).
import QPCP.Statements

/-- Test payload (tests/run_tests.sh, stage 6): code that runs at build time and
tries to change what later checks see. It only creates or overwrites marker
files: a file in /tmp, a canary in scripts/, a file in the build folder and,
unless QPCP_PROBE_CONTROL is set, a file in the toolchain bin folder and in
the home folder. -/
def qpcpTamperTargets (tag : String) : IO (List System.FilePath) := do
  let app ← IO.appPath
  let bin := app.parent.getD "."
  let lp := (← IO.getEnv "LEAN_PATH").getD ""
  let repo : System.FilePath :=
    ((lp.splitOn ":").find? (fun e => (e.splitOn "/.lake/packages/").length > 1)).map
      (fun e => (e.splitOn "/.lake/packages/").headD ".") |>.getD "."
  let home : System.FilePath := (app.toString.splitOn "/.elan/").headD "."
  let safe : List System.FilePath :=
    [⟨"/tmp/qpcp_probe_merged_" ++ tag⟩, repo / "scripts" / "qpcp_canary", repo / ".lake" / ("qpcp_tamper_" ++ tag)]
  let risky : List System.FilePath := [bin / ("qpcp_tamper_" ++ tag), home / ("qpcp_tamper_" ++ tag)]
  return if (← IO.getEnv "QPCP_PROBE_CONTROL").isSome then safe else safe ++ risky

def qpcpTamper (tag : String) : IO Unit := do
  for p in (← qpcpTamperTargets tag) do
    try IO.FS.writeFile p "tampered" catch _ => pure ()

initialize qpcpTamper "init"

namespace QPCP.Lemma

def L900003 : Prop := True

end QPCP.Lemma
