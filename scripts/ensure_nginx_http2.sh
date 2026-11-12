#!/usr/bin/env bash
set -euo pipefail

# Enables HTTP/2 as one grouped change for every declared HTTPS app vhost.
# It is fail-closed: every target must resolve to exactly one enabled vhost,
# all backups are made before any write, and every changed file is restored
# if Nginx validation, reload, or HTTP/2 verification fails.

ENABLE_NGINX_HTTP2="${ENABLE_NGINX_HTTP2:-0}"
NGINX_HTTP2_EXPECTED_HOSTS="${NGINX_HTTP2_EXPECTED_HOSTS:-}"
NGINX_HTTP2_SITE_ROOT="${NGINX_HTTP2_SITE_ROOT:-/etc/nginx/sites-available}"
NGINX_HTTP2_ENABLED_ROOT="${NGINX_HTTP2_ENABLED_ROOT:-/etc/nginx/sites-enabled}"
SUDO_PASSWORD="${SUDO_PASSWORD:-${VPS_SUDO_PASSWORD:-}}"

log() {
  printf '[nginx-http2] %s\n' "$*"
}

run_with_sudo() {
  if ! command -v sudo >/dev/null 2>&1; then
    "$@"
    return $?
  fi

  if sudo -n true >/dev/null 2>&1; then
    sudo -n "$@"
    return $?
  fi

  if [[ -n "${SUDO_PASSWORD}" ]] && printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' -v >/dev/null 2>&1; then
    printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' "$@"
    return $?
  fi

  "$@"
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

vhost_declares_host() {
  local expected_host="$1"
  local site_file="$2"

  run_with_sudo awk -v expected_host="${expected_host}" '
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/[[:space:]]*#.*/, "", line)

      if (collecting) {
        directive = directive " " line
      } else if (line ~ /^[[:space:]]*server_name[[:space:]]+/) {
        directive = line
        collecting = 1
      } else {
        next
      }

      if (directive !~ /;/) {
        next
      }

      sub(/^[[:space:]]*server_name[[:space:]]+/, "", directive)
      sub(/;.*/, "", directive)
      count = split(directive, names, /[[:space:]]+/)
      for (name_index = 1; name_index <= count; name_index++) {
        if (names[name_index] == expected_host) {
          found = 1
          exit
        }
      }
      directive = ""
      collecting = 0
    }
    END { exit(found ? 0 : 1) }
  ' "${site_file}"
}

if [[ "${ENABLE_NGINX_HTTP2}" != "1" ]]; then
  log "HTTP/2 enablement disabled; skipping."
  exit 0
fi

if [[ -z "${NGINX_HTTP2_EXPECTED_HOSTS}" ]]; then
  echo "[nginx-http2] NGINX_HTTP2_EXPECTED_HOSTS is required when HTTP/2 is enabled." >&2
  exit 1
fi

if ! run_with_sudo test -d "${NGINX_HTTP2_SITE_ROOT}" || ! run_with_sudo test -d "${NGINX_HTTP2_ENABLED_ROOT}"; then
  echo "[nginx-http2] Nginx site directories are unavailable." >&2
  exit 1
fi

nginx_bin="$(command -v nginx 2>/dev/null || true)"
if [[ -z "${nginx_bin}" ]]; then
  echo "[nginx-http2] Nginx binary is unavailable." >&2
  exit 1
fi

nginx_build_details="$(run_with_sudo "${nginx_bin}" -V 2>&1 || true)"
if ! printf '%s\n' "${nginx_build_details}" | grep -Fq -- '--with-http_v2_module'; then
  echo "[nginx-http2] Nginx was not built with the HTTP/2 module; refusing to modify vhosts." >&2
  exit 1
fi
log "Nginx HTTP/2 module is available."

declare -a raw_hosts=()
IFS=',' read -r -a raw_hosts <<< "${NGINX_HTTP2_EXPECTED_HOSTS}"
declare -a expected_hosts=()
for raw_host in "${raw_hosts[@]:-}"; do
  host="$(trim "${raw_host}")"
  if [[ -z "${host}" ]]; then
    echo "[nginx-http2] Empty host in NGINX_HTTP2_EXPECTED_HOSTS." >&2
    exit 1
  fi
  for known_host in "${expected_hosts[@]:-}"; do
    if [[ "${known_host}" == "${host}" ]]; then
      echo "[nginx-http2] Duplicate expected host: ${host}." >&2
      exit 1
    fi
  done
  expected_hosts+=("${host}")
done

if [[ "${#expected_hosts[@]}" -lt 2 ]]; then
  echo "[nginx-http2] At least two distinct hosts are required for the shared TLS listener." >&2
  exit 1
fi

declare -a enabled_entries=()
while IFS= read -r -d '' enabled_entry; do
  enabled_entries+=("${enabled_entry}")
done < <(run_with_sudo find "${NGINX_HTTP2_ENABLED_ROOT}" \( -type f -o -type l \) -print0)

declare -a site_files=()
for host in "${expected_hosts[@]}"; do
  declare -a candidates=()
  for enabled_entry in "${enabled_entries[@]:-}"; do
    candidate="$(run_with_sudo readlink -f -- "${enabled_entry}" || true)"
    if [[ "${candidate}" == "${NGINX_HTTP2_SITE_ROOT}/"* ]] && \
      run_with_sudo test -f "${candidate}" && \
      vhost_declares_host "${host}" "${candidate}"; then
      candidates+=("${candidate}")
    fi
  done

  if [[ "${#candidates[@]}" -ne 1 ]]; then
    echo "[nginx-http2] Expected exactly one enabled vhost for ${host}; found ${#candidates[@]}." >&2
    exit 1
  fi

  site_file="${candidates[0]}"
  log "Resolved ${host} to ${site_file}."
  if ! run_with_sudo grep -Eq '^[[:space:]]*listen[[:space:]]+(\[::\]:)?443[[:space:]].*ssl.*;' "${site_file}"; then
    echo "[nginx-http2] HTTPS listen directive was not found in ${site_file}." >&2
    exit 1
  fi

  already_listed=0
  for known_site in "${site_files[@]:-}"; do
    if [[ "${known_site}" == "${site_file}" ]]; then
      already_listed=1
      break
    fi
  done
  if [[ "${already_listed}" == "0" ]]; then
    site_files+=("${site_file}")
  fi
