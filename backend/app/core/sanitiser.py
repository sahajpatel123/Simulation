from __future__ import annotations

import html
import re
from typing import Any

MAX_DESCRIPTION_LENGTH = 5000
MAX_ASSUMPTION_LENGTH = 500
MAX_FIELD_LENGTH = 200

# Whitespace allowed between dangerous URI scheme and the colon — e.g.
# "javascript\t:alert(1)" still resolves to a javascript: URL in some
# browsers. The trailing colon is required so we don't erase the
# legitimate word "javascript" wherever it appears in prose.
_DANGEROUS_URI_SCHEMES = r"(?:javascript|vbscript|data)"
# Touched:
#   - Anchor `<script>` content so attempts to split the tag (e.g. with
#     newlines or self-closing variants) still match.
#   - Require an `=` after on*-handler names so we don't drop substrings
#     like "onclick" in plain English ("the onclick handler").
#   - Use [:/\s]* to handle whitespace and lines between "data" and the
#     embedded "text/html" / "text/javascript" payload.
_DANGEROUS_TAG_PATTERN = (
    r"<script\b[^>]*>.*?</script\s*>"
    r"|<script\b[^>]*>"
    r"|</script\s*>"
)
_DANGEROUS_DATA_PATTERN = r"\bdata\s*[:/]\s*text\s*/\s*(?:html|javascript)\b"
_DANGEROUS_ATTR_PATTERN = r"\bon[a-z]+\s*=\s*['\"]?[^'\">\s]+"

DANGEROUS_PATTERNS = [
    _DANGEROUS_TAG_PATTERN,
    rf"\b{_DANGEROUS_URI_SCHEMES}\s*:",
    _DANGEROUS_ATTR_PATTERN,
    _DANGEROUS_DATA_PATTERN,
    rf"\b{_DANGEROUS_URI_SCHEMES}\s*=\s*['\"]?[^'\">\s]+",
]


def sanitise_text(text: str, max_length: int = MAX_FIELD_LENGTH) -> str:
    """Remove dangerous patterns and enforce length limit.

    The sanitiser is the last line of defence before user-supplied text
    reaches the database or the LLM. Order matters:

      1. HTML-escape first so angle brackets and ampersands become
         inert. This kills `<script>` BEFORE we try to drop it via
         regex (the regex needs to match the *raw* form).
      2. Strip dangerous URI schemes (javascript:, vbscript:, data:
         text/html / data: text/javascript) — the regex now requires a
         literal colon after the scheme, tolerating whitespace between
         the scheme and the colon so "javascript\t:alert(1)" still
         matches.
      3. Strip HTML on*-handler attributes — the regex now requires the
         `=` sign so we don't damage prose like "onclick is preferred".
      4. Truncate to ``max_length`` then strip outer whitespace.
    """
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
