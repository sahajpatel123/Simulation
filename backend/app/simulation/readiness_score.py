"""Pure helper for computing a simple project readiness score."""
from __future__ import annotations

from typing import Any


def compute_readiness(project: dict[str, Any]) -> dict[str, Any]:
    """Return a 0-100 readiness score and checklist from project fields."""
    checks: list[dict[str, Any]] = []
    score = 0

    if (project.get("description") or "").strip():
        score += 20
        checks.append({"label": "description", "done": True})
    else:
        checks.append({"label": "description", "done": False})

    if (project.get("title") or "").strip():
        score += 10
        checks.append({"label": "title", "done": True})
    else:
        checks.append({"label": "title", "done": False})

    tags = project.get("tags") or []
    if tags:
        score += 15
        checks.append({"label": "tags", "done": True})
    else:
        checks.append({"label": "tags", "done": False})

    if (project.get("simulation_count") or 0) > 0:
        score += 25
        checks.append({"label": "simulation", "done": True})
    else:
        checks.append({"label": "simulation", "done": False})

    if (project.get("decision_count") or 0) > 0:
        score += 15
        checks.append({"label": "decision", "done": True})
    else:
        checks.append({"label": "decision", "done": False})

    if (project.get("outcome_count") or 0) > 0:
        score += 15
        checks.append({"label": "outcome", "done": True})
    else:
        checks.append({"label": "outcome", "done": False})

    score = min(100, score)
    level = "HIGH" if score >= 80 else "MEDIUM" if score >= 50 else "LOW"
    return {"score": score, "level": level, "checks": checks}


__all__ = ["compute_readiness"]
