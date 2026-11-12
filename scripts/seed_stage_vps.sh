#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKEND_DIR="${BACKEND_DIR:-${APP_DIR}/backend}"

EXPECTED_BRANCH="${EXPECTED_BRANCH:-stage}"
REQUIRE_STAGE_PATH="${REQUIRE_STAGE_PATH:-1}"
IMPORT_CUSTOM_PHRASES="${IMPORT_CUSTOM_PHRASES:-0}"

PYTHON_BIN="${PYTHON_BIN:-${BACKEND_DIR}/venv/bin/python}"
PIP_BIN="${PIP_BIN:-${BACKEND_DIR}/venv/bin/pip}"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

validate_stage_guardrails() {
  local app_dir_lc branch_name

  app_dir_lc="$(printf '%s' "${APP_DIR}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${REQUIRE_STAGE_PATH}" == "1" ]] && [[ "${app_dir_lc}" != *stage* ]]; then
    fail "Refusing to run: APP_DIR does not look like stage (${APP_DIR}). Set REQUIRE_STAGE_PATH=0 to bypass."
  fi

  if git -C "${APP_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    branch_name="$(git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD)"
    if [[ "${branch_name}" != "${EXPECTED_BRANCH}" ]]; then
      fail "Refusing to run: current branch is '${branch_name}', expected '${EXPECTED_BRANCH}'."
    fi
  else
    fail "APP_DIR is not a git worktree: ${APP_DIR}"
  fi
}

ensure_backend_runtime() {
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    log "Backend venv not found. Creating at ${BACKEND_DIR}/venv"
    python3 -m venv "${BACKEND_DIR}/venv"
    "${PIP_BIN}" install -U pip
    "${PIP_BIN}" install -r "${BACKEND_DIR}/requirements.txt"
  fi
}

require_cmd git
require_cmd python3

[[ -d "${BACKEND_DIR}" ]] || fail "Backend directory not found: ${BACKEND_DIR}"
[[ -f "${BACKEND_DIR}/.env" ]] || fail "Missing backend env file: ${BACKEND_DIR}/.env"
[[ -f "${BACKEND_DIR}/setup_database.py" ]] || fail "Missing setup_database.py in ${BACKEND_DIR}"

validate_stage_guardrails
ensure_backend_runtime

cd "${BACKEND_DIR}"

set -a
# shellcheck disable=SC1091
source "${BACKEND_DIR}/.env"
set +a

[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL is empty in ${BACKEND_DIR}/.env"
if [[ -n "${PROD_DATABASE_URL:-}" ]] && [[ "${DATABASE_URL}" == "${PROD_DATABASE_URL}" ]]; then
  fail "DATABASE_URL matches PROD_DATABASE_URL. Aborting."
fi

log "Running stage DB setup/migrations"
PYTHONPATH="${BACKEND_DIR}" "${PYTHON_BIN}" setup_database.py

log "Running synthetic seed baseline"
PYTHONPATH="${BACKEND_DIR}" "${PYTHON_BIN}" seed_data.py

if [[ "${IMPORT_CUSTOM_PHRASES}" == "1" ]] && [[ -f "${BACKEND_DIR}/frases_personalizadas.json" ]]; then
  log "Importing custom phrases from frases_personalizadas.json"
  PYTHONPATH="${BACKEND_DIR}" "${PYTHON_BIN}" import_frases_stage.py
fi

log "Running idempotent content seeders and final summary"
PYTHONPATH="${BACKEND_DIR}" "${PYTHON_BIN}" scripts/stage_seed.py

log "Stage seed finished"
