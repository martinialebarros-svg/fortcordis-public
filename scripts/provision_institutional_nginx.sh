#!/usr/bin/env bash
set -euo pipefail

SITE_NAME="${SITE_NAME:-fortcordis-www}"
SITE_PATH="/etc/nginx/sites-available/${SITE_NAME}"
SITE_LINK="/etc/nginx/sites-enabled/${SITE_NAME}"

DOMAIN_PRIMARY="${DOMAIN_PRIMARY:-fortcordis.com}"
DOMAIN_WWW="${DOMAIN_WWW:-www.fortcordis.com}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
EXPECTED_PUBLIC_IP="${EXPECTED_PUBLIC_IP:-}"
ENABLE_TLS="${ENABLE_TLS:-0}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
SUDO_PASSWORD="${SUDO_PASSWORD:-${VPS_SUDO_PASSWORD:-}}"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

is_truthy() {
  case "${1,,}" in
    1|true|yes|y|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_with_sudo() {
  if command -v sudo >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
      sudo -n "$@"
      return $?
    fi

    if [[ -n "${SUDO_PASSWORD}" ]]; then
      if printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' -v >/dev/null 2>&1; then
        printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' "$@"
        return $?
      fi
    fi
  fi

  "$@"
}

resolve_ipv4s() {
  python3 - "$1" <<'PY'
import socket
import sys

host = sys.argv[1]
ips = sorted({item[4][0] for item in socket.getaddrinfo(host, None, socket.AF_INET)})
for ip in ips:
    print(ip)
PY
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERROR] Missing command: $1" >&2
    exit 1
  }
}

require_cmd nginx
require_cmd curl
require_cmd python3

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

cat >"${TMP_FILE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN_PRIMARY} ${DOMAIN_WWW};

    location / {
        proxy_pass http://127.0.0.1:${FRONTEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    location /api/ {
        client_max_body_size 30m;
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

log "Backing up existing site file when present"
if run_with_sudo test -f "${SITE_PATH}"; then
  BACKUP_PATH="${SITE_PATH}.bak.$(date +%F-%H%M%S)"
  run_with_sudo cp "${SITE_PATH}" "${BACKUP_PATH}"
  log "Backup created: ${BACKUP_PATH}"
fi

log "Installing nginx site ${SITE_NAME}"
run_with_sudo cp "${TMP_FILE}" "${SITE_PATH}"
run_with_sudo chmod 644 "${SITE_PATH}"

if ! run_with_sudo test -L "${SITE_LINK}"; then
  run_with_sudo ln -sf "${SITE_PATH}" "${SITE_LINK}"
fi

log "Validating nginx configuration"
run_with_sudo nginx -t
run_with_sudo systemctl reload nginx

log "Running local HTTP probes through nginx"
curl -fsSI -H "Host: ${DOMAIN_PRIMARY}" http://127.0.0.1/ >/dev/null
curl -fsSI -H "Host: ${DOMAIN_WWW}" http://127.0.0.1/ >/dev/null
curl -fsSI -H "Host: ${DOMAIN_WWW}" http://127.0.0.1/area-pacientes >/dev/null
curl -fsSI -H "Host: ${DOMAIN_WWW}" http://127.0.0.1/dashboard >/dev/null
log "HTTP probes OK"

if is_truthy "${ENABLE_TLS}"; then
  require_cmd certbot

  if [[ -z "${CERTBOT_EMAIL}" ]]; then
    echo "[ERROR] CERTBOT_EMAIL is required when ENABLE_TLS=1" >&2
    exit 1
  fi

  if [[ -n "${EXPECTED_PUBLIC_IP}" ]]; then
    for host in "${DOMAIN_PRIMARY}" "${DOMAIN_WWW}"; do
      resolved="$(resolve_ipv4s "${host}" | tr '\n' ' ')"
      if [[ " ${resolved} " != *" ${EXPECTED_PUBLIC_IP} "* ]]; then
        echo "[ERROR] ${host} nao resolve para ${EXPECTED_PUBLIC_IP}. Resolvido: ${resolved:-<nenhum>}" >&2
        exit 1
      fi
      log "DNS OK for ${host}: ${resolved}"
    done
  fi

  log "Issuing/updating TLS certificate with certbot"
  run_with_sudo certbot --nginx \
    --non-interactive \
    --agree-tos \
    --redirect \
    --email "${CERTBOT_EMAIL}" \
    -d "${DOMAIN_PRIMARY}" \
    -d "${DOMAIN_WWW}"

  log "Running local HTTPS probes through nginx"
  curl -kfsSI --resolve "${DOMAIN_PRIMARY}:443:127.0.0.1" "https://${DOMAIN_PRIMARY}/" >/dev/null
  curl -kfsSI --resolve "${DOMAIN_WWW}:443:127.0.0.1" "https://${DOMAIN_WWW}/" >/dev/null
  curl -kfsSI --resolve "${DOMAIN_WWW}:443:127.0.0.1" "https://${DOMAIN_WWW}/area-pacientes" >/dev/null
  log "HTTPS probes OK"
else
  log "TLS provisioning skipped (ENABLE_TLS=${ENABLE_TLS})"
fi

log "Institutional host provisioning finished successfully"
