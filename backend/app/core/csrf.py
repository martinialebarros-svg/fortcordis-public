from __future__ import annotations

import hmac
from urllib.parse import urlparse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_EXEMPT_PATH_PREFIXES = (
    "/api/v1/auth/login",
)


def is_safe_method(method: str) -> bool:
    return (method or "").upper() in SAFE_METHODS


def is_csrf_exempt_path(path: str) -> bool:
    normalized = (path or "").strip()
    return any(normalized.startswith(prefix) for prefix in CSRF_EXEMPT_PATH_PREFIXES)


def should_protect_request(path: str, method: str, has_session_cookie: bool) -> bool:
    if not has_session_cookie:
        return False
    if is_safe_method(method):
        return False
    if is_csrf_exempt_path(path):
        return False
    return True


def normalize_origin(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().rstrip("/").lower()


def extract_origin_from_url(value: str | None) -> str:
    if not value:
        return ""

    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def is_trusted_origin(
    *,
    origin: str | None,
    referer: str | None,
    allowed_origins: set[str],
    request_origin: str | None,
) -> bool:
    normalized_allowed = {normalize_origin(item) for item in allowed_origins if item}
    request_origin_normalized = normalize_origin(request_origin)
    if request_origin_normalized:
        normalized_allowed.add(request_origin_normalized)

    normalized_origin = normalize_origin(origin)
    if normalized_origin:
        return normalized_origin in normalized_allowed

    referer_origin = normalize_origin(extract_origin_from_url(referer))
    if referer_origin:
        return referer_origin in normalized_allowed

    return False


def has_valid_csrf_token_pair(header_token: str | None, cookie_token: str | None) -> bool:
    if not header_token or not cookie_token:
        return False
    return hmac.compare_digest(header_token.strip(), cookie_token.strip())
