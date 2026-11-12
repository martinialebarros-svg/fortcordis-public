#!/usr/bin/env bash
set -euo pipefail

# Production deploy script with guardrails:
# - hard reset to the resolved deploy SHA (avoids stash/pop conflicts)
# - backend deps + migrations + health check
# - frontend clean build (.next) + service checks
#
# Usage (on VPS):
#   bash scripts/deploy_prod_vps.sh
#
# Required deploy identity (including manual invocations):
#   DEPLOY_SHA=<full 40-character approved workflow SHA>
#   DEPLOY_REF=refs/heads/main
# Optional env overrides:
#   APP_DIR=/var/www/fortcordis-v2
#   BRANCH=main
#   Missing identity always fails; the branch tip is never a fallback.
#   BACKEND_SERVICE=fortcordis-backend
#   BACKGROUND_WORKER_SERVICE=fortcordis-backend-worker
#   FRONTEND_SERVICE=fortcordis-frontend
#   BACKEND_PORT=8000
#   FRONTEND_PORT=3000
#   PUBLIC_URL=https://app.fortcordis.com.br
#   ENABLE_WHATSAPP_STAGE_BACKEND=1
#   WHATSAPP_STAGE_BACKEND_SERVICE=fortcordis-stage-whatsapp-backend
#   WHATSAPP_STAGE_BACKEND_PORT=3010
#   WHATSAPP_STAGE_BACKEND_URL=http://127.0.0.1:3010
#   WHATSAPP_META_SOURCE_ENV_FILE=/caminho/seguro/.env
#   WHATSAPP_EXPECTED_PHONE_NUMBER_ID=<id-publico-do-ambiente>
#   WHATSAPP_EXPECTED_META_APP_ID=<id-publico-do-ambiente>
#   WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID=<id-publico-do-ambiente>
#   WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION=0|1
#   WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED=true|false
#   WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED=true|false (somente apos aprovacao na WABA)
#   DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE=0|1 (opt-in, apos os gates finais)
#   WHATSAPP_RUNTIME_LABEL=Stage
#   ENABLE_WHATSAPP_STAGE_SMOKE=1
#   WHATSAPP_DEFAULT_ALLOWED_PAPEIS=admin,recepcao,veterinario,cardiologista
#   WHATSAPP_DEFAULT_WRITE_ALLOWED_PAPEIS=admin,recepcao,veterinario,cardiologista
#   AUTO_ROLLBACK_ON_FAILURE=1
#   ENABLE_AUTH_CANARY=1
#   AUTH_CANARY_TIMEOUT_SECONDS=8
#   AUTH_CANARY_DISABLE_INTERNAL_TOKEN=0
#   AUTH_CANARY_AGENDA_LATENCY_SAMPLES=5
#   AUTH_CANARY_AGENDA_MAX_P95_MS=1200
#   CANARY_BEARER_TOKEN=<token-opcional>
#   CANARY_USERNAME=<usuario-opcional>
#   CANARY_PASSWORD=<senha-opcional>
#   ENABLE_BACKUP_RESTORE_DRILL=1
#   BACKUP_RESTORE_DRILL_SKIP_SQLITE_CHECK=0
#   BACKUP_RESTORE_DRILL_KEEP_RESTORE_DIR=0
#   ENABLE_ECO_STUDY_OCR=1
#   REQUIRE_ECO_STUDY_OCR=0
#   RUNTIME_BACKUP_RETENTION_DAYS=30
#   RUNTIME_BACKUP_MAX_ITEMS=200
#   ENABLE_NGINX_HTTP2=0|1
#   NGINX_HTTP2_EXPECTED_HOSTS=app.stage.fortcordis.com.br,app.fortcordis.com.br
#   NGINX_HTTP2_SITE_ROOT=/etc/nginx/sites-available
#   NGINX_HTTP2_ENABLED_ROOT=/etc/nginx/sites-enabled

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/var/www/fortcordis-v2}"
BRANCH="${BRANCH:-main}"
DEPLOY_SHA="${DEPLOY_SHA:-}"
DEPLOY_REF="${DEPLOY_REF:-}"
DEPLOY_TARGET_SHA=""
SUDO_PASSWORD="${SUDO_PASSWORD:-${VPS_SUDO_PASSWORD:-}}"

BACKEND_DIR="${APP_DIR}/backend"
FRONTEND_DIR="${APP_DIR}/frontend"

BACKEND_SERVICE="${BACKEND_SERVICE:-fortcordis-backend}"
BACKGROUND_WORKER_SERVICE="${BACKGROUND_WORKER_SERVICE:-${BACKEND_SERVICE}-worker}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-fortcordis-frontend}"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
API_BACKEND_URL="${API_BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"
PUBLIC_URL="${PUBLIC_URL:-https://app.fortcordis.com.br}"
ENABLE_WHATSAPP_STAGE_BACKEND="${ENABLE_WHATSAPP_STAGE_BACKEND:-0}"
# Only the stage wrapper supplies this mode. Empty preserves production behavior.
WHATSAPP_STAGE_LIVE_META_ENABLED="${WHATSAPP_STAGE_LIVE_META_ENABLED:-}"
WHATSAPP_STAGE_BACKEND_SERVICE="${WHATSAPP_STAGE_BACKEND_SERVICE:-fortcordis-stage-whatsapp-backend}"
WHATSAPP_STAGE_BACKEND_PORT="${WHATSAPP_STAGE_BACKEND_PORT:-3010}"
WHATSAPP_STAGE_BACKEND_URL="${WHATSAPP_STAGE_BACKEND_URL:-http://127.0.0.1:${WHATSAPP_STAGE_BACKEND_PORT}}"
WHATSAPP_STAGE_BACKEND_DIR="${WHATSAPP_STAGE_BACKEND_DIR:-${APP_DIR}/whatsapp-stage-backend}"
WHATSAPP_STAGE_BACKEND_ENV_FILE="${WHATSAPP_STAGE_BACKEND_ENV_FILE:-${WHATSAPP_STAGE_BACKEND_DIR}/.env}"
WHATSAPP_META_SOURCE_ENV_FILE="${WHATSAPP_META_SOURCE_ENV_FILE:-}"
WHATSAPP_EXPECTED_PHONE_NUMBER_ID="${WHATSAPP_EXPECTED_PHONE_NUMBER_ID:-}"
WHATSAPP_EXPECTED_META_APP_ID="${WHATSAPP_EXPECTED_META_APP_ID:-}"
WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID="${WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID:-}"
WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION="${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION:-0}"
DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE="${DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE:-0}"
WHATSAPP_PRODUCTION_PHONE_NUMBER_ID="1279142515283484"
WHATSAPP_PRODUCTION_META_APP_ID="975334532125008"
WHATSAPP_PRODUCTION_BUSINESS_ACCOUNT_ID="1369494994627980"
WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED="${WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED:-}"
WHATSAPP_RUNTIME_LABEL="${WHATSAPP_RUNTIME_LABEL:-Stage}"
ENABLE_WHATSAPP_STAGE_SMOKE="${ENABLE_WHATSAPP_STAGE_SMOKE:-1}"
WHATSAPP_DEFAULT_ALLOWED_PAPEIS="${WHATSAPP_DEFAULT_ALLOWED_PAPEIS:-admin,recepcao,veterinario,cardiologista}"
WHATSAPP_DEFAULT_WRITE_ALLOWED_PAPEIS="${WHATSAPP_DEFAULT_WRITE_ALLOWED_PAPEIS:-${WHATSAPP_DEFAULT_ALLOWED_PAPEIS}}"

