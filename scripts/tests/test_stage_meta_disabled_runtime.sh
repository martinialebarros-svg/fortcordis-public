#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$FIXTURE_ROOT"' EXIT
mkdir -p "$FIXTURE_ROOT/bin" "$FIXTURE_ROOT/backend" "$FIXTURE_ROOT/frontend"
export STAGE_TEST_COMMAND_LOG="$FIXTURE_ROOT/commands"
export STAGE_TEST_FAKE_SYSTEMCTL="$FIXTURE_ROOT/bin/systemctl"
: > "$STAGE_TEST_COMMAND_LOG"

# sudo and systemctl are complete stubs. No host service or credential is read.
cat > "$FIXTURE_ROOT/bin/sudo" <<'SUDO'
#!/usr/bin/env bash
set -euo pipefail
printf 'sudo %s\n' "$*" >> "$STAGE_TEST_COMMAND_LOG"
[[ "${1:-}" == -n ]] || exit 90
shift
if [[ "${1:-}" == true ]]; then exit 0; fi
[[ "${1:-}" == "$STAGE_TEST_FAKE_SYSTEMCTL" ]] || exit 91
exec "$@"
SUDO
cat > "$FIXTURE_ROOT/bin/systemctl" <<'SYSTEMCTL'
#!/usr/bin/env bash
set -euo pipefail
printf 'systemctl %s\n' "$*" >> "$STAGE_TEST_COMMAND_LOG"
case "${1:-}" in
  show)
    [[ "${2:-}" == fortcordis-stage-whatsapp-backend && "${4:-}" == --value ]] || exit 92
    if [[ "${3:-}" == --property=LoadState ]]; then
      printf '%s\n' "${STAGE_TEST_LOAD_STATE:-loaded}"
      [[ "${STAGE_TEST_LOAD_STATE:-loaded}" != not-found ]] || exit 4
    elif [[ "${3:-}" == --property=ActiveState ]]; then
      [[ "${STAGE_TEST_STILL_ACTIVE:-0}" == 1 ]] && { printf 'active\n'; exit 0; }
      [[ "${STAGE_TEST_ACTIVE_UNRESOLVED:-0}" == 1 ]] && exit 1
      printf 'inactive\n'
    else
      exit 92
    fi
    ;;
  disable)
    [[ "${2:-}" == --now && "${3:-}" == fortcordis-stage-whatsapp-backend && $# == 3 ]] || exit 93
    [[ "${STAGE_TEST_DISABLE_FAIL:-0}" != 1 ]] || exit 1
    ;;
  is-active)
    [[ "${2:-}" == --quiet && "${3:-}" == fortcordis-stage-whatsapp-backend && $# == 3 ]] || exit 94
    [[ "${STAGE_TEST_STILL_ACTIVE:-0}" == 1 ]] && exit 0
    exit 3
    ;;
  *) exit 95 ;;
esac
SYSTEMCTL
cat > "$FIXTURE_ROOT/bin/npm" <<'NPM'
#!/usr/bin/env bash
set -euo pipefail
[[ "${API_BACKEND_URL:-}" == http://127.0.0.1:8001 ]]
[[ "${WHATSAPP_STAGE_BACKEND_URL:-}" == http://127.0.0.1:3010 ]]
printf 'npm %s stage-upstream-3010\n' "$*" >> "$STAGE_TEST_COMMAND_LOG"
NPM
chmod 700 "$FIXTURE_ROOT/bin/sudo" "$FIXTURE_ROOT/bin/systemctl" "$FIXTURE_ROOT/bin/npm"
export PATH="$FIXTURE_ROOT/bin:$PATH"

# Sourcing loads only functions and defaults; the actual deploy is never run.
source "$REPO_ROOT/scripts/deploy_prod_vps.sh"
SYSTEMCTL_BIN="$STAGE_TEST_FAKE_SYSTEMCTL"
configure_stage() {
  APP_DIR=/var/www/fortcordis-stage
  BRANCH=stage
  BACKEND_SERVICE=fortcordis-stage-backend
  BACKEND_DIR="$FIXTURE_ROOT/backend"
  WHATSAPP_STAGE_LIVE_META_ENABLED=0
  ENABLE_WHATSAPP_STAGE_BACKEND=0
  ENABLE_WHATSAPP_STAGE_SMOKE=0
  WHATSAPP_STAGE_BACKEND_SERVICE=fortcordis-stage-whatsapp-backend
  WHATSAPP_STAGE_BACKEND_PORT=3010
  WHATSAPP_STAGE_BACKEND_URL=http://127.0.0.1:3010
  WHATSAPP_STAGE_BACKEND_DIR=/var/www/fortcordis-stage/whatsapp-stage-backend
  WHATSAPP_STAGE_BACKEND_ENV_FILE=/var/www/fortcordis-stage/whatsapp-stage-backend/.env
  WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION=1
  WHATSAPP_META_SOURCE_ENV_FILE=""
}
write_env() {
  cat > "$FIXTURE_ROOT/backend/.env" <<'ENV'
WHATSAPP_AGENDA_ENABLED=true
WHATSAPP_BOT_AUTO_SEND_ENABLED=true
SYNTHETIC_UNRELATED_VALUE=preserve
ENV
}
assert_disabled() {
  grep -Fxq 'WHATSAPP_AGENDA_ENABLED=false' "$FIXTURE_ROOT/backend/.env"
  grep -Fxq 'WHATSAPP_BOT_AUTO_SEND_ENABLED=false' "$FIXTURE_ROOT/backend/.env"
  grep -Fxq 'SYNTHETIC_UNRELATED_VALUE=preserve' "$FIXTURE_ROOT/backend/.env"
}

configure_stage
write_env
ensure_whatsapp_core_integration_env
assert_disabled
grep -Fq 'systemctl disable --now fortcordis-stage-whatsapp-backend' "$STAGE_TEST_COMMAND_LOG"
grep -Fq 'systemctl show fortcordis-stage-whatsapp-backend --property=ActiveState --value' "$STAGE_TEST_COMMAND_LOG"
if grep -Eq 'fortcordis-whatsapp-backend|fortcordis-backend|3009|restart' "$STAGE_TEST_COMMAND_LOG"; then
  echo 'Disabled stage path touched a non-stage service or production upstream.' >&2; exit 1
fi

# A fresh stage without a unit is safe and still disables core flags.
configure_stage
write_env
: > "$STAGE_TEST_COMMAND_LOG"
export STAGE_TEST_LOAD_STATE=not-found
ensure_whatsapp_core_integration_env
assert_disabled
! grep -Fq 'systemctl disable' "$STAGE_TEST_COMMAND_LOG"
unset STAGE_TEST_LOAD_STATE

# Failed stop, unverifiable state, or an active remainder must block deployment.
for failure in disable-failed still-active unknown-state active-unresolved; do
  configure_stage
  write_env
  : > "$STAGE_TEST_COMMAND_LOG"
  if (
    case "$failure" in
      disable-failed) export STAGE_TEST_DISABLE_FAIL=1 ;;
      still-active) export STAGE_TEST_STILL_ACTIVE=1 ;;
      unknown-state) export STAGE_TEST_LOAD_STATE=error ;;
      active-unresolved) export STAGE_TEST_ACTIVE_UNRESOLVED=1 ;;
    esac
    ensure_whatsapp_core_integration_env
  ) > "$FIXTURE_ROOT/rejected" 2>&1; then
    echo "Unsafe service state was accepted: $failure" >&2; exit 1
  fi
done

# Every environment and isolation boundary rejects before any operational call.
for invalid in mode branch app core-service wa-service wa-dir wa-env port url isolation source enable smoke; do
  configure_stage
  write_env
  : > "$STAGE_TEST_COMMAND_LOG"
  if (
    case "$invalid" in
      mode) WHATSAPP_STAGE_LIVE_META_ENABLED=true ;;
      branch) BRANCH=main ;;
      app) APP_DIR=/var/www/fortcordis-v2 ;;
      core-service) BACKEND_SERVICE=fortcordis-backend ;;
      wa-service) WHATSAPP_STAGE_BACKEND_SERVICE=fortcordis-whatsapp-backend ;;
      wa-dir) WHATSAPP_STAGE_BACKEND_DIR=/var/www/fortcordis-v2/whatsapp-stage-backend ;;
      wa-env) WHATSAPP_STAGE_BACKEND_ENV_FILE=/var/www/fortcordis-v2/whatsapp-stage-backend/.env ;;
      port) WHATSAPP_STAGE_BACKEND_PORT=3009 ;;
      url) WHATSAPP_STAGE_BACKEND_URL=http://127.0.0.1:3009 ;;
      isolation) WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION=0 ;;
      source) WHATSAPP_META_SOURCE_ENV_FILE=/production/must-not-read.env ;;
      enable) ENABLE_WHATSAPP_STAGE_BACKEND=1 ;;
      smoke) ENABLE_WHATSAPP_STAGE_SMOKE=1 ;;
    esac
    ensure_whatsapp_core_integration_env
  ) > "$FIXTURE_ROOT/rejected" 2>&1; then
    echo "Unsafe stage boundary was accepted: $invalid" >&2; exit 1
  fi
  [[ ! -s "$STAGE_TEST_COMMAND_LOG" ]]
  grep -Fxq 'WHATSAPP_AGENDA_ENABLED=true' "$FIXTURE_ROOT/backend/.env"
