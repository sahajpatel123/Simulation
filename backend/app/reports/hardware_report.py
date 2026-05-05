from __future__ import annotations

import html
import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Colour palette (matches Step 66) ──
THECEE_DARK = colors.HexColor("#0F172A")
THECEE_BLUE = colors.HexColor("#3B82F6")
THECEE_LIGHT = colors.HexColor("#F1F5F9")
THECEE_GREEN = colors.HexColor("#22C55E")
THECEE_RED = colors.HexColor("#EF4444")
THECEE_AMBER = colors.HexColor("#F59E0B")
THECEE_SLATE = colors.HexColor("#64748B")

# ── Cluster persona names — server-side equivalent of Step 68a ──
# Subset of the 52 clusters most relevant for hardware products
HARDWARE_PERSONA_NAMES: dict[str, tuple[str, str]] = {
    "health_hardware_skeptic": ("Dr. Anita", "Burned Before, High Guard"),
    "health_hardware_enthusiast": ("Kabir", "Upgrades Every 18 Months"),
    "wealthy_health_conscious_buyer": ("Priya", "Clinical or Nothing"),
    "high_income_hardware_enthusiast": ("Karan", "Spec Sheet First"),
    "early_hardware_adopter_tech_enthusiast": ("Aditya", "Pre-orders Before Reviews"),
    "considered_hardware_researcher": ("Pallavi", "10 Reviews, 5 Videos Minimum"),
    "value_hardware_buyer": ("Dinesh", "Best Under ₹X, Every Time"),
    "gift_hardware_buyer": ("Rekha", "Packaging Is Half the Product"),
    "replacement_hardware_buyer": ("Vijay", "Urgent, Loyal Unless Burned"),
    "smart_home_early_adopter": ("Tanya", "Does It Talk to My Hub?"),
    "urban_mid_income_hardware_considerer": ("Kavya", "EMI Makes It Real"),
    "tier3_first_time_app_user": ("Geeta", "Converts If Explained In Person"),
    "tier2_price_sensitive_pragmatist": ("Mohan", "Cheapest Credible Option Wins"),
    "impulsive_trend_follower": ("Tia", "Reel to Cart in 8 Seconds"),
    "burnt_previously_buyer": ("Sarah", "Burned Before, High Guard"),
    "anxiety_driven_researcher": ("Manish", "20 Tabs, Still Not Sure"),
    "metro_power_professional": ("Arjun", "Pays for Performance"),
    "tier3_community_influenced_buyer": ("Savita", "Community Decides, Not Her"),
    "urban_working_mother": ("Deepa", "Safety and Time First"),
    "ngo_nonprofit_buyer": ("Sister Agnes", "Committee, Budget Cap, Slow Cycle"),
    "diaspora_remittance_buyer": ("Raj (NRI)", "Buying for Family Back Home"),
}


def _persona_name(cluster_id: str) -> str:
    if cluster_id in HARDWARE_PERSONA_NAMES:
        return HARDWARE_PERSONA_NAMES[cluster_id][0]
    return cluster_id.replace("_", " ").title()


def _persona_tagline(cluster_id: str) -> str:
    if cluster_id in HARDWARE_PERSONA_NAMES:
        return HARDWARE_PERSONA_NAMES[cluster_id][1]
    return ""


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
            alignment=TA_LEFT,
        ),
        "Caption": ParagraphStyle(
            "Caption",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.grey,
            alignment=TA_CENTER,
        ),
        "Verdict": ParagraphStyle(
            "Verdict",
            parent=base["Normal"],
            fontSize=14,
            textColor=THECEE_DARK,
            alignment=TA_CENTER,
            spaceBefore=4,
        ),
    }
    return base, custom


