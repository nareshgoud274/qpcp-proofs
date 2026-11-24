#!/usr/bin/env bash
# Check one contributed file without trusting anything Lean produces from it.
#
#   contribution_check.sh <kind> <ident> <file> [--no-sandbox]
#
# <kind> is proof, refutation or lemma; <file> is the contributed source, which
# must NOT be present at its place in the repository tree (the caller moves it
# aside), so that everything built here first is main's trusted code.
#
# 1. Trusted, outside the sandbox: build the library as it is on main.
# 2. Untrusted, inside a bubblewrap sandbox with no network, a read-only view of
#    the system, a private /tmp and one writable scratch directory: compile the
#    contributed file, replay it with leanchecker, and export it to text.
# 3. Trusted again: take only the export (a regular file, size-capped). Export a
#    reference from main with the toolchain's leanexport: the statement and the
#    permitted axioms, with their whole dependency closure, plus for a lemma
#    the names its definition refers to. Check the untrusted export with the
#    independent kernel nanoda_bin, and compare it with the reference
#    (scripts/verify_export.py). No untrusted .olean is ever read outside the
#    sandbox.
#
# --no-sandbox runs step 2 without isolation. It exists only for development
# on machines without bubblewrap (macOS); CI never passes it.
#
# Prints a final line "ACCEPTED: ..." or "REJECTED: ..."; exit 0 or 1, 2 on a
# fault of the checker itself.
set -uo pipefail

KIND="${1:-}"; IDENT="${2:-}"; FILE="${3:-}"; MODE="${4:-sandbox}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

reject() { echo "REJECTED: $*"; exit 1; }
fault()  { echo "FAULT: $*"; exit 2; }

case "$KIND" in
  proof)      FOLDER=QPCP/Proofs;      PREFIX=QPCP.Proofs;      TARGET="QPCP.Proof.$IDENT" ;;
  refutation) FOLDER=QPCP/Refutations; PREFIX=QPCP.Refutations; TARGET="QPCP.Refutation.$IDENT" ;;
  lemma)      FOLDER=QPCP/Lemmas;      PREFIX=QPCP.Lemmas;      TARGET="QPCP.Lemma.$IDENT" ;;
  *) fault "usage: contribution_check.sh <proof|refutation|lemma> <ident> <file> [--no-sandbox]" ;;
esac
[[ "$IDENT" =~ ^(S[0-9]{3,6}|L[0-9]{1,9})$ ]] || fault "bad id: $IDENT"
[[ "$KIND" != lemma || "$IDENT" =~ ^L ]] || fault "a lemma id starts with L"
[ -f "$FILE" ] && [ ! -L "$FILE" ] || fault "no such regular file: $FILE"
[ ! -e "$FOLDER/$IDENT.lean" ] || fault "$FOLDER/$IDENT.lean is in the tree; move it aside first"
MODULE="$PREFIX.$IDENT"
REL="$FOLDER/$IDENT.lean"

if [[ "$IDENT" =~ ^S ]]; then STMT="QPCP.Statement.$IDENT"; STMT_MOD=QPCP.Statements
else STMT="QPCP.Lemma.$IDENT"; STMT_MOD="QPCP.Lemmas.$IDENT"; fi
FIXED="propext Classical.choice Quot.sound Quot Quot.mk Quot.lift Quot.ind"

if [ "$MODE" = "--no-sandbox" ]; then
  echo "WARNING: --no-sandbox: the contributed file runs WITHOUT isolation (development only)." >&2
elif ! command -v bwrap >/dev/null 2>&1; then
  fault "bubblewrap (bwrap) is not installed; refusing to build untrusted code unsandboxed"
fi

# The scratch directory must not live under /tmp, which the sandbox replaces.
WORK="${RUNNER_TEMP:-$ROOT/.lake}/qpcp-contribution"
rm -rf "$WORK" && mkdir -p "$WORK/src/$FOLDER" "$WORK/out" "$WORK/export" "$WORK/trusted" || fault "cannot create $WORK"
cp "$FILE" "$WORK/src/$REL" || fault "cannot copy $FILE"

# ---- 1. Trusted: main's library, toolchain paths and the reference export ----
lake build QPCP > "$WORK/trusted/build.log" 2>&1 || { tail -20 "$WORK/trusted/build.log"; fault "main's library does not build"; }
SYSROOT="$(lake env printenv LEAN_SYSROOT)" || fault "cannot locate the toolchain"
TRUSTED_LEAN_PATH="$(lake env printenv LEAN_PATH)" || fault "cannot read LEAN_PATH"
BIN="$SYSROOT/bin"
REPO_LIB="$ROOT/.lake/build/lib/lean"
case ":$TRUSTED_LEAN_PATH:" in *":$REPO_LIB:"*) ;; *) fault "LEAN_PATH does not contain $REPO_LIB" ;; esac
for t in lean leanchecker leanexport nanoda_bin; do [ -x "$BIN/$t" ] || fault "toolchain has no $t"; done
if [ "$KIND" = lemma ]; then
  REF_NAMES="$FIXED"; REF_MOD=QPCP.Statements
else
  REF_NAMES="$STMT $FIXED"; REF_MOD="$STMT_MOD"
fi

# ---- 2. Untrusted: compile, replay and export inside the sandbox ----
# Each step is a fresh sandbox, so nothing started by one step survives into the next.
sandbox() {  # sandbox <writable dir> <LEAN_PATH> <timeout seconds> <command...>
  local rw="$1" lp="$2" secs="$3"; shift 3
  if [ "$MODE" = "--no-sandbox" ]; then
    (cd "$WORK" && env -i PATH="$BIN:/usr/bin:/bin" HOME="$WORK" LEAN_PATH="$lp" timeout "$secs" "$@")
  else
    bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp \
      --bind "$rw" "$rw" --chdir "$WORK" \
      --unshare-all --die-with-parent --new-session --cap-drop ALL \
      --clearenv --setenv PATH "$BIN:/usr/bin:/bin" --setenv HOME /tmp --setenv LEAN_PATH "$lp" \
      -- timeout "$secs" "$@"
  fi
}

