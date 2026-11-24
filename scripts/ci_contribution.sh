#!/usr/bin/env bash
# The contributor path of the `check` workflow, as a script so it can be tested.
#
#   ci_contribution.sh gate  <base-sha>   git only: exactly one new contribution file
#   ci_contribution.sh check <base-sha>   scan, move the file aside, sandboxed check
#
# `gate` runs before anything else in the job, so a pull request that changes
# more than one file gets nothing of its own executed. After `gate`, every file
# other than the contribution is main's, including this script.
set -euo pipefail
cd "$(dirname "$0")/.."
CMD="${1:-}"; BASE="${2:-}"
[ -n "$BASE" ] || { echo "usage: ci_contribution.sh <gate|check> <base-sha>"; exit 2; }

case "$CMD" in
  gate)
    files="$(git diff --name-status --no-renames "$BASE"...HEAD)"
    printf '%s\n' "$files"
    n="$(printf '%s\n' "$files" | grep -c . || true)"
    if [ "$n" != 1 ]; then
      echo "REJECTED: a contribution must add exactly one file; this pull request changes $n"
      exit 1
    fi
    if ! printf '%s\n' "$files" | grep -qE $'^A\tQPCP/((Proofs|Refutations)/(S[0-9]{3,6}|L[0-9]{1,9})|Lemmas/L[0-9]{1,9})\\.lean$'; then
      echo "REJECTED: a contribution adds one new file QPCP/Proofs/<ID>.lean, QPCP/Refutations/<ID>.lean or QPCP/Lemmas/L<N>.lean"
      exit 1
    fi
    echo "gate: one new contribution file"
    ;;
  check)
    scan="$(python3 scripts/check.py scan "$BASE")" || { echo "$scan"; exit 1; }
    echo "$scan"
    line="$(printf '%s\n' "$scan" | sed -n 's/^CONTRIBUTION: //p')"
    read -r kind ident path <<< "$line"
    [ -n "${path:-}" ] || { echo "FAULT: the scanner named no contribution"; exit 2; }
    # Move the contribution aside so that the trusted build is main's.
    aside="${RUNNER_TEMP:-$PWD/.lake}/qpcp-aside"
    rm -rf "$aside" && mkdir -p "$aside"
    mv "$path" "$aside/$ident.lean"
    scripts/contribution_check.sh "$kind" "$ident" "$aside/$ident.lean"
    ;;
  *) echo "usage: ci_contribution.sh <gate|check> <base-sha>"; exit 2 ;;
esac
