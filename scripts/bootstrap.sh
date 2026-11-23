#!/usr/bin/env bash
# First build. Pins the Lean toolchain to the one Mathlib's stable branch uses,
# fetches Mathlib and its prebuilt cache, then builds definitions and statements.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v lake >/dev/null 2>&1; then
  echo "lake not found. Install elan first: https://github.com/leanprover/elan" >&2
  exit 1
fi

echo "==> Pinning the Lean toolchain to Mathlib's stable branch"
curl -sSfL \
  https://raw.githubusercontent.com/leanprover-community/mathlib4/stable/lean-toolchain \
  -o lean-toolchain
cat lean-toolchain

echo "==> Resolving dependencies"
lake update

echo "==> Fetching the Mathlib cache"
lake exe cache get

echo "==> Building definitions and statements"
lake build QPCP.Defs QPCP.Statements

echo "==> Done. Commit lean-toolchain and lake-manifest.json."
