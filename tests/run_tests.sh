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
  rm -f /tmp/qpcp_probe_*
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
WORK="${RUNNER_TEMP:-$ROOT/.lake}/qpcp-contribution"
keep() {  # keep <label>: save the honest export and its reference for step 5
  cp "$WORK/trusted/contribution.ndjson" "$ROOT/.lake/qpcp-tests/$1.ndjson" 2>/dev/null
  cp "$WORK/trusted/reference.ndjson" "$ROOT/.lake/qpcp-tests/$1.ref.ndjson" 2>/dev/null
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
  honest="$ROOT/.lake/qpcp-tests/$label.ndjson"; ref="$ROOT/.lake/qpcp-tests/$label.ref.ndjson"
  if [ ! -f "$honest" ] || [ ! -f "$ref" ]; then bad "no honest $kind export to forge from (step 4 failed)"; continue; fi
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
rm -rf "$ROOT/.lake/qpcp-tests"

echo "passed $passes, failed $fails"
[ "$fails" = 0 ]
