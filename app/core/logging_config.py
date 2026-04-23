from __future__ import annotations

import json
import logging
import re

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"(api[_-]?key[\"']?\s*[:=]\s*)[\"']?[\w-]+", r"\1[REDACTED]"),
    (r"(secret[\"']?\s*[:=]\s*)[\"']?[\w-]+", r"\1[REDACTED]"),
    (r"(password[\"']?\s*[:=]\s*)[\"']?\S+", r"\1[REDACTED]"),
    (r"(token[\"']?\s*[:=]\s*)[\"']?[\w.-]+", r"\1[REDACTED]"),
    (r"rzp_(test|live)_[\w]+", r"rzp_[REDACTED]"),
    (r"Bearer [\w.-]+", r"Bearer [REDACTED]"),
]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A002
        message = str(record.getMessage())
        for pattern, replacement in SENSITIVE_PATTERNS:
            message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        record.msg = message
        record.args = ()
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        return json.dumps(
            {
                "time": self.formatTime(record),
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.addFilter(SensitiveDataFilter())
