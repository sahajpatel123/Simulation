"""Tests for app.core.security.log_safe — anti-log-forging sanitizer.

py/log-injection defense: untrusted values interpolated into log lines
must not be able to forge additional entries via CR/LF.
"""
from __future__ import annotations

from app.core.security import log_safe


def test_strips_newline_log_forging() -> None:
    # A hostile Origin header trying to forge a follow-up log line.
    forged = "evil.com\n[WS] AUTH OK user=admin"
    out = log_safe(forged)

    assert "\n" not in out
    assert "\r" not in out
    assert "evil.com [WS] AUTH OK" in out


def test_strips_carriage_returns_and_control_chars() -> None:
    out = log_safe("a\rb\x00c\x1fd\x7fe")

    assert "\r" not in out and "\x00" not in out
    assert "\x1f" not in out and "\x7f" not in out


def test_benign_values_pass_through() -> None:
    assert log_safe("https://app.thecee.com") == "https://app.thecee.com"
    assert log_safe(12345) == "12345"
    assert log_safe(None) == "None"


def test_exception_messages_are_sanitized() -> None:
    try:
        raise ValueError("bad input for sim 7\ninjected: root login")
    except ValueError as exc:
        out = log_safe(exc)

    assert "\n" not in out
    assert "injected:" in out  # content preserved, structure neutralized
