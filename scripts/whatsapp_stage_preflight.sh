#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/var/www/fortcordis-stage}"
WHATSAPP_ENV_FILE="${WHATSAPP_ENV_FILE:-${APP_DIR}/whatsapp-stage-backend/.env}"
CORE_ENV_FILE="${CORE_ENV_FILE:-${APP_DIR}/backend/.env}"
WHATSAPP_BACKEND_DIR="${WHATSAPP_BACKEND_DIR:-${APP_DIR}/whatsapp-stage-backend}"
WHATSAPP_BACKEND_PORT="${WHATSAPP_BACKEND_PORT:-3010}"
CORE_BACKEND_PORT="${CORE_BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
WHATSAPP_SERVICE="${WHATSAPP_SERVICE:-fortcordis-stage-whatsapp-backend}"
CORE_SERVICE="${CORE_SERVICE:-fortcordis-stage-backend}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-fortcordis-stage-frontend}"
RUN_SMOKE="${RUN_SMOKE:-0}"
SKIP_SERVICE_CHECKS="${SKIP_SERVICE_CHECKS:-0}"
SKIP_HTTP_CHECKS="${SKIP_HTTP_CHECKS:-0}"
SKIP_META_GRAPH_CHECKS="${SKIP_META_GRAPH_CHECKS:-0}"
RECOMMENDED_ALLOWED_ROLES="${RECOMMENDED_ALLOWED_ROLES:-admin,recepcao,veterinario,cardiologista}"
RECOMMENDED_WRITE_ROLES="${RECOMMENDED_WRITE_ROLES:-${RECOMMENDED_ALLOWED_ROLES}}"
EXPECTED_PHONE_NUMBER_ID="${EXPECTED_PHONE_NUMBER_ID:-}"
EXPECTED_META_APP_ID="${EXPECTED_META_APP_ID:-}"
EXPECTED_BUSINESS_ACCOUNT_ID="${EXPECTED_BUSINESS_ACCOUNT_ID:-}"
REQUIRE_STAGE_META_ISOLATION="${REQUIRE_STAGE_META_ISOLATION:-1}"
PRODUCTION_PHONE_NUMBER_ID="1279142515283484"
PRODUCTION_META_APP_ID="975334532125008"
PRODUCTION_BUSINESS_ACCOUNT_ID="1369494994627980"

FAILURES=0
WARNINGS=0

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf '[FAIL] %s\n' "$1"
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

is_placeholder_value() {
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

assert_required_key_present() {
  local key="$1"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if [[ -z "$value" ]]; then
    fail "Variavel obrigatoria ausente ou vazia em ${WHATSAPP_ENV_FILE}: ${key}"
    return
  fi

  ok "Variavel presente: ${key}"
}

assert_required_key_non_placeholder() {
  local key="$1"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if [[ -z "$value" ]]; then
    fail "Variavel obrigatoria ausente ou vazia em ${WHATSAPP_ENV_FILE}: ${key}"
    return
  fi

  if is_placeholder_value "$value"; then
    fail "Variavel ${key} ainda esta com placeholder"
    return
  fi

  ok "Variavel configurada com valor real: ${key}"
}

assert_env_equals() {
  local key="$1"
  local expected="$2"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if [[ "$value" != "$expected" ]]; then
    fail "Variavel ${key} esperada '${expected}', atual '${value:-<vazio>}'"
    return
  fi

  ok "Variavel ${key} = ${expected}"
}

assert_secret_format() {
  local key="$1"
  local kind="$2"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if is_placeholder_value "$value"; then
    fail "Variavel ${key} ausente ou ainda esta com placeholder"
    return
  fi

  case "$kind" in
    access_token)
      if [[ "$value" != EAA* || "${#value}" -lt 64 ]]; then
        fail "Variavel ${key} fora do formato esperado"
        return
      fi
      ;;
    app_secret)
      if [[ ! "$value" =~ ^[[:xdigit:]]{32}$ ]]; then
        fail "Variavel ${key} fora do formato esperado"
        return
      fi
      ;;
    verify_token)
      if [[ "${#value}" -lt 16 ]]; then
        fail "Variavel ${key} deve ter pelo menos 16 caracteres"
        return
      fi
      ;;
    *)
      fail "Tipo de validacao desconhecido para ${key}"
      return
      ;;
  esac

  ok "Formato valido sem exposicao do segredo: ${key}"
}

assert_public_meta_id() {
  local key="$1"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if is_placeholder_value "$value" || [[ ! "$value" =~ ^[0-9]{10,32}$ ]]; then
    fail "Variavel ${key} ausente, placeholder ou fora do formato esperado"
    return
  fi

  ok "Identificador publico Meta valido: ${key}"
}

