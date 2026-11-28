#!/usr/bin/env bash
# Can this machine host a qpcp-proofs workspace? Run by the OWNER, in an
# ordinary terminal, before giving an agent anything (JOIN.md, "Before
# anything else"). Takes about a minute, or a few the first time an Ubuntu
# image is downloaded.
#
# It installs nothing. It only looks, except for one throwaway guest, which it
# creates under a name of its own (qpcp-check-<process id>-<random>), probes
# and deletes. It never touches any other guest, and if it is interrupted it
# deletes its own guest on the way out. If that deletion fails it says so,
# with the guest's exact name and the command that removes it.
#
# The image the guest starts from stays, as the workspace reuses it:
#   - Lima keeps its Ubuntu image cache (about 3 GB; ~/Library/Caches/lima on
#     macOS). `limactl prune` removes it.
#   - Docker keeps the pulled ubuntu:24.04 image (about 0.1 GB, inside
#     Docker's own storage). `docker image rm ubuntu:24.04` removes it.
#
# It checks, in this order:
#   1. free disk in your home folder (the workspace and its downloads); if
#      there is too little, no guest is created at all;
#   2. from this terminal, an HTTPS request to github.com (an HTTP error
#      counts as a failure);
#   3. Docker (running) or Lima (on the PATH, or from scripts/get_lima.sh in
#      ~/qpcp-setup), and whether it can start a guest;
#   4. from INSIDE that guest, for github.com and each host the setup
#      downloads from: whether its name resolves, and whether its TCP port
#      (443, or 80 for the Ubuntu mirror) opens. That is all it measures
#      there: it makes no HTTPS request from the guest.
# Every probe has a time limit. Every FAIL says what to do next; after fixing
# one, run this again.
set -u
NEED_GB=25
SETUP="${QPCP_SETUP_DIR:-$HOME/qpcp-setup}"
fails=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$1"; shift; for l in "$@"; do printf '      Next: %s\n' "$l"; done; fails=$((fails + 1)); }

# 1. Disk.
avail_kb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR == 2 { print $4 }')
avail_gb=$(( ${avail_kb:-0} / 1024 / 1024 ))
disk_ok=0
if [ "$avail_gb" -ge "$NEED_GB" ]; then
  disk_ok=1
  pass "disk: $avail_gb GB free in your home folder (need $NEED_GB GB)"
else
  fail "disk: $avail_gb GB free in your home folder; $NEED_GB GB are needed (no test guest was created)" \
    "free up space. The workspace uses about 15 GB (Lean about 3 GB, Mathlib's build about 7.5 GB, the system);" \
    "downloaded images add about 3 GB, and Lima itself about 0.1 GB. Docker Desktop keeps them in its own disk"
fi

# 2. This terminal's network: one HTTPS request; -f makes an HTTP error a failure.
if curl -fsS -o /dev/null --max-time 15 https://github.com 2>/dev/null; then
  pass "network (this terminal): an HTTPS request to github.com succeeded"
else
  fail "network (this terminal): an HTTPS request to github.com failed" \
    "check your connection, proxy or firewall. If a browser on this machine works but this terminal does not," \
    "something on this machine may be blocking command-line access (JOIN.md, \"Network\")"
fi

# 3. A container or virtual machine tool.
LIMACTL=""
lima_env=""
if command -v limactl >/dev/null 2>&1; then
  LIMACTL=$(command -v limactl)
elif [ -x "$SETUP/lima/bin/limactl" ]; then
  LIMACTL="$SETUP/lima/bin/limactl"
  export LIMA_HOME="${LIMA_HOME:-$SETUP/lima-home}"
  lima_env="LIMA_HOME=\"$LIMA_HOME\" "
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
      "you can run scripts/get_lima.sh, which downloads a pinned, checksummed Lima into ~/qpcp-setup and installs" \
      "nothing system-wide. Fetch it from the same commit as this script: in the address you downloaded this from," \
      "replace workspace_check.sh with get_lima.sh (JOIN.md, \"A machine with nothing installed\")" ;;
    *) fail "workspace tool: neither Docker nor Lima is on this machine" \
      "on Linux, install Docker Engine from your distribution (Ubuntu: sudo apt-get install docker.io)," \
      "or Lima (JOIN.md, \"A machine with nothing installed\")" ;;
  esac
fi

# 4. A throwaway guest of this run's own, and the network from inside it.
case "$(uname -m)" in aarch64|arm64) mirror=ports.ubuntu.com ;; *) mirror=archive.ubuntu.com ;; esac
SPECS="github.com:443 raw.githubusercontent.com:443 release-assets.githubusercontent.com:443 cache.mathlib.org:443 $mirror:80"
# One line per host: "probe <host> resolve=ok|FAILED tcp<port>=ok|FAILED". Each probe has a 10-second limit.
probe='for s in '"$SPECS"'; do h=${s%:*}; p=${s#*:}
if timeout 10 getent hosts "$h" >/dev/null 2>&1; then d=ok; else d=FAILED; fi
if timeout 10 bash -c "exec 3<>/dev/tcp/$h/$p" 2>/dev/null; then c=ok; else c=FAILED; fi
echo "probe $h resolve=$d tcp$p=$c"; done'