RUNTIME_BACKUP_DIR="${RUNTIME_BACKUP_DIR:-$HOME/fortcordis-runtime-backups}"
# Stage e prod rodam na mesma VPS, com o mesmo $HOME, e escrevem nesse mesmo
# diretorio - sem rotacao, ele cresce sem limite a cada deploy (chegou a 2004
# itens / 13G em ~5 meses e derrubou o disco). Os dois limites abaixo sao
# aplicados juntos: por idade e por quantidade, para segurar o crescimento
# mesmo se a frequencia de deploy aumentar.
RUNTIME_BACKUP_RETENTION_DAYS="${RUNTIME_BACKUP_RETENTION_DAYS:-30}"
RUNTIME_BACKUP_MAX_ITEMS="${RUNTIME_BACKUP_MAX_ITEMS:-200}"
AUTO_ROLLBACK_ON_FAILURE="${AUTO_ROLLBACK_ON_FAILURE:-1}"
ENABLE_AUTH_CANARY="${ENABLE_AUTH_CANARY:-1}"
AUTH_CANARY_TIMEOUT_SECONDS="${AUTH_CANARY_TIMEOUT_SECONDS:-8}"
AUTH_CANARY_DISABLE_INTERNAL_TOKEN="${AUTH_CANARY_DISABLE_INTERNAL_TOKEN:-0}"
AUTH_CANARY_AGENDA_LATENCY_SAMPLES="${AUTH_CANARY_AGENDA_LATENCY_SAMPLES:-5}"
AUTH_CANARY_AGENDA_MAX_P95_MS="${AUTH_CANARY_AGENDA_MAX_P95_MS:-1200}"
ENABLE_BACKUP_RESTORE_DRILL="${ENABLE_BACKUP_RESTORE_DRILL:-1}"
BACKUP_RESTORE_DRILL_SKIP_SQLITE_CHECK="${BACKUP_RESTORE_DRILL_SKIP_SQLITE_CHECK:-0}"
BACKUP_RESTORE_DRILL_KEEP_RESTORE_DIR="${BACKUP_RESTORE_DRILL_KEEP_RESTORE_DIR:-0}"
ENABLE_ECO_STUDY_OCR="${ENABLE_ECO_STUDY_OCR:-1}"
REQUIRE_ECO_STUDY_OCR="${REQUIRE_ECO_STUDY_OCR:-0}"
ENABLE_NGINX_HTTP2="${ENABLE_NGINX_HTTP2:-0}"
RELOAD_NGINX_ON_DEPLOY="${RELOAD_NGINX_ON_DEPLOY:-1}"
NGINX_HTTP2_EXPECTED_HOSTS="${NGINX_HTTP2_EXPECTED_HOSTS:-}"
NGINX_HTTP2_SITE_ROOT="${NGINX_HTTP2_SITE_ROOT:-/etc/nginx/sites-available}"
NGINX_HTTP2_ENABLED_ROOT="${NGINX_HTTP2_ENABLED_ROOT:-/etc/nginx/sites-enabled}"
PRE_DEPLOY_HASH=""
NEW_HASH=""
CODE_UPDATED=0
DEPLOY_STAGE="bootstrap"
ROLLBACK_IN_PROGRESS=0
REMINDER_SERVICE_FLAG_CHANGED=0
REMINDER_SERVICE_PREVIOUS_FLAG_LINES=""
NPM_BIN="/usr/bin/npm"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

validate_deploy_target() {
  if [[ ! "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "[ERROR] DEPLOY_SHA must be a full 40-character lowercase commit SHA." >&2
    return 1
  fi
  if [[ "$DEPLOY_REF" != "refs/heads/${BRANCH}" ]]; then
    echo "[ERROR] DEPLOY_REF does not match the deployment branch." >&2
    return 1
  fi
  if ! git check-ref-format --branch "$BRANCH" >/dev/null; then
    echo "[ERROR] Invalid deploy branch." >&2
    return 1
  fi
}

resolve_deploy_target() {
  validate_deploy_target || return 1
  git fetch --no-tags origin \
    "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" || return 1
  git fetch --no-tags origin "$DEPLOY_SHA" || return 1
  DEPLOY_TARGET_SHA="$(git rev-parse --verify "${DEPLOY_SHA}^{commit}")" || return 1
  if [[ "$DEPLOY_TARGET_SHA" != "$DEPLOY_SHA" ]]; then
    echo "[ERROR] Fetched commit does not match DEPLOY_SHA." >&2
    return 1
  fi
  if ! git merge-base --is-ancestor "$DEPLOY_TARGET_SHA" "refs/remotes/origin/${BRANCH}"; then
    echo "[ERROR] DEPLOY_SHA is not reachable from the expected remote branch." >&2
    return 1
  fi
  log "Resolved deploy SHA: ${DEPLOY_TARGET_SHA} (branch=${BRANCH})"
}

update_deploy_code() {
  if [[ ! "$DEPLOY_TARGET_SHA" =~ ^[0-9a-f]{40}$ || "$DEPLOY_TARGET_SHA" != "$DEPLOY_SHA" ]]; then
    echo "[ERROR] Resolve the approved deploy SHA before updating code." >&2
    return 1
  fi
  git checkout "$BRANCH" || return 1
  git reset --hard "$DEPLOY_TARGET_SHA" || return 1
  CODE_UPDATED=1
  local installed_sha
  installed_sha="$(git rev-parse HEAD)" || return 1
  if [[ "$installed_sha" != "$DEPLOY_TARGET_SHA" ]]; then
    echo "[ERROR] Installed HEAD differs from the resolved deploy SHA." >&2
    return 1
  fi
  log "Installed deploy SHA: ${installed_sha}"
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

  if [[ -n "${SUDO_PASSWORD}" ]]; then
    if printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' -v >/dev/null 2>&1; then
      printf '%s\n' "${SUDO_PASSWORD}" | sudo -S -p '' "$@"
      return $?
    fi
  fi

  return 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[ERROR] Missing command: $1" >&2
    exit 1
  }
}

has_tesseract_language() {
  local language="$1"
  tesseract --list-langs 2>/dev/null | grep -Fxq "$language"
}

ensure_eco_study_ocr_dependencies() {
  if [[ "${ENABLE_ECO_STUDY_OCR}" != "1" ]]; then
    log "Eco study OCR disabled for this deploy."
    return 0
  fi

  if command -v tesseract >/dev/null 2>&1 \
    && has_tesseract_language por \
    && has_tesseract_language eng; then
    log "Eco study OCR ready: $(tesseract --version 2>/dev/null | head -n 1)"
    return 0
  fi

  log "Installing Tesseract OCR with por/eng language data"
  if command -v apt-get >/dev/null 2>&1; then
    if run_with_sudo env DEBIAN_FRONTEND=noninteractive apt-get update \
      && run_with_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng; then
      log "Tesseract packages installed."
    fi
  fi

  if command -v tesseract >/dev/null 2>&1 \
    && has_tesseract_language por \
    && has_tesseract_language eng; then
    log "Eco study OCR ready: $(tesseract --version 2>/dev/null | head -n 1)"
    return 0
  fi

  if [[ "${REQUIRE_ECO_STUDY_OCR}" == "1" ]]; then
    echo "[ERROR] Tesseract OCR with por/eng is required but unavailable." >&2
    return 1
  fi

  log "WARN: Tesseract OCR unavailable; image and raster PDF imports will fail until provisioned."
  return 0
}

wait_http_ok() {
  local url="$1"
  local tries="${2:-20}"
  local delay="${3:-1}"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

wait_http_head_ok() {
  local url="$1"
  local tries="${2:-20}"
  local delay="${3:-1}"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsSI "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

resolve_systemctl_bin() {
  if [[ -n "${SYSTEMCTL_BIN:-}" && -x "${SYSTEMCTL_BIN}" ]]; then
    echo "${SYSTEMCTL_BIN}"
    return 0
  fi
  for candidate in /bin/systemctl /usr/bin/systemctl; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  command -v systemctl 2>/dev/null || true
}

restart_service() {
  local service="$1"
  if run_with_sudo "$SYSTEMCTL_BIN" restart "$service"; then
    return 0
  fi
  if "$SYSTEMCTL_BIN" restart "$service"; then
    return 0
  fi
  echo "[ERROR] Unable to restart service '${service}' automatically." >&2
  echo "[ERROR] Run manually: sudo ${SYSTEMCTL_BIN} restart ${service}" >&2
  return 1
}

print_service_diagnostics() {
  local service="$1"
  "$SYSTEMCTL_BIN" is-active "$service" || true
  echo "[INFO] Service diagnostics are available in the private VPS journal for ${service}."
}

reload_nginx_if_possible() {
  if [[ "${RELOAD_NGINX_ON_DEPLOY}" != "1" ]]; then
    log "Nginx reload disabled for this deploy."
    return 0
  fi
  local nginx_bin
  nginx_bin="$(command -v nginx 2>/dev/null || true)"
  if [[ -z "$nginx_bin" ]]; then
    log "Nginx binary not found; skipping nginx reload."
    return 0
  fi

  if run_with_sudo "$nginx_bin" -t && run_with_sudo "$SYSTEMCTL_BIN" reload nginx; then
    return 0
  fi

  if "$nginx_bin" -t && "$SYSTEMCTL_BIN" reload nginx; then
    return 0
  fi
  log "Skipping nginx reload (insufficient permissions)."
  return 0
}

ensure_nginx_http2_if_enabled() {
  if [[ "${ENABLE_NGINX_HTTP2}" != "1" ]]; then
    log "HTTP/2 enablement disabled (ENABLE_NGINX_HTTP2=${ENABLE_NGINX_HTTP2}); skipping."
    return 0
  fi

  local helper="${SCRIPT_DIR}/ensure_nginx_http2.sh"
  if [[ ! -f "${helper}" ]]; then
    echo "[ERROR] HTTP/2 helper is missing: ${helper}" >&2
    return 1
  fi

  ENABLE_NGINX_HTTP2="${ENABLE_NGINX_HTTP2}" \
    NGINX_HTTP2_EXPECTED_HOSTS="${NGINX_HTTP2_EXPECTED_HOSTS}" \
    NGINX_HTTP2_SITE_ROOT="${NGINX_HTTP2_SITE_ROOT}" \
    NGINX_HTTP2_ENABLED_ROOT="${NGINX_HTTP2_ENABLED_ROOT}" \
    PUBLIC_URL="${PUBLIC_URL}" \
    SUDO_PASSWORD="${SUDO_PASSWORD}" \
    bash "${helper}"
}

run_systemctl_command() {
  local action="$1"
  shift

  if run_with_sudo "$SYSTEMCTL_BIN" "$action" "$@"; then
    return 0
  fi

  "$SYSTEMCTL_BIN" "$action" "$@"
}

read_backend_service_property() {
  local property="$1"

  if run_with_sudo "$SYSTEMCTL_BIN" show "$BACKEND_SERVICE" "--property=${property}" --value 2>/dev/null; then
    return 0
  fi
  "$SYSTEMCTL_BIN" show "$BACKEND_SERVICE" "--property=${property}" --value 2>/dev/null || true
}

run_frontend_build() {
  rm -rf .next
  npm ci

  if [[ "${ENABLE_WHATSAPP_STAGE_BACKEND}" == "1" ]]; then
    API_BACKEND_URL="$API_BACKEND_URL" \
      WHATSAPP_STAGE_BACKEND_URL="$WHATSAPP_STAGE_BACKEND_URL" \
      npm run build
    return 0
  fi

  API_BACKEND_URL="$API_BACKEND_URL" npm run build
}

read_env_file_value() {
  local env_file="$1"
  local key="$2"
  local default_value="${3:-}"

  if [[ ! -f "$env_file" ]]; then
    printf '%s' "$default_value"
    return 0
  fi

  local line
  line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$default_value"
    return 0
  fi

  local value
  value="${line#*=}"
  value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  value="$(printf '%s' "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
  printf '%s' "$value"
}

is_env_placeholder_value() {
  local value="$1"
  local normalized
  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

  if [[ -z "$normalized" ]]; then
    return 0
  fi

  case "$normalized" in
    "<"*">")
      return 0
      ;;
    *placeholder*)
      return 0
      ;;
    *not_configured*|000000000000000)
      return 0
      ;;
    stage_access_token_placeholder|stage_phone_number_id|stage_verify_token|stage_app_secret)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

