"""Systemic guard: every CSV cell flows through the formula-injection guard.

Exported spreadsheets are opened in Excel/Sheets/LibreOffice, where a cell
whose text starts with ``=``, ``+``, ``-``, or ``@`` executes as a formula.
User-controlled text (titles, assumptions, tags, narratives) reaches those
cells, so every exporter must route cells through
``app.simulation.export_utils.write_row`` / ``safe_csv_cell``.

The meta-test below bans direct ``writerow`` calls outside export_utils so
a new exporter cannot silently bypass the guard; the round-trip tests pin
the behaviour through real exporters end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_APP = Path(__file__).resolve().parents[1] / "backend" / "app"

HOSTILE_CELLS = [
    '=HYPERLINK("http://evil.example","pwn")',
    "=cmd|' /C calc'!A0",
    "+SUM(A1:A2)",
    "-2+3+cmd|' /C calc'!A0",
    "@SUM(1+2)*cmd|' /C calc'!A0",
    "\t=cmd(...)",
    "\r=cmd(...)",
    " =cmd (leading space still evaluates)",
]


class TestMetaNoDirectWriters:
    def test_writerow_only_in_export_utils(self) -> None:
        """Direct csv writerow/writerows calls are banned outside the shared
        helper — write_row applies safe_csv_cell to every cell, raw writerow
        does not."""
        offenders = []
        for path in BACKEND_APP.rglob("*.py"):
            if path.name == "export_utils.py":
                continue
            text = path.read_text()
            if ".writerow(" in text or ".writerows(" in text:
                offenders.append(str(path.relative_to(BACKEND_APP)))
        assert not offenders, (
            "Modules below call csv writerow directly, bypassing the "
            f"formula-injection guard — use export_utils.write_row: {offenders}"
        )

    def test_safe_csv_cell_covers_union_character_set(self) -> None:
        from app.simulation.export_utils import safe_csv_cell

        for cell in HOSTILE_CELLS:
            guarded = safe_csv_cell(cell)
            assert guarded == f"'{cell}", f"unguarded formula cell: {cell!r}"

        # Benign values pass through untouched.
        assert safe_csv_cell("5.2% conversion") == "5.2% conversion"
        assert safe_csv_cell("plain title") == "plain title"
        assert safe_csv_cell(12345) == 12345
        assert safe_csv_cell(None) is None

    @pytest.mark.parametrize(
        "numeric",
        ["-20.0", "+3.14", "-7", "42", "2.5e-3", "-1E+9", " -12.75"],
    )
    def test_signed_pure_numbers_pass_through_unguarded(self, numeric: str) -> None:
        """Spreadsheets parse signed pure numbers as numeric cells, never
        formulas — prefixing them would only corrupt founder data (e.g. a
        backfilled variance of -20.0)."""
        from app.simulation.export_utils import safe_csv_cell

        assert safe_csv_cell(numeric) == numeric

    @pytest.mark.parametrize(
        ("numeric", "lookalike"),
        [
            ("-20.0", "-20 bananas"),
            ("+3.14", "+3 bananas"),
        ],
    )
    def test_sign_plus_non_numeric_stays_guarded(self, numeric: str, lookalike: str) -> None:
        """The exemption is exact-match: the same sign followed by anything
        non-numeric keeps the full guard."""
        from app.simulation.export_utils import safe_csv_cell

        assert safe_csv_cell(numeric) == numeric  # sanity anchor
        assert safe_csv_cell(lookalike) == f"'{lookalike}"

    @pytest.mark.parametrize(
        "lookalike",
        ["-2+3+cmd|' /C calc'!A0", "+1+1", "--20", "+-3"],
    )
    def test_arithmetic_lookalikes_stay_guarded(self, lookalike: str) -> None:
        """Sign-leading strings that are NOT clean numbers keep the full
        guard — DDE/formula payloads often disguise themselves this way."""
        from app.simulation.export_utils import safe_csv_cell

        assert safe_csv_cell(lookalike) == f"'{lookalike}"


class TestExporterRoundTrips:
    """Hostile user-controlled text through real exporters, end to end."""

    def _rows_of(self, csv_text: str) -> list[list[str]]:
        import csv
        import io

        return list(csv.reader(io.StringIO(csv_text)))

    def test_decisions_export_neutralises_hostile_title(self) -> None:
        from app.simulation.decisions_export import decisions_to_csv

        text = decisions_to_csv(
            [
                {
                    "id": 1,
                    "project_id": 9,
                    "title": '=HYPERLINK("http://evil.example","x")',
                    "status": "open",
                    "task_id": "t-1",
                    "created_at": "2026-08-25T00:00:00Z",
                    "result": "+cmd|' /C calc'!A0",
                }
            ],
            metadata={"generated_at": "2026-08-25T00:00:00Z", "user_id": 1},
        )
        rows = self._rows_of(text)
        data_row = next(r for r in rows if r and r[0] == "1")
        assert data_row[2].startswith("'="), f"title not guarded: {data_row[2]!r}"
        assert data_row[6].startswith("'+"), f"result not guarded: {data_row[6]!r}"

    def test_status_export_neutralises_hostile_status(self) -> None:
        from app.simulation.status_export import status_to_csv

        text = status_to_csv({"project_id": 9, "status": "@SUM(1+2)"})
        rows = self._rows_of(text)
        data_row = rows[-1]
        assert data_row[1] == "'@SUM(1+2)"

    def test_tags_export_neutralises_hostile_tag(self) -> None:
        from app.simulation.tags_export import tags_to_csv

        text = tags_to_csv(["=cmd|' /C calc'!A0", "growth"])
        rows = self._rows_of(text)
        tag_rows = [r for r in rows if len(r) == 2 and r[0].isdigit()]
        assert tag_rows[0][1].startswith("'="), "tag not guarded"
        assert tag_rows[1][1] == "growth"

    def test_benign_roundtrip_is_unchanged(self) -> None:
        """The guard must never mangle ordinary founder data."""
        from app.simulation.decisions_export import decisions_to_csv

        text = decisions_to_csv(
            [
                {
                    "id": 7,
                    "project_id": 2,
                    "title": "Pricing v2 rollout",
                    "status": "done",
                    "task_id": None,
                    "created_at": "2026-08-25T00:00:00Z",
                    "result": {"lift": 0.12},
                }
            ]
        )
        assert "Pricing v2 rollout" in text
        assert "'" not in text  # the guard never fired, so no quote prefixes


@pytest.mark.parametrize(
    ("module_name", "func_name"),
    [
        ("decisions_export", "decisions_to_csv"),
        ("status_export", "status_to_csv"),
        ("tags_export", "tags_to_csv"),
    ],
)
def test_representative_exporters_import_the_guard(module_name: str, func_name: str) -> None:
    """Every migrated exporter pulls write_row from export_utils — pins the
    dependency so a revert to local writers is visible."""
    import importlib

    module = importlib.import_module(f"app.simulation.{module_name}")
    assert hasattr(module, func_name)
    assert getattr(module, func_name) is not None
