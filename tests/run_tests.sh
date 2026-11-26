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
#      For each, the export was canonicalized, type-checked by nanoda and
#      compared in sandboxes of their own, and nanoda read the canonical file.
#   5. Forged and malformed exports of each honest contribution (proof, lemma,
#      refutation) are all rejected, each for its expected reason, and a
#      reference without `Not` is refused.
#   6. A merged file whose code runs at build time (tests/merged/) cannot alter a
#      later verdict in any of the four places that build merged files: the
#      contributor check, the record check (maintainer pull requests and
#      verify-main), the per-module leanchecker replay, and this job's own
#      trusted build. Nothing it writes reaches the host, the scripts or the
#      toolchain, and the verdicts around it stay correct.
#
# Exit 0 only if every test passes.
#
# The real checkout is never written. The suite runs in a disposable copy of
# the repository (its tracked files, plus untracked files outside QPCP/, with
# .lake/packages hard-linked), made under $RUNNER_TEMP or ~/.cache and deleted
# on exit, failure or interrupt. Before anything else, and before any trap is
# installed, it refuses to start if QPCP/ has uncommitted changes, unless it
# runs in CI ($CI set). Inside the copy it uses only fixture ids, which the
# gate and the scanner refuse for any real contribution (S900000-S999999 and
# L900000-L999999): the proof target S900030 and the merged file S900031 are
# the copy's own statements, `def S900030 : Prop := S030` and
# `def S900031 : Prop := S031`, appended to the copy's QPCP/Statements.lean,
# and the tests/merged/ fixtures are rewritten from S030/S031 to them in the
# copy only. No Lean file on main changes.
set -uo pipefail
cd "$(dirname "$0")/.."
MODE="${1:-sandbox}"

if [ "${QPCP_SUITE_COPY:-}" != "$(pwd -P)" ]; then
  # ------------------------------------------------ the real checkout: read only
  REAL="$(pwd -P)"
  if [ -z "${CI:-}" ]; then
    dirty="$(git status --porcelain --untracked-files=all -- QPCP)"
    if [ -n "$dirty" ]; then
      echo "REFUSED: QPCP/ has uncommitted changes; commit or move them before running the tests:"
      printf '%s\n' "$dirty"
      exit 2
    fi
  fi
  base="${RUNNER_TEMP:-${XDG_CACHE_HOME:-$HOME/.cache}}"
  mkdir -p "$base"
  SUITE="$(mktemp -d "$base/qpcp-suite.XXXXXX")" || exit 2
  SUITE="$(cd "$SUITE" && pwd -P)"
  cleanup() { rm -rf "$SUITE"; }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  COPY="$SUITE/repo"
  mkdir -p "$COPY/.lake"
  echo "Copying the repository to $COPY"
  python3 -I - "$REAL" "$COPY" <<'PYCOPY' || exit 2
import os, shutil, subprocess, sys
from pathlib import Path
real, copy = Path(sys.argv[1]), Path(sys.argv[2])
def listed(*args):
    out = subprocess.run(["git", "ls-files", "-z", *args], cwd=real, capture_output=True, check=True).stdout
    return [f.decode() for f in out.split(b"\0") if f]
# Tracked files, and untracked ones outside QPCP/ (new tests or scripts under development).
names = listed() + listed("--others", "--exclude-standard", "--", ":!QPCP")
for rel in dict.fromkeys(names):
    src = real / rel
    if src.is_symlink() or not src.is_file():
        continue
    dest = copy / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
