#!/usr/bin/env bash
# The test suite never touches a volunteer's uncommitted work.
#
#   tests/test_suite_safety.sh            the quick cases below (a few minutes)
#   tests/test_suite_safety.sh plant      plant the two files, for a full run
#   tests/test_suite_safety.sh verify     check them byte for byte, then remove them
#
# It creates uncommitted QPCP/Proofs/S030.lean and QPCP/Proofs/S031.lean in
# this checkout, with random contents, and confirms they are byte-for-byte
# unchanged after tests/run_tests.sh:
#
#   1. refuses to start (outside CI, QPCP/ has uncommitted changes);
#   2. runs and fails (CI set, `lake env` made to fail, so every Lean check fails);
#   3. is interrupted (CI set, SIGINT to its process group once it is running
#      the tests inside its copy);
#   4. runs and passes: CI runs `plant`, then the full suite, then `verify`.
#
# After 2 and 3, no disposable copy is left behind. The planted files are this
# test's own; it refuses to start if either already exists, and removes them
# only after confirming they are unchanged.
set -uo pipefail
cd "$(dirname "$0")/.."
REAL="$(pwd -P)"
STATE="${RUNNER_TEMP:-${XDG_CACHE_HOME:-$HOME/.cache}}/qpcp-suite-safety"
FILES="QPCP/Proofs/S030.lean QPCP/Proofs/S031.lean"
fails=0
ok()  { echo "  ok    $*"; }
bad() { fails=$((fails + 1)); echo "  FAIL  $*"; }

plant() {
  for f in $FILES; do
    if [ -e "$f" ] || [ -L "$f" ]; then echo "REFUSED: $f already exists; this test only plants files of its own"; exit 2; fi
  done
  rm -rf "$STATE" && mkdir -p "$STATE"
  for f in $FILES; do
    python3 -I -c 'import os, sys; sys.stdout.buffer.write(b"-- planted by tests/test_suite_safety.sh\n" + os.urandom(4096).hex().encode() + b"\n")' > "$f"
    cp "$f" "$STATE/$(basename "$f")"
  done
}

unchanged() {  # unchanged <when>
  for f in $FILES; do
    if [ -f "$f" ] && [ ! -L "$f" ] && cmp -s "$f" "$STATE/$(basename "$f")"; then ok "$1: $f is byte-for-byte unchanged"
    else bad "$1: $f was changed, moved or deleted"; fi
  done
}

remove_planted() {
  for f in $FILES; do
    cmp -s "$f" "$STATE/$(basename "$f")" 2>/dev/null && rm -f "$f"
  done
  rm -rf "$STATE"
}

copies() { ls -d "${RUNNER_TEMP:-${XDG_CACHE_HOME:-$HOME/.cache}}"/qpcp-suite.* 2>/dev/null | sort; }

case "${1:-quick}" in
  plant) plant; echo "planted $FILES"; exit 0 ;;
  verify) unchanged "after the full suite"; remove_planted; echo "failed $fails"; [ "$fails" = 0 ]; exit ;;
  quick) ;;
  *) echo "usage: test_suite_safety.sh [plant|verify]"; exit 2 ;;
esac

plant
trap remove_planted EXIT
before_copies="$(copies)"
log="$STATE/suite.log"

echo "1. The suite refuses to start"
out="$(env -u CI tests/run_tests.sh 2>&1)"; rc=$?
case "$out" in REFUSED*) [ "$rc" = 2 ] && ok "refuses with exit 2: $(printf '%s' "$out" | head -1)" || bad "refused with exit $rc" ;;
  *) bad "did not refuse (exit $rc): $(printf '%s' "$out" | head -3)" ;; esac
unchanged "after the refusal"

echo "2. The suite runs and fails"
fake="$STATE/fake-bin"; mkdir -p "$fake"
real_lake="$(command -v lake)"
cat > "$fake/lake" <<EOF
#!/usr/bin/env bash
# Every 'lake env' fails, so every Lean check in the suite fails; building still works.
[ "\${1:-}" = env ] && { echo "fake lake: env refused for tests/test_suite_safety.sh" >&2; exit 1; }
exec "$real_lake" "\$@"
EOF
chmod +x "$fake/lake"
CI=1 PATH="$fake:$PATH" tests/run_tests.sh > "$log" 2>&1; rc=$?
if [ "$rc" != 0 ] && grep -q "FAIL" "$log" && grep -q "^passed [0-9]*, failed [1-9]" "$log"; then
  ok "the suite ran inside its copy and failed (exit $rc, $(grep -c 'FAIL' "$log") failures)"
else bad "the suite did not run and fail as intended (exit $rc): $(tail -5 "$log" | tr '\n' ';')"; fi
unchanged "after a failing run"
[ "$(copies)" = "$before_copies" ] && ok "after a failing run, no disposable copy is left" || bad "a disposable copy was left: $(copies)"

echo "3. The suite is interrupted"
set -m   # the suite gets a process group of its own, as at a terminal
CI=1 tests/run_tests.sh > "$log" 2>&1 &
pid=$!
set +m
for _ in $(seq 1 900); do
  grep -q "^2. Source scanner" "$log" 2>/dev/null && break
  kill -0 "$pid" 2>/dev/null || break
  sleep 1
done
if grep -q "^2. Source scanner" "$log"; then
  kill -INT -- "-$pid" 2>/dev/null
  wait "$pid"; rc=$?
  [ "$rc" != 0 ] && ok "interrupted inside its copy, while testing (exit $rc)" || bad "the interrupted suite exited 0"
else
  kill -TERM -- "-$pid" 2>/dev/null; wait "$pid"
  bad "the suite never reached its tests: $(tail -5 "$log" | tr '\n' ';')"
fi
unchanged "after an interrupt"
for _ in $(seq 1 30); do [ "$(copies)" = "$before_copies" ] && break; sleep 1; done
[ "$(copies)" = "$before_copies" ] && ok "after an interrupt, no disposable copy is left" || bad "a disposable copy was left: $(copies)"

echo "failed $fails"
[ "$fails" = 0 ]
