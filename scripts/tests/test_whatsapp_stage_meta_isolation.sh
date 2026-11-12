#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PREFLIGHT="${REPO_ROOT}/scripts/whatsapp_stage_preflight.sh"
FIXTURE_ROOT="$(mktemp -d)"
ACCESS_TOKEN="EAA$(printf 'a%.0s' {1..64})"
APP_SECRET="$(printf '0%.0s' {1..32})"
VERIFY_TOKEN="stage_verify_token_fixture"
INTERNAL_TOKEN="internal_token_fixture_123456"

cleanup() {
  rm -rf "${FIXTURE_ROOT}"
}
trap cleanup EXIT

write_fixture() {
  local fixture_dir="$1"
  local phone_number_id="$2"
  local meta_app_id="$3"
  local business_account_id="$4"

  mkdir -p "${fixture_dir}/whatsapp-stage-backend" "${fixture_dir}/backend"
  cat > "${fixture_dir}/whatsapp-stage-backend/.env" <<EOF
WHATSAPP_ACCESS_TOKEN=${ACCESS_TOKEN}
PHONE_NUMBER_ID=${phone_number_id}
WHATSAPP_VERIFY_TOKEN=${VERIFY_TOKEN}
WHATSAPP_APP_SECRET=${APP_SECRET}
WHATSAPP_GRAPH_API_VERSION=v26.0
META_APP_ID=${meta_app_id}
WHATSAPP_BUSINESS_ACCOUNT_ID=${business_account_id}
WHATSAPP_RESERVATION_TEMPLATE_NAME=reserva_de_agendamento
WHATSAPP_RESERVATION_TEMPLATE_LANGUAGE=pt_BR
API_BACKEND_URL=http://127.0.0.1:8001
WHATSAPP_API_AUTH_ENABLED=true
WEBHOOK_ALLOW_UNSIGNED=false
NODE_ENV=production
WHATSAPP_ALLOWED_PAPEIS=admin,recepcao,veterinario,cardiologista
WHATSAPP_WRITE_ALLOWED_PAPEIS=admin,recepcao,veterinario,cardiologista
WHATSAPP_INTERNAL_API_TOKEN=${INTERNAL_TOKEN}
EOF
  cat > "${fixture_dir}/backend/.env" <<EOF
WHATSAPP_AGENDA_ENABLED=true
WHATSAPP_AGENDA_INTERNAL_TOKEN=${INTERNAL_TOKEN}
EOF
}

run_preflight() {
  local fixture_dir="$1"
  shift
  APP_DIR="${fixture_dir}" \
    SKIP_SERVICE_CHECKS=1 \
    SKIP_HTTP_CHECKS=1 \
    SKIP_META_GRAPH_CHECKS=1 \
    RUN_SMOKE=0 \
    "$@" \
    bash "${PREFLIGHT}"
}

assert_not_exposed() {
  local output="$1"
  for sensitive_value in "${ACCESS_TOKEN}" "${APP_SECRET}" "${VERIFY_TOKEN}" "${INTERNAL_TOKEN}"; do
    if grep -Fq "${sensitive_value}" <<<"${output}"; then
      echo "Sensitive fixture value was exposed by preflight output." >&2
      exit 1
    fi
  done
}

isolated_fixture="${FIXTURE_ROOT}/isolated"
write_fixture "${isolated_fixture}" "223456789012345" "323456789012345" "423456789012345"
isolated_output="$(
  run_preflight "${isolated_fixture}" \
    env \
    EXPECTED_PHONE_NUMBER_ID=223456789012345 \
    EXPECTED_META_APP_ID=323456789012345 \
    EXPECTED_BUSINESS_ACCOUNT_ID=423456789012345
)"
grep -Fq "Identidade Meta de stage isolada da producao" <<<"${isolated_output}"
grep -Fq "Resultado: PASS" <<<"${isolated_output}"
assert_not_exposed "${isolated_output}"

production_fixture="${FIXTURE_ROOT}/production"
write_fixture "${production_fixture}" "1279142515283484" "975334532125008" "1369494994627980"
if production_output="$(run_preflight "${production_fixture}" env 2>&1)"; then
  echo "Preflight accepted the production Meta identity in stage." >&2
  exit 1
