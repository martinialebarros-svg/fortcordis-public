#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

load_env_file() {
  local env_path="$1"

  if [[ ! -f "${env_path}" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]]; then
      continue
    fi

    if [[ "${line}" != *"="* ]]; then
      continue
    fi

    local key="${line%%=*}"
    local value="${line#*=}"

    key="$(echo "${key}" | xargs)"
    value="$(echo "${value}" | sed 's/\r$//')"

    if [[ -z "${key}" ]]; then
      continue
    fi

    if [[ -z "${!key:-}" ]]; then
      export "${key}=${value}"
    fi
  done < "${env_path}"
}

load_env_file "${PROJECT_ROOT}/.env"

BASE_URL="${BASE_URL:-http://localhost:3000}"
RUN_GRAPH_RETRY_TEST="${RUN_GRAPH_RETRY_TEST:-true}"
RUN_PERSIST_FAILURE_TEST="${RUN_PERSIST_FAILURE_TEST:-false}"
API_AUTH_BEARER_TOKEN="${API_AUTH_BEARER_TOKEN:-}"
WHATSAPP_INTERNAL_API_TOKEN="${WHATSAPP_INTERNAL_API_TOKEN:-}"

AUTH_HEADER_ARGS=()
if [[ -n "${API_AUTH_BEARER_TOKEN}" ]]; then
  AUTH_HEADER_ARGS+=( -H "Authorization: Bearer ${API_AUTH_BEARER_TOKEN}" )
fi
if [[ -n "${WHATSAPP_INTERNAL_API_TOKEN}" ]]; then
  AUTH_HEADER_ARGS+=( -H "X-WhatsApp-Internal-Token: ${WHATSAPP_INTERNAL_API_TOKEN}" )
fi

if [[ -z "${WHATSAPP_VERIFY_TOKEN:-}" ]]; then
  echo "Set WHATSAPP_VERIFY_TOKEN before running smoke tests."
  exit 1
fi

if [[ -z "${WHATSAPP_APP_SECRET:-}" ]]; then
  echo "Set WHATSAPP_APP_SECRET before running smoke tests."
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required."
  exit 1
fi

if ! command -v xxd >/dev/null 2>&1; then
  echo "xxd is required."
  exit 1
fi

DB_ASSERT_MODE="none"
HAS_DB_ASSERTS=false

if [[ -n "${DATABASE_URL:-}" ]]; then
  if command -v psql >/dev/null 2>&1; then
    DB_ASSERT_MODE="psql"
    HAS_DB_ASSERTS=true
  elif command -v node >/dev/null 2>&1; then
    DB_ASSERT_MODE="node"
    HAS_DB_ASSERTS=true
  fi
fi

if [[ "${HAS_DB_ASSERTS}" == "true" ]]; then
  echo "SQL-level assertions enabled via ${DB_ASSERT_MODE}."
else
  echo "DATABASE_URL is missing (or no SQL runner available). SQL-level assertions will be skipped."
fi

HTTP_BODY_FILE="$(mktemp)"
RENAMED_WEBHOOK_TABLE=false

cleanup() {
  if [[ "${RENAMED_WEBHOOK_TABLE}" == "true" ]] && [[ "${HAS_DB_ASSERTS}" == "true" ]]; then
    sql_exec "ALTER TABLE webhook_events__tmp_smoke_fail RENAME TO webhook_events;" >/dev/null 2>&1 || true
  fi

  rm -f "${HTTP_BODY_FILE}"
}
trap cleanup EXIT

assert_equals() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "${expected}" != "${actual}" ]]; then
    echo "Assertion failed: ${label}. Expected '${expected}', got '${actual}'."
    exit 1
  fi
}

trim_line() {
  echo "$1" | tr -d '\r\n'
}

