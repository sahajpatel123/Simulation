"""Static regression test for tag-mutation cache invalidation.

Pins the contract added in commit 2ab72a9: the
/put_project_tags and /delete_project_tag endpoints
must invalidate _USER_TAG_TAXONOMY_CACHE_NAMESPACE so
the /me/tag-taxonomy cache reflects the new tag set +
per-tag count within the next GET.

A future refactor that silently drops the invalidation
would leave the tag taxonomy tile stale for up to its
60s TTL — every tag add/remove would show old numbers.
"""
from __future__ import annotations

import ast
import os

PROJECTS_PY = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "backend", "app", "api", "v1", "projects.py",
))

EXPECTED_NS = "_USER_TAG_TAXONOMY_CACHE_NAMESPACE"


def _find_function(src: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in projects.py")


def _function_invalidates_namespace(fn: ast.FunctionDef, ns: str) -> bool:
    """True if the function body calls cache_invalidate with
    ``namespace=<ns>`` somewhere — either directly as a kwarg
    or inside a for-loop iter."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            # Direct call: cache_invalidate(namespace=NS, ...)
            for kw in node.keywords:
                if kw.arg == "namespace":
                    if isinstance(kw.value, ast.Name) and kw.value.id == ns:
                        return True
        if isinstance(node, ast.For):
            # for-NS-in-(...) pattern: NS appears in the iter.
            iter_node = node.iter
            if isinstance(iter_node, ast.Tuple):
                for elt in iter_node.elts:
                    if (
                        isinstance(elt, ast.Name)
                        and elt.id == ns
                    ):
                        return True
    return False


def test_put_project_tags_invalidates_tag_taxonomy_cache():
    src = open(PROJECTS_PY).read()
    fn = _find_function(src, "put_project_tags")
    assert _function_invalidates_namespace(fn, EXPECTED_NS), (
        f"put_project_tags must invalidate {EXPECTED_NS} on "
        f"every tag change. Without it, the cached taxonomy "
        f"shows stale tag set + counts for up to 60s after "
        f"every PUT."
    )


def test_delete_project_tag_invalidates_tag_taxonomy_cache():
    src = open(PROJECTS_PY).read()
    fn = _find_function(src, "delete_project_tag")
    assert _function_invalidates_namespace(fn, EXPECTED_NS), (
        f"delete_project_tag must invalidate {EXPECTED_NS} on "
        f"every successful tag removal. The handler's "
        f"no-op-on-missing-tag branch should NOT bust the "
        f"cache (nothing changed) — but the actual-mutation "
        f"branch must."
    )


def test_delete_project_tag_only_invalidates_on_actual_mutation():
    """The cache invalidation must be inside the
    `if target in current_tags` branch (the actual-mutation
    branch), not at the top of the function. Otherwise
    a no-op remove (tag wasn't on the project) would
    evict the cache needlessly, hurting cache hit rate
    for users who didn't change anything."""
    src = open(PROJECTS_PY).read()
    fn = _find_function(src, "delete_project_tag")
    cache_invalidate_lines = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                (isinstance(func, ast.Name) and func.id == "cache_invalidate")
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "cache_invalidate"
                )
            ):
                cache_invalidate_lines.append(node.lineno)
    if not cache_invalidate_lines:
        raise AssertionError(
            f"delete_project_tag doesn't call cache_invalidate "
            f"at all — see test_delete_project_tag_invalidates..."
        )
    # The function body should be at least a few lines; the
    # invalidation must NOT be on line 1 (the function header
    # isn't an expression). The earliest cache_invalidate
    # must be AFTER the `if target in current_tags` line.
    if_target_line = None
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "target"
        ):
            if_target_line = node.lineno
            break
    assert if_target_line is not None, (
        "delete_project_tag should have an `if target in "
        "current_tags:` branch — the no-op-on-missing branch "
        "guards against evicting the cache when nothing changed"
    )
    earliest = min(cache_invalidate_lines)
    assert earliest > if_target_line, (
        f"cache_invalidate at line {earliest} is BEFORE the "
        f"`if target in current_tags:` branch at line "
        f"{if_target_line}. A no-op remove (tag not on the "
        f"project) should not bust the cache."
    )
