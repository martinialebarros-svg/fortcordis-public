#!/usr/bin/env bash
set -euo pipefail

# Probe externo curto e sem credenciais. O corpo da resposta e descartado; a
# saida contem somente metadados de transporte necessarios para correlacao.

PROBE_URL="${PROBE_URL:-}"
PROBE_LABEL="${PROBE_LABEL:-public_https}"
PROBE_ATTEMPTS="${PROBE_ATTEMPTS:-20}"
PROBE_INTERVAL_SECONDS="${PROBE_INTERVAL_SECONDS:-1}"
PROBE_CONNECT_TIMEOUT_SECONDS="${PROBE_CONNECT_TIMEOUT_SECONDS:-4}"
PROBE_MAX_TIME_SECONDS="${PROBE_MAX_TIME_SECONDS:-6}"

is_positive_integer() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

validate_configuration() {
  if [[ ! "${PROBE_URL}" =~ ^https:// ]]; then
    echo "PROBE_URL must use HTTPS" >&2
    return 2
  fi

  if [[ ! "${PROBE_LABEL}" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "PROBE_LABEL contains unsupported characters" >&2
    return 2
  fi

  for value in "${PROBE_ATTEMPTS}" "${PROBE_INTERVAL_SECONDS}" "${PROBE_CONNECT_TIMEOUT_SECONDS}" "${PROBE_MAX_TIME_SECONDS}"; do
    if ! is_positive_integer "${value}"; then
      echo "Probe timing values must be non-negative integers" >&2
      return 2
    fi
  done

  if (( PROBE_ATTEMPTS < 1 || PROBE_ATTEMPTS > 60 || PROBE_MAX_TIME_SECONDS < 1 || PROBE_CONNECT_TIMEOUT_SECONDS < 1 )); then
    echo "Probe values are outside their allowed range" >&2
    return 2
  fi
}

main() {
  local attempt curl_exit metrics success_count=0 failure_count=0 http_code

  validate_configuration
  printf 'PUBLIC_HTTPS_PROBE label=%s attempts=%s\n' "${PROBE_LABEL}" "${PROBE_ATTEMPTS}"

  for ((attempt = 1; attempt <= PROBE_ATTEMPTS; attempt++)); do
    set +e
    metrics="$(curl --disable --silent --show-error --location --proto '=https' --proto-redir '=https' --output /dev/null \
      --connect-timeout "${PROBE_CONNECT_TIMEOUT_SECONDS}" \
      --max-time "${PROBE_MAX_TIME_SECONDS}" \
      --write-out 'http=%{http_code} remote_ip=%{remote_ip} http_version=%{http_version} time_connect_s=%{time_connect} time_tls_s=%{time_appconnect} time_total_s=%{time_total}' \
      "${PROBE_URL}" 2>/dev/null)"
    curl_exit=$?
    set -e

    http_code="${metrics#*http=}"
    http_code="${http_code%% *}"
    if (( curl_exit == 0 )) && [[ "${http_code}" =~ ^[23][0-9][0-9]$ ]]; then
      ((success_count += 1))
    else
      ((failure_count += 1))
    fi

    printf 'PUBLIC_HTTPS_PROBE label=%s attempt=%s curl_exit=%s %s timestamp_utc=%s\n' \
      "${PROBE_LABEL}" "${attempt}" "${curl_exit}" "${metrics:-transport_metrics_unavailable}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if (( attempt < PROBE_ATTEMPTS && PROBE_INTERVAL_SECONDS > 0 )); then
      sleep "${PROBE_INTERVAL_SECONDS}"
    fi
  done

  printf 'PUBLIC_HTTPS_PROBE_SUMMARY label=%s success=%s failure=%s\n' \
    "${PROBE_LABEL}" "${success_count}" "${failure_count}"
}

main "$@"