upsert_env_key() {
  local env_file="$1"
  local key="$2"
  local value="${3:-}"
  local temp_file

  if [[ ! -f "$env_file" ]]; then
    return 1
  fi

  temp_file="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { replaced = 0 }
    {
      if ($0 ~ ("^" k "=")) {
        if (replaced == 0) {
          print k "=" v
          replaced = 1
        }
      } else {
        print $0
      }
    }
    END {
      if (replaced == 0) {
        print k "=" v
      }
    }
  ' "$env_file" > "$temp_file"

  mv "$temp_file" "$env_file"
}

set_env_key_if_blank() {
  local env_file="$1"
  local key="$2"
  local default_value="${3:-}"
  local current_value

  current_value="$(read_env_file_value "$env_file" "$key" "")"
  if [[ -n "$current_value" ]]; then
    return 0
  fi

  upsert_env_key "$env_file" "$key" "$default_value"
}

set_env_key_if_blank_or_placeholder() {
  local env_file="$1"
  local key="$2"
  local default_value="${3:-}"
  local current_value

  current_value="$(read_env_file_value "$env_file" "$key" "")"
  if [[ -n "$current_value" ]] && ! is_env_placeholder_value "$current_value"; then
    return 0
  fi

  upsert_env_key "$env_file" "$key" "$default_value"
}

ensure_backend_stage_cookie_security() {
  local backend_env_file="${BACKEND_DIR}/.env"

  if [[ "${BRANCH}" != "stage" ]]; then
    return 0
  fi

  if [[ ! -f "${backend_env_file}" ]]; then
    echo "[ERROR] Backend env file not found: ${backend_env_file}" >&2
    return 1
  fi

  upsert_env_key "${backend_env_file}" "APP_ENV" "stage"
  upsert_env_key "${backend_env_file}" "AUTH_COOKIE_SECURE" "true"
  set_env_key_if_blank "${backend_env_file}" "AUTH_COOKIE_SAMESITE" "lax"
  log "Stage backend cookie security env ensured (APP_ENV=stage, AUTH_COOKIE_SECURE=true)."
}

replace_env_key_if_exact_match() {
  local env_file="$1"
  local key="$2"
  local expected_value="${3:-}"
  local replacement_value="${4:-}"
  local current_value

  current_value="$(read_env_file_value "$env_file" "$key" "")"
  if [[ "$current_value" != "$expected_value" ]]; then
    return 0
  fi

  upsert_env_key "$env_file" "$key" "$replacement_value"
  log "Auto-healed legacy WhatsApp stage placeholder: ${key}"
}

sync_env_key_from_file() {
  local source_file="$1"
  local target_file="$2"
  local key="$3"
  local value

  value="$(read_env_file_value "$source_file" "$key" "")"
  if [[ -z "$value" ]]; then
    echo "[ERROR] WhatsApp source config is missing required key: ${key}" >&2
    return 1
  fi

  upsert_env_key "$target_file" "$key" "$value"
}

ensure_whatsapp_stage_env_file() {
  local generated_internal_token generated_verify_token
  local default_access_token default_phone_number_id default_app_secret
  local default_meta_app_id default_business_account_id
  local current_internal_token_before current_internal_token_after
  local backend_database_url
  generated_internal_token="$(
    python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
  )"
  generated_verify_token="$(
    python3 - <<'PY'
import secrets
print("stage_verify_" + secrets.token_hex(8))
PY
  )"
  default_access_token="stage_access_token_not_configured"
  default_phone_number_id="${WHATSAPP_EXPECTED_PHONE_NUMBER_ID:-stage_phone_number_id_not_configured}"
  default_app_secret="stage_app_secret_not_configured"
  default_meta_app_id="${WHATSAPP_EXPECTED_META_APP_ID:-stage_meta_app_id_not_configured}"
  default_business_account_id="${WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID:-stage_business_account_id_not_configured}"

  backend_database_url="$(read_env_file_value "${BACKEND_DIR}/.env" "DATABASE_URL" "")"
  if [[ -z "${backend_database_url}" ]]; then
    echo "[ERROR] Could not infer DATABASE_URL from ${BACKEND_DIR}/.env for WhatsApp backend." >&2
    return 1
  fi

  if [[ ! -f "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" ]]; then
    mkdir -p "$(dirname "${WHATSAPP_STAGE_BACKEND_ENV_FILE}")"
    cat > "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" <<EOF