def _table_cmds(header_color=THECEE_BLUE) -> list[tuple]:
    return [
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


def _table_style(header_color=THECEE_BLUE) -> TableStyle:
    return TableStyle(_table_cmds(header_color))


def _verdict_color(verdict: str) -> colors.Color:
    return {
        "VIABLE": THECEE_GREEN,
        "MARGINAL": THECEE_AMBER,
        "NOT_VIABLE": THECEE_RED,
    }.get(verdict, THECEE_SLATE)


def _status_color(status: str) -> colors.Color:
    return {
        "PASS": THECEE_GREEN,
        "PARTIAL": THECEE_AMBER,
        "FAIL": THECEE_RED,
    }.get(status, THECEE_SLATE)


class HardwareReportGenerator:
    def generate(
        self,
        hardware_product: dict[str, Any],
        spec: dict[str, Any],
        test_results: list[dict[str, Any]],
        cost_estimate: dict[str, Any],
        consumer_sim: dict[str, Any],
        competitive: dict[str, Any],
        project_name: str = "Hardware Product",
    ) -> bytes:
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
        story: list = []

        product_name = html.escape(
            str(
                hardware_product.get("name")
                or spec.get("product_name")
                or project_name,
            ),
        )
        category_raw = str(hardware_product.get("category", "hardware"))
        category = html.escape(category_raw.replace("_", " ").title())
        target_price = float(hardware_product.get("target_price_inr", 0))
        verdict = str(cost_estimate.get("verdict", "UNKNOWN"))
        overall_cr = float(consumer_sim.get("overall_conversion_rate", 0))
        prototype_wired = bool(consumer_sim.get("prototype_wired", False))

        verdict_para_style = ParagraphStyle(
            "VerdictDynamic",
            parent=S["Verdict"],
            textColor=_verdict_color(verdict),
        )

        gen_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

        # ══════════════ COVER PAGE ══════════════
        story += [
            Spacer(1, 25 * mm),
            Paragraph("TheCee", S["ReportTitle"]),
            Paragraph("Hardware Intelligence Report", S["ReportTitle"]),
            Spacer(1, 4 * mm),
            HRFlowable(width="100%", thickness=2, color=THECEE_BLUE),
            Spacer(1, 4 * mm),
            Paragraph(
                product_name,
                ParagraphStyle(
                    "ProjName",
                    parent=base["Normal"],
                    fontSize=16,
                    textColor=THECEE_DARK,
                    alignment=TA_CENTER,
                ),
            ),
            Spacer(1, 2 * mm),
            Paragraph(
                f"Category: {category}  |  "
                f"Target price: ₹{target_price:,.0f}  |  "
                f"Generated: {gen_date}",
                S["Caption"],
            ),
            Spacer(1, 6 * mm),
            Paragraph(
                f"Product Verdict: {html.escape(verdict)}",
                verdict_para_style,
            ),
            Spacer(1, 2 * mm),
            Paragraph(html.escape(str(cost_estimate.get("verdict_reason", ""))), S["Body"]),
            PageBreak(),
        ]

        # ══════════════ SECTION 1 — EXECUTIVE SUMMARY ══════════════
        story.append(Paragraph("1. Executive Summary", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        summary_data = [
            ["Metric", "Value"],
            ["Product Name", product_name],
            ["Category", category],
            ["Target Price", f"₹{target_price:,.0f}"],
            ["Landed Cost", f"₹{float(cost_estimate.get('landed_cost_inr', 0)):,.0f}"],
            ["Gross Margin", f"{float(cost_estimate.get('margin_pct', 0)):.1f}%"],
            ["Viability Verdict", html.escape(verdict)],
            ["Break-even MOQ", f"{int(cost_estimate.get('break_even_moq', 0)):,} units"],
            ["Overall Conversion Rate", f"{overall_cr * 100:.1f}%"],
            [
                "Physics Tests Passed",
                f"{sum(1 for r in test_results if r.get('status') == 'PASS')}/{len(test_results)}",
            ],
            ["Prototype Wired", "Yes" if prototype_wired else "No"],
        ]
        story.append(Table(summary_data, colWidths=[90 * mm, 80 * mm], style=_table_style()))
        story.append(PageBreak())

        # ══════════════ SECTION 2 — KEY PERSON REPORT ══════════════
        story.append(
            Paragraph(
                "2. The People Who Will Decide This Product's Fate",
                S["SectionHeader"],
            ),
        )
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        champion_ids = list(consumer_sim.get("champion_clusters", []))[:3]
        blocker_ids = list(consumer_sim.get("blocker_clusters", []))[:3]
        cluster_res = consumer_sim.get("cluster_results") or {}
        findings_top = list(consumer_sim.get("domain_findings", []))

        def _top_finding_for(cluster_id: str) -> str:
            matches = [f for f in findings_top if f.get("cluster_id") == cluster_id]
            return matches[0]["finding"] if matches else "No critical findings"

        if blocker_ids:
            story.append(Paragraph("People Who Drop — Fix These First", S["SubHeader"]))
            blocker_data = [["Persona", "Tagline", "Conversion", "Top Finding"]]
            for cid in blocker_ids:
                cr_val = float((cluster_res.get(cid) or {}).get("conversion_rate", 0))
                blocker_data.append(
                    [
                        html.escape(_persona_name(cid)),
                        html.escape(_persona_tagline(cid)),
                        f"{cr_val * 100:.1f}%",
                        html.escape(str(_top_finding_for(cid))[:55]),
                    ],
                )
            t = Table(blocker_data, colWidths=[28 * mm, 40 * mm, 20 * mm, 75 * mm])
            t.setStyle(_table_style(THECEE_RED))
            story.append(t)
            story.append(Spacer(1, 3 * mm))

        if champion_ids:
            story.append(
                Paragraph(
                    "People Who Convert — Focus Acquisition Here",
                    S["SubHeader"],
                ),
            )
            champ_data = [["Persona", "Tagline", "Conversion", "Population"]]
            for cid in champion_ids:
                cdata = cluster_res.get(cid) or {}
                cr_val = float(cdata.get("conversion_rate", 0))
                pop_val = float(cdata.get("population_fraction", 0))
                champ_data.append(
                    [
                        html.escape(_persona_name(cid)),
                        html.escape(_persona_tagline(cid)),
                        f"{cr_val * 100:.1f}%",
                        f"{pop_val * 100:.1f}% of market",
                    ],
                )
            t = Table(champ_data, colWidths=[28 * mm, 40 * mm, 20 * mm, 75 * mm])
            t.setStyle(_table_style(THECEE_GREEN))
            story.append(t)
        story.append(PageBreak())

        # ══════════════ SECTION 3 — PHYSICS TEST RESULTS ══════════════
        story.append(Paragraph("3. Physics Test Results", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        if test_results:
            def _sort_t(x: dict[str, Any]) -> tuple[int, str]:
                st = x.get("status")
                rank = 0 if st == "FAIL" else 1 if st == "PARTIAL" else 2
                return (rank, str(x.get("test_type", "")))

            sorted_tests = sorted(test_results, key=_sort_t)
            test_data = [["Test", "Status", "Pass Rate", "Key Metric", "Top Failure"]]
            for r in sorted_tests:
                metrics = r.get("metrics") or {}
                fps = r.get("failure_points") or []
                top_fp = str(fps[0].get("reason", "—"))[:40] if fps else "—"

                test_type = str(r.get("test_type", ""))
                if test_type == "DROP_TEST":
                    key_m = f"Impact {float(metrics.get('impact_force_n', 0) or 0):.0f}N"
                elif test_type == "THERMAL_CYCLE":
                    key_m = f"Delta {metrics.get('delta_celsius', 0)}°C"
                elif test_type == "WATER_INGRESS":
                    key_m = f"Target {metrics.get('target_ip', '—')}"
                elif test_type == "BATTERY_DRAIN":
                    key_m = f"{float(metrics.get('runtime_hours', 0) or 0):.1f}h runtime"
                elif test_type == "VIBRATION":
                    key_m = f"{metrics.get('frequency_hz', 0)}Hz"
                elif test_type == "HUMIDITY_SOAK":
                    key_m = f"{metrics.get('rh_percent', 0)}% RH"
                elif test_type == "UV_EXPOSURE":
                    key_m = f"{float(metrics.get('effective_hours', 0) or 0):.0f}h UV"
                elif test_type == "COMPRESSION":
                    key_m = f"{float(metrics.get('stress_mpa', 0) or 0):.2f} MPa"
                else:
                    key_m = "—"

                test_data.append(
                    [
                        html.escape(test_type.replace("_", " ").title()),
                        html.escape(str(r.get("status", "—"))),
                        f"{float(r.get('pass_rate', 0) or 0) * 100:.0f}%",
                        html.escape(key_m),
                        html.escape(top_fp),
                    ],
                )

            status_cmds: list[tuple] = []
            for i, r in enumerate(sorted_tests, start=1):
                sc = _status_color(str(r.get("status", "INFO")))
                status_cmds.append(("TEXTCOLOR", (1, i), (1, i), sc))
                status_cmds.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))

            t = Table(test_data, colWidths=[35 * mm, 18 * mm, 18 * mm, 35 * mm, 57 * mm])
            t.setStyle(TableStyle(_table_cmds() + status_cmds))
            story.append(t)
        else:
            story.append(Paragraph("No physics tests run yet.", S["Body"]))
        story.append(PageBreak())

        # ══════════════ SECTION 4 — MANUFACTURING COST ══════════════
        story.append(Paragraph("4. Manufacturing Cost Analysis", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        bom = list(cost_estimate.get("bom", []))
        if bom:
            story.append(Paragraph("Bill of Materials", S["SubHeader"]))
            bom_data = [
                ["Component", "Material", "Volume cm³", "Unit Cost (₹)"],
            ]
            for item in bom:
                bom_data.append(
                    [
                        html.escape(str(item.get("component_name", ""))[:25]),
                        html.escape(str(item.get("material", ""))[:20]),
                        f"{float(item.get('volume_cm3', 0) or 0):.1f}",
                        f"₹{float(item.get('unit_cost_inr', 0) or 0):,.2f}",
                    ],
                )
            bom_data.append(
                [
                    "",
                    "",
                    "TOTAL",
                    f"₹{float(cost_estimate.get('bom_total_inr', 0)):,.2f}",
                ],
            )
            story.append(Table(bom_data, colWidths=[50 * mm, 42 * mm, 25 * mm, 47 * mm], style=_table_style()))
            story.append(Spacer(1, 3 * mm))

        bom_t = float(cost_estimate.get("bom_total_inr", 0) or 0)
        alb = float(cost_estimate.get("assembly_labour_inr", 0) or 0)
        tool_u = float(cost_estimate.get("tooling_per_unit_inr", 0) or 0)
        landed = float(cost_estimate.get("landed_cost_inr", 0) or 0)
        logistics = max(0.0, landed - bom_t - alb - tool_u)

        cost_summary = [
            ["Cost Component", "Per Unit (₹)"],
            ["Raw Materials (BOM)", f"₹{bom_t:,.2f}"],
            ["Assembly Labour", f"₹{alb:,.2f}"],
            ["Tooling (amortised)", f"₹{tool_u:,.2f}"],
            ["Logistics (residual)", f"₹{logistics:,.2f}"],
            ["Landed Cost", f"₹{landed:,.2f}"],
            ["Target Price", f"₹{float(cost_estimate.get('target_price_inr', 0) or 0):,.2f}"],
            [
                "Gross Margin",
                f"₹{float(cost_estimate.get('margin_inr', 0) or 0):,.2f} "
                f"({float(cost_estimate.get('margin_pct', 0) or 0):.1f}%)",
            ],
            ["Break-even MOQ", f"{int(cost_estimate.get('break_even_moq', 0)):,} units"],
        ]
        story.append(Table(cost_summary, colWidths=[90 * mm, 80 * mm], style=_table_style()))
        story.append(PageBreak())

        # ══════════════ SECTION 5 — CLUSTER BEHAVIORAL ANALYSIS ══════════════
        story.append(Paragraph("5. Cluster Behavioral Analysis", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        story.append(
            Paragraph(
                f"Simulation ran {int(consumer_sim.get('total_agents', 0)):,} synthetic people "
                f"across 52 market segments. Overall conversion: "
                f"{overall_cr * 100:.1f}%.",
                S["Body"],
            ),
        )
        story.append(Spacer(1, 3 * mm))

        pfd = str(consumer_sim.get("primary_failure_domain", "unknown"))
        story.append(
            Paragraph(
                f"Primary failure domain: {html.escape(pfd.replace('Architect', ''))}",
                S["SubHeader"],
            ),
        )
        story.append(Spacer(1, 2 * mm))

        if isinstance(cluster_res, dict) and cluster_res:
            sorted_clusters = sorted(
                cluster_res.items(),
                key=lambda x: float((x[1] or {}).get("conversion_rate", 0)),
                reverse=True,
            )
            cluster_data = [["Cluster", "Persona", "Conv. Rate", "Population", "Top Finding"]]
            for cid, cdata in sorted_clusters[:15]:
                cdata = cdata or {}
                cluster_data.append(
                    [
                        html.escape(cid.replace("_", " ")[:22]),
                        html.escape(_persona_name(cid)),
                        f"{float(cdata.get('conversion_rate', 0) or 0) * 100:.1f}%",
                        f"{float(cdata.get('population_fraction', 0) or 0) * 100:.1f}%",
                        html.escape(str(cdata.get("top_finding", "—"))[:35]),
                    ],
                )
            story.append(
                Table(
                    cluster_data,
                    colWidths=[42 * mm, 24 * mm, 18 * mm, 18 * mm, 58 * mm],
                    style=_table_style(),
                ),
            )

        story.append(Spacer(1, 3 * mm))

        accountab = consumer_sim.get("architect_accountability") or {}
        if isinstance(accountab, dict) and accountab:
            story.append(Paragraph("Which Architects Identified Highest Risk", S["SubHeader"]))
            acc_data = [["Architect Domain", "Accountability Score"]]
            for arch, score in sorted(accountab.items(), key=lambda x: float(x[1]), reverse=True)[:6]:
                acc_data.append(
                    [
                        html.escape(str(arch).replace("Architect", "").replace("_", " ")),
                        f"{float(score) * 100:.1f}%",
                    ],
                )
            story.append(Table(acc_data, colWidths=[100 * mm, 70 * mm], style=_table_style()))
        story.append(PageBreak())

        # ══════════════ SECTION 6 — COMPETITIVE ANALYSIS ══════════════
        story.append(Paragraph("6. Competitive Analysis", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        if competitive:
            rp = competitive.get("recommended_positioning")
            if isinstance(rp, str) and rp.strip():
                story.append(
                    Paragraph(
                        f"<b>Recommended positioning</b>: {html.escape(rp)}",
                        S["Body"],
                    ),
                )
            pp = competitive.get("price_position")
            if isinstance(pp, str) and pp.strip():
                story.append(
                    Paragraph(f"<b>Price position</b>: {html.escape(pp)}", S["Body"]),
                )
            mf = competitive.get("margin_floor")
            if mf is not None:
                story.append(
                    Paragraph(
                        f"<b>Margin floor</b>: {html.escape(str(mf))}",
                        S["Body"],
                    ),
                )
            kdrag = competitive.get("key_drag_on_conversion")
            if isinstance(kdrag, str) and kdrag.strip():
                story.append(
                    Paragraph(
                        f"<b>Key drag on conversion</b>: {html.escape(kdrag)}",
                        S["Body"],
                    ),
                )
            clusters = competitive.get("margin_drag_clusters") or []
            if isinstance(clusters, list) and clusters:
                story.append(Paragraph("<b>Margin drag clusters</b>:", S["Body"]))
                for c in clusters[:8]:
                    story.append(
                        Paragraph(f"• {html.escape(str(c))}", S["Body"]),
                    )
            for label, key in (
                ("Top threats", "top_threats"),
                ("Top opportunities", "top_opportunities"),
            ):
                items = competitive.get(key) or []
                if isinstance(items, list) and items:
                    story.append(Paragraph(f"<b>{html.escape(label)}</b>:", S["Body"]))
                    for item in items[:6]:
                        story.append(Paragraph(f"• {html.escape(str(item))}", S["Body"]))
            story.append(Spacer(1, 2 * mm))
        else:
            story.append(
                Paragraph(
                    "Run competitive analysis to populate this section. "
                    "POST to /hardware/{id}/competitive-analysis.",
                    S["Body"],
                ),
            )
        story.append(PageBreak())

        # ══════════════ SECTION 7 — RECOMMENDED ACTIONS ══════════════
        story.append(Paragraph("7. Recommended Actions", S["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=THECEE_BLUE))
        story.append(Spacer(1, 3 * mm))

        all_recs: list[tuple[str, str, str]] = []

        for r in test_results:
            if r.get("status") in ("FAIL", "PARTIAL"):
                fps = r.get("failure_points") or []
                if fps:
                    all_recs.append(
                        (
                            str(r.get("test_type", "")).replace("_", " ").title(),
                            "CRITICAL" if r.get("status") == "FAIL" else "WARNING",
                            str(fps[0].get("reason", "Review component"))[:80],
                        ),
                    )

        for f in findings_top[:5]:
            all_recs.append(
                (
                    str(f.get("architect_name", "")).replace("Architect", ""),
                    str(f.get("severity", "INFO")),
                    str(f.get("recommended_action", ""))[:80],
                ),
            )

        if not all_recs:
            all_recs.append(
                ("Overall", "INFO", "No critical actions required — product is well-specified"),
            )

        SRANK = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        all_recs.sort(key=lambda x: SRANK.get(x[1], 2))
        top_recs = all_recs[:10]

        rec_data = [["Source", "Severity", "Action"]]
        for source, sev, action in top_recs:
            rec_data.append(
                [
                    html.escape(source[:20]),
                    html.escape(sev[:8]),
                    html.escape(action),
                ],
            )

        sev_cmds: list[tuple] = []
        for i, (_, sev, _) in enumerate(top_recs, start=1):
            sc = _status_color(
                "FAIL"
                if sev == "CRITICAL"
                else "PARTIAL"
                if sev == "WARNING"
                else "PASS",
            )
            sev_cmds.append(("TEXTCOLOR", (1, i), (1, i), sc))
            sev_cmds.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))

        t = Table(rec_data, colWidths=[35 * mm, 20 * mm, 110 * mm])
        t.setStyle(TableStyle(_table_cmds() + sev_cmds))
        story.append(t)

        doc.build(story)
        return buf.getvalue()
