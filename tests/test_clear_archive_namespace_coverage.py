"""Regression test: every _USER_*_CACHE_NAMESPACE must be
invalidated by clear_archive.

clear_archive deletes every project owned by the
authenticated user, so any cache namespace that depends
on owned-project data must be invalidated when it runs.
A namespace that gets the GET endpoint added but the
clear_archive hook forgotten silently returns stale data
for up to its TTL — the user thinks they wiped their
archive but two tiles still show the old numbers.

This test parses backend/app/api/v1/users.py as text,
extracts every declared _USER_*_CACHE_NAMESPACE
constant, then asserts each one appears in a
cache_invalidate() call inside the clear_archive
function body.

If a future commit adds a new _USER_*_CACHE_NAMESPACE
without adding the matching cache_invalidate call, this
test fails immediately at PR time instead of silently
serving stale data in production.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Resolve the path to backend/app/api/v1/users.py without
# importing the module — that would transitively pull in
# app.core.claude_client which needs the `openai` package
# not available in every dev/test venv.
USERS_PY = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "backend",
    "app", "api", "v1", "users.py",
))


def test_every_user_cache_namespace_invalidated_by_clear_archive() -> None:
    src = Path(USERS_PY).read_text()

    # Every declared _USER_*_CACHE_NAMESPACE constant in
    # the module. The convention is <NAME>: str = "<value>"
    # in module scope.
    declared = set(re.findall(
        r"^(_USER_[A-Z0-9_]+_CACHE_NAMESPACE):\s*str\s*=",
        src,
        re.MULTILINE,
    ))

    # The clear_archive function body — from the def line
    # to the next top-level decorator or def. Use a simple
    # state machine to bound the slice.
    start = src.find("\n@router.post(")
    start = src.find("\ndef clear_archive(", start)
    assert start > 0, "could not find clear_archive def"
    # Find the next top-level decorator or def after clear_archive
    next_marker = re.search(
        r"\n(?:@router\.|\ndef |\nclass )",
        src[start + 1:],
    )
    end = start + 1 + (next_marker.start() if next_marker else len(src) - start - 1)
    body = src[start:end]

    # Every cache_invalidate(namespace=_XYZ, ...) call inside clear_archive
    invalidated = set(re.findall(
        r"cache_invalidate\(\s*namespace=(_USER_[A-Z0-9_]+_CACHE_NAMESPACE)",
        body,
    ))

    # Assert: every declared namespace must be invalidated
    missing = declared - invalidated
    assert not missing, (
        f"clear_archive does not invalidate these "
        f"_USER_*_CACHE_NAMESPACE constants: {sorted(missing)}. "
        f"clear_archive wipes every owned project, so any "
        f"cache that depends on owned-project data must be "
        f"busted — otherwise the corresponding /me/* tile "
        f"serves stale data for up to its TTL after archive "
        f"wipe. Add a cache_invalidate(namespace=..., "
        f"user_id=current_user.id) call to clear_archive."
    )

    # Sanity: at least one declaration must exist (so the
    # test catches the case where someone deletes all
    # _USER_*_CACHE_NAMESPACE constants and the test
    # silently passes).
    assert declared, (
        "expected at least one _USER_*_CACHE_NAMESPACE "
        "constant in users.py — if all user caches were "
        "removed, this test should be updated, not silently "
        "passing."
    )