fi
grep -Fq "PHONE_NUMBER_ID de stage reutiliza o numero de producao" <<<"${production_output}"
grep -Fq "META_APP_ID de stage reutiliza o app de producao" <<<"${production_output}"
grep -Fq "WHATSAPP_BUSINESS_ACCOUNT_ID de stage reutiliza a WABA de producao" <<<"${production_output}"
grep -Fq "Resultado: FAIL" <<<"${production_output}"
assert_not_exposed "${production_output}"

mismatch_fixture="${FIXTURE_ROOT}/mismatch"
write_fixture "${mismatch_fixture}" "223456789012345" "323456789012345" "423456789012345"
if mismatch_output="$(
  run_preflight "${mismatch_fixture}" \
    env \
    EXPECTED_PHONE_NUMBER_ID=523456789012345 \
    EXPECTED_META_APP_ID=323456789012345 \
    EXPECTED_BUSINESS_ACCOUNT_ID=423456789012345 2>&1
)"; then
  echo "Preflight accepted a stage identity that differs from the expected values." >&2
  exit 1
fi
grep -Fq "PHONE_NUMBER_ID nao corresponde a identidade esperada de stage" <<<"${mismatch_output}"
grep -Fq "Resultado: FAIL" <<<"${mismatch_output}"
assert_not_exposed "${mismatch_output}"

if grep -Fq "WHATSAPP_META_SOURCE_ENV_FILE=/var/www/fortcordis-stage/whatsapp-stage-backend/.env" \
  "${REPO_ROOT}/.github/workflows/deploy.yml"; then
  echo "Production workflow still sources the WhatsApp identity from stage." >&2
  exit 1
fi

# A reconstrucao do nono digito existe para o numero de TESTE da Meta, cuja
# lista de permitidos guarda o numero com o 9. Producao entrega na forma de 12
# digitos - medido em 2026-08-24: 96 saidas sent/delivered/read contra 1 falha.
# Ligar a flag em producao trocaria um formato comprovado por um nao testado.
if grep -q "WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT" \
  "${REPO_ROOT}/.github/workflows/deploy.yml"; then
  echo "Production workflow must not force the BR mobile ninth digit." >&2
  exit 1
fi

# E stage precisa continuar ligando: sem isso o envio volta a bater em
# OAuthException/131030 contra o numero de teste.
grep -Fq 'upsert_env WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT "true"' \
  "${REPO_ROOT}/.github/workflows/deploy-stage.yml"

for stage_variable in \
  WHATSAPP_PHONE_NUMBER_ID_STAGE \
  WHATSAPP_META_APP_ID_STAGE \
  WHATSAPP_BUSINESS_ACCOUNT_ID_STAGE; do
  grep -Fq "vars.${stage_variable}" "${REPO_ROOT}/.github/workflows/deploy-stage.yml"
done

grep -Fq 'WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION="1"' \
  "${REPO_ROOT}/scripts/deploy_stage_vps.sh"

stage_workflow="${REPO_ROOT}/.github/workflows/deploy-stage.yml"
grep -Fq 'git archive --format=tar "$DEPLOY_SHA"' "${stage_workflow}"
grep -Fq 'bash "$deploy_scripts_dir/scripts/deploy_stage_vps.sh"' "${stage_workflow}"
if grep -Fq 'BRANCH="$BRANCH" bash scripts/deploy_stage_vps.sh' "${stage_workflow}"; then
  echo "Stage workflow can still start the stale deploy script from the VPS checkout." >&2
  exit 1
fi

