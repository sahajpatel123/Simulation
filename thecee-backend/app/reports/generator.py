from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# TheCee brand palette
INK = colors.HexColor("#1a1714")
RED = colors.HexColor("#c0392b")
MUTED = colors.HexColor("#6b6460")
BORDER = colors.HexColor("#d4cfc8")
WHITE = colors.white
CREAM = colors.HexColor("#faf8f4")
CRITICAL_BG = colors.HexColor("#fce8e6")
HIGH_BG = colors.HexColor("#fef3e2")
MEDIUM_BG = colors.HexColor("#f0f9ee")
HEADER_BG = colors.HexColor("#1a1714")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()

    def s(name: str, **kwargs: Any) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base["Normal"], **kwargs)

    return {
        "cover_title": s(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=28,
            textColor=INK,
            leading=34,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "cover_sub": s(
            "cover_sub",
            fontName="Helvetica",
            fontSize=13,
            textColor=MUTED,
            leading=18,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "cover_meta": s(
            "cover_meta",
            fontName="Helvetica",
            fontSize=9,
            textColor=MUTED,
            leading=13,
            alignment=TA_LEFT,
        ),
        "section_heading": s(
            "section_heading",
            fontName="Helvetica-Bold",
            fontSize=14,
            textColor=INK,
            leading=18,
            spaceBefore=14,
            spaceAfter=8,
        ),
        "sub_heading": s(
            "sub_heading",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=INK,
            leading=15,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": s(
            "body",
            fontName="Helvetica",
            fontSize=9,
            textColor=INK,
            leading=14,
            spaceAfter=4,
        ),
        "body_muted": s(
            "body_muted",
            fontName="Helvetica",
            fontSize=9,
            textColor=MUTED,
            leading=13,
            spaceAfter=3,
        ),
        "stat_value": s(
            "stat_value",
            fontName="Helvetica-Bold",
            fontSize=22,
            textColor=RED,
            leading=26,
            alignment=TA_CENTER,
        ),
        "stat_label": s(
            "stat_label",
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            leading=11,
            alignment=TA_CENTER,
        ),
        "tag_critical": s("tag_critical", fontName="Helvetica-Bold", fontSize=8, textColor=RED, leading=11),
        "tag_high": s(
            "tag_high",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#b45309"),
            leading=11,
        ),
        "tag_medium": s(
            "tag_medium",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#166534"),
            leading=11,
        ),
        "table_header": s(
            "table_header",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=WHITE,
            leading=11,
            alignment=TA_CENTER,
        ),
        "table_cell": s(
            "table_cell",
            fontName="Helvetica",
            fontSize=8,
            textColor=INK,
            leading=12,
            alignment=TA_LEFT,
        ),
        "table_cell_c": s(
            "table_cell_c",
            fontName="Helvetica",
            fontSize=8,
            textColor=INK,
            leading=12,
            alignment=TA_CENTER,
        ),
    }


def _make_page_template(doc: BaseDocTemplate) -> PageTemplate:
    def on_page(canvas, doc_obj):  # noqa: ANN001
        canvas.saveState()

        canvas.setFillColor(INK)
        canvas.rect(0, PAGE_H - 10 * mm, PAGE_W, 10 * mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, PAGE_H - 6.5 * mm, "TheCee")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#8a8480"))
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 6.5 * mm, "Simulation Intelligence Platform")

        canvas.setFillColor(BORDER)
        canvas.rect(MARGIN, 10 * mm, CONTENT_W, 0.3, fill=1, stroke=0)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            MARGIN,
            7 * mm,
            "Generated by TheCee. Predictions are synthetic-model outputs; validate with real market testing.",
        )
        canvas.drawRightString(PAGE_W - MARGIN, 7 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    frame = Frame(MARGIN, 14 * mm, CONTENT_W, PAGE_H - 26 * mm, id="main")
    return PageTemplate(id="standard", frames=[frame], onPage=on_page)


def _divider() -> list[Any]:
    return [Spacer(1, 4), HRFlowable(width=CONTENT_W, thickness=0.5, color=BORDER), Spacer(1, 8)]


def _cover_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = [Spacer(1, 24), HRFlowable(width=40, thickness=3, color=RED, spaceAfter=12)]

    title = data.get("title") or "Untitled Project"
    story.append(Paragraph(title, st["cover_title"]))
    story.append(Paragraph("Simulation Intelligence Report", st["cover_sub"]))
    generated = datetime.now(timezone.utc).strftime("%B %d, %Y")
    story.append(Paragraph(f"Generated · {generated}", st["cover_meta"]))

    desc = str(data.get("description") or "")[:300]
    if desc:
        story += [Spacer(1, 14), Paragraph(desc, st["body_muted"])]

    sim = data.get("simulation") or {}
    conv = sim.get("mean_conversion_rate") or sim.get("conversion_rate") or 0.0
    rev = sim.get("mean_revenue") or sim.get("revenue_projection") or 0.0
    conf = sim.get("confidence_score") or 0
    total = sim.get("total_agents") or 0

    story.append(Spacer(1, 20))
    cells = [
        [
            Paragraph(f"{float(conv) * 100:.1f}%", st["stat_value"]),
            Paragraph(f"₹{float(rev):,.0f}", st["stat_value"]),
            Paragraph(f"{int(conf)}/100", st["stat_value"]),
            Paragraph(f"{int(total):,}", st["stat_value"]),
        ],
        [
            Paragraph("Conversion rate", st["stat_label"]),
            Paragraph("Projected revenue", st["stat_label"]),
            Paragraph("Confidence score", st["stat_label"]),
            Paragraph("Agents simulated", st["stat_label"]),
        ],
    ]
    table = Table(cells, colWidths=[CONTENT_W / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CREAM),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story += [table, PageBreak()]
    return story


def _executive_summary(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = [Paragraph("Executive Summary", st["section_heading"])]
    story += _divider()

    sim = data.get("simulation") or {}
    conv = float(sim.get("mean_conversion_rate") or sim.get("conversion_rate") or 0.0)
    rev = float(sim.get("mean_revenue") or sim.get("revenue_projection") or 0.0)
    ci_lo = float((sim.get("ci_95") or {}).get("low") or sim.get("ci_low") or 0.0)
    ci_hi = float((sim.get("ci_95") or {}).get("high") or sim.get("ci_high") or 0.0)
    worst = sim.get("worst_drop_off_stage") or "N/A"
    opt_p = float(sim.get("optimal_price") or 0.0)
    runs = int(sim.get("total_runs") or 1)

    lines = [
        f"TheCee ran <b>{int(sim.get('total_agents', 0)):,} synthetic consumers</b> across <b>{runs} run(s)</b>.",
        f"Predicted conversion: <b>{conv*100:.1f}%</b> with 95% CI [{ci_lo*100:.1f}%, {ci_hi*100:.1f}%].",
        f"Projected cohort revenue: <b>₹{rev:,.0f}</b>.",
        f"Highest drop-off stage: <b>{worst}</b>.",
    ]
    if opt_p > 0:
        lines.append(f"Optimal modelled price point: <b>₹{opt_p:,.0f}</b>.")

    for line in lines:
        story += [Paragraph(line, st["body"]), Spacer(1, 3)]
    return story


def _assumptions_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    assumptions = data.get("assumptions") or []
    if not assumptions:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Key Assumptions", st["section_heading"])]
    story += _divider()

    rows: list[list[Paragraph]] = [
        [Paragraph("Assumption", st["table_header"]), Paragraph("Sensitivity", st["table_header"]), Paragraph("Impact", st["table_header"])]
    ]
    for a in assumptions[:8]:
        rows.append(
            [
                Paragraph(str(a.get("text", ""))[:120], st["table_cell"]),
                Paragraph(str(a.get("sensitivity", "MEDIUM")).upper(), st["table_cell_c"]),
                Paragraph(f"{float(a.get('impact_score') or 5.0):.1f}/10", st["table_cell_c"]),
            ]
        )

    table = Table(rows, colWidths=[CONTENT_W * 0.65, CONTENT_W * 0.18, CONTENT_W * 0.17])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    return story


def _funnel_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    sim = data.get("simulation") or {}
    stages = sim.get("stage_aggregations") or sim.get("stage_metrics") or []
    if not stages:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Customer Funnel Analysis", st["section_heading"])]
    story += _divider()
    rows = [[Paragraph("Stage", st["table_header"]), Paragraph("Entry rate", st["table_header"]), Paragraph("Drop-off", st["table_header"]), Paragraph("Avg time", st["table_header"])]]
    for stage in stages:
        entry = float(stage.get("mean_entry_rate") or stage.get("entry_rate") or 0.0)
        dropoff = float(stage.get("mean_drop_off_rate") or stage.get("drop_off_rate") or 0.0)
        time_s = float(stage.get("mean_time_seconds") or stage.get("avg_time_seconds") or 0.0)
        rows.append(
            [
                Paragraph(str(stage.get("state", "")), st["table_cell"]),
                Paragraph(f"{entry*100:.1f}%", st["table_cell_c"]),
                Paragraph(f"{dropoff*100:.1f}%", st["table_cell_c"]),
                Paragraph(f"{time_s:.0f}s", st["table_cell_c"]),
            ]
        )

    table = Table(rows, colWidths=[CONTENT_W * 0.35, CONTENT_W * 0.22, CONTENT_W * 0.22, CONTENT_W * 0.21])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    return story


def _premortem_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    premortem = data.get("premortem") or {}
    modes = premortem.get("failure_modes") or []
    if not modes:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Pre-Mortem: Failure Mode Analysis", st["section_heading"])]
    story += _divider()
    sev_bg = {"CRITICAL": CRITICAL_BG, "HIGH": HIGH_BG, "MEDIUM": MEDIUM_BG}

    for i, mode in enumerate(modes[:6]):
        sev = str(mode.get("severity", "MEDIUM")).upper()
        prob = float(mode.get("probability", 0.0))
        title = str(mode.get("title") or mode.get("failure_mode") or "")[:100]
        desc = str(mode.get("trigger_condition") or "")[:200]
        intervention = str(mode.get("intervention") or mode.get("recommended_intervention") or "")[:160]

        row_data = [
            [
                Paragraph(f"{i+1}. {title}", st["sub_heading"]),
                Paragraph(
                    f"P={prob:.0%} · {sev}",
                    st["tag_critical"] if sev == "CRITICAL" else st["tag_high"] if sev == "HIGH" else st["tag_medium"],
                ),
            ]
        ]
        table = Table(row_data, colWidths=[CONTENT_W * 0.78, CONTENT_W * 0.22])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), sev_bg.get(sev, CREAM)),
                    ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (0, -1), 8),
                ]
            )
        )
        story.append(table)
        if desc:
            story.append(Paragraph(desc, st["body_muted"]))
        if intervention:
            story.append(Paragraph(f"→ Intervention: {intervention}", st["body"]))
        story.append(Spacer(1, 5))
    return story