assert_expected_meta_id() {
  local key="$1"
  local expected="$2"
  local value

  if [[ -z "$expected" ]]; then
    return
  fi

  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"
  if [[ "$value" != "$expected" ]]; then
    fail "Variavel ${key} nao corresponde a identidade esperada de stage"
    return
  fi

  ok "Variavel ${key} corresponde a identidade esperada de stage"
}

assert_stage_identity_isolated() {
  local phone_number_id meta_app_id business_account_id

  if [[ "$REQUIRE_STAGE_META_ISOLATION" != "0" && "$REQUIRE_STAGE_META_ISOLATION" != "1" ]]; then
    fail "REQUIRE_STAGE_META_ISOLATION deve ser 0 ou 1"
    return
  fi
  if [[ "$REQUIRE_STAGE_META_ISOLATION" != "1" ]]; then
    warn "Isolamento da identidade Meta de stage desabilitado explicitamente"
    return
  fi

  phone_number_id="$(read_env_file_value "$WHATSAPP_ENV_FILE" "PHONE_NUMBER_ID" "")"
  meta_app_id="$(read_env_file_value "$WHATSAPP_ENV_FILE" "META_APP_ID" "")"
  business_account_id="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_BUSINESS_ACCOUNT_ID" "")"

  if is_placeholder_value "$phone_number_id" || [[ ! "$phone_number_id" =~ ^[0-9]{10,32}$ ]] || \
     is_placeholder_value "$meta_app_id" || [[ ! "$meta_app_id" =~ ^[0-9]{10,32}$ ]] || \
     is_placeholder_value "$business_account_id" || [[ ! "$business_account_id" =~ ^[0-9]{10,32}$ ]]; then
    return
  fi

  if [[ "$phone_number_id" == "$PRODUCTION_PHONE_NUMBER_ID" ]]; then
    fail "PHONE_NUMBER_ID de stage reutiliza o numero de producao"
  fi
  if [[ "$meta_app_id" == "$PRODUCTION_META_APP_ID" ]]; then
    fail "META_APP_ID de stage reutiliza o app de producao"
  fi
  if [[ "$business_account_id" == "$PRODUCTION_BUSINESS_ACCOUNT_ID" ]]; then
    fail "WHATSAPP_BUSINESS_ACCOUNT_ID de stage reutiliza a WABA de producao"
  fi

  if [[ "$phone_number_id" != "$PRODUCTION_PHONE_NUMBER_ID" && \
        "$meta_app_id" != "$PRODUCTION_META_APP_ID" && \
        "$business_account_id" != "$PRODUCTION_BUSINESS_ACCOUNT_ID" ]]; then
    ok "Identidade Meta de stage isolada da producao"
  fi
}

assert_roles_value() {
  local key="$1"
  local expected="$2"
  local value
  value="$(read_env_file_value "$WHATSAPP_ENV_FILE" "$key" "")"

  if [[ -z "$value" ]]; then
    fail "Variavel ${key} vazia; defina papeis permitidos"
    return
  fi

  ok "Variavel ${key} preenchida"

  if [[ "$value" != "$expected" ]]; then
    warn "${key} diferente da recomendacao (${expected}). Atual: ${value}"
  else
    ok "${key} segue recomendacao atual"
  fi
}

check_service_active() {
  local service="$1"
  local status
  status="$(systemctl is-active "$service" 2>/dev/null || true)"
  if [[ "$status" == "active" ]]; then
    ok "Service ativo: ${service}"
    return
  fi

  fail "Service inativo (${status:-unknown}): ${service}"
}

check_http_ok() {
  local url="$1"
  if curl -fsS "$url" >/dev/null 2>&1; then
    ok "HTTP OK: ${url}"
    return
  fi

  fail "HTTP falhou: ${url}"
}

check_http_status_in_range() {
  local url="$1"
  local label="$2"
  local regex="$3"
  local status
  status="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || true)"

  if [[ "$status" =~ $regex ]]; then
    ok "${label}: HTTP ${status}"
    return
  fi

  fail "${label}: HTTP ${status} (fora do esperado)"
}

printf 'WhatsApp Stage Preflight\n'
printf '========================\n'
printf 'APP_DIR: %s\n' "$APP_DIR"
printf 'WHATSAPP_ENV_FILE: %s\n' "$WHATSAPP_ENV_FILE"
printf '\n'

if [[ ! -f "$WHATSAPP_ENV_FILE" ]]; then
  fail "Arquivo .env do WhatsApp stage nao encontrado: ${WHATSAPP_ENV_FILE}"
  printf '\nResultado: FAIL (%s falha(s), %s aviso(s))\n' "$FAILURES" "$WARNINGS"
  exit 1
