from __future__ import annotations

import html
import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

THECEE_DARK = colors.HexColor("#0F172A")
THECEE_BLUE = colors.HexColor("#3B82F6")
THECEE_LIGHT = colors.HexColor("#F1F5F9")
THECEE_GREEN = colors.HexColor("#22C55E")
THECEE_RED = colors.HexColor("#EF4444")
THECEE_AMBER = colors.HexColor("#F59E0B")


def _styles():
    base = getSampleStyleSheet()
    custom = {
        "ReportTitle": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontSize=22,
            textColor=THECEE_DARK,
            spaceAfter=6,
            alignment=TA_CENTER,
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader",
            parent=base["Heading1"],
            fontSize=13,
            textColor=THECEE_BLUE,
            spaceBefore=12,
            spaceAfter=4,
        ),
        "SubHeader": ParagraphStyle(
            "SubHeader",
            parent=base["Heading2"],
            fontSize=10,
            textColor=THECEE_DARK,
            spaceBefore=8,
            spaceAfter=3,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9,
            leading=14,
            textColor=THECEE_DARK,
        ),
        "Metric": ParagraphStyle(
            "Metric",
            parent=base["Normal"],
            fontSize=11,
            textColor=THECEE_BLUE,
            alignment=TA_CENTER,
        ),
        "Caption": ParagraphStyle(
            "Caption",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.grey,
            alignment=TA_CENTER,
        ),
    }
    return base, custom


def _severity_color(severity: str) -> colors.Color:
    return {
        "CRITICAL": THECEE_RED,
        "WARNING": THECEE_AMBER,
        "INFO": THECEE_GREEN,
    }.get(severity, THECEE_DARK)


def _table_style(header_color=THECEE_BLUE) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [THECEE_LIGHT, colors.white]),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
    )


def _top_channel_label(channel_data: dict) -> str:
    mr = channel_data.get("market_channel_ranking") or []
    if not mr:
        return "—"
    first = mr[0]
    if isinstance(first, dict):
        return str(first.get("channel", "—"))
    if isinstance(first, (list, tuple)) and len(first) >= 1:
        return str(first[0])
    return "—"