def _stress_test_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    stress = data.get("stress_test") or {}
    matrix = stress.get("sensitivity_matrix") or []
    if not matrix:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Assumption Stress Test", st["section_heading"])]
    story += _divider()

    risk = stress.get("overall_risk_level", "UNKNOWN")
    baseline = float(stress.get("baseline_conversion") or 0.0)
    tested = int(stress.get("assumptions_tested") or 0)
    story.append(
        Paragraph(
            f"Overall risk level: <b>{risk}</b> · Baseline conversion: <b>{baseline*100:.1f}%</b> · Assumptions tested: <b>{tested}</b>",
            st["body"],
        )
    )

    rows = [[Paragraph("Assumption", st["table_header"]), Paragraph("Δ Conversion", st["table_header"]), Paragraph("Kill Shot", st["table_header"])]]
    for row in matrix[:6]:
        rows.append(
            [
                Paragraph(str(row.get("assumption_text", ""))[:90], st["table_cell"]),
                Paragraph(f"{float(row.get('delta', 0.0))*100:+.1f}%", st["table_cell_c"]),
                Paragraph("YES" if bool(row.get("kill_shot")) else "NO", st["table_cell_c"]),
            ]
        )

    table = Table(rows, colWidths=[CONTENT_W * 0.70, CONTENT_W * 0.15, CONTENT_W * 0.15])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    return story


