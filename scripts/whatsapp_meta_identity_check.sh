#!/usr/bin/env bash
set -euo pipefail

WHATSAPP_ACCESS_TOKEN="${WHATSAPP_ACCESS_TOKEN:-}"
PHONE_NUMBER_ID="${PHONE_NUMBER_ID:-}"
META_APP_ID="${META_APP_ID:-}"
WHATSAPP_BUSINESS_ACCOUNT_ID="${WHATSAPP_BUSINESS_ACCOUNT_ID:-}"
WHATSAPP_GRAPH_API_VERSION="${WHATSAPP_GRAPH_API_VERSION:-v26.0}"
WHATSAPP_GRAPH_API_BASE_URL="${WHATSAPP_GRAPH_API_BASE_URL:-https://graph.facebook.com}"
WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER="${WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER:-0}"
WHATSAPP_REQUIRE_SUBSCRIBED_APP="${WHATSAPP_REQUIRE_SUBSCRIBED_APP:-1}"

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

for required_command in curl jq; do
  command -v "${required_command}" >/dev/null 2>&1 || fail "Comando obrigatorio ausente: ${required_command}"
done

if [[ "${WHATSAPP_ACCESS_TOKEN}" != EAA* || "${#WHATSAPP_ACCESS_TOKEN}" -lt 64 ]]; then
  fail "WHATSAPP_ACCESS_TOKEN ausente ou fora do formato esperado"
fi
for public_id_name in PHONE_NUMBER_ID META_APP_ID WHATSAPP_BUSINESS_ACCOUNT_ID; do
  public_id_value="${!public_id_name:-}"
  if [[ ! "${public_id_value}" =~ ^[0-9]{10,32}$ ]]; then
    fail "${public_id_name} ausente ou fora do formato esperado"
  fi
done
if [[ ! "${WHATSAPP_GRAPH_API_VERSION}" =~ ^v[0-9]+\.[0-9]+$ ]]; then
  fail "WHATSAPP_GRAPH_API_VERSION fora do formato esperado"
fi
if [[ "${WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER}" != "0" && \
      "${WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER}" != "1" ]]; then
  fail "WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER deve ser 0 ou 1"
fi
if [[ "${WHATSAPP_REQUIRE_SUBSCRIBED_APP}" != "0" && \
      "${WHATSAPP_REQUIRE_SUBSCRIBED_APP}" != "1" ]]; then
  fail "WHATSAPP_REQUIRE_SUBSCRIBED_APP deve ser 0 ou 1"
fi

graph_get() {
  local resource="$1"
  local fields="${2:-}"
  local url="${WHATSAPP_GRAPH_API_BASE_URL%/}/${WHATSAPP_GRAPH_API_VERSION}/${resource}"
  local curl_args=(
    --silent
    --show-error
    --connect-timeout 8
    --max-time 20
  )

  if [[ -n "${fields}" ]]; then
    curl_args+=(--get --data-urlencode "fields=${fields}")
  fi

  printf 'header = "Authorization: Bearer %s"\n' "${WHATSAPP_ACCESS_TOKEN}" \
    | curl --config - "${curl_args[@]}" "${url}"
}

assert_graph_success() {
  local response="$1"
  local label="$2"
  local graph_code

  if jq -e 'type == "object" and (.error == null)' <<<"${response}" >/dev/null 2>&1; then
    return 0
  fi

  graph_code="$(jq -r '.error.code // "desconhecido"' <<<"${response}" 2>/dev/null || printf 'resposta-invalida')"
  fail "${label} falhou na Graph API (codigo ${graph_code})"
}

phone_response="$(graph_get "${PHONE_NUMBER_ID}" "id,code_verification_status,platform_type")" \
  || fail "Consulta da identidade do numero falhou"
assert_graph_success "${phone_response}" "Consulta da identidade do numero"
if ! jq -e --arg expected "${PHONE_NUMBER_ID}" '.id == $expected' <<<"${phone_response}" >/dev/null; then
  fail "Token nao resolve o PHONE_NUMBER_ID esperado"
fi
phone_verification_status="$(jq -r '.code_verification_status // "VERIFIED"' <<<"${phone_response}")"
case "${phone_verification_status}" in
  VERIFIED)
    printf '[OK] Token resolve o numero verificado na Meta\n'
    ;;
  NOT_VERIFIED)
    if [[ "${WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER}" != "1" ]]; then
      fail "Numero nao verificado na Meta; modo de numero de teste nao autorizado"
    fi
    printf '[OK] Numero de teste Meta explicitamente autorizado para stage\n'
    ;;
  *)
    fail "Status de verificacao do numero nao aceito"
    ;;
esac
if ! jq -e '(.platform_type // "CLOUD_API") == "CLOUD_API"' <<<"${phone_response}" >/dev/null; then
  fail "Numero de stage nao esta registrado na Cloud API"
fi
printf '[OK] Token resolve o numero de stage na Cloud API\n'

waba_phones_response="$(graph_get "${WHATSAPP_BUSINESS_ACCOUNT_ID}/phone_numbers" "id")" \
  || fail "Consulta dos numeros da WABA falhou"
assert_graph_success "${waba_phones_response}" "Consulta dos numeros da WABA"
if ! jq -e --arg expected "${PHONE_NUMBER_ID}" 'any((.data // [])[]; .id == $expected)' \
  <<<"${waba_phones_response}" >/dev/null; then
  fail "PHONE_NUMBER_ID nao pertence a WHATSAPP_BUSINESS_ACCOUNT_ID informada"
fi
printf '[OK] Numero de stage pertence a WABA esperada\n'

subscribed_apps_response="$(graph_get "${WHATSAPP_BUSINESS_ACCOUNT_ID}/subscribed_apps")" \
  || fail "Consulta dos apps assinantes da WABA falhou"
assert_graph_success "${subscribed_apps_response}" "Consulta dos apps assinantes da WABA"
if jq -e --arg expected "${META_APP_ID}" \
  'any((.data // [])[]; ((.id // "") | tostring) == $expected or ((.whatsapp_business_api_data.id // "") | tostring) == $expected)' \
  <<<"${subscribed_apps_response}" >/dev/null; then
  printf '[OK] App de stage esta assinado na WABA esperada\n'
elif [[ "${WHATSAPP_REQUIRE_SUBSCRIBED_APP}" == "1" ]]; then
  fail "META_APP_ID nao esta assinado na WABA informada"
else
  printf '[WARN] Assinatura do app na WABA pendente para o corte do callback\n'
fi

unset phone_response phone_verification_status waba_phones_response subscribed_apps_response \
  WHATSAPP_ACCESS_TOKEN
printf 'WhatsApp Meta identity check passed.\n'
