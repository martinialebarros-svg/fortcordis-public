from __future__ import annotations

import os
import shutil


_COMMON_TESSERACT_PATHS = (
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
    "/opt/local/bin/tesseract",
)


def resolve_tesseract_command() -> str:
    configured = (os.getenv("TESSERACT_CMD") or "").strip()
    if configured:
        if os.path.isabs(configured):
            return configured
        discovered = shutil.which(configured)
        if discovered:
            return discovered
        if configured.lower() != "tesseract":
            return configured

    common_windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.name == "nt" and os.path.isfile(common_windows_path):
        return common_windows_path

    discovered = shutil.which("tesseract")
    if discovered:
        return discovered

    for candidate in _COMMON_TESSERACT_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return "tesseract"