fi
ok "Arquivo .env encontrado"

assert_required_key_non_placeholder "WHATSAPP_ACCESS_TOKEN"
assert_required_key_non_placeholder "PHONE_NUMBER_ID"
assert_required_key_non_placeholder "WHATSAPP_VERIFY_TOKEN"
assert_required_key_non_placeholder "WHATSAPP_APP_SECRET"
assert_required_key_non_placeholder "WHATSAPP_GRAPH_API_VERSION"
assert_required_key_non_placeholder "META_APP_ID"
assert_required_key_non_placeholder "WHATSAPP_BUSINESS_ACCOUNT_ID"
assert_required_key_non_placeholder "WHATSAPP_RESERVATION_TEMPLATE_NAME"
assert_required_key_non_placeholder "WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE"
assert_secret_format "WHATSAPP_ACCESS_TOKEN" "access_token"
assert_secret_format "WHATSAPP_APP_SECRET" "app_secret"
assert_secret_format "WHATSAPP_VERIFY_TOKEN" "verify_token"
assert_public_meta_id "PHONE_NUMBER_ID"
assert_public_meta_id "META_APP_ID"
assert_public_meta_id "WHATSAPP_BUSINESS_ACCOUNT_ID"
assert_expected_meta_id "PHONE_NUMBER_ID" "$EXPECTED_PHONE_NUMBER_ID"
assert_expected_meta_id "META_APP_ID" "$EXPECTED_META_APP_ID"
assert_expected_meta_id "WHATSAPP_BUSINESS_ACCOUNT_ID" "$EXPECTED_BUSINESS_ACCOUNT_ID"
assert_stage_identity_isolated
assert_env_equals "WHATSAPP_RESERVATION_TEMPLATE_NAME" "reserva_de_agendamento"
assert_env_equals "WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE" "pt_BR"

assert_required_key_present "API_BACKEND_URL"
assert_env_equals "WHATSAPP_API_AUTH_ENABLED" "true"
assert_env_equals "WEBHOOK_ALLOW_UNSIGNED" "false"
assert_env_equals "NODE_ENV" "production"

assert_roles_value "WHATSAPP_ALLOWED_PAPEIS" "$RECOMMENDED_ALLOWED_ROLES"
assert_roles_value "WHATSAPP_WRITE_ALLOWED_PAPEIS" "$RECOMMENDED_WRITE_ROLES"
assert_required_key_non_placeholder "WHATSAPP_INTERNAL_API_TOKEN"

WHATSAPP_VERIFY_TOKEN_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_VERIFY_TOKEN" "")"
WHATSAPP_APP_SECRET_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_APP_SECRET" "")"
WHATSAPP_INTERNAL_API_TOKEN_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_INTERNAL_API_TOKEN" "")"
WHATSAPP_ACCESS_TOKEN_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_ACCESS_TOKEN" "")"
PHONE_NUMBER_ID_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "PHONE_NUMBER_ID" "")"
META_APP_ID_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "META_APP_ID" "")"
BUSINESS_ACCOUNT_ID_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_BUSINESS_ACCOUNT_ID" "")"
GRAPH_API_VERSION_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_GRAPH_API_VERSION" "v26.0")"
ALLOW_UNVERIFIED_TEST_NUMBER_VALUE="$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER" "0")"

if [[ "$SKIP_META_GRAPH_CHECKS" != "1" ]]; then
  if WHATSAPP_ACCESS_TOKEN="$WHATSAPP_ACCESS_TOKEN_VALUE" \
    PHONE_NUMBER_ID="$PHONE_NUMBER_ID_VALUE" \
    META_APP_ID="$META_APP_ID_VALUE" \
    WHATSAPP_BUSINESS_ACCOUNT_ID="$BUSINESS_ACCOUNT_ID_VALUE" \
    WHATSAPP_GRAPH_API_VERSION="$GRAPH_API_VERSION_VALUE" \
    WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER="$ALLOW_UNVERIFIED_TEST_NUMBER_VALUE" \
    bash "${SCRIPT_DIR}/whatsapp_meta_identity_check.sh"; then
    ok "Identidade Meta de stage validada na Graph API"
  else
    fail "Identidade Meta de stage falhou na Graph API"
  fi
else
  warn "SKIP_META_GRAPH_CHECKS=1; checagem da identidade Meta foi pulada"
fi

if [[ ! -f "$CORE_ENV_FILE" ]]; then
  fail "Arquivo .env do backend principal nao encontrado: ${CORE_ENV_FILE}"
