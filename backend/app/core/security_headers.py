from typing import Dict


API_CSP_POLICY = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def build_security_headers(path: str) -> Dict[str, str]:
    normalized_path = (path or "").strip() or "/"
    headers: Dict[str, str] = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
    }

    if normalized_path.startswith("/api/") or normalized_path in {"/health", "/ready"}:
        headers["Content-Security-Policy"] = API_CSP_POLICY

    return headers
