"""Regression tests for the shared require_admin helper.

The admin authorization check was duplicated in
``backend/app/api/v1/analytics.py`` and ``backend/app/api/v1/calibration.py``.
A future change to one copy (e.g. adding an ``is_superuser`` flag,
whitelisting an additional env var, or tightening the comparison)
would not reach the others — a classic security smell.

``app.core.deps.require_admin`` is now the single source of truth.
These tests pin:

1. The helper lives at the shared path.
2. Both call sites import it.
3. The legacy ``_require_admin`` private wrappers still delegate
   correctly so any third caller of the private names keeps working
   during the migration window.
4. The shared helper accepts the same inputs the previous duplicates
   did (is_admin flag, ADMIN_EMAILS env var, case-insensitive email
   comparison).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.deps import require_admin


def _user(*, is_admin: bool = False, email: str | None = "u@e.com") -> MagicMock:
    u = MagicMock()
    u.is_admin = is_admin
    u.email = email
    return u


class TestIsAdminFlag:
    def test_is_admin_true_passes(self) -> None:
        # Should not raise even when ADMIN_EMAILS is empty.
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = ""
            require_admin(_user(is_admin=True))

    def test_is_admin_false_with_no_env_rejected(self) -> None:
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = ""
            with pytest.raises(HTTPException) as exc:
                require_admin(_user(is_admin=False, email="u@e.com"))
            assert exc.value.status_code == 403


class TestAdminEmailsEnv:
    def test_email_in_allowlist_passes(self) -> None:
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = "alice@example.com,bob@example.com"
            require_admin(_user(is_admin=False, email="alice@example.com"))

    def test_email_case_insensitive(self) -> None:
        """Stored email casing must not matter — the env list is
        lowercased before comparison."""
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = "alice@example.com"
            require_admin(_user(is_admin=False, email="Alice@Example.com"))

    def test_email_not_in_allowlist_rejected(self) -> None:
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = "alice@example.com,bob@example.com"
            with pytest.raises(HTTPException):
                require_admin(_user(is_admin=False, email="eve@example.com"))

    def test_no_email_rejected(self) -> None:
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = "alice@example.com"
            with pytest.raises(HTTPException):
                require_admin(_user(is_admin=False, email=None))

    def test_empty_admin_emails_is_ignored(self) -> None:
        """Empty ADMIN_EMAILS must not accidentally grant access to
        every user — the comparison set would be empty and ``in``
        would still raise."""
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = ""
            with pytest.raises(HTTPException):
                require_admin(_user(is_admin=False, email="anyone@example.com"))

    def test_whitespace_only_entries_filtered(self) -> None:
        with patch("app.core.deps.settings") as s:
            s.ADMIN_EMAILS = "  ,alice@example.com, ,"
            require_admin(_user(is_admin=False, email="alice@example.com"))


def test_shared_helper_is_importable():
    """Pin the public path so a future refactor that moves the helper
    is intentional, not accidental."""
    from app.core import deps

    assert hasattr(deps, "require_admin")


def test_legacy_wrappers_in_both_modules_delegate():
    """Both modules still expose ``_require_admin`` as a private alias
    for back-compat. The alias must delegate to the shared helper —
    not carry its own (potentially divergent) copy of the rule."""
    import importlib.util
    import sys
    from pathlib import Path

    # Bypass the package __init__ chain (which imports razorpay etc.)
    # by loading each module directly via spec.
    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    base = Path(__file__).resolve().parents[1] / "backend" / "app" / "api" / "v1"
    # The legacy wrappers still exist
    analytics = _load("analytics_under_test", base / "analytics.py")
    calibration = _load("calibration_under_test", base / "calibration.py")
    assert callable(analytics._require_admin)
    assert callable(calibration._require_admin)

    # And they're simple delegations to the shared helper. Patch the
    # analytics module's own reference (since it did
    # ``from app.core.deps import require_admin``) and assert the
    # legacy wrapper calls it.
    sentinel_user = _user(is_admin=False, email="x@y.com")
    with patch("app.core.deps.settings") as s, patch.object(
        analytics, "require_admin"
    ) as mock_helper:
        s.ADMIN_EMAILS = ""
        mock_helper.side_effect = lambda u: None
        analytics._require_admin(sentinel_user)
        mock_helper.assert_called_once_with(sentinel_user)
    # Same for calibration
    with patch("app.core.deps.settings") as s, patch.object(
        calibration, "require_admin"
    ) as mock_helper:
        s.ADMIN_EMAILS = ""
        mock_helper.side_effect = lambda u: None
        calibration._require_admin(sentinel_user)
        mock_helper.assert_called_once_with(sentinel_user)
