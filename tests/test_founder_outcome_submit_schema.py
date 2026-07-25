"""Regression tests for the typed founder-outcome submission schema.

``POST /calibration/outcome`` and ``POST /analytics/founder-outcome``
previously accepted ``body: dict`` with manual validation. The handler
then coerced ``actual_conversion_rate`` via ``float(...)`` with no
range check (so NaN, infinity, or negative values could corrupt the
calibration EMA), accepted unbounded ``notes``, and let extra keys
through silently.

The body is now a typed ``FounderOutcomeSubmit`` Pydantic model with
``extra="forbid"`` so unknown keys are rejected and every field is
range-checked at the validation layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.outcome import FounderOutcomeSubmit


class TestSimulationId:
    def test_required(self) -> None:
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit()

    def test_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit(simulation_id=0)
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit(simulation_id=-1)


class TestActualConversionRate:
    def test_default_zero(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1).actual_conversion_rate == 0.0

    def test_zero_allowed(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, actual_conversion_rate=0.0).actual_conversion_rate == 0.0

    def test_one_allowed(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, actual_conversion_rate=1.0).actual_conversion_rate == 1.0

    @pytest.mark.parametrize("bad", [1.0001, -0.0001, 100.0, -100.0])
    def test_out_of_range_rejected(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit(simulation_id=1, actual_conversion_rate=bad)


class TestDaysSinceLaunch:
    def test_default_thirty(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1).days_since_launch == 30

    def test_minimum_one(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, days_since_launch=1).days_since_launch == 1

    def test_maximum_3650(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, days_since_launch=3650).days_since_launch == 3650

    @pytest.mark.parametrize("bad", [0, -1, 3651, 10000])
    def test_out_of_range_rejected(self, bad: int) -> None:
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit(simulation_id=1, days_since_launch=bad)


class TestNotes:
    def test_optional(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1).notes is None

    def test_max_length_500(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, notes="x" * 500).notes == "x" * 500
        with pytest.raises(ValidationError):
            FounderOutcomeSubmit(simulation_id=1, notes="x" * 501)


class TestLaunched:
    def test_default_true(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1).launched is True

    def test_can_be_false(self) -> None:
        assert FounderOutcomeSubmit(simulation_id=1, launched=False).launched is False


def test_extra_fields_are_rejected() -> None:
    """extra='forbid' so unknown keys surface as 422 instead of being
    silently accepted by the legacy ``body.get(...)`` paths."""
    with pytest.raises(ValidationError):
        FounderOutcomeSubmit(simulation_id=1, garbage="x")
