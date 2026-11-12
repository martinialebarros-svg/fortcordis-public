#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_UNDER_TEST="${REPO_ROOT}/scripts/collect_vps_ingress_diagnostics.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_ROOT}"' EXIT

fail() {
  echo "[test-vps-ingress-diagnostics] $*" >&2
  exit 1
}

mkdir -p "${FIXTURE_ROOT}/bin" "${FIXTURE_ROOT}/proc/net" "${FIXTURE_ROOT}/proc/sys/fs"

cat >"${FIXTURE_ROOT}/bin/ss" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" state syn-recv "*) printf 'SYN-RECV\n' ;;
  *" state established "*) printf 'ESTAB\nESTAB\n' ;;
  *) printf 'LISTEN\n' ;;
esac
EOF

cat >"${FIXTURE_ROOT}/bin/sysctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
test "${1:-}" = "-n"
case "${2:-}" in
  net.core.somaxconn) echo 4096 ;;
  net.ipv4.tcp_max_syn_backlog) echo 2048 ;;
  net.netfilter.nf_conntrack_count) echo 12 ;;
  net.netfilter.nf_conntrack_max) echo 65536 ;;
  fs.file-max) echo 999999 ;;
  *) exit 1 ;;
esac
EOF

cat >"${FIXTURE_ROOT}/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  is-active) echo active ;;
  show)
    cat <<'PROPERTIES'
ActiveState=active
SubState=running
NRestarts=2
TasksCurrent=4
TasksMax=100
LimitNOFILE=1048576
PROPERTIES
    ;;
  *) exit 1 ;;
esac
EOF

cat >"${FIXTURE_ROOT}/bin/journalctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'worker_connections are not enough' 'routine message' 'upstream timed out' 'accept() failed'
EOF

chmod +x "${FIXTURE_ROOT}/bin/ss" "${FIXTURE_ROOT}/bin/sysctl" "${FIXTURE_ROOT}/bin/systemctl" "${FIXTURE_ROOT}/bin/journalctl"

cat >"${FIXTURE_ROOT}/proc/net/netstat" <<'EOF'
TcpExt: ListenOverflows ListenDrops TCPBacklogDrop TCPReqQFullDrop TCPReqQFullDoCookies SyncookiesSent SyncookiesRecv TCPSynRetrans TCPTimeouts TCPAbortOnMemory TCPMemoryPressures Other
TcpExt: 3 4 5 6 7 8 9 10 11 12 13 14
EOF
printf '100 10 1000\n' >"${FIXTURE_ROOT}/proc/sys/fs/file-nr"

output="$(PATH="${FIXTURE_ROOT}/bin:${PATH}" DIAGNOSTICS_PROC_ROOT="${FIXTURE_ROOT}/proc" bash "${SCRIPT_UNDER_TEST}")"

printf '%s\n' "${output}" | grep -Fqx 'READ_ONLY_DIAGNOSTIC version=1' || fail "missing diagnostic header"
printf '%s\n' "${output}" | grep -Fqx 'SOCKETS listen_443=1' || fail "missing listener count"
printf '%s\n' "${output}" | grep -Fqx 'SOCKETS syn_recv_443=1' || fail "missing SYN queue count"
printf '%s\n' "${output}" | grep -Fqx 'SOCKETS established_443=2' || fail "missing established count"
printf '%s\n' "${output}" | grep -Fqx 'SYSCTL net.core.somaxconn=4096' || fail "missing backlog limit"
printf '%s\n' "${output}" | grep -Fqx 'TCP_EXT ListenOverflows=3' || fail "missing TCP overflow counter"
printf '%s\n' "${output}" | grep -Fqx 'NGINX_STATE active' || fail "missing Nginx state"
printf '%s\n' "${output}" | grep -Fqx 'NGINX_RECENT_INGRESS_ERRORS window_minutes=30 count=3' || fail "missing aggregated Nginx errors"

if grep -Eq '\bsudo\b|systemctl (restart|reload|stop)|rm -rf|sed -i' "${SCRIPT_UNDER_TEST}"; then
  fail "collector contains a mutation-capable command"
fi

echo "VPS ingress diagnostics tests passed."
