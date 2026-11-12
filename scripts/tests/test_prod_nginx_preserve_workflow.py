#!/usr/bin/env python3
"""Run the production Nginx policy and installer gates without server I/O."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/deploy.yml"
PIN = "a" * 40


def nginx_policy():
    text = WORKFLOW.read_text()
    match = re.search(
        r"(?m)^([ ]*)# BEGIN per-release Nginx policy:[^\n]*\n(.*?)"
        r"^[ ]*# END per-release Nginx policy\.$",
        text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("Missing production Nginx policy block")
    return textwrap.dedent(match.group(2))


class ProductionNginxPreservationTests(unittest.TestCase):
    def run_policy(self, message, *, event="push", commit_available=True, probe_installer=False):
        with tempfile.TemporaryDirectory(prefix="prod-nginx-policy-") as temp:
            folder = Path(temp)
            trace = folder / "trace"
            trace.write_text("")
            state = folder / "state"
            marker = folder / "unexpected-evaluation"
            env = dict(os.environ, DEPLOY_SHA=PIN, COMMIT_MESSAGE=message,
                       GITHUB_EVENT_NAME=event, COMMIT_AVAILABLE="1" if commit_available else "0",
                       TRACE=str(trace), STATE=str(state), INJECTION_MARKER=str(marker))
            script = r'''
set -euo pipefail
git() {
  printf 'git %s\n' "$*" >> "$TRACE"
  [[ "$*" == "show -s --format=%B $DEPLOY_SHA" ]] || return 98
  [[ "$COMMIT_AVAILABLE" == 1 ]] || return 99
  printf '%s\n' "$COMMIT_MESSAGE"
}
'''
            script += nginx_policy()
            script += '\nprintf "%s\\n" "$NGINX_HTTP2_FOR_DEPLOY" "$NGINX_RELOAD_FOR_DEPLOY" > "$STATE"\n'
            if probe_installer:
                # Source definitions only, then fail loudly on any side effect.
                # All commands are doubles even if a future regression enables
                # the helper or reload; no real nginx/systemctl/sudo is invoked.
                script += r'''
export ENABLE_NGINX_HTTP2="$NGINX_HTTP2_FOR_DEPLOY"
export RELOAD_NGINX_ON_DEPLOY="$NGINX_RELOAD_FOR_DEPLOY"
source scripts/deploy_prod_vps.sh
SCRIPT_DIR="$APP_DIR"
mkdir -p "$SCRIPT_DIR"
printf '# inert helper fixture\n' > "$SCRIPT_DIR/ensure_nginx_http2.sh"
nginx() { printf 'nginx %s\n' "$*" >> "$TRACE"; return 97; }
systemctl() { printf 'systemctl %s\n' "$*" >> "$TRACE"; return 97; }
run_with_sudo() { printf 'run_with_sudo %s\n' "$*" >> "$TRACE"; return 97; }
bash() { printf 'helper %s\n' "$*" >> "$TRACE"; return 97; }
SYSTEMCTL_BIN=systemctl
ensure_nginx_http2_if_enabled
reload_nginx_if_possible
# Rollback uses the same reload function and inherited override.
reload_nginx_if_possible
'''
                env.update(APP_DIR=str(folder / "app"), BRANCH="main",
                           DEPLOY_REF="refs/heads/main")
            run = subprocess.run(["/bin/bash", "-c", script], cwd=ROOT, env=env,
                                 text=True, capture_output=True, timeout=10)
            return (run, state.read_text().splitlines() if state.exists() else [],
                    trace.read_text().splitlines(), marker.exists())

    def test_unmarked_commits_keep_both_production_defaults(self):
        for event in ("push", "workflow_dispatch"):
            for message in ("", "Merge pull request #999\n\nPublish report preview",
                            "[preserve-nginx-other]", "[PRESERVE-NGINX]"):
                with self.subTest(event=event, message=message):
                    run, state, trace, injected = self.run_policy(message, event=event)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(state, ["1", "1"])
                    self.assertEqual(trace, [f"git show -s --format=%B {PIN}"])
                    self.assertFalse(injected)

    def test_marker_disables_both_flags_for_the_same_gated_commit_on_any_trigger(self):
        for event in ("push", "workflow_dispatch"):
            for message in ("[preserve-nginx] Publish report preview",
                            "Merge pull request #999\n\nReport preview [preserve-nginx]"):
                with self.subTest(event=event, message=message):
                    run, state, trace, injected = self.run_policy(message, event=event)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(state, ["0", "0"])
                    self.assertEqual(trace, [f"git show -s --format=%B {PIN}"])
                    self.assertFalse(injected)

    def test_commit_text_is_data_never_evaluated_or_echoed(self):
        message = '[preserve-nginx] $(touch "$INJECTION_MARKER") `touch "$INJECTION_MARKER"`\n"; exit 89'
        run, state, _, injected = self.run_policy(message)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(state, ["0", "0"])
        self.assertFalse(injected)
        self.assertNotIn("touch", run.stdout)

    def test_missing_commit_fails_before_selecting_or_launching_installer(self):
        run, state, trace, _ = self.run_policy("[preserve-nginx]", commit_available=False)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(state, [])
        self.assertEqual(trace, [f"git show -s --format=%B {PIN}"])

    def test_installer_and_rollback_reload_gate_skip_all_nginx_commands(self):
        run, state, trace, _ = self.run_policy("[preserve-nginx]", probe_installer=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(state, ["0", "0"])
        self.assertEqual(trace, [f"git show -s --format=%B {PIN}"])
        self.assertIn("HTTP/2 enablement disabled (ENABLE_NGINX_HTTP2=0); skipping.", run.stdout)
        self.assertEqual(run.stdout.count("Nginx reload disabled for this deploy."), 2)

    def test_workflow_passes_the_selected_flags_and_keeps_reminder_input(self):
        text = WORKFLOW.read_text()
        self.assertIn('ENABLE_NGINX_HTTP2="$NGINX_HTTP2_FOR_DEPLOY" \\', text)
        self.assertIn('RELOAD_NGINX_ON_DEPLOY="$NGINX_RELOAD_FOR_DEPLOY" \\', text)
        self.assertNotIn("ENABLE_NGINX_HTTP2=1 \\", text)
        self.assertIn("activate_whatsapp_reminder_service:", text)
        self.assertIn("inputs.activate_whatsapp_reminder_service", text)
        self.assertIn("run: python3 scripts/tests/test_prod_nginx_preserve_workflow.py", text)
        self.assertLess(text.index('git archive --format=tar "$DEPLOY_SHA" --'),
                        text.index("# BEGIN per-release Nginx policy:"))
        self.assertLess(text.index("# END per-release Nginx policy."),
                        text.index('bash "$DEPLOY_SCRIPT_DIR/scripts/deploy_prod_vps.sh"'))


if __name__ == "__main__":
    unittest.main()
