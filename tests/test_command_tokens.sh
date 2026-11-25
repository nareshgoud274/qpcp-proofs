#!/usr/bin/env bash
# The scanner's table of command tokens (scripts/command_tokens.txt) must be
# exactly what Lean reports for the pinned toolchain, Mathlib and the
# project's maintainer-written modules. Needs the Mathlib cache.
#
#   tests/test_command_tokens.sh
set -uo pipefail
cd "$(dirname "$0")/.."
lake build QPCP.Statements > /dev/null || { echo "FAIL  the maintainer-written modules do not build"; exit 1; }
fresh="$(mktemp)"; trap 'rm -f "$fresh"' EXIT
lake env lean tests/gen_command_tokens.lean > "$fresh" || { echo "FAIL  cannot list the command tokens"; cat "$fresh"; exit 1; }
if diff -u scripts/command_tokens.txt "$fresh"; then
  echo "  ok    scripts/command_tokens.txt matches the toolchain and Mathlib ($(wc -l < "$fresh" | tr -d ' ') tokens)"
  echo "failed 0"
else
  echo "  FAIL  scripts/command_tokens.txt is out of date: regenerate it with"
  echo "        lake env lean tests/gen_command_tokens.lean > scripts/command_tokens.txt"
  echo "failed 1"; exit 1
fi
