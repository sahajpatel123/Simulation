"""Regression test: cache hit short-circuit must precede
DB queries in the same route handler.

Every /me/* and /projects/{id}/* digest endpoint follows
the same pattern: a `cache_get_json` short-circuit at the
top of the route, then DB queries, then `cache_set_json`.
The cache check is supposed to skip the DB queries on a
hit — but if the cache check is placed AFTER any DB
query, the cache hit still pays the DB cost, defeating
the whole point.

The parallel loop has reproduced this bug 4 times so
far (insights, last-week-stats, sim-failure-rate, plus
a syntax-error variant on projects-needing-attention
that combined both bugs). This test scans every cached
route and asserts that the first DB-touching statement
in the function body is the first cache hit check, OR
that there are no DB statements before the first cache
hit check.

Tradeoff vs. a strict AST walker: this is a line-level
scan, not control-flow aware. It will miss cases where
the DB query is hidden inside a helper called before
cache_get_json. That's acceptable — the bug class we're
guarding against is "developer copy-pasted the cache hit
short-circuit into the wrong place", and a line-level
scan catches exactly that.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

# Routes live in backend/app/api/v1/. We scan every .py
# file there except shared modules and __init__.
ROUTES_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "backend", "app", "api", "v1",
))

# Statements that touch the DB. Kept narrow so the scan
# doesn't false-positive on imports / type aliases / etc.
_DB_TOUCH_PATTERNS = (
    "db.query",
    "db.execute",
    "db.add",
    "db.delete",
    "db.merge",
    "db.bulk_save",
    "db.flush",
    "engine.execute",
    "session.execute",
    "session.query",
)


def _route_functions(path: str) -> list[tuple[str, ast.FunctionDef]]:
    """Yield every (name, function) pair that lives under a
    ``@router.{get,post,put,patch,delete}`` decorator."""
    src = Path(path).read_text()
    tree = ast.parse(src)
    out: list[tuple[str, ast.FunctionDef]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # Look up the decorators above this def.
        decorators = [
            ast.unparse(d) for d in node.decorator_list
        ]
        if not any("router." in d for d in decorators):
            continue
        out.append((node.name, node))
    return out


def _first_db_line(body: ast.FunctionDef) -> int | None:
    """Return the 1-indexed line of the first DB-touching
    statement in the function body, or None if none."""
    for stmt in ast.walk(body):
        # Skip the function's own docstring + decorators
        # (already excluded by ast.walk which descends into
        # nested expressions).
        if isinstance(stmt, ast.Expr) and isinstance(
            stmt.value, ast.Constant
        ) and isinstance(stmt.value.value, str):
            # docstring; skip
            continue
        line = getattr(stmt, "lineno", None)
        if line is None:
            continue
        src_line = ast.unparse(stmt).split("\n")[0]
        if any(pat in src_line for pat in _DB_TOUCH_PATTERNS):
            return line
    return None


def _first_cache_hit_line(body: ast.FunctionDef) -> int | None:
    """Return the 1-indexed line of the first
    cache_get_json call in the function body, or None if
    none."""
    for node in ast.walk(body):
        if isinstance(node, ast.Call):
            # Look at the function name being called.
            func = node.func
            if isinstance(func, ast.Name) and func.id == "cache_get_json":
                return getattr(node, "lineno", None)
            if isinstance(func, ast.Attribute) and func.attr == "cache_get_json":
                return getattr(node, "lineno", None)
    return None


def test_cache_hit_precedes_db_in_every_cached_route() -> None:
    """Every cached route must check the cache BEFORE its
    first DB query."""
    violations: list[tuple[str, str, int, int]] = []
    # (file, fn_name, cache_line, db_line) — file is the
    # relative path for readable output; cache_line is where
    # the first cache_get_json sits; db_line is where the
    # first db.* query sits.
    for entry in sorted(os.listdir(ROUTES_DIR)):
        if not entry.endswith(".py"):
            continue
        if entry in {"__init__.py", "common.py"}:
            continue
        path = os.path.join(ROUTES_DIR, entry)
        for fn_name, fn in _route_functions(path):
            cache_line = _first_cache_hit_line(fn)
            db_line = _first_db_line(fn)
            # Only flag routes that BOTH use the cache AND
            # have DB queries — pure-DB or pure-cache
            # routes are fine.
            if cache_line is None or db_line is None:
                continue
            if db_line < cache_line:
                rel = os.path.relpath(path, ROUTES_DIR)
                violations.append((rel, fn_name, cache_line, db_line))
    assert not violations, (
        "These route handlers have cache hit short-circuits "
        "placed AFTER DB queries, which defeats the cache:\n"
        + "\n".join(
            f"  {rel}::{fn_name} (cache hit at L{cache}, first "
            f"DB at L{db})"
            for rel, fn_name, cache, db in violations
        )
        + "\n\nFix: move the cache_get_json call to the top of "
        "the route function, BEFORE any db.query/db.execute "
        "/db.add calls."
    )