done

# The production path without this new stage-only mode remains untouched.
configure_stage
write_env
: > "$STAGE_TEST_COMMAND_LOG"
APP_DIR=/var/www/fortcordis-v2
BRANCH=main
BACKEND_SERVICE=fortcordis-backend
WHATSAPP_STAGE_LIVE_META_ENABLED=""
ensure_whatsapp_core_integration_env
[[ ! -s "$STAGE_TEST_COMMAND_LOG" ]]
grep -Fxq 'WHATSAPP_AGENDA_ENABLED=true' "$FIXTURE_ROOT/backend/.env"

# Opt-in keeps the existing live path available; the disabled handler is inert.
configure_stage
WHATSAPP_STAGE_LIVE_META_ENABLED=1
ENABLE_WHATSAPP_STAGE_BACKEND=1
ENABLE_WHATSAPP_STAGE_SMOKE=1
: > "$STAGE_TEST_COMMAND_LOG"
validate_stage_live_meta_mode
disable_stage_live_meta_runtime
[[ ! -s "$STAGE_TEST_COMMAND_LOG" ]]

# An exported disabled upstream still reaches the build as 3010, never 3009.
configure_stage
export API_BACKEND_URL=http://127.0.0.1:8001
export WHATSAPP_STAGE_BACKEND_URL
: > "$STAGE_TEST_COMMAND_LOG"
(cd "$FIXTURE_ROOT/frontend" && run_frontend_build)
grep -Fq 'npm run build stage-upstream-3010' "$STAGE_TEST_COMMAND_LOG"

# Guard placement precedes dependency/service/backup work in an actual deploy.
python3 - "$REPO_ROOT/scripts/deploy_prod_vps.sh" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
entry = text.split('# Invalid identity must not enter cleanup/rollback handlers or inspect services.', 1)[1]
assert entry.index('validate_deploy_target\nvalidate_stage_live_meta_mode') < entry.index('require_cmd git') < entry.index('backup_runtime_file')
PY
printf 'PASS: Stage without Meta disables only its service/core integration, rejects unsafe boundaries, preserves production and builds with upstream 3010; all operational commands stubbed.\n'
