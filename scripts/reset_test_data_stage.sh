#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKEND_DIR="${BACKEND_DIR:-${APP_DIR}/backend}"

EXPECTED_BRANCH="${EXPECTED_BRANCH:-stage}"
REQUIRE_STAGE_PATH="${REQUIRE_STAGE_PATH:-1}"

PYTHON_BIN="${PYTHON_BIN:-${BACKEND_DIR}/venv/bin/python}"
PIP_BIN="${PIP_BIN:-${BACKEND_DIR}/venv/bin/pip}"

APPLY_MODE=0
PREFIX="TST-"
OLDER_THAN_DAYS=0

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

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/reset_test_data_stage.sh [--dry-run] [--apply] [--prefix TST-] [--older-than-days N]

Options:
  --dry-run           Show what would be deleted (default).
  --apply             Execute deletion.
  --prefix VALUE      Prefix marker for test records. Default: TST-
  --older-than-days N Only include prefixed rows older than N days (when created_at exists).
  -h, --help          Show this help.
USAGE
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY_MODE=1
      shift
      ;;
    --dry-run)
      APPLY_MODE=0
      shift
      ;;
    --prefix)
      [[ $# -ge 2 ]] || fail "Missing value for --prefix"
      PREFIX="$2"
      shift 2
      ;;
    --older-than-days)
      [[ $# -ge 2 ]] || fail "Missing value for --older-than-days"
      OLDER_THAN_DAYS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

if [[ -z "${PREFIX// }" ]]; then
  fail "--prefix cannot be empty"
fi
if ! [[ "${OLDER_THAN_DAYS}" =~ ^[0-9]+$ ]]; then
  fail "--older-than-days must be an integer >= 0"
fi

require_cmd git
require_cmd python3

[[ -d "${BACKEND_DIR}" ]] || fail "Backend directory not found: ${BACKEND_DIR}"
[[ -f "${BACKEND_DIR}/.env" ]] || fail "Missing backend env file: ${BACKEND_DIR}/.env"
[[ -f "${BACKEND_DIR}/scripts/reset_stage_test_data.py" ]] || fail "Missing backend/scripts/reset_stage_test_data.py"

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

RESET_CMD=(
  "${PYTHON_BIN}" scripts/reset_stage_test_data.py
  --prefix "${PREFIX}"
  --older-than-days "${OLDER_THAN_DAYS}"
)
if [[ "${APPLY_MODE}" == "1" ]]; then
  RESET_CMD+=(--apply)
fi

if [[ "${APPLY_MODE}" == "1" ]]; then
  log "Running APPLY mode (destructive) for prefix '${PREFIX}'"
else
  log "Running DRY-RUN mode for prefix '${PREFIX}'"
fi

PYTHONPATH="${BACKEND_DIR}" "${RESET_CMD[@]}"

log "Reset script finished"