PYCOPY
  # Mathlib and the other packages: hard links, so the copy's paths are its own.
  cp -al "$REAL/.lake/packages" "$COPY/.lake/packages" || { echo "FAULT: cannot hard-link .lake/packages into $COPY (another filesystem?)"; exit 2; }
  ( cd "$COPY" || exit 2
    python3 -I - <<'PYFIX' || exit 2
import json, re
from pathlib import Path
st = Path("QPCP/Statements.lean"); text = st.read_text()
fixture = ("/-- Test fixtures (tests/run_tests.sh, disposable copy only). -/\n"
           "def S900030 : Prop := S030\n\n/-- Test fixture. -/\ndef S900031 : Prop := S031\n\n")
assert text.rstrip().endswith("end QPCP.Statement")
st.write_text(text[:text.rstrip().rfind("end QPCP.Statement")] + fixture + "end QPCP.Statement\n")
steps = json.loads(Path("steps.json").read_text())
steps += [{"id": i, "title": "Test fixture", "section": "Test fixtures", "difficulty": 1, "deps": []}
          for i in ("S900030", "S900031")]
Path("steps.json").write_text(json.dumps(steps, indent=1) + "\n")
for f in Path("tests/merged").glob("*.lean"):
    f.write_text(re.sub(r"S03([01])\b", r"S90003\1", f.read_text()))
PYFIX
    git init -q && git add -A \
      && git -c user.name=qpcp-tests -c user.email=qpcp-tests@example.invalid -c commit.gpgsign=false commit -qm "disposable test copy" \
      || exit 2
    pwd -P > .qpcp-suite-copy
    echo "Building the trusted modules in the copy"
    lake build QPCP.Statements > "$SUITE/build.log" 2>&1 || { tail -40 "$SUITE/build.log"; echo "FAULT: the copy does not build"; exit 2; }
  ) || exit 2
  QPCP_SUITE_COPY="$COPY" bash "$COPY/tests/run_tests.sh" "$@"
  exit $?
fi

