#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_UNDER_TEST="${REPO_ROOT}/scripts/monitor_vps_ingress_deltas.sh"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_ROOT}"' EXIT

fail() {
  echo "[test-vps-ingress-monitor] $*" >&2
  exit 1
}

cat >"${FIXTURE_ROOT}/collector.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
counter_file="\${MONITOR_TEST_COUNTER_FILE:-${FIXTURE_ROOT}/collector-count}"
if [[ "\${MONITOR_TEST_FAIL:-0}" == 1 ]]; then
  echo 'private fixture text must not leak' >&2
  exit 1
fi
count=0
if [[ -f "\${counter_file}" ]]; then
  count="\$(<"\${counter_file}")"
fi
count=\$((count + 1))
printf '%s' "\${count}" >"\${counter_file}"

case "\${count}" in
  1)
    cat <<'SNAPSHOT'
SOCKETS syn_recv_443=4
SOCKETS established_443=1
SYSCTL net.netfilter.nf_conntrack_count=10
TCP_EXT ListenOverflows=1
TCP_EXT ListenDrops=10
TCP_EXT TCPBacklogDrop=0
TCP_EXT TCPReqQFullDrop=0
TCP_EXT TCPReqQFullDoCookies=2
TCP_EXT SyncookiesSent=2
TCP_EXT TCPSynRetrans=20
NGINX_RECENT_INGRESS_ERRORS window_minutes=30 count=0
SNAPSHOT
    ;;
  2)
    cat <<'SNAPSHOT'
SOCKETS syn_recv_443=7
SOCKETS established_443=3
SYSCTL net.netfilter.nf_conntrack_count=12
TCP_EXT ListenOverflows=1
TCP_EXT ListenDrops=12
TCP_EXT TCPBacklogDrop=0
TCP_EXT TCPReqQFullDrop=0
TCP_EXT TCPReqQFullDoCookies=3
TCP_EXT SyncookiesSent=3
TCP_EXT TCPSynRetrans=25
NGINX_RECENT_INGRESS_ERRORS window_minutes=30 count=1
SNAPSHOT
    ;;
  3)
    cat <<'SNAPSHOT'
SOCKETS syn_recv_443=2
SOCKETS established_443=2
SYSCTL net.netfilter.nf_conntrack_count=11
TCP_EXT ListenOverflows=1
TCP_EXT ListenDrops=9
TCP_EXT TCPBacklogDrop=unavailable
TCP_EXT TCPReqQFullDrop=0
TCP_EXT TCPReqQFullDoCookies=3
TCP_EXT SyncookiesSent=3
TCP_EXT TCPSynRetrans=28
NGINX_RECENT_INGRESS_ERRORS window_minutes=30 count=1
SNAPSHOT
    ;;
  *)
    cat <<'SNAPSHOT'
SOCKETS syn_recv_443=2
SOCKETS established_443=2
SYSCTL net.netfilter.nf_conntrack_count=11
TCP_EXT ListenOverflows=1
TCP_EXT ListenDrops=15
TCP_EXT TCPBacklogDrop=0
TCP_EXT TCPReqQFullDrop=0
TCP_EXT TCPReqQFullDoCookies=3
TCP_EXT SyncookiesSent=3
TCP_EXT TCPSynRetrans=30
NGINX_RECENT_INGRESS_ERRORS window_minutes=30 count=1
SNAPSHOT
    ;;
esac
EOF

cat >"${FIXTURE_ROOT}/sleep" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF

chmod +x "${FIXTURE_ROOT}/collector.sh" "${FIXTURE_ROOT}/sleep"

# MacOS nao possui GNU timeout; o teste verifica o contrato e substitui apenas
# a espera. O workflow Linux usa GNU timeout real.
cat >"${FIXTURE_ROOT}/timeout" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
test "$1" = --kill-after=2
test "$2" = 8
shift 2
exec "$@"
EOF
chmod +x "${FIXTURE_ROOT}/timeout"

output="$(PATH="${FIXTURE_ROOT}:${PATH}" \
  INGRESS_MONITOR_COLLECTOR_SCRIPT="${FIXTURE_ROOT}/collector.sh" \
  INGRESS_MONITOR_SAMPLES=4 \
  INGRESS_MONITOR_INTERVAL_SECONDS=1 \
  bash "${SCRIPT_UNDER_TEST}")"

