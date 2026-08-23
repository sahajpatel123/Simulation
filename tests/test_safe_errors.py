"""Tests for app.core.safe_errors."""

from __future__ import annotations

import socket

from sqlalchemy.exc import OperationalError

from app.core.safe_errors import safe_error_label


def test_safe_error_label_returns_class_name_only() -> None:
    exc = RuntimeError("host db-1.internal; password=hunter2")
    label = safe_error_label(exc)

    assert label == "RuntimeError"
    assert "hunter2" not in label


def test_safe_error_label_distinguishes_exception_types() -> None:
    assert safe_error_label(TimeoutError("late")) == "TimeoutError"
    assert safe_error_label(socket.gaierror("name resolution")) == "gaierror"


def test_safe_error_label_handles_library_exceptions() -> None:
    # SQLAlchemy exceptions carry SQL fragments in their args; the label
    # exposes none of that.
    try:
        raise OperationalError("SELECT * FROM secrets", {}, Exception("boom"))
    except OperationalError as exc:
        label = safe_error_label(exc)

    assert label == "OperationalError"
    assert "secrets" not in label and "boom" not in label
