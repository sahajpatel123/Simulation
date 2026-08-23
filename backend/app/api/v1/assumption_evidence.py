"""
Assumption-evidence log and de-risking scorecard routes.

The validation-experiment planner says *what* to run; these endpoints let a
founder record *what happened* and see the consequence:

* ``POST /projects/{project_id}/assumptions/{assumption_id}/evidence``
  logs one experiment result (method + PASS/FAIL/INCONCLUSIVE).
* ``POST /projects/{project_id}/assumptions/evidence/import`` logs many
  results in one call — invalid rows are skipped with reasons instead of
  blocking the valid ones.
* ``POST /projects/{project_id}/assumptions/evidence/import/csv`` does the
  same from raw CSV text — a downloaded export can be filled in offline
  and pasted straight back.
* ``POST /projects/{project_id}/assumptions/import`` bulk-creates
  assumptions (JSON rows), skipping duplicates against the project and
  within the batch so re-imports are idempotent.
* ``POST /projects/{project_id}/assumptions/import/csv`` does the same
  from raw CSV text with per-row skip reasons.
* ``GET /projects/{project_id}/assumptions/export`` downloads the
  project's assumptions in exactly that CSV shape, so export → edit
  offline → re-import is a lossless, duplicate-free round trip.
* ``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard``
  returns the evidence history plus the before/after validation-ROI shift
  implied by the derived confidence tier.
* ``GET /projects/{project_id}/evidence-digest`` rolls every logged
  experiment up into a project-level de-risking summary.
* ``GET /projects/{project_id}/assumption-validation-timeline`` replays
  every logged experiment chronologically with cumulative validation
  progress and first-occurrence milestones.
* ``GET /projects/{project_id}/assumption-validation-timeline/export``
  downloads that replay as CSV, JSON, or a founder-facing Markdown brief.
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
* ``GET /projects/{project_id}/evidence-verdicts`` judges each assumption's
  latest decisive experiment against its method's success bar (ON_TRACK /
  KILLED / INCONSISTENT_*), surfacing records that contradict their own
  metric.
* ``GET /projects/{project_id}/evidence-verdicts/export`` downloads that
  scorecard as CSV, JSON, or a founder-facing Markdown brief.
* ``GET /projects/{project_id}/assumption-recovery-plan`` turns killed and
  inconsistent verdicts into ordered recovery plays — a reframed
  hypothesis plus a concrete re-test from the planner's METHOD_SPECS.
* ``GET /projects/{project_id}/assumption-recovery-plan/export``
  downloads that plan as CSV, JSON, or a founder-facing Markdown brief.
* ``GET /projects/{project_id}/evidence-quality`` grades how trustworthy
  each logged experiment is — method reliability, decisiveness, metric
  presence, recency — and names the project's weakest link.

Pure post-hoc analysis — no Celery dispatch, no LLM calls.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any, get_args

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
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
    EVIDENCE_IMPORT_MAX_ROWS,
    EVIDENCE_RESULT_LITERAL,
    AssumptionEvidenceDigestOut,
    AssumptionEvidenceScorecardOut,
    EvidenceCreate,
    EvidenceImportOut,
    EvidenceImportRequest,
    EvidenceImportRow,
    EvidenceImportSkippedRow,
    EvidenceOut,
)
from app.schemas.assumption_import import (
    ASSUMPTION_IMPORT_MAX_ROWS,
    SENSITIVITY_LITERAL,
    AssumptionImportOut,
    AssumptionImportRequest,
    AssumptionImportRow,
    AssumptionImportSkippedRow,
)
from app.schemas.evidence_quality import EvidenceQualityOut
from app.schemas.evidence_staleness import (
    EvidenceStalenessOut,
    EvidenceStalenessRowOut,
    EvidenceStalenessSummaryOut,
)
from app.schemas.evidence_verdicts import EvidenceVerdictsOut
from app.schemas.recovery_plan import RecoveryPlanOut
from app.schemas.validation_dashboard import DASHBOARD_MODEL, ValidationDashboardOut
from app.schemas.validation_experiment import METHOD_ID_LITERAL
from app.schemas.validation_momentum import ValidationMomentumOut
from app.schemas.validation_risk_map import ValidationRiskMapOut
from app.schemas.validation_timeline import (
    AssumptionValidationTimelineOut,
    ValidationTimelineMilestonesOut,
)
from app.simulation.assumption_evidence_digest import (
    build_assumption_evidence_digest,
)
from app.simulation.evidence_quality import build_evidence_quality
from app.simulation.evidence_quality_export import (
    FORMAT_VERSION as EVIDENCE_QUALITY_FORMAT_VERSION,
)
from app.simulation.evidence_quality_export import (
    evidence_quality_to_csv,
    evidence_quality_to_json,
    evidence_quality_to_markdown,
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
from app.simulation.evidence_verdicts import build_evidence_verdicts
from app.simulation.evidence_verdicts_export import (
    FORMAT_VERSION as EVIDENCE_VERDICTS_FORMAT_VERSION,
)
from app.simulation.evidence_verdicts_export import (
    evidence_verdicts_to_csv,
    evidence_verdicts_to_json,
    evidence_verdicts_to_markdown,
)
from app.simulation.recovery_planner import build_recovery_plan
from app.simulation.recovery_planner_export import (
    FORMAT_VERSION as RECOVERY_PLAN_FORMAT_VERSION,
)
from app.simulation.recovery_planner_export import (
    recovery_plan_to_csv,
    recovery_plan_to_json,
    recovery_plan_to_markdown,
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
from app.simulation.validation_risk_map import build_validation_risk_map
from app.simulation.validation_risk_map_export import (
    FORMAT_VERSION as VALIDATION_RISK_MAP_FORMAT_VERSION,
)
from app.simulation.validation_risk_map_export import (
    validation_risk_map_to_csv,
    validation_risk_map_to_json,
    validation_risk_map_to_markdown,
)
from app.simulation.validation_timeline import build_validation_timeline
from app.simulation.validation_timeline_export import (
    FORMAT_VERSION as VALIDATION_TIMELINE_FORMAT_VERSION,
)
from app.simulation.validation_timeline_export import (
    validation_timeline_to_csv,
    validation_timeline_to_json,
    validation_timeline_to_markdown,
)

router = APIRouter(prefix="/projects", tags=["assumption-evidence"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

# Acceptable spellings for CSV import cells, derived from the same
# literals the JSON schemas enforce.
VALID_METHOD_IDS: frozenset[str] = frozenset(get_args(METHOD_ID_LITERAL))
VALID_RESULT_IDS: frozenset[str] = frozenset(get_args(EVIDENCE_RESULT_LITERAL))
VALID_SENSITIVITY_IDS: frozenset[str] = frozenset(
    get_args(SENSITIVITY_LITERAL)
)


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


def _apply_evidence_import(
    db: Session,
    project_id: int,
    parsed_rows: list[EvidenceImportRow],
    parse_skips: list[EvidenceImportSkippedRow],
) -> EvidenceImportOut:
    """Insert parsed evidence rows, skipping unknown assumptions.

    Shared by the JSON and CSV import routes; the caller supplies any
    parse-level skips so their indices line up with data-row positions.
    Rows name their assumption by ``assumption_id`` or, when the id is
    absent, by case-insensitive ``assumption_text`` match.
    """
    project_assumptions = (
        db.query(Assumption).filter(Assumption.project_id == project_id).all()
    )
    assumptions_by_id = {assumption.id: assumption for assumption in project_assumptions}
    ids_by_text = {
        (assumption.text or "").strip().casefold(): assumption.id
        for assumption in project_assumptions
    }

    rows_to_insert: list[AssumptionEvidence] = []
    skipped_rows = list(parse_skips)
    touched_ids: list[int] = []
    for index, row in enumerate(parsed_rows):
        if row.assumption_id > 0:
            assumption = assumptions_by_id.get(row.assumption_id)
            if assumption is None:
                skipped_rows.append(
                    EvidenceImportSkippedRow(
                        index=index,
                        assumption_id=row.assumption_id,
                        reason=(
                            f"assumption {row.assumption_id} does not exist "
                            "in this project"
                        ),
                    )
                )
                continue
        else:
            matched_id = ids_by_text.get(
                (row.assumption_text or "").strip().casefold()
            )
            if matched_id is None:
                skipped_rows.append(
                    EvidenceImportSkippedRow(
                        index=index,
                        assumption_id=None,
                        reason=(
                            "no assumption matches text "
                            f"{row.assumption_text!r} in this project"
                        ),
                    )
                )
                continue
            assumption = assumptions_by_id[matched_id]
        rows_to_insert.append(
            AssumptionEvidence(
                project_id=project_id,
                assumption_id=assumption.id,
                method=row.method,
                result=row.result,
                observed_metric=row.observed_metric,
                notes=row.notes,
            )
        )
        if assumption.id not in touched_ids:
            touched_ids.append(assumption.id)

    # One commit for the whole batch — never per-row commits in a loop.
    if rows_to_insert:
        db.add_all(rows_to_insert)
        db.commit()

    return EvidenceImportOut(
        project_id=project_id,
        imported_count=len(rows_to_insert),
        skipped_count=len(skipped_rows),
        skipped_rows=skipped_rows,
        assumption_ids_touched=touched_ids,
    )


@router.post(
    "/{project_id}/assumptions/evidence/import",
    response_model=EvidenceImportOut,
    summary="Bulk-log validation experiment results for many assumptions",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def import_assumption_evidence(
    project_id: int,
    payload: EvidenceImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportOut:
    """
    Record many validation experiment results in one call — the write-side
    complement to the CSV exports, so a founder can fill in a downloaded
    spreadsheet offline and paste the outcomes back.

    Each row names its assumption by ``assumption_id`` or, failing that,
    by case-insensitive ``assumption_text`` match against the project's
    assumptions. Rows referencing an assumption that does not exist are
    skipped with a reason instead of failing the whole import. Valid rows
    insert in a single commit.
    """
    project = get_owned_project(db, current_user.id, project_id)
    return _apply_evidence_import(
        db, project.id, payload.rows, []
    )


_CSV_IMPORT_REQUIRED_HEADERS: tuple[str, ...] = (
    "method",
    "result",
)


@router.post(
    "/{project_id}/assumptions/evidence/import/csv",
    response_model=EvidenceImportOut,
    summary="Bulk-log experiment results from raw CSV text",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
async def import_assumption_evidence_csv(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceImportOut:
    """
    Paste a spreadsheet straight back into TheCee: accepts raw CSV text
    with the columns ``assumption_id,method,result`` (or ``assumption_text``
    instead of the id) plus optional ``observed_metric`` and ``notes`` —
    the same shape the validation exports download.

    Rows that fail parsing (unknown method or result, bad numbers) are
    skipped with founder-readable reasons instead of failing the batch;
    valid rows insert in a single commit.
    """
    project = get_owned_project(db, current_user.id, project_id)
    try:
        text = (await request.body()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"request body is not valid UTF-8 text: {exc}",
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = [header.strip() for header in (reader.fieldnames or [])]
    missing = [
        column
        for column in _CSV_IMPORT_REQUIRED_HEADERS
        if column not in headers
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "CSV is missing required column(s): "
                f"{', '.join(missing)}; expected header row with "
                "assumption_id (or assumption_text), method, result"
                "[, observed_metric, notes]"
            ),
        )

    def _cell(row: dict[str, str | None], name: str) -> str:
        value = row.get(name)
        return "" if value is None else value.strip()

    parsed_rows: list[EvidenceImportRow] = []
    parse_skips: list[EvidenceImportSkippedRow] = []
    data_index = -1
    for raw in reader:
        cells = {
            (key.strip() if key else key): value
            for key, value in raw.items()
        }
        if not any((value or "").strip() for value in cells.values()):
            continue  # entirely blank line — not a data row
        data_index += 1

        def skip(reason: str) -> None:
            parse_skips.append(
                EvidenceImportSkippedRow(
                    index=data_index,
                    assumption_id=None,
                    reason=reason,
                )
            )

        raw_id = _cell(cells, "assumption_id")
        assumption_text: str | None = None
        assumption_id = 0
        if raw_id:
            try:
                assumption_id = int(raw_id)
            except ValueError:
                skip(f"assumption_id {raw_id!r} is not a whole number")
                continue
        else:
            # No id — resolve by exact (case-insensitive) text instead.
            assumption_text = _cell(cells, "assumption_text") or None

        method = _cell(cells, "method").upper()
        result = _cell(cells, "result").upper()
        if method not in VALID_METHOD_IDS:
            skip(f"method {method!r} is not a known experiment method")
            continue
        if result not in VALID_RESULT_IDS:
            skip(f"result {result!r} is not one of PASS/FAIL/INCONCLUSIVE")
            continue

        observed_raw = _cell(cells, "observed_metric")
        observed_metric: float | None = None
        if observed_raw:
            try:
                observed_metric = float(observed_raw)
            except ValueError:
                skip(f"observed_metric {observed_raw!r} is not a number")
                continue

        notes = _cell(cells, "notes") or None
        if notes is not None and len(notes) > 500:
            skip("notes exceed the 500-character limit")
            continue

        try:
            parsed_rows.append(
                EvidenceImportRow.model_validate(
                    {
                        "assumption_id": assumption_id,
                        "assumption_text": assumption_text,
                        "method": method,
                        "result": result,
                        "observed_metric": observed_metric,
                        "notes": notes,
                    }
                )
            )
        except ValueError as exc:
            skip(f"row is not a valid experiment record: {exc}")

    if len(parsed_rows) + len(parse_skips) > EVIDENCE_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"CSV exceeds the {EVIDENCE_IMPORT_MAX_ROWS}-row import "
                "limit"
            ),
        )

    return _apply_evidence_import(db, project.id, parsed_rows, parse_skips)


_ASSUMPTION_EXPORT_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "text",
    "category",
    "sensitivity",
    "impact_score",
)


def _csv_guard(value: object) -> object:
    """Neutralise spreadsheet formulas in exported CSV cells."""
    if isinstance(value, str) and (
        value.lstrip()[:1] in ("=", "+", "-", "@")
        or value[:1] in ("\t", "\r", "\n")
    ):
        return f"'{value}"
    return value


@router.get(
    "/{project_id}/assumptions/export",
    response_class=StreamingResponse,
    summary=(
        "Download a project's assumptions in the bulk-import CSV shape"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_assumptions_csv(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Emit the project's non-hidden assumptions as CSV with exactly the
    columns ``text,category,sensitivity,impact_score`` that
    ``POST /{project_id}/assumptions/import/csv`` consumes — so a founder
    can download, edit offline, and re-import; duplicate rows skip
    themselves.
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

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(_ASSUMPTION_EXPORT_HEADERS))
    for assumption in assumptions:
        writer.writerow(
            [
                _csv_guard(value)
                for value in (
                    assumption.id,
                    assumption.text or "",
                    assumption.category or "",
                    assumption.sensitivity or "",
                    (
                        ""
                        if assumption.impact_score is None
                        else assumption.impact_score
                    ),
                )
            ]
        )

    body = buffer.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="assumptions-{project.id}.csv"'
            ),
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
        },
    )


def _apply_assumption_import(
    db: Session,
    project_id: int,
    parsed_rows: list[AssumptionImportRow],
    parse_skips: list[AssumptionImportSkippedRow],
) -> AssumptionImportOut:
    """Create parsed assumption rows, skipping duplicates.

    Shared by the JSON and CSV assumption-import routes. A row is skipped
    when its text (case-insensitively) already exists in the project or
    repeats earlier in the same batch, making re-imports idempotent.
    """
    existing_keys = {
        (assumption.text or "").strip().casefold()
        for assumption in db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .all()
    }

    rows_to_insert: list[Assumption] = []
    skipped_rows = list(parse_skips)
    for index, row in enumerate(parsed_rows):
        key = row.text.strip().casefold()
        if key in existing_keys:
            skipped_rows.append(
                AssumptionImportSkippedRow(
                    index=index,
                    reason=(
                        "an assumption with this text already exists in "
                        "this project"
                    ),
                )
            )
            continue
        existing_keys.add(key)
        rows_to_insert.append(
            Assumption(
                project_id=project_id,
                text=row.text.strip(),
                category=row.category.strip() or "Market",
                sensitivity=row.sensitivity,
                impact_score=min(10.0, max(1.0, row.impact_score)),
            )
        )

    # One commit for the whole batch — never per-row commits in a loop.
    if rows_to_insert:
        db.add_all(rows_to_insert)
        db.commit()

    return AssumptionImportOut(
        project_id=project_id,
        imported_count=len(rows_to_insert),
        skipped_count=len(skipped_rows),
        skipped_rows=skipped_rows,
    )


@router.post(
    "/{project_id}/assumptions/import",
    response_model=AssumptionImportOut,
    summary="Bulk-create assumptions on a project (idempotent)",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def import_assumptions(
    project_id: int,
    payload: AssumptionImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionImportOut:
    """
    Create many assumptions in one call — the write-side complement to the
    assumption-bearing exports. Rows whose text already exists in the
    project (or repeats within the batch) are skipped with reasons instead
    of creating duplicates, so re-running an import is safe. Valid rows
    insert in a single commit.
    """
    project = get_owned_project(db, current_user.id, project_id)
    return _apply_assumption_import(db, project.id, payload.rows, [])


@router.post(
    "/{project_id}/assumptions/import/csv",
    response_model=AssumptionImportOut,
    summary="Bulk-create assumptions from raw CSV text",
    responses=_JSON_200,
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
async def import_assumptions_csv(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssumptionImportOut:
    """
    Paste an assumption list straight into TheCee: raw CSV text with the
    columns ``text`` plus optional ``category``, ``sensitivity``, and
    ``impact_score``. Case-normalised sensitivity; rows failing parsing
    are skipped with reasons; valid rows insert in a single commit.
    """
    project = get_owned_project(db, current_user.id, project_id)
    try:
        text = (await request.body()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"request body is not valid UTF-8 text: {exc}",
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = [header.strip() for header in (reader.fieldnames or [])]
    if "text" not in headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "CSV is missing required column(s): text; expected header "
                "row with text[, category, sensitivity, impact_score]"
            ),
        )

    def _cell(row: dict[str, str | None], name: str) -> str:
        value = row.get(name)
        return "" if value is None else value.strip()

    parsed_rows: list[AssumptionImportRow] = []
    parse_skips: list[AssumptionImportSkippedRow] = []
    data_index = -1
    for raw in reader:
        cells = {
            (key.strip() if key else key): value
            for key, value in raw.items()
        }
        if not any((value or "").strip() for value in cells.values()):
            continue  # entirely blank line — not a data row
        data_index += 1

        def skip(reason: str) -> None:
            parse_skips.append(
                AssumptionImportSkippedRow(
                    index=data_index,
                    reason=reason,
                )
            )

        row_text = _cell(cells, "text")
        if not row_text:
            skip("text is empty")
            continue
        if len(row_text) > 2000:
            skip("text exceeds the 2000-character limit")
            continue

        sensitivity = _cell(cells, "sensitivity").upper() or "MEDIUM"
        if sensitivity not in VALID_SENSITIVITY_IDS:
            skip(
                f"sensitivity {sensitivity!r} is not one of "
                "LOW/MEDIUM/HIGH/CRITICAL"
            )
            continue

        category = _cell(cells, "category") or "Market"
        if len(category) > 100:
            skip("category exceeds the 100-character limit")
            continue

        impact_raw = _cell(cells, "impact_score")
        impact_score = 5.0
        if impact_raw:
            try:
                impact_score = float(impact_raw)
            except ValueError:
                skip(f"impact_score {impact_raw!r} is not a number")
                continue
            if not 1.0 <= impact_score <= 10.0:
                skip("impact_score must be between 1.0 and 10.0")
                continue

        parsed_rows.append(
            AssumptionImportRow.model_validate(
                {
                    "text": row_text,
                    "category": category,
                    "sensitivity": sensitivity,
                    "impact_score": impact_score,
                }
            )
        )

    if len(parsed_rows) + len(parse_skips) > ASSUMPTION_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"CSV exceeds the {ASSUMPTION_IMPORT_MAX_ROWS}-row import "
                "limit"
            ),
        )

    return _apply_assumption_import(db, project.id, parsed_rows, parse_skips)


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
    "/{project_id}/evidence-verdicts",
    response_model=EvidenceVerdictsOut,
    summary="Judge each assumption's evidence against its method's success bar",
    responses=_JSON_200,
)
def get_evidence_verdicts(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceVerdictsOut:
    """
    Close the validation loop: the planner set every method a success bar
    ("≥ 30% would pay"), founders logged metrics — this scorecard compares
    them. The latest decisive experiment per assumption becomes ON_TRACK or
    KILLED; records that contradict their own metric (a PASS below the bar,
    a FAIL above it) are surfaced as INCONSISTENT rather than trusted. Pure
    post-hoc analysis — no Celery dispatch, no LLM calls.
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
    return EvidenceVerdictsOut(
        **build_evidence_verdicts(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/evidence-verdicts/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's evidence-verdict scorecard as CSV, JSON, or "
        "Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_evidence_verdicts(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "summary with the full verdict table; ``json`` returns the "
            "envelope payload; ``md`` returns a founder-facing Markdown "
            "brief. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same verdict scorecard shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    verdicts = get_evidence_verdicts(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = verdicts.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": EVIDENCE_VERDICTS_FORMAT_VERSION,
    }

    if fmt == "json":
        body = evidence_verdicts_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-verdicts-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = evidence_verdicts_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-verdicts-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = evidence_verdicts_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-verdicts-{project_id}.csv"
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
    "/{project_id}/assumption-recovery-plan",
    response_model=RecoveryPlanOut,
    summary="Ordered recovery plays for killed and inconsistent assumptions",
    responses=_JSON_200,
)
def get_assumption_recovery_plan(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecoveryPlanOut:
    """
    The verdicts scorecard says *what* died; this says *what to do next*.
    Every KILLED or INCONSISTENT_* assumption gets deterministic recovery
    plays selected by theme — pricing, demand, trust, competition,
    usability, retention — each rendered from the experiment planner's
    METHOD_SPECS (method, cost tier, duration, sample target, success bar).
    Inconsistent records get an audit play first: verify the bookkeeping
    before spending on new experiments.
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
    return RecoveryPlanOut(
        **build_recovery_plan(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/assumption-recovery-plan/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's assumption recovery plan as CSV, JSON, or "
        "Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_assumption_recovery_plan(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "summary with one row per recovery play; ``json`` returns the "
            "envelope payload; ``md`` returns a founder-facing Markdown "
            "brief. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same recovery plan shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    plan = get_assumption_recovery_plan(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = plan.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": RECOVERY_PLAN_FORMAT_VERSION,
    }

    if fmt == "json":
        body = recovery_plan_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"recovery-plan-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = recovery_plan_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"recovery-plan-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = recovery_plan_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"recovery-plan-{project_id}.csv"
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
    "/{project_id}/evidence-quality",
    response_model=EvidenceQualityOut,
    summary="Grade how trustworthy each logged experiment's evidence is",
    responses=_JSON_200,
)
def get_evidence_quality(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvidenceQualityOut:
    """
    Verdicts say what the records *say*; quality says how much to *trust*
    them. Every experiment row is scored on method reliability (observed
    commitment outranks stated intent and desk research), decisiveness
    (PASS/FAIL vs INCONCLUSIVE), metric presence, and recency; assumption
    scores blend the latest row with older history and roll up to a
    project index. The weakest link names where the validation story is
    thinnest.
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
    return EvidenceQualityOut(
        **build_evidence_quality(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/evidence-quality/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's evidence-quality report as CSV, JSON, or "
        "Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_evidence_quality(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "quality table with native numeric cells; ``json`` returns the "
            "envelope payload; ``md`` returns a founder-facing Markdown "
            "brief. Unsupported values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same quality report shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    report = get_evidence_quality(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = report.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": EVIDENCE_QUALITY_FORMAT_VERSION,
    }

    if fmt == "json":
        body = evidence_quality_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-quality-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = evidence_quality_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"evidence-quality-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = evidence_quality_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"evidence-quality-{project_id}.csv"
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
    "/{project_id}/validation-risk-map",
    response_model=ValidationRiskMapOut,
    summary="Rank assumption categories by validation risk",
    responses=_JSON_200,
)
def get_validation_risk_map(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ValidationRiskMapOut:
    """
    The per-assumption endpoints answer one claim at a time; this map
    answers the portfolio question: which area of the business model has
    the weakest validation story? Assumptions are grouped by category
    and ranked by a transparent risk score combining killed verdicts,
    self-contradicting records, untested claims, and low-trust evidence.
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
    return ValidationRiskMapOut(
        **build_validation_risk_map(
            assumptions=assumptions,
            evidence=evidence,
            project_id=project.id,
        )
    )


@router.get(
    "/{project_id}/validation-risk-map/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's validation risk map as CSV, JSON, or "
        "Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_validation_risk_map(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "category risk table with native numeric cells; ``json`` "
            "returns the envelope payload; ``md`` returns a "
            "founder-facing Markdown brief. Unsupported values return a "
            "400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same risk map shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    report = get_validation_risk_map(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = report.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": VALIDATION_RISK_MAP_FORMAT_VERSION,
    }

    if fmt == "json":
        body = validation_risk_map_to_json(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-risk-map-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = validation_risk_map_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-risk-map-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = validation_risk_map_to_csv(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-risk-map-{project_id}.csv"
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
    "/{project_id}/assumption-validation-timeline/export",
    response_class=StreamingResponse,
    summary=(
        "Export a project's validation timeline as CSV, JSON, or Markdown"
    ),
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def export_assumption_validation_timeline(
    project_id: int,
    format: str = Query(
        default="csv",
        max_length=8,
        description=(
            "Output format. ``csv`` (default) returns a spreadsheet-friendly "
            "document with every event, cumulative progress snapshots, and "
            "per-assumption rollups; ``json`` returns the envelope payload; "
            "``md`` returns a founder-facing Markdown brief. Unsupported "
            "values return a 400 response."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download the same timeline shown by the JSON endpoint."""
    fmt = (format or "csv").strip().lower()
    if fmt not in {"csv", "json", "md"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"unsupported export format {format!r}; expected 'csv', "
                "'json', or 'md'"
            ),
        )

    timeline = get_assumption_validation_timeline(
        project_id=project_id,
        db=db,
        current_user=current_user,
    )
    payload = timeline.model_dump()
    metadata = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": current_user.id,
        "project_id": project_id,
        "format_version": VALIDATION_TIMELINE_FORMAT_VERSION,
    }

    if fmt == "json":
        body = validation_timeline_to_json(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"validation-timeline-{project_id}.json"
        media_type = "application/json; charset=utf-8"
    elif fmt == "md":
        body = validation_timeline_to_markdown(
            payload,
            metadata=metadata,
        ).encode("utf-8")
        filename = f"validation-timeline-{project_id}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        body = validation_timeline_to_csv(payload, metadata=metadata).encode(
            "utf-8"
        )
        filename = f"validation-timeline-{project_id}.csv"
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


