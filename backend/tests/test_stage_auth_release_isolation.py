"""Execute deployment boundaries with inert upstream/service commands."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


class StageReleaseIsolationTest(unittest.TestCase):
    def test_stage_wrapper_overrides_shared_resource_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copy(SCRIPTS / "deploy_stage_vps.sh", root)
            (root / "deploy_prod_vps.sh").write_text('env | sort\n', encoding="utf-8")
            env = dict(os.environ, ENABLE_NGINX_HTTP2="1", RELOAD_NGINX_ON_DEPLOY="1",
                       RUNTIME_BACKUP_DIR="/production")
            output = subprocess.check_output(
                ["bash", str(root / "deploy_stage_vps.sh")], env=env, text=True)
            values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            for key, value in {
                "APP_DIR": "/var/www/fortcordis-stage", "BRANCH": "stage",
                "BACKEND_SERVICE": "fortcordis-stage-backend",
                "FRONTEND_SERVICE": "fortcordis-stage-frontend",
                "BACKEND_PORT": "8001", "FRONTEND_PORT": "3001",
                "ENABLE_NGINX_HTTP2": "0", "RELOAD_NGINX_ON_DEPLOY": "0",
                "RUNTIME_BACKUP_DIR": f'{env["HOME"]}/fortcordis-stage-runtime-backups',
            }.items():
                self.assertEqual(values[key], value, key)

    def test_reload_gate_does_not_invoke_shared_service(self):
        source = (SCRIPTS / "deploy_prod_vps.sh").read_text(encoding="utf-8")
        function = re.search(r"^reload_nginx_if_possible\(\) \{\n.*?^\}", source, re.M | re.S).group()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("nginx", "systemctl"):
                script = root / name
                script.write_text('#!/bin/bash\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$CALLS"\n')
                script.chmod(0o700)
            calls = root / "calls"
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}', CALLS=str(calls))
            harness = 'log() { :; }; run_with_sudo() { "$@"; }; SYSTEMCTL_BIN=systemctl\n' + function
            for enabled in ("0", "1"):
                subprocess.run(["bash", "-c", harness + '\nreload_nginx_if_possible'],
                               env=dict(env, RELOAD_NGINX_ON_DEPLOY=enabled), check=True)
                if enabled == "0":
                    self.assertFalse(calls.exists())
                else:
                    self.assertEqual(calls.read_text().splitlines(), ["nginx -t", "systemctl reload nginx"])
