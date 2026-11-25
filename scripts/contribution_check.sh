#!/usr/bin/env bash
# Check one contributed file without trusting anything Lean produces from it.
#
#   contribution_check.sh <kind> <ident> <file> [--no-sandbox]
#
# A thin wrapper around scripts/sandbox_verify.py (see there): only the
# maintainer-written modules are built outside a sandbox; the contribution, and
# every merged contribution it needs, is compiled, replayed and exported inside
# bubblewrap; the verdict comes from checking the text exports outside it.
# <file> must NOT be present at its place in the repository tree.
#
# Prints a final line "ACCEPTED: ..." or "REJECTED: ..."; exit 0, 1, or 2 on a
# fault of the checker itself.
set -uo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 3 ] || { echo "usage: contribution_check.sh <proof|refutation|lemma> <ident> <file> [--no-sandbox]"; exit 2; }
exec python3 -I scripts/sandbox_verify.py contribution "$1" "$2" "$3" "${@:4}"