def _interventions_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    iv_data = data.get("interventions") or {}
    items = iv_data.get("interventions") or []
    if not items:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Recommended Interventions", st["section_heading"])]
    story += _divider()

    quick_wins = [i for i in items if i.get("difficulty") == "LOW" and float(i.get("priority_score", 0)) > 0.70]
    if quick_wins:
        story.append(Paragraph("Quick Wins (Low effort, high impact)", st["sub_heading"]))
        for quick_win in quick_wins[:3]:
            story.append(
                Paragraph(
                    f"<b>{quick_win.get('title', '')}</b> — {quick_win.get('expected_impact', '')}",
                    st["body"],
                )
            )
            story.append(
                Paragraph(
                    f"Cost: {quick_win.get('estimated_cost', 'N/A')} · Time: {quick_win.get('time_to_implement', 'N/A')}",
                    st["body_muted"],
                )
            )
            story.append(Spacer(1, 4))

    story += [Spacer(1, 6), Paragraph("All Interventions (sorted by priority)", st["sub_heading"])]
    rows = [[Paragraph("Title", st["table_header"]), Paragraph("Impact", st["table_header"]), Paragraph("Effort", st["table_header"]), Paragraph("Score", st["table_header"])]]
    for intervention in items[:8]:
        rows.append(
            [
                Paragraph(str(intervention.get("title", ""))[:70], st["table_cell"]),
                Paragraph(str(intervention.get("expected_impact", ""))[:50], st["table_cell"]),
                Paragraph(str(intervention.get("difficulty", ""))[:10], st["table_cell_c"]),
                Paragraph(f"{float(intervention.get('priority_score', 0)):.2f}", st["table_cell_c"]),
            ]
        )
    table = Table(rows, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.30, CONTENT_W * 0.14, CONTENT_W * 0.14])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    return story


