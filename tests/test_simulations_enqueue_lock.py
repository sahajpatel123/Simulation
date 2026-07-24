"""Regression tests for the row-lock on simulation enqueue.

The "no QUEUED/RUNNING sim for this project" check followed by an
insert was a TOCTOU race: two concurrent POSTs could both observe an
empty in-flight set and both insert. The fix acquires
``SELECT ... FOR UPDATE`` on the project row so the entire check+insert
sequence runs as a single serialised critical section per project.

These tests verify the contract by inspecting the route source code
(no runtime import of the heavy simulations module, which would pull
in the rest of the v1 router package).
"""

from __future__ import annotations

import re
from pathlib import Path

_SIMULATIONS_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "simulations.py"
)


def _read_create_simulation_block() -> str:
    """Extract the body of create_simulation from simulations.py."""
    source = _SIMULATIONS_PATH.read_text()
    match = re.search(
        r"def create_simulation\([\s\S]*?\n(?=\ndef |\nclass |\Z)",
        source,
    )
    assert match, "create_simulation not found in simulations.py"
    return match.group(0)


def test_project_ownership_query_uses_with_for_update() -> None:
    """The first DB query in create_simulation — the project ownership
    check — must call .with_for_update() so two concurrent enqueue
    requests serialise on the project row."""
    body = _read_create_simulation_block()

    # Find the first ``db.query(Project)`` block in create_simulation.
    project_query = re.search(
        r"db\.query\(\s*Project\s*\)([\s\S]*?)\.first\(\)",
        body,
    )
    assert project_query, "No Project query found in create_simulation"
    query_chain = project_query.group(1)

    assert ".with_for_update()" in query_chain, (
        "Project ownership query in create_simulation must acquire a "
        "row lock via .with_for_update() to close the concurrent-enqueue "
        "TOCTOU race.\n\nGot chain:\n" + query_chain
    )


def test_project_ownership_query_filters_by_user_id() -> None:
    """Defense in depth: the lock only matters if it also scopes by
    user_id, otherwise user A could accidentally block user B on a
    shared project row (not exploitable today since project IDs are
    unique, but the pattern must stay safe)."""
    body = _read_create_simulation_block()

    project_query = re.search(
        r"db\.query\(\s*Project\s*\)([\s\S]*?)\.first\(\)",
        body,
    )
    assert project_query
    chain = project_query.group(1)
    assert "Project.user_id == current_user.id" in chain, (
        "Project ownership query must filter by current_user.id"
    )


def test_comment_documents_the_race() -> None:
    """A regression here would be silent without a doc comment.
    Verify the lock site carries an explanatory comment so future
    contributors don't simplify it away."""
    body = _read_create_simulation_block()
    # The lock comment explicitly mentions "concurrent" and explains
    # the failure mode (draining two quota slots). Either keyword
    # works; we check both for robustness.
    lowered = body.lower()
    assert "concurrent" in lowered, (
        "create_simulation should carry a comment documenting why the "
        "lock is in place. Expected the word 'concurrent' to appear "
        "near the lock.\n\nGot body:\n" + body
    )
