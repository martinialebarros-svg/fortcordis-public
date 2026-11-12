#!/usr/bin/env python3
"""One-shot, fixed-target HTTP-01 repair. Invoke only through its stage workflow.

No credentials are accepted here: sudo consumes the password from SSH stdin.
Command output stays private; the audit stream contains status and paths only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import uuid


IP = "216.238.116.77"
HOSTNAME = "fortcordis-vps"
DOMAINS = ("stage.fortcordis.com.br", "app.stage.fortcordis.com.br", "www.stage.fortcordis.com.br")
LINEAGE = DOMAINS[0]
VHOST = Path("/etc/nginx/sites-available/fortcordis-stage")
LIVE = Path("/etc/letsencrypt/live") / LINEAGE
ARCHIVE = Path("/etc/letsencrypt/archive") / LINEAGE
RENEWAL = Path("/etc/letsencrypt/renewal") / (LINEAGE + ".conf")
BACKUP_ROOT = Path("/var/backups/fortcordis-stage-alias")
GLOBAL_CONFIGS = (Path("/etc/letsencrypt/cli.ini"), Path("/root/.config/letsencrypt/cli.ini"))
STAGE_PATHS = (VHOST, LIVE, ARCHIVE, RENEWAL)
PROTECTED = tuple(Path(p) for p in (
    "/etc/nginx/sites-available/fortcordis-app",
    "/etc/nginx/sites-available/fortcordis-com-br",
    "/etc/nginx/sites-available/fortcordis-www",
    "/etc/letsencrypt/live/app.fortcordis.com.br/fullchain.pem",
    "/etc/letsencrypt/live/fortcordis.com.br/fullchain.pem",
    "/etc/letsencrypt/live/fortcordis.com/fullchain.pem",
    "/etc/nginx/nginx.conf",
    "/etc/letsencrypt/options-ssl-nginx.conf",
))
CERTBOT = ["/usr/bin/certbot", "certonly", "--nginx", "--non-interactive",
           "--no-directory-hooks", "--cert-name", LINEAGE, "--expand"]
for _domain in DOMAINS:
    CERTBOT += ["-d", _domain]


class RepairError(Exception):
    pass


def emit(status, **fields):
    print(json.dumps({"status": status, **fields}, sort_keys=True), flush=True)


class Commands:
    def __init__(self):
        self.active = None

    def stop(self):
        if self.active is not None and self.active.poll() is None:
            os.killpg(self.active.pid, signal.SIGINT)
            try:
                self.active.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.active.pid, signal.SIGKILL)
                self.active.wait()

    def __call__(self, args, label, timeout=180):
        # Never inherit the SSH/sudo input stream or secret-bearing CI environment.
        with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True,
                              env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root",
                                   "LANG": "C", "LC_ALL": "C"}) as process:
            self.active = process
            try:
                out, _ = process.communicate(timeout=timeout)
                if process.returncode:
                    raise RepairError(label + "_failed")
                return out.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                self.stop()
                raise RepairError(label + "_timeout") from None
            finally:
                self.active = None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(paths):
    return {str(path): digest(path) for path in paths}


def require_hashes(expected, label):
    if hashes(map(Path, expected)) != expected:
        raise RepairError(label + "_changed")


def validate_dns(run):
    # Two public resolvers; reject a proxy address, an unexpected AAAA or stale NXDOMAIN.
    for resolver in ("1.1.1.1", "8.8.8.8"):
        def query(domain, kind):
            answer = run(["/usr/bin/dig", "@" + resolver, domain, kind, "+short",
                          "+time=5", "+tries=1"], "dns", 10)
            return {line.rstrip(".") for line in answer.splitlines() if line.strip()}
        if query(DOMAINS[2], "CNAME") != {LINEAGE}:
            raise RepairError("alias_cname_not_ready")
        for domain in DOMAINS:
            addresses = query(domain, "A") - {LINEAGE}
            if addresses != {IP} or query(domain, "AAAA") - {LINEAGE}:
                raise RepairError("dns_not_direct_to_stage")


def validate_layout():
    conf = VHOST.read_text()
    names = set(re.findall(r"server_name\s+([^;]+);", conf))
    if not names or any(set(names_line.split()) != set(DOMAINS) for names_line in names):
        raise RepairError("stage_vhost_names_unexpected")
    upstreams = set(re.findall(r"proxy_pass\s+([^;]+);", conf))
    if upstreams != {"http://127.0.0.1:3001", "http://127.0.0.1:8001"}:
        raise RepairError("stage_upstreams_unexpected")
    for directive, expected in (("ssl_certificate", LIVE / "fullchain.pem"),
                                ("ssl_certificate_key", LIVE / "privkey.pem")):
        if set(re.findall(r"\b" + directive + r"\s+([^;]+);", conf)) != {str(expected)}:
            raise RepairError("stage_certificate_path_unexpected")
    for name in ("cert.pem", "chain.pem", "fullchain.pem", "privkey.pem"):
        link = LIVE / name
        if not link.is_symlink() or link.resolve().parent != ARCHIVE:
            raise RepairError("stage_lineage_unexpected")
    renewal = RENEWAL.read_text()
    if not re.search(r"^authenticator\s*=\s*nginx\s*$", renewal, re.M):
        raise RepairError("stage_authenticator_unexpected")
    hook_key = r"^\s*(?:--)?(?:pre[-_]hook|post[-_]hook|renew[-_]hook|deploy[-_]hook)(?=$|[\s:=])"
    if re.search(hook_key, renewal, re.M):
        raise RepairError("stage_renewal_hook_present")
    for config in GLOBAL_CONFIGS:
        if config.exists():
            value = config.read_text()
            if re.search(hook_key, value, re.M):
                raise RepairError("certbot_global_hook_present")
            if re.search(r"^\s*(?:--)?(?:server|config[-_]dir|work[-_]dir|logs[-_]dir)(?=$|[\s:=])", value, re.M):
                raise RepairError("certbot_global_override_present")


class Backup:
    def __init__(self):
        base = BACKUP_ROOT
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="repair-", dir=base))
        self.protected = hashes(PROTECTED)
        self.vhost = hashes([VHOST])
        self.stage_files = {}
        self.modes = {}
        for source in STAGE_PATHS:
            destination = self.path / source.relative_to("/")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
                for item in source.iterdir():
                    if not item.is_dir():
                        self.stage_files[str(item)] = ("link", os.readlink(item)) if item.is_symlink() else ("sha256", digest(item))
                        self.modes[str(item)] = stat.S_IMODE(item.lstat().st_mode)
            else:
                shutil.copy2(source, destination)
                self.stage_files[str(source)] = ("sha256", digest(source))
                self.modes[str(source)] = stat.S_IMODE(source.stat().st_mode)
        # Backup includes private keys; parent is 0700, regular copies are 0600.
        for item in self.path.rglob("*"):
            if not item.is_symlink():
                item.chmod(0o700 if item.is_dir() else 0o600)
        self.checkpoint("prepared")

    def checkpoint(self, status):
        (self.path / "manifest.json").write_text(json.dumps({
            "status": status, "protected": self.protected, "stage_files": self.stage_files,
            "modes": self.modes,
        }, indent=2))
        (self.path / "manifest.json").chmod(0o600)

    def restore(self):
        # Restore archive bytes before live symlinks, then the stage vhost/renewal.
        # New, unused archive versions are retained, never recursively deleted.
        for destination in (ARCHIVE, LIVE, VHOST, RENEWAL):
            source = self.path / destination.relative_to("/")
            pairs = [(item, destination / item.name) for item in source.iterdir()] if source.is_dir() else [(source, destination)]
            for original, target in pairs:
                temporary = target.with_name(target.name + ".stage-alias-" + uuid.uuid4().hex)
                if original.is_symlink():
                    temporary.symlink_to(os.readlink(original))
                else:
                    shutil.copy2(original, temporary)
                    temporary.chmod(self.modes[str(target)])
                os.replace(temporary, target)
        for path, (kind, expected) in self.stage_files.items():
            actual = os.readlink(path) if kind == "link" else digest(Path(path))
            if actual != expected:
                raise RepairError("stage_restore_verification_failed")
        self.checkpoint("restored")


def certificate_ready(run):
    output = run(["/usr/bin/openssl", "x509", "-in", str(LIVE / "fullchain.pem"),
                  "-noout", "-ext", "subjectAltName"], "certificate_sans")
    names = set(re.findall(r"DNS:([^,\s]+)", output))
    if names != set(DOMAINS):
        if not names.issubset(set(DOMAINS)):
            raise RepairError("certificate_has_unexpected_names")
        return False
    try:
        run(["/usr/bin/openssl", "x509", "-in", str(LIVE / "fullchain.pem"),
             "-noout", "-checkend", "2592000"], "certificate_validity")
    except RepairError:
        return False
    return True


def verify_https(run):
    for domain in DOMAINS:
        headers = run(["/usr/bin/curl", "--silent", "--show-error", "--fail", "--max-time", "20",
                      "--resolve", domain + ":443:" + IP, "--output", "/dev/null",
                      "--dump-header", "-", "https://" + domain + "/agenda"], "https", 30)
        statuses = re.findall(r"^HTTP/\S+\s+(\d{3})", headers, re.M)
        status = statuses[-1] if statuses else ""
        locations = re.findall(r"^location:\s*(.*?)\s*$", headers, re.M | re.I)
        if domain == DOMAINS[1]:
            if status != "200":
                raise RepairError("canonical_https_not_200")
        elif status not in {"301", "302", "307", "308"} or locations != ["https://" + DOMAINS[1] + "/agenda"]:
            raise RepairError("stage_redirect_unexpected")
        emit("https_ok", host=domain, http_status=int(status))


def repair(run):
    validate_layout()
    validate_dns(run)
    run(["/usr/sbin/nginx", "-t"], "nginx_preflight")
    ready = certificate_ready(run)
    backup = Backup()
    emit("backup_ready", path=str(backup.path), protected_files=len(backup.protected))
    try:
        backup.checkpoint("in_progress")
        if not ready:
            run(CERTBOT + ["--dry-run"], "acme_preflight", 300)
            require_hashes(backup.protected, "protected_files")
            require_hashes(backup.vhost, "stage_vhost")
            run(CERTBOT, "acme_issue", 300)
        if not certificate_ready(run):
            raise RepairError("issued_certificate_invalid")
        require_hashes(backup.protected, "protected_files")
        require_hashes(backup.vhost, "stage_vhost")
        validate_layout()
        run(["/usr/sbin/nginx", "-t"], "nginx_after_issue")
        run(["/bin/systemctl", "reload", "nginx"], "nginx_reload")
        verify_https(run)
        run(["/usr/bin/certbot", "renew", "--cert-name", LINEAGE, "--dry-run",
             "--non-interactive", "--no-directory-hooks", "--disable-renew-updates",
             "--no-random-sleep-on-renew"], "renewal_dry_run", 300)
        require_hashes(backup.protected, "protected_files")
        require_hashes(backup.vhost, "stage_vhost")
        run(["/usr/sbin/nginx", "-t"], "nginx_final")
        verify_https(run)
        backup.checkpoint("complete")
        emit("complete", issued=not ready, sans=len(DOMAINS), protected_files=len(backup.protected))
    except (Exception, KeyboardInterrupt):
        # Do not interrupt rollback twice; a hard kill still requires operator recovery.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        backup.restore()
        require_hashes(backup.protected, "protected_files_manual_recovery_required")
        run(["/usr/sbin/nginx", "-t"], "rollback_nginx")
        run(["/bin/systemctl", "reload", "nginx"], "rollback_reload")
        emit("rolled_back", path=str(backup.path), protected_files=len(backup.protected))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-stage-alias", action="store_true")
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--script-sha256", required=True)
    args = parser.parse_args()
    if (not args.execute_stage_alias or args.source_ref != "refs/heads/stage"
            or not re.fullmatch(r"[0-9a-f]{40}", args.source_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", args.script_sha256)
            or digest(Path(__file__)) != args.script_sha256
            or os.geteuid() != 0 or socket.gethostname() != HOSTNAME
            or not Path("/var/www/fortcordis-stage").is_dir()):
        emit("execution_guard_rejected")
        return 2
    os.umask(0o077)
    run = Commands()
    def interrupted(signum, frame):
        run.stop()
        raise RepairError("interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        emit("stage_alias_repair", source_sha=args.source_sha)
        repair(run)
        return 0
    except RepairError as exc:
        emit("failed", reason=str(exc))
    except Exception:
        # Do not expose arbitrary command output, certificate/key contents or environment.
        emit("failed", reason="unexpected_error")
    return 1


if __name__ == "__main__":
    sys.exit(main())