done

temp_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "${temp_dir}"
}
trap cleanup EXIT

declare -a updated_files=()
declare -a changed_files=()
declare -a backup_files=()
changed_count=0

for index in "${!site_files[@]}"; do
  original_file="${temp_dir}/vhost-${index}.original"
  updated_file="${temp_dir}/vhost-${index}.updated"
  run_with_sudo cat -- "${site_files[index]}" > "${original_file}"
  awk '
    /^[[:space:]]*listen[[:space:]]+(\[::\]:)?443[[:space:]].*ssl.*;([[:space:]]*#.*)?[[:space:]]*$/ {
      listener = $0
      comment = ""
      if (match(listener, /[[:space:]]*#.*/)) {
        comment = substr(listener, RSTART)
        listener = substr(listener, 1, RSTART - 1)
      }
      if (listener !~ /(^|[[:space:]])http2([[:space:];]|$)/) {
        sub(/;[[:space:]]*$/, " http2;", listener)
        $0 = listener comment
      }
    }
    { print }
  ' "${original_file}" > "${updated_file}"

  updated_files[index]="${updated_file}"
  changed_files[index]=0
  backup_files[index]=""
  if ! cmp -s "${original_file}" "${updated_file}"; then
    changed_files[index]=1
    changed_count=$((changed_count + 1))
  fi
done

restore_changed_vhosts() {
  log "Restoring every changed Nginx vhost backup after failed HTTP/2 validation."
  for restore_index in "${!site_files[@]}"; do
    if [[ "${changed_files[restore_index]}" == "1" ]] && [[ -n "${backup_files[restore_index]}" ]]; then
      run_with_sudo cp -- "${backup_files[restore_index]}" "${site_files[restore_index]}" || true
    fi
  done
  run_with_sudo "${nginx_bin}" -t || true
  run_with_sudo systemctl reload nginx || true
}

http2_protocol_with_retry() {
  local host="$1"
  local verification_scope="$2"
  local protocol=""
  local attempt

  for attempt in 1 2 3 4 5; do
    if [[ "${verification_scope}" == "local" ]]; then
      protocol="$(curl --noproxy '*' --silent --show-error --fail --http2 \
        --connect-timeout 8 --max-time 20 --output /dev/null --write-out '%{http_version}' \
        --resolve "${host}:443:127.0.0.1" \
        "https://${host}/" || true)"
    else
      protocol="$(curl --noproxy '*' --silent --show-error --fail --http2 \
        --connect-timeout 8 --max-time 20 --output /dev/null --write-out '%{http_version}' \
        "https://${host}/" || true)"
    fi

    if [[ "${protocol}" == "2" || "${protocol}" == "2.0" ]]; then
      printf '%s' "${protocol}"
      return 0
    fi

    if [[ "${attempt}" -lt 5 ]]; then
      sleep 1
    fi
  done

  printf '%s' "${protocol}"
  return 1
}

if [[ "${changed_count}" -gt 0 ]]; then
  backup_suffix="$(date +%Y%m%d%H%M%S)"
  for index in "${!site_files[@]}"; do
    if [[ "${changed_files[index]}" == "1" ]]; then
      backup_files[index]="${site_files[index]}.bak.http2.${backup_suffix}"
      if ! run_with_sudo cp -- "${site_files[index]}" "${backup_files[index]}"; then
        echo "[nginx-http2] Could not create the backup for ${site_files[index]}." >&2
        exit 1
      fi
    fi
  done

  for index in "${!site_files[@]}"; do
    if [[ "${changed_files[index]}" == "1" ]]; then
      if ! run_with_sudo cp -- "${updated_files[index]}" "${site_files[index]}"; then
        echo "[nginx-http2] Could not write ${site_files[index]}; restoring grouped backups." >&2
        restore_changed_vhosts
        exit 1
      fi
    fi
  done
  log "HTTP/2 directive added atomically to ${changed_count} vhost file(s); validating Nginx."

  if ! run_with_sudo "${nginx_bin}" -t; then
    restore_changed_vhosts
    exit 1
  fi

  if ! run_with_sudo systemctl reload nginx; then
    restore_changed_vhosts
    exit 1
  fi
else
  log "HTTP/2 directive already present in every declared vhost."
fi

for host in "${expected_hosts[@]}"; do
  if ! protocol="$(http2_protocol_with_retry "${host}" "local")"; then
    echo "[nginx-http2] Local HTTP/2 verification failed for ${host}; negotiated '${protocol:-none}'." >&2
    if [[ "${changed_count}" -gt 0 ]]; then
      restore_changed_vhosts
    fi
    exit 1
  fi
  log "Local HTTP/2 verified for ${host}."

  if ! protocol="$(http2_protocol_with_retry "${host}" "external")"; then
    echo "[nginx-http2] External HTTP/2 verification failed for ${host}; negotiated '${protocol:-none}'." >&2
    if [[ "${changed_count}" -gt 0 ]]; then
      restore_changed_vhosts
    fi
    exit 1
  fi
  log "External HTTP/2 verified for ${host}."
done
