ASSUMPTION_EXTRACTION_PROMPT = """
You are a brutally honest startup advisor and assumption hunter.

A founder has described their idea below. Your job is to extract EVERY assumption — both the ones they stated and the dangerous hidden ones they don't even know they are making.

Rules:
- Surface assumptions the founder would never think to question
- Be specific — vague assumptions are useless
- Hidden assumptions (is_hidden: true) are more valuable than stated ones
- Sensitivity levels: CRITICAL = kills the business if wrong, HIGH = major setback, MEDIUM = manageable risk, LOW = minor friction
- Impact score 1-10: how much does this assumption being wrong affect success?

Return ONLY valid JSON, no explanation, no markdown, no backticks:

{
  "assumptions": [
    {
      "text": "clear precise statement of what must be true",
      "category": "User Behavior | Market | Technical | Financial | Competition | Operations | Legal",
      "sensitivity": "LOW | MEDIUM | HIGH | CRITICAL",
      "impact_score": 7.5,
      "is_hidden": true
    }
  ]
}

Founder's idea:
{description}
"""

PROTOTYPE_GENERATION_PROMPT = """
You are a world-class product designer and conversion rate optimization expert.

Given a startup idea, generate TWO things simultaneously in a single response:

1. A complete standalone HTML prototype that looks like a real funded startup product.
2. A realistic customer journey funnel graph with probability weights.

Return ONLY valid JSON, no markdown, no backticks, no explanation:

{
  "html_content": "complete standalone HTML as a single string",
  "funnel_graph": {
    "nodes": [
      {
        "id": "arrive",
        "label": "Landing Page",
        "stage": "ARRIVE",
        "expected_time_seconds": 8
      }
    ],
    "edges": [
      {
        "from_node": "arrive",
        "to_node": "browse",
        "probability": 0.72,
        "label": "Scrolls page"
      }
    ]
  }
}

HTML rules:
- Include <script src="https://cdn.tailwindcss.com"></script> in head
- Include <script src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js" defer></script> for interactivity
- Build at minimum: hero, product/feature section, pricing section, one CTA flow
- Use realistic product names, copy, and pricing based on the idea
- Dark or light theme that fits the product category
- Buttons should have hover states via Tailwind
- Must be fully self-contained — no external image dependencies
- Use SVG placeholders for any images
- Minimum 200 lines of HTML

Funnel graph rules:
- Stages must only be from: ARRIVE, BROWSE, CONSIDER, DECIDE, PURCHASE, ABANDON
- Every funnel must include at least one ABANDON node
- Probabilities on edges leaving the same node must be realistic (they represent the fraction of users taking that path)
- Include 6 to 10 nodes minimum
- Edge labels should describe the user action taken

Idea:
{description}
"""

PREMORTEM_PROMPT = """
You are a world-class startup failure analyst.

A founder has described their idea below. You have their key assumptions
and simulation results. Your job is to perform a rigorous pre-mortem:
assume the product has already failed completely - work backwards and
identify the most probable root causes with surgical precision.

Return ONLY valid JSON. No markdown. No explanation. No backticks.

{
  "failure_modes": [
    {
      "title":                    "specific, concrete failure title",
      "probability":              0.72,
      "severity":                 "CRITICAL | HIGH | MEDIUM",
      "trigger_condition":        "the exact scenario that causes this failure",
      "linked_assumption_texts":  ["exact text of assumption 1", "exact text of assumption 2"],
      "intervention":             "concrete, actionable thing to do before launch",
      "intervention_impact":      "expected improvement e.g. +18% conversion survival",
      "earliest_signal":          "the first real-world indicator this failure is happening"
    }
  ]
}

Rules:
- Generate 5 to 8 failure modes. No more, no fewer.
- Probability must be a float between 0.05 and 0.95.
- Every failure mode must reference at least one assumption by its exact text.
- Interventions must be specific - never generic advice like "improve UX".
- Severity is CRITICAL if failure alone ends the business,
  HIGH if it severely damages growth, MEDIUM if it reduces efficiency.
- Sort by probability descending.
- earliest_signal must be observable within 30 days of launch.

Product description:
{description}

Key assumptions (from TheCee assumption extraction):
{assumptions_text}

Latest simulation summary:
{simulation_summary}
"""


