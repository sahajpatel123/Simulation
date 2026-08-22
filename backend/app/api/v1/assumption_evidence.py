"""
Assumption-evidence log and de-risking scorecard routes.

The validation-experiment planner says *what* to run; these endpoints let a
founder record *what happened* and see the consequence:

* ``POST /projects/{project_id}/assumptions/{assumption_id}/evidence``
  logs one experiment result (method + PASS/FAIL/INCONCLUSIVE).
* ``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard``
  returns the evidence history plus the before/after validation-ROI shift
  implied by the derived confidence tier.
* ``GET /projects/{project_id}/evidence-digest`` rolls every logged
  experiment up into a project-level de-risking summary.
* ``GET /projects/{project_id}/assumption-validation-timeline`` replays
  every logged experiment chronologically with cumulative validation
  progress and first-occurrence milestones.
* ``GET /projects/{project_id}/validation-dashboard`` composes the digest,
  timeline milestones, and momentum forecast into one response.
* ``GET /projects/{project_id}/validation-dashboard/export`` downloads the
  dashboard as CSV, JSON, or a founder-facing Markdown brief.
* ``GET /projects/{project_id}/validation-momentum`` measures evidence
  cadence and projects how many weeks remain until full coverage or a
  de-risked target.
* ``GET /projects/{project_id}/validation-momentum/export`` downloads that
  forecast as CSV, JSON, or a founder-facing Markdown brief.
* ``GET /projects/{project_id}/evidence-freshness`` ages every
  assumption's latest evidence (FRESH/AGING/STALE/NEVER_TESTED) and ranks
  a prioritised re-test queue.
* ``GET /projects/{project_id}/evidence-freshness/export`` downloads the
  re-test queue as CSV, JSON, or a founder-facing Markdown brief.

Pure post-hoc analysis — no Celery dispatch, no LLM calls.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.common import get_owned_project
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.models.assumption import Assumption
from app.models.assumption_evidence import AssumptionEvidence
from app.models.environment import Environment
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.assumption_evidence import (
    AssumptionEvidenceDigestOut,
    AssumptionEvidenceScorecardOut,
    EvidenceCreate,
    EvidenceOut,
)
from app.schemas.evidence_staleness import (
    EvidenceStalenessOut,
    EvidenceStalenessRowOut,
    EvidenceStalenessSummaryOut,
)
from app.schemas.validation_dashboard import DASHBOARD_MODEL, ValidationDashboardOut
from app.schemas.validation_momentum import ValidationMomentumOut
from app.schemas.validation_timeline import (
    AssumptionValidationTimelineOut,
    ValidationTimelineMilestonesOut,
)
from app.simulation.assumption_evidence_digest import (
    build_assumption_evidence_digest,
)
from app.simulation.evidence_scorecard import (
    build_assumption_scorecard,
    derive_confidence,
    evidence_to_out,
)
from app.simulation.evidence_scorecard_export import (
    FORMAT_VERSION as EVIDENCE_SCORECARD_FORMAT_VERSION,
)
from app.simulation.evidence_scorecard_export import (
    evidence_scorecard_to_csv,
    evidence_scorecard_to_json,
    evidence_scorecard_to_markdown,
)
from app.simulation.evidence_staleness import (
    DEFAULT_AGING_DAYS,
    DEFAULT_FRESH_DAYS,
    FRESHNESS_NEVER_TESTED,
    FRESHNESS_STALE,
    MAX_WINDOW_DAYS,
    MIN_WINDOW_DAYS,
    build_evidence_staleness,
)
from app.simulation.evidence_staleness_export import (
    FORMAT_VERSION as EVIDENCE_FRESHNESS_FORMAT_VERSION,
)
from app.simulation.evidence_staleness_export import (
    evidence_staleness_to_csv,
    evidence_staleness_to_json,
    evidence_staleness_to_markdown,
)
from app.simulation.validation_dashboard_export import (
    FORMAT_VERSION as VALIDATION_DASHBOARD_FORMAT_VERSION,
)
from app.simulation.validation_dashboard_export import (
    validation_dashboard_to_csv,
    validation_dashboard_to_json,
    validation_dashboard_to_markdown,
)
from app.simulation.validation_momentum import build_validation_momentum
from app.simulation.validation_momentum_export import (
    FORMAT_VERSION as VALIDATION_MOMENTUM_FORMAT_VERSION,
)
from app.simulation.validation_momentum_export import (
    validation_momentum_to_csv,
    validation_momentum_to_json,
    validation_momentum_to_markdown,
)
from app.simulation.validation_timeline import build_validation_timeline

router = APIRouter(prefix="/projects", tags=["assumption-evidence"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _assumption_or_404(
    db: Session, project_id: int, assumption_id: int
) -> Assumption:
    assumption = (
        db.query(Assumption)
        .filter(
            Assumption.id == assumption_id,
            Assumption.project_id == project_id,
        )
        .first()
    )
    if not assumption:
        raise HTTPException(
            status_code=404, detail="Assumption not found in this project"
        )
    return assumption


@router.post(
    "/{project_id}/assumptions/{assumption_id}/evidence",
    response_model=EvidenceOut,
    summary="Log a validation experiment result for an assumption",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def create_assumption_evidence(
    project_id: int,
    assumption_id: int,
    payload: EvidenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceOut:
    """
    Record the outcome of one validation experiment (method + PASS/FAIL/
    INCONCLUSIVE) against an assumption. A PASS upgrades the assumption's
    derived confidence to ``VALIDATED_INTERNAL``; a FAIL drops it to
    ``ASPIRATIONAL``; INCONCLUSIVE leaves it unchanged.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumption = _assumption_or_404(db, project.id, assumption_id)

    row = AssumptionEvidence(
        project_id=project.id,
        assumption_id=assumption.id,
        method=payload.method,
        result=payload.result,
        observed_metric=payload.observed_metric,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    derived = derive_confidence(row.result)
    return EvidenceOut(
        id=row.id,
        project_id=row.project_id,
        assumption_id=row.assumption_id,
        assumption_text=assumption.text,
        method=row.method,
        method_label=evidence_to_out(row, assumption.text).method_label,
        result=row.result,
        observed_metric=row.observed_metric,
        notes=row.notes,
        created_at=row.created_at,
        derived_confidence=derived.value if derived is not None else None,
    )


@router.get(
    "/{project_id}/assumptions/{assumption_id}/evidence-scorecard",
    response_model=AssumptionEvidenceScorecardOut,
    summary="De-risking scorecard: evidence history + validation-ROI shift",
    responses=_JSON_200,
)
def get_assumption_evidence_scorecard(
    project_id: int,
    assumption_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionEvidenceScorecardOut:
    """
    De-risking scorecard for one assumption: every logged experiment, the
    evidence-derived confidence tier, and how validation-ROI (and its tier)
    would shift if the derived confidence were applied today.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumption = _assumption_or_404(db, project.id, assumption_id)

    evidence = (
        db.query(AssumptionEvidence)
        .filter(
            AssumptionEvidence.project_id == project.id,
            AssumptionEvidence.assumption_id == assumption.id,
        )
        .order_by(AssumptionEvidence.created_at.desc(), AssumptionEvidence.id.desc())
        .all()
    )

    sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project.id)
        .order_by(Simulation.created_at.desc(), Simulation.id.desc())
        .first()
    )
    if sim is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No simulation found for this project — run a simulation before "
                "requesting an evidence scorecard."
            ),
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Latest simulation is {sim.status} — evidence scorecards "
                "require completed results."
            ),
        )
    if not sim.results_json:
        raise HTTPException(
            status_code=422,
            detail="Latest simulation completed but results_json is empty.",
        )

    environment = (
        db.query(Environment).filter(Environment.id == sim.environment_id).first()
    )
    env_params: dict = {}
    if environment:
        env_params = {
            "average_order_value": float(environment.average_order_value or 999.0),
            "price_sensitivity": float(environment.price_sensitivity or 0.5),
            "market_maturity": float(environment.market_maturity or 0.3),
            "consumer_volume": int(environment.consumer_volume or 10000),
            "growth_rate_per_month": float(environment.growth_rate_per_month or 5.0),
        }

    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .all()
    )

    return build_assumption_scorecard(
        simulation_id=sim.id,
        project_id=project.id,
        assumption=assumption,
        evidence=evidence,
        base_results=sim.results_json,
        env_params=env_params,
        existing_assumptions=assumptions,
        signal_quality=float(sim.signal_quality)
        if sim.signal_quality is not None
        else None,
    )


@router.get(
    "/{project_id}/evidence-digest",
    response_model=AssumptionEvidenceDigestOut,
    summary="Project-level validation-evidence digest",
    responses=_JSON_200,
)
def get_assumption_evidence_digest(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionEvidenceDigestOut:
    """
    Roll every logged validation experiment for the project up into one
    de-risking digest: evidence coverage, de-risked / challenged /
    pending counts, result and method histograms, and the top
    experiments still worth running. Unlike the per-assumption scorecard,
    this endpoint does not require a completed simulation — a founder can
    track validation progress as soon as experiments are logged.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.desc(),
            AssumptionEvidence.id.desc(),
        )
        .all()
    )
    return AssumptionEvidenceDigestOut(
        **build_assumption_evidence_digest(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/assumption-validation-timeline",
    response_model=AssumptionValidationTimelineOut,
    summary="Chronological validation-evidence timeline for a project",
    responses=_JSON_200,
)
def get_assumption_validation_timeline(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionValidationTimelineOut:
    """
    Replay the project's logged validation experiments in chronological
    order: each event's method/result, the assumption status it produced,
    cumulative de-risked / challenged / pending counts, and the first time
    each state occurred. Unlike the per-assumption scorecard, this endpoint
    does not require a completed simulation — a founder can watch validation
    progress accumulate from the first logged experiment.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.asc(),
            AssumptionEvidence.id.asc(),
        )
        .all()
    )
    return AssumptionValidationTimelineOut(
        **build_validation_timeline(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/validation-momentum",
    response_model=ValidationMomentumOut,
    summary="Validation momentum: evidence cadence and de-risking forecast",
    responses=_JSON_200,
)
def get_validation_momentum(
    project_id: int,
    target_de_risked_pct: float = Query(
        default=1.0,
        ge=0.5,
        le=1.0,
        description=(
            "Share of assumptions that must be de-risked before the "
            "projected horizon is reached (0.5–1.0)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationMomentumOut:
    """
    Measure how fast a project's assumptions are being validated and
    project when the remaining work will finish. Combines the current
    coverage/de-risked counts with evidence cadence (experiments per week,
    recent vs overall trend) and per-assumption first-evidence /
    first-de-risked velocities, then projects weeks and calendar dates to
    full coverage and to ``target_de_risked_pct`` de-risked. Like the
    evidence digest and validation timeline, this endpoint does not require
    a completed simulation.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.asc(),
            AssumptionEvidence.id.asc(),
        )
        .all()
    )
    return ValidationMomentumOut(
        **build_validation_momentum(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
            target_de_risked_pct=target_de_risked_pct,
        )
    )


