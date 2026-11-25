#!/usr/bin/env bash
# Release claims on step issues that have had no activity for 24 hours.
#
#   expire_claims.sh sweep [--except <issue>]
#       every claimed issue whose last update is over 24 hours old
#   expire_claims.sh target <issue> <comment-id>
#       one issue, judged by its last comment before <comment-id> (the comment
#       that triggered the run, which itself refreshes the issue's update time)
#
# Needs GH_TOKEN and GH_REPO. Used by claim.yml, so that a stale claim is
# released at the moment someone tries to claim (scheduled runs have been
# unreliable on this repository), and by expire-claims.yml as a backstop.
# Prints the numbers of the issues it released.
set -euo pipefail
LAPSE=86400

release() {  # release <issue> <comma-separated assignees>
  local args=(--remove-label claimed)
  [ -n "${2:-}" ] && args+=(--remove-assignee "$2")
  gh issue edit "$1" "${args[@]}" > /dev/null
  gh issue comment "$1" --body "The claim lapsed after 24 hours without activity. This step is open again." > /dev/null
  echo "$1"
}

case "${1:-}" in
  sweep)
    except="${3:-}"
    [ "${2:-}" = "--except" ] || except=""
    gh issue list --state open --label claimed --limit 500 --json number,updatedAt,assignees \
      --jq ".[] | select((.updatedAt | fromdateiso8601) < (now - $LAPSE)) | \"\(.number) \([.assignees[].login] | join(\",\"))\"" \
    | while read -r number assignees; do
        [ "$number" = "$except" ] && continue
        release "$number" "${assignees:-}"
      done
    ;;
  target)
    issue="${2:?issue}"; comment="${3:?comment id}"
    [[ "$issue" =~ ^[0-9]+$ && "$comment" =~ ^[0-9]+$ ]] || { echo "bad arguments" >&2; exit 2; }
    info="$(gh issue view "$issue" --json labels,assignees,createdAt \
      --jq '[([.labels[].name] | index("claimed") != null), ([.assignees[].login] | join(",")), .createdAt] | @tsv')"
    IFS=$'\t' read -r claimed assignees created <<< "$info"
    [ "$claimed" = "true" ] || exit 0
    last="$(gh api "repos/$GH_REPO/issues/$issue/comments" --paginate \
      --jq "[.[] | select(.id != $comment) | .created_at] | last // empty" | tail -n 1)"
    last="${last:-$created}"
    if [ "$(date -u -d "$last" +%s)" -lt "$(( $(date -u +%s) - LAPSE ))" ]; then
      release "$issue" "${assignees:-}"
    fi
    ;;
  *) echo "usage: expire_claims.sh sweep [--except <issue>] | target <issue> <comment-id>" >&2; exit 2 ;;
esac
