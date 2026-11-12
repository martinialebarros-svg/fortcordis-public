#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://stage.fortcordis.com.br}"
API_BASE_URL="${API_BASE_URL:-${BASE_URL}/api/v1}"
ORIGIN="${ORIGIN:-${BASE_URL}}"
AUTH_EMAIL="${AUTH_EMAIL:-}"
AUTH_PASSWORD="${AUTH_PASSWORD:-}"
RUN_UNIT_TESTS="${RUN_UNIT_TESTS:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

FAILURES=0
WARNINGS=0

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

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

assert_header_equals() {
  local header_file="$1"
  local header_name="$2"
  local expected="$3"
  local actual
  actual="$(grep -i "^${header_name}:" "${header_file}" | tail -n1 | cut -d: -f2- | tr -d '\r' | xargs || true)"
  if [[ "${actual}" == "${expected}" ]]; then
    ok "${header_name}=${expected}"
  else
    fail "${header_name} esperado '${expected}', atual '${actual:-<vazio>}'"
  fi
}

assert_status_in() {
  local actual="$1"
  shift
  local allowed="$*"
  for expected in "$@"; do
    if [[ "${actual}" == "${expected}" ]]; then
      return 0
    fi
  done
  fail "HTTP ${actual} fora do esperado (${allowed})"
  return 1
}

printf 'Security regression smoke\n'
printf '=========================\n'
printf 'BASE_URL: %s\n' "${BASE_URL}"
printf 'API_BASE_URL: %s\n' "${API_BASE_URL}"
printf 'ORIGIN: %s\n\n' "${ORIGIN}"

api_headers_file="${TMP_DIR}/api_headers.txt"
api_status="$(
  curl -sS -o /dev/null -D "${api_headers_file}" -w "%{http_code}" \
    "${BASE_URL}/health" || true
)"
if [[ "${api_status}" == "200" ]]; then
  ok "GET /health retornou 200"
else
  fail "GET /health retornou ${api_status} (esperado 200)"
fi
assert_header_equals "${api_headers_file}" "X-Frame-Options" "DENY"
assert_header_equals "${api_headers_file}" "X-Content-Type-Options" "nosniff"

csp_header="$(grep -i '^Content-Security-Policy:' "${api_headers_file}" | tail -n1 | cut -d: -f2- | tr -d '\r' | xargs || true)"
if [[ -n "${csp_header}" ]]; then
  ok "Content-Security-Policy presente no backend"
else
  fail "Content-Security-Policy ausente no backend"
fi

cors_headers_file="${TMP_DIR}/cors_headers.txt"
cors_status="$(
  curl -sS -o /dev/null -D "${cors_headers_file}" -w "%{http_code}" -X OPTIONS \
    -H "Origin: ${ORIGIN}" \
    -H "Access-Control-Request-Method: GET" \
    "${API_BASE_URL}/auth/me" || true
)"
assert_status_in "${cors_status}" 200 204 405
cors_allow_origin="$(grep -i '^Access-Control-Allow-Origin:' "${cors_headers_file}" | tail -n1 | cut -d: -f2- | tr -d '\r' | xargs || true)"
if [[ "${cors_allow_origin}" == "${ORIGIN}" ]]; then
  ok "CORS allow-origin coerente (${cors_allow_origin})"
else
  warn "CORS allow-origin atual '${cors_allow_origin:-<vazio>}' diferente de ORIGIN='${ORIGIN}'"
fi

unauth_status="$(curl -sS -o /dev/null -w "%{http_code}" "${API_BASE_URL}/auth/me" || true)"
if [[ "${unauth_status}" == "401" ]]; then
  ok "GET /auth/me sem credencial retorna 401"
else
  fail "GET /auth/me sem credencial retornou ${unauth_status} (esperado 401)"
fi

