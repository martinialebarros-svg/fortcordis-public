#!/usr/bin/env python3
"""Offline fixtures only: no sudo, SSH, Nginx or service calls."""
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("atendimento_ingress", ROOT / "scripts/ensure_atendimento_ia_ingress.py")
ingress = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingress)
SHA = "a" * 40
ORIGINAL = """# Stage only
server {
    listen 443 ssl;
    server_name app.stage.fortcordis.com.br;
    ssl_certificate /etc/letsencrypt/live/stage/fullchain.pem;
    location / {
        proxy_pass http://127.0.0.1:3001;
    }
    location /api {
        client_max_body_size 30m;
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Test-Private "synthetic-secret-do-not-print";
        proxy_http_version 1.1;
        proxy_buffering off;
        include /etc/nginx/snippets/fortcordis-auth.conf;
        # Preserve all settings of the source location.
    }
}
server {
    listen 80;
    server_name stage.fortcordis.com.br www.stage.fortcordis.com.br;
    return 301 https://app.stage.fortcordis.com.br$request_uri;
}
"""
TLS_FIXTURE = """# Public Certbot options observed read-only on Stage; no key material.
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384";
"""


def with_tls(text=ORIGINAL):
    return text.replace("    location / {", f"    include {ingress.TLS_INCLUDE};\n    location / {{", 1)


