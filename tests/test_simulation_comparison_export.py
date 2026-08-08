"""Tests for the simulation-comparison export serializers and route."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
import types
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.comparison import build_simulation_comparison
from app.simulation.simulation_comparison_export import (
    simulation_comparison_to_csv,
    simulation_comparison_to_json,
    simulation_comparison_to_markdown,
)


def _row(
    sim_id: int,
    *,
    cr: float,
    project_id: int = 7,
    status: str = "COMPLETED",
    clusters: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    revenue: float | None = None,
    signal: float | None = 0.7,
    product_type: str = "saas",
    domain: str = "PricingArchitect",
) -> dict[str, Any]:
    return {
        "id": sim_id,
        "project_id": project_id,
        "status": status,
        "signal_quality": signal,
        "created_at": f"2026-07-2{sim_id}T00:00:00+00:00",
        "results_json": {
            "population_weighted_conversion": cr,
            "conversion_rate": cr,
            "revenue_projection": revenue,
            "cluster_breakdown": clusters
            or {
                "metro_power_professional": cr + 0.02,
                "tier2_price_sensitive_pragmatist": max(0.0, cr - 0.01),
            },
            "domain_findings": findings or [],
            "primary_failure_domain": domain,
            "product_type_detected": product_type,
        },
    }


def _comparison() -> Any:
    finding = {
        "architect_name": "PricingArchitect",
        "severity": "CRITICAL",
        "finding": "price too high",
    }
    return build_simulation_comparison(
        [
            _row(
                1,
                cr=0.03,
                revenue=3000,
                findings=[finding],
            ),
            _row(2, cr=0.08, revenue=8000, findings=[dict(finding)]),
        ],
        cluster_registry={
            "metro_power_professional": {
                "name": "Metro Pros",
                "population_weight": 0.4,
            },
            "tier2_price_sensitive_pragmatist": {
                "name": "Tier-2 Pragmatists",
                "population_weight": 0.6,
            },
        },
    )


_METADATA = {
    "generated_at": "2026-08-08T00:00:00Z",
    "user_id": 42,
    "format_version": "1",
    "project_id": 7,
    "comparison_id": "abc123",
}


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_has_summary_refs_cluster_and_domain_sections() -> None:
    csv_text = simulation_comparison_to_csv(_comparison(), metadata=_METADATA)
    rows = _rows(csv_text)
    flat = csv_text

    assert "section,Simulation Comparison Summary" in flat
    assert "best_simulation_id,2 (B)" in flat
    assert "worst_simulation_id,1 (A)" in flat
    assert "section,Simulations Compared" in flat
    assert "A,1,COMPLETED,0.03" in flat
    assert "B,2,COMPLETED,0.08" in flat
    assert "section,Cluster Conversion Comparison" in flat
    assert "conversion_1,conversion_2,delta_from_best_1,delta_from_best_2" in flat
    assert "section,Domain Finding Comparison" in flat
    assert "PricingArchitect" in flat
    assert "price too high" in flat

    headers = rows[0]
    assert headers[0] == "generated_at"
    assert "abc123" in flat


def test_csv_cluster_rows_include_conversions_and_deltas() -> None:
    csv_text = simulation_comparison_to_csv(_comparison(), metadata=_METADATA)
    cluster_lines = [
        row
        for row in _rows(csv_text)
        if row and row[0] in {"metro_power_professional", "tier2_price_sensitive_pragmatist"}
    ]
    assert len(cluster_lines) == 2
    metro = next(
        row
        for row in cluster_lines
        if row[0] == "metro_power_professional"
    )
    # cluster_id, name, weight, best_sim, winner, conv1, conv2, delta1, delta2
    assert metro[1] == "Metro Pros"
    assert metro[2] == "0.4"
    assert metro[3] == "2"
    assert metro[4] == "B"
    assert metro[5] == "0.05"
    assert metro[6] == "0.1"
    assert metro[7] == "-0.05"
    assert metro[8] == "0.0"


def test_csv_neutralises_formula_injection_in_finding_text() -> None:
    finding = {
        "architect_name": "TrustArchitect",
        "severity": "WARNING",
        "finding": "=HYPERLINK(https://example.com)",
    }
    out = build_simulation_comparison(
        [
            _row(1, cr=0.03, findings=[finding]),
            _row(2, cr=0.04, findings=[]),
        ]
    )
    csv_text = simulation_comparison_to_csv(out)
    assert "'A:=HYPERLINK(https://example.com)" in csv_text
    # The raw formula should never survive as a cell that starts with '='.
    assert not any(
        row and row[0].startswith("=")
        for row in _rows(csv_text)
    )


def test_csv_empty_payload_still_renders_sections() -> None:
    csv_text = simulation_comparison_to_csv({})
    assert "section,Simulation Comparison Summary" in csv_text
    assert "section,Simulations Compared" in csv_text
    assert "section,Cluster Conversion Comparison" in csv_text
    assert "section,Domain Finding Comparison" in csv_text


def test_csv_and_markdown_handle_json_style_string_keyed_maps() -> None:
    # A JSON-serialized comparison (e.g. a cached endpoint response) uses
    # string keys for dict[int, ...] fields; the serializers should render
    # the same output as the in-memory Pydantic payload.
    payload = json.loads(
        simulation_comparison_to_json(_comparison(), metadata=_METADATA)
    )["simulation_comparison"]

    csv_text = simulation_comparison_to_csv(payload, metadata=_METADATA)
    cluster_lines = [
        row
        for row in _rows(csv_text)
        if row and row[0] == "metro_power_professional"
    ]
    assert len(cluster_lines) == 1
    metro = cluster_lines[0]
    # cluster_id, name, weight, best_sim, winner, conv1, conv2, delta1, delta2
    assert metro[5] == "0.05"
    assert metro[6] == "0.1"
    assert metro[7] == "-0.05"
    assert metro[8] == "0.0"
    assert "A:CRITICAL" in csv_text
    assert "price too high" in csv_text

    md = simulation_comparison_to_markdown(payload, metadata=_METADATA)
    assert "Metro Pros" in md
    assert "A: CRITICAL" in md
    assert "price too high" in md


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_envelope_includes_metadata_and_comparison() -> None:
    text = simulation_comparison_to_json(_comparison(), metadata=_METADATA)
    parsed = json.loads(text)
    assert parsed["metadata"]["comparison_id"] == "abc123"
    assert parsed["metadata"]["project_id"] == 7
    comp = parsed["simulation_comparison"]
    assert comp["summary"]["verdict"] == "CLEAR_WINNER"
    assert comp["summary"]["best_simulation_id"] == 2
    assert len(comp["simulations"]) == 2
    assert comp["cluster_comparison"][0]["cluster_name"] == "Tier-2 Pragmatists"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_brief_has_verdict_tables_and_domains() -> None:
    md = simulation_comparison_to_markdown(_comparison(), metadata=_METADATA)
    assert md.startswith("# Simulation Comparison")
    assert "## Verdict" in md
    assert "CLEAR_WINNER" in md
    assert "winner B (simulation 2)" in md
    assert "## Simulations Compared" in md
    assert "| Label | Simulation | Conversion | Revenue | Signal | Product type | Status |" in md
    assert "| A | 1 | 3.0% | $3,000 | 0.70 | saas | COMPLETED |" in md
    assert "## Cluster Conversion Comparison" in md
    assert "Metro Pros" in md
    assert "## Domain Findings" in md
    assert "PricingArchitect" in md
    assert "price too high" in md


def test_markdown_handles_empty_payload() -> None:
    md = simulation_comparison_to_markdown({})
    assert md.startswith("# Simulation Comparison")
    assert "No per-cluster conversion data is available." in md
    assert "No domain-finding comparison is available." in md


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int,
        *,
        status: str = "COMPLETED",
        project_id: int = 7,
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.status = status
        self.signal_quality = 0.7
        self.created_at = datetime.now(timezone.utc)
        self.results_json = {
            "population_weighted_conversion": 0.03 if sim_id == 1 else 0.08,
            "conversion_rate": 0.03 if sim_id == 1 else 0.08,
            "cluster_breakdown": {
                "metro_power_professional": 0.05 if sim_id == 1 else 0.10,
                "tier2_price_sensitive_pragmatist": 0.02 if sim_id == 1 else 0.06,
            },
            "domain_findings": [
                {
                    "architect_name": "PricingArchitect",
                    "severity": "CRITICAL",
                    "finding": "price too high",
                }
            ],
            "product_type_detected": "saas",
        }


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def join(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def filter(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def all(self) -> list[Any]:
        return self.items


class _FakeSession:
    def __init__(self, sims: list[_FakeSimulation]) -> None:
        self.sims = sims

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        if getattr(model, "__name__", "") == "Simulation":
            return _FakeQuery(self.sims)
        return _FakeQuery([])


def _call_route(
    *,
    simulation_ids: str = "1,2",
    format: str = "csv",
    session: _FakeSession | None = None,
) -> Any:
    from app.api.v1 import simulations as sim_mod

    return sim_mod.export_simulation_comparison(
        simulation_ids=simulation_ids,
        format=format,
        db=session or _FakeSession([_FakeSimulation(1), _FakeSimulation(2)]),
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp: Any) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp: Any) -> bytes:
    return asyncio.run(_collect(resp))


def test_route_returns_multi_section_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="simulation-comparison.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "Simulation Comparison Summary" in body
    assert "Cluster Conversion Comparison" in body
    assert "Domain Finding Comparison" in body
    assert "PricingArchitect" in body


def test_route_json_returns_comparison_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    parsed = json.loads(body)
    assert parsed["metadata"]["project_id"] == 7
    assert parsed["simulation_comparison"]["summary"]["best_simulation_id"] == 2


def test_route_markdown_returns_brief() -> None:
    resp = _call_route(format="md")

    assert resp.media_type == "text/markdown; charset=utf-8"
    assert 'filename="simulation-comparison.md"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert body.startswith("# Simulation Comparison")
    assert "## Verdict" in body
    assert "## Cluster Conversion Comparison" in body


def test_route_rejects_unsupported_format() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(format="pdf")
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail


def test_route_rejects_too_few_or_many_ids() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1")
    assert exc.value.status_code == 400
    assert "between 2 and 5" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1,2,3,4,5,6")
    assert exc.value.status_code == 400


def test_route_rejects_duplicate_or_nonpositive_ids() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1,1")
    assert exc.value.status_code == 400
    assert "unique" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="0,1")
    assert exc.value.status_code == 400
    assert "positive" in exc.value.detail


def test_route_rejects_non_integer_ids() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1,abc")
    assert exc.value.status_code == 400
    assert "comma-separated integers" in exc.value.detail


def test_route_raises_404_when_sim_missing() -> None:
    session = _FakeSession([_FakeSimulation(1)])
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1,2", session=session)
    assert exc.value.status_code == 404
    assert "not found or not owned" in exc.value.detail


def test_route_raises_409_when_incomplete() -> None:
    session = _FakeSession(
        [
            _FakeSimulation(1),
            _FakeSimulation(2, status="RUNNING"),
        ]
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_ids="1,2", session=session)
    assert exc.value.status_code == 409
    assert "COMPLETED" in exc.value.detail