def _competitive_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    comp = data.get("competitive") or {}
    competitors = comp.get("competitors") or []
    if not competitors:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Competitive Landscape", st["section_heading"])]
    story += _divider()
    position = comp.get("overall_competitive_position") or "MODERATE"
    rationale = comp.get("position_rationale") or ""
    story += [Paragraph(f"Overall competitive position: <b>{position}</b>. {rationale}", st["body"]), Spacer(1, 8)]

    rows = [[Paragraph("Competitor", st["table_header"]), Paragraph("Category", st["table_header"]), Paragraph("Threat", st["table_header"]), Paragraph("India presence", st["table_header"]), Paragraph("Pricing", st["table_header"])]]
    for competitor in competitors[:6]:
        rows.append(
            [
                Paragraph(str(competitor.get("name", ""))[:30], st["table_cell"]),
                Paragraph(str(competitor.get("category", ""))[:12], st["table_cell_c"]),
                Paragraph(str(competitor.get("threat_level", ""))[:8], st["table_cell_c"]),
                Paragraph(str(competitor.get("india_presence", ""))[:12], st["table_cell_c"]),
                Paragraph(str(competitor.get("pricing", ""))[:35], st["table_cell"]),
            ]
        )
    table = Table(rows, colWidths=[CONTENT_W * 0.24, CONTENT_W * 0.13, CONTENT_W * 0.10, CONTENT_W * 0.16, CONTENT_W * 0.37])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)

    gap = comp.get("gap_analysis") or {}
    wins = gap.get("our_wins") or []
    if wins:
        story += [Spacer(1, 8), Paragraph("Where we win:", st["sub_heading"])]
        for win in wins[:4]:
            story.append(Paragraph(f"• {win}", st["body"]))

    losses = gap.get("our_losses") or []
    if losses:
        story += [Spacer(1, 6), Paragraph("Where we are at risk:", st["sub_heading"])]
        for loss in losses[:4]:
            story.append(Paragraph(f"• {loss}", st["body"]))
    return story


