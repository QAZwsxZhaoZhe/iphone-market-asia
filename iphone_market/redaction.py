from __future__ import annotations

import re


_SENSITIVE_HEADER = re.compile(
    r"(?im)\b(cookie|set-cookie|authorization)\s*:\s*(.*?)"
    r"(?=\s+\b(?:cookie|set-cookie|authorization)\s*:|$)"
)


def redact_sensitive(value: str | None) -> str | None:
    if value is None:
        return None
    return _SENSITIVE_HEADER.sub(r"\1: [已隐藏]", str(value))