@router.get(
    "/{project_id}/validation-momentum/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's validation momentum as CSV, JSON, or Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_validation_momentum(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "summary with counts, velocity, forecast, and insights; "
            "``json`` returns the envelope payload; ``md`` returns a "
            "founder-facing Markdown brief. Unsupported values return a "
            "400 response."
        ),
    ),
    target_de_risked_pct: float = Query(
        default=1.0,
        ge=0.5,
        le=1.0,
        description=(
            "Share of assumptions that must be de-risked before the "
            "projected horizon is reached (0.5–1.0)."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same momentum forecast shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    momentum = get_validation_momentum(
        project_id=project_id,
        target_de_risked_pct=target_de_risked_pct,
        db=db,
        current_user=current_user,
    )
    payload = momentum.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": VALIDATION_MOMENTUM_FORMAT_VERSION,
    }

    if fmt == "json":
        body = validation_momentum_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"validation-momentum-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = validation_momentum_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-momentum-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = validation_momentum_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"validation-momentum-{project_id}.csv"
        media_type = "text/csv; charset=utf-8"

    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{project_id}/evidence-freshness",
    response_model=EvidenceStalenessOut,
    summary="Per-assumption evidence freshness with a prioritised re-test queue",
    responses=_JSON_200,
)
def get_evidence_freshness(
    project_id: int,
    fresh_days: int = Query(
        default=DEFAULT_FRESH_DAYS,
        ge=MIN_WINDOW_DAYS,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence within this many days counts as ``FRESH``."
        ),
    ),
    aging_days: int = Query(
        default=DEFAULT_AGING_DAYS,
        ge=MIN_WINDOW_DAYS + 1,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence older than this many days counts as "
            "``STALE``; in between is ``AGING``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceStalenessOut:
    """
    Age every non-hidden assumption's most recent logged experiment and
    rank the results into a founder-facing re-test queue.

    Never-tested assumptions lead the queue, followed by stale ones ordered
    by sensitivity. Like the other validation endpoints this does **not**
    require a completed simulation.
    """
    if fresh_days >= aging_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"fresh_days ({fresh_days}) must be strictly less than "
                f"aging_days ({aging_days})"
            ),
        )

    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.asc(),
            AssumptionEvidence.id.asc(),
        )
        .all()
    )

    payload = build_evidence_staleness(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project.id,
        fresh_days=fresh_days,
        aging_days=aging_days,
    )
    return EvidenceStalenessOut(**payload)


