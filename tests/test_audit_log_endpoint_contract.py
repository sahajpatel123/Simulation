"""Static regression test for the /me/audit-log endpoint contract.

Pins the key behaviors of the get_audit_log route
implementation in backend/app/api/v1/users.py:
* cursor pagination via `before_id` parameter
* first page (no before_id) is cached for 60s
* paginated reads (with before_id) bypass the cache
  (so a paginated walk never sees stale page-1 rows)
* limit is bounded 1-200

A future refactor that swaps one of these would change
the contract — this test pins the file-level structure.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

USERS_PY = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "backend", "app", "api", "v1", "users.py",
))


def _find_get_audit_log(src: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_audit_log":
            return node
    raise AssertionError("get_audit_log not found in users.py")


def _fn_calls_cache_get_json(fn: ast.FunctionDef) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "cache_get_json":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "cache_get_json":
            return True
    return False


def test_get_audit_log_uses_cache_get_json():
    """The route must call cache_get_json somewhere — the
    first page (no before_id) is the cached path; paginated
    reads (with before_id) bypass the cache."""
    src = Path(USERS_PY).read_text()
    fn = _find_get_audit_log(src)
    assert _fn_calls_cache_get_json(fn), (
        "get_audit_log must call cache_get_json so the first "
        "page (no before_id) is served from cache. Without it, "
        "every dashboard poll hits the DB."
    )


def test_get_audit_log_uses_before_id_query_param():
    """The route must declare a `before_id` Query parameter for
    cursor-based pagination. A bug that dropped it would
    force offset-based pagination, which silently skips /
    duplicates rows on concurrent inserts."""
    src = Path(USERS_PY).read_text()
    fn = _find_get_audit_log(src)
    found = False
    for arg in fn.args.args:
        # Function arg without a default is positional-or-keyword.
        if arg.arg == "before_id":
            found = True
            break
    # The before_id may also be a Query() in defaults — also
    # check FunctionDef.defaults.
    if not found:
        for default in fn.args.defaults:
            if (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id == "Query"
            ):
                for kw in default.keywords:
                    if kw.arg == "before_id":
                        found = True
                        break
    assert found, (
        "get_audit_log must declare a `before_id` Query param "
        "for cursor pagination. Without it, the route has no "
        "way to walk older rows."
    )


def test_get_audit_log_branch_gates_cache_on_before_id():
    """The cache_get_json call must be inside the branch
    `if before_id is None` (or equivalent) so that paginated
    reads (with a before_id) bypass the cache. A bug that
    cached ALL responses would serve a stale snapshot of page
    1 even after the user has scrolled into the history."""
    src = Path(USERS_PY).read_text()
    fn = _find_get_audit_log(src)
    cache_call_in_unconditional_branch = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if not (
                (isinstance(func, ast.Name) and func.id == "cache_get_json")
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "cache_get_json"
                )
            ):
                continue
            # Walk up the AST ancestors — is this call inside
            # any `if` whose test mentions before_id?
            gated = False
            # Without stored parents, scan source line range:
            call_line = node.lineno
            for ancestor in ast.walk(fn):
                if not isinstance(ancestor, ast.If):
                    continue
                if (
                    ancestor.end_lineno is not None
                    and ancestor.lineno is not None
                    and ancestor.lineno <= call_line
                    <= ancestor.end_lineno
                ):
                    test_src = ast.unparse(ancestor.test)
                    if "before_id" in test_src:
                        gated = True
                        break
            if not gated:
                cache_call_in_unconditional_branch = True
                break
    assert not cache_call_in_unconditional_branch, (
        "cache_get_json call is in a code path that doesn't gate "
        "on before_id. A paginated walk (before_id != None) "
        "would then serve a stale page-1 snapshot — the user "
        "would see the same rows repeated as they paginated."
    )