# Compile against main's build, writing only to $WORK/out.
sandbox "$WORK/out" "$TRUSTED_LEAN_PATH" 1500 "$BIN/lean" --root="$WORK/src" -o "$WORK/out/contribution.olean" "$WORK/src/$REL" \
  > "$WORK/trusted/compile.log" 2>&1 || { tail -c 3000 "$WORK/trusted/compile.log"; reject "the file does not compile"; }
OUT_OLEAN="$WORK/out/contribution.olean"
[ -f "$OUT_OLEAN" ] && [ ! -L "$OUT_OLEAN" ] || reject "the sandbox produced no compiled file"
# A fresh copy of main's compiled QPCP modules plus that one file. The copy
# replaces main's entry on the search path for the replay and export steps.
mkdir -p "$WORK/lib" && cp -R "$REPO_LIB/QPCP" "$REPO_LIB/QPCP.olean" "$WORK/lib/" 2>/dev/null || cp -R "$REPO_LIB/QPCP" "$WORK/lib/" || fault "cannot copy main's build"
rm -f "$WORK/lib/$FOLDER/$IDENT".*
mkdir -p "$WORK/lib/$FOLDER" && cp "$OUT_OLEAN" "$WORK/lib/$FOLDER/$IDENT.olean" || fault "cannot place the compiled file"
rm -rf "$WORK/out"
CHECK_LEAN_PATH="$(printf '%s' "$TRUSTED_LEAN_PATH" | tr ':' '\n' | sed "s#^$REPO_LIB\$#$WORK/lib#" | paste -sd: -)"
sandbox "$WORK/export" "$CHECK_LEAN_PATH" 600 "$BIN/leanchecker" "$MODULE" > "$WORK/trusted/replay.log" 2>&1 \
  || { tail -c 2000 "$WORK/trusted/replay.log"; reject "leanchecker's kernel replay failed"; }
sandbox "$WORK/export" "$CHECK_LEAN_PATH" 600 sh -c "\"$BIN/leanexport\" \"$MODULE\" -- \"$TARGET\" > \"$WORK/export/contribution.ndjson\"" \
  2> "$WORK/trusted/export.err" || { tail -c 2000 "$WORK/trusted/export.err"; reject "cannot export $TARGET"; }

# ---- 3. Trusted: take only the export, then check it twice ----
EXPORT="$WORK/export/contribution.ndjson"
[ -f "$EXPORT" ] && [ ! -L "$EXPORT" ] || reject "the sandbox produced no export"
SIZE=$(wc -c < "$EXPORT")
[ "$SIZE" -le 2000000000 ] || reject "the export is larger than 2 GB"
cp "$EXPORT" "$WORK/trusted/contribution.ndjson" || fault "cannot copy the export"
rm -rf "$WORK/lib" "$WORK/export"

# The reference, exported from main outside the sandbox. For a lemma, add the
# names its definition refers to; main exports them with their whole closure.
DEPS=""
if [ "$KIND" = lemma ]; then
  python3 -I scripts/verify_export.py deps "$IDENT" "$WORK/trusted/contribution.ndjson" > "$WORK/trusted/deps.txt" \
    || reject "$(tail -1 "$WORK/trusted/deps.txt" | sed 's/^REJECTED: //')"
  [ "$(wc -l < "$WORK/trusted/deps.txt")" -le 5000 ] || reject "the statement refers to more than 5000 constants"
  DEPS="$(cat "$WORK/trusted/deps.txt")"
fi
printf '%s\n' $REF_NAMES $DEPS > "$WORK/trusted/reference.names"
LEAN_PATH="$TRUSTED_LEAN_PATH" "$BIN/leanexport" $REF_MOD -- $REF_NAMES $DEPS > "$WORK/trusted/reference.ndjson" 2> "$WORK/trusted/reference.err" \
  || { tail -5 "$WORK/trusted/reference.err"; fault "cannot export the reference from main"; }
if grep -q "PANIC" "$WORK/trusted/reference.err"; then
  reject "main has no constant named in the export ($(grep -o 'Constant [^ ]* not found' "$WORK/trusted/reference.err" | head -1))"
fi

cat > "$WORK/trusted/nanoda.json" <<EOF
{"export_file_path": "$WORK/trusted/contribution.ndjson", "use_stdin": false,
 "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"],
 "unpermitted_axiom_hard_error": true, "nat_extension": true, "string_extension": true,
 "print_success_message": true}
EOF
timeout 1800 "$BIN/nanoda_bin" "$WORK/trusted/nanoda.json" > "$WORK/trusted/nanoda.log" 2>&1 \
  || { tail -c 2000 "$WORK/trusted/nanoda.log"; reject "the independent kernel (nanoda) rejects the export"; }
grep -q "with no typechecker errors" "$WORK/trusted/nanoda.log" || { tail -c 2000 "$WORK/trusted/nanoda.log"; reject "the independent kernel (nanoda) did not report success"; }

VERDICT="$(timeout 1800 python3 -I scripts/verify_export.py "$KIND" "$IDENT" "$WORK/trusted/contribution.ndjson" "$WORK/trusted/reference.ndjson" "$WORK/trusted/reference.names")"
STATUS=$?
echo "$VERDICT"
exit $STATUS