class TransformTest(unittest.TestCase):
    def test_narrow_route_clones_security_and_preserves_generic_and_other_servers(self):
        result = ingress.transform(ORIGINAL)
        self.assertEqual(ingress.transform(result), result)
        original_api = ingress.stage_api(ORIGINAL)[1]
        api = ingress.stage_api(result)[1]
        self.assertEqual(ORIGINAL[original_api["start"]:original_api["end"]], result[api["start"]:api["end"]])
        self.assertEqual(result.count("proxy_set_header X-Test-Private"), 2)
        self.assertEqual(result.count("include /etc/nginx/snippets/fortcordis-auth.conf;"), 2)
        self.assertEqual(result.count("proxy_read_timeout 210s;"), 1)
        self.assertIn(f"location ~ {ingress.ROUTE} {{", result)
        self.assertLess(result.index(ingress.BEGIN), result.index("location / {"))
        self.assertEqual(result[result.rfind("server {"):], ORIGINAL[ORIGINAL.rfind("server {"):])
        managed = result[result.index(ingress.BEGIN):result.index(ingress.END)]
        self.assertNotIn("proxy_pass http://127.0.0.1:8001/", managed)

    def test_replaces_timeouts_only_inside_managed_location(self):
        original = ORIGINAL.replace("proxy_buffering off;", "proxy_buffering off;\n        proxy_read_timeout 60s;\n        proxy_send_timeout 60s;")
        result = ingress.transform(original)
        self.assertEqual(result.count("proxy_read_timeout 60s;"), 1)
        self.assertEqual(result.count("proxy_send_timeout 60s;"), 1)
        self.assertEqual(result.count("proxy_read_timeout 210s;"), 1)
        self.assertEqual(result.count("proxy_send_timeout 210s;"), 1)

    def test_rejects_wrong_upstream_uri_production_and_bypassing_or_ambiguous_routes(self):
        cases = [
            ORIGINAL.replace(":8001;", ":8000;"),
            ORIGINAL.replace(":8001;", ":8001/;"),
            ORIGINAL.replace("app.stage.fortcordis.com.br;", "app.fortcordis.com.br;"),
            ORIGINAL.replace("location /api {", "location ^~ /api {"),
            ORIGINAL.replace("proxy_buffering off;", "if ($invalid) { return 403; }"),
            ORIGINAL.replace("proxy_buffering off;", "rewrite ^ /different break;"),
            ORIGINAL.replace("location / {", f"location ~ {ingress.ROUTE} {{ proxy_pass http://127.0.0.1:8001; }}\n    location / {{"),
            ORIGINAL.replace("location / {", "location = /api/v1/atendimentos/2/assistente/analisar { return 200; }\n    location / {"),
            ORIGINAL + "server { server_name app.stage.fortcordis.com.br; location /api { proxy_pass http://127.0.0.1:8001; } }",
        ]
        for text in cases:
            with self.subTest(text=text[-50:]), self.assertRaises(ingress.IngressError):
                ingress.transform(text)

    def test_markers_cannot_delete_unowned_directives(self):
        for block in (f"{ingress.BEGIN}\nserver {{ server_name other.example; }}\n{ingress.END}\n",
                      f"{ingress.BEGIN}\nlocation ~ {ingress.ROUTE} {{ }}\nreturn 200;\n{ingress.END}\n",
                      ingress.BEGIN + "\n"):
            with self.assertRaises(ingress.IngressError):
                ingress.transform(block + ORIGINAL)

    def test_quotes_comments_and_braced_variables_are_preserved(self):
        value = ORIGINAL.replace("proxy_buffering off;", "proxy_set_header X-Example '${http_example} literal { } #'; # comment {\n        proxy_set_header Connection \"\";\n        proxy_set_header X-Literal ';';\n        proxy_buffering off;")
        result = ingress.transform(value)
        self.assertEqual(result.count("'${http_example} literal { } #'"), 2)
        self.assertEqual(result.count('proxy_set_header Connection "";'), 2)
        self.assertEqual(result.count("proxy_set_header X-Literal ';';"), 2)

    def test_unrelated_prefix_location_does_not_block_the_stage_route(self):
        value = ORIGINAL.replace("location / {", "location ^~ /.well-known/acme-challenge/ { root /var/www/acme; }\n    location / {")
        self.assertIn(ingress.BEGIN, ingress.transform(value))

    def test_never_bypasses_existing_auth_or_rate_limits_from_overlapping_routes(self):
        routes = ["/api/v1/atendimentos/", "/api/v1/atendimentos/2/assistente/", "/api/v1/",
                  "^~ /api/v1/", "~ ^/api/", "~* ^/API/", "~ \\.(json|pdf)$"]
        for route in routes:
            value = ORIGINAL.replace("location / {", f"location {route} {{ auth_basic restricted; limit_req zone=clinical; }}\n    location / {{")
            with self.subTest(route=route), self.assertRaises(ingress.IngressError):
                ingress.transform(value)

    def test_server_include_cannot_hide_more_specific_protected_locations(self):
        value = ORIGINAL.replace("    location / {", "    include /etc/nginx/snippets/protected-routes.conf;\n    location / {")
        with self.assertRaisesRegex(ingress.IngressError, "server_include_requires_explicit_review"):
            ingress.transform(value)

    def test_only_reviewed_tls_path_and_exact_safe_directives_are_accepted(self):
        result = ingress.transform(with_tls(), TLS_FIXTURE)
        self.assertEqual(result.count(f"include {ingress.TLS_INCLUDE};"), 1)
        self.assertEqual(ingress.transform(result, TLS_FIXTURE), result)
        with self.assertRaises(ingress.IngressError):
            ingress.transform(with_tls())
        with self.assertRaises(ingress.IngressError):
            ingress.transform(with_tls().replace(str(ingress.TLS_INCLUDE), "/etc/nginx/custom-ssl.conf"), TLS_FIXTURE)
        for unsafe in ("location /api/v1/ { auth_basic protected; }", "include /etc/nginx/hidden.conf;",
                       "ssl_certificate_key /private/key.pem;", "ssl_protocols TLSv1.3;"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ingress.IngressError):
                ingress.transform(with_tls(), TLS_FIXTURE + unsafe)
        for unsafe in (TLS_FIXTURE.replace("1440m", "$custom_timeout"),
                       TLS_FIXTURE.replace("TLSv1.2 TLSv1.3", "TLSv1")):
            with self.assertRaises(ingress.IngressError):
                ingress.transform(with_tls(), unsafe)


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="atendimento-ingress-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        stage = self.root / "var/www/fortcordis-stage"
        enabled = self.root / "etc/nginx/sites-enabled/fortcordis-stage"
        available = self.root / "etc/nginx/sites-available/fortcordis-stage"
        backup = self.root / "var/backups/fortcordis-atendimento-ia-ingress"
        tls = self.root / "etc/letsencrypt/options-ssl-nginx.conf"
        for folder in (stage / "scripts", stage / "backend", enabled.parent, available.parent, backup.parent, tls.parent):
            folder.mkdir(parents=True)
        tls.write_text(TLS_FIXTURE)
        tls.chmod(0o644)
        source = (ROOT / ingress.SCRIPT).read_text()
        (stage / ingress.SCRIPT).write_text(source)
        (stage / "backend/.env").write_text("APP_ENV=stage\nOPENAI_API_KEY=synthetic-never-log\n")
        available.write_text(ORIGINAL)
        available.chmod(0o640)
        enabled.symlink_to("../sites-available/fortcordis-stage")
        self.production = enabled.parent / "fortcordis-app"
        self.production.write_text("production untouched\n")
        modifications = patch.multiple(ingress, STAGE_ROOT=stage, ENABLED=enabled, AVAILABLE=available,
                                      BACKUP_ROOT=backup, TLS_INCLUDE=tls, OWNER_UID=os.getuid(), __file__=str(stage / ingress.SCRIPT))
        modifications.start()
        self.addCleanup(modifications.stop)
        euid = patch.object(ingress.os, "geteuid", return_value=0)
        euid.start()
        self.addCleanup(euid.stop)
        signals = patch.object(ingress.signal, "signal")
        signals.start()
        self.addCleanup(signals.stop)
        self.log = io.StringIO()
        stdout = redirect_stdout(self.log)
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        self.calls = []

    def fake_run(self, args, label):
        self.calls.append(label)
        if label == "installed_sha":
            return SHA + "\n"
        if label == "installed_script":
            return (ROOT / ingress.SCRIPT).read_text()
        if label == "nginx_effective":
            return f"# configuration file {ingress.ENABLED}:\n{ingress.AVAILABLE.read_text()}\n# configuration file /etc/nginx/sites-enabled/fortcordis-app:\nsecret-production-value\n# configuration file {ingress.TLS_INCLUDE}:\n{ingress.TLS_INCLUDE.read_text()}"
        return ""

    def test_real_stage_tls_layout_is_preserved_and_effective_include_is_verified(self):
        original = with_tls()
        ingress.AVAILABLE.write_text(original)
        tls_before = ingress.TLS_INCLUDE.read_bytes()
        ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(ingress.TLS_INCLUDE.read_bytes(), tls_before)
        self.assertEqual(ingress.AVAILABLE.read_text().count(f"include {ingress.TLS_INCLUDE};"), 1)
        self.assertIn('"validated_tls_include"', self.log.getvalue())
        self.assertIn('"status": "complete"', self.log.getvalue())

    def test_changed_tls_snapshot_blocks_write_and_effective_change_rolls_back(self):
        original = with_tls()
        ingress.AVAILABLE.write_text(original)
        def mutate(status, **fields):
            if status == "backup_ready":
                ingress.TLS_INCLUDE.write_text(TLS_FIXTURE + "# concurrent change\n")
        with patch.object(ingress, "emit", side_effect=mutate):
            with self.assertRaisesRegex(ingress.IngressError, "tls_include_changed_before_write"):
                ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(ingress.AVAILABLE.read_text(), original)
        self.assertNotIn("nginx_validation", self.calls)
        ingress.TLS_INCLUDE.write_text(TLS_FIXTURE)
        def runner(args, label):
            dump = self.fake_run(args, label)
            return dump.replace("ssl_session_timeout 1440m;", "ssl_session_timeout 60m;") if label == "nginx_effective" else dump
        with self.assertRaisesRegex(ingress.IngressError, "effective_tls_include_mismatch"):
            ingress.apply_ingress(SHA, True, runner)
        self.assertEqual(ingress.AVAILABLE.read_text(), original)
        self.assertEqual(ingress.TLS_INCLUDE.read_text(), TLS_FIXTURE)
        self.assertEqual(self.calls[-2:], ["rollback_validation", "rollback_reload"])

    def test_untrusted_tls_file_or_routing_directive_is_rejected_without_writes(self):
        ingress.AVAILABLE.write_text(with_tls())
        original = ingress.AVAILABLE.read_text()
        ingress.TLS_INCLUDE.write_text(TLS_FIXTURE + "location /api/ { auth_basic private; }\n")
        with self.assertRaisesRegex(ingress.IngressError, "tls_include_content"):
            ingress.apply_ingress(SHA, True, self.fake_run)
        ingress.TLS_INCLUDE.write_text(TLS_FIXTURE)
        ingress.TLS_INCLUDE.chmod(0o666)
        with self.assertRaisesRegex(ingress.IngressError, "untrusted_target_file"):
            ingress.apply_ingress(SHA, True, self.fake_run)
        ingress.TLS_INCLUDE.unlink()
        other = ingress.TLS_INCLUDE.parent / "other.conf"
        other.write_text(TLS_FIXTURE)
        ingress.TLS_INCLUDE.symlink_to(other)
        with self.assertRaisesRegex(ingress.IngressError, "untrusted_tls_include_path"):
            ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(ingress.AVAILABLE.read_text(), original)
        self.assertFalse(ingress.BACKUP_ROOT.exists())
        self.assertNotIn("nginx_reload", self.calls)

    def test_success_backup_before_write_permissions_symlink_production_and_sanitized_dump(self):
        original = ingress.AVAILABLE.read_bytes()
        def runner(args, label):
            if label == "nginx_validation":
                backups = list(ingress.BACKUP_ROOT.glob("*/fortcordis-stage.conf"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)
                self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(backups[0].parent.stat().st_mode), 0o700)
            return self.fake_run(args, label)
        ingress.apply_ingress(SHA, True, runner)
        self.assertEqual(self.calls, ["installed_sha", "installed_script", "nginx_preflight", "nginx_validation", "nginx_reload", "nginx_effective"])
        self.assertEqual(stat.S_IMODE(ingress.AVAILABLE.stat().st_mode), 0o640)
        self.assertTrue(ingress.ENABLED.is_symlink())
        self.assertEqual(os.readlink(ingress.ENABLED), "../sites-available/fortcordis-stage")
        self.assertEqual(self.production.read_text(), "production untouched\n")
        log = self.log.getvalue()
        self.assertIn('"status": "complete"', log)
        self.assertIn('"proxy_read_timeout": "210s"', log)
        for secret in ("synthetic-secret-do-not-print", "secret-production-value", "synthetic-never-log"):
            self.assertNotIn(secret, log)

    def test_idempotence_does_not_write_backup_or_reload(self):
        ingress.apply_ingress(SHA, True, self.fake_run)
        before = ingress.AVAILABLE.stat().st_mtime_ns
        self.calls.clear()
        ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(self.calls, ["installed_sha", "installed_script", "nginx_preflight", "nginx_effective"])
        self.assertEqual(ingress.AVAILABLE.stat().st_mtime_ns, before)
        self.assertEqual(len(list(ingress.BACKUP_ROOT.iterdir())), 1)

    def test_validation_reload_and_effective_failure_restore_original_and_reload(self):
        for failure in ("nginx_validation", "nginx_reload", "nginx_effective"):
            with self.subTest(failure=failure):
                ingress.AVAILABLE.write_text(ORIGINAL)
                before = ingress.AVAILABLE.stat()
                self.calls.clear()
                def runner(args, label):
                    if label == failure:
                        self.calls.append(label)
                        raise ingress.IngressError("synthetic_failure")
                    if label == "rollback_reload":
                        self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
                    return self.fake_run(args, label)
                with self.assertRaisesRegex(ingress.IngressError, "synthetic_failure"):
                    ingress.apply_ingress(SHA, True, runner)
                self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
                self.assertEqual(ingress.AVAILABLE.stat().st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(stat.S_IMODE(ingress.AVAILABLE.stat().st_mode), 0o640)
                self.assertEqual(self.calls[-2:], ["rollback_validation", "rollback_reload"])

    def test_effective_dump_mismatch_rolls_back_without_exposing_dump(self):
        def runner(args, label):
            if label == "nginx_effective":
                return "secret-not-the-stage-config"
            return self.fake_run(args, label)
        with self.assertRaisesRegex(ingress.IngressError, "effective_stage_config_mismatch"):
            ingress.apply_ingress(SHA, True, runner)
        self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
        self.assertNotIn("secret-not-the-stage-config", self.log.getvalue())

    def test_rollback_failure_is_explicit_and_never_claims_success(self):
        for failure in ("rollback_validation", "rollback_reload"):
            with self.subTest(failure=failure):
                self.log.seek(0)
                self.log.truncate(0)
                def runner(args, label):
                    if label in {"nginx_validation", failure}:
                        raise ingress.IngressError("synthetic_failure")
                    return self.fake_run(args, label)
                with self.assertRaisesRegex(ingress.IngressError, "rollback_failed_manual_recovery_required"):
                    ingress.apply_ingress(SHA, True, runner)
                self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
                self.assertNotIn('"status": "complete"', self.log.getvalue())
                self.assertNotIn('"status": "rolled_back"', self.log.getvalue())

    def test_concurrent_target_change_after_backup_is_never_overwritten(self):
        def mutate(status, **fields):
            if status == "backup_ready":
                ingress.AVAILABLE.write_text("external-stage-config-change\n")
        with patch.object(ingress, "emit", side_effect=mutate):
            with self.assertRaisesRegex(ingress.IngressError, "target_changed_before_write"):
                ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(ingress.AVAILABLE.read_text(), "external-stage-config-change\n")
        self.assertEqual(self.production.read_text(), "production untouched\n")
        self.assertNotIn("nginx_validation", self.calls)
        self.assertNotIn("nginx_reload", self.calls)

    def test_backup_failure_never_writes_or_reloads(self):
        with patch.object(ingress.shutil, "copy2", side_effect=OSError("no space")):
            with self.assertRaises(OSError):
                ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
        self.assertNotIn("nginx_reload", self.calls)

    def test_backup_parent_symlink_is_rejected_before_creating_backup_or_writing(self):
        ingress.BACKUP_ROOT.parent.rmdir()
        escaped = self.root / "outside-backup-root"
        escaped.mkdir()
        ingress.BACKUP_ROOT.parent.symlink_to(escaped)
        with self.assertRaisesRegex(ingress.IngressError, "untrusted_backup_parent"):
            ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertEqual(list(escaped.iterdir()), [])
        self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)
        self.assertNotIn("nginx_reload", self.calls)

    def test_guards_fail_before_writes(self):
        for sha, execute in ((SHA, False), ("abc", True), ("z" * 40, True)):
            with self.subTest(sha=sha), self.assertRaises(ingress.IngressError):
                ingress.apply_ingress(sha, execute, self.fake_run)
        for value in ("APP_ENV=production\n", "APP_ENV=stage\nAPP_ENV=production\n", "OPENAI_API_KEY=synthetic\n"):
            (ingress.STAGE_ROOT / "backend/.env").write_text(value)
            with self.assertRaisesRegex(ingress.IngressError, "app_env"):
                ingress.apply_ingress(SHA, True, self.fake_run)
        self.assertFalse(ingress.BACKUP_ROOT.exists())
        self.assertEqual(ingress.AVAILABLE.read_text(), ORIGINAL)

    def test_wrong_installed_sha_or_modified_script_is_rejected(self):
        for failure in ("installed_sha", "installed_script"):
            def runner(args, label):
                return "different" if label == failure else self.fake_run(args, label)
            with self.subTest(failure=failure), self.assertRaises(ingress.IngressError):
                ingress.apply_ingress(SHA, True, runner)
        self.assertFalse(ingress.BACKUP_ROOT.exists())

    def test_rejects_production_symlink_chain_hardlink_and_other_vhost_alias(self):
        ingress.ENABLED.unlink()
        ingress.ENABLED.symlink_to(self.production)
        with self.assertRaises(ingress.IngressError):
            ingress.target_path()
        ingress.ENABLED.unlink()
        ingress.ENABLED.symlink_to("../sites-available/fortcordis-stage")
        ingress.AVAILABLE.unlink()
        ingress.AVAILABLE.symlink_to(self.production)
        with self.assertRaises(ingress.IngressError):
            ingress.target_path()
        ingress.AVAILABLE.unlink()
        ingress.AVAILABLE.write_text(ORIGINAL)
        alias = ingress.ENABLED.parent / "another-vhost"
        alias.symlink_to(ingress.AVAILABLE)
        with self.assertRaises(ingress.IngressError):
            ingress.target_path()
        alias.unlink()
        os.link(ingress.AVAILABLE, alias)
        with self.assertRaises(ingress.IngressError):
            ingress.target_path()

    def test_accepts_fixed_enabled_regular_file_layout(self):
        ingress.ENABLED.unlink()
        ingress.ENABLED.write_text(ORIGINAL)
        self.assertEqual(ingress.target_path(), ingress.ENABLED)