_WORKBOOK_FILENAME_RE = re.compile(r'filename="([^"]+)"')


async def _workbook_part(builder, **kwargs) -> tuple[bytes, str]:
    """Call one export builder and return ``(body_bytes, filename)``."""
    response = builder(**kwargs)
    body = b"".join([chunk async for chunk in response.body_iterator])
    disposition = response.headers.get("Content-Disposition", "")
    match = _WORKBOOK_FILENAME_RE.search(disposition)
    filename = match.group(1) if match else "sheet.csv"
    return body, filename


@router.get(
    "/{project_id}/validation-workbook/export",
    response_class=StreamingResponse,
    summary="Download every validation export as one ZIP workbook",
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
async def export_validation_workbook(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Bundle the project's validation exports into a single ZIP.

    One download carries the assumptions sheet (import-shaped), the
    validation timeline, momentum forecast, evidence-freshness re-test
    queue, and the validation dashboard — each in its CSV form — plus a
    ``README.txt`` manifest. A sheet that fails to build never sinks the
    bundle: it is reported in ``errors.txt`` instead.
    """
    project = get_owned_project(db, current_user.id, project_id)

    sheets: list[tuple[str, bytes]] = []
    failures: list[str] = []

    builders: list[tuple[str, Any]] = [
        ("assumptions", export_assumptions_csv),
        ("validation-timeline", export_assumption_validation_timeline),
        ("validation-momentum", export_validation_momentum),
        ("evidence-freshness", export_evidence_freshness),
        ("validation-dashboard", export_validation_dashboard),
    ]
    for label, builder in builders:
        try:
            kwargs: dict[str, Any] = {
                "project_id": project.id,
                "db": db,
                "current_user": current_user,
            }
            if builder is not export_assumptions_csv:
                kwargs["format"] = "csv"
            if builder is export_validation_momentum:
                kwargs["target_de_risked_pct"] = 1.0
            elif builder is export_evidence_freshness:
                kwargs["fresh_days"] = DEFAULT_FRESH_DAYS
                kwargs["aging_days"] = DEFAULT_AGING_DAYS
            elif builder is export_validation_dashboard:
                kwargs["target_de_risked_pct"] = 1.0
                kwargs["fresh_days"] = DEFAULT_FRESH_DAYS
                kwargs["aging_days"] = DEFAULT_AGING_DAYS

            body, filename = await _workbook_part(builder, **kwargs)
            sheets.append((filename, body))
        except HTTPException as exc:
            failures.append(f"{label}: {exc.status_code} {exc.detail}")
        except Exception as exc:  # noqa: BLE001 — one bad sheet must not sink the bundle
            failures.append(f"{label}: {exc}")

    # Founder-facing Markdown briefs ride along with the raw CSVs so the
    # workbook doubles as a shareable narrative, not just data.
    for label, builder in (
        ("momentum-brief", export_validation_momentum),
        ("dashboard-brief", export_validation_dashboard),
    ):
        try:
            brief_kwargs: dict[str, Any] = {
                "project_id": project.id,
                "format": "md",
                "target_de_risked_pct": 1.0,
                "db": db,
                "current_user": current_user,
            }
            if builder is export_validation_dashboard:
                brief_kwargs["fresh_days"] = DEFAULT_FRESH_DAYS
                brief_kwargs["aging_days"] = DEFAULT_AGING_DAYS
            body, filename = await _workbook_part(builder, **brief_kwargs)
            sheets.append((filename, body))
        except HTTPException as exc:
            failures.append(f"{label}: {exc.status_code} {exc.detail}")
        except Exception as exc:  # noqa: BLE001 — one bad sheet must not sink the bundle
            failures.append(f"{label}: {exc}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        generated = datetime.now(tz=UTC).isoformat()
        lines = [
            "TheCee Validation Workbook",
            f"Generated: {generated}",
            f"Project: {project.id}",
            "",
            "Contents:",
        ]
        for filename, body in sheets:
            lines.append(f"- {filename} ({len(body)} bytes)")
        if failures:
            lines.append("")
            lines.append(
                "Sheets that could not be built are listed in errors.txt."
            )
        lines.append("")
        lines.append(
            "assumptions.csv is import-shaped: edit offline and paste it back "
            "through POST /projects/{id}/assumptions/import/csv (duplicates "
            "self-skip); evidence results can be logged per assumption via "
            "POST /projects/{id}/assumptions/evidence/import/csv."
        )
        archive.writestr("README.txt", "\n".join(lines) + "\n")
        for filename, body in sheets:
            archive.writestr(filename, body)
        if failures:
            archive.writestr(
                "errors.txt",
                "Some sheets failed to render:\n\n"
                + "\n".join(failures)
                + "\n",
            )

    zip_body = buffer.getvalue()
    return StreamingResponse(
        iter([zip_body]),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="validation-workbook-{project.id}.zip"'
            ),
            "Content-Length": str(len(zip_body)),
            "Cache-Control": "no-store",
        },
    )
