"""
A/B landing-page experiment analysis routes.

The simulation engine recommends concrete micro-tests (landing-page A/B
experiments, pricing tests, messaging variants); this router lets a founder
paste the observed results back and get a statistical verdict. It is a
pure computation endpoint — no DB writes, no Celery dispatch, no LLM calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.core.rate_limiter import rate_limit
from app.models.user import User
from app.schemas.ab_test import AbTestAnalysisIn, AbTestAnalysisOut
from app.simulation import ab_test_analysis as ab_engine

router = APIRouter(prefix="/experiments", tags=["experiments"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


@router.post(
    "/ab-analysis",
    response_model=AbTestAnalysisOut,
    summary="Analyse a two-variant A/B landing-page experiment",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def analyze_ab_test(
    payload: AbTestAnalysisIn,
    current_user: User = Depends(get_current_user),
) -> AbTestAnalysisOut:
    """
    Return a statistical verdict for two observed A/B arms (visitors +
    conversions each): significance, uplift, confidence interval, and how
    much more traffic the test needs. Inputs are validated by the schema
    (conversions must not exceed visitors, counts must be finite ints), and
    the analysis is deliberately conservative — it refuses to report
    p-values until the test has enough traffic to be meaningful.
    """
    result = ab_engine.analyze_ab_test(
        payload.variant_a,
        payload.variant_b,
        alpha=payload.alpha,
        power=payload.power,
        mde=payload.minimum_detectable_effect,
    )
    return AbTestAnalysisOut(**result)
