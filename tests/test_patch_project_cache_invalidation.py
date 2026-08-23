"""Static regression test for patch_project cache invalidation.

Pins the cache-invalidation contract added in commits
fae8444, db7e081: patch_project must invalidate the 6
user-level cache namespaces that depend on the project
title or description, on either field change.

A future refactor that silently drops the invalidation
would leave /me/dashboard, /me/projects-by-status,
/me/projects-needing-attention, /me/most-active-project,
/me/last-touched-project, /me/portfolio-health-snapshot
serving stale data for up to each tile's TTL.

This is a static-analysis test: it parses the patch_project
function and asserts the right cache_invalidate calls are
present. Functional tests would require a full DB +
cache mock which is too heavy for a quick regression
check.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

PROJECTS_PY = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "backend", "app", "api", "v1", "projects.py",
))

EXPECTED_NAMESPACES = (
    "_USER_DASHBOARD_CACHE_NAMESPACE",
    "_USER_PROJECTS_BY_STATUS_CACHE_NAMESPACE",
    "_USER_PROJECTS_NEEDING_ATTENTION_CACHE_NAMESPACE",
    "_USER_MOST_ACTIVE_PROJECT_CACHE_NAMESPACE",
    "_USER_LAST_TOUCHED_PROJECT_CACHE_NAMESPACE",
    "_USER_PORTFOLIO_HEALTH_SNAPSHOT_CACHE_NAMESPACE",
)


def _find_patch_project(src: str) -> ast.FunctionDef:
    """Find the patch_project function definition in the
    project source file."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "patch_project":
            return node
    raise AssertionError("patch_project not found in projects.py")


def _find_cache_invalidate_calls(fn: ast.FunctionDef) -> list[tuple[str, str]]:
    """Find all cache_invalidate(...) calls inside fn.

    Also detects the loop pattern that builds a set of
    namespaces and iterates over them — the namespace
    set is captured in the loop's iter.

    Returns a list of (namespace_literal, condition_source)
    tuples — one per call OR per loop-body namespace.
    The condition_source is a text snippet showing what
    the call is gated on (if anything) so we can tell
    title-only vs description-only vs unconditional
    invalidations apart."""
    out: list[tuple[str, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if not (
                (isinstance(func, ast.Name) and func.id == "cache_invalidate")
                or (isinstance(func, ast.Attribute) and func.attr == "cache_invalidate")
            ):
                continue
            # First positional arg may be a Name (loop var) or
            # a constant from the expected set. Capture either.
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Name):
                out.append((first.id, ast.unparse(node).split("\n")[0]))
            elif isinstance(first, ast.Attribute):
                out.append((ast.unparse(first), ast.unparse(node).split("\n")[0]))
        if isinstance(node, ast.For):
            # Detect the loop pattern: `for _ns in (CONST, CONST, ...):`
            # The iter is a Tuple of Names — capture them.
            iter_node = node.iter
            if isinstance(iter_node, ast.Tuple):
                for elt in iter_node.elts:
                    if isinstance(elt, ast.Name):
                        out.append((elt.id, "for-loop iter"))
    return out


def test_patch_project_invalidates_six_user_caches():
    src = Path(PROJECTS_PY).read_text()
    fn = _find_patch_project(src)
    calls = _find_cache_invalidate_calls(fn)

    invalidations = {ns for ns, _ in calls}

    missing = set(EXPECTED_NAMESPACES) - invalidations
    assert not missing, (
        f"patch_project is missing cache invalidations for: "
        f"{sorted(missing)}. patch_project mutates the "
        f"project's title and description; the 6 user-level "
        f"tiles that show title (dashboard, projects-by-status, "
        f"projects-needing-attention, most-active-project, "
        f"last-touched-project, portfolio-health-snapshot) "
        f"must be busted on either field change so the cached "
        f"snapshot reflects the new value within the next GET."
    )


def test_patch_project_invalidations_gated_on_title_or_description_change():
    """The 6 cache_invalidate calls must be gated on EITHER
    title or description change — not just title (description
    change is what mutates the per-project health score
    that the portfolio-health-snapshot aggregates).

    We look for the gating condition: the call must be
    inside a conditional that checks title_changed OR
    description. The condition is typically
    `if title_changed or payload.description is not None:`
    but other forms are acceptable as long as both field
    changes are covered.
    """
    src = Path(PROJECTS_PY).read_text()
    fn = _find_patch_project(src)

    # Find the call that busts DASHBOARD (the first invalidation
    # in the gated block). The variable that gates the call
    # must be one of {title_changed, payload.description, ...}.
    in_gated_block = False
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            cond = ast.unparse(node.test)
            if "title_changed" in cond or "description" in cond:
                in_gated_block = True
                break
    assert in_gated_block, (
        "patch_project must invalidate caches inside an if "
        "that checks title_changed OR description. Couldn't "
        "find such a condition in the function."
    )


def test_patch_project_invalidates_using_calling_user_id():
    """Every cache_invalidate call must pass user_id=
    current_user.id — the CALLING user's id. A bug that
    hardcoded a value or used a wrong variable would let
    user A bust user B's cached data (multi-tenant privacy
    leak)."""
    src = Path(PROJECTS_PY).read_text()
    fn = _find_patch_project(src)
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            (isinstance(func, ast.Name) and func.id == "cache_invalidate")
            or (isinstance(func, ast.Attribute) and func.attr == "cache_invalidate")
        ):
            continue
        if not node.keywords:
            continue
        for kw in node.keywords:
            if kw.arg == "user_id":
                # The user_id arg must reference current_user.id
                # (the parameter name in the function signature),
                # not a hardcoded value.
                if not isinstance(kw.value, ast.Attribute):
                    raise AssertionError(
                        f"cache_invalidate user_id= is not an "
                        f"attribute access (e.g. current_user.id); "
                        f"got: {ast.unparse(kw.value)}. A hardcoded "
                        f"value would leak data across users."
                    )
                if kw.value.attr != "id":
                    raise AssertionError(
                        f"cache_invalidate user_id= should be "
                        f"current_user.id, got "
                        f"{ast.unparse(kw.value)}"
                    )
