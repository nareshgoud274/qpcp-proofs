#!/usr/bin/env bash
# The no-install route for a Mac (JOIN.md, "A machine with nothing installed").
# Run by the OWNER, after reading it, in an ordinary terminal.
#
# Downloads a pinned Lima release for this Mac's architecture, checks it
# against a pinned SHA-256 before anything in it runs, and unpacks it into
# ~/qpcp-setup/lima. Nothing is installed system-wide: no sudo, no Homebrew,
# no change to your shell's startup files. Lima's VMs then live in
# ~/qpcp-setup/lima-home. To remove everything afterwards: stop and delete the
# VM, `limactl prune` (Lima's image cache in ~/Library/Caches/lima), then
# `rm -rf ~/qpcp-setup`.
#
# To update: pick a release, and for each archive below replace its SHA-256,
# checking it against the release's SHA256SUMS.
set -euo pipefail
LIMA_VERSION="2.3.0"
LIMA_SHA256_ARM64="b7af444bd8f91d3c307477e562f2cf3bd7595d62b9429185e4fa841563578cfc"
LIMA_SHA256_X86_64="d58bc7d6b8158d638720d8c8fdb17eb58527dfead6a29a5b60f48a35ee4a65a6"
SETUP="${QPCP_SETUP_DIR:-$HOME/qpcp-setup}"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "get_lima.sh: for macOS only. On Linux, use Docker Engine from your distribution (JOIN.md)." >&2; exit 1
fi
case "$(uname -m)" in
  arm64) arch=arm64; sha="$LIMA_SHA256_ARM64" ;;
  x86_64) arch=x86_64; sha="$LIMA_SHA256_X86_64" ;;
  *) echo "get_lima.sh: unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac
if [ -x "$SETUP/lima/bin/limactl" ]; then
  echo "get_lima.sh: Lima is already in $SETUP/lima; nothing to do."
else
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  file="lima-${LIMA_VERSION}-Darwin-${arch}.tar.gz"
  curl -fsSL -o "$tmp/$file" "https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/${file}"
  echo "${sha}  $tmp/$file" | shasum -a 256 -c --quiet -
  echo "get_lima.sh: Lima ${LIMA_VERSION} for ${arch}, SHA-256 checked"
  mkdir -p "$SETUP/lima" "$SETUP/lima-home"
  tar -xzf "$tmp/$file" -C "$SETUP/lima"
fi
"$SETUP/lima/bin/limactl" --version
cat <<EOF

Lima is in $SETUP/lima. In every terminal where you use it, first run:

  export PATH="$SETUP/lima/bin:\$PATH" LIMA_HOME="$SETUP/lima-home"

Then run workspace_check.sh again, from a terminal where you ran that line.
EOF
