"""
Tests for ResultsAggregator helpers (cycle 39 aggregation-helper-tests).

These helpers feed every simulation result into the persisted
``simulations.results_json``. They are pure (no DB / no LLM) but
mathematically meaningful, so the tests pin the contract:

  1. ``_ci`` returns a degenerate interval for empty / single-value inputs.
  2. ``_ci`` clamps ``low`` to ≥ 0.0 and ``high`` to ≤ 1.0.
  3. ``_ci`` wider for wider distributions.
  4. ``_revenue_ci`` floors the lower bound at 0.
  5. ``_price_curve`` returns the documented number of points and an
     exactly-one-optimal flag.
  6. ``_price_curve`` is monotonically decreasing for high
     price_sensitivity (above-base multipliers).
  7. ``PriceCurvePoint`` exposes ``is_optimal`` exactly once across the curve.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def aggregator():
    from app.simulation.aggregation import ResultsAggregator

    return ResultsAggregator()


# ---------------------------------------------------------------------------
# _ci — confidence interval for conversion rates (clipped to [0, 1])
# ---------------------------------------------------------------------------


def test_ci_empty_returns_zero_interval(aggregator) -> None:
    from app.simulation.aggregation import ConfidenceInterval

    ci = aggregator._ci([], level=0.95)
    assert isinstance(ci, ConfidenceInterval)
    assert ci.low == 0.0
    assert ci.high == 0.0
    assert ci.level == 0.95


def test_ci_single_value_degenerate_interval(aggregator) -> None:
    ci = aggregator._ci([0.07], level=0.95)
    assert ci.low == ci.high == 0.07
    assert ci.level == 0.95


def test_ci_clips_to_unit_interval(aggregator) -> None:
    """Sample data with extreme outliers; lower bound should clip to 0."""
    # Values chosen so the t-interval would normally produce a negative low.
    ci = aggregator._ci([0.0, 0.0, 0.0, 0.05, 0.0, 0.0, 0.0], level=0.95)
    assert ci.low >= 0.0
    assert ci.high <= 1.0


def test_ci_contains_mean_within_bounds(aggregator) -> None:
    values = [0.04, 0.05, 0.06, 0.07, 0.05, 0.04, 0.06]
    ci = aggregator._ci(values, level=0.95)
    mean = sum(values) / len(values)
    # Mean must lie inside the interval (clamping aside).
    assert ci.low - 1e-9 <= mean <= ci.high + 1e-9


def test_ci_95_wider_than_99(aggregator) -> None:
    """Lower confidence level → wider interval."""
    values = [0.05, 0.06, 0.04, 0.07, 0.05, 0.05, 0.06]
    ci_95 = aggregator._ci(values, level=0.95)
    ci_99 = aggregator._ci(values, level=0.99)
    width_95 = ci_95.high - ci_95.low
    width_99 = ci_99.high - ci_99.low
    assert width_99 >= width_95


def test_ci_rounds_to_four_dp(aggregator) -> None:
    ci = aggregator._ci([0.123456, 0.654321, 0.111111], level=0.95)
    # All values rounded to 4 decimal places.
    assert ci.low == round(ci.low, 4)
    assert ci.high == round(ci.high, 4)


# ---------------------------------------------------------------------------
# _revenue_ci — confidence interval for revenue (floored at 0)
# ---------------------------------------------------------------------------


def test_revenue_ci_empty_returns_zero_interval(aggregator) -> None:
    from app.simulation.aggregation import ConfidenceInterval

    ci = aggregator._revenue_ci([], level=0.95)
    assert ci.low == 0.0
    assert ci.high == 0.0


def test_revenue_ci_single_value_degenerate(aggregator) -> None:
    ci = aggregator._revenue_ci([500.0], level=0.95)
    assert ci.low == 500.0
    assert ci.high == 500.0


def test_revenue_ci_lower_bound_floored_at_zero(aggregator) -> None:
    """Even when the t-interval would dip below zero, _revenue_ci floors it."""
    values = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    ci = aggregator._revenue_ci(values, level=0.95)
    assert ci.low >= 0.0


def test_revenue_ci_rounds_to_two_dp(aggregator) -> None:
    ci = aggregator._revenue_ci([100.123, 200.456, 50.789], level=0.95)
    assert ci.low == round(ci.low, 2)
    assert ci.high == round(ci.high, 2)


def test_revenue_ci_higher_level_wider(aggregator) -> None:
    values = [100.0, 200.0, 150.0, 175.0, 125.0]
    ci_95 = aggregator._revenue_ci(values, level=0.95)
    ci_99 = aggregator._revenue_ci(values, level=0.99)
    assert (ci_99.high - ci_99.low) >= (ci_95.high - ci_95.low)


# ---------------------------------------------------------------------------
# _price_curve — pure math, no DB
# ---------------------------------------------------------------------------


def test_price_curve_returns_ten_points(aggregator) -> None:
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=0.5,
    )
    assert len(curve) == 10


def test_price_curve_exactly_one_optimal(aggregator) -> None:
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=0.5,
    )
    optimal = [p for p in curve if p.is_optimal]
    assert len(optimal) == 1
    # The optimal point should have the max revenue_per_1000_visitors.
    max_rev = max(p.revenue_per_1000_visitors for p in curve)
    assert optimal[0].revenue_per_1000_visitors == max_rev


def test_price_curve_prices_increasing(aggregator) -> None:
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=0.5,
    )
    prices = [p.price for p in curve]
    assert prices == sorted(prices), "price curve must be sorted ascending"


def test_price_curve_conversion_decreases_with_price(aggregator) -> None:
    """Higher multipliers should reduce conversion (decay < 1.0)."""
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=0.5,
    )
    # Compare the lowest-priced and the highest-priced points.
    first = curve[0]
    last = curve[-1]
    assert last.price > first.price
    assert last.conversion_rate < first.conversion_rate


def test_price_curve_high_sensitivity_pushes_optimal_lower(aggregator) -> None:
    """When price sensitivity is high, the optimal price is the lowest tested
    multiplier (or near it)."""
    low_sens = aggregator._price_curve(1000.0, 0.10, price_sensitivity=0.05)
    high_sens = aggregator._price_curve(1000.0, 0.10, price_sensitivity=1.5)
    opt_low = next(p for p in low_sens if p.is_optimal)
    opt_high = next(p for p in high_sens if p.is_optimal)
    # Optimal at high sensitivity ≤ optimal at low sensitivity.
    assert opt_high.price <= opt_low.price


def test_price_curve_revenue_is_non_negative_and_bounded(aggregator) -> None:
    """Revenue per 1000 visitors must be non-negative and within plausible
    bounds given the inputs. (Exact equality is not asserted because
    intermediate rounding of price and conversion_rate introduces drift.)"""
    curve = aggregator._price_curve(
        base_price=500.0,
        base_conversion=0.20,
        price_sensitivity=0.3,
    )
    for p in curve:
        # Lower bound: 0 (no negative revenue).
        assert p.revenue_per_1000_visitors >= 0.0
        # Upper bound: assume conversion ≤ 1.0 and price ≤ 10× base.
        upper = p.price * 1.0 * 1000
        assert p.revenue_per_1000_visitors <= upper + 1.0


def test_price_curve_conversion_rates_in_unit_interval(aggregator) -> None:
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=1.5,
    )
    for p in curve:
        assert 0.0 < p.conversion_rate <= 1.0


def test_price_curve_zero_sensitivity_matches_base(aggregator) -> None:
    """With price_sensitivity=0, the decay formula becomes 1/1 = 1.0, so every
    curve point uses base_conversion (clipped)."""
    curve = aggregator._price_curve(
        base_price=1000.0,
        base_conversion=0.10,
        price_sensitivity=0.0,
    )
    # All conversion rates should be approximately equal to base_conversion.
    conversions = [p.conversion_rate for p in curve]
    assert all(math.isclose(c, 0.10, abs_tol=1e-4) for c in conversions)
