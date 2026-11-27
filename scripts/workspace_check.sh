#!/usr/bin/env bash
# Can this machine host a qpcp-proofs workspace? Run by the OWNER, in an
# ordinary terminal, before giving an agent anything (JOIN.md, "Before
# anything else"). Takes about a minute, or two the first time Lima downloads
# its Ubuntu image.
#
# It installs nothing. It only looks, except for one throwaway guest, which it
# starts and deletes. With Lima, the guest's Ubuntu image stays in Lima's
# cache (about 3 GB, ~/Library/Caches/lima on macOS): the workspace reuses it,
# and `limactl prune` removes it. It checks:
#   1. free disk in your home folder (the workspace and its downloads);
#   2. whether this terminal reaches github.com;
#   3. Docker (running) or Lima (on the PATH, or from scripts/get_lima.sh in
#      ~/qpcp-setup), and whether it can start a guest;
#   4. from INSIDE that guest, whether github.com and the hosts the setup
#      downloads from can be reached.
# Every FAIL says what to do next; after fixing one, run this again.
set -u
NEED_GB=25
SETUP="${QPCP_SETUP_DIR:-$HOME/qpcp-setup}"
fails=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$1"; shift; for l in "$@"; do printf '      Next: %s\n' "$l"; done; fails=$((fails + 1)); }

# 1. Disk.
avail_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR == 2 { print $4 }')
avail_gb=$(( ${avail_kb:-0} / 1024 / 1024 ))
if [ "$avail_gb" -ge "$NEED_GB" ]; then
  pass "disk: $avail_gb GB free in your home folder (need $NEED_GB GB)"
else
  fail "disk: $avail_gb GB free in your home folder; $NEED_GB GB are needed" \
    "free up space. The workspace uses about 15 GB (Lean about 3 GB, Mathlib's build about 7.5 GB, the system);" \
    "downloaded images add about 3 GB, and Lima itself about 0.1 GB. Docker Desktop keeps them in its own disk"
fi

# 2. This terminal's network.
if curl -sS -o /dev/null --max-time 15 https://github.com 2>/dev/null; then
  pass "network: this terminal reaches github.com"
else
  fail "network: this terminal cannot reach github.com" \
    "check your connection, proxy or firewall. If a browser on this machine works but this terminal does not," \
    "something on this machine blocks command-line access (JOIN.md, \"Network\")"
fi

# 3. A container or virtual machine tool.
LIMACTL=""
if command -v limactl >/dev/null 2>&1; then
  LIMACTL=$(command -v limactl)
elif [ -x "$SETUP/lima/bin/limactl" ]; then
  LIMACTL="$SETUP/lima/bin/limactl"
  export LIMA_HOME="${LIMA_HOME:-$SETUP/lima-home}"
fi
mode=""
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  mode=docker; pass "workspace tool: Docker is running"
elif [ -n "$LIMACTL" ]; then
  mode=lima; pass "workspace tool: Lima ($LIMACTL)"
elif command -v docker >/dev/null 2>&1; then
  fail "workspace tool: Docker is installed but not running" "start Docker (Docker Desktop, or the docker service), then run this again"
else
  case "$(uname -s)" in
    Darwin) fail "workspace tool: neither Docker nor Lima is on this Mac" \
      "the no-install route: with your approval, scripts/get_lima.sh downloads a pinned, checksummed Lima" \
      "into ~/qpcp-setup, nothing system-wide (JOIN.md, \"A machine with nothing installed\")" ;;
    *) fail "workspace tool: neither Docker nor Lima is on this machine" \
      "on Linux, install Docker Engine from your distribution (Ubuntu: sudo apt-get install docker.io)," \
      "or Lima (JOIN.md, \"A machine with nothing installed\")" ;;
  esac
fi

# 4. A throwaway guest, and the network from inside it.
HOSTS="github.com raw.githubusercontent.com release-assets.githubusercontent.com cache.mathlib.org"
probe='for h in '"$HOSTS"'; do if (exec 3<>"/dev/tcp/$h/443") 2>/dev/null; then echo "reach $h ok"; else echo "reach $h FAILED"; fi; done
case "$(uname -m)" in aarch64|arm64) m=ports.ubuntu.com ;; *) m=archive.ubuntu.com ;; esac
if (exec 3<>"/dev/tcp/$m/80") 2>/dev/null; then echo "reach $m ok"; else echo "reach $m FAILED"; fi'
out=""
case "$mode" in
  docker)
    out=$(docker run --rm ubuntu:24.04 bash -c "$probe" 2>&1) || true ;;
  lima)
    name=qpcp-check
    "$LIMACTL" delete -f "$name" >/dev/null 2>&1 || true
    if "$LIMACTL" create --yes --name="$name" --cpus=1 --memory=1 --disk=10 \
         --set '.mounts = [] | .ssh.forwardAgent = false' template:ubuntu-24.04 >/dev/null 2>&1 \
       && "$LIMACTL" start "$name" >/dev/null 2>&1; then
      out=$("$LIMACTL" shell "$name" -- bash -c "$probe" 2>&1) || true
    else
      out="guest did not start"
    fi
    "$LIMACTL" delete -f "$name" >/dev/null 2>&1 || true ;;
esac
if [ -n "$mode" ]; then
  if ! printf '%s\n' "$out" | grep -q '^reach '; then
    fail "guest: $mode could not start a guest ($(printf '%s' "$out" | tail -1))" \
      "make sure $mode works on its own (for Lima: limactl create and start a VM), then run this again"
  else
    pass "guest: $mode started a guest"
    bad=$(printf '%s\n' "$out" | grep '^reach .* FAILED$' | awk '{print $2}' | tr '\n' ' ')
    if [ -z "$bad" ]; then
      pass "guest network: reaches github.com and every download host"
    else
      fail "guest network: cannot reach: $bad" \
        "a guest needs these hosts to clone and download Lean and Mathlib. Check a proxy or firewall that applies to $mode"
    fi
  fi
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "All checks passed. Give your agent the pinned JOIN.md link."
else
  echo "$fails check(s) failed. Fix them, then run this again, before giving your agent anything."
fi
exit $(( fails > 0 ))
