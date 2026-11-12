#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/deploy-stage.yml"

fail() {
  echo "[test-vps-ingress-stage-trigger] $*" >&2
  exit 1
}

grep -Fq "name: Run one-shot VPS ingress diagnostics on Stage" "${WORKFLOW}" || fail "missing one-shot diagnostic step"
grep -Fq "contains(github.event.head_commit.message, '[vps-ingress-diagnostics]')" "${WORKFLOW}" || fail "missing explicit marker guard"
grep -Fq "scripts/probe_public_https.sh" "${WORKFLOW}" || fail "missing external probe"
grep -Fq "scripts/collect_vps_ingress_diagnostics.sh" "${WORKFLOW}" || fail "missing remote collector"
grep -Fq "name: Run bounded VPS ingress delta monitor on Stage" "${WORKFLOW}" || fail "missing bounded monitor step"
grep -Fq "contains(github.event.head_commit.message, '[vps-ingress-monitor]')" "${WORKFLOW}" || fail "missing bounded monitor marker guard"
grep -Fq "scripts/monitor_vps_ingress_deltas.sh" "${WORKFLOW}" || fail "missing delta monitor script"
grep -Fq "PROBE_ATTEMPTS=30" "${WORKFLOW}" || fail "missing bounded public monitor probes"
monitor_step="$(sed -n '/name: Run bounded VPS ingress delta monitor on Stage/,/name: Run one-shot AI echo canary on Stage/p' "${WORKFLOW}")"
printf '%s\n' "${monitor_step}" | grep -Fq 'cd /var/www/fortcordis-stage && test "$(git rev-parse HEAD)"' || fail "remote execution must verify the deployed checkout"
printf '%s\n' "${monitor_step}" | grep -Fq 'timeout --kill-after=5 360 bash scripts/monitor_vps_ingress_deltas.sh' || fail "remote monitor requires a deadline and a real file path"
if printf '%s\n' "${monitor_step}" | grep -Fq 'bash -s'; then
  fail "streamed monitor cannot resolve its sibling collector"
fi

if grep -A60 -F "name: Run one-shot VPS ingress diagnostics on Stage" "${WORKFLOW}" | rg -q '\bsudo\b|systemctl (restart|reload|stop)|rm -rf'; then
  fail "diagnostic stage steps contain a mutation-capable command"
fi

echo "VPS ingress diagnostics stage trigger tests passed."