fake_bin="${FIXTURE_ROOT}/fake-bin"
mkdir -p "${fake_bin}"
cat > "${fake_bin}/curl" <<'FAKE_CURL'
#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
url="${*: -1}"
case "${url}" in
  */223456789012345)
    if [[ "${FAKE_GRAPH_MISMATCH:-0}" == "1" ]]; then
      printf '%s\n' '{"id":"999999999999999","code_verification_status":"VERIFIED","platform_type":"CLOUD_API"}'
    elif [[ "${FAKE_GRAPH_UNVERIFIED:-0}" == "1" ]]; then
      printf '%s\n' '{"id":"223456789012345","code_verification_status":"NOT_VERIFIED","platform_type":"CLOUD_API"}'
    else
      printf '%s\n' '{"id":"223456789012345","code_verification_status":"VERIFIED","platform_type":"CLOUD_API"}'
    fi
    ;;
  */423456789012345/phone_numbers)
    printf '%s\n' '{"data":[{"id":"223456789012345"}]}'
    ;;
  */423456789012345/subscribed_apps)
    if [[ "${FAKE_GRAPH_UNSUBSCRIBED:-0}" == "1" ]]; then
      printf '%s\n' '{"data":[]}'
    else
      printf '%s\n' '{"data":[{"whatsapp_business_api_data":{"id":"323456789012345"}}]}'
    fi
    ;;
  *)
    printf '%s\n' '{"error":{"code":100}}'
    ;;
esac
FAKE_CURL
chmod 700 "${fake_bin}/curl"

graph_output="$(
  PATH="${fake_bin}:${PATH}" \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh"
)"
grep -Fq "WhatsApp Meta identity check passed" <<<"${graph_output}"
assert_not_exposed "${graph_output}"

if graph_unverified_default_output="$(
  PATH="${fake_bin}:${PATH}" \
    FAKE_GRAPH_UNVERIFIED=1 \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh" 2>&1
)"; then
  echo "Graph identity check accepted an unverified number without test mode." >&2
  exit 1
fi
grep -Fq "modo de numero de teste nao autorizado" <<<"${graph_unverified_default_output}"
assert_not_exposed "${graph_unverified_default_output}"

graph_unverified_test_output="$(
  PATH="${fake_bin}:${PATH}" \
    FAKE_GRAPH_UNVERIFIED=1 \
    WHATSAPP_ALLOW_UNVERIFIED_TEST_NUMBER=1 \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh"
)"
grep -Fq "Numero de teste Meta explicitamente autorizado para stage" \
  <<<"${graph_unverified_test_output}"
grep -Fq "WhatsApp Meta identity check passed" <<<"${graph_unverified_test_output}"
assert_not_exposed "${graph_unverified_test_output}"

if graph_unsubscribed_default_output="$(
  PATH="${fake_bin}:${PATH}" \
    FAKE_GRAPH_UNSUBSCRIBED=1 \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh" 2>&1
)"; then
  echo "Graph identity check accepted an unsubscribed app by default." >&2
  exit 1
fi
grep -Fq "META_APP_ID nao esta assinado" <<<"${graph_unsubscribed_default_output}"
assert_not_exposed "${graph_unsubscribed_default_output}"

graph_unsubscribed_precutover_output="$(
  PATH="${fake_bin}:${PATH}" \
    FAKE_GRAPH_UNSUBSCRIBED=1 \
    WHATSAPP_REQUIRE_SUBSCRIBED_APP=0 \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh"
)"
grep -Fq "Assinatura do app na WABA pendente para o corte do callback" \
  <<<"${graph_unsubscribed_precutover_output}"
grep -Fq "WhatsApp Meta identity check passed" <<<"${graph_unsubscribed_precutover_output}"
assert_not_exposed "${graph_unsubscribed_precutover_output}"

if graph_mismatch_output="$(
  PATH="${fake_bin}:${PATH}" \
    FAKE_GRAPH_MISMATCH=1 \
    WHATSAPP_ACCESS_TOKEN="${ACCESS_TOKEN}" \
    PHONE_NUMBER_ID=223456789012345 \
    META_APP_ID=323456789012345 \
    WHATSAPP_BUSINESS_ACCOUNT_ID=423456789012345 \
    WHATSAPP_GRAPH_API_VERSION=v26.0 \
    bash "${REPO_ROOT}/scripts/whatsapp_meta_identity_check.sh" 2>&1
)"; then
  echo "Graph identity check accepted a mismatched phone identity." >&2
  exit 1
fi
grep -Fq "Token nao resolve o PHONE_NUMBER_ID esperado" <<<"${graph_mismatch_output}"
assert_not_exposed "${graph_mismatch_output}"

bash "${REPO_ROOT}/scripts/tests/test_stage_smoke_opt_in.sh"
bash "${REPO_ROOT}/scripts/tests/test_stage_meta_disabled_runtime.sh"

echo "WhatsApp stage Meta isolation tests passed."
