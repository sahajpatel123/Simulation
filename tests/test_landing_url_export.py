"""Tests for the pure landing-page-URL export helper."""
from __future__ import annotations

import csv
import io

import pytest

from app.simulation.landing_url_export import landing_url_to_csv


def test_landing_url_to_csv_contains_header_and_row() -> None:
    csv_text = landing_url_to_csv(
        {"project_id": 10, "landing_page_url": "https://example.com"},
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "project_id,landing_page_url" in csv_text
    assert "10,https://example.com" in csv_text
    assert "generated_at,now" in csv_text


@pytest.mark.parametrize(
    "malicious",
    [
        '=HYPERLINK("http://evil.example")',
        "+cmd()",
        "-cmd()",
        "@cmd",
        "\t=cmd()",
        "\r=cmd()",
    ],
)
def test_landing_url_to_csv_neutralizes_formula_injection(malicious: str) -> None:
    csv_text = landing_url_to_csv(
        {"project_id": 10, "landing_page_url": malicious},
        metadata={"generated_at": "now", "user_id": 42},
    )

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[-1][1] == f"'{malicious}"