PORT=${WHATSAPP_STAGE_BACKEND_PORT}
DATABASE_URL=${backend_database_url}
WHATSAPP_ACCESS_TOKEN=${default_access_token}
PHONE_NUMBER_ID=${default_phone_number_id}
WHATSAPP_VERIFY_TOKEN=${generated_verify_token}
WHATSAPP_APP_SECRET=${default_app_secret}
WHATSAPP_GRAPH_API_VERSION=v26.0
META_APP_ID=${default_meta_app_id}
WHATSAPP_BUSINESS_ACCOUNT_ID=${default_business_account_id}
WHATSAPP_RESERVATION_TEMPLATE_NAME=reserva_de_agendamento
WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE=pt_BR
NODE_ENV=production
WEBHOOK_ALLOW_UNSIGNED=false
API_BACKEND_URL=${API_BACKEND_URL}
WHATSAPP_API_AUTH_ENABLED=true
WHATSAPP_ALLOWED_PAPEIS=${WHATSAPP_DEFAULT_ALLOWED_PAPEIS}
WHATSAPP_WRITE_ALLOWED_PAPEIS=${WHATSAPP_DEFAULT_WRITE_ALLOWED_PAPEIS}
WHATSAPP_INTERNAL_API_TOKEN=${generated_internal_token}
EOF
    log "Created ${WHATSAPP_STAGE_BACKEND_ENV_FILE} with safe placeholders."
  fi

  if [[ -n "${WHATSAPP_META_SOURCE_ENV_FILE}" ]]; then
    if [[ ! -f "${WHATSAPP_META_SOURCE_ENV_FILE}" ]]; then
      echo "[ERROR] WhatsApp Meta source env file not found: ${WHATSAPP_META_SOURCE_ENV_FILE}" >&2
      return 1
    fi

    local meta_key
    for meta_key in \
      WHATSAPP_ACCESS_TOKEN \
      PHONE_NUMBER_ID \
      WHATSAPP_VERIFY_TOKEN \
      WHATSAPP_APP_SECRET \
      WHATSAPP_GRAPH_API_VERSION \
      META_APP_ID \
      WHATSAPP_BUSINESS_ACCOUNT_ID \
      WHATSAPP_RESERVATION_TEMPLATE_NAME \
      WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE; do
      sync_env_key_from_file \
        "${WHATSAPP_META_SOURCE_ENV_FILE}" \
        "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" \
        "${meta_key}"
    done
    log "WhatsApp Meta configuration synchronized for ${WHATSAPP_RUNTIME_LABEL} without exposing secrets."
  fi

  current_internal_token_before="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_INTERNAL_API_TOKEN" "")"

  # Handle exact legacy placeholder values first, then keep generic fallback below.
  replace_env_key_if_exact_match "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_ACCESS_TOKEN" "stage_access_token_placeholder" "${default_access_token}"
  replace_env_key_if_exact_match "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "PHONE_NUMBER_ID" "stage_phone_number_id" "${default_phone_number_id}"
  replace_env_key_if_exact_match "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_VERIFY_TOKEN" "stage_verify_token" "${generated_verify_token}"
  replace_env_key_if_exact_match "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_APP_SECRET" "stage_app_secret" "${default_app_secret}"

  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "PORT" "${WHATSAPP_STAGE_BACKEND_PORT}"
  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "DATABASE_URL" "${backend_database_url}"
  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "API_BACKEND_URL" "${API_BACKEND_URL}"
  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "NODE_ENV" "production"
  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WEBHOOK_ALLOW_UNSIGNED" "false"
  upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_API_AUTH_ENABLED" "true"
  if [[ -n "${WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED}" ]]; then
    if [[ "${WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED}" != "true" && "${WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED}" != "false" ]]; then
      echo "[ERROR] WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED must be true or false." >&2
      return 1
    fi
    upsert_env_key \
      "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" \
      "DATABASE_SSL_REJECT_UNAUTHORIZED" \
      "${WHATSAPP_DATABASE_SSL_REJECT_UNAUTHORIZED}"
  fi
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_ALLOWED_PAPEIS" "${WHATSAPP_DEFAULT_ALLOWED_PAPEIS}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_WRITE_ALLOWED_PAPEIS" "${WHATSAPP_DEFAULT_WRITE_ALLOWED_PAPEIS}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_INTERNAL_API_TOKEN" "${generated_internal_token}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_ACCESS_TOKEN" "${default_access_token}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "PHONE_NUMBER_ID" "${default_phone_number_id}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_VERIFY_TOKEN" "${generated_verify_token}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_APP_SECRET" "${default_app_secret}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_GRAPH_API_VERSION" "v26.0"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "META_APP_ID" "${default_meta_app_id}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_BUSINESS_ACCOUNT_ID" "${default_business_account_id}"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_RESERVATION_TEMPLATE_NAME" "reserva_de_agendamento"
  set_env_key_if_blank_or_placeholder "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE" "pt_BR"

  current_internal_token_after="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_INTERNAL_API_TOKEN" "")"
  if [[ -z "${current_internal_token_before}" && -n "${current_internal_token_after}" ]]; then
    log "Generated WHATSAPP_INTERNAL_API_TOKEN for ${WHATSAPP_STAGE_BACKEND_ENV_FILE}."
  fi
  chmod 600 "${WHATSAPP_STAGE_BACKEND_ENV_FILE}"
}

validate_whatsapp_stage_meta_config() {
  local access_token phone_number_id app_secret verify_token
  local meta_app_id business_account_id template_name template_language
  local invalid=0

  access_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_ACCESS_TOKEN" "")"
  phone_number_id="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "PHONE_NUMBER_ID" "")"
  app_secret="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_APP_SECRET" "")"
  verify_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_VERIFY_TOKEN" "")"
  meta_app_id="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "META_APP_ID" "")"
  business_account_id="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_BUSINESS_ACCOUNT_ID" "")"
  template_name="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_RESERVATION_TEMPLATE_NAME" "")"
  template_language="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE" "")"

  if is_env_placeholder_value "${access_token}" || [[ "${access_token}" != EAA* ]] || [[ "${#access_token}" -lt 64 ]]; then
    echo "[ERROR] WHATSAPP_ACCESS_TOKEN ausente, placeholder ou fora do formato esperado." >&2
    invalid=1
  fi
  if is_env_placeholder_value "${phone_number_id}" || [[ ! "${phone_number_id}" =~ ^[0-9]{10,32}$ ]]; then
    echo "[ERROR] PHONE_NUMBER_ID ausente, placeholder ou fora do formato esperado." >&2
    invalid=1
  fi
  if is_env_placeholder_value "${app_secret}" || [[ ! "${app_secret}" =~ ^[[:xdigit:]]{32}$ ]]; then
    echo "[ERROR] WHATSAPP_APP_SECRET ausente, placeholder ou fora do formato esperado." >&2
    invalid=1
  fi
  if is_env_placeholder_value "${verify_token}" || [[ "${#verify_token}" -lt 16 ]]; then
    echo "[ERROR] WHATSAPP_VERIFY_TOKEN ausente, placeholder ou muito curto." >&2
    invalid=1
  fi
  if is_env_placeholder_value "${meta_app_id}" || [[ ! "${meta_app_id}" =~ ^[0-9]{10,32}$ ]]; then
    echo "[ERROR] META_APP_ID ausente, placeholder ou fora do formato esperado." >&2
    invalid=1
  fi
  if is_env_placeholder_value "${business_account_id}" || [[ ! "${business_account_id}" =~ ^[0-9]{10,32}$ ]]; then
    echo "[ERROR] WHATSAPP_BUSINESS_ACCOUNT_ID ausente, placeholder ou fora do formato esperado." >&2
    invalid=1
  fi
  if [[ -n "${WHATSAPP_EXPECTED_PHONE_NUMBER_ID}" && "${phone_number_id}" != "${WHATSAPP_EXPECTED_PHONE_NUMBER_ID}" ]]; then
    echo "[ERROR] PHONE_NUMBER_ID nao corresponde a identidade esperada para ${WHATSAPP_RUNTIME_LABEL}." >&2
    invalid=1
  fi
  if [[ -n "${WHATSAPP_EXPECTED_META_APP_ID}" && "${meta_app_id}" != "${WHATSAPP_EXPECTED_META_APP_ID}" ]]; then
    echo "[ERROR] META_APP_ID nao corresponde a identidade esperada para ${WHATSAPP_RUNTIME_LABEL}." >&2
    invalid=1
  fi
  if [[ -n "${WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID}" && "${business_account_id}" != "${WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID}" ]]; then
    echo "[ERROR] WHATSAPP_BUSINESS_ACCOUNT_ID nao corresponde a identidade esperada para ${WHATSAPP_RUNTIME_LABEL}." >&2
    invalid=1
  fi
  if [[ "${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION}" != "0" && "${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION}" != "1" ]]; then
    echo "[ERROR] WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION deve ser 0 ou 1." >&2
    invalid=1
  elif [[ "${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION}" == "1" ]]; then
    if [[ "${phone_number_id}" == "${WHATSAPP_PRODUCTION_PHONE_NUMBER_ID}" ]]; then
      echo "[ERROR] PHONE_NUMBER_ID de stage nao pode reutilizar o numero de producao." >&2
      invalid=1
    fi
    if [[ "${meta_app_id}" == "${WHATSAPP_PRODUCTION_META_APP_ID}" ]]; then
      echo "[ERROR] META_APP_ID de stage nao pode reutilizar o app de producao." >&2
      invalid=1
    fi
    if [[ "${business_account_id}" == "${WHATSAPP_PRODUCTION_BUSINESS_ACCOUNT_ID}" ]]; then
      echo "[ERROR] WHATSAPP_BUSINESS_ACCOUNT_ID de stage nao pode reutilizar a WABA de producao." >&2
      invalid=1
    fi
  fi
  if [[ "${template_name}" != "reserva_de_agendamento" || "${template_language}" != "pt_BR" ]]; then
    echo "[ERROR] Modelo de reserva ou idioma nao correspondem ao modelo aprovado." >&2
    invalid=1
  fi

  if [[ "${invalid}" -ne 0 ]]; then
    echo "[ERROR] Configure os segredos Meta diretamente no servidor antes de habilitar o servico." >&2
    return 1
  fi

  log "WhatsApp ${WHATSAPP_RUNTIME_LABEL} Meta configuration validated without exposing secrets."
}

