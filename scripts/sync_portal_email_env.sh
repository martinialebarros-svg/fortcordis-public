#!/usr/bin/env bash
set -euo pipefail

PROD_ENV_FILE="${PROD_ENV_FILE:-/var/www/fortcordis-v2/backend/.env}"
STAGE_ENV_FILE="${STAGE_ENV_FILE:-/var/www/fortcordis-stage/backend/.env}"
BACKEND_SERVICE="${BACKEND_SERVICE:-fortcordis-backend}"
SUDO_PASSWORD="${SUDO_PASSWORD:-${VPS_SUDO_PASSWORD:-}}"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
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

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERROR] Missing command: $1" >&2
    exit 1
  }
}

require_cmd python3

STAGE_TMP="$(mktemp)"
PROD_TMP="$(mktemp)"
MERGED_TMP="$(mktemp)"
trap 'rm -f "${STAGE_TMP}" "${PROD_TMP}" "${MERGED_TMP}"' EXIT

log "Reading portal email config from stage env"
run_with_sudo grep -E '^PORTAL_EMAIL_' "${STAGE_ENV_FILE}" >"${STAGE_TMP}"

python3 - "${STAGE_TMP}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
required_keys = [
    "PORTAL_EMAIL_SMTP_HOST",
    "PORTAL_EMAIL_SMTP_PORT",
    "PORTAL_EMAIL_SMTP_USE_TLS",
    "PORTAL_EMAIL_SMTP_USE_SSL",
    "PORTAL_EMAIL_FROM_EMAIL",
    "PORTAL_EMAIL_FROM_NAME",
    "PORTAL_EMAIL_SUBJECT",
]

values = {}
for raw_line in env_path.read_text().splitlines():
    if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
        continue
    key, value = raw_line.split("=", 1)
    values[key] = value

missing = [key for key in required_keys if not values.get(key)]
if missing:
    raise SystemExit(f"[ERROR] Stage env is missing required portal email keys: {', '.join(missing)}")
PY

log "Backing up prod env"
run_with_sudo cp "${PROD_ENV_FILE}" "${PROD_ENV_FILE}.bak.$(date +%F-%H%M%S)"

log "Loading current prod env"
run_with_sudo cat "${PROD_ENV_FILE}" >"${PROD_TMP}"

log "Merging portal email config into prod env"
python3 - "${PROD_TMP}" "${STAGE_TMP}" "${MERGED_TMP}" <<'PY'
from pathlib import Path
import sys

prod_path = Path(sys.argv[1])
stage_path = Path(sys.argv[2])
merged_path = Path(sys.argv[3])

stage_lines = [line for line in stage_path.read_text().splitlines() if line.strip()]
prod_lines = prod_path.read_text().splitlines()

filtered = [line for line in prod_lines if not line.startswith("PORTAL_EMAIL_=") and not line.startswith("PORTAL_EMAIL_")]
if filtered and filtered[-1].strip():
    filtered.append("")
filtered.extend(stage_lines)
merged_path.write_text("\n".join(filtered) + "\n")
PY

run_with_sudo cp "${MERGED_TMP}" "${PROD_ENV_FILE}"

log "Restarting prod backend"
run_with_sudo systemctl restart "${BACKEND_SERVICE}"

log "Validating SMTP handshake with prod env"
run_with_sudo python3 - "${PROD_ENV_FILE}" <<'PY'
from pathlib import Path
import smtplib
import sys

env = {}
for raw_line in Path(sys.argv[1]).read_text().splitlines():
    if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
        continue
    key, value = raw_line.split("=", 1)
    env[key] = value

host = env["PORTAL_EMAIL_SMTP_HOST"].strip()
port = int(env["PORTAL_EMAIL_SMTP_PORT"].strip() or "587")
username = env["PORTAL_EMAIL_SMTP_USERNAME"].strip()
password = env["PORTAL_EMAIL_SMTP_PASSWORD"]
use_tls = env.get("PORTAL_EMAIL_SMTP_USE_TLS", "true").strip().lower() == "true"
use_ssl = env.get("PORTAL_EMAIL_SMTP_USE_SSL", "false").strip().lower() == "true"

if use_ssl:
    with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
        if username:
            smtp.login(username, password)
else:
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if username:
            smtp.login(username, password)

print("[OK] SMTP handshake validated")
PY

log "Portal email config synced successfully"
