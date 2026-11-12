"""Read-only stage journal summary. Never emit payloads, SQL or error messages."""
from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

EVENTS = (
    "Failed to persist webhook event",
    "PostgreSQL query failed",
    "Unexpected PostgreSQL pool error",
)
CODE = re.compile(r"^(?:[0-9A-Z]{5}|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EPIPE|ENOTFOUND)$")
TIMESTAMP = re.compile(r"\[(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\]")


def classify(message: str, code: str | None) -> str:
    value = message.lower()
    if code == "53300" or any(term in value for term in (
        "maxclients", "max client", "too many clients", "connection slots",
        "connection limit", "too many connections",
    )):
        return "connection_capacity"
    if code == "28P01" or "authentication failed" in value or "password authentication" in value:
        return "authentication_failure"
    if "timeout" in value or "timed out" in value or code == "ETIMEDOUT":
        return "timeout"
    if "certificate" in value or "ssl" in value or "tls" in value:
        return "tls_failure"
    if code in ("ECONNRESET", "ECONNREFUSED", "EPIPE", "ENOTFOUND", "08006", "08001") or any(
        term in value for term in ("connection terminated", "connection reset", "pooler is not healthy")
    ):
        return "connection_unavailable"
    if code == "23505":
        return "uniqueness_conflict"
    return "database_error"


def summarize(journal: str) -> dict:
    counts = collections.Counter()
    timestamps = []
    for line in journal.splitlines():
        event = next((event for event in EVENTS if event in line), None)
        if event is None:
            continue
        try:
            meta = json.loads(line[line.index("{", line.index(event)):])
        except (ValueError, json.JSONDecodeError):
            meta = {}
        details = meta.get("details", meta) if isinstance(meta, dict) else {}
        if not isinstance(details, dict):
            details = {}
        raw_code = details.get("code")
        code = raw_code if isinstance(raw_code, str) and CODE.fullmatch(raw_code) else None
        # The raw message is used only to classify; none of its words leave the host.
        message = str(details.get("message") or "")
        for inner in details.get("inner_errors") or []:
            if isinstance(inner, dict):
                message += " " + str(inner.get("message") or "")
        counts[(event, code, classify(message, code))] += 1
        timestamp = TIMESTAMP.search(line)
        if timestamp:
            timestamps.append(timestamp.group(1))
    return {
        "scope": "stage_whatsapp_persistence",
        "events_found": sum(counts.values()),
        "first_seen": min(timestamps) if timestamps else None,
        "last_seen": max(timestamps) if timestamps else None,
        "errors": [
            {"event": event, "code": code, "category": category, "count": count}
            for (event, code, category), count in sorted(counts.items(), key=lambda item: str(item[0]))
        ],
    }



def stage_state() -> dict:
    """Only immutable code identity, enum service states, HTTP codes and a flag."""
    commit = subprocess.run(["git", "-C", "/var/www/fortcordis-stage", "rev-parse", "HEAD"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False).stdout.strip()
    services = {}
    for unit in ("fortcordis-stage-backend", "fortcordis-stage-backend-worker",
                 "fortcordis-stage-frontend", "fortcordis-stage-whatsapp-backend"):
        value = subprocess.run(["systemctl", "is-active", unit], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False).stdout.strip()
        services[unit] = value if value in {"active", "inactive", "activating", "deactivating", "failed"} else "unknown"
    process = subprocess.run(["pgrep", "-f", r"scripts/deploy_(prod|stage)_vps\.sh"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
    probes = {}
    for name, url in (("backend_ready", "http://127.0.0.1:8001/ready"),
                      ("whatsapp_health", "http://127.0.0.1:3010/health")):
        try:
            with urlopen(url, timeout=10) as response:
                probes[name] = response.status
        except HTTPError as error:
            probes[name] = error.code
        except (URLError, TimeoutError):
            probes[name] = None
    return {
        "head": commit if re.fullmatch(r"[a-f0-9]{40}", commit) else None,
        "services": services, "probes": probes,
        "deployment_process_running": process.returncode == 0,
    }


def main() -> int:
    password = sys.stdin.readline().removesuffix("\n")
    result = subprocess.run(
        ["sudo", "-S", "-p", "", "journalctl", "-u", "fortcordis-stage-whatsapp-backend",
         "--since", "2 hours ago", "--no-pager", "-n", "5000", "-o", "cat"],
        input=password + "\n", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=45, check=False,
    )
    if result.returncode:
        print(json.dumps({"scope": "stage_whatsapp_persistence", "status": "journal_read_failed"}))
        return 1
    summary = summarize(result.stdout)
    summary["stage_state"] = stage_state()
    print(json.dumps(summary, sort_keys=True))
    # A cancelled SSH job may leave a remote installation/rollback in flight.
    # Keep the deploy dependency blocked until a later read sees it finished.
    return 1 if summary["stage_state"]["deployment_process_running"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
