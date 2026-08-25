"""Tests for WhatIfOut.has_recommendations()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfOut, WhatIfRecommendation


def test_has_recommendations_false_when_empty() -> None:
    assert WhatIfOut(simulation_id=1, project_id=1).has_recommendations() is False


def test_has_recommendations_true_when_present() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[
            WhatIfRecommendation(priority=1, title="ok", rationale="r"),
        ],
    )

    assert out.has_recommendations() is True


def test_has_recommendations_true_with_multiple() -> None:
    out = WhatIfOut(
        simulation_id=1,
        project_id=1,
        recommendations=[
            WhatIfRecommendation(priority=1, title="a", rationale="r"),
            WhatIfRecommendation(priority=2, title="b", rationale="r"),
        ],
    )

    assert out.has_recommendations() is True
