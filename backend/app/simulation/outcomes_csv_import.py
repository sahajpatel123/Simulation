"""Pure CSV parser for backfilling structured launch outcomes.

Founders often keep real launch numbers in a spreadsheet. The JSON batch
endpoint (``POST /projects/{id}/outcomes/batch``) accepts the same rows, but
hand-converting a spreadsheet into JSON is friction. This module turns a
founder-supplied CSV into the exact validated row payload that batch endpoint
expects, so the two routes share one recording path and one set of semantics
(all-or-nothing, idempotency keys, prediction binding).

Accepted columns
----------------
Required:

* ``actual_conversion_rate`` — fraction in ``[0, 1]``, or ``5%`` style
* ``actual_mrr``
* ``actual_cac``
* ``actual_churn_rate`` — fraction in ``[0, 1]``, or ``5%`` style

Optional:

* ``days_since_launch`` — integer in ``[1, 3650]`` (defaults to 30)
* ``actual_dau``
* ``actual_nps`` — ``[-100, 100]``
* ``notes``
* ``client_request_id`` — idempotency key; must be unique within the file
* ``simulation_id`` — completed simulation owned by the project

Columns the export writes (``id``, ``project_id``, ``created_at``,
``predicted_*``, ``variance_*``, ``calibration_score``) are rejected with an
explicit error instead of being silently ignored, so a stale exported file
cannot be re-imported by accident and mislead the founder into thinking their
edits to read-only prediction columns took effect.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from typing import Any

REQUIRED_COLUMNS: tuple[str, ...] = (
    "actual_conversion_rate",
    "actual_mrr",
    "actual_cac",
    "actual_churn_rate",
)

OPTIONAL_COLUMNS: tuple[str, ...] = (
    "days_since_launch",
    "actual_dau",
    "actual_nps",
    "notes",
    "client_request_id",
    "simulation_id",
)

READ_ONLY_COLUMNS: frozenset[str] = frozenset({
    "id",
    "project_id",
    "created_at",
    "predicted_conversion_rate",
    "predicted_mrr",
    "predicted_revenue",
    "variance_conversion",
    "variance_mrr",
    "variance_cac",
    "variance_churn",
    "calibration_score",
})

# Columns that accept spreadsheet percentages ("5%" -> 0.05).
RATE_COLUMNS: frozenset[str] = frozenset({
    "actual_conversion_rate",
    "actual_churn_rate",
})

FLOAT_COLUMNS: frozenset[str] = frozenset({
    "actual_mrr",
    "actual_cac",
    "actual_dau",
    "actual_nps",
})

INT_COLUMNS: frozenset[str] = frozenset({
    "days_since_launch",
    "simulation_id",
})

# Matches ``OutcomeBatchCreate``'s 100-row cap so the parser's row-count
# error is raised before the schema's, with a spreadsheet-friendly message.
MAX_ROWS: int = 100


@dataclass(frozen=True)
class CsvRowError:
    """One import problem tied to a specific spreadsheet row/column."""

    row: int
    column: str | None
    error: str


@dataclass(frozen=True)
class CsvParseResult:
    """Outcome of parsing a CSV file.

    ``items`` holds only rows that parsed cleanly (no per-cell errors).
    ``errors`` may reference more rows than ``items``; callers must treat
    any non-empty ``errors`` as a failed import and write nothing.
    """

    items: list[dict[str, Any]]
    errors: list[CsvRowError]
    data_row_count: int


def _normalise_column(cell: str) -> str:
    """Normalise a header cell for matching (case/whitespace tolerant)."""
    return cell.strip().removeprefix("\ufeff").strip().lower()


def _parse_rate(cell: str) -> tuple[float | None, str | None]:
    """Parse a rate cell as a ``[0, 1]`` fraction.

    Accepts plain fractions (``0.05``) and spreadsheet percentages
    (``5%`` / ``12.5%``). Bare whole numbers above 1.0 are rejected with a
    hint rather than left to Pydantic's generic range error, because
    ``5`` almost always means 5% in a spreadsheet.
    """
    token = cell
    if token.endswith("%"):
        token = token[:-1].strip()
        try:
            value = float(token) / 100.0
        except (TypeError, ValueError):
            return None, f"invalid percentage {cell!r} — expected e.g. 5% or 0.05"
    else:
        try:
            value = float(token)
        except (TypeError, ValueError):
            return None, f"invalid number {cell!r}"
    if not math.isfinite(value):
        return None, f"invalid number {cell!r}"
    if not 0.0 <= value <= 1.0:
        return None, (
            f"value {cell!r} must be a fraction in [0, 1] — "
            "use 0.05 or 5%, not 5"
        )
    return value, None


def _parse_float(cell: str) -> tuple[float | None, str | None]:
    """Parse a plain numeric cell to a finite float."""
    try:
        value = float(cell)
    except (TypeError, ValueError):
        return None, f"invalid number {cell!r}"
    if not math.isfinite(value):
        return None, f"invalid number {cell!r}"
    return value, None


def _parse_int(cell: str) -> tuple[int | None, str | None]:
    """Parse an integer cell (spreadsheets may quote integers as text)."""
    try:
        return int(cell), None
    except (TypeError, ValueError):
        return None, f"invalid integer {cell!r}"


def _is_blank_row(row: list[str]) -> bool:
    return not any(cell.strip() for cell in row)


def parse_outcomes_csv(text: str) -> CsvParseResult:
    """Parse a founder-supplied outcomes CSV into batch rows + errors.

    Args:
        text: UTF-8 decoded CSV content (BOM may be present; ``csv``
            handles quoted fields, CRLF, and commas in values).

    Returns:
        :class:`CsvParseResult` with rows that parsed cleanly and every
        problem found. Row numbers are 1-based and match spreadsheet row
        numbers (header = row 1, first data row = row 2).
    """
    reader = csv.reader(io.StringIO(text))
    rows = [list(row) for row in reader]

    header_index: int | None = None
    for index, row in enumerate(rows):
        if not _is_blank_row(row):
            header_index = index
            break
    if header_index is None:
        return CsvParseResult(
            items=[],
            errors=[
                CsvRowError(
                    row=1,
                    column=None,
                    error="CSV is empty — a header row is required",
                )
            ],
            data_row_count=0,
        )

    raw_header = rows[header_index]
    errors: list[CsvRowError] = []

    canonical_by_name: dict[str, str] = {
        column: column for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)
    }
    normalized_columns: list[str] = []
    seen_names: dict[str, int] = {}
    for cell in raw_header:
        norm = _normalise_column(cell)
        if not norm:
            errors.append(
                CsvRowError(
                    row=header_index + 1,
                    column=None,
                    error="header contains an empty column name",
                )
            )
            continue
        if norm in READ_ONLY_COLUMNS:
            errors.append(
                CsvRowError(
                    row=header_index + 1,
                    column=norm,
                    error=(
                        f"column {norm!r} is read-only output — remove it "
                        "before importing"
                    ),
                )
            )
        elif norm not in canonical_by_name:
            errors.append(
                CsvRowError(
                    row=header_index + 1,
                    column=norm,
                    error=f"unknown column {norm!r}",
                )
            )
        seen_names[norm] = seen_names.get(norm, 0) + 1
        normalized_columns.append(norm)

    for norm, count in seen_names.items():
        if count > 1:
            errors.append(
                CsvRowError(
                    row=header_index + 1,
                    column=norm,
                    error=f"duplicate column {norm!r}",
                )
            )

    for column in REQUIRED_COLUMNS:
        if column not in seen_names:
            errors.append(
                CsvRowError(
                    row=header_index + 1,
                    column=column,
                    error=f"missing required column {column!r}",
                )
            )

    data_rows = rows[header_index + 1:]
    data_row_count = sum(1 for row in data_rows if not _is_blank_row(row))

    if errors:
        # Header problems make row-to-column mapping ambiguous; report the
        # header errors and stop so the caller writes nothing.
        return CsvParseResult(items=[], errors=errors, data_row_count=data_row_count)

    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    scanned_rows = 0

    for row_index, row in enumerate(data_rows, start=header_index + 2):
        if _is_blank_row(row):
            continue
        scanned_rows += 1
        if scanned_rows > MAX_ROWS:
            errors.append(
                CsvRowError(
                    row=row_index,
                    column=None,
                    error=(
                        f"row count exceeds {MAX_ROWS} — split the file "
                        "into smaller batches"
                    ),
                )
            )
            continue

        # Trailing empty cells are common in spreadsheets; treat them as
        # absent rather than "too many columns".
        trimmed = list(row)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        if len(trimmed) > len(normalized_columns):
            errors.append(
                CsvRowError(
                    row=row_index,
                    column=None,
                    error=(
                        f"row has {len(trimmed)} columns but the header has "
                        f"{len(normalized_columns)}"
                    ),
                )
            )
            continue

        record: dict[str, Any] = {}
        row_has_error = False
        for col_index, norm in enumerate(normalized_columns):
            cell = trimmed[col_index].strip() if col_index < len(trimmed) else ""
            canonical = canonical_by_name[norm]
            if not cell:
                if canonical in REQUIRED_COLUMNS:
                    errors.append(
                        CsvRowError(
                            row=row_index,
                            column=canonical,
                            error=(
                                f"missing required value for "
                                f"{canonical!r}"
                            ),
                        )
                    )
                    row_has_error = True
                continue

            if canonical in RATE_COLUMNS:
                value, parse_error = _parse_rate(cell)
            elif canonical in FLOAT_COLUMNS:
                value, parse_error = _parse_float(cell)
            elif canonical in INT_COLUMNS:
                value, parse_error = _parse_int(cell)
            else:
                value, parse_error = cell, None

            if parse_error is not None:
                errors.append(
                    CsvRowError(
                        row=row_index,
                        column=canonical,
                        error=parse_error,
                    )
                )
                row_has_error = True
            else:
                record[canonical] = value

        if row_has_error:
            continue

        key = record.get("client_request_id")
        if key is not None:
            if key in seen_keys:
                errors.append(
                    CsvRowError(
                        row=row_index,
                        column="client_request_id",
                        error=f"duplicate client_request_id {key!r} in file",
                    )
                )
                continue
            seen_keys.add(key)

        items.append(record)

    return CsvParseResult(
        items=items,
        errors=errors,
        data_row_count=data_row_count,
    )


__all__ = [
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "READ_ONLY_COLUMNS",
    "MAX_ROWS",
    "CsvRowError",
    "CsvParseResult",
    "parse_outcomes_csv",
]
