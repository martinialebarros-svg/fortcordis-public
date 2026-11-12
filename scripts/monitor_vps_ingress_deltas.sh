#!/usr/bin/env bash
set -euo pipefail

# Monitor operacional estritamente somente-leitura. Ele executa o coletor
# agregado existente em uma janela limitada e publica apenas ocupacoes atuais,
# picos e deltas de contadores monotônicos. Nao lista conexoes, IPs ou logs.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTOR_SCRIPT="${INGRESS_MONITOR_COLLECTOR_SCRIPT:-${SCRIPT_DIR}/collect_vps_ingress_diagnostics.sh}"
SAMPLES="${INGRESS_MONITOR_SAMPLES:-30}"
INTERVAL_SECONDS="${INGRESS_MONITOR_INTERVAL_SECONDS:-10}"
COLLECT_TIMEOUT_SECONDS=8

COUNTER_NAMES=(
  ListenOverflows
  ListenDrops
  TCPBacklogDrop
  TCPReqQFullDrop
  TCPReqQFullDoCookies
  SyncookiesSent
  TCPSynRetrans
)
FIRST_COUNTER_VALUES=()
PREVIOUS_COUNTER_VALUES=()
CURRENT_COUNTER_VALUES=()
TOTAL_COUNTER_VALID=()

is_nonnegative_integer() {
  [[ "$1" =~ ^(0|[1-9][0-9]{0,17})$ ]]
}

validate_configuration() {
  if ! is_nonnegative_integer "${SAMPLES}" || ! is_nonnegative_integer "${INTERVAL_SECONDS}"; then
    printf 'INGRESS_MONITOR_ERROR timing values must be non-negative integers\n' >&2
    return 2
  fi

  if (( SAMPLES < 2 || SAMPLES > 60 || INTERVAL_SECONDS < 1 || INTERVAL_SECONDS > 60 )); then
    printf 'INGRESS_MONITOR_ERROR samples must be 2..60 and interval_seconds must be 1..60\n' >&2
    return 2
  fi

  if (( (SAMPLES - 1) * INTERVAL_SECONDS > 900 )); then
    printf 'INGRESS_MONITOR_ERROR monitoring window must not exceed 900 seconds\n' >&2
    return 2
  fi

  if [[ ! -r "${COLLECTOR_SCRIPT}" ]]; then
    printf 'INGRESS_MONITOR_ERROR collector is unavailable\n' >&2
    return 2
  fi

  if ! command -v timeout >/dev/null 2>&1; then
    printf 'INGRESS_MONITOR_ERROR timeout is required\n' >&2
    return 2
  fi
}

metric_value() {
  local snapshot="$1"
  local category="$2"
  local metric_name="$3"

  awk -v category="${category}" -v metric_name="${metric_name}" '
    $1 == category && index($2, metric_name "=") == 1 {
      value = $2
      sub("^[^=]+=", "", value)
      if (value ~ /^[0-9]+$/) {
        print value
      }
      exit
    }
  ' <<<"${snapshot}"
}

nginx_error_count() {
  local snapshot="$1"

  awk '
    $1 == "NGINX_RECENT_INGRESS_ERRORS" {
      for (field_no = 2; field_no <= NF; field_no++) {
        if ($field_no ~ /^count=[0-9]+$/) {
          value = $field_no
          sub(/^count=/, "", value)
          print value
          exit
        }
      }
    }
  ' <<<"${snapshot}"
}

normalized_or_unavailable() {
  local value="$1"

  if is_nonnegative_integer "${value}"; then
    printf '%s' "${value}"
  else
    printf 'unavailable'
  fi
}

delta_or_unavailable() {
  local previous="$1"
  local current="$2"

  if is_nonnegative_integer "${previous}" && is_nonnegative_integer "${current}" && (( current >= previous )); then
    printf '%s' "$((current - previous))"
  else
    printf 'unavailable'
  fi
}

max_or_unavailable() {
  local previous="$1"
  local current="$2"

  if ! is_nonnegative_integer "${current}"; then
    printf '%s' "${previous}"
  elif ! is_nonnegative_integer "${previous}" || (( current > previous )); then
    printf '%s' "${current}"
  else
    printf '%s' "${previous}"
  fi
}

collect_snapshot() {
  timeout --kill-after=2 "${COLLECT_TIMEOUT_SECONDS}" bash "${COLLECTOR_SCRIPT}" 2>/dev/null
}

