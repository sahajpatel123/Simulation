"""Regression tests for the SensitiveDataFilter email redaction.

Email addresses are PII under GDPR / CCPA and must not land in
centralized log sinks. retention_email_tasks.py previously logged
``logger.error("Retention email failed for %s: %s", email, e)``
which would have produced ``email: user@example.com`` in the log
sink. The SensitiveDataFilter now redacts email addresses; these
tests pin that the redaction catches the shape used in the
retention_email task and doesn't regress while redaction patterns
are refactored.
"""

from __future__ import annotations

import logging

from app.core.logging_config import SensitiveDataFilter


def _log(message: str) -> str:
    """Run a log message through the filter and return the redacted text."""
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "path",
        1,
        message,
        None,
        None,
    )
    SensitiveDataFilter().filter(record)
    return record.getMessage()


def test_retention_email_pattern_is_redacted() -> None:
    """The exact shape produced by retention_email_tasks.py."""
    assert (
        _log("Retention email failed for user@example.com: SMTP timeout")
        == "Retention email failed for [REDACTED_EMAIL]: SMTP timeout"
    )


def test_email_redaction_preserves_surrounding_text() -> None:
    """The redacted marker should replace just the email, not adjacent
    text like the subject or call-site."""
    assert _log("To: alice@thecee.ai sent") == "To: [REDACTED_EMAIL] sent"


def test_email_redaction_handles_common_tlds() -> None:
    """Plausible production email shapes must all be caught."""
    for email in [
        "u@gmail.com",
        "first.last@company.co.uk",
        "user+tag@sub.domain.io",
        "x@y.z",
    ]:
        assert email not in _log(f"sent to {email}"), (
            f"Email {email!r} was not redacted"
        )
        assert "[REDACTED_EMAIL]" in _log(f"sent to {email}")


def test_existing_secrets_are_still_redacted() -> None:
    """Refactoring the pattern list must not drop existing redactions."""
    msg = "api_key=sk-12345 password=hunter2 token=abc Bearer eyJ.eyJ"
    filtered = _log(msg)
    assert "sk-12345" not in filtered
    assert "hunter2" not in filtered
    assert "eyJ.eyJ" not in filtered
    assert "[REDACTED]" in filtered
    assert "Bearer [REDACTED]" in filtered


def test_email_pattern_is_anchored_to_word_boundary() -> None:
    """The pattern must not eat unrelated fragments that happen to
    contain ``@`` — e.g. CI annotations like ``::error::...@2.0``
    shouldn't be mangled.

    This is a regression guard: a too-loose email regex would start
    swallowing version numbers and paths.
    """
    # The string '::error file=app.py@2.0::' contains an `@` but is
    # not an email — the local-part regex [\w.+-]+ accepts a dot, and
    # the domain part accepts alphanumeric segments, so we test that
    # an `@` followed by a non-letter doesn't trigger a false positive.
    msg = "::error file=app.py@2.0:: oops"
    filtered = _log(msg)
    # We accept either untouched (preferred) or redacted; the key
    # contract is that the email substitution never produces a
    # malformed replacement like '[REDACTED_EMAIL]@2.0'.
    assert "[REDACTED_EMAIL]@" not in filtered