def build_simulation_summary(simulation_results: dict | None) -> str:
    """
    Extracts the most relevant simulation metrics for the pre-mortem prompt.
    Keeps context usage low by summarising rather than dumping raw JSON.
    """
    if not simulation_results:
        return "No simulation results available - analysis based on assumptions only."

    lines: list[str] = []

    cr = simulation_results.get("mean_conversion_rate") or simulation_results.get("conversion_rate")
    if cr is not None:
        lines.append(f"Overall conversion rate: {float(cr):.1%}")

    ci = simulation_results.get("ci_95") or simulation_results.get("ci_90")
    if isinstance(ci, dict):
        lo = ci.get("low")
        hi = ci.get("high")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            lines.append(f"95% confidence interval: [{float(lo):.3f}, {float(hi):.3f}]")

    revenue = simulation_results.get("mean_revenue") or simulation_results.get("revenue_projection")
    if revenue is not None:
        lines.append(f"Projected revenue per run: INR {float(revenue):,.0f}")

    worst = simulation_results.get("worst_drop_off_stage")
    if worst:
        lines.append(f"Worst drop-off stage: {worst}")

    stages = simulation_results.get("stage_aggregations") or simulation_results.get("stage_metrics", [])
    for s in stages:
        if isinstance(s, dict) and float(s.get("mean_drop_off_rate", 0) or 0) > 0.5:
            lines.append(
                f"Stage {s.get('state', '?')}: {float(s.get('mean_drop_off_rate', 0)):.0%} drop-off"
            )

    insights = simulation_results.get("insights", [])
    if insights:
        lines.append("Simulation insights:")
        for ins in insights[:3]:
            if isinstance(ins, dict):
                lines.append(f"  [{ins.get('severity', '?')}] {str(ins.get('text', ''))[:120]}")

    return "\n".join(lines) if lines else "Simulation ran but produced no summary metrics."


INTERVENTION_PROMPT = """
You are a world-class startup growth advisor and product strategist.

A founder has an idea with known assumptions, simulation results, and
pre-mortem failure modes. Your job is to generate the most impactful,
specific, realistic interventions that can be executed within 30 days.

Return ONLY valid JSON. No markdown. No backticks. No explanation.

{
  "interventions": [
    {
      "id":                  "short-kebab-case-id",
      "title":               "Concrete, action-oriented title",
      "description":         "Exactly what to do and why - no vague advice",
      "expected_impact":     "Specific measurable outcome e.g. +18% conversion, -30% churn",
      "difficulty":          "LOW | MEDIUM | HIGH",
      "estimated_cost":      "Realistic estimate e.g. INR 12,000 or 3 days of founder time",
      "linked_assumption":   "exact text of the assumption this addresses, or null",
      "linked_failure_mode": "exact title of the failure mode this prevents, or null",
      "priority_score":      0.87,
      "time_to_implement":   "e.g. 3 days, 2 weeks",
      "success_metric":      "how to measure if this intervention worked"
    }
  ]
}

Rules:
- Generate 6 to 10 interventions. No more, no fewer.
- Sort by priority_score descending - highest leverage first.
- Priority score = (expected_impact × 0.5) + (1 - difficulty_weight × 0.3) + (speed × 0.2)
  where difficulty_weight: LOW=0.1, MEDIUM=0.5, HIGH=0.9
- Favour LOW and MEDIUM difficulty interventions unless HIGH difficulty
  is truly transformative (priority_score > 0.85).
- Every intervention must be executable without external dependencies
  or significant capital unless explicitly noted in estimated_cost.
- estimated_cost must include both money AND time.
- success_metric must be observable within 60 days of implementation.
- linked_assumption and linked_failure_mode use exact text from inputs.
  If no direct link exists use null - do not fabricate links.

Product description:
{description}

Key assumptions (sorted by impact):
{assumptions_text}

Simulation results summary:
{simulation_summary}

Pre-mortem failure modes:
{failure_modes_text}

Stress test kill shots (if any):
{kill_shots_text}
"""