sql_scalar() {
  local statement="$1"

  if [[ "${DB_ASSERT_MODE}" == "psql" ]]; then
    psql "${DATABASE_URL}" -Atqc "${statement}"
    return 0
  fi

  SQL_ASSERT_QUERY="${statement}" DATABASE_URL="${DATABASE_URL}" node - <<'NODE'
const { Client } = require("pg");

async function main() {
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();

  try {
    const result = await client.query(process.env.SQL_ASSERT_QUERY);
    const row = result.rows[0];
    if (!row) {
      process.stdout.write("");
      return;
    }

    const firstKey = Object.keys(row)[0];
    const value = row[firstKey];
    process.stdout.write(value === null || value === undefined ? "" : String(value));
  } finally {
    await client.end();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
}

sql_exec() {
  local statement="$1"

  if [[ "${DB_ASSERT_MODE}" == "psql" ]]; then
    psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -qc "${statement}"
    return 0
  fi

  SQL_ASSERT_QUERY="${statement}" DATABASE_URL="${DATABASE_URL}" node - <<'NODE'
const { Client } = require("pg");

async function main() {
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();

  try {
    await client.query(process.env.SQL_ASSERT_QUERY);
  } finally {
    await client.end();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
}

wait_for_sql_equals() {
  local statement="$1"
  local expected="$2"
  local timeout_seconds="$3"
  local label="$4"

  for ((second=1; second<=timeout_seconds; second+=1)); do
    local raw
    raw="$(sql_scalar "${statement}" || true)"
    local value
    value="$(trim_line "${raw}")"

    if [[ "${value}" == "${expected}" ]]; then
      return 0
    fi

    sleep 1
  done

  local final_value
  final_value="$(trim_line "$(sql_scalar "${statement}" || true)")"
  echo "Timed out waiting for SQL assertion '${label}'. Expected '${expected}', got '${final_value}'."
  exit 1
}

request_json_with_body() {
  local method="$1"
  local url="$2"
  local payload="${3:-}"
  local signature="${4:-}"

  local -a args
  args=( -sS -o "${HTTP_BODY_FILE}" -w "%{http_code}" -X "${method}" "${url}" )

  if [[ "${#AUTH_HEADER_ARGS[@]}" -gt 0 ]]; then
    args+=( "${AUTH_HEADER_ARGS[@]}" )
  fi

  if [[ -n "${payload}" ]]; then
    args+=( -H "Content-Type: application/json" -d "${payload}" )
  fi

  if [[ -n "${signature}" ]]; then
    args+=( -H "X-Hub-Signature-256: ${signature}" )
  fi

  curl "${args[@]}"
}

request_json_status_only() {
  local method="$1"
  local url="$2"
  local payload="${3:-}"
  local signature="${4:-}"

  local response_file
  response_file="$(mktemp)"
  local -a args
  args=( -sS -o "${response_file}" -w "%{http_code}" -X "${method}" "${url}" )

  if [[ "${#AUTH_HEADER_ARGS[@]}" -gt 0 ]]; then
    args+=( "${AUTH_HEADER_ARGS[@]}" )
  fi

  if [[ -n "${payload}" ]]; then
    args+=( -H "Content-Type: application/json" -d "${payload}" )
  fi

  if [[ -n "${signature}" ]]; then
    args+=( -H "X-Hub-Signature-256: ${signature}" )
  fi

  local status
  status="$(curl "${args[@]}")"
  rm -f "${response_file}"
  printf "%s" "${status}"
}

read_last_body() {
  cat "${HTTP_BODY_FILE}"
}

sign_payload() {
  local payload="$1"
  local sig
  sig="$(printf '%s' "${payload}" | openssl dgst -sha256 -hmac "${WHATSAPP_APP_SECRET}" -binary | xxd -p -c 256)"
  printf "sha256=%s" "${sig}"
}

post_signed_with_body() {
  local payload="$1"
  local signature
  signature="$(sign_payload "${payload}")"
  request_json_with_body POST "${BASE_URL}/webhook" "${payload}" "${signature}"
}

post_signed_status_only() {
  local payload="$1"
  local signature
  signature="$(sign_payload "${payload}")"
  request_json_status_only POST "${BASE_URL}/webhook" "${payload}" "${signature}"
}

RUN_ID="$(date +%s%N 2>/dev/null || date +%s)"
TEST_PHONE="5511${RUN_ID: -8}"
INBOUND_WAMID="wamid.smoke.${RUN_ID}.inbound"
STATUS_TIMESTAMP="${RUN_ID: -10}"

INBOUND_PAYLOAD="$(cat <<JSON
{"object":"whatsapp_business_account","entry":[{"id":"WABA_SMOKE","changes":[{"field":"messages","value":{"contacts":[{"wa_id":"${TEST_PHONE}","profile":{"name":"Smoke User ${RUN_ID}"}}],"messages":[{"from":"${TEST_PHONE}","id":"${INBOUND_WAMID}","timestamp":"${STATUS_TIMESTAMP}","type":"text","text":{"body":"smoke duplicate ${RUN_ID}"}}]}}]}]}
JSON
)"

echo "1) GET /webhook verification"
VERIFY_STATUS="$(curl -sS -o "${HTTP_BODY_FILE}" -w "%{http_code}" "${BASE_URL}/webhook?hub.mode=subscribe&hub.verify_token=${WHATSAPP_VERIFY_TOKEN}&hub.challenge=hello")"
assert_equals "200" "${VERIFY_STATUS}" "webhook verification status"
assert_equals "hello" "$(trim_line "$(read_last_body)")" "webhook verification challenge"


echo "2) POST /webhook with invalid signature returns 401"
INVALID_STATUS="$(request_json_with_body POST "${BASE_URL}/webhook" "${INBOUND_PAYLOAD}" "sha256=deadbeef")"
assert_equals "401" "${INVALID_STATUS}" "invalid signature status"


echo "3) Duplicate webhook payload is idempotent (HTTP 200 both times)"
STATUS_FIRST="$(post_signed_with_body "${INBOUND_PAYLOAD}")"
assert_equals "200" "${STATUS_FIRST}" "signed webhook first request status"
STATUS_SECOND="$(post_signed_with_body "${INBOUND_PAYLOAD}")"
assert_equals "200" "${STATUS_SECOND}" "signed webhook duplicate request status"

if [[ "${HAS_DB_ASSERTS}" == "true" ]]; then
  PAYLOAD_HASH="$(printf '%s' "${INBOUND_PAYLOAD}" | openssl dgst -sha256 | awk '{print $2}')"

  wait_for_sql_equals "SELECT COUNT(*) FROM webhook_events WHERE payload_hash = '${PAYLOAD_HASH}';" "1" 15 "single webhook_events row for duplicate payload"
  wait_for_sql_equals "SELECT COUNT(*) FROM messages WHERE wa_message_id = '${INBOUND_WAMID}';" "1" 15 "single messages row for duplicate wa_message_id"
fi


echo "4) Conversation upsert under concurrent webhook messages"
CONCURRENT_STATUS_FILES=()
for i in 1 2 3 4 5; do
  concurrent_wamid="wamid.smoke.${RUN_ID}.concurrent.${i}"
  concurrent_payload="$(cat <<JSON
{"object":"whatsapp_business_account","entry":[{"id":"WABA_SMOKE","changes":[{"field":"messages","value":{"contacts":[{"wa_id":"${TEST_PHONE}","profile":{"name":"Smoke User ${RUN_ID}"}}],"messages":[{"from":"${TEST_PHONE}","id":"${concurrent_wamid}","timestamp":"${STATUS_TIMESTAMP}","type":"text","text":{"body":"concurrent ${i}"}}]}}]}]}
JSON
)"

  status_file="$(mktemp)"
  CONCURRENT_STATUS_FILES+=("${status_file}")

  (
    code="$(post_signed_status_only "${concurrent_payload}")"
    printf "%s" "${code}" > "${status_file}"
  ) &
done

wait
for status_file in "${CONCURRENT_STATUS_FILES[@]}"; do
  code="$(cat "${status_file}")"
  rm -f "${status_file}"
  assert_equals "200" "${code}" "concurrent webhook status"
done

if [[ "${HAS_DB_ASSERTS}" == "true" ]]; then
  wait_for_sql_equals "SELECT COUNT(*) FROM conversations WHERE wa_phone_number = '${TEST_PHONE}';" "1" 20 "single conversation for concurrent upsert"
  wait_for_sql_equals "SELECT COUNT(*) FROM messages WHERE wa_message_id LIKE 'wamid.smoke.${RUN_ID}.concurrent.%';" "5" 20 "all concurrent messages inserted"
fi


echo "5) Status history updates message and inserts single event"
STATUS_PAYLOAD="$(cat <<JSON
{"object":"whatsapp_business_account","entry":[{"id":"WABA_SMOKE","changes":[{"field":"messages","value":{"statuses":[{"id":"${INBOUND_WAMID}","status":"delivered","timestamp":"${STATUS_TIMESTAMP}","recipient_id":"${TEST_PHONE}"}]}}]}]}
JSON
)"

STATUS_EVENT_FIRST="$(post_signed_with_body "${STATUS_PAYLOAD}")"
assert_equals "200" "${STATUS_EVENT_FIRST}" "status webhook first request"
STATUS_EVENT_DUPLICATE="$(post_signed_with_body "${STATUS_PAYLOAD}")"
assert_equals "200" "${STATUS_EVENT_DUPLICATE}" "status webhook duplicate request"

if [[ "${HAS_DB_ASSERTS}" == "true" ]]; then
  wait_for_sql_equals "SELECT status FROM messages WHERE wa_message_id = '${INBOUND_WAMID}' LIMIT 1;" "delivered" 20 "messages.status updated by status webhook"
  wait_for_sql_equals "SELECT COUNT(*) FROM message_status_events WHERE wa_message_id = '${INBOUND_WAMID}' AND status = 'delivered' AND provider_timestamp = ${STATUS_TIMESTAMP};" "1" 20 "single status history row after duplicate status webhook"
fi


echo "6) Agent claim/unclaim sanity check"
AGENT_RESPONSE="$(curl -sS -X POST "${BASE_URL}/agents" -H "Content-Type: application/json" -d "{\"name\":\"Agent Smoke\",\"email\":\"agent.smoke.${RUN_ID}@example.com\",\"role\":\"agent\"}")"
AGENT_ID="$(printf "%s" "${AGENT_RESPONSE}" | node -e "const fs=require('fs');const raw=fs.readFileSync(0,'utf8').trim();if(!raw){process.stdout.write('');process.exit(0);}const d=JSON.parse(raw);process.stdout.write(String(d.id ?? ''));" || true)"

CONVERSATIONS_RESPONSE="$(curl -sS -X GET "${BASE_URL}/conversations?phone=${TEST_PHONE}&limit=1&page=1")"
CONVERSATION_ID="$(printf "%s" "${CONVERSATIONS_RESPONSE}" | node -e "const fs=require('fs');const raw=fs.readFileSync(0,'utf8').trim();if(!raw){process.stdout.write('');process.exit(0);}const d=JSON.parse(raw);const id=d?.data?.[0]?.id;process.stdout.write(id ? String(id) : '');" || true)"

if [[ -n "${AGENT_ID}" && -n "${CONVERSATION_ID}" ]]; then
  CLAIM_STATUS="$(request_json_with_body POST "${BASE_URL}/conversations/${CONVERSATION_ID}/claim" "{\"agent_id\":${AGENT_ID}}")"
  assert_equals "200" "${CLAIM_STATUS}" "claim status"

  UNCLAIM_STATUS="$(request_json_with_body POST "${BASE_URL}/conversations/${CONVERSATION_ID}/unclaim" "{\"agent_id\":${AGENT_ID}}")"
  assert_equals "200" "${UNCLAIM_STATUS}" "unclaim status"
else
  echo "Skipping claim/unclaim assertion because conversation_id or agent_id is missing."
fi


echo "7) Optional webhook persistence failure test (expect 503)"
if [[ "${RUN_PERSIST_FAILURE_TEST}" == "true" ]]; then
  if [[ "${HAS_DB_ASSERTS}" != "true" ]]; then
    echo "Skipping persistence failure test because DATABASE_URL or DB assertion runner is not available."
  else
    sql_exec "ALTER TABLE webhook_events RENAME TO webhook_events__tmp_smoke_fail;" >/dev/null
    RENAMED_WEBHOOK_TABLE=true

    FAIL_PAYLOAD="$(cat <<JSON
{"object":"whatsapp_business_account","entry":[{"id":"WABA_SMOKE","changes":[{"field":"messages","value":{"messages":[{"from":"${TEST_PHONE}","id":"wamid.smoke.${RUN_ID}.persist.failure","timestamp":"${STATUS_TIMESTAMP}","type":"text","text":{"body":"persist fail"}}]}}]}]}
JSON
)"

    FAIL_STATUS="$(post_signed_with_body "${FAIL_PAYLOAD}")"
    assert_equals "503" "${FAIL_STATUS}" "webhook persistence failure status"

    sql_exec "ALTER TABLE webhook_events__tmp_smoke_fail RENAME TO webhook_events;" >/dev/null
    RENAMED_WEBHOOK_TABLE=false
  fi
else
  echo "Skipping persistence failure test. Set RUN_PERSIST_FAILURE_TEST=true to run it."
fi


echo "8) Optional Graph API retry behavior test"
if [[ "${RUN_GRAPH_RETRY_TEST}" == "true" ]]; then
  npm run test:whatsapp-retry
else
  echo "Skipping Graph API retry behavior test."
fi


echo "Smoke tests finished successfully."
