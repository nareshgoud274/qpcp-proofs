#!/usr/bin/env bash
# Installs a pinned elan release on a Linux x86_64 CI runner and puts it on the
# PATH. The download is checked against a fixed SHA-256 before anything in it
# runs; elan then installs the toolchain named in lean-toolchain.
#
# elan-init.sh, the usual installer, always fetches the latest elan release,
# so pinning that script would not pin elan; this script is used instead.
# To update: pick a release, download its x86_64-unknown-linux-gnu archive,
# and replace both values below.
set -euo pipefail
ELAN_VERSION="v4.4.0"
ELAN_SHA256="0e8250aa2be86c7af929ade68db617af9edc8b9ccf6eaf5ece228250d0d032e2"
dir="$(mktemp -d)"; trap 'rm -rf "$dir"' EXIT
curl -sSfL -o "$dir/elan.tar.gz" \
  "https://github.com/leanprover/elan/releases/download/${ELAN_VERSION}/elan-x86_64-unknown-linux-gnu.tar.gz"
echo "${ELAN_SHA256}  $dir/elan.tar.gz" | sha256sum -c --quiet -
tar -xzf "$dir/elan.tar.gz" -C "$dir"
"$dir/elan-init" -y --no-modify-path --default-toolchain none
echo "$HOME/.elan/bin" >> "${GITHUB_PATH:-/dev/null}"
