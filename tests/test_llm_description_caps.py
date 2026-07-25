"""Regression tests for the length caps on LLM-bound description fields.

Four request schemas accept user-supplied text that flows directly to
the LLM as part of the prompt. Without a length cap, a single
request could send a 10MB string to the LLM, paying token cost and
consuming worker time even though the language model can only use a
few thousand tokens of context for the actual task.

The Pydantic level is the right place to enforce the cap: it fails
fast (422) before the worker is even enqueued, and we don't need to
trust the worker to truncate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.assumption import AssumptionExtractRequest
from app.schemas.competitive import CompetitiveAnalysisRequest
from app.schemas.intervention import InterventionRequest
from app.schemas.premortem import PremortemRequest


CAP = 5000


def test_assumption_extract_request_caps_description() -> None:
    assert AssumptionExtractRequest(description="x" * CAP).description == "x" * CAP
    with pytest.raises(ValidationError):
        AssumptionExtractRequest(description="x" * (CAP + 1))


@pytest.mark.parametrize(
    "cls",
    [InterventionRequest, PremortemRequest, CompetitiveAnalysisRequest],
)
def test_description_override_caps_at_5000(cls) -> None:
    assert cls(description_override="x" * CAP).description_override == "x" * CAP
    with pytest.raises(ValidationError):
        cls(description_override="x" * (CAP + 1))


def test_competitive_target_market_caps() -> None:
    """target_market is a separate field with a tighter 500-char cap."""
    assert (
        CompetitiveAnalysisRequest(target_market="x" * 500).target_market
        == "x" * 500
    )
    with pytest.raises(ValidationError):
        CompetitiveAnalysisRequest(target_market="x" * 501)


def test_fields_remain_optional() -> None:
    """Adding Field(default=None, max_length=...) must not break the
    empty-body case — all four schemas are invoked without arguments
    through the route's optional ``payload`` parameter."""
    assert AssumptionExtractRequest().description is None
    assert InterventionRequest().description_override is None
    assert PremortemRequest().description_override is None
    assert CompetitiveAnalysisRequest().description_override is None
    assert CompetitiveAnalysisRequest().target_market is None