name="qpcp-check-$$-$RANDOM"
attempted=0   # set just before this run asks for a guest under its own, fresh name
# Is the guest there? Prints present, absent (confirmed), or unknown (the lookup itself failed).
guest_state() {
  case "$mode" in
    docker)
      if look=$(docker container inspect "$name" 2>&1 >/dev/null); then echo present
      else case "$look" in *"No such container"*|*"No such object"*) echo absent ;; *) echo unknown ;; esac; fi ;;
    lima)
      if list=$("$LIMACTL" list --quiet 2>/dev/null); then
        if printf '%s\n' "$list" | grep -qx "$name"; then echo present; else echo absent; fi
      else echo unknown; fi ;;
  esac
}
# Deletes this run's guest. Succeeds only if its absence was confirmed beforehand, or the deletion
# succeeded and its absence is then confirmed; otherwise a FAIL with the exact name and command.
cleanup() {
  [ "$attempted" = 1 ] || return 0
  attempted=0
  [ "$(guest_state)" = absent ] && return 0
  case "$mode" in
    docker) how="docker rm -f $name"; docker rm -f "$name" >/dev/null 2>&1 ;;
    lima) how="${lima_env}$LIMACTL delete -f $name"; "$LIMACTL" delete -f "$name" >/dev/null 2>&1 ;;
  esac
  rc=$?
  if [ "$rc" -eq 0 ] && [ "$(guest_state)" = absent ]; then return 0; fi
  fail "cleanup: the test guest $name could not be confirmed deleted" "remove it with: $how"
  return 1
}
trap 'cleanup; exit 130' INT TERM HUP
trap 'cleanup || exit 1' EXIT

out=""; status=0; started=0
if [ -n "$mode" ] && [ "$disk_ok" = 1 ]; then
  before=$(guest_state)
  if [ "$before" = present ]; then
    fail "guest: a guest named $name already exists; it is not this run's, so it was left alone" "run this again"
  elif [ "$before" = unknown ]; then
    fail "guest: $mode could not list its guests, so no test guest was created" \
      "make sure $mode works on its own (docker ps, or limactl list), then run this again"
  else
    attempted=1
    case "$mode" in
      docker)
        if docker create --name "$name" ubuntu:24.04 bash -c "$probe" >/dev/null 2>&1; then
          started=1; out=$(docker start -a "$name" 2>&1); status=$?
        fi ;;
      lima)
        if "$LIMACTL" create --yes --name="$name" --cpus=1 --memory=1 --disk=10 \
             --set '.mounts = [] | .ssh.forwardAgent = false' template:ubuntu-24.04 >/dev/null 2>&1 \
           && "$LIMACTL" start "$name" >/dev/null 2>&1; then
          started=1; out=$("$LIMACTL" shell "$name" -- bash -c "$probe" 2>&1); status=$?
        fi ;;
    esac
    if cleanup; then gone="now deleted"; else gone="NOT confirmed deleted, see above"; fi
    if [ "$started" = 0 ]; then
      fail "guest: $mode could not start a guest" \
        "make sure $mode works on its own (for Lima: limactl create and start a VM), then run this again"
    else
      pass "guest: $mode started a throwaway guest ($name), $gone"
      lines=$(printf '%s\n' "$out" | awk '$1 == "probe"')
      problems=""
      [ "$status" -eq 0 ] || problems="the probe in the guest exited with status $status; "
      for s in $SPECS; do
        h=${s%:*}
        n=$(printf '%s\n' "$lines" | awk -v h="$h" '$2 == h { n++ } END { print n + 0 }')
        [ "$n" -eq 1 ] || problems="${problems}$n result line(s) for $h, not 1; "
      done
      total=$(printf '%s\n' "$lines" | awk 'NF { n++ } END { print n + 0 }')
      expected=$(printf '%s\n' $SPECS | awk 'END { print NR }')
      [ "$total" -eq "$expected" ] || problems="${problems}$total result line(s) in all, not $expected; "
      if [ -n "$problems" ]; then
        fail "guest network: the probe did not report cleanly (${problems%; })" \
          "run this again; if it repeats, check that $mode guests work on their own"
      else
        bad=$(printf '%s\n' "$lines" | awk '/=FAILED/ { printf "%s (%s) ", $2, ($3 ~ /FAILED/ ? "name does not resolve" : "TCP port does not open") }')
        if [ -z "$bad" ]; then
          pass "guest network: every host's name resolves and its TCP port opens (443; 80 for $mirror); no HTTPS request is made from the guest"
        else
          fail "guest network: ${bad% }" \
            "a guest needs these hosts to clone and download Lean and Mathlib. Check a proxy or firewall that applies to $mode"
        fi
      fi
    fi
  fi
fi

echo
case "$mode" in
  lima) echo "Lima keeps its Ubuntu image cache (about 3 GB) for the workspace; \`limactl prune\` removes it." ;;
  docker) echo "Docker keeps the pulled ubuntu:24.04 image for the workspace; \`docker image rm ubuntu:24.04\` removes it." ;;
esac
if [ "$fails" -eq 0 ]; then
  echo "All checks passed. Give your agent the pinned JOIN.md link."
else
  echo "$fails check(s) failed. Fix them, then run this again, before giving your agent anything."
fi
trap - EXIT
exit $(( fails > 0 ))
