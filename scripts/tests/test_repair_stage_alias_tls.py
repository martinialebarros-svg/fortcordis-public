"""No SSH, sudo, DNS, ACME or infrastructure calls: filesystem fixtures only."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stage_alias_repair", ROOT / "scripts/repair_stage_alias_tls.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)
WORKFLOW = (ROOT / ".github/workflows/repair-stage-alias-tls.yml").read_text()


class StageAliasRepairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        paths = {name: self.root / getattr(repair, name).relative_to("/")
                 for name in ("VHOST", "LIVE", "ARCHIVE", "RENEWAL", "BACKUP_ROOT")}
        protected = tuple(self.root / path.relative_to("/") for path in repair.PROTECTED)
        config = self.root / "cli.ini"
        self.patch = patch.multiple(repair, **paths, STAGE_PATHS=tuple(paths[name] for name in ("VHOST", "LIVE", "ARCHIVE", "RENEWAL")),
                                    PROTECTED=protected, GLOBAL_CONFIGS=(config,))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for path in (*protected, paths["VHOST"], paths["RENEWAL"]):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("protected fixture")
        repair.ARCHIVE.mkdir(parents=True)
        repair.LIVE.mkdir(parents=True)
        for name in ("cert", "chain", "fullchain", "privkey"):
            target = repair.ARCHIVE / (name + "1.pem")
            target.write_text("original-" + name)
            target.chmod(0o600 if name == "privkey" else 0o644)
            (repair.LIVE / (name + ".pem")).symlink_to("../../archive/" + repair.LINEAGE + "/" + target.name)
        repair.RENEWAL.write_text("[renewalparams]\nauthenticator = nginx\ninstaller = nginx\n")
        repair.RENEWAL.chmod(0o640)
        repair.VHOST.write_text("server {\nserver_name " + " ".join(repair.DOMAINS) + ";\n"
                                + "proxy_pass http://127.0.0.1:3001;\nproxy_pass http://127.0.0.1:8001;\n"
                                + "ssl_certificate " + str(repair.LIVE / "fullchain.pem") + ";\n"
                                + "ssl_certificate_key " + str(repair.LIVE / "privkey.pem") + ";\n}\n")
        self.output = io.StringIO()
        stdout = redirect_stdout(self.output)
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        signals = patch.object(repair.signal, "signal")
        self.signal_mock = signals.start()
        self.addCleanup(signals.stop)

    def fake_run(self, args, label, timeout=180):
        if label == "dns":
            domain, kind = args[2:4]
            if kind == "CNAME":
                return repair.LINEAGE + ".\n"
            if kind == "AAAA":
                return ""
            return (repair.LINEAGE + ".\n" if domain != repair.LINEAGE else "") + repair.IP + "\n"
        if label == "https":
            if args[-1] == "https://" + repair.DOMAINS[1] + "/agenda":
                return "HTTP/2 200\r\n\r\n"
            return "HTTP/2 307\r\nlocation: https://" + repair.DOMAINS[1] + "/agenda\r\n\r\n"
        return ""

    def mutate_stage(self):
        repair.RENEWAL.write_text("mutated")
        repair.VHOST.write_text("mutated")
        (repair.ARCHIVE / "fullchain2.pem").write_text("new certificate")
        (repair.LIVE / "fullchain.pem").unlink()
        (repair.LIVE / "fullchain.pem").symlink_to("../../archive/" + repair.LINEAGE + "/fullchain2.pem")

    def test_dns_requires_exact_cname_direct_ipv4_and_no_ipv6_before_mutation(self):
        repair.validate_dns(self.fake_run)
        for kind, bad in (("CNAME", "wrong.example.\n"), ("A", "104.16.0.1\n"), ("AAAA", "2606:4700::1\n")):
            with self.subTest(kind=kind), patch.object(repair, "Backup") as backup:
                def run(args, label, timeout=180):
                    return bad if label == "dns" and args[3] == kind else self.fake_run(args, label, timeout)
                with self.assertRaises(repair.RepairError):
                    repair.repair(run)
                backup.assert_not_called()

    def test_rejects_global_hooks_server_override_and_wrong_upstream(self):
        config = repair.GLOBAL_CONFIGS[0]
        for directive in (" pre-hook = secret-command", "post_hook = secret-command",
                          "pre-hook: secret-command", "--post-hook secret-command",
                          "server = https://example.com", "--server https://example.com"):
            config.write_text(directive)
            with self.assertRaises(repair.RepairError):
                repair.validate_layout()
        config.unlink()
        repair.VHOST.write_text(repair.VHOST.read_text().replace(":3001", ":3000"))
        with self.assertRaisesRegex(repair.RepairError, "upstreams"):
            repair.validate_layout()
        self.assertNotIn("secret-command", self.output.getvalue())

    def test_backup_restore_bytes_modes_symlinks_only_stage(self):
        before = repair.hashes(repair.PROTECTED)
        original = repair.VHOST.read_bytes()
        backup = repair.Backup()
        self.assertEqual(stat.S_IMODE(backup.path.stat().st_mode), 0o700)
        self.mutate_stage()
        backup.restore()
        self.assertEqual(repair.VHOST.read_bytes(), original)
        self.assertEqual((repair.LIVE / "fullchain.pem").read_text(), "original-fullchain")
        self.assertEqual(stat.S_IMODE(repair.RENEWAL.stat().st_mode), 0o640)
        self.assertEqual(repair.hashes(repair.PROTECTED), before)
        self.assertTrue((repair.ARCHIVE / "fullchain2.pem").exists())
        self.assertEqual(json.loads((backup.path / "manifest.json").read_text())["status"], "restored")

    def test_success_orders_preflight_issue_reload_and_renewal(self):
        calls = []
        def run(args, label, timeout=180):
            calls.append((label, args))
            return self.fake_run(args, label, timeout)
        with patch.object(repair, "certificate_ready", side_effect=[False, True]):
            repair.repair(run)
        labels = [label for label, _ in calls]
        self.assertLess(labels.index("acme_preflight"), labels.index("acme_issue"))
        self.assertLess(labels.index("acme_issue"), labels.index("nginx_reload"))
        self.assertLess(labels.index("nginx_reload"), labels.index("renewal_dry_run"))
        renewal = next(args for label, args in calls if label == "renewal_dry_run")
        self.assertIn("--no-random-sleep-on-renew", renewal)
        issued = next(args for label, args in calls if label == "acme_issue")
        self.assertEqual([issued[i + 1] for i, item in enumerate(issued) if item == "-d"], list(repair.DOMAINS))
        self.assertIn('"status": "complete"', self.output.getvalue())

    def test_idempotent_certificate_does_not_issue_again(self):
        calls = []
        def run(args, label, timeout=180):
            calls.append(label)
            return self.fake_run(args, label, timeout)
        with patch.object(repair, "certificate_ready", return_value=True):
            repair.repair(run)
        self.assertNotIn("acme_issue", calls)
        self.assertIn("renewal_dry_run", calls)
        self.assertIn('"issued": false', self.output.getvalue())

    def test_failure_restores_before_reload_and_suppresses_repeated_hup(self):
        original = repair.VHOST.read_bytes()
        calls = []
        def run(args, label, timeout=180):
            calls.append(label)
            if label == "acme_issue":
                self.mutate_stage()
                raise repair.RepairError("interrupted")
            if label == "rollback_reload":
                self.assertEqual(repair.VHOST.read_bytes(), original)
            return self.fake_run(args, label, timeout)
        with patch.object(repair, "certificate_ready", return_value=False), self.assertRaisesRegex(repair.RepairError, "interrupted"):
            repair.repair(run)
        self.assertIn("rollback_reload", calls)
        self.assertEqual((repair.LIVE / "fullchain.pem").read_text(), "original-fullchain")
        self.signal_mock.assert_any_call(signal.SIGHUP, signal.SIG_IGN)

    def test_production_change_is_detected_and_never_overwritten(self):
        calls = []
        def run(args, label, timeout=180):
            calls.append(label)
            if label == "acme_preflight":
                repair.PROTECTED[0].write_text("unexpected external change")
            return self.fake_run(args, label, timeout)
        with patch.object(repair, "certificate_ready", return_value=False), self.assertRaisesRegex(repair.RepairError, "manual_recovery"):
            repair.repair(run)
        self.assertEqual(repair.PROTECTED[0].read_text(), "unexpected external change")
        self.assertNotIn("nginx_reload", calls)
        self.assertNotIn("rollback_reload", calls)
        self.assertNotIn("acme_issue", calls)

    def test_tls_or_renewal_failure_rolls_back(self):
        for failing in ("https", "renewal_dry_run"):
            with self.subTest(failing=failing), patch.object(repair, "certificate_ready", return_value=True):
                calls = []
                def run(args, label, timeout=180):
                    calls.append(label)
                    if label == failing:
                        raise repair.RepairError("forced_failure")
                    return self.fake_run(args, label, timeout)
                with self.assertRaises(repair.RepairError):
                    repair.repair(run)
                self.assertIn("rollback_reload", calls)

    def test_wrong_redirect_or_canonical_non_200_rejected(self):
        for headers in ("HTTP/2 302\r\nlocation: https://example.com/agenda\r\n", "HTTP/2 500\r\n"):
            with self.assertRaises(repair.RepairError):
                repair.verify_https(lambda *args: headers)

    def test_certificate_requires_exact_sans_and_validity(self):
        for names, expected in ((repair.DOMAINS, True), (repair.DOMAINS[:2], False)):
            result = repair.certificate_ready(lambda *args: ", ".join("DNS:" + name for name in names))
            self.assertEqual(result, expected)
        with self.assertRaises(repair.RepairError):
            repair.certificate_ready(lambda *args: "DNS:fortcordis.com.br")


class WorkflowGuardTest(unittest.TestCase):
    def run_blocks(self):
        return re.findall(r"        run: \|\n((?:          .*\n|\n)+)", WORKFLOW)

    def test_ref_guard_executed_not_only_text_matched(self):
        guard = "\n".join(line[10:] for line in self.run_blocks()[0].splitlines())
        for ref, expected in (("refs/heads/stage", 0), ("refs/heads/main", 1), ("refs/heads/codex/foo", 1)):
            result = subprocess.run(["/bin/bash", "-c", guard], env={"DISPATCH_REF": ref, "DISPATCH_SHA": "a" * 40}, capture_output=True)
            self.assertEqual(result.returncode, expected)

    def test_shell_blocks_parse_and_credentials_never_interpolate_remote_command(self):
        for block in self.run_blocks():
            source = "\n".join(line[10:] for line in block.splitlines())
            result = subprocess.run(["/bin/bash", "-n"], input=source, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ssh-keyscan", WORKFLOW)
        self.assertNotIn("StrictHostKeyChecking=no", WORKFLOW)
        self.assertNotIn("environment: production", WORKFLOW)
        self.assertIn("ref: ${{ github.sha }}", WORKFLOW)
        self.assertIn("group: fortcordis-vps-deploy", WORKFLOW)
        self.assertIn("'/usr/bin/python3', '-I', '-c', bootstrap", WORKFLOW)
        self.assertIn("printf '%s\\n' \"$VPS_SUDO_PASSWORD\" | ssh", WORKFLOW)
        self.assertNotRegex(WORKFLOW, r"run: \|[\s\S]*?\$\{\{ secrets\.VPS_SUDO_PASSWORD \}\}[^\n]*ssh")

    def test_privileged_bootstrap_rejects_bad_digest_before_payload(self):
        bootstrap = re.search(r"bootstrap = '''(.*?)'''", WORKFLOW, re.S).group(1)
        bootstrap = bootstrap.replace("\n          ", "\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.py"
            marker = Path(directory) / "executed"
            path.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('yes')\n")
            rejected = subprocess.run([sys.executable, "-c", bootstrap, str(path), "0" * 64, "a" * 40], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(marker.exists())
            accepted = subprocess.run([sys.executable, "-c", bootstrap, str(path), hashlib.sha256(path.read_bytes()).hexdigest(), "a" * 40], capture_output=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertTrue(marker.exists())

    def test_cli_rejects_non_stage_without_running_any_commands(self):
        path = ROOT / "scripts/repair_stage_alias_tls.py"
        result = subprocess.run([sys.executable, str(path), "--execute-stage-alias", "--source-ref", "refs/heads/main",
                                 "--source-sha", "a" * 40, "--script-sha256", hashlib.sha256(path.read_bytes()).hexdigest()], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "execution_guard_rejected")


if __name__ == "__main__":
    unittest.main()
