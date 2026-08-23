"""CI migration-step contract tests.

``.github/workflows/backend-ci.yml`` runs ``migrate_and_start.py``
in its "Run database migrations" step before pytest. The script must
exit there (``--migrate-only``) instead of falling through to its
default behavior of starting uvicorn — otherwise the step blocks on a
server nobody stops, the job burns its whole timeout budget, and the
run is cancelled before a single test executes.

These tests pin both halves of that contract so neither half can be
removed silently.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backend-ci.yml"
MIGRATIONS = ROOT / "migrate_and_start.py"

_MIGRATE_ONLY_CMD = "python migrate_and_start.py --migrate-only"


def test_backend_ci_invokes_migrations_with_exit_flag() -> None:
    """The CI workflow must call the migration script with --migrate-only."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert (
        _MIGRATE_ONLY_CMD in text
    ), (
        "backend-ci.yml must invoke `"
        + _MIGRATE_ONLY_CMD
        + "`; calling the script bare starts uvicorn "
        "and hangs the job until the timeout cancels it."
    )


def test_migration_script_guard_precedes_uvicorn_start() -> None:
    """--migrate-only must short-circuit before uvicorn ever runs."""
    source = MIGRATIONS.read_text(encoding="utf-8")
    guard = '"--migrate-only" in sys.argv[1:]'
    assert guard in source, (
        "migrate_and_start.py lost its --migrate-only guard; "
        "the CI migrations step would block forever."
    )
    server_start = source.index("uvicorn.run(")
    assert source.index(guard) < server_start, (
        "--migrate-only guard must execute before the uvicorn "
        "startup line."
    )