# ---------------------------------------------------- inside the disposable copy
ROOT="$(pwd -P)"
[ "$(cat .qpcp-suite-copy 2>/dev/null)" = "$ROOT" ] || { echo "FAULT: not inside the suite's disposable copy"; exit 2; }
NS=""; [ "$MODE" = "--no-sandbox" ] && NS="--no-sandbox"
fails=0; passes=0
ok()   { passes=$((passes + 1)); echo "  ok    $*"; }
bad()  { fails=$((fails + 1)); echo "  FAIL  $*"; }
markers() { ls /tmp/qpcp_probe_* 2>/dev/null | wc -l | tr -d ' '; }
ATTACKS=$(ls tests/attacks/*.lean tests/attacks/import-time/ProbeInit.lean tests/attacks/import-time/ProbeEnvExt.lean)
TARGET=S900030   # a fixture statement of the copy (see the top)
MERGED=S900031   # the fixture statement the merged build-time file claims to prove
n_work=0
newwork() {  # each verifier run gets a directory of its own, passed in QPCP_WORK
  n_work=$((n_work + 1)); mkdir -p "$ROOT/.lake/qpcp-work"; export QPCP_WORK="$ROOT/.lake/qpcp-work/$n_work"
}

# Put anything moved aside back, whatever happens.
restore() {
  [ -f "$ROOT/.lake/qpcp-tests/S019.lean" ] && mv "$ROOT/.lake/qpcp-tests/S019.lean" QPCP/Proofs/S019.lean
  rm -f QPCP/Lemmas/L900002.lean QPCP/Proofs/$TARGET.lean
  rm -f QPCP/Proofs/$MERGED.lean QPCP/Lemmas/L900003.lean QPCP/Proofs/L900003.lean scripts/qpcp_canary
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
  newwork
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
newwork
out=$(scripts/contribution_check.sh proof S019 "$ROOT/.lake/qpcp-tests/S019.lean" $NS 2>/dev/null | tail -1)
case "$out" in "ACCEPTED: proof S019") ok "pipeline accepts the merged proof of S019" ;; *) bad "honest proof S019: $out" ;; esac
keep() {  # keep <label>: save the honest export and its references for step 5
  python3 -I - "$QPCP_WORK/result/contribution.json" "$ROOT/.lake/qpcp-tests" "$1" <<'PYKEEP'
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
# The trusted checks on the export ran in sandboxes of their own, on the canonical file.
WORK="$QPCP_WORK"
steps="$(cat "$WORK/logs/steps.log" 2>/dev/null)"
for step in canon nanoda verify; do
  want="sandboxed"; [ -n "$NS" ] && want="UNSANDBOXED"
  if printf '%s\n' "$steps" | grep -q "^$step $want "; then ok "honest proof: the $step step ran $want"
  else bad "honest proof: no $want $step step in steps.log"; fi
done
if [ -z "$NS" ] && printf '%s\n' "$steps" | grep -q " UNSANDBOXED "; then bad "a step ran unsandboxed"; fi
nanoda_in="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["export_file_path"])' \
  "$WORK/ref/QPCP.Proofs.S019.nanoda.json" 2>/dev/null)"
# Sandboxed, $WORK is mounted at /qpcp/work.
canon_dir="/qpcp/work/canon/"; [ -n "$NS" ] && canon_dir="$WORK/canon/"
case "$nanoda_in" in "$canon_dir"*) ok "nanoda read the canonical export" ;; *) bad "nanoda read $nanoda_in" ;; esac
mv "$ROOT/.lake/qpcp-tests/S019.lean" QPCP/Proofs/S019.lean

newwork
out=$(scripts/contribution_check.sh lemma L900001 tests/honest/L900001.lean $NS 2>/dev/null | tail -1)
case "$out" in "ACCEPTED: lemma L900001") ok "pipeline accepts an honest lemma" ;; *) bad "honest lemma: $out" ;; esac
keep lemma-L900001

cp tests/honest/L900002.lean QPCP/Lemmas/L900002.lean
newwork
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
  out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$honest" "$ref")
  case "$out" in ACCEPTED*) ok "$kind $ident: the honest export itself is accepted" ;; *) bad "$kind $ident: honest export rejected: $out" ;; esac
  # An incomplete reference (a requested name main lacks) must be refused too.
  printf 'propext\nQPCP.NoSuchConstant\n' > "$dir.names"
  out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$honest" "$ref" "$dir.names")
  case "$out" in REJECTED*"QPCP.NoSuchConstant"*) ok "$kind $ident: refuses an incomplete reference" ;; *) bad "$kind $ident: incomplete reference not refused: $out" ;; esac
  while IFS=$'\t' read -r name expect; do
    out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$dir/$name.ndjson" "$ref")
    case "$out" in
      "REJECTED: "*"$expect"*) ok "$kind $ident: rejects $name: ${out#REJECTED: }" ;;
      REJECTED*) bad "$kind $ident: rejects $name for another reason than [$expect]: $out" ;;
      *) bad "$kind $ident: accepts forged $name: $out" ;;
    esac
  done < <(python3 -I tests/forge_exports.py "$kind" "$ident" "$honest" "$ref" "$dir")
  # A reference that lacks `Not` (always required) is refused: drop it from every reference file.
  noNot=""; i=0
  IFS=',' read -r -a refs <<< "$ref"
  for r in "${refs[@]}"; do
    i=$((i + 1))
    python3 -I - "$r" "$dir.noNot$i.ndjson" <<'PYNOT'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
names = {0: ""}
for r in rows:
    if "in" in r:
        pre, val = (r["str"]["pre"], r["str"]["str"]) if "str" in r else (r["num"]["pre"], r["num"]["i"])
        names[r["in"]] = (names[pre] + "." if names[pre] else "") + str(val)
keep = [r for r in rows if not ("def" in r and names[r["def"]["name"]] == "Not")]
open(sys.argv[2], "w").write("".join(json.dumps(r) + "\n" for r in keep))
PYNOT
    noNot="${noNot:+$noNot,}$dir.noNot$i.ndjson"
  done
  out=$(python3 -I scripts/verify_export.py "$kind" "$ident" "$honest" "$noNot")
  case "$out" in REJECTED*"main has no \`Not\`"*) ok "$kind $ident: refuses a reference without Not" ;; *) bad "$kind $ident: reference without Not: $out" ;; esac
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
  cp tests/merged/merged_buildtime.lean QPCP/Proofs/$MERGED.lean
  cp tests/merged/merged_init_lemma.lean QPCP/Lemmas/L900003.lean
  cp tests/merged/merged_init_user.lean QPCP/Proofs/L900003.lean
}
remove_merged() { rm -f QPCP/Proofs/$MERGED.lean QPCP/Lemmas/L900003.lean QPCP/Proofs/L900003.lean; }
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
newwork
out=$(python3 -I scripts/sandbox_verify.py trusted-build $NS 2>/dev/null | tail -1)
case "$out" in "trusted build:"*) ok "place 4: the trusted build builds only Defs, Qudit, Statements and Promise" ;; *) bad "place 4: trusted build: $out" ;; esac
after "place 4 (trusted build)" "$before"

if [ -n "$NS" ]; then
  echo "  skip  places 1-3 need the sandbox; with --no-sandbox the payload would really run"
else
  # Place 1 (contributor check): a new contribution imports the merged file.
  clean_traces; before="$(snapshot)"
  newwork
  out=$(scripts/contribution_check.sh proof $TARGET tests/merged/bad_imports_merged.lean 2>/dev/null | tail -1)
  # Any rejection will do: which check fires first depends on the forgery.
  case "$out" in REJECTED*) ok "place 1: the wrong-type contribution that imports it stays rejected: ${out#REJECTED: }" ;;
    *) bad "place 1: contribution importing the merged file: $out" ;; esac
  after "place 1 (contributor check)" "$before"
  clean_traces
  newwork
  out=$(scripts/contribution_check.sh lemma L900001 tests/honest/L900001.lean 2>/dev/null | tail -1)
  case "$out" in "ACCEPTED: lemma L900001") ok "place 1: a later honest contribution is still accepted" ;; *) bad "place 1: later honest lemma: $out" ;; esac

  # Places 2 and 3 (record check, with its per-module leanchecker replay).
  only="QPCP.Proofs.$MERGED,QPCP.Lemmas.L900003,QPCP.Proofs.L900003,QPCP.Proofs.S001"
  clean_traces; before="$(snapshot)"
  newwork
  rec=$(python3 -I scripts/sandbox_verify.py record --only "$only" --skip-scan-for-tests 2>/dev/null)
  if printf '%s\n' "$rec" | grep -q "ACCEPTED  proof S001" && printf '%s\n' "$rec" | grep -q "REJECTED  proof $MERGED"; then
    ok "place 2: the record check still accepts S001 and rejects the merged $MERGED"
  else bad "place 2: record check verdicts: $(printf '%s' "$rec" | tr '\n' ';')"; fi
  after "place 2 (record check)" "$before"
  clean_traces; before="$(snapshot)"
  newwork
  rec=$(python3 -I scripts/sandbox_verify.py record --replay-only --only "$only" --skip-scan-for-tests 2>/dev/null); rc=$?
  # A replay-only run accepts nothing: its verdict is REPLAYED-ONLY, its exit code 3.
  if printf '%s\n' "$rec" | grep -q "REPLAYED-ONLY proof S001"; then ok "place 3: the leanchecker replay still passes S001"
  else bad "place 3: replay verdicts: $(printf '%s' "$rec" | tr '\n' ';')"; fi
  if printf '%s\n' "$rec" | grep -q "ACCEPTED"; then bad "place 3: a replay-only run printed ACCEPTED"
  else ok "place 3: a replay-only run prints no ACCEPTED"; fi
  after "place 3 (leanchecker replay)" "$before"
fi
remove_merged; rm -f scripts/qpcp_canary

rm -rf "$ROOT/.lake/qpcp-tests"

echo "passed $passes, failed $fails"
[ "$fails" = 0 ]