if [[ -n "${AUTH_EMAIL}" && -n "${AUTH_PASSWORD}" ]]; then
  login_headers_file="${TMP_DIR}/login_headers.txt"
  login_body_file="${TMP_DIR}/login_body.json"
  login_status="$(
    curl -sS -D "${login_headers_file}" -o "${login_body_file}" -w "%{http_code}" \
      -X POST "${API_BASE_URL}/auth/login" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      --data-urlencode "username=${AUTH_EMAIL}" \
      --data-urlencode "password=${AUTH_PASSWORD}" || true
  )"
  if [[ "${login_status}" == "200" ]]; then
    ok "POST /auth/login retornou 200"
  else
    fail "POST /auth/login retornou ${login_status} (esperado 200)"
  fi

  session_cookie_line="$(grep -i '^set-cookie: fortcordis_session=' "${login_headers_file}" | head -n1 || true)"
  csrf_cookie_line="$(grep -i '^set-cookie: fortcordis_csrf=' "${login_headers_file}" | head -n1 || true)"

  if [[ -n "${session_cookie_line}" ]]; then
    ok "Cookie fortcordis_session emitido"
    if echo "${session_cookie_line}" | grep -qi 'HttpOnly'; then
      ok "fortcordis_session com HttpOnly"
    else
      fail "fortcordis_session sem HttpOnly"
    fi
    if echo "${session_cookie_line}" | grep -qi 'Secure'; then
      ok "fortcordis_session com Secure"
    else
      fail "fortcordis_session sem Secure"
    fi
  else
    fail "Cookie fortcordis_session nao encontrado no login"
  fi

  if [[ -n "${csrf_cookie_line}" ]]; then
    ok "Cookie fortcordis_csrf emitido"
  else
    fail "Cookie fortcordis_csrf nao encontrado no login"
  fi

  session_cookie_value="$(echo "${session_cookie_line}" | sed -E 's/^[Ss]et-[Cc]ookie: fortcordis_session=([^;]+).*/\1/' || true)"
  csrf_cookie_value="$(echo "${csrf_cookie_line}" | sed -E 's/^[Ss]et-[Cc]ookie: fortcordis_csrf=([^;]+).*/\1/' || true)"
  cookie_header="fortcordis_session=${session_cookie_value}; fortcordis_csrf=${csrf_cookie_value}"

  logout_wo_csrf_status="$(
    curl -sS -o /dev/null -w "%{http_code}" \
      -X POST "${API_BASE_URL}/auth/logout" \
      -H "Cookie: ${cookie_header}" || true
  )"
  if [[ "${logout_wo_csrf_status}" == "403" ]]; then
    ok "POST /auth/logout sem header CSRF retorna 403"
  else
    fail "POST /auth/logout sem CSRF retornou ${logout_wo_csrf_status} (esperado 403)"
  fi

  logout_with_csrf_status="$(
    curl -sS -o /dev/null -w "%{http_code}" \
      -X POST "${API_BASE_URL}/auth/logout" \
      -H "Origin: ${ORIGIN}" \
      -H "x-csrf-token: ${csrf_cookie_value}" \
      -H "Cookie: ${cookie_header}" || true
  )"
  if [[ "${logout_with_csrf_status}" == "200" ]]; then
    ok "POST /auth/logout com CSRF valido retorna 200"
  else
    fail "POST /auth/logout com CSRF valido retornou ${logout_with_csrf_status} (esperado 200)"
  fi
else
  warn "AUTH_EMAIL/AUTH_PASSWORD nao informados; bloco de login/cookie/csrf foi pulado"
fi

if [[ "${RUN_UNIT_TESTS}" == "1" ]]; then
  if (
    cd backend
    "${PYTHON_BIN}" -m unittest \
      tests/test_csrf_protection.py \
      tests/test_websocket_auth.py \
      tests/test_security_headers.py
  ); then
    ok "Suite unit de seguranca (csrf/ws/headers) passou"
  else
    fail "Suite unit de seguranca (csrf/ws/headers) falhou"
  fi
else
  warn "RUN_UNIT_TESTS=0; suite unit de seguranca nao executada"
fi

printf '\nResultado: %s (%s falha(s), %s aviso(s))\n' \
  "$([[ "${FAILURES}" -eq 0 ]] && echo "PASS" || echo "FAIL")" \
  "${FAILURES}" "${WARNINGS}"

if [[ "${FAILURES}" -ne 0 ]]; then
  exit 1
fi
