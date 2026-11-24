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

smoke() {  # prints NONET only if a sandbox has no network and cannot touch the host
  local probe="$RUNNER_TEMP/qpcp-sandbox-probe"
  rm -f "$probe" /tmp/qpcp-sandbox-inside
  local out
  out="$("$BWRAP" --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-all --die-with-parent \
    --new-session --cap-drop ALL --clearenv --setenv PATH /usr/bin:/bin -- \
    sh -c "touch '$probe' 2>/dev/null; touch /tmp/qpcp-sandbox-inside; getent hosts github.com > /dev/null 2>&1 && echo NET || echo NONET" 2>&1)" || true
  echo "$out"
  [ "$out" = "NONET" ] && [ ! -e "$probe" ] && [ ! -e /tmp/qpcp-sandbox-inside ]
}

if smoke; then
  echo "sandbox works with the AppArmor profile for bwrap"
else
  # The runner's AppArmor policy still withholds capabilities inside new user
  # namespaces (bwrap then cannot bring up loopback in its network namespace).
  # Lift the restriction on this throwaway runner only, and test again.
  sudo aa-status 2>/dev/null | grep -q qpcp-bwrap && echo "(profile qpcp-bwrap is loaded)" || echo "(profile qpcp-bwrap is not loaded)"
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
  smoke || { echo "sandbox check failed: bubblewrap does not isolate on this runner"; exit 1; }
  echo "sandbox works after lifting kernel.apparmor_restrict_unprivileged_userns on this runner"
fi
echo "bubblewrap $("$BWRAP" --version): no network, read-only host, private /tmp"
