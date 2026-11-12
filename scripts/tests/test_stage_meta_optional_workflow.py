#!/usr/bin/env python3
"""Stage's optional Meta channel must never become an implicit live channel."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / '.github/workflows/deploy-stage.yml').read_text()
MODE = 'WHATSAPP_STAGE_LIVE_META_ENABLED'


def step_body(name):
    marker = f'      - name: {name}\n'
    start = WORKFLOW.index(marker) + len(marker)
    tail = WORKFLOW[start:]
    return tail.split('\n      - name:', 1)[0]


class StageMetaOptionalWorkflowTest(unittest.TestCase):
    def test_default_off_and_identity_secrets_are_only_used_after_opt_in(self):
        deploy = WORKFLOW.split('  deploy-stage:\n', 1)[1]
        self.assertIn(f"{MODE}: ${{{{ vars.{MODE} || '0' }}}}", deploy)
        identity = step_body('Configure isolated WhatsApp Cloud API identity on Stage VPS')
        self.assertIn(f"        if: env.{MODE} == '1'\n", identity)
        self.assertIn('bash scripts/whatsapp_meta_identity_check.sh', identity)
        self.assertIn('Stage WhatsApp identity must be isolated from production.', identity)
        self.assertIn('WHATSAPP_ACCESS_TOKEN_STAGE: ${{ secrets.WHATSAPP_ACCESS_TOKEN_STAGE }}', identity)
        self.assertLess(WORKFLOW.index('name: Validate optional stage Meta mode'), WORKFLOW.index('name: Configure OpenAI secret on Stage VPS'))
        deploy_steps = WORKFLOW.split('  deploy-stage:\n', 1)[1]
        self.assertLess(deploy_steps.index('name: Validate optional stage Meta mode'), deploy_steps.index('name: Setup SSH key'))

    def test_mode_validation_fails_closed_without_running_providers(self):
        validation = step_body('Validate optional stage Meta mode')
        script = validation.split('        run: |\n', 1)[1]
        script = '\n'.join(line[10:] if line.startswith('          ') else line for line in script.splitlines())
        for mode, expected in [('0', 0), ('1', 0), ('', 1), ('true', 1), ('2', 1), ('1; exit 0', 1)]:
            with self.subTest(mode=mode):
                result = subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH'], MODE: mode}, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_same_validated_mode_reaches_remote_wrapper(self):
        deploy = step_body('Deploy to Stage (VPS)')
        self.assertIn(f'[[ "${MODE}" == "0" || "${MODE}" == "1" ]]', deploy)
        self.assertIn(f'"{MODE}=\'${MODE}\' bash -s" << \'EOF\'', deploy)
        self.assertIn(f'{MODE}="${MODE}"', deploy)
        self.assertIn('git archive --format=tar "$DEPLOY_SHA"', deploy)
        self.assertIn('bash "$deploy_scripts_dir/scripts/deploy_stage_vps.sh"', deploy)

    def test_production_has_no_stage_opt_in(self):
        self.assertNotIn(MODE, (ROOT / '.github/workflows/deploy.yml').read_text())


if __name__ == '__main__':
    unittest.main()