print_sample() {
  local index="$1"
  local elapsed_seconds="$2"
  local syn_recv="$3"
  local established="$4"
  local conntrack="$5"
  local nginx_errors="$6"

  printf 'INGRESS_MONITOR_SAMPLE index=%s elapsed_seconds=%s syn_recv_443=%s established_443=%s conntrack_count=%s nginx_journal_matches_30m=%s timestamp_utc=%s\n' \
    "${index}" \
    "${elapsed_seconds}" \
    "$(normalized_or_unavailable "${syn_recv}")" \
    "$(normalized_or_unavailable "${established}")" \
    "$(normalized_or_unavailable "${conntrack}")" \
    "$(normalized_or_unavailable "${nginx_errors}")" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

print_counter_deltas() {
  local index="$1"
  local elapsed_seconds="$2"
  local counter_index counter_name

  printf 'INGRESS_COUNTER_DELTA index=%s elapsed_seconds=%s' "${index}" "${elapsed_seconds}"
  for counter_index in "${!COUNTER_NAMES[@]}"; do
    counter_name="${COUNTER_NAMES[${counter_index}]}"
    printf ' %s=%s' "${counter_name}" "$(delta_or_unavailable "${PREVIOUS_COUNTER_VALUES[${counter_index}]:-}" "${CURRENT_COUNTER_VALUES[${counter_index}]:-}")"
  done
  printf '\n'
}

print_total_counter_deltas() {
  local counter_index counter_name

  printf 'INGRESS_COUNTER_TOTAL_DELTA'
  for counter_index in "${!COUNTER_NAMES[@]}"; do
    counter_name="${COUNTER_NAMES[${counter_index}]}"
    if [[ "${TOTAL_COUNTER_VALID[${counter_index}]:-0}" == 1 ]]; then
      printf ' %s=%s' "${counter_name}" "$(delta_or_unavailable "${FIRST_COUNTER_VALUES[${counter_index}]:-}" "${PREVIOUS_COUNTER_VALUES[${counter_index}]:-}")"
    else
      printf ' %s=unavailable' "${counter_name}"
    fi
  done
  printf '\n'
}

main() {
  local index elapsed_seconds snapshot syn_recv established conntrack nginx_errors counter_index counter_name
  local max_syn_recv="" max_established="" max_conntrack=""
  local started_seconds scheduled_seconds delay_seconds collector_failures=0
  local interval_delta

  validate_configuration
  printf 'INGRESS_MONITOR version=1 samples=%s interval_seconds=%s\n' "${SAMPLES}" "${INTERVAL_SECONDS}"
  started_seconds=${SECONDS}

  for ((index = 1; index <= SAMPLES; index++)); do
    scheduled_seconds=$((started_seconds + (index - 1) * INTERVAL_SECONDS))
    delay_seconds=$((scheduled_seconds - SECONDS))
    if (( delay_seconds > 0 )); then
      sleep "${delay_seconds}"
    fi

    if ! snapshot="$(collect_snapshot)"; then
      snapshot=""
      collector_failures=$((collector_failures + 1))
      printf 'INGRESS_MONITOR_COLLECTION index=%s status=unavailable\n' "${index}"
    fi
    elapsed_seconds=$((SECONDS - started_seconds))
    syn_recv="$(metric_value "${snapshot}" SOCKETS syn_recv_443)"
    established="$(metric_value "${snapshot}" SOCKETS established_443)"
    conntrack="$(metric_value "${snapshot}" SYSCTL net.netfilter.nf_conntrack_count)"
    nginx_errors="$(nginx_error_count "${snapshot}")"

    for counter_index in "${!COUNTER_NAMES[@]}"; do
      counter_name="${COUNTER_NAMES[${counter_index}]}"
      CURRENT_COUNTER_VALUES[${counter_index}]="$(metric_value "${snapshot}" TCP_EXT "${counter_name}")"
      if (( index == 1 )); then
        TOTAL_COUNTER_VALID[${counter_index}]=1
        if ! is_nonnegative_integer "${CURRENT_COUNTER_VALUES[${counter_index}]}"; then
          TOTAL_COUNTER_VALID[${counter_index}]=0
        fi
      else
        interval_delta="$(delta_or_unavailable "${PREVIOUS_COUNTER_VALUES[${counter_index}]:-}" "${CURRENT_COUNTER_VALUES[${counter_index}]}")"
        if [[ "${interval_delta}" == unavailable ]]; then
          TOTAL_COUNTER_VALID[${counter_index}]=0
        fi
      fi
    done

    print_sample "${index}" "${elapsed_seconds}" "${syn_recv}" "${established}" "${conntrack}" "${nginx_errors}"
    max_syn_recv="$(max_or_unavailable "${max_syn_recv}" "${syn_recv}")"
    max_established="$(max_or_unavailable "${max_established}" "${established}")"
    max_conntrack="$(max_or_unavailable "${max_conntrack}" "${conntrack}")"

    if (( index == 1 )); then
      for counter_index in "${!COUNTER_NAMES[@]}"; do
        FIRST_COUNTER_VALUES[${counter_index}]="${CURRENT_COUNTER_VALUES[${counter_index}]}"
      done
    else
      print_counter_deltas "${index}" "${elapsed_seconds}"
    fi

    for counter_index in "${!COUNTER_NAMES[@]}"; do
      PREVIOUS_COUNTER_VALUES[${counter_index}]="${CURRENT_COUNTER_VALUES[${counter_index}]}"
    done
  done

  printf 'INGRESS_MONITOR_SUMMARY samples=%s interval_seconds=%s max_syn_recv_443=%s max_established_443=%s max_conntrack_count=%s collector_failures=%s elapsed_seconds=%s\n' \
    "${SAMPLES}" \
    "${INTERVAL_SECONDS}" \
    "$(normalized_or_unavailable "${max_syn_recv}")" \
    "$(normalized_or_unavailable "${max_established}")" \
    "$(normalized_or_unavailable "${max_conntrack}")" \
    "${collector_failures}" "$((SECONDS - started_seconds))"
  print_total_counter_deltas
  printf 'INGRESS_MONITOR completed\n'
  (( collector_failures == 0 ))
}

main "$@"