validate_stage_live_meta_mode() {
  if [[ -z "${WHATSAPP_STAGE_LIVE_META_ENABLED}" ]]; then
    return 0
  fi
  if [[ "${WHATSAPP_STAGE_LIVE_META_ENABLED}" != "0" && "${WHATSAPP_STAGE_LIVE_META_ENABLED}" != "1" ]]; then
    echo "[ERROR] WHATSAPP_STAGE_LIVE_META_ENABLED deve ser 0 ou 1." >&2
    return 1
  fi
  if [[ "${APP_DIR}" != "/var/www/fortcordis-stage" || "${BRANCH}" != "stage" \
        || "${BACKEND_SERVICE}" != "fortcordis-stage-backend" \
        || "${WHATSAPP_STAGE_BACKEND_SERVICE}" != "fortcordis-stage-whatsapp-backend" \
        || "${WHATSAPP_STAGE_BACKEND_PORT}" != "3010" \
        || "${WHATSAPP_STAGE_BACKEND_URL}" != "http://127.0.0.1:3010" \
        || "${WHATSAPP_STAGE_BACKEND_DIR}" != "/var/www/fortcordis-stage/whatsapp-stage-backend" \
        || "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" != "/var/www/fortcordis-stage/whatsapp-stage-backend/.env" \
        || "${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION}" != "1" \
        || -n "${WHATSAPP_META_SOURCE_ENV_FILE}" \
        || "${ENABLE_WHATSAPP_STAGE_BACKEND}" != "${WHATSAPP_STAGE_LIVE_META_ENABLED}" ]]; then
    echo "[ERROR] Stage live Meta mode requires the exact isolated stage target." >&2
    return 1
  fi
  if [[ "${WHATSAPP_STAGE_LIVE_META_ENABLED}" == "0" && "${ENABLE_WHATSAPP_STAGE_SMOKE}" != "0" ]]; then
    echo "[ERROR] Stage without live Meta cannot enable WhatsApp smoke." >&2
    return 1
  fi
}

disable_stage_live_meta_runtime() {
  validate_stage_live_meta_mode || return 1
  if [[ "${WHATSAPP_STAGE_LIVE_META_ENABLED}" != "0" ]]; then
    return 0
  fi
  local load_state active_state backend_env_file
  backend_env_file="${BACKEND_DIR}/.env"
  if [[ ! -f "${backend_env_file}" ]]; then
    echo "[ERROR] Stage backend env is required to disable its WhatsApp integration." >&2
    return 1
  fi
  if ! load_state="$("${SYSTEMCTL_BIN}" show "${WHATSAPP_STAGE_BACKEND_SERVICE}" --property=LoadState --value 2>/dev/null)"; then
    if [[ "${load_state}" != "not-found" ]]; then
      echo "[ERROR] Could not verify the isolated stage WhatsApp service state." >&2
      return 1
    fi
  fi
  case "${load_state}" in
    loaded|masked)
      run_systemctl_command disable --now "${WHATSAPP_STAGE_BACKEND_SERVICE}" || return 1
      if ! active_state="$("${SYSTEMCTL_BIN}" show "${WHATSAPP_STAGE_BACKEND_SERVICE}" --property=ActiveState --value 2>/dev/null)"; then
        echo "[ERROR] Could not confirm the isolated stage WhatsApp service stopped." >&2
        return 1
      fi
      if [[ "${active_state}" != "inactive" && "${active_state}" != "failed" ]]; then
        echo "[ERROR] Stage WhatsApp service remains active or unresolved without live Meta opt-in." >&2
        return 1
      fi
      ;;
    not-found) ;;
    *) echo "[ERROR] Unexpected isolated stage WhatsApp service load state." >&2; return 1 ;;
  esac
  upsert_env_key "${backend_env_file}" "WHATSAPP_AGENDA_ENABLED" "false"
  upsert_env_key "${backend_env_file}" "WHATSAPP_BOT_AUTO_SEND_ENABLED" "false"
  log "Stage live Meta disabled: isolated service stopped; core WhatsApp integration and automatic sending disabled."
}

ensure_whatsapp_core_integration_env() {
  validate_stage_live_meta_mode || return 1
  if [[ "${ENABLE_WHATSAPP_STAGE_BACKEND}" != "1" ]]; then
    disable_stage_live_meta_runtime
    return $?
  fi

  ensure_whatsapp_stage_env_file
  local internal_token backend_env_file
  backend_env_file="${BACKEND_DIR}/.env"
  internal_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_INTERNAL_API_TOKEN" "")"
  if [[ -z "${internal_token}" ]]; then
    echo "[ERROR] WhatsApp internal token is unavailable for core integration." >&2
    return 1
  fi

  upsert_env_key "${backend_env_file}" "WHATSAPP_AGENDA_ENABLED" "true"
  upsert_env_key "${backend_env_file}" "WHATSAPP_AGENDA_SERVICE_URL" "${WHATSAPP_STAGE_BACKEND_URL}"
  upsert_env_key "${backend_env_file}" "WHATSAPP_AGENDA_INTERNAL_TOKEN" "${internal_token}"
  log "Core WhatsApp agenda integration env ensured."
}

ensure_whatsapp_stage_service_unit() {
  local unit_path="/etc/systemd/system/${WHATSAPP_STAGE_BACKEND_SERVICE}.service"
  local temp_unit="${APP_DIR}/.tmp.${WHATSAPP_STAGE_BACKEND_SERVICE}.service"

  cat > "${temp_unit}" <<EOF
[Unit]
Description=FortCordis WhatsApp ${WHATSAPP_RUNTIME_LABEL} Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=${WHATSAPP_STAGE_BACKEND_DIR}
EnvironmentFile=${WHATSAPP_STAGE_BACKEND_ENV_FILE}
Environment=NODE_ENV=production
ExecStart=${NPM_BIN} run start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  if run_with_sudo install -m 0644 "${temp_unit}" "${unit_path}"; then
    :
  else
    install -m 0644 "${temp_unit}" "${unit_path}"
  fi
  rm -f "${temp_unit}"

  run_systemctl_command daemon-reload
  run_systemctl_command enable "${WHATSAPP_STAGE_BACKEND_SERVICE}"
}

ensure_background_worker_service_units() {
  local worker_unit_path="/etc/systemd/system/${BACKGROUND_WORKER_SERVICE}.service"
  local api_dropin_dir="/etc/systemd/system/${BACKEND_SERVICE}.service.d"
  local api_dropin_path="${api_dropin_dir}/fortcordis-process-role.conf"
  local worker_unit_tmp="${APP_DIR}/.tmp.${BACKGROUND_WORKER_SERVICE}.service"
  local api_dropin_tmp="${APP_DIR}/.tmp.${BACKEND_SERVICE}.process-role.conf"
  local backend_service_user backend_service_group worker_account_lines
  backend_service_user="$(read_backend_service_property User)"
  backend_service_group="$(read_backend_service_property Group)"
  worker_account_lines=""
  if [[ -n "${backend_service_user}" ]]; then
    worker_account_lines+="User=${backend_service_user}"$'\n'
  fi
  if [[ -n "${backend_service_group}" ]]; then
    worker_account_lines+="Group=${backend_service_group}"$'\n'
  fi

  cat > "${worker_unit_tmp}" <<EOF
[Unit]
Description=FortCordis Background Workers (${BRANCH})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${BACKEND_DIR}
EnvironmentFile=${BACKEND_DIR}/.env
Environment=FORTCORDIS_PROCESS_ROLE=worker
Environment=PYTHONPATH=${BACKEND_DIR}
${worker_account_lines}ExecStart=${BACKEND_DIR}/venv/bin/python -m app.worker
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

  cat > "${api_dropin_tmp}" <<EOF
[Service]
Environment=FORTCORDIS_PROCESS_ROLE=api
EOF

  if run_with_sudo install -m 0644 "${worker_unit_tmp}" "${worker_unit_path}"; then
    :
  else
    install -m 0644 "${worker_unit_tmp}" "${worker_unit_path}"
  fi
  if run_with_sudo mkdir -p "${api_dropin_dir}"; then
    :
  else
    mkdir -p "${api_dropin_dir}"
  fi
  if run_with_sudo install -m 0644 "${api_dropin_tmp}" "${api_dropin_path}"; then
    :
  else
    install -m 0644 "${api_dropin_tmp}" "${api_dropin_path}"
  fi
  rm -f "${worker_unit_tmp}" "${api_dropin_tmp}"

  run_systemctl_command daemon-reload
  run_systemctl_command enable "${BACKGROUND_WORKER_SERVICE}"
}

remove_background_worker_service_units() {
  local worker_unit_path="/etc/systemd/system/${BACKGROUND_WORKER_SERVICE}.service"
  local api_dropin_path="/etc/systemd/system/${BACKEND_SERVICE}.service.d/fortcordis-process-role.conf"

  run_systemctl_command disable --now "${BACKGROUND_WORKER_SERVICE}" || true
  if run_with_sudo rm -f "${worker_unit_path}" "${api_dropin_path}"; then
    :
  else
    rm -f "${worker_unit_path}" "${api_dropin_path}"
  fi
  run_systemctl_command daemon-reload
}

