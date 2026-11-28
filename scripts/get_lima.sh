#!/usr/bin/env bash
# The no-install route for a Mac (JOIN.md, "A machine with nothing installed").
# Run by the OWNER, after reading it, in an ordinary terminal.
#
# Downloads a pinned Lima release for this Mac's architecture, checks it
# against a pinned SHA-256 before anything in it runs, and unpacks it into
# ~/qpcp-setup/lima. Nothing is installed system-wide: no sudo, no Homebrew,
# no change to your shell's startup files. Lima's VMs then live in
# ~/qpcp-setup/lima-home.
#
# It trusts nothing already there: if ~/qpcp-setup/lima exists, it stops and
# runs nothing from it. A fresh copy is unpacked into a temporary folder inside
# ~/qpcp-setup and moved into place only after the checksum and the unpacking
# have both succeeded, so an interrupted run leaves no half-installed Lima.
#
# To remove everything afterwards: stop and delete the VM, `limactl prune`
# (Lima's image cache in ~/Library/Caches/lima), then `rm -rf ~/qpcp-setup`.
#
# To update: pick a release, and for each archive below replace its SHA-256,
# checking it against the release's SHA256SUMS.
set -euo pipefail
LIMA_VERSION="2.3.0"
LIMA_SHA256_ARM64="b7af444bd8f91d3c307477e562f2cf3bd7595d62b9429185e4fa841563578cfc"
LIMA_SHA256_X86_64="d58bc7d6b8158d638720d8c8fdb17eb58527dfead6a29a5b60f48a35ee4a65a6"
SETUP="${QPCP_SETUP_DIR:-$HOME/qpcp-setup}"
DEST="$SETUP/lima"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "get_lima.sh: for macOS only. On Linux, use Docker Engine from your distribution (JOIN.md)." >&2; exit 1
fi
case "$(uname -m)" in
  arm64) arch=arm64; sha="$LIMA_SHA256_ARM64" ;;
  x86_64) arch=x86_64; sha="$LIMA_SHA256_X86_64" ;;
  *) echo "get_lima.sh: unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac
if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  echo "get_lima.sh: $DEST already exists. This run did not check it, so it runs nothing from it." >&2
  echo "get_lima.sh: if it is a copy you trust, use it as it is; otherwise remove it (rm -rf \"$DEST\") and run this again." >&2
  exit 1
fi
mkdir -p "$SETUP"
tmp="$(mktemp -d "$SETUP/.get_lima.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
trap 'exit 130' INT TERM HUP
file="lima-${LIMA_VERSION}-Darwin-${arch}.tar.gz"
curl -fsSL --max-time 300 -o "$tmp/$file" "https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/${file}"
echo "${sha}  $tmp/$file" | shasum -a 256 -c --quiet -
echo "get_lima.sh: Lima ${LIMA_VERSION} for ${arch}, SHA-256 checked"
mkdir "$tmp/lima"
tar -xzf "$tmp/$file" -C "$tmp/lima"
[ -x "$tmp/lima/bin/limactl" ] || { echo "get_lima.sh: the archive has no bin/limactl; nothing was installed" >&2; exit 1; }
[ ! -e "$DEST" ] || { echo "get_lima.sh: $DEST appeared while this ran; nothing was installed" >&2; exit 1; }
mv "$tmp/lima" "$DEST"
mkdir -p "$SETUP/lima-home"
"$DEST/bin/limactl" --version
cat <<EOF

Lima is in $DEST. In every terminal where you use it, first run:

  export PATH="$DEST/bin:\$PATH" LIMA_HOME="$SETUP/lima-home"

Then run workspace_check.sh again, from a terminal where you ran that line.
EOF
