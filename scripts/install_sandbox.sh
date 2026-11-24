#!/usr/bin/env bash
# Install bubblewrap on a GitHub ubuntu-latest runner and prove it isolates.
#
# Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor, which
# bubblewrap needs. Rather than lifting that restriction for every program, give
# bwrap its own AppArmor profile that permits user namespaces (the approach
# Ubuntu documents). Then check that a sandbox really has no network and cannot
# write to the host, and fail if it can.
set -euo pipefail

sudo apt-get update -qq
sudo apt-get install -y -qq bubblewrap > /dev/null
BWRAP="$(command -v bwrap)"

if [ -d /etc/apparmor.d ] && command -v apparmor_parser > /dev/null; then
  sudo tee /etc/apparmor.d/qpcp-bwrap > /dev/null <<EOF
abi <abi/4.0>,
include <tunables/global>
profile qpcp-bwrap $BWRAP flags=(unconfined) {
  userns,
}
EOF
  sudo apparmor_parser -r /etc/apparmor.d/qpcp-bwrap
fi

probe="$RUNNER_TEMP/qpcp-sandbox-probe"
rm -f "$probe"
"$BWRAP" --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-all --die-with-parent \
  --new-session --cap-drop ALL --clearenv --setenv PATH /usr/bin:/bin -- \
  sh -c "touch '$probe' 2>/dev/null; touch /tmp/inside; getent hosts github.com > /dev/null 2>&1 && echo NET || echo NONET" \
  > "$RUNNER_TEMP/qpcp-sandbox-probe.out"
out="$(cat "$RUNNER_TEMP/qpcp-sandbox-probe.out")"
[ "$out" = "NONET" ] || { echo "sandbox check failed: network reachable ($out)"; exit 1; }
[ ! -e "$probe" ] || { echo "sandbox check failed: it wrote to the host"; exit 1; }
[ ! -e /tmp/inside ] || { echo "sandbox check failed: its /tmp is the host's"; exit 1; }
echo "bubblewrap $("$BWRAP" --version) works: no network, read-only host, private /tmp"