else
  CORE_WHATSAPP_TOKEN="$(read_env_file_value "$CORE_ENV_FILE" "WHATSAPP_AGENDA_INTERNAL_TOKEN" "")"
  CORE_WHATSAPP_ENABLED="$(read_env_file_value "$CORE_ENV_FILE" "WHATSAPP_AGENDA_ENABLED" "false")"
  if [[ "$CORE_WHATSAPP_ENABLED" != "true" ]]; then
    fail "WHATSAPP_AGENDA_ENABLED deve ser true no backend principal"
  elif [[ -z "$CORE_WHATSAPP_TOKEN" || "$CORE_WHATSAPP_TOKEN" != "$WHATSAPP_INTERNAL_API_TOKEN_VALUE" ]]; then
    fail "Token interno do backend principal nao corresponde ao servico WhatsApp"
  else
    ok "Backend principal e servico WhatsApp usam a mesma credencial interna"
  fi
fi

if [[ "$SKIP_SERVICE_CHECKS" != "1" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    check_service_active "$CORE_SERVICE"
    check_service_active "$FRONTEND_SERVICE"
    check_service_active "$WHATSAPP_SERVICE"
  else
    warn "systemctl nao encontrado; pulando checagem de services"
  fi
else
  warn "SKIP_SERVICE_CHECKS=1; checagem de services foi pulada"
fi

if [[ "$SKIP_HTTP_CHECKS" != "1" ]]; then
  check_http_ok "http://127.0.0.1:${CORE_BACKEND_PORT}/health"
  check_http_ok "http://127.0.0.1:${WHATSAPP_BACKEND_PORT}/health"
  check_http_status_in_range "http://127.0.0.1:${FRONTEND_PORT}/whatsapp" "Rewrite local /whatsapp" '^[23][0-9][0-9]$'

  if [[ "$(read_env_file_value "$WHATSAPP_ENV_FILE" "WHATSAPP_API_AUTH_ENABLED" "false")" == "true" ]]; then
    local_unauth_status="$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:${WHATSAPP_BACKEND_PORT}/agents" || true)"
    if [[ "$local_unauth_status" == "401" ]]; then
      ok "Auth gate sem token: HTTP 401 em /agents"
    else
      fail "Auth gate sem token esperado HTTP 401 em /agents, recebido ${local_unauth_status}"
    fi

    local_internal_status="$(
      curl -sS -o /dev/null -w "%{http_code}" \
        -H "X-WhatsApp-Internal-Token: ${WHATSAPP_INTERNAL_API_TOKEN_VALUE}" \
        "http://127.0.0.1:${WHATSAPP_BACKEND_PORT}/agents" || true
    )"
    if [[ "$local_internal_status" =~ ^2[0-9][0-9]$ ]]; then
      ok "Auth gate com token interno: HTTP ${local_internal_status} em /agents"
    else
      fail "Auth gate com token interno retornou HTTP ${local_internal_status} em /agents (esperado 2xx)"
    fi
  fi
else
  warn "SKIP_HTTP_CHECKS=1; checagem HTTP foi pulada"
fi

if [[ "$RUN_SMOKE" == "1" ]]; then
  if [[ ! -d "$WHATSAPP_BACKEND_DIR" ]]; then
    fail "Diretorio WhatsApp backend nao encontrado: ${WHATSAPP_BACKEND_DIR}"
  elif [[ ! -f "${WHATSAPP_BACKEND_DIR}/scripts/smoke-tests.sh" ]]; then
    fail "Script de smoke nao encontrado: ${WHATSAPP_BACKEND_DIR}/scripts/smoke-tests.sh"
  else
    ok "Executando smoke autenticado do WhatsApp stage"
    if (
      cd "$WHATSAPP_BACKEND_DIR"
      BASE_URL="http://127.0.0.1:${WHATSAPP_BACKEND_PORT}" \
        WHATSAPP_VERIFY_TOKEN="${WHATSAPP_VERIFY_TOKEN_VALUE}" \
        WHATSAPP_APP_SECRET="${WHATSAPP_APP_SECRET_VALUE}" \
        WHATSAPP_INTERNAL_API_TOKEN="${WHATSAPP_INTERNAL_API_TOKEN_VALUE}" \
        bash scripts/smoke-tests.sh
    ); then
      ok "Smoke autenticado concluido"
    else
      fail "Smoke autenticado falhou"
    fi
  fi
else
  warn "RUN_SMOKE=0; smoke funcional nao executado"
fi

printf '\nResultado: %s (%s falha(s), %s aviso(s))\n' \
  "$([[ "$FAILURES" -eq 0 ]] && echo "PASS" || echo "FAIL")" \
  "$FAILURES" "$WARNINGS"

if [[ "$FAILURES" -ne 0 ]]; then
  exit 1
fi