ensure_ffmpeg_static_binary() {
  local backend_dir="$1"
  local ffmpeg_bin
  ffmpeg_bin="$(cd "${backend_dir}" && node -e "console.log(require('ffmpeg-static') || '')" 2>/dev/null || true)"

  if [[ -z "${ffmpeg_bin}" || ! -x "${ffmpeg_bin}" ]]; then
    log "WARN: ffmpeg-static binary unavailable (resolved path='${ffmpeg_bin:-<empty>}'); WhatsApp audio de voz sera servido sem transcodificacao (fallback OGG/Opus original)."
    return 0
  fi

  log "ffmpeg-static binary ready: ${ffmpeg_bin} ($("${ffmpeg_bin}" -version 2>&1 | head -n 1))"
}

deploy_whatsapp_stage_backend() {
  if [[ "${ENABLE_WHATSAPP_STAGE_BACKEND}" != "1" ]]; then
    return 0
  fi

  if [[ ! -d "${WHATSAPP_STAGE_BACKEND_DIR}" ]]; then
    echo "[ERROR] WhatsApp stage backend dir not found: ${WHATSAPP_STAGE_BACKEND_DIR}" >&2
    return 1
  fi

  ensure_whatsapp_stage_env_file
  validate_whatsapp_stage_meta_config
  if [[ -n "${WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED:-}" ]]; then
    if [[ "${WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED}" != "true" && "${WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED}" != "false" ]]; then
      echo "[ERROR] WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED must be true or false." >&2
      return 1
    fi
    upsert_env_key "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED" "${WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED}"
    log "WhatsApp ${WHATSAPP_RUNTIME_LABEL} home report template gate set to ${WHATSAPP_HOME_REPORT_TEMPLATE_ENABLED}."
  fi
  ensure_whatsapp_stage_service_unit

  log "WhatsApp ${WHATSAPP_RUNTIME_LABEL} backend: install deps + migrations"
  cd "${WHATSAPP_STAGE_BACKEND_DIR}"
  npm ci
  ensure_ffmpeg_static_binary "${WHATSAPP_STAGE_BACKEND_DIR}"
  npm run build
  npm run migrate

  restart_service "${WHATSAPP_STAGE_BACKEND_SERVICE}"
  sleep 3
  if ! wait_http_ok "http://127.0.0.1:${WHATSAPP_STAGE_BACKEND_PORT}/health" 25 1; then
    echo "[ERROR] WhatsApp ${WHATSAPP_RUNTIME_LABEL} backend health check failed." >&2
    print_service_diagnostics "${WHATSAPP_STAGE_BACKEND_SERVICE}"
    return 1
  fi
  log "WhatsApp ${WHATSAPP_RUNTIME_LABEL} backend health OK"

  if [[ "${ENABLE_WHATSAPP_STAGE_SMOKE}" == "1" && -f "${WHATSAPP_STAGE_BACKEND_DIR}/scripts/smoke-tests.sh" ]]; then
    local verify_token app_secret access_token internal_api_token
    verify_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_VERIFY_TOKEN" "stage_verify_token")"
    app_secret="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_APP_SECRET" "stage_app_secret")"
    access_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_ACCESS_TOKEN" "stage_access_token_placeholder")"
    internal_api_token="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" "WHATSAPP_INTERNAL_API_TOKEN" "")"

    log "WhatsApp ${WHATSAPP_RUNTIME_LABEL} backend smoke tests"
    BASE_URL="http://127.0.0.1:${WHATSAPP_STAGE_BACKEND_PORT}" \
      WHATSAPP_VERIFY_TOKEN="${verify_token}" \
      WHATSAPP_APP_SECRET="${app_secret}" \
      WHATSAPP_ACCESS_TOKEN="${access_token}" \
      WHATSAPP_INTERNAL_API_TOKEN="${internal_api_token}" \
      bash "${WHATSAPP_STAGE_BACKEND_DIR}/scripts/smoke-tests.sh"
  fi
}

backup_runtime_file() {
  local rel_path="$1"
  local src="${APP_DIR}/${rel_path}"
  local dst="${RUNTIME_SNAPSHOT_DIR}/${rel_path}"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    cp -f "$src" "$dst"
    log "Preserved runtime file: ${rel_path}"
  fi
}

prune_runtime_backups() {
  if [[ ! -d "$RUNTIME_BACKUP_DIR" ]]; then
    return
  fi

  local pruned_by_age=0
  while IFS= read -r -d '' item; do
    rm -rf -- "$item"
    pruned_by_age=$((pruned_by_age + 1))
  done < <(find "$RUNTIME_BACKUP_DIR" -mindepth 1 -maxdepth 1 -mtime "+${RUNTIME_BACKUP_RETENTION_DAYS}" -print0 2>/dev/null)
  if [[ "$pruned_by_age" -gt 0 ]]; then
    log "Pruned ${pruned_by_age} runtime backup item(s) com mais de ${RUNTIME_BACKUP_RETENTION_DAYS} dias em ${RUNTIME_BACKUP_DIR}"
  fi

  local total_items
  total_items="$(find "$RUNTIME_BACKUP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$total_items" -gt "$RUNTIME_BACKUP_MAX_ITEMS" ]]; then
    local excess=$((total_items - RUNTIME_BACKUP_MAX_ITEMS))
    local pruned_by_count=0
    while IFS= read -r item && [[ "$pruned_by_count" -lt "$excess" ]]; do
      rm -rf -- "$item"
      pruned_by_count=$((pruned_by_count + 1))
    done < <(find "$RUNTIME_BACKUP_DIR" -mindepth 1 -maxdepth 1 -printf '%T@ %p\n' 2>/dev/null | sort -n | cut -d' ' -f2-)
    log "Pruned ${pruned_by_count} runtime backup item(s) adicionais para manter no maximo ${RUNTIME_BACKUP_MAX_ITEMS} itens em ${RUNTIME_BACKUP_DIR}"
  fi
}

restore_runtime_file() {
  local rel_path="$1"
  local src="${RUNTIME_SNAPSHOT_DIR}/${rel_path}"
  local dst="${APP_DIR}/${rel_path}"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    cp -f "$src" "$dst"
    log "Restored runtime file: ${rel_path}"
  fi
}

restore_runtime_artifacts() {
  restore_runtime_file "backend/fortcordis.db"
  restore_runtime_file "backend/data/frases.json"
  restore_runtime_file "backend/data/patologias.json"
  restore_runtime_file "backend/data/frases_ecocardiograma_estruturado_teste.json"
  restore_runtime_file "backend/data/frases_ultrassom_abdominal.json"
  restore_runtime_file "backend/data/atendimento_clinical_phrases.json"
}

write_reminder_service_flag_lines() {
  # Somente a flag operacional; nunca copiar ou imprimir as outras chaves.
  python3 - "${BACKEND_DIR}/.env" "$1" <<'PY'
import os
from pathlib import Path
import stat
import sys
import tempfile

path = Path(sys.argv[1]).resolve(strict=True)
previous = path.stat()
key = "WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED="
lines = [line for line in path.read_text().splitlines(keepends=True) if not line.startswith(key)]
if sys.argv[2]:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(sys.argv[2] + "\n")
temp = None
try:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temp = handle.name
        os.fchown(handle.fileno(), previous.st_uid, previous.st_gid)
        os.fchmod(handle.fileno(), stat.S_IMODE(previous.st_mode))
        handle.write("".join(lines))
    os.replace(temp, path)
finally:
    if temp and os.path.exists(temp):
        os.unlink(temp)
PY
}

restore_reminder_service_flag() {
  if [[ "${REMINDER_SERVICE_FLAG_CHANGED}" != "1" ]]; then
    return 0
  fi
  if ! run_systemctl_command stop "$BACKGROUND_WORKER_SERVICE"; then
    echo "[WARN] Worker stop failed; restoring reminder flag before retrying restart." >&2
  fi
  write_reminder_service_flag_lines "${REMINDER_SERVICE_PREVIOUS_FLAG_LINES}" || return 1
  REMINDER_SERVICE_FLAG_CHANGED=0
  log "Previous WhatsApp reminder flag restored before rollback."
  restart_service "$BACKEND_SERVICE" || return 1
  wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/ready" 25 1 || return 1
  restart_service "$BACKGROUND_WORKER_SERVICE" || return 1
  run_systemctl_command is-active --quiet "$BACKGROUND_WORKER_SERVICE"
}

activate_whatsapp_reminder_service() {
  if [[ "${DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE}" == "0" ]]; then
    return 0
  fi
  if [[ "${DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE}" != "1" \
        || "${BRANCH}" != "main" || "${WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION}" != "0" \
        || "${ENABLE_WHATSAPP_STAGE_BACKEND}" != "1" \
        || "${WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID}" != "${WHATSAPP_PRODUCTION_BUSINESS_ACCOUNT_ID}" \
        || "${ENABLE_AUTH_CANARY}" != "1" || "${ENABLE_BACKUP_RESTORE_DRILL}" != "1" ]]; then
    echo "[ERROR] Reminder activation requires production and all release gates." >&2
    return 1
  fi
  local account previous_value
  account="$(read_env_file_value "${WHATSAPP_STAGE_BACKEND_ENV_FILE}" WHATSAPP_BUSINESS_ACCOUNT_ID "")"
  if [[ "${account}" != "${WHATSAPP_PRODUCTION_BUSINESS_ACCOUNT_ID}" ]]; then
    echo "[ERROR] Reminder activation rejected: unexpected WhatsApp account." >&2
    return 1
  fi
  wait_http_ok "http://127.0.0.1:${WHATSAPP_STAGE_BACKEND_PORT}/health" 25 1 || return 1
  # Verifica o contrato compilado que acabou de ser instalado, sem chamar a Meta.
  WHATSAPP_BUSINESS_ACCOUNT_ID="${account}" node - "${WHATSAPP_STAGE_BACKEND_DIR}/dist/templates/approvedTemplates.js" <<'JS' || return 1
const catalog = require(process.argv[2]);
if (typeof catalog.isTemplateDeliveryApproved !== "function"
    || !catalog.isTemplateDeliveryApproved("appointmentReminderService")) {
  throw new Error("Installed reminder contract is not approved for this account");
}
JS
  previous_value="$(read_env_file_value "${BACKEND_DIR}/.env" WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED "false")"
  case "$(printf '%s' "${previous_value}" | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) log "WhatsApp service reminder already enabled; operational flag preserved."; return 0 ;;
    false|0|no|off|"") ;;
    *) echo "[ERROR] Existing reminder flag is invalid; activation cancelled." >&2; return 1 ;;
  esac
  REMINDER_SERVICE_PREVIOUS_FLAG_LINES="$(grep '^WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=' "${BACKEND_DIR}/.env" || true)"
  run_systemctl_command stop "$BACKGROUND_WORKER_SERVICE" || return 1
  REMINDER_SERVICE_FLAG_CHANGED=1
  write_reminder_service_flag_lines 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=true' || return 1
  restart_service "$BACKEND_SERVICE" || return 1
  wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/ready" 25 1 || return 1
  restart_service "$BACKGROUND_WORKER_SERVICE" || return 1
  run_systemctl_command is-active --quiet "$BACKGROUND_WORKER_SERVICE" || return 1
  log "WhatsApp service reminder activated after release gates."
}

rollback_deploy() {
  if [[ -z "${PRE_DEPLOY_HASH}" ]]; then
    echo "[ERROR] PRE_DEPLOY_HASH vazio; rollback automatico indisponivel." >&2
    return 1
  fi

  log "Starting automatic rollback to ${PRE_DEPLOY_HASH}"

  cd "$APP_DIR"
  git checkout "$BRANCH"
  git reset --hard "$PRE_DEPLOY_HASH"
  restore_runtime_artifacts
  local rollback_hash
  rollback_hash="$(git rev-parse --short HEAD)"
  log "Rollback HEAD: ${rollback_hash}"
  if [[ -f "${BACKEND_DIR}/.env" ]]; then
    upsert_env_key "${BACKEND_DIR}/.env" "RUNTIME_HTTP_LATENCY_RELEASE_ID" "${rollback_hash}"
    log "Runtime latency release id restored for rollback."
  fi

  if [[ "${PREVIOUS_BACKGROUND_WORKER_SUPPORT}" != "1" ]]; then
    # A versao anterior iniciava os workers dentro da API. Remover o drop-in
    # antes de reinicia-la devolve exatamente esse comportamento no rollback.
    remove_background_worker_service_units
  fi

  cd "$BACKEND_DIR"
  if [[ ! -x "${BACKEND_DIR}/venv/bin/python" ]]; then
    log "Creating backend venv for rollback"
    python3 -m venv "${BACKEND_DIR}/venv"
  fi
  "${BACKEND_DIR}/venv/bin/pip" install -r requirements.txt
  restart_service "$BACKEND_SERVICE"
  sleep 3
  if ! wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/health" 25 1; then
    echo "[ERROR] Rollback backend health check failed." >&2
    print_service_diagnostics "$BACKEND_SERVICE"
    return 1
  fi

  if [[ "${PREVIOUS_BACKGROUND_WORKER_SUPPORT}" == "1" ]]; then
    restart_service "$BACKGROUND_WORKER_SERVICE"
    if ! run_systemctl_command is-active --quiet "$BACKGROUND_WORKER_SERVICE"; then
      echo "[ERROR] Rollback background worker service is not active." >&2
      print_service_diagnostics "$BACKGROUND_WORKER_SERVICE"
      return 1
    fi
  fi

  cd "$FRONTEND_DIR"
  run_frontend_build
  if [[ ! -f "${FRONTEND_DIR}/.next/BUILD_ID" ]]; then
    echo "[ERROR] Rollback frontend build missing .next/BUILD_ID" >&2
    return 1
  fi
  restart_service "$FRONTEND_SERVICE"
  sleep 3
  if ! wait_http_head_ok "http://127.0.0.1:${FRONTEND_PORT}" 25 1; then
    echo "[ERROR] Rollback frontend local check failed." >&2
    print_service_diagnostics "$FRONTEND_SERVICE"
    return 1
  fi

  reload_nginx_if_possible
  if ! wait_http_head_ok "$PUBLIC_URL" 15 1; then
    echo "[ERROR] Rollback public URL check failed: $PUBLIC_URL" >&2
    print_service_diagnostics nginx
    return 1
  fi

  log "Automatic rollback completed successfully (HEAD=${rollback_hash})"
  return 0
}

on_exit() {
  local exit_code="$1"
  trap - EXIT

  if [[ "$exit_code" -eq 0 ]]; then
    exit 0
  fi

  echo "[ERROR] Deploy failed at stage '${DEPLOY_STAGE}' (exit=${exit_code})." >&2
  # A chave pode não existir no runtime antigo; restaurar também sua ausência
  # antes de reiniciar/voltar código, inclusive quando não há rollback de SHA.
  if ! restore_reminder_service_flag; then
    echo "[ERROR] Reminder flag/runtime restoration failed; checking rollback." >&2
    if [[ "${REMINDER_SERVICE_FLAG_CHANGED}" == "1" ]]; then
      echo "[ERROR] Previous reminder flag was not restored; preserving installed code and skipping rollback." >&2
      exit "$exit_code"
    fi
  fi
  if [[ "${AUTO_ROLLBACK_ON_FAILURE}" != "1" ]]; then
    echo "[ERROR] AUTO_ROLLBACK_ON_FAILURE=${AUTO_ROLLBACK_ON_FAILURE}; skipping rollback." >&2
    exit "$exit_code"
  fi
  if [[ "${CODE_UPDATED}" != "1" ]]; then
    echo "[ERROR] Deploy failed before code update; rollback not required." >&2
    exit "$exit_code"
  fi
  if [[ -z "${PRE_DEPLOY_HASH}" ]]; then
    echo "[ERROR] PRE_DEPLOY_HASH indisponivel; rollback nao pode ser executado." >&2
    exit "$exit_code"
  fi
  if [[ -n "${NEW_HASH}" && "${NEW_HASH}" == "${PRE_DEPLOY_HASH}" ]]; then
    echo "[ERROR] HEAD nao mudou; rollback nao necessario." >&2
    exit "$exit_code"
  fi
  if [[ "${ROLLBACK_IN_PROGRESS}" == "1" ]]; then
    echo "[ERROR] Rollback ja em execucao; abortando para evitar loop." >&2
    exit "$exit_code"
  fi

  ROLLBACK_IN_PROGRESS=1
  set +e
  rollback_deploy
  local rollback_code=$?
  if [[ "$rollback_code" -eq 0 ]]; then
    echo "[ERROR] Deploy rollback executado com sucesso." >&2
  else
    echo "[ERROR] Rollback automatico falhou (code=${rollback_code}). Intervencao manual necessaria." >&2
  fi
  exit "$exit_code"
}

# Ao carregar as funções para ensaio local, não iniciar um deploy.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

# Invalid identity must not enter cleanup/rollback handlers or inspect services.
validate_deploy_target
validate_stage_live_meta_mode

require_cmd git
require_cmd curl
require_cmd npm
require_cmd python3
NPM_BIN="$(command -v npm)"

SYSTEMCTL_BIN="$(resolve_systemctl_bin)"
if [[ -z "$SYSTEMCTL_BIN" ]]; then
  echo "[ERROR] Missing command: systemctl" >&2
  exit 1
fi

