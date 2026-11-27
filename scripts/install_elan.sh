#!/usr/bin/env bash
# Installs a pinned elan release on Linux (x86_64 or aarch64) and puts it on the
# PATH. Used by CI and by volunteers' workspaces (JOIN.md, "Set up"). The
# download is checked against a fixed SHA-256 before anything in it runs; elan
# then installs no toolchain (--default-toolchain none): the Lean version comes
# from lean-toolchain when lake first runs.
#
# elan-init.sh, the usual installer, always fetches the latest elan release,
# so pinning that script would not pin elan; this script is used instead.
# To update: pick a release, and for each archive below
# (elan-<arch>-unknown-linux-gnu.tar.gz) replace its SHA-256, checking it
# against the release's published digest.
set -euo pipefail
ELAN_VERSION="v4.4.0"
ELAN_SHA256_X86_64="0e8250aa2be86c7af929ade68db617af9edc8b9ccf6eaf5ece228250d0d032e2"
ELAN_SHA256_AARCH64="45cde3006f82f98804c94cf2ca4949d117060a5f3cc8afa62f523759947ee21f"
if [ "$(uname -s)" != "Linux" ]; then
  echo "install_elan.sh: Linux only (this is $(uname -s))" >&2; exit 1
fi
case "$(uname -m)" in
  x86_64) arch=x86_64; sha="$ELAN_SHA256_X86_64" ;;
  aarch64|arm64) arch=aarch64; sha="$ELAN_SHA256_AARCH64" ;;
  *) echo "install_elan.sh: unsupported architecture $(uname -m) (x86_64 and aarch64 only)" >&2; exit 1 ;;
esac
dir="$(mktemp -d)"; trap 'rm -rf "$dir"' EXIT
curl -sSfL -o "$dir/elan.tar.gz" \
  "https://github.com/leanprover/elan/releases/download/${ELAN_VERSION}/elan-${arch}-unknown-linux-gnu.tar.gz"
echo "${sha}  $dir/elan.tar.gz" | sha256sum -c --quiet -
echo "install_elan.sh: elan ${ELAN_VERSION} for ${arch} Linux, SHA-256 checked"
tar -xzf "$dir/elan.tar.gz" -C "$dir"
"$dir/elan-init" -y --no-modify-path --default-toolchain none
echo "$HOME/.elan/bin" >> "${GITHUB_PATH:-/dev/null}"