@router.get(
    "/{project_id}/evidence-freshness/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's evidence-freshness re-test queue as CSV, JSON, "
        "or Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_evidence_freshness(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "summary with the full re-test queue; ``json`` returns the "
            "envelope payload; ``md`` returns a founder-facing Markdown "
            "brief. Unsupported values return a 400 response."
        ),
    ),
    fresh_days: int = Query(
        default=DEFAULT_FRESH_DAYS,
        ge=MIN_WINDOW_DAYS,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence within this many days counts as ``FRESH``."
        ),
    ),
    aging_days: int = Query(
        default=DEFAULT_AGING_DAYS,
        ge=MIN_WINDOW_DAYS + 1,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence older than this many days counts as "
            "``STALE``; in between is ``AGING``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same re-test queue shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )
    if fresh_days >= aging_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"fresh_days ({fresh_days}) must be strictly less than "
                f"aging_days ({aging_days})"
            ),
        )

    freshness = get_evidence_freshness(
        project_id=project_id,
        fresh_days=fresh_days,
        aging_days=aging_days,
        db=db,
        current_user=current_user,
    )
    payload = freshness.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": EVIDENCE_FRESHNESS_FORMAT_VERSION,
    }

    if fmt == "json":
        body = evidence_staleness_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-freshness-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = evidence_staleness_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-freshness-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = evidence_staleness_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-freshness-{project_id}.csv"
        media_type = "text/csv; charset=utf-8"

    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{project_id}/validation-dashboard",
    response_model=ValidationDashboardOut,
    summary="Combined validation dashboard: digest + milestones + momentum",
    responses=_JSON_200,
)
def get_validation_dashboard(
    project_id: int,
    target_de_risked_pct: float = Query(
        default=1.0,
        ge=0.5,
        le=1.0,
        description=(
            "Share of assumptions that must be de-risked before the "
            "projected horizon is reached (0.5–1.0)."
        ),
    ),
    fresh_days: int = Query(
        default=DEFAULT_FRESH_DAYS,
        ge=MIN_WINDOW_DAYS,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence within this many days counts as ``FRESH`` "
            "in the freshness rollup."
        ),
    ),
    aging_days: int = Query(
        default=DEFAULT_AGING_DAYS,
        ge=MIN_WINDOW_DAYS + 1,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence older than this many days counts as "
            "``STALE``; in between is ``AGING``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationDashboardOut:
    """
    Single-response de-risking overview that composes the evidence digest,
    validation-timeline milestones, and validation-momentum forecast.

    Loads assumptions and evidence once and passes them to all three
    builders, so the dashboard is cheaper to compute than three separate
    calls. Like the underlying endpoints, this does **not** require a
    completed simulation — a founder can track de-risking progress from the
    first logged experiment.
    """
    project = get_owned_project(db, current_user.id, project_id)
    assumptions = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project.id,
            Assumption.is_hidden.is_(False),
        )
        .order_by(Assumption.id.asc())
        .all()
    )
    evidence = (
        db.query(AssumptionEvidence)
        .filter(AssumptionEvidence.project_id == project.id)
        .order_by(
            AssumptionEvidence.created_at.asc(),
            AssumptionEvidence.id.asc(),
        )
        .all()
    )

    digest = build_assumption_evidence_digest(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project.id,
    )
    timeline = build_validation_timeline(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project.id,
    )
    momentum = build_validation_momentum(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project.id,
        target_de_risked_pct=target_de_risked_pct,
    )
    if fresh_days >= aging_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"fresh_days ({fresh_days}) must be strictly less than "
                f"aging_days ({aging_days})"
            ),
        )

    freshness = build_evidence_staleness(
        assumptions=assumptions,
        evidence=evidence,
        project_id=project.id,
        fresh_days=fresh_days,
        aging_days=aging_days,
    )
    retest_queue_top = [
        EvidenceStalenessRowOut(**row)
        for row in freshness["rows"]
        if row["freshness"] in (FRESHNESS_NEVER_TESTED, FRESHNESS_STALE)
    ][:3]

    return ValidationDashboardOut(
        project_id=project.id,
        evidence_digest=AssumptionEvidenceDigestOut(**digest),
        timeline_milestones=ValidationTimelineMilestonesOut(**timeline["milestones"]),
        momentum=ValidationMomentumOut(**momentum),
        evidence_freshness=EvidenceStalenessSummaryOut(**freshness["summary"]),
        retest_queue_top=retest_queue_top,
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": DASHBOARD_MODEL,
            "source": [
                "evidence-digest",
                "assumption-validation-timeline",
                "validation-momentum",
                "evidence-freshness",
            ],
        },
    )