class SimulationReportGenerator:

    def generate(
        self,
        simulation_data: dict[str, Any],
        conductor_data: dict[str, Any],
        funnel_data: dict[str, Any],
        heatmap_data: dict[str, Any],
        pricing_data: dict[str, Any],
        retention_data: dict[str, Any],
        channel_data: dict[str, Any],
        infra_data: dict[str, Any],
        project_name: str = "Product Simulation",
    ) -> bytes:
        _ = conductor_data  # reserved for future conductor-only panels
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )
        base, S = _styles()
        story = []

        gen_ts = datetime.now(timezone.utc).strftime("%B %d, %Y")
        story += [
            Spacer(1, 30 * mm),
            Paragraph("TheCee", S["ReportTitle"]),
            Paragraph("Simulation Intelligence Report", S["ReportTitle"]),
            Spacer(1, 4 * mm),
            HRFlowable(width="100%", thickness=2, color=THECEE_BLUE),
            Spacer(1, 4 * mm),
            Paragraph(
                html.escape(project_name),
                ParagraphStyle(
                    "ProjName",
                    parent=base["Normal"],
                    fontSize=14,
                    textColor=THECEE_DARK,
                    alignment=TA_CENTER,
                ),
            ),
            Spacer(1, 3 * mm),
            Paragraph(
                f"Generated: {gen_ts}  |  "
                f"Product type: {html.escape(str(simulation_data.get('product_type_detected', '—')))}  |  "
                f"Signal quality: {round((simulation_data.get('signal_quality') or 0) * 100)}%",
                S["Caption"],
            ),
            PageBreak(),
        ]

        story.append(Paragraph("1. Executive Summary", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        overall_cr = simulation_data.get("population_weighted_conversion", 0)
        primary_fd = simulation_data.get("primary_failure_domain", "—")
        hv_cluster = simulation_data.get("highest_value_cluster", {})
        hv_name = hv_cluster.get("name", "—") if isinstance(hv_cluster, dict) else str(hv_cluster)
        hv_cr = hv_cluster.get("conversion_rate", 0) if isinstance(hv_cluster, dict) else 0

        summary_data = [
            ["Metric", "Value"],
            ["Overall Conversion Rate", f"{overall_cr * 100:.1f}%"],
            ["Primary Failure Domain", html.escape(str(primary_fd))],
            ["Highest Value Segment", f"{html.escape(str(hv_name))} ({hv_cr * 100:.1f}%)"],
            ["Market Day-7 Survival", f"{retention_data.get('market_day7_survival', 0) * 100:.1f}%"],
            ["Market Day-30 Survival", f"{retention_data.get('market_day30_survival', 0) * 100:.1f}%"],
            ["Recommended Price Point", f"INR {pricing_data.get('recommended_price', 0):,.0f}"],
            ["Revenue-Optimal Price", f"INR {pricing_data.get('revenue_optimal_price', 0):,.0f}"],
            ["Top Acquisition Channel", html.escape(_top_channel_label(channel_data))],
            [
                "Viral Growth Possible",
                "Yes" if channel_data.get("viral_growth_possible") else "No",
            ],
        ]
        story.append(Table(summary_data, colWidths=[90 * mm, 80 * mm], style=_table_style()))
        story.append(Spacer(1, 4 * mm))

        narrative = simulation_data.get("cluster_narrative", "")
        if narrative:
            story.append(Paragraph("Cluster Analysis Summary", S["SubHeader"]))
            for line in narrative.split("\n")[:12]:
                if line.strip():
                    story.append(Paragraph(html.escape(line.strip()), S["Body"]))
        story.append(PageBreak())

        story.append(Paragraph("2. Domain Findings (Top 10 by Impact)", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        findings = simulation_data.get("domain_findings", [])[:10]
        if findings:
            findings_data = [["Architect", "Cluster", "Finding", "Impact", "Sev."]]
            for f in findings:
                findings_data.append(
                    [
                        html.escape(str(f.get("architect_name", "")).replace("Architect", "")),
                        html.escape(str(f.get("cluster_name", ""))[:20]),
                        html.escape(str(f.get("finding", ""))[:50]),
                        f"{f.get('conversion_impact', 0) * 100:.1f}%",
                        html.escape(str(f.get("severity", "INFO"))[:4]),
                    ]
                )
            t = Table(findings_data, colWidths=[30 * mm, 30 * mm, 72 * mm, 15 * mm, 12 * mm])
            t.setStyle(_table_style())
            for i, f in enumerate(findings, start=1):
                sev = f.get("severity", "INFO")
                t.setStyle(
                    TableStyle(
                        [
                            ("TEXTCOLOR", (4, i), (4, i), _severity_color(str(sev))),
                            ("FONTNAME", (4, i), (4, i), "Helvetica-Bold"),
                        ]
                    )
                )
            story.append(t)
        else:
            story.append(Paragraph("No domain findings available.", S["Body"]))
        story.append(PageBreak())

        story.append(Paragraph("3. Conversion Funnel", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        stages = funnel_data.get("stages", [])
        if stages:
            funnel_table = [["Stage", "Agents Entered", "Agents Exited", "Exit Rate"]]
            for s in stages:
                funnel_table.append(
                    [
                        html.escape(str(s.get("stage", ""))),
                        f"{s.get('agents_entered', 0):,}",
                        f"{s.get('agents_exited', 0):,}",
                        f"{s.get('exit_rate', 0) * 100:.1f}%",
                    ]
                )
            story.append(Table(funnel_table, colWidths=[40 * mm, 45 * mm, 45 * mm, 40 * mm], style=_table_style()))
            story.append(Spacer(1, 2 * mm))
            story.append(
                Paragraph(
                    f"Highest drop-off stage: {html.escape(str(funnel_data.get('highest_drop_stage', '—')))}  |  "
                    f"Best cluster: {html.escape(str(funnel_data.get('best_cluster', '—')))}  |  "
                    f"Worst cluster: {html.escape(str(funnel_data.get('worst_cluster', '—')))}",
                    S["Caption"],
                )
            )

        story.append(Paragraph("Click heatmap summary", S["SubHeader"]))
        story.append(
            Paragraph(
                f"Total tracked clicks: {heatmap_data.get('total_clicks', 0):,} | "
                f"Unique elements: {heatmap_data.get('unique_elements', 0)} | "
                f"Top conversion element: {html.escape(str(heatmap_data.get('top_conversion_element', '—')))} | "
                f"Top abandon element: {html.escape(str(heatmap_data.get('top_abandon_element', '—')))}",
                S["Body"],
            )
        )
        story.append(PageBreak())

        story.append(Paragraph("4. Pricing Sensitivity", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        profiles = pricing_data.get("cluster_profiles", [])[:10]
        if profiles:
            price_table = [["Cluster", "Price Ceiling", "Optimal Price", "EMI Required", "Annual Pref."]]
            for p in profiles:
                price_table.append(
                    [
                        html.escape(str(p.get("cluster_name", ""))[:25]),
                        f"INR {p.get('price_ceiling', 0):,.0f}",
                        f"INR {p.get('optimal_price', 0):,.0f}",
                        "Yes" if p.get("emi_required") else "No",
                        f"{p.get('annual_preference', 0) * 100:.0f}%",
                    ]
                )
            story.append(Table(price_table, colWidths=[55 * mm, 30 * mm, 30 * mm, 25 * mm, 25 * mm], style=_table_style()))
        story.append(PageBreak())

        story.append(Paragraph("5. Retention and Churn", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        ret_profiles = retention_data.get("cluster_profiles", [])[:10]
        if ret_profiles:
            ret_table = [["Cluster", "D-1", "D-7", "D-30", "D-90", "LTV", "Churn Trigger"]]
            for p in ret_profiles:
                ret_table.append(
                    [
                        html.escape(str(p.get("cluster_name", ""))[:22]),
                        f"{p.get('day1_survival', 0) * 100:.0f}%",
                        f"{p.get('day7_survival', 0) * 100:.0f}%",
                        f"{p.get('day30_survival', 0) * 100:.0f}%",
                        f"{p.get('day90_survival', 0) * 100:.0f}%",
                        f"{p.get('ltv_score', 0):.2f}",
                        html.escape(str(p.get("churn_trigger", "—"))[:12]),
                    ]
                )
            story.append(
                Table(
                    ret_table,
                    colWidths=[44 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 25 * mm],
                    style=_table_style(),
                )
            )
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(
                f"Churn trigger distribution: {html.escape(str(retention_data.get('churn_trigger_distribution', {})))}",
                S["Body"],
            )
        )
        story.append(PageBreak())

        story.append(Paragraph("6. Marketing Channel Attribution", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        channel_ranking = channel_data.get("market_channel_ranking", [])[:8]
        if channel_ranking:
            ch_table = [["Channel", "Weighted Score"]]
            for row in channel_ranking:
                if isinstance(row, dict):
                    ch = row.get("channel", "—")
                    score = row.get("weighted_score", 0)
                else:
                    ch, score = row[0], row[1]
                ch_table.append([html.escape(str(ch).replace("_", " ").title()), f"{float(score):.3f}"])
            story.append(Table(ch_table, colWidths=[80 * mm, 50 * mm], style=_table_style()))
        story.append(Spacer(1, 2 * mm))
        mix = channel_data.get("recommended_channel_mix", {})
        if mix:
            story.append(Paragraph("Recommended budget allocation:", S["SubHeader"]))
            mix_table = [["Channel", "Allocation %"]] + [
                [html.escape(str(ch).replace("_", " ").title()), f"{float(v) * 100:.0f}%"] for ch, v in mix.items()
            ]
            story.append(Table(mix_table, colWidths=[80 * mm, 50 * mm], style=_table_style()))
        story.append(PageBreak())

        story.append(Paragraph("7. Infrastructure Scaling Projections", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        infra_stages = infra_data.get("stages", [])
        if infra_stages:
            infra_table = [["Stage", "Users", "DAU", "Concurrent", "Est. Cost/mo", "Tier", "Bottleneck"]]
            for s in infra_stages:
                infra_table.append(
                    [
                        html.escape(str(s.get("label", ""))[:20]),
                        f"{s.get('total_users', 0):,}",
                        f"{s.get('active_users', 0):,}",
                        f"{s.get('concurrent_peak', 0):,}",
                        f"${s.get('estimated_cost_usd', 0):,.0f}",
                        html.escape(str(s.get("recommended_tier", "—"))),
                        html.escape(str(s.get("bottleneck", "none"))[:18]),
                    ]
                )
            story.append(
                Table(
                    infra_table,
                    colWidths=[32 * mm, 18 * mm, 16 * mm, 20 * mm, 22 * mm, 18 * mm, 34 * mm],
                    style=_table_style(),
                )
            )
        warnings = infra_data.get("scaling_warnings", [])
        if warnings:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph("Scaling Warnings:", S["SubHeader"]))
            for w in warnings[:5]:
                story.append(Paragraph(f"• {html.escape(str(w))}", S["Body"]))

        doc.build(story)
        return buf.getvalue()
