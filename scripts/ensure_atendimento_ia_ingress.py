#!/usr/bin/env python3
"""Opt-in, fixed-target Stage ingress adjustment. Never enables the AI feature.

Run the installed script through sudo after a successful immutable Stage deploy.
No secrets are read except selecting APP_ENV; child output is captured privately.
Nginx -T verifies disk configuration; an authenticated request over 60 seconds
must separately prove the active worker timeout before IA homologation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid


STAGE_ROOT = Path("/var/www/fortcordis-stage")
ENABLED = Path("/etc/nginx/sites-enabled/fortcordis-stage")
AVAILABLE = Path("/etc/nginx/sites-available/fortcordis-stage")
BACKUP_ROOT = Path("/var/backups/fortcordis-atendimento-ia-ingress")
TLS_INCLUDE = Path("/etc/letsencrypt/options-ssl-nginx.conf")
# Observed read-only on Stage. Accept no extra directives, nesting, variables,
# paths or includes; a future Certbot options update requires another review.
TLS_OPTIONS = {
    "ssl_session_cache": ["shared:le_nginx_SSL:10m"],
    "ssl_session_timeout": ["1440m"],
    "ssl_session_tickets": ["off"],
    "ssl_protocols": ["TLSv1.2", "TLSv1.3"],
    "ssl_prefer_server_ciphers": ["off"],
    "ssl_ciphers": ["ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
                    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
                    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
                    "DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384"],
}
OWNER_UID = 0
SCRIPT = "scripts/ensure_atendimento_ia_ingress.py"
HOSTS = {"stage.fortcordis.com.br", "app.stage.fortcordis.com.br", "www.stage.fortcordis.com.br"}
ROUTE = r"^/api/v1/atendimentos/[0-9]+/assistente/(transcrever|analisar)$"
BEGIN = "# BEGIN FORTCORDIS STAGE ATENDIMENTO IA INGRESS"
END = "# END FORTCORDIS STAGE ATENDIMENTO IA INGRESS"
DIRECTIVES = {
    "proxy_pass": "http://127.0.0.1:8001",
    "client_max_body_size": "30m",
    "proxy_read_timeout": "210s",
    "proxy_send_timeout": "210s",
}


class IngressError(Exception):
    pass


def emit(status, **fields):
    print(json.dumps({"status": status, **fields}, sort_keys=True), flush=True)


def run(args, label):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=30, check=True,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"})
        return result.stdout.decode("utf-8")
    except (subprocess.SubprocessError, OSError, UnicodeError):
        # Nginx -T and git output may contain secrets; never print either stream.
        raise IngressError(label + "_failed") from None


def tokens(text):
    """Small Nginx lexer: preserves source offsets, quoted values and comments."""
    result, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text[pos] == "#":
            end = text.find("\n", pos)
            pos = len(text) if end < 0 else end + 1
            continue
        start, value = pos, ""
        if text[pos] in "{};":
            result.append((text[pos], pos, pos + 1, True))
            pos += 1
            continue
        quote = None
        while pos < len(text):
            char = text[pos]
            if char == "\\" and pos + 1 < len(text):
                value += text[pos:pos + 2]
                pos += 2
                continue
            if quote:
                if char == quote:
                    quote = None
                else:
                    value += char
                pos += 1
                continue
            if char in "\"'":
                quote = char
                pos += 1
                continue
            if char == "$" and text[pos:pos + 2] == "${":
                end = text.find("}", pos + 2)
                if end < 0:
                    raise IngressError("invalid_variable")
                value += text[pos:end + 1]
                pos = end + 1
                continue
            if char.isspace() or char in "{};#":
                break
            value += char
            pos += 1
        if quote or pos == start:
            raise IngressError("invalid_nginx_token")
        result.append((value, start, pos, False))
    return result


def parse(text):
    stream = tokens(text)
    index = 0

    def nodes(nested=False):
        nonlocal index
        output = []
        while index < len(stream):
            if stream[index][3] and stream[index][0] == "}":
                if not nested:
                    raise IngressError("unexpected_closing_brace")
                end = stream[index][1]
                index += 1
                return output, end
            start, words = stream[index][1], []
            while index < len(stream) and not stream[index][3]:
                words.append(stream[index][0])
                index += 1
            if not words or index == len(stream) or stream[index][0] == "}":
                raise IngressError("invalid_nginx_statement")
            delimiter = stream[index]
            index += 1
            if delimiter[0] == "{":
                children, body_end = nodes(True)
                output.append({"words": words, "start": start, "end": body_end + 1,
                               "body_start": delimiter[2], "body_end": body_end, "children": children})
            else:
                output.append({"words": words, "start": start, "end": delimiter[2], "children": None})
        if nested:
            raise IngressError("unclosed_nginx_block")
        return output, len(text)

    return nodes()[0]


def validate_tls_content(text):
    directives = parse(text)
    if (len(directives) != len(TLS_OPTIONS)
            or {node["words"][0] for node in directives} != set(TLS_OPTIONS)
            or any(node["children"] is not None
                   or node["words"][1:] != TLS_OPTIONS[node["words"][0]] for node in directives)):
        raise IngressError("tls_include_content_requires_explicit_review")


def read_tls_include(text):
    includes = [node for root in parse(text) for node in (root["children"] or [])
                if node["words"][0] == "include"]
    if not includes:
        return None
    if any(node["words"] != ["include", str(TLS_INCLUDE)] for node in includes):
        raise IngressError("server_include_requires_explicit_review")
    if TLS_INCLUDE.resolve(strict=True) != TLS_INCLUDE:
        raise IngressError("untrusted_tls_include_path")
    directory = TLS_INCLUDE.parent.stat()
    if directory.st_uid != OWNER_UID or directory.st_mode & 0o022:
        raise IngressError("untrusted_tls_include_directory")
    trusted_file(TLS_INCLUDE)
    content = TLS_INCLUDE.read_text()
    validate_tls_content(content)
    return content


def stage_api(text, tls_content=None):
    roots = parse(text)
    if not roots or any(node["words"] != ["server"] or node["children"] is None for node in roots):
        raise IngressError("unexpected_vhost_structure")
    candidates = []
    for server in roots:
        includes = [node for node in server["children"] if node["words"][0] == "include"]
        if includes:
            if (len(includes) != 1 or includes[0]["words"] != ["include", str(TLS_INCLUDE)]
                    or tls_content is None):
                raise IngressError("server_include_requires_explicit_review")
            validate_tls_content(tls_content)
        names = [n for n in server["children"] if n["words"][0] == "server_name"]
        if len(names) != 1 or not names[0]["words"][1:] or not set(names[0]["words"][1:]).issubset(HOSTS):
            raise IngressError("non_stage_server_name")
        locations = [n for n in server["children"] if n["words"][0] == "location"]
        api = [n for n in locations if n["words"] in (["location", "/api"], ["location", "/api/"])]
        if api:
            if len(api) != 1 or "app.stage.fortcordis.com.br" not in names[0]["words"]:
                raise IngressError("ambiguous_stage_api")
            candidates.append((server, api[0], locations))
    if len(candidates) != 1:
        raise IngressError("stage_api_not_unique")
    server, api, locations = candidates[0]
    if api["children"] is None or any(n["children"] is not None for n in api["children"]):
        raise IngressError("nested_api_directives_unsupported")
    passes = [n for n in api["children"] if n["words"][0] == "proxy_pass"]
    if len(passes) != 1 or passes[0]["words"] != ["proxy_pass", DIRECTIVES["proxy_pass"]]:
        raise IngressError("stage_upstream_must_be_8001_without_uri")
    if any(n["words"][0] in {"rewrite", "return", "try_files"} for n in api["children"]):
        raise IngressError("api_routing_unsupported")
    # Adding a first regex must not override auth/rate limits from another route.
    # Reject every unowned regex and potentially overlapping prefix/exact route.
    for location in locations:
        words = location["words"]
        if location is api or words == ["location", "~", ROUTE]:
            continue
        path = words[-1]
        api_prefix = "/api/v1/atendimentos/"
        if words[1:2] in (["~"], ["~*"]):
            raise IngressError("unowned_regex_location_unsupported")
        if path != "/" and (api_prefix.startswith(path) or path.startswith(api_prefix)):
            raise IngressError("overlapping_api_location_unsupported")
        if "assistente" in path:
            raise IngressError("conflicting_assistente_location")
        if location["children"] and any(n["words"][0] == "location" for n in location["children"]):
            raise IngressError("nested_locations_unsupported")
    return server, api, locations


def transform(text, tls_content=None):
    """Insert/reconcile only the owned block, leaving the generic API verbatim."""
    managed = re.compile(r"(?m)^[ \t]*" + re.escape(BEGIN) + r"\n.*?^[ \t]*" + re.escape(END) + r"\n?", re.S)
    matches = list(managed.finditer(text))
    if len(matches) > 1 or text.count(BEGIN) != len(matches) or text.count(END) != len(matches):
        raise IngressError("invalid_managed_markers")
    base = text
    if matches:
        match = matches[0]
        parsed = parse(match.group())
        if len(parsed) != 1 or parsed[0]["words"] != ["location", "~", ROUTE]:
            raise IngressError("managed_block_contains_unowned_content")
        base = text[:match.start()] + text[match.end():]
    _, api, locations = stage_api(base, tls_content)
    if any(n["words"] == ["location", "~", ROUTE] for n in locations):
        raise IngressError("unmanaged_assistente_location")
    body = base[api["body_start"]:api["body_end"]]
    edits = []
    seen = set()
    for node in api["children"]:
        key = node["words"][0]
        if key in DIRECTIVES:
            if key in seen:
                raise IngressError("duplicate_proxy_directive")
            seen.add(key)
            edits.append((node["start"] - api["body_start"], node["end"] - api["body_start"], f"{key} {DIRECTIVES[key]};"))
    for start, end, replacement in reversed(edits):
        body = body[:start] + replacement + body[end:]
    body = body.rstrip() + "\n"
    for key, value in DIRECTIVES.items():
        if key not in seen:
            body += f"        {key} {value};\n"
    first = min(location["start"] for location in locations)
    start = base.rfind("\n", 0, first) + 1
    if base[start:first].strip():
        raise IngressError("location_must_start_on_own_line")
    indent = base[start:first]
    block = f"{indent}{BEGIN}\n{indent}location ~ {ROUTE} {{{body}{indent}}}\n{indent}{END}\n"
    return base[:start] + block + base[start:]


def trusted_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER_UID or info.st_mode & 0o022 or info.st_nlink != 1:
        raise IngressError("untrusted_target_file")
    return info


def target_path():
    for directory in (ENABLED.parent, AVAILABLE.parent):
        if directory.resolve(strict=True) != directory:
            raise IngressError("symlinked_nginx_directory")
        info = directory.stat()
        if info.st_uid != OWNER_UID or info.st_mode & 0o022:
            raise IngressError("untrusted_nginx_directory")
    if ENABLED.is_symlink():
        link = os.readlink(ENABLED)
        if link not in {str(AVAILABLE), "../sites-available/fortcordis-stage"} or AVAILABLE.is_symlink():
            raise IngressError("unexpected_stage_symlink")
        target = AVAILABLE
    else:
        target = ENABLED
    trusted_file(target)
    if ENABLED.resolve(strict=True) != target:
        raise IngressError("unexpected_stage_target")
    for other in ENABLED.parent.iterdir():
        if other != ENABLED and other.resolve() == target:
            raise IngressError("stage_target_shared_by_other_vhost")
    return target


def validate_execution(expected_sha, execute, command=run):
    if not execute or not re.fullmatch(r"[0-9a-f]{40}", expected_sha) or os.geteuid() != 0:
        raise IngressError("explicit_stage_execution_required")
    if STAGE_ROOT.resolve(strict=True) != STAGE_ROOT or Path(__file__).resolve() != STAGE_ROOT / SCRIPT:
        raise IngressError("unexpected_installed_root")
    env_path = STAGE_ROOT / "backend/.env"
    if env_path.is_symlink() or not env_path.is_file():
        raise IngressError("stage_env_unavailable")
    values = re.findall(r"(?m)^\s*(?:export\s+)?APP_ENV\s*=\s*([^\n]*)$", env_path.read_text())
    if len(values) != 1 or not re.fullmatch(r"(?:stage|'stage'|\"stage\")\s*(?:#.*)?", values[0].strip()):
        raise IngressError("app_env_must_be_stage")
    if os.environ.get("APP_ENV", "stage") != "stage":
        raise IngressError("process_app_env_must_be_stage")
    git = ["/usr/bin/git", "-c", f"safe.directory={STAGE_ROOT}", "-C", str(STAGE_ROOT)]
    if command(git + ["rev-parse", "HEAD"], "installed_sha").strip() != expected_sha:
        raise IngressError("installed_sha_mismatch")
    source = command(git + ["show", f"{expected_sha}:{SCRIPT}"], "installed_script")
    if source != Path(__file__).read_text():
        raise IngressError("installed_script_differs_from_snapshot")


def atomic_write(target, data, metadata, attributes_from):
    fd, name = tempfile.mkstemp(prefix=".atendimento-ia-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(attributes_from, name)
        os.chown(name, metadata.st_uid, metadata.st_gid)
        os.chmod(name, stat.S_IMODE(metadata.st_mode))
        os.replace(name, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def effective_proof(dump, expected, target, tls_content=None):
    sections = re.split(r"(?m)^# configuration file ([^\n]+):\n", dump)
    found = [sections[i + 1] for i in range(1, len(sections), 2) if sections[i] in {str(ENABLED), str(target)}]
    if len(found) != 1 or found[0].strip() != expected.strip():
        raise IngressError("effective_stage_config_mismatch")
    if tls_content is not None:
        tls_found = [sections[i + 1] for i in range(1, len(sections), 2) if sections[i] == str(TLS_INCLUDE)]
        if len(tls_found) != 1 or tls_found[0].strip() != tls_content.strip():
            raise IngressError("effective_tls_include_mismatch")
        validate_tls_content(tls_found[0])
    _, _, locations = stage_api(found[0], tls_content)
    managed = [node for node in locations if node["words"] == ["location", "~", ROUTE]]
    if len(managed) != 1:
        raise IngressError("effective_location_missing")
    for key, value in DIRECTIVES.items():
        values = [node["words"][1:] for node in managed[0]["children"] if node["words"][0] == key]
        if values != [[value]]:
            raise IngressError("effective_directive_mismatch")
    # Sanitized allowlist only; never include cloned header/include/auth values.
    proof = {"evidence": "nginx_T_configuration_on_disk", "location": ROUTE, **DIRECTIVES,
             "cloned_directive_names": sorted({n["words"][0] for n in managed[0]["children"]})}
    if tls_content is not None:
        proof["validated_tls_include"] = {"path": str(TLS_INCLUDE),
                                          "sha256": hashlib.sha256(tls_content.encode()).hexdigest()}
    return proof


def apply_ingress(expected_sha, execute, command=run):
    validate_execution(expected_sha, execute, command)
    target = target_path()
    metadata = target.stat()
    original = target.read_bytes()
    try:
        original_text = original.decode("utf-8")
        tls_content = read_tls_include(original_text)
        candidate = transform(original_text, tls_content).encode("utf-8")
    except UnicodeError:
        raise IngressError("vhost_not_utf8") from None
    command(["/usr/sbin/nginx", "-t"], "nginx_preflight")
    if original == candidate:
        proof = effective_proof(command(["/usr/sbin/nginx", "-T"], "nginx_effective"), candidate.decode(), target, tls_content)
        emit("unchanged", expected_sha=expected_sha, effective=proof)
        return
    if BACKUP_ROOT.exists() and (BACKUP_ROOT.is_symlink() or BACKUP_ROOT.resolve() != BACKUP_ROOT):
        raise IngressError("untrusted_backup_root")
    parent_info = BACKUP_ROOT.parent.stat()
    if (BACKUP_ROOT.parent.resolve(strict=True) != BACKUP_ROOT.parent
            or parent_info.st_uid != OWNER_UID or parent_info.st_mode & 0o022):
        raise IngressError("untrusted_backup_parent")
    BACKUP_ROOT.mkdir(mode=0o700, exist_ok=True)
    backup_info = BACKUP_ROOT.stat()
    if backup_info.st_uid != OWNER_UID or backup_info.st_mode & 0o077:
        raise IngressError("untrusted_backup_permissions")
    backup = BACKUP_ROOT / uuid.uuid4().hex
    backup.mkdir(mode=0o700)
    saved = backup / "fortcordis-stage.conf"
    shutil.copy2(target, saved)
    saved.chmod(0o600)
    manifest = {"target": str(target), "sha256": hashlib.sha256(original).hexdigest(),
                "uid": metadata.st_uid, "gid": metadata.st_gid, "mode": stat.S_IMODE(metadata.st_mode),
                "expected_sha": expected_sha}
    (backup / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    (backup / "manifest.json").chmod(0o600)
    if saved.read_bytes() != original:
        raise IngressError("backup_verification_failed")
    emit("backup_ready", path=str(backup), sha256=manifest["sha256"])
    wrote = False
    try:
        if target_path() != target or target.read_bytes() != original:
            raise IngressError("target_changed_before_write")
        if read_tls_include(original_text) != tls_content:
            raise IngressError("tls_include_changed_before_write")
        wrote = True
        atomic_write(target, candidate, metadata, saved)
        command(["/usr/sbin/nginx", "-t"], "nginx_validation")
        command(["/bin/systemctl", "reload", "nginx"], "nginx_reload")
        proof = effective_proof(command(["/usr/sbin/nginx", "-T"], "nginx_effective"), candidate.decode(), target, tls_content)
        emit("complete", expected_sha=expected_sha, backup=str(backup), effective=proof)
    except (Exception, KeyboardInterrupt):
        if wrote:
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)
            try:
                if target_path() != target:
                    raise IngressError("rollback_target_changed")
                atomic_write(target, original, metadata, saved)
                os.utime(target, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                if target.read_bytes() != original:
                    raise IngressError("rollback_bytes_mismatch")
                command(["/usr/sbin/nginx", "-t"], "rollback_validation")
                command(["/bin/systemctl", "reload", "nginx"], "rollback_reload")
                emit("rolled_back", backup=str(backup))
            except Exception:
                raise IngressError("rollback_failed_manual_recovery_required") from None
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-stage-ingress", action="store_true")
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    def interrupted(signum, frame):
        raise IngressError("interrupted")
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        apply_ingress(args.expected_sha, args.apply_stage_ingress)
    except Exception as exc:
        emit("failed", reason=str(exc) if isinstance(exc, IngressError) else "unexpected_failure")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
