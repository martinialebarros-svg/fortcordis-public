#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$FIXTURE_ROOT"' EXIT

mkdir -p "$FIXTURE_ROOT/scripts"
cp "$REPO_ROOT/scripts/deploy_stage_vps.sh" "$FIXTURE_ROOT/scripts/deploy_stage_vps.sh"

# Never execute the real installer, invoke providers, or inspect live env files.
cat > "$FIXTURE_ROOT/scripts/deploy_prod_vps.sh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[[ "$BRANCH" == stage ]]
[[ "$APP_DIR" == /var/www/fortcordis-stage ]]
[[ "$BACKEND_SERVICE" == fortcordis-stage-backend ]]
[[ "$ENABLE_WHATSAPP_STAGE_BACKEND" == "$WHATSAPP_STAGE_LIVE_META_ENABLED" ]]
[[ "$WHATSAPP_STAGE_BACKEND_URL" == http://127.0.0.1:3010 ]]
[[ "$WHATSAPP_STAGE_BACKEND_DIR" == /var/www/fortcordis-stage/whatsapp-stage-backend ]]
[[ "$WHATSAPP_STAGE_BACKEND_ENV_FILE" == /var/www/fortcordis-stage/whatsapp-stage-backend/.env ]]
[[ -z "$WHATSAPP_META_SOURCE_ENV_FILE" ]]
[[ "$DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE" == 0 ]]
[[ "$ENABLE_NGINX_HTTP2" == 0 && "$RELOAD_NGINX_ON_DEPLOY" == 0 ]]
printf '%s:%s:%s\n' "$WHATSAPP_STAGE_LIVE_META_ENABLED" "$ENABLE_WHATSAPP_STAGE_BACKEND" "$ENABLE_WHATSAPP_STAGE_SMOKE" > "$STUB_OUTPUT"
STUB

check_mode() {
  local mode="$1" smoke="$2" expected="$3" result="$FIXTURE_ROOT/result"
  rm -f "$result"
  local args=("ENABLE_WHATSAPP_STAGE_BACKEND=1")
  [[ "$mode" == unset ]] || args+=("WHATSAPP_STAGE_LIVE_META_ENABLED=$mode")
  [[ "$smoke" == unset ]] || args+=("ENABLE_WHATSAPP_STAGE_SMOKE=$smoke")
  env -i PATH="$PATH" HOME="$HOME" STUB_OUTPUT="$result" \
    WHATSAPP_META_SOURCE_ENV_FILE=/production/must-not-inherit.env \
    WHATSAPP_STAGE_BACKEND_DIR=/production/must-not-inherit \
    WHATSAPP_STAGE_BACKEND_ENV_FILE=/production/must-not-read.env \
    WHATSAPP_STAGE_BACKEND_URL=http://127.0.0.1:3009 "${args[@]}" \
    bash "$FIXTURE_ROOT/scripts/deploy_stage_vps.sh"
  [[ "$(cat "$result")" == "$expected" ]]
}

check_mode unset unset 0:0:0
check_mode unset 1 0:0:0
check_mode 0 0 0:0:0
check_mode 0 1 0:0:0
check_mode 1 unset 1:1:0
check_mode 1 0 1:1:0
check_mode 1 1 1:1:1
for invalid in true false 2 invalid; do
  rm -f "$FIXTURE_ROOT/result"
  if env -i PATH="$PATH" HOME="$HOME" STUB_OUTPUT="$FIXTURE_ROOT/result" \
    WHATSAPP_STAGE_LIVE_META_ENABLED="$invalid" \
    bash "$FIXTURE_ROOT/scripts/deploy_stage_vps.sh" >"$FIXTURE_ROOT/rejected" 2>&1; then
    echo "Invalid stage live Meta mode was accepted." >&2; exit 1
  fi
  [[ ! -e "$FIXTURE_ROOT/result" ]]
done
printf 'PASS: Stage live Meta and smoke default off; separate opt-ins preserved; production identity source never inherited; installer fully stubbed.\n'
