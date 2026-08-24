"""Regression guard: every pagination Query param declares schema bounds.

An authenticated caller passing ``?limit=1000000`` to a route whose
``Query(...)`` lacks ``le=`` makes the database do unbounded work per
hit — the same resource-exhaustion class as the route-level rate-limit
audit, one layer down. This test AST-scans ``backend/app/api/v1`` and
fails on any pagination-shaped parameter that does not declare its
bound at the schema level.

Two escape hatches exist, both deliberate:

* ``le=``/``ge=`` declared in the ``Query(...)`` call itself — the
  normal case (422 on violation, documented in OpenAPI).
* ``DECLARED_IN_HANDLER`` — endpoints that clamp inside the handler so
  out-of-range values are *coerced to the bound* instead of rejected.
  That is a real API contract (existing clients may rely on clamping),
  so those sites are allowlisted by ``(file, param)`` rather than
  forced to change semantics. Each entry must still correspond to an
  actual finding — stale entries fail the suite.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[1] / "backend" / "app"
V1_DIR = BACKEND_APP / "api" / "v1"

UPPER_NAME = re.compile(r"(limit|page_size|per_page)$")
LOWER_ONLY_NAME = re.compile(r"(offset|skip|page)$")
_SUFFIX_STRIP = re.compile(r"_count$|_max$")

# Endpoints that clamp in-handler instead of declaring bounds in the
# Query() schema. Keyed (filename, param_name). Every entry must be
# consumed by a live finding or the stale-entry test fails.
DECLARED_IN_HANDLER: frozenset[tuple[str, str]] = frozenset(
    {
        # search_projects passes limit through build_search_filters ->
        # _normalise_limit (clamps to [1, 100], default 50).
        ("projects.py", "limit"),
        # get_buyer_personas clamps inline: max(1, min(limit, 52)).
        ("simulations.py", "limit"),
    }
)


def _pagination_findings() -> list[tuple[str, int, str, bool, bool]]:
    """Return (file, line, param, has_le, has_ge) for each Query default."""
    findings: list[tuple[str, int, str, bool, bool]] = []
    for path in sorted(V1_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            args = node.args
            pairs: list[tuple[ast.arg, ast.expr | None]] = []
            n_unnamed = len(args.args) - len(args.defaults)
            for i, arg in enumerate(args.args):
                if i >= n_unnamed:
                    pairs.append((arg, args.defaults[i - n_unnamed]))
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    pairs.append((arg, default))
            for arg, default in pairs:
                if not isinstance(default, ast.Call):
                    continue
                func_name = getattr(default.func, "id", "") or getattr(default.func, "attr", "")
                if func_name != "Query":
                    continue
                has_le = any(kw.arg == "le" for kw in default.keywords)
                has_ge = any(kw.arg == "ge" for kw in default.keywords)
                findings.append((path.name, arg.lineno, arg.arg, has_le, has_ge))
    return findings


def _is_violation(param: str, has_le: bool, has_ge: bool) -> bool:
    base = _SUFFIX_STRIP.sub("", param)
    if UPPER_NAME.search(base):
        return not has_le
    if LOWER_ONLY_NAME.search(param):
        return not has_ge
    return False


def test_pagination_params_all_bounded_or_allowlisted() -> None:
    violations: list[str] = []
    used_allowlist: set[tuple[str, str]] = set()
    for fname, lineno, param, has_le, has_ge in _pagination_findings():
        if not _is_violation(param, has_le, has_ge):
            continue
        key = (fname, param)
        if key in DECLARED_IN_HANDLER:
            used_allowlist.add(key)
            continue
        violations.append(
            f"{fname}:{lineno} `{param}` — Query() missing {'le=' if UPPER_NAME.search(_SUFFIX_STRIP.sub('', param)) else 'ge='}"
        )

    assert not violations, (
        "Pagination params without schema bounds found "
        "(add ge=/le= to the Query(), or — only if the handler deliberately "
        f"clamps/coerces — add (file, param) to DECLARED_IN_HANDLER): {violations}"
    )


def test_handler_clamp_allowlist_has_no_stale_entries() -> None:
    used: set[tuple[str, str]] = set()
    for fname, _lineno, param, has_le, has_ge in _pagination_findings():
        if _is_violation(param, has_le, has_ge) and (fname, param) in DECLARED_IN_HANDLER:
            used.add((fname, param))

    stale = set(DECLARED_IN_HANDLER) - used
    assert not stale, (
        "DECLARED_IN_HANDLER entries no longer match any unbounded Query() "
        f"(the site gained bounds or was renamed — remove them): {sorted(stale)}"
    )


# ---------------------------------------------------------------------------
# The clamp contract behind both allowlisted sites actually holds.
# ---------------------------------------------------------------------------


def test_search_limit_coercion_clamps_both_directions() -> None:
    from app.simulation.project_search import (
        DEFAULT_LIMIT,
        MAX_LIMIT,
        MIN_LIMIT,
        build_search_filters,
    )

    assert MAX_LIMIT == 100 and MIN_LIMIT == 1
    assert build_search_filters(limit=None)["limit"] == DEFAULT_LIMIT == 50
    assert build_search_filters(limit=-5)["limit"] == MIN_LIMIT
    assert build_search_filters(limit=0)["limit"] == MIN_LIMIT
    assert build_search_filters(limit=500)["limit"] == MAX_LIMIT
    assert build_search_filters(limit=42)["limit"] == 42


def test_buyer_persona_limit_documented_clamp_is_real() -> None:
    """get_buyer_personas claims 'clamped to 1-52'; pin the source line."""
    source = (V1_DIR / "simulations.py").read_text(encoding="utf-8")
    assert "effective_limit = max(1, min(effective_limit, 52))" in source, (
        "The buyer-personas handler stopped clamping limit to [1, 52] — "
        "either restore the clamp or drop its DECLARED_IN_HANDLER entry."
    )
