#!/usr/bin/env bash
# Regression tests for the checker (HARDENING.md, H5). Run from anywhere:
#
#   tests/run_tests.sh [--no-sandbox]
#
# CI runs it on the maintainer's own pull requests, with bubblewrap. Locally on
# a machine without bubblewrap, --no-sandbox runs the pipeline unsandboxed: the
# attack files then really run, so the "no marker on the host" checks are
# skipped. This directory is outside the QPCP library; nothing here is built by
# `lake build`.
#
#   1. Positive control: one attack, run with plain Lean, must leave its marker,
#      or a missing marker would prove nothing.
#   2. The source scanner refuses every attack and accepts every honest file.
#   3. With the scanner bypassed, the sandboxed pipeline still rejects every
#      attack, and no attack leaves a marker on the host.
#   4. The pipeline accepts an honest proof (the merged S019), an honest lemma
#      and an honest refutation.
#   5. Forged exports of each honest contribution (proof, lemma, refutation)
#      are all rejected.
#   6. A merged file whose code runs at build time (tests/merged/) cannot alter a
#      later verdict in any of the four places that build merged files: the
#      contributor check, the record check (maintainer pull requests and
#      verify-main), the per-module leanchecker replay, and this job's own
#      trusted build. Nothing it writes reaches the host, the scripts or the
#      toolchain, and the verdicts around it stay correct.
#
# Exit 0 only if every test passes.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
MODE="${1:-sandbox}"
NS=""; [ "$MODE" = "--no-sandbox" ] && NS="--no-sandbox"
fails=0; passes=0
ok()   { passes=$((passes + 1)); echo "  ok    $*"; }
bad()  { fails=$((fails + 1)); echo "  FAIL  $*"; }
markers() { ls /tmp/qpcp_probe_* 2>/dev/null | wc -l | tr -d ' '; }
ATTACKS=$(ls tests/attacks/*.lean tests/attacks/import-time/ProbeInit.lean tests/attacks/import-time/ProbeEnvExt.lean)
TARGET=S030   # an open founding step with no proof on main

# Put anything moved aside back, whatever happens.
restore() {
  [ -f "$ROOT/.lake/qpcp-tests/S019.lean" ] && mv "$ROOT/.lake/qpcp-tests/S019.lean" QPCP/Proofs/S019.lean
  rm -f QPCP/Lemmas/L900002.lean QPCP/Proofs/$TARGET.lean
  rm -f QPCP/Proofs/S031.lean QPCP/Lemmas/L900003.lean QPCP/Proofs/L900003.lean scripts/qpcp_canary
  rm -f /tmp/qpcp_probe_* "$ROOT"/.lake/qpcp_tamper_*
}
trap restore EXIT
mkdir -p "$ROOT/.lake/qpcp-tests"
[ ! -e QPCP/Proofs/$TARGET.lean ] || { echo "QPCP/Proofs/$TARGET.lean exists; pick another target"; exit 2; }

echo "1. Positive control"
rm -f /tmp/qpcp_probe_*
lake env lean tests/attacks/run_cmd.lean > /dev/null 2>&1
if [ -f /tmp/qpcp_probe_run_cmd ]; then ok "run_cmd.lean leaves its marker when run with plain Lean"
else bad "run_cmd.lean left no marker even unsandboxed; marker checks below would prove nothing"; fi
rm -f /tmp/qpcp_probe_*

echo "2. Source scanner"
for f in $ATTACKS; do
  out=$(python3 scripts/check.py scan-file proof $TARGET "$f")
  case "$out" in REJECTED*) ok "scanner refuses $(basename "$f")" ;; *) bad "scanner accepts $(basename "$f"): $out" ;; esac
done
for spec in "proof S019 QPCP/Proofs/S019.lean" "lemma L900001 tests/honest/L900001.lean" \
            "lemma L900002 tests/honest/L900002.lean" "refutation L900002 tests/honest/refute_L900002.lean"; do
  set -- $spec
  out=$(python3 scripts/check.py scan-file "$1" "$2" "$3")
  case "$out" in ACCEPTED*) ok "scanner accepts $(basename "$3")" ;; *) bad "scanner refuses honest $(basename "$3"): $out" ;; esac
done

echo "3. Pipeline with the scanner bypassed"
for f in $ATTACKS; do
  rm -f /tmp/qpcp_probe_*
  out=$(scripts/contribution_check.sh proof $TARGET "$f" $NS 2>/dev/null | tail -1)
  n=$(markers)
  case "$out" in
    REJECTED*)
      if [ -n "$NS" ]; then ok "pipeline rejects $(basename "$f") (marker check skipped: --no-sandbox)"
      elif [ "$n" = 0 ]; then ok "pipeline rejects $(basename "$f"), no marker on the host"
      else bad "pipeline rejects $(basename "$f") but a marker reached the host"; fi ;;
    *) bad "pipeline did not reject $(basename "$f"): $out" ;;
  esac
done
rm -f /tmp/qpcp_probe_*

echo "4. Honest contributions"
mv QPCP/Proofs/S019.lean "$ROOT/.lake/qpcp-tests/S019.lean"
out=$(scripts/contribution_check.sh proof S019 "$ROOT/.lake/qpcp-tests/S019.lean" $NS 2>/dev/null | tail -1)
case "$out" in "ACCEPTED: proof S019") ok "pipeline accepts the merged proof of S019" ;; *) bad "honest proof S019: $out" ;; esac
WORK="${RUNNER_TEMP:-$ROOT/.lake}/qpcp-verify"
keep() {  # keep <label>: save the honest export and its references for step 5
  python3 -I - "$WORK/result/contribution.json" "$ROOT/.lake/qpcp-tests" "$1" <<'PYKEEP'
import json, shutil, sys
from pathlib import Path
r = json.load(open(sys.argv[1])); out = Path(sys.argv[2]); label = sys.argv[3]
shutil.copyfile(r["export"], out / f"{label}.ndjson")
refs = []
for i, ref in enumerate(r["references"]):
    dest = out / f"{label}.ref{i}.ndjson"; shutil.copyfile(ref, dest); refs.append(str(dest))
(out / f"{label}.refs").write_text(",".join(refs))
PYKEEP
}
keep proof-S019
mv "$ROOT/.lake/qpcp-tests/S019.lean" QPCP/Proofs/S019.lean

out=$(scripts/contribution_check.sh lemma L900001 tests/honest/L900001.lean $NS 2>/dev/null | tail -1)
case "$out" in "ACCEPTED: lemma L900001") ok "pipeline accepts an honest lemma" ;; *) bad "honest lemma: $out" ;; esac
keep lemma-L900001

cp tests/honest/L900002.lean QPCP/Lemmas/L900002.lean
out=$(scripts/contribution_check.sh refutation L900002 tests/honest/refute_L900002.lean $NS 2>/dev/null | tail -1)
case "$out" in "ACCEPTED: refutation L900002") ok "pipeline accepts an honest refutation" ;; *) bad "honest refutation: $out" ;; esac
keep refutation-L900002
rm -f QPCP/Lemmas/L900002.lean

echo "5. Forged exports"
for label in proof-S019 lemma-L900001 refutation-L900002; do
  kind="${label%%-*}"; ident="${label#*-}"
  honest="$ROOT/.lake/qpcp-tests/$label.ndjson"; ref="$(cat "$ROOT/.lake/qpcp-tests/$label.refs" 2>/dev/null)"
  if [ ! -f "$honest" ] || [ -z "$ref" ]; then bad "no honest $kind export to forge from (step 4 failed)"; continue; fi
  dir="$ROOT/.lake/qpcp-tests/forged-$label"
  rm -rf "$dir"
  python3 -I tests/forge_exports.py "$kind" "$ident" "$honest" "$ref" "$dir" > /dev/null || { bad "cannot forge the $kind export"; continue; }
  out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$honest" "$ref")
  case "$out" in ACCEPTED*) ok "$kind $ident: the honest export itself is accepted" ;; *) bad "$kind $ident: honest export rejected: $out" ;; esac
  # An incomplete reference (a requested name main lacks) must be refused too.
  printf 'propext\nQPCP.NoSuchConstant\n' > "$dir.names"
  out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$honest" "$ref" "$dir.names")
  case "$out" in REJECTED*"QPCP.NoSuchConstant"*) ok "$kind $ident: refuses an incomplete reference" ;; *) bad "$kind $ident: incomplete reference not refused: $out" ;; esac
  for f in "$dir"/*.ndjson; do
    out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$f" "$ref")
    case "$out" in REJECTED*) ok "$kind $ident: rejects $(basename "$f" .ndjson): ${out#REJECTED: }" ;; *) bad "$kind $ident: accepts forged $(basename "$f" .ndjson): $out" ;; esac
  done
done
echo "6. Merged files with build-time code"
SYSROOT="$(lake env printenv LEAN_SYSROOT)"
snapshot() {  # what a forged verdict would have to change: scripts, tests, the toolchain's binaries
  { find scripts tests -type f -not -name 'qpcp_canary' -not -path '*/__pycache__/*' -print0 | sort -z | xargs -0 shasum -a 256
    ls -la "$SYSROOT/bin"; } 2>/dev/null | shasum -a 256 | cut -d' ' -f1
}
tampered() {  # lists every trace a payload could leave on the host
  ls /tmp/qpcp_probe_merged_* "$ROOT"/.lake/qpcp_tamper_* "$SYSROOT"/bin/qpcp_tamper_* "$HOME"/qpcp_tamper_* 2>/dev/null
  [ "$(cat scripts/qpcp_canary 2>/dev/null)" = original ] || echo "scripts/qpcp_canary changed"
}
clean_traces() { rm -f /tmp/qpcp_probe_merged_* "$ROOT"/.lake/qpcp_tamper_*; echo original > scripts/qpcp_canary; }
install_merged() {
  cp tests/merged/merged_buildtime.lean QPCP/Proofs/S031.lean
  cp tests/merged/merged_init_lemma.lean QPCP/Lemmas/L900003.lean
  cp tests/merged/merged_init_user.lean QPCP/Proofs/L900003.lean
}
remove_merged() { rm -f QPCP/Proofs/S031.lean QPCP/Lemmas/L900003.lean QPCP/Proofs/L900003.lean; }
after() {  # after <place> <snapshot before>
  local traces; traces="$(tampered)"
  if [ -n "$traces" ]; then bad "$1: the merged file reached the host: $(echo $traces)"
  elif [ "$(snapshot)" != "$2" ]; then bad "$1: scripts, tests or the toolchain changed"
  else ok "$1: nothing reached the host, the scripts or the toolchain"; fi
}

# Positive control: run directly, the payload does reach the host.
clean_traces
QPCP_PROBE_CONTROL=1 lake env lean tests/merged/merged_buildtime.lean > /dev/null 2>&1
if [ -f /tmp/qpcp_probe_merged_buildtime ] && [ "$(cat scripts/qpcp_canary)" != original ]; then
  ok "positive control: run unsandboxed, the payload writes to /tmp and overwrites scripts/qpcp_canary"
else bad "positive control: the payload left no trace even unsandboxed; the checks below would prove nothing"; fi
clean_traces

install_merged
# Place 4 (this job's trusted build): merged files are not built at all.
before="$(snapshot)"
out=$(python3 -I scripts/sandbox_verify.py trusted-build $NS 2>/dev/null | tail -1)
case "$out" in "trusted build:"*) ok "place 4: the trusted build builds only Defs, Qudit and Statements" ;; *) bad "place 4: trusted build: $out" ;; esac
after "place 4 (trusted build)" "$before"

if [ -n "$NS" ]; then
  echo "  skip  places 1-3 need the sandbox; with --no-sandbox the payload would really run"
else
  # Place 1 (contributor check): a new contribution imports the merged file.
  clean_traces; before="$(snapshot)"
  out=$(scripts/contribution_check.sh proof $TARGET tests/merged/bad_imports_merged.lean 2>/dev/null | tail -1)
  case "$out" in REJECTED*"required type"*) ok "place 1: the wrong-type contribution that imports it stays rejected: ${out#REJECTED: }" ;;
    *) bad "place 1: contribution importing the merged file: $out" ;; esac
  after "place 1 (contributor check)" "$before"
  clean_traces
  out=$(scripts/contribution_check.sh lemma L900001 tests/honest/L900001.lean 2>/dev/null | tail -1)
  case "$out" in "ACCEPTED: lemma L900001") ok "place 1: a later honest contribution is still accepted" ;; *) bad "place 1: later honest lemma: $out" ;; esac

  # Places 2 and 3 (record check, with its per-module leanchecker replay).
  only="QPCP.Proofs.S031,QPCP.Lemmas.L900003,QPCP.Proofs.L900003,QPCP.Proofs.S001"
  clean_traces; before="$(snapshot)"
  rec=$(python3 -I scripts/sandbox_verify.py record --only "$only" --skip-scan-for-tests 2>/dev/null)
  if printf '%s\n' "$rec" | grep -q "ACCEPTED  proof S001" && printf '%s\n' "$rec" | grep -q "REJECTED  proof S031"; then
    ok "place 2: the record check still accepts S001 and rejects the merged S031"
  else bad "place 2: record check verdicts: $(printf '%s' "$rec" | tr '\n' ';')"; fi
  after "place 2 (record check)" "$before"
  clean_traces; before="$(snapshot)"
  rec=$(python3 -I scripts/sandbox_verify.py record --replay-only --only "$only" --skip-scan-for-tests 2>/dev/null)
  if printf '%s\n' "$rec" | grep -q "ACCEPTED  proof S001"; then ok "place 3: the leanchecker replay still passes S001"
  else bad "place 3: replay verdicts: $(printf '%s' "$rec" | tr '\n' ';')"; fi
  after "place 3 (leanchecker replay)" "$before"
fi
remove_merged; rm -f scripts/qpcp_canary

rm -rf "$ROOT/.lake/qpcp-tests"

echo "passed $passes, failed $fails"
[ "$fails" = 0 ]