printf '%s\n' "${output}" | grep -Fqx 'INGRESS_MONITOR version=1 samples=4 interval_seconds=1' || fail "missing monitor header"
printf '%s\n' "${output}" | grep -Eq '^INGRESS_MONITOR_SAMPLE index=2 elapsed_seconds=[0-9]+ syn_recv_443=7 established_443=3 conntrack_count=12 nginx_journal_matches_30m=1 timestamp_utc=' || fail "missing second sample"
printf '%s\n' "${output}" | grep -Eq '^INGRESS_COUNTER_DELTA index=2 elapsed_seconds=[0-9]+ ListenOverflows=0 ListenDrops=2 TCPBacklogDrop=0 TCPReqQFullDrop=0 TCPReqQFullDoCookies=1 SyncookiesSent=1 TCPSynRetrans=5$' || fail "incorrect interval delta"
printf '%s\n' "${output}" | grep -Eq '^INGRESS_COUNTER_DELTA index=3 elapsed_seconds=[0-9]+ ListenOverflows=0 ListenDrops=unavailable' || fail "counter reset was inferred as a numeric delta"
printf '%s\n' "${output}" | grep -Eq '^INGRESS_COUNTER_DELTA index=4 elapsed_seconds=[0-9]+ ListenOverflows=0 ListenDrops=6 TCPBacklogDrop=unavailable' || fail "recovered counters were not handled correctly"
printf '%s\n' "${output}" | grep -Fq 'INGRESS_MONITOR_SUMMARY samples=4 interval_seconds=1 max_syn_recv_443=7 max_established_443=3 max_conntrack_count=12 collector_failures=0' || fail "incorrect occupancy peak"
printf '%s\n' "${output}" | grep -Fqx 'INGRESS_COUNTER_TOTAL_DELTA ListenOverflows=0 ListenDrops=unavailable TCPBacklogDrop=unavailable TCPReqQFullDrop=0 TCPReqQFullDoCookies=1 SyncookiesSent=1 TCPSynRetrans=10' || fail "reset or missing intermediate counter did not invalidate total"

# Mesmo contrato usado pelo SSH: arquivo no checkout, sem dependencia do cwd.
remote_style_output="$(cd "${FIXTURE_ROOT}" && PATH="${FIXTURE_ROOT}:${PATH}" \
  MONITOR_TEST_COUNTER_FILE="${FIXTURE_ROOT}/remote-count" \
  INGRESS_MONITOR_COLLECTOR_SCRIPT="${FIXTURE_ROOT}/collector.sh" \
  INGRESS_MONITOR_SAMPLES=2 INGRESS_MONITOR_INTERVAL_SECONDS=1 \
  bash "${SCRIPT_UNDER_TEST}")"
printf '%s\n' "${remote_style_output}" | grep -Fq 'INGRESS_MONITOR completed' || fail "monitor failed from another working directory"

set +e
failure_output="$(PATH="${FIXTURE_ROOT}:${PATH}" MONITOR_TEST_FAIL=1 \
  INGRESS_MONITOR_COLLECTOR_SCRIPT="${FIXTURE_ROOT}/collector.sh" \
  INGRESS_MONITOR_SAMPLES=2 INGRESS_MONITOR_INTERVAL_SECONDS=1 \
  bash "${SCRIPT_UNDER_TEST}" 2>&1)"
failure_exit=$?
set -e
(( failure_exit != 0 )) || fail "failed collector reported success"
printf '%s\n' "${failure_output}" | grep -Fq 'collector_failures=2' || fail "failed samples were not counted"
if printf '%s\n' "${failure_output}" | grep -Fq 'private fixture'; then
  fail "collector stderr leaked"
fi

if grep -Eq '\bsudo\b|systemctl|rm -rf|\btee\b|\btouch\b|\bmkdir\b|\bcurl\b' "${SCRIPT_UNDER_TEST}"; then
  fail "monitor contains a mutation-capable or client-data command"
fi

if PATH="${FIXTURE_ROOT}:${PATH}" INGRESS_MONITOR_COLLECTOR_SCRIPT="${FIXTURE_ROOT}/collector.sh" INGRESS_MONITOR_SAMPLES=1 bash "${SCRIPT_UNDER_TEST}" >/dev/null 2>&1; then
  fail "invalid sample count was accepted"
fi

if PATH="${FIXTURE_ROOT}:${PATH}" INGRESS_MONITOR_COLLECTOR_SCRIPT="${FIXTURE_ROOT}/collector.sh" INGRESS_MONITOR_SAMPLES=60 INGRESS_MONITOR_INTERVAL_SECONDS=60 bash "${SCRIPT_UNDER_TEST}" >/dev/null 2>&1; then
  fail "monitoring window above the safety limit was accepted"
fi

echo "VPS ingress delta monitor tests passed."
