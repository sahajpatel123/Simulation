"""Repo-wide import-hygiene guard.

CLAUDE.md's Python rules say imports belong at module top. Function-local
imports of *stdlib* modules are never load-bearing (no cycle to break, no
optional dependency), so they are pure rule violations — historically they
accumulated silently until a 2026-08-25 sweep hoisted all of them. This
test keeps the count at zero.

Deliberately out of scope:

- ``app.*`` local imports: several are intentional lazy/cycle-breaking
  imports (the cyclic-import remediation introduced them by design).
- Third-party locals such as ``playwright`` in ``app/browser/session.py``:
  heavy optional dependencies are legitimately deferred until use.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_BACKEND_APP = Path(__file__).resolve().parents[1] / "backend" / "app"

# Modules whose function-local import is always pointless. Anything not
# listed here (third-party, app-internal) is allowed to stay local.
_STDLIB_MODULES = set(sys.stdlib_module_names)


def _local_stdlib_imports() -> list[str]:
    """Every ``def``-scoped stdlib import under backend/app as 'file:line'."""
    findings: list[str] = []
    for path in sorted(_BACKEND_APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for stmt in ast.walk(node):
                mods: list[str] = []
                if isinstance(stmt, ast.Import):
                    mods = [a.name.split(".")[0] for a in stmt.names]
                elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                    mods = [stmt.module.split(".")[0]]
                for mod in mods:
                    if mod in _STDLIB_MODULES:
                        findings.append(f"{path.relative_to(_BACKEND_APP)}:{stmt.lineno} ({mod} in {node.name})")
    return findings


def test_no_function_local_stdlib_imports():
    violations = _local_stdlib_imports()
    assert violations == [], (
        "function-local stdlib imports found (hoist them to module top): "
        + "; ".join(violations)
    )
