from __future__ import annotations

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


def configure_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.addFilter(SensitiveDataFilter())
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