log "Starting deploy in ${APP_DIR} (branch=${BRANCH})"
cd "$APP_DIR"
PRE_DEPLOY_HASH="$(git rev-parse HEAD 2>/dev/null || true)"
PREVIOUS_BACKGROUND_WORKER_SUPPORT=0
if [[ -n "${PRE_DEPLOY_HASH}" ]]; then
  log "Pre-deploy HEAD: $(git rev-parse --short "${PRE_DEPLOY_HASH}")"
  if git cat-file -e "${PRE_DEPLOY_HASH}:backend/app/worker.py" 2>/dev/null; then
    PREVIOUS_BACKGROUND_WORKER_SUPPORT=1
  fi
fi

# Fail before runtime backup/reset/services when the requested revision cannot
# be fetched or does not belong to this environment's branch.
DEPLOY_STAGE="resolve_target"
resolve_deploy_target

trap 'on_exit $?' EXIT

mkdir -p "$RUNTIME_BACKUP_DIR"
prune_runtime_backups
STAMP="$(date +%Y%m%d_%H%M%S)"
DEPLOY_BACKUP_MARKER="${RUNTIME_BACKUP_DIR}/${STAMP}__deploy-prod.marker"
touch "$DEPLOY_BACKUP_MARKER"
log "Deploy marker created: $DEPLOY_BACKUP_MARKER"
RUNTIME_SNAPSHOT_DIR="${RUNTIME_BACKUP_DIR}/${STAMP}__runtime"

backup_runtime_file "backend/fortcordis.db"
backup_runtime_file "backend/data/frases.json"
backup_runtime_file "backend/data/patologias.json"
backup_runtime_file "backend/data/frases_ecocardiograma_estruturado_teste.json"
backup_runtime_file "backend/data/frases_ultrassom_abdominal.json"
backup_runtime_file "backend/data/atendimento_clinical_phrases.json"

DEPLOY_STAGE="update_code"
log "Updating code to ${DEPLOY_TARGET_SHA}"
update_deploy_code
restore_runtime_artifacts
NEW_HASH="$(git rev-parse --short HEAD)"
log "Current HEAD: ${NEW_HASH}"
git log --oneline -n 1

# PERF-17: permite comparar a latencia com o release realmente instalado, sem
# expor hash pelo navegador. Nao cria arquivo de ambiente ausente, para manter
# a configuracao existente de cada host como fonte de verdade.
if [[ -f "${BACKEND_DIR}/.env" ]]; then
  upsert_env_key "${BACKEND_DIR}/.env" "RUNTIME_HTTP_LATENCY_RELEASE_ID" "${NEW_HASH}"
  log "Runtime latency release id updated."
else
  log "WARNING: backend .env not found; latency samples will use release_id=unknown."
fi

DEPLOY_STAGE="backend_setup"
log "Backend: install deps + migrations"
cd "$BACKEND_DIR"

ensure_backend_stage_cookie_security
ensure_whatsapp_core_integration_env
ensure_eco_study_ocr_dependencies

if [[ ! -x "${BACKEND_DIR}/venv/bin/python" ]]; then
  log "Creating backend venv"
  python3 -m venv "${BACKEND_DIR}/venv"
fi

"${BACKEND_DIR}/venv/bin/pip" install -r requirements.txt

if [[ -f "${BACKEND_DIR}/migrations/runner.py" ]]; then
  PYTHONPATH="$BACKEND_DIR" "${BACKEND_DIR}/venv/bin/python" - <<'PY'
from migrations.runner import run_migrations
run_migrations()
print("MIGRATIONS_OK")
PY
elif [[ -f "${BACKEND_DIR}/setup_database.py" ]]; then
  PYTHONPATH="$BACKEND_DIR" "${BACKEND_DIR}/venv/bin/python" setup_database.py
else
  log "No migration runner found; skipping migrations."
fi

DEPLOY_STAGE="background_worker_setup"
ensure_background_worker_service_units

DEPLOY_STAGE="backend_restart"
restart_service "$BACKEND_SERVICE"
sleep 3
if ! wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/health" 25 1; then
  echo "[ERROR] Backend health check failed." >&2
  print_service_diagnostics "$BACKEND_SERVICE"
  exit 1
fi
log "Backend health OK"

DEPLOY_STAGE="background_worker_restart"
restart_service "$BACKGROUND_WORKER_SERVICE"
if ! run_systemctl_command is-active --quiet "$BACKGROUND_WORKER_SERVICE"; then
  echo "[ERROR] Background worker service is not active." >&2
  print_service_diagnostics "$BACKGROUND_WORKER_SERVICE"
  exit 1
fi
log "Background worker service active"

DEPLOY_STAGE="whatsapp_stage_backend"
deploy_whatsapp_stage_backend

DEPLOY_STAGE="frontend_build"
log "Frontend: clean build + restart"
cd "$FRONTEND_DIR"

run_frontend_build

if [[ ! -f "${FRONTEND_DIR}/.next/BUILD_ID" ]]; then
  echo "[ERROR] Frontend build missing .next/BUILD_ID" >&2
  exit 1
fi

DEPLOY_STAGE="frontend_restart"
restart_service "$FRONTEND_SERVICE"
sleep 3
if ! wait_http_head_ok "http://127.0.0.1:${FRONTEND_PORT}" 25 1; then
  echo "[ERROR] Frontend local check failed." >&2
  print_service_diagnostics "$FRONTEND_SERVICE"
  exit 1
fi
log "Frontend local check OK"

DEPLOY_STAGE="public_check"
log "Nginx reload + public check"
ensure_nginx_http2_if_enabled
reload_nginx_if_possible

if ! wait_http_head_ok "$PUBLIC_URL" 15 1; then
  echo "[ERROR] Public URL check failed: $PUBLIC_URL" >&2
  print_service_diagnostics nginx
  exit 1
fi

DEPLOY_STAGE="runtime_gate"
log "Runtime observability gate"
if ! python3 "${APP_DIR}/scripts/runtime_observability_gate.py" \
  --health-url "http://127.0.0.1:${BACKEND_PORT}/health" \
  --ready-url "http://127.0.0.1:${BACKEND_PORT}/ready" \
  --timeout-seconds 8; then
  echo "[ERROR] Runtime observability gate failed." >&2
  print_service_diagnostics "$BACKEND_SERVICE"
  exit 1
fi
log "Runtime observability gate OK"

DEPLOY_STAGE="auth_canary"
if [[ "${ENABLE_AUTH_CANARY}" == "1" ]]; then
  log "Authenticated canary smoke"
  CANARY_CMD=(
    "${BACKEND_DIR}/venv/bin/python"
    "${APP_DIR}/scripts/deploy_authenticated_canary.py"
    --base-url "http://127.0.0.1:${BACKEND_PORT}"
    --timeout-seconds "${AUTH_CANARY_TIMEOUT_SECONDS}"
    --backend-dir "${BACKEND_DIR}"
    --agenda-latency-samples "${AUTH_CANARY_AGENDA_LATENCY_SAMPLES}"
    --agenda-max-p95-ms "${AUTH_CANARY_AGENDA_MAX_P95_MS}"
    --expected-release-id "${NEW_HASH}"
  )
  if [[ "${AUTH_CANARY_DISABLE_INTERNAL_TOKEN}" == "1" ]]; then
    CANARY_CMD+=(--disable-internal-token)
  fi

  if ! PYTHONPATH="$BACKEND_DIR" "${CANARY_CMD[@]}"; then
    echo "[ERROR] Authenticated canary smoke failed." >&2
    print_service_diagnostics "$BACKEND_SERVICE"
    exit 1
  fi
  log "Authenticated canary smoke OK"
else
  log "Authenticated canary disabled (ENABLE_AUTH_CANARY=${ENABLE_AUTH_CANARY}); skipping."
fi

DEPLOY_STAGE="backup_restore_drill"
if [[ "${ENABLE_BACKUP_RESTORE_DRILL}" == "1" ]]; then
  log "Backup restore drill"
  DRILL_CMD=(
    python3
    "${APP_DIR}/scripts/deploy_backup_restore_drill.py"
    --app-dir "${APP_DIR}"
    --backup-dir "${RUNTIME_BACKUP_DIR}"
  )
  if [[ "${BACKUP_RESTORE_DRILL_SKIP_SQLITE_CHECK}" == "1" ]]; then
    DRILL_CMD+=(--skip-sqlite-check)
  fi
  if [[ "${BACKUP_RESTORE_DRILL_KEEP_RESTORE_DIR}" == "1" ]]; then
    DRILL_CMD+=(--keep-restore-dir)
  fi

  if ! "${DRILL_CMD[@]}"; then
    echo "[ERROR] Backup restore drill failed." >&2
    exit 1
  fi
  log "Backup restore drill OK"
else
  log "Backup restore drill disabled (ENABLE_BACKUP_RESTORE_DRILL=${ENABLE_BACKUP_RESTORE_DRILL}); skipping."
fi

DEPLOY_STAGE="whatsapp_reminder_activation"
activate_whatsapp_reminder_service

DEPLOY_STAGE="completed"
log "Deploy finished successfully (HEAD=${NEW_HASH})"
