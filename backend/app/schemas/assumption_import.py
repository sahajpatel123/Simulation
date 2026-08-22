"""Schemas for bulk assumption import.

The write-side complement to the assumption-bearing exports: a founder can
draft an assumption list offline (or re-import a previous export) and paste
it straight into a project. Imports are idempotent — exact-duplicate texts,
both within a batch and against assumptions already in the project, are
skipped with reasons instead of creating noise rows.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ASSUMPTION_IMPORT_MAX_ROWS: int = 200

SENSITIVITY_LITERAL = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class AssumptionImportRow(BaseModel):
    """One assumption inside a bulk assumption import."""

    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="Market", max_length=100)
    sensitivity: SENSITIVITY_LITERAL = "MEDIUM"
    impact_score: float = Field(default=5.0, ge=1.0, le=10.0)


class AssumptionImportRequest(BaseModel):
    """Body for bulk-creating assumptions on a project."""

    model_config = {"extra": "forbid"}

    rows: list[AssumptionImportRow] = Field(
        min_length=1,
        max_length=ASSUMPTION_IMPORT_MAX_ROWS,
    )


class AssumptionImportSkippedRow(BaseModel):
    """One rejected import row, with why it was rejected."""

    index: int = Field(ge=0)
    reason: str


class AssumptionImportOut(BaseModel):
    """Result summary of a bulk assumption import.

    Valid rows insert atomically; duplicates and unparseable rows never
    block the valid ones — each is reported in ``skipped_rows`` so a
    spreadsheet paste can be corrected and re-run.
    """

    project_id: int
    imported_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    skipped_rows: list[AssumptionImportSkippedRow] = Field(
        default_factory=list,
    )


__all__ = [
    "ASSUMPTION_IMPORT_MAX_ROWS",
    "AssumptionImportOut",
    "AssumptionImportRequest",
    "AssumptionImportRow",
    "AssumptionImportSkippedRow",
    "SENSITIVITY_LITERAL",
]
