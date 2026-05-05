from __future__ import annotations

import html
import re
from typing import Any

MAX_DESCRIPTION_LENGTH = 5000
MAX_ASSUMPTION_LENGTH = 500
MAX_FIELD_LENGTH = 200

DANGEROUS_PATTERNS = [
    r"<script[^>]*>.*?</script>",
    r"javascript:",
    r"on\w+\s*=",
    r"data:text/html",
    r"vbscript:",
]


def sanitise_text(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    """Remove dangerous patterns and enforce length limit."""
    if not text:
        return ""
    t = html.escape(str(text))
    for pattern in DANGEROUS_PATTERNS:
        t = re.sub(pattern, "", t, flags=re.IGNORECASE | re.DOTALL)
    return t[:max_length].strip()


def sanitise_description(text: str) -> str:
    return sanitise_text(text, MAX_DESCRIPTION_LENGTH)


def sanitise_assumption(text: str) -> str:
    return sanitise_text(text, MAX_ASSUMPTION_LENGTH)


def sanitise_dict(data: dict[str, Any], max_length: int = MAX_FIELD_LENGTH) -> dict[str, Any]:
    """Recursively sanitise all string values in a dict."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = sanitise_text(v, max_length)
        elif isinstance(v, dict):
            result[k] = sanitise_dict(v, max_length)  # type: ignore[assignment]
        elif isinstance(v, list):
            result[k] = [
                sanitise_text(i, max_length) if isinstance(i, str) else i for i in v
            ]
        else:
            result[k] = v
    return result
