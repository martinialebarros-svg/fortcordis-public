#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf -- "$FIXTURE_ROOT"' EXIT
export APP_DIR="${FIXTURE_ROOT}/app"
mkdir -p "$APP_DIR/backend" "$APP_DIR/whatsapp-stage-backend/dist/templates"
# Carrega somente funções; nenhum systemd, Git, banco ou endpoint real é usado.
source "$REPO_ROOT/scripts/deploy_prod_vps.sh"
printf 'WHATSAPP_BUSINESS_ACCOUNT_ID=1369494994627980\n' > "$WHATSAPP_STAGE_BACKEND_ENV_FILE"
cat > "$WHATSAPP_STAGE_BACKEND_DIR/dist/templates/approvedTemplates.js" <<'JS'
exports.isTemplateDeliveryApproved = key => key === "appointmentReminderService"
  && process.env.WHATSAPP_BUSINESS_ACCOUNT_ID === "1369494994627980";
JS
WHATSAPP_EXPECTED_BUSINESS_ACCOUNT_ID=1369494994627980
ENABLE_WHATSAPP_STAGE_BACKEND=1
DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE=1
ACTIONS="${FIXTURE_ROOT}/actions"
restart_service() {
  printf 'restart:%s\n' "$1" >> "$ACTIONS"
  [[ "${FAIL_RESTART_API:-0}" != "1" || "$1" != "$BACKEND_SERVICE" ]]
}
run_systemctl_command() {
  printf 'systemctl:%s\n' "$*" >> "$ACTIONS"
  [[ "${FAIL_STOP_WORKER:-0}" != "1" || "$1" != "stop" ]]
}
wait_http_ok() { printf 'health:%s\n' "$1" >> "$ACTIONS"; }

printf 'UNCHANGED=synthetic\nWHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false\n' > "$BACKEND_DIR/.env"
chmod 640 "$BACKEND_DIR/.env"
activate_whatsapp_reminder_service
grep -Fxq 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=true' "$BACKEND_DIR/.env"
grep -Fxq 'UNCHANGED=synthetic' "$BACKEND_DIR/.env"
python3 - "$ACTIONS" "$BACKEND_SERVICE" "$BACKGROUND_WORKER_SERVICE" "$BACKEND_PORT" "$WHATSAPP_STAGE_BACKEND_PORT" <<'PY'
from pathlib import Path
import sys
assert Path(sys.argv[1]).read_text().splitlines() == [
    f"health:http://127.0.0.1:{sys.argv[5]}/health",
    f"systemctl:stop {sys.argv[3]}",
    f"restart:{sys.argv[2]}",
    f"health:http://127.0.0.1:{sys.argv[4]}/ready",
    f"restart:{sys.argv[3]}",
    f"systemctl:is-active --quiet {sys.argv[3]}",
]
PY
restore_reminder_service_flag
grep -Fxq 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false' "$BACKEND_DIR/.env"
python3 - "$BACKEND_DIR/.env" <<'PY'
from pathlib import Path
import stat
import sys
assert stat.S_IMODE(Path(sys.argv[1]).stat().st_mode) == 0o640
PY

# O arquivo operacional pode ser compartilhado por symlink; preservar o vínculo.
mv "$BACKEND_DIR/.env" "$FIXTURE_ROOT/backend.env"
ln -s "$FIXTURE_ROOT/backend.env" "$BACKEND_DIR/.env"
activate_whatsapp_reminder_service
FAIL_STOP_WORKER=1
restore_reminder_service_flag
FAIL_STOP_WORKER=0
test -L "$BACKEND_DIR/.env"
grep -Fxq 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false' "$FIXTURE_ROOT/backend.env"

# Restaurar ausência também é necessário para Settings de versões anteriores.
printf 'UNCHANGED=synthetic\n' > "$BACKEND_DIR/.env"
activate_whatsapp_reminder_service
restore_reminder_service_flag
if grep -q '^WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=' "$BACKEND_DIR/.env"; then exit 1; fi

# Falha após gravar a flag não deve deixá-la habilitada no rollback.
printf 'UNCHANGED=synthetic\nWHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false\n' > "$BACKEND_DIR/.env"
FAIL_RESTART_API=1
if activate_whatsapp_reminder_service; then exit 1; fi
FAIL_RESTART_API=0
restore_reminder_service_flag
grep -Fxq 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false' "$BACKEND_DIR/.env"

# Não voltar código antigo se nem a flag anterior pôde ser restaurada.
if (
  trap - EXIT
  write_reminder_service_flag_lines() { return 1; }
  rollback_deploy() { touch "$FIXTURE_ROOT/unexpected-rollback"; }
  REMINDER_SERVICE_FLAG_CHANGED=1
  AUTO_ROLLBACK_ON_FAILURE=1
  CODE_UPDATED=1
  PRE_DEPLOY_HASH=previous
  NEW_HASH=installed
  on_exit 7
); then exit 1; fi
test ! -e "$FIXTURE_ROOT/unexpected-rollback"

# Outra WABA e stage nunca recebem ativação; opt-out não muda a flag.
printf 'WHATSAPP_BUSINESS_ACCOUNT_ID=4413513738886247\n' > "$WHATSAPP_STAGE_BACKEND_ENV_FILE"
if activate_whatsapp_reminder_service; then exit 1; fi
grep -Fxq 'WHATSAPP_REMINDER_SERVICE_TEMPLATE_ENABLED=false' "$BACKEND_DIR/.env"
WHATSAPP_REQUIRE_DISTINCT_FROM_PRODUCTION=1
if activate_whatsapp_reminder_service; then exit 1; fi
DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE=0
activate_whatsapp_reminder_service

# Push comum preserva a decisão; input explícito só implanta refs/heads/main.
python3 - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
workflow = (root / ".github/workflows/deploy.yml").read_text()
assert "default: false" in workflow
assert "if: github.ref == 'refs/heads/main'" in workflow
assert "github.event_name == 'workflow_dispatch' && inputs.activate_whatsapp_reminder_service" in workflow
script = (root / "scripts/deploy_prod_vps.sh").read_text()
assert script.rindex("activate_whatsapp_reminder_service\n") > script.index('log "Backup restore drill OK"')
PY

mkdir -p "$FIXTURE_ROOT/bin"
cat > "$FIXTURE_ROOT/bin/bash" <<'SH'
#!/bin/sh
test "$DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE" = 0
SH
chmod +x "$FIXTURE_ROOT/bin/bash"
DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE=1 PATH="$FIXTURE_ROOT/bin:$PATH" \
  /bin/bash "$REPO_ROOT/scripts/deploy_stage_vps.sh"
echo "Controlled WhatsApp reminder activation tests passed."
