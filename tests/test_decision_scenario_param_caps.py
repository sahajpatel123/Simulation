"""Regression tests for length caps on ScenarioParameters free-text fields.

ScenarioParameters flow into the LLM prompt for the decision-comparison
worker. Three fields — ``positioning``, ``go_to_market``, ``notes`` —
were unbounded, so a single request could send a 10MB string to the
LLM. Cap them at the Pydantic layer so the cap fails fast (422) before
the worker is enqueued.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.decision import DecisionCreate, ScenarioIn, ScenarioParameters


def _scenario(**overrides) -> ScenarioIn:
    defaults = {
        "name": "low",
        "description": "Low-price scenario",
        "parameters": ScenarioParameters(),
    }
    defaults.update(overrides)
    return ScenarioIn(**defaults)


def _decision(**overrides) -> DecisionCreate:
    defaults = {
        "title": "Compare scenarios",
        "description": "Compare two pricing scenarios",
        "scenarios": [
            _scenario(name="low", description="Low price"),
            _scenario(name="high", description="High price"),
        ],
    }
    defaults.update(overrides)
    return DecisionCreate(**defaults)


class TestPositioning:
    def test_short_ok(self) -> None:
        p = ScenarioParameters(positioning="x" * 500)
        assert p.positioning == "x" * 500

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioParameters(positioning="x" * 501)


class TestGoToMarket:
    def test_short_ok(self) -> None:
        p = ScenarioParameters(go_to_market="x" * 500)
        assert p.go_to_market == "x" * 500

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioParameters(go_to_market="x" * 501)


class TestNotes:
    def test_short_ok(self) -> None:
        # notes gets a slightly larger cap (1000) since it's a free-text
        # annotation field for the writer.
        p = ScenarioParameters(notes="x" * 1000)
        assert p.notes == "x" * 1000

    def test_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioParameters(notes="x" * 1001)


def test_optional_fields_remain_optional() -> None:
    p = ScenarioParameters()
    assert p.positioning is None
    assert p.go_to_market is None
    assert p.notes is None


def test_decision_create_still_works_with_populated_params() -> None:
    """End-to-end: the decision-create payload still accepts populated
    ScenarioParameters."""
    d = _decision(
        scenarios=[
            _scenario(
                name="low",
                description="Low price",
                parameters=ScenarioParameters(
                    positioning="aggressive",
                    go_to_market="direct",
                    notes="watch CAC",
                ),
            ),
            _scenario(name="high", description="High price"),
        ]
    )
    assert d.scenarios[0].parameters.positioning == "aggressive"