@router.get(
    "/{project_id}/validation-dashboard/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's validation dashboard as CSV, JSON, or Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_validation_dashboard(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "summary with assumption rows; ``json`` returns the full "
            "dashboard envelope; ``md`` returns a founder-facing Markdown "
            "brief. Unsupported values return a 400 response."
        ),
    ),
    target_de_risked_pct: float = Query(
        default=1.0,
        ge=0.5,
        le=1.0,
        description=(
            "Share of assumptions that must be de-risked before the "
            "projected horizon is reached (0.5–1.0)."
        ),
    ),
    fresh_days: int = Query(
        default=DEFAULT_FRESH_DAYS,
        ge=MIN_WINDOW_DAYS,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence within this many days counts as ``FRESH`` "
            "in the freshness rollup."
        ),
    ),
    aging_days: int = Query(
        default=DEFAULT_AGING_DAYS,
        ge=MIN_WINDOW_DAYS + 1,
        le=MAX_WINDOW_DAYS,
        description=(
            "Latest evidence older than this many days counts as "
            "``STALE``; in between is ``AGING``."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same de-risking dashboard shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )
    if fresh_days >= aging_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"fresh_days ({fresh_days}) must be strictly less than "
                f"aging_days ({aging_days})"
            ),
        )

    dashboard = get_validation_dashboard(
        project_id=project_id,
        target_de_risked_pct=target_de_risked_pct,
        fresh_days=fresh_days,
        aging_days=aging_days,
        db=db,
        current_user=current_user,
    )
    payload = dashboard.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": VALIDATION_DASHBOARD_FORMAT_VERSION,
    }

    if fmt == "json":
        body = validation_dashboard_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-dashboard-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = validation_dashboard_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-dashboard-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = validation_dashboard_to_csv(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-dashboard-{project_id}.csv"
        media_type = "text/csv; charset=utf-8"

    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{project_id}/assumptions/{assumption_id}/evidence-scorecard/export",
    response_class=StreamingResponse,
    summary=(
        "Export an assumption's evidence scorecard as CSV, JSON, or Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_assumption_evidence_scorecard(
    project_id: int,
    assumption_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default, UTF-8 BOM) returns a "
            "spreadsheet-friendly summary with evidence rows; ``json`` returns "
            "the full scorecard envelope; ``md`` returns a founder-facing "
            "Markdown brief. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same scorecard shown by the JSON endpoint.

    Reuses :func:`get_assumption_evidence_scorecard` so the export can never
    disagree with the dashboard.  Formula-injection guards are applied to CSV
    cells so free-form assumption text and notes stay inert in spreadsheets.
    """
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    scorecard = get_assumption_evidence_scorecard(
        project_id=project_id,
        assumption_id=assumption_id,
        db=db,
        current_user=current_user,
    )
    payload = scorecard.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "format_version": EVIDENCE_SCORECARD_FORMAT_VERSION,
        "assumption_id": assumption_id,
        "project_id": project_id,
    }

    if fmt == "json":
        body = evidence_scorecard_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-scorecard-{project_id}-{assumption_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = evidence_scorecard_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-scorecard-{project_id}-{assumption_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = evidence_scorecard_to_csv(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-scorecard-{project_id}-{assumption_id}.csv"
        media_type = "text/csv; charset=utf-8"

    return StreamingResponse(
        iter([body]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )
