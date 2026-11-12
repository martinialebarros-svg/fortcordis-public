#!/usr/bin/env bash
set -euo pipefail

# Coleta operacional somente-leitura para investigar indisponibilidade antes do
# TLS. A saida e propositalmente agregada: nao inclui configuracoes, URLs,
# enderecos de clientes nem linhas brutas de log.

PROC_ROOT="${DIAGNOSTICS_PROC_ROOT:-/proc}"
LOG_WINDOW_MINUTES="${DIAGNOSTICS_LOG_WINDOW_MINUTES:-30}"

emit() {
  printf '%s\n' "$*"
}

is_positive_integer() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

read_numeric_sysctl() {
  local key="$1"
  local value

  if ! command -v sysctl >/dev/null 2>&1; then
    emit "SYSCTL ${key}=unavailable"
    return
  fi

  value="$(sysctl -n "${key}" 2>/dev/null || true)"
  if is_positive_integer "${value}"; then
    emit "SYSCTL ${key}=${value}"
  else
    emit "SYSCTL ${key}=unavailable"
  fi
}

count_tls_sockets() {
  local description="$1"
  shift
  local count

  if ! command -v ss >/dev/null 2>&1; then
    emit "SOCKETS ${description}=unavailable"
    return
  fi

  if count="$(ss "$@" 2>/dev/null | wc -l | tr -d '[:space:]')" && is_positive_integer "${count}"; then
    emit "SOCKETS ${description}=${count}"
  else
    emit "SOCKETS ${description}=unavailable"
  fi
}

emit_tcp_ext_counters() {
  local netstat_file="${PROC_ROOT}/net/netstat"

  if [[ ! -r "${netstat_file}" ]]; then
    emit "TCP_EXT unavailable"
    return
  fi

  if ! awk '
    $1 == "TcpExt:" {
      if (!seen_header) {
        for (field_no = 2; field_no <= NF; field_no++) {
          names[field_no] = $field_no
        }
        seen_header = 1
        next
      }

      for (field_no = 2; field_no <= NF; field_no++) {
        name = names[field_no]
        if (name ~ /^(ListenOverflows|ListenDrops|TCPBacklogDrop|TCPReqQFullDrop|TCPReqQFullDoCookies|SyncookiesSent|SyncookiesRecv|TCPSynRetrans|TCPTimeouts|TCPAbortOnMemory|TCPMemoryPressures)$/) {
          printf "TCP_EXT %s=%s\n", name, $field_no
        }
      }
      exit
    }
  ' "${netstat_file}"; then
    emit "TCP_EXT unavailable"
  fi
}

emit_file_usage() {
  local file_nr="${PROC_ROOT}/sys/fs/file-nr"
  local values

  if [[ ! -r "${file_nr}" ]]; then
    emit "FILE_NR unavailable"
    return
  fi

  values="$(tr -d '\n' < "${file_nr}" | tr -s '[:space:]' ' ')"
  if [[ "${values}" =~ ^[0-9]+\ [0-9]+\ [0-9]+$ ]]; then
    emit "FILE_NR allocated_unused_max=${values// /_}"
  else
    emit "FILE_NR unavailable"
  fi
}

emit_nginx_state() {
  local state

  if ! command -v systemctl >/dev/null 2>&1; then
    emit "NGINX_STATE unavailable"
    return
  fi

  state="$(systemctl is-active nginx 2>/dev/null || true)"
  case "${state}" in
    active|inactive|failed|activating|deactivating|unknown)
      emit "NGINX_STATE ${state}"
      ;;
    *)
      emit "NGINX_STATE unavailable"
      ;;
  esac

  if ! systemctl show nginx --no-pager \
    --property=ActiveState \
    --property=SubState \
    --property=NRestarts \
    --property=TasksCurrent \
    --property=TasksMax \
    --property=LimitNOFILE 2>/dev/null \
    | awk -F= '
      $1 ~ /^(ActiveState|SubState|NRestarts|TasksCurrent|TasksMax|LimitNOFILE)$/ &&
      $2 ~ /^[A-Za-z0-9._-]+$/ {
        printf "NGINX %s=%s\n", $1, $2
      }
    '; then
    emit "NGINX_PROPERTIES unavailable"
  fi
}

emit_nginx_error_count() {
  local count

  if ! command -v journalctl >/dev/null 2>&1; then
    emit "NGINX_RECENT_INGRESS_ERRORS unavailable"
    return
  fi

  if count="$(journalctl -u nginx --since "-${LOG_WINDOW_MINUTES} minutes" --no-pager -o cat 2>/dev/null | awk '
    BEGIN { count = 0 }
    /accept\(\) failed|worker_connections are not enough|too many open files|upstream timed out|connect\(\) failed/ {
      count++
    }
    END { print count }
  ')" && is_positive_integer "${count}"; then
    emit "NGINX_RECENT_INGRESS_ERRORS window_minutes=${LOG_WINDOW_MINUTES} count=${count}"
  else
    emit "NGINX_RECENT_INGRESS_ERRORS unavailable"
  fi
}

main() {
  if ! is_positive_integer "${LOG_WINDOW_MINUTES}" || (( LOG_WINDOW_MINUTES < 1 || LOG_WINDOW_MINUTES > 1440 )); then
    emit "ERROR DIAGNOSTICS_LOG_WINDOW_MINUTES must be an integer between 1 and 1440"
    exit 2
  fi

  emit "READ_ONLY_DIAGNOSTIC version=1"
  emit "TIMESTAMP_UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)"

  count_tls_sockets "listen_443" -Hln '( sport = :443 )'
  count_tls_sockets "syn_recv_443" -Htan state syn-recv '( sport = :443 )'
  count_tls_sockets "established_443" -Htan state established '( sport = :443 )'
  read_numeric_sysctl net.core.somaxconn
  read_numeric_sysctl net.ipv4.tcp_max_syn_backlog
  read_numeric_sysctl net.netfilter.nf_conntrack_count
  read_numeric_sysctl net.netfilter.nf_conntrack_max
  read_numeric_sysctl fs.file-max
  emit_file_usage
  emit_tcp_ext_counters
  emit_nginx_state
  emit_nginx_error_count
  emit "READ_ONLY_DIAGNOSTIC completed"
}

main "$@"