def _decision_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    decision = data.get("decision") or {}
    scenarios = decision.get("scenarios") or []
    if not scenarios:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Decision Comparison", st["section_heading"])]
    story += _divider()
    story.append(
        Paragraph(
            f"Recommended scenario: <b>{decision.get('recommended_scenario', 'N/A')}</b> · Winner margin: <b>{float(decision.get('winner_margin', 0.0))*100:.1f}%</b>",
            st["body"],
        )
    )

    rows = [[Paragraph("Scenario", st["table_header"]), Paragraph("Conversion", st["table_header"]), Paragraph("Revenue", st["table_header"]), Paragraph("Rank", st["table_header"])]]
    for scenario in scenarios[:6]:
        rows.append(
            [
                Paragraph(str(scenario.get("scenario_name", ""))[:50], st["table_cell"]),
                Paragraph(f"{float(scenario.get('conversion_rate', 0.0))*100:.1f}%", st["table_cell_c"]),
                Paragraph(f"₹{float(scenario.get('revenue_projection', 0.0)):,.0f}", st["table_cell_c"]),
                Paragraph(str(scenario.get("rank", "")), st["table_cell_c"]),
            ]
        )
    table = Table(rows, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.18, CONTENT_W * 0.22, CONTENT_W * 0.15])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    return story


def _outcomes_section(data: dict[str, Any], st: dict[str, ParagraphStyle]) -> list[Any]:
    outcomes = data.get("outcomes") or []
    if not outcomes:
        return []

    story: list[Any] = [Spacer(1, 8), Paragraph("Real-World Outcomes vs Predictions", st["section_heading"])]
    story += _divider()
    rows = [[Paragraph("Date", st["table_header"]), Paragraph("Actual conv.", st["table_header"]), Paragraph("Predicted", st["table_header"]), Paragraph("Variance", st["table_header"]), Paragraph("Calibration", st["table_header"])]]
    for outcome in outcomes[:6]:
        actual = float(outcome.get("actual_conversion_rate") or 0.0)
        pred = outcome.get("predicted_conversion_rate")
        var = (outcome.get("variance") or {}).get("conversion")
        cal = float(outcome.get("calibration_score") or 0.0)
        rec_at = str(outcome.get("recorded_at") or "")[:10]
        rows.append(
            [
                Paragraph(rec_at, st["table_cell_c"]),
                Paragraph(f"{actual*100:.1f}%", st["table_cell_c"]),
                Paragraph(f"{float(pred)*100:.1f}%" if pred is not None else "N/A", st["table_cell_c"]),
                Paragraph(f"{float(var):+.1f}%" if var is not None else "N/A", st["table_cell_c"]),
                Paragraph(f"{cal:.0f}/100", st["table_cell_c"]),
            ]
        )
    table = Table(rows, colWidths=[CONTENT_W * 0.20] * 5)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, CREAM]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    return story


class ReportGenerator:
    def generate(self, project_data: dict[str, Any]) -> bytes:
        buffer = io.BytesIO()
        styles = _styles()

        doc = BaseDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=MARGIN,
            leftMargin=MARGIN,
            topMargin=14 * mm,
            bottomMargin=16 * mm,
            title=project_data.get("title") or "TheCee Report",
            author="TheCee Simulation Engine",
        )
        doc.addPageTemplates([_make_page_template(doc)])

        story: list[Any] = []
        story += _cover_section(project_data, styles)
        story += _executive_summary(project_data, styles)
        story += _assumptions_section(project_data, styles)
        story += _funnel_section(project_data, styles)

        if project_data.get("premortem"):
            story += [PageBreak()]
            story += _premortem_section(project_data, styles)

        if project_data.get("stress_test"):
            story += [PageBreak()]
            story += _stress_test_section(project_data, styles)

        if project_data.get("interventions"):
            story += [PageBreak()]
            story += _interventions_section(project_data, styles)

        if project_data.get("competitive"):
            story += [PageBreak()]
            story += _competitive_section(project_data, styles)

        if project_data.get("decision"):
            story += [PageBreak()]
            story += _decision_section(project_data, styles)

        if project_data.get("outcomes"):
            story += [PageBreak()]
            story += _outcomes_section(project_data, styles)

        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
