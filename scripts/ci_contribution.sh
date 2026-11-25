#!/usr/bin/env bash
# The contributor path of the `check` workflow, as a script so it can be tested.
#
#   ci_contribution.sh gate  <base-sha>   git only: exactly one new contribution file
#   ci_contribution.sh check <base-sha>   scan, move the file aside, sandboxed check
#
# `gate` runs before anything else in the job. For a pull request that adds
# exactly one contribution file, every other file, including this script and
# the workflow that runs it, is main's. A pull request that changes more files,
# such as the workflow itself, runs its own copy of the workflow, which need not
# call this gate at all and can pass its own check; automerge.py never merges
# such a pull request (see the note at the top of check.yml).
set -euo pipefail
cd "$(dirname "$0")/.."
CMD="${1:-}"; BASE="${2:-}"
[ -n "$BASE" ] || { echo "usage: ci_contribution.sh <gate|check> <base-sha>"; exit 2; }

case "$CMD" in
  gate)
    files="$(git diff --name-status --no-renames "$BASE"...HEAD)"
    # File names are the contributor's: no line breaks or `::` reach the log.
    printf '%s\n' "$files" | python3 -I scripts/logsafe.py
    n="$(printf '%s\n' "$files" | grep -c . || true)"
    if [ "$n" != 1 ]; then
      echo "REJECTED: a contribution must add exactly one file; this pull request changes $n"
      exit 1
    fi
    if ! printf '%s\n' "$files" | grep -qE $'^A\tQPCP/((Proofs|Refutations)/(S[0-9]{3,6}|L[0-9]{1,9})|Lemmas/L[0-9]{1,9})\\.lean$'; then
      echo "REJECTED: a contribution adds one new file QPCP/Proofs/<ID>.lean, QPCP/Refutations/<ID>.lean or QPCP/Lemmas/L<N>.lean"
      exit 1
    fi
    # The Git entry, not the working copy, and before any content is read: a
    # regular, non-executable file (mode 100644). A symlink (120000), an
    # executable (100755) or a submodule (160000) is refused here.
    path="$(printf '%s\n' "$files" | cut -f2)"
    entry="$(git ls-tree HEAD -- "$path")"
    mode="${entry%% *}"; rest="${entry#* }"; type="${rest%% *}"
    if [ "$mode" != 100644 ] || [ "$type" != blob ]; then
      echo "REJECTED: $path must be a regular file (Git mode 100644); this one has Git mode ${mode:-none}"
      exit 1
    fi
    ident="$(basename "$path" .lean)"
    if printf '%s\n' "$ident" | grep -qE '^[SL]9[0-9]{5}$'; then
      echo "REJECTED: $ident is reserved for the test suite's fixtures"
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
    # Move the contribution aside so that the trusted build is main's. The copy
    # checked is the committed blob the scanner read, not the working copy.
    aside="$(mktemp -d "${RUNNER_TEMP:-$PWD/.lake}/qpcp-aside.XXXXXX")"
    git cat-file blob "HEAD:$path" > "$aside/$ident.lean"
    rm -f -- "$path"
    scripts/contribution_check.sh "$kind" "$ident" "$aside/$ident.lean"
    ;;
  *) echo "usage: ci_contribution.sh <gate|check> <base-sha>"; exit 2 ;;
esac