class WorkflowTest(unittest.TestCase):
    def test_opt_in_after_successful_deploy_uses_stdin_password_and_pinned_sha(self):
        workflow = (ROOT / ".github/workflows/deploy-stage.yml").read_text()
        name = "      - name: Configure isolated Atendimento IA ingress on Stage\n"
        block = workflow.split(name)[1].split("      - name:", 1)[0]
        self.assertIn("success() && contains(github.event.head_commit.message, '[atendimento-ia-ingress]')", block)
        self.assertIn('printf \'%s\\n\' "$VPS_SUDO_PASSWORD"', block)
        self.assertIn("sudo -S -p", block)
        self.assertIn("--apply-stage-ingress --expected-sha", block)
        self.assertIn("${{ github.sha }}", block)
        self.assertIn("/var/www/fortcordis-stage/scripts/ensure_atendimento_ia_ingress.py", block)
        self.assertNotIn("ATENDIMENTO_IA_ENABLED", block)
        self.assertGreater(workflow.index(name), workflow.index("      - name: Deploy to Stage (VPS)\n"))
        self.assertIn("python3 scripts/tests/test_ensure_atendimento_ia_ingress.py", workflow)
        self.assertNotIn("ensure_atendimento_ia_ingress", (ROOT / ".github/workflows/deploy.yml").read_text())


if __name__ == "__main__":
    unittest.main()
