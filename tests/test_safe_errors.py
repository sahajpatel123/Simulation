"""Tests for app.core.safe_errors."""

from __future__ import annotations

import socket

import pytest
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError

from app.core.safe_errors import safe_error_label


def test_safe_error_label_returns_fixed_vocabulary_only() -> None:
    # The message carries credentials and hostnames; none of it may leak.
    exc = RuntimeError("host db-1.internal; password=hunter2")
    label = safe_error_label(exc)

    assert label == "internal_error"
    assert "hunter2" not in label
    assert "db-1.internal" not in label
    assert "RuntimeError" not in label


def test_safe_error_label_distinguishes_dependency_classes() -> None:
    assert safe_error_label(TimeoutError("late")) == "timeout"
    assert safe_error_label(socket.gaierror("name resolution")) == "dns_failure"
    assert safe_error_label(ConnectionError("refused")) == "connection_failed"


def test_safe_error_label_handles_library_exceptions() -> None:
    # SQLAlchemy exceptions carry SQL fragments in their args; the label
    # exposes none of that.
    try:
        raise OperationalError("SELECT * FROM secrets", {}, Exception("boom"))
    except OperationalError as exc:
        label = safe_error_label(exc)

    assert label == "database_unavailable"
    assert "secrets" not in label and "boom" not in label


def test_safe_error_label_maps_cache_failures() -> None:
    assert safe_error_label(RedisError("pool exhausted")) == "cache_unavailable"


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("x=1"),
        KeyError("secret_key"),
        Exception("SELECT * FROM users; --"),
    ],
    ids=["value", "key", "generic"],
)
def test_safe_error_label_never_echoes_exception_content(exc: Exception) -> None:
    label = safe_error_label(exc)

    assert label in {
        "timeout",
        "dns_failure",
        "connection_failed",
        "database_unavailable",
        "database_error",
        "cache_unavailable",
        "internal_error",
    }
    assert str(exc) not in label
