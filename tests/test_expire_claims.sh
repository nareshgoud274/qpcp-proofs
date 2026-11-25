#!/usr/bin/env bash
# Tests for scripts/expire_claims.sh against a stub `gh` (no network). Needs GNU date.
#
#   tests/test_expire_claims.sh
set -uo pipefail
cd "$(dirname "$0")/.."
STUB="$(mktemp -d)"; trap 'rm -rf "$STUB"' EXIT
fails=0
old="$(date -u -d '-30 hours' +%Y-%m-%dT%H:%M:%SZ)"
new="$(date -u -d '-2 hours' +%Y-%m-%dT%H:%M:%SZ)"

# The stub answers from files the test writes, and logs every edit and comment.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "issue view") cat "$STUB_DIR/view" ;;
  "issue list") cat "$STUB_DIR/list" ;;
  "api "*)      cat "$STUB_DIR/comments" ;;
  "issue edit"|"issue comment") echo "$*" >> "$STUB_DIR/log" ;;
esac
EOF
chmod +x "$STUB/gh"
run() { PATH="$STUB:$PATH" STUB_DIR="$STUB" GH_REPO=o/r GH_TOKEN=x bash scripts/expire_claims.sh "$@"; }
check() {  # check <description> <expected released issues> <actual>
  if [ "$2" = "$3" ]; then echo "  ok    $1"; else echo "  FAIL  $1: expected [$2], got [$3]"; fails=1; fi
}

# target: claimed, last earlier comment 30 hours ago -> released
: > "$STUB/log"; printf 'true\talice\t%s\n' "$old" > "$STUB/view"; echo "$old" > "$STUB/comments"
check "a claim idle for 30 hours is released when someone claims" "7" "$(run target 7 99)"
grep -q -- "--remove-label claimed --remove-assignee alice" "$STUB/log" || { echo "  FAIL  release did not remove label and assignee"; fails=1; }

# target: claimed, last earlier comment 2 hours ago -> kept
: > "$STUB/log"; printf 'true\talice\t%s\n' "$old" > "$STUB/view"; echo "$new" > "$STUB/comments"
check "a claim active 2 hours ago is kept" "" "$(run target 7 99)"
[ ! -s "$STUB/log" ] || { echo "  FAIL  a fresh claim was edited"; fails=1; }

# target: claimed, no other comments, issue created 30 hours ago -> released
: > "$STUB/log"; printf 'true\talice\t%s\n' "$old" > "$STUB/view"; : > "$STUB/comments"
check "with no earlier comment, the issue's age counts" "7" "$(run target 7 99)"

# target: not claimed -> nothing
: > "$STUB/log"; printf 'false\t\t%s\n' "$old" > "$STUB/view"; echo "$old" > "$STUB/comments"
check "an unclaimed issue is left alone" "" "$(run target 7 99)"

# sweep: two stale claims, one excepted
: > "$STUB/log"; printf '5 bob\n8 carol\n' > "$STUB/list"
check "the sweep releases stale claims except the given issue" "8" "$(run sweep --except 5)"

# bad arguments are refused
run target 7 "1; rm -rf /" > /dev/null 2>&1 && { echo "  FAIL  bad comment id accepted"; fails=1; } || echo "  ok    a malformed comment id is refused"

echo "failed $fails"
exit $fails
