import re

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
- Include <script src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js" defer></script> for interactivity
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
Domain analysis has already identified these failure points
across 52 behavioral clusters:

{domain_findings_text}

Primary failure domain: {primary_failure_domain}
Highest-value acquisition target: {highest_value_cluster}

Cluster breakdown:
{cluster_narrative}

Build the pre-mortem around these findings. Your job is to add:
1. Second-order effects the domain analysis may have missed
2. Non-obvious failure modes from cluster interactions
3. Pre-launch vs post-launch timing of each failure

Do NOT repeat what the domain findings already state.
Add strategic reasoning on top of the structured data.

Return ONLY valid JSON. No markdown. No backticks.

{{
  "failure_modes": [
    {{
      "title": "specific, concrete failure title",
      "probability": 0.72,
      "severity": "CRITICAL | HIGH | MEDIUM",
      "trigger_condition": "the exact scenario that causes this failure",
      "linked_assumption_texts": ["cluster/architect phrase or assumption text tied to this mode"],
      "intervention": "concrete, actionable response",
      "intervention_impact": "expected improvement e.g. +18% conversion survival",
      "earliest_signal": "first observable indicator within 30 days of launch"
    }}
  ]
}}

Rules:
- Generate 5 to 8 failure modes. No more, no fewer.
- Probability must be a float between 0.05 and 0.95.
- Each failure mode must tie to the domain findings (cluster name, architect, or metric) in linked_assumption_texts or trigger_condition.
- Sort by probability descending.
"""

# Dossier Précis — Haiku deck line (short printed name from title + description).
DISPLAY_PRECIS_SYSTEM = """You sit at the copy desk of TheCee — an editorial product-validation paper, not a pitch deck factory.

INPUT HIERARCHY (never invert):
1. DOSSIER NAME — the founder’s chosen filing name; treat it as the vow printed on the spine.
2. MARGINAL NOTE — context only; use it to disambiguate what the name refers to, never to paste long clauses.

YOUR TASK:
Write the **printed deck name** that will appear on the précis slip: **one line, 3–9 words**, **sentence case**
(capitalise proper nouns and acronyms only). It must read as the **main identity** of the idea — what a reader would
remember after closing the folder.

If the name is already short and apt, polish lightly (typos, articles) but keep its soul; do not invent features
that are not implied by name + marginal note.

FORBIDDEN: quotation marks, leading colons or em dashes, hashtags, hype words
(“revolutionary”, “next-gen”, “cutting-edge”, “leverage”, “disrupt”, “solution” as a noun stack).

OUTPUT: the deck-name line only — no preamble, no explanation."""

DISPLAY_PRECIS_MARGINAL_CHAR_LIMIT = 2000


def build_display_precis_user_message(
    dossier_title: str,
    marginal_note: str,
    *,
    max_marginal_chars: int = DISPLAY_PRECIS_MARGINAL_CHAR_LIMIT,
) -> str:
    """User turn for Haiku: spine title plus truncated description for disambiguation."""
    title = (dossier_title or "").strip()
    raw = (marginal_note or "").strip()
    excerpt = raw[:max_marginal_chars] if raw else "(none supplied)"
    return (
        "DOSSIER NAME (canonical spine text):\n"
        f"{title}\n\n"
        "MARGINAL NOTE — founder’s longer submission (may be long; use only to disambiguate the name):\n"
        f"{excerpt}\n\n"
        "Write the line that will be printed on the précis slip (deck name only)."
    )


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
Highest-impact cluster: {highest_value_cluster}
Primary failure domain: {primary_failure_domain}

Cluster breakdown (from simulation):
{cluster_narrative}

Top domain findings by impact:
{ranked_findings_text}

Generate 6-10 interventions that specifically address
these identified failure points in order of impact.
Each intervention must:
- Target a specific cluster or architect domain by name
- State the expected conversion lift
- Classify as: pre-launch-required | post-launch-acceptable
- Rate effort: low (days) | medium (weeks) | high (months)

No generic advice. Every intervention must reference
a specific finding from the domain analysis above.

Return ONLY valid JSON. No markdown. No backticks.

{{
  "interventions": [
    {{
      "id": "short-kebab-case-id",
      "title": "Concrete, action-oriented title",
      "description": "What to do; include pre-launch-required OR post-launch-acceptable",
      "expected_impact": "Specific lift e.g. +12% conversion; name cluster/architect",
      "difficulty": "LOW | MEDIUM | HIGH",
      "estimated_cost": "Realistic INR + time; align effort with low/medium/high",
      "linked_assumption": "exact finding line or null",
      "linked_failure_mode": "exact pre-mortem title or null",
      "priority_score": 0.87,
      "time_to_implement": "e.g. 3 days, 2 weeks",
      "success_metric": "observable within 60 days"
    }}
  ]
}}

Rules:
- Generate 6 to 10 interventions. No more, no fewer.
- Sort by priority_score descending.
- Map effort bands: low=LOW difficulty, medium=MEDIUM, high=HIGH.
- linked_assumption should quote or paraphrase a specific domain finding line when possible.
"""


COMPETITIVE_ANALYSIS_PROMPT = """
You are a world-class competitive intelligence analyst and go-to-market
strategist with deep knowledge of the Indian startup ecosystem.

A founder has described their product idea below. Your job is to:
1. Identify the 4–6 most relevant real or likely competitors
   (Indian-first where applicable, global where dominant).
2. Perform an honest, evidence-based gap analysis.
3. Assign an overall competitive position based on the landscape.

Return ONLY valid JSON. No markdown. No backticks. No explanation.

{
  "competitors": [
    {
      "name":           "Exact company or product name",
      "category":       "DIRECT | INDIRECT | SUBSTITUTE",
      "features":       ["feature 1", "feature 2", "feature 3"],
      "pricing":        "Specific pricing e.g. freemium + INR 999/mo, INR 2,499/mo, free",
      "positioning":    "One-sentence positioning statement",
      "target_segment": "Who they primarily sell to",
      "strengths":      ["strength 1", "strength 2"],
      "weaknesses":     ["weakness 1", "weakness 2"],
      "india_presence": "STRONG | MODERATE | WEAK | NONE",
      "threat_level":   "HIGH | MEDIUM | LOW"
    }
  ],
  "gap_analysis": {
    "our_wins":                  ["specific advantage 1", "specific advantage 2"],
    "our_losses":                ["specific gap 1", "specific gap 2"],
    "underserved_segments":      ["segment or need not served by any competitor"],
    "key_differentiators":       ["what this product can own that no one else does"],
    "recommended_counter_moves": ["specific tactical action to take against competition"]
  },
  "market_map": {
    "most_dangerous_competitor": "Name",
    "easiest_to_displace":       "Name",
    "most_similar_to_us":        "Name"
  },
  "overall_competitive_position": "DOMINANT | STRONG | MODERATE | CHALLENGING | HIGH_RISK",
  "position_rationale":           "Two-sentence explanation of why this position was assigned"
}

Rules:
- Competitors must be real or highly plausible — no invented names.
- DIRECT = same problem, same customer. INDIRECT = adjacent.
  SUBSTITUTE = customer could use this instead of building a product.
- Pricing must reflect actual market rates where known.
  Use "Unknown" only if genuinely unavailable.
- gap_analysis.our_wins and our_losses must each have 3–5 items.
- recommended_counter_moves must be specific tactics, not generic advice.
- overall_competitive_position must reflect the honest landscape:
  DOMINANT = clear blue ocean or massive moat
  STRONG   = meaningful differentiation, winnable
  MODERATE = competitive but differentiation exists
  CHALLENGING = strong incumbents, hard to displace
  HIGH_RISK = commoditised, well-funded competitors, low moat

Product description:
{description}

Additional context (use if available):
Target market: {target_market}
Known assumptions: {assumptions_text}
"""

# ══════════════════════════════════════════
# STEP 54 — UI GENERATION
# ══════════════════════════════════════════

UI_GENERATION_PROMPT = """\
You are the lead frontend engineer at a $500M Series B startup. You ship production-quality HTML prototypes
that look indistinguishable from Vercel, Linear, or Stripe's marketing sites.
Build a single self-contained HTML file — three layers: semantic HTML, a full <style> block, a full <script> block.
NO Alpine.js. NO React. NO Vue. Pure vanilla JavaScript only.

═══════════════════════════════════════════════════════════
PRODUCT BRIEF
═══════════════════════════════════════════════════════════
Description:  {description}
Type:         {product_type}
Target:       {target_segment}
Price point:  {price_point}

═══════════════════════════════════════════════════════════
MANDATORY HEAD — copy exactly, do not alter any URL
═══════════════════════════════════════════════════════════
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[BrandName] — [6-word value prop]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Plus+Jakarta+Sans:wght@600;700;800;900&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{theme:{{extend:{{fontFamily:{{
      sans:['"Inter"','system-ui','sans-serif'],
      display:['"Plus Jakarta Sans"','"Inter"','sans-serif']
    }}}}}}}}
  </script>
  <style> /* FULL CSS HERE — follow DESIGN SYSTEM spec below */ </style>
</head>
<body> <!-- HTML here --> <script>/* ALL VANILLA JS here at bottom of body */</script> </body>

═══════════════════════════════════════════════════════════
DESIGN SYSTEM — write verbatim in your <style> block
═══════════════════════════════════════════════════════════

STEP 1 — Pick brand color by product type:
  SaaS / productivity   → #6366f1  (indigo)
  Health / wellness     → #10b981  (emerald)
  Finance / B2B / legal → #3b82f6  (blue)
  Consumer / D2C / food → #f59e0b  (amber)
  Developer tools       → #22c55e  (electric green)
  EdTech                → #a855f7  (violet)
  Hardware / IoT        → #0ea5e9  (sky)

STEP 2 — Pick theme:
  DARK  (SaaS, B2B, dev tools, fintech) : --bg #08080e  --surface #111119  --surface-2 #181825
  LIGHT (consumer, health, food, retail): --bg #f7f7f4  --surface #ffffff   --surface-2 #f0f0eb

STEP 3 — Write this entire block:

:root {{
  --brand:        [chosen color];
  --brand-dark:   [10% darker];
  --brand-dim:    [brand at 10% opacity — rgba(...)];
  --brand-glow:   [brand at 28% opacity — rgba(...)];
  --bg:           [theme bg];
  --surface:      [theme surface];
  --surface-2:    [theme surface-2];
  --border:       rgba(255,255,255,0.07);   /* dark theme */
  --border-strong:rgba(255,255,255,0.13);   /* light: rgba(0,0,0,0.09) and rgba(0,0,0,0.16) */
  --text-1:       #f0f0f8;   /* light: #0f0f1a */
  --text-2:       #8888a0;   /* light: #6b7280 */
  --text-3:       #52526a;   /* light: #9ca3af */
  --radius:       10px;
  --radius-lg:    16px;
  --radius-xl:    22px;
  --shadow:       0 2px 16px rgba(0,0,0,0.22);
  --shadow-lg:    0 20px 56px rgba(0,0,0,0.38);
  --ease:         cubic-bezier(0.4,0,0.2,1);
  --transition:   all 0.18s cubic-bezier(0.4,0,0.2,1);
}}

/* ── RESET ─────────────────────────────────────────────────── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{background:var(--bg);color:var(--text-1);font-family:'Inter',system-ui,sans-serif;-webkit-font-smoothing:antialiased;overflow-x:hidden}}

/* ── SCROLL PROGRESS BAR ────────────────────────────────────── */
#scroll-bar{{position:fixed;top:0;left:0;height:2px;width:0%;background:linear-gradient(to right,var(--brand),#a78bfa,#f472b6);z-index:9999;transition:width 0.08s linear;pointer-events:none}}

/* ── TYPOGRAPHY ─────────────────────────────────────────────── */
.font-display{{font-family:'Plus Jakarta Sans',sans-serif}}
.text-hero{{font-family:'Plus Jakarta Sans',sans-serif;font-weight:900;font-size:clamp(2.6rem,5.5vw,4.8rem);letter-spacing:-0.04em;line-height:1.06}}
.text-h2{{font-family:'Plus Jakarta Sans',sans-serif;font-weight:800;font-size:clamp(1.75rem,3vw,2.6rem);letter-spacing:-0.03em;line-height:1.15}}
.text-h3{{font-family:'Plus Jakarta Sans',sans-serif;font-weight:700;font-size:1.1rem;line-height:1.4}}
.text-body{{font-size:1rem;line-height:1.72;color:var(--text-2)}}
.text-sm{{font-size:0.875rem;line-height:1.65;color:var(--text-2)}}
.text-xs{{font-size:0.75rem;line-height:1.5;color:var(--text-3)}}
.overline{{font-size:0.7rem;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--text-3)}}

/* ── GRADIENT TEXT ──────────────────────────────────────────── */
.gradient-text{{background:linear-gradient(130deg,var(--brand) 0%,#a78bfa 55%,#f472b6 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}

/* ── BUTTONS ────────────────────────────────────────────────── */
.btn{{display:inline-flex;align-items:center;gap:8px;border:none;cursor:pointer;font-family:inherit;white-space:nowrap;text-decoration:none}}
.btn-primary{{background:var(--brand);color:#fff;padding:0.75rem 1.8rem;border-radius:var(--radius);font-weight:600;font-size:0.9rem;letter-spacing:0.01em;transition:var(--transition);box-shadow:0 4px 18px var(--brand-glow)}}
.btn-primary:hover{{background:var(--brand-dark);transform:translateY(-2px);box-shadow:0 8px 28px var(--brand-glow)}}
.btn-primary:active{{transform:scale(0.97)}}
.btn-ghost{{background:transparent;border:1px solid var(--border-strong);color:var(--text-2);padding:0.75rem 1.8rem;border-radius:var(--radius);font-weight:500;font-size:0.9rem;transition:var(--transition)}}
.btn-ghost:hover{{background:var(--brand-dim);border-color:var(--brand);color:var(--text-1)}}
.btn-lg{{padding:1rem 2.2rem;font-size:0.975rem;border-radius:var(--radius-lg)}}
.btn-sm{{padding:0.45rem 1rem;font-size:0.8rem}}
.btn-icon{{width:38px;height:38px;padding:0;border-radius:50%;justify-content:center;border:1px solid var(--border-strong);background:var(--surface);color:var(--text-2);transition:var(--transition)}}
.btn-icon:hover{{border-color:var(--brand);color:var(--brand);background:var(--brand-dim)}}

/* ── CARDS ──────────────────────────────────────────────────── */
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);transition:var(--transition)}}
.card:hover{{transform:translateY(-4px);box-shadow:var(--shadow-lg);border-color:var(--border-strong)}}
.card-featured{{background:linear-gradient(145deg,var(--surface-2),var(--surface));border:1px solid var(--brand);border-radius:var(--radius-xl);position:relative;overflow:hidden}}
.card-featured::before{{content:'';position:absolute;inset:0;background:radial-gradient(ellipse at 20% 20%,var(--brand-dim),transparent 65%);pointer-events:none}}

/* ── GLASS ──────────────────────────────────────────────────── */
.glass{{background:rgba(255,255,255,0.04);backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);border:1px solid var(--border-strong)}}

/* ── PILLS / BADGES ─────────────────────────────────────────── */
.pill{{display:inline-flex;align-items:center;gap:6px;background:var(--brand-dim);border:1px solid var(--brand-glow);color:var(--brand);border-radius:999px;padding:5px 14px;font-size:0.75rem;font-weight:600;letter-spacing:0.01em}}
.badge{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:0.68rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase}}
.badge-brand{{background:var(--brand);color:#fff}}
.badge-success{{background:#10b981;color:#fff}}
.badge-muted{{background:var(--surface-2);color:var(--text-2);border:1px solid var(--border-strong)}}

/* ── ANIMATED BLOBS ─────────────────────────────────────────── */
.blob{{position:absolute;border-radius:50%;filter:blur(80px);opacity:0.16;pointer-events:none;z-index:0;animation:blobDrift 12s ease-in-out infinite}}
.blob-2{{animation-delay:-6s;animation-duration:15s}}
@keyframes blobDrift{{0%,100%{{transform:translate(0,0) scale(1)}}33%{{transform:translate(30px,-20px) scale(1.05)}}66%{{transform:translate(-15px,25px) scale(0.96)}}}}

/* ── LAYOUT HELPERS ─────────────────────────────────────────── */
.section{{padding:6rem 0}}
.section-sm{{padding:3.5rem 0}}
.container{{max-width:1120px;margin:0 auto;padding:0 1.5rem}}
.grid-3{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}}
.grid-2{{display:grid;grid-template-columns:repeat(2,1fr);gap:1.5rem}}

/* ── NAVBAR ─────────────────────────────────────────────────── */
#main-nav{{position:fixed;top:0;left:0;right:0;z-index:100;padding:1.1rem 0;transition:background 0.35s ease,padding 0.3s ease,border-color 0.3s ease;border-bottom:1px solid transparent}}
#main-nav.scrolled{{background:rgba(8,8,14,0.88);backdrop-filter:blur(20px);border-color:var(--border);padding:0.7rem 0}}

/* ── MOBILE DRAWER ──────────────────────────────────────────── */
#mobile-drawer{{position:fixed;top:0;right:0;bottom:0;width:280px;background:var(--surface);border-left:1px solid var(--border);transform:translateX(100%);transition:transform 0.32s var(--ease);z-index:300;padding:4.5rem 2rem 2rem;display:flex;flex-direction:column;gap:1rem}}
#mobile-drawer.open{{transform:translateX(0)}}
#drawer-overlay{{position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:200;opacity:0;pointer-events:none;transition:opacity 0.3s}}
#drawer-overlay.open{{opacity:1;pointer-events:all}}

/* ── SCROLL REVEAL ──────────────────────────────────────────── */
.reveal{{opacity:0;transform:translateY(30px);transition:opacity 0.65s ease,transform 0.65s ease}}
.reveal.from-left{{transform:translateX(-30px)}}
.reveal.from-right{{transform:translateX(30px)}}
.reveal.scale-in{{transform:scale(0.93)}}
.reveal.visible{{opacity:1;transform:none}}
.d1{{transition-delay:0.07s}}.d2{{transition-delay:0.14s}}.d3{{transition-delay:0.21s}}.d4{{transition-delay:0.28s}}.d5{{transition-delay:0.35s}}

/* ── PAGE SYSTEM ────────────────────────────────────────────── */
.page{{display:none}}
.page.active{{display:block;animation:pageIn 0.28s ease}}
@keyframes pageIn{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}

/* ── FAQ ACCORDION ──────────────────────────────────────────── */
.faq-answer{{max-height:0;overflow:hidden;opacity:0;transition:max-height 0.42s ease,opacity 0.32s ease}}
.faq-icon{{display:inline-block;transition:transform 0.3s ease;line-height:1}}

/* ── TABS ───────────────────────────────────────────────────── */
.tab-btn{{cursor:pointer;padding:0.55rem 1.25rem;border-radius:var(--radius);font-size:0.875rem;font-weight:500;color:var(--text-2);border:1px solid transparent;transition:var(--transition)}}
.tab-btn.active{{background:var(--brand);color:#fff;box-shadow:0 4px 14px var(--brand-glow)}}
.tab-panel{{display:none}}
.tab-panel.active{{display:block;animation:pageIn 0.2s ease}}

/* ── PRICING TOGGLE ─────────────────────────────────────────── */
.plan-opt{{padding:7px 22px;border-radius:999px;cursor:pointer;font-size:0.875rem;font-weight:500;color:var(--text-2);transition:var(--transition)}}
.plan-opt.active{{background:var(--brand);color:#fff}}

/* ── TOAST ──────────────────────────────────────────────────── */
#toast{{position:fixed;bottom:1.75rem;left:50%;transform:translateX(-50%) translateY(80px);background:var(--surface-2);border:1px solid var(--border-strong);color:var(--text-1);padding:0.75rem 1.5rem;border-radius:var(--radius);font-size:0.875rem;font-weight:500;z-index:9998;transition:transform 0.38s cubic-bezier(0.34,1.56,0.64,1),opacity 0.3s ease;opacity:0;pointer-events:none;white-space:nowrap}}
#toast.show{{transform:translateX(-50%) translateY(0);opacity:1}}

/* ── FORMS ──────────────────────────────────────────────────── */
.input{{width:100%;background:var(--surface-2);border:1px solid var(--border-strong);color:var(--text-1);border-radius:var(--radius);padding:0.75rem 1rem;font-size:0.9rem;font-family:inherit;transition:var(--transition);outline:none}}
.input:focus{{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-dim)}}
.input::placeholder{{color:var(--text-3)}}
.form-label{{display:block;font-size:0.78rem;font-weight:600;color:var(--text-2);margin-bottom:6px;letter-spacing:0.03em}}

/* ── STEP DOTS ──────────────────────────────────────────────── */
.step-dot{{width:38px;height:38px;border-radius:50%;background:var(--brand);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:0.9rem;flex-shrink:0}}

/* ── ICON CIRCLE ────────────────────────────────────────────── */
.icon-circle{{width:48px;height:48px;border-radius:50%;background:var(--brand-dim);border:1px solid var(--brand-glow);display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}}

/* ── DIVIDER ────────────────────────────────────────────────── */
.divider{{height:1px;background:linear-gradient(to right,transparent,var(--border-strong),transparent)}}

/* ── COUNTER ────────────────────────────────────────────────── */
.counter{{font-variant-numeric:tabular-nums}}

/* ── RESPONSIVE ─────────────────────────────────────────────── */
@media(max-width:768px){{
  .grid-3{{grid-template-columns:1fr}}
  .grid-2{{grid-template-columns:1fr}}
  .hide-mobile{{display:none!important}}
  .section{{padding:4rem 0}}
}}

═══════════════════════════════════════════════════════════
JAVASCRIPT ARCHITECTURE — write this EXACT boilerplate in your <script>, fill in product logic
═══════════════════════════════════════════════════════════

/* ── STATE ──────────────────────────────────────────────────── */
const S = {{
  page:'home', cart:[], plan:'monthly',
  navOpen:false, openFaq:-1, activeTab:0, formSent:false, qty:1, activeThumb:0,
}};

/* ── HELPERS ────────────────────────────────────────────────── */
const $  = (s,c=document) => c.querySelector(s);
const $$ = (s,c=document) => Array.from(c.querySelectorAll(s));
const on = (el,ev,fn) => el?.addEventListener(ev,fn);

/* ── PAGE NAVIGATION ────────────────────────────────────────── */
function goTo(page){{
  $$('.page').forEach(p=>p.classList.remove('active'));
  const t=$(`[data-page="${{page}}"]`);
  if(t){{t.classList.add('active');window.scrollTo({{top:0,behavior:'smooth'}})}};
  S.page=page;
  // re-run reveal for newly shown page
  initReveal();
}}

/* ── NAVBAR ─────────────────────────────────────────────────── */
function initNavbar(){{
  const nav=$('#main-nav');
  window.addEventListener('scroll',()=>nav.classList.toggle('scrolled',scrollY>60),{{passive:true}});
  on($('#menu-btn'),'click',()=>{{
    S.navOpen=!S.navOpen;
    $('#mobile-drawer').classList.toggle('open',S.navOpen);
    $('#drawer-overlay').classList.toggle('open',S.navOpen);
  }});
  on($('#drawer-overlay'),'click',()=>{{
    S.navOpen=false;
    $('#mobile-drawer').classList.remove('open');
    $('#drawer-overlay').classList.remove('open');
  }});
}}

/* ── SCROLL PROGRESS ────────────────────────────────────────── */
function initScrollProgress(){{
  const bar=$('#scroll-bar');
  if(!bar)return;
  window.addEventListener('scroll',()=>{{
    const max=document.documentElement.scrollHeight-innerHeight;
    bar.style.width=(scrollY/max*100)+'%';
  }},{{passive:true}});
}}

/* ── SCROLL REVEAL ──────────────────────────────────────────── */
function initReveal(){{
  const obs=new IntersectionObserver((entries)=>{{
    entries.forEach((e,i)=>{{
      if(e.isIntersecting){{
        setTimeout(()=>{{
          e.target.classList.add('visible');
          const ct=e.target.dataset.countTo;
          if(ct)animateCounter(e.target,parseFloat(ct));
        }},i*75);
        obs.unobserve(e.target);
      }}
    }});
  }},{{threshold:0.1,rootMargin:'0px 0px -36px 0px'}});
  $$('.reveal').forEach(el=>obs.observe(el));
}}

/* ── ANIMATED COUNTER ───────────────────────────────────────── */
function animateCounter(el,target,dur=1600){{
  const start=performance.now();
  const isFloat=target%1!==0;
  const pfx=el.dataset.prefix||'';
  const sfx=el.dataset.suffix||'';
  const fmt=n=>n.toString().replace(/\B(?=(\d{{3}})+(?!\d))/g,',');
  (function tick(now){{
    const p=Math.min((now-start)/dur,1);
    const ease=1-Math.pow(1-p,3);
    const val=isFloat?(ease*target).toFixed(1):Math.floor(ease*target);
    el.textContent=pfx+fmt(val)+sfx;
    if(p<1)requestAnimationFrame(tick);
  }})(start);
}}

/* ── FAQ ACCORDION ──────────────────────────────────────────── */
function initFAQ(){{
  $$('.faq-item').forEach((item,i)=>{{
    on(item.querySelector('.faq-q'),'click',()=>{{
      const ans=item.querySelector('.faq-answer');
      const icon=item.querySelector('.faq-icon');
      const isOpen=S.openFaq===i;
      $$('.faq-answer').forEach(a=>{{a.style.maxHeight='0';a.style.opacity='0'}});
      $$('.faq-icon').forEach(ic=>ic.style.transform='rotate(0deg)');
      S.openFaq=isOpen?-1:i;
      if(!isOpen){{
        ans.style.maxHeight=ans.scrollHeight+'px';
        ans.style.opacity='1';
        icon.style.transform='rotate(45deg)';
      }}
    }});
  }});
}}

/* ── TABS ───────────────────────────────────────────────────── */
function initTabs(wrapperId){{
  const w=$('#'+wrapperId);if(!w)return;
  const btns=$$('.tab-btn',w);
  const panels=$$('.tab-panel',w);
  btns.forEach((btn,i)=>on(btn,'click',()=>{{
    btns.forEach(b=>b.classList.remove('active'));
    panels.forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    if(panels[i])panels[i].classList.add('active');
  }}));
  if(btns[0])btns[0].click();
}}

/* ── PRICING TOGGLE ─────────────────────────────────────────── */
function initPricing(){{
  const opts=$$('.plan-opt');
  opts.forEach(opt=>on(opt,'click',()=>{{
    S.plan=opt.dataset.plan;
    opts.forEach(o=>o.classList.toggle('active',o.dataset.plan===S.plan));
    $$('[data-price-m]').forEach(el=>{{
      el.textContent=S.plan==='monthly'?el.dataset.priceM:el.dataset.priceY;
    }});
    const badge=$('#annual-badge');
    if(badge)badge.style.display=S.plan==='annual'?'inline-block':'none';
  }}));
  if(opts[0])opts[0].click();
}}

/* ── CART ───────────────────────────────────────────────────── */
function addToCart(name,price){{
  S.cart.push({{name,price,qty:1}});
  renderCart();
  showToast(name+' added to cart ✓');
}}
function removeFromCart(i){{S.cart.splice(i,1);renderCart()}}
function renderCart(){{
  const badge=$('#cart-count');
  if(badge){{badge.textContent=S.cart.length;badge.style.display=S.cart.length?'flex':'none'}}
  const list=$('#cart-list');
  if(!list)return;
  if(S.cart.length===0){{list.innerHTML='<p class="text-sm" style="padding:2rem;text-align:center">Your cart is empty</p>';return}}
  list.innerHTML=S.cart.map((item,i)=>`
    <div style="display:flex;align-items:center;justify-content:space-between;padding:1rem 0;border-bottom:1px solid var(--border)">
      <div><div class="text-h3" style="font-size:0.95rem">${{item.name}}</div><div class="text-sm">₹${{item.price.toLocaleString()}}</div></div>
      <button class="btn btn-sm btn-ghost" onclick="removeFromCart(${{i}})">✕</button>
    </div>`).join('');
  const total=S.cart.reduce((a,b)=>a+b.price,0);
  const gst=$('#cart-gst');const tot=$('#cart-total');
  if(gst)gst.textContent='₹'+Math.round(total*0.18).toLocaleString();
  if(tot)tot.textContent='₹'+Math.round(total*1.18).toLocaleString();
}}

/* ── TOAST ──────────────────────────────────────────────────── */
function showToast(msg){{
  const t=$('#toast');if(!t)return;
  t.textContent=msg;t.classList.add('show');
  clearTimeout(t._tid);t._tid=setTimeout(()=>t.classList.remove('show'),2600);
}}

/* ── SMOOTH SCROLL ──────────────────────────────────────────── */
function initSmoothScroll(){{
  $$('[data-scroll]').forEach(el=>on(el,'click',()=>{{
    $(el.dataset.scroll)?.scrollIntoView({{behavior:'smooth',block:'start'}});
    // close mobile drawer if open
    S.navOpen=false;$('#mobile-drawer')?.classList.remove('open');$('#drawer-overlay')?.classList.remove('open');
  }}));
}}

/* ── FORM ───────────────────────────────────────────────────── */
function initForms(){{
  const form=$('[data-thecee-id="checkout-form"]');
  on(form,'submit',e=>{{e.preventDefault();S.formSent=true;goTo('confirmation')}});
}}

/* ── THUMBNAILS (product page) ──────────────────────────────── */
function selectThumb(i){{
  $$('.thumb').forEach((t,j)=>t.classList.toggle('active',j===i));
  const main=$('#product-main-img');
  if(main){{main.style.opacity='0';setTimeout(()=>main.style.opacity='1',200)}}
  S.activeThumb=i;
}}

/* ── INIT ───────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded',()=>{{
  initNavbar();
  initScrollProgress();
  initReveal();
  initFAQ();
  initPricing();
  initTabs('product-tabs');
  initSmoothScroll();
  initForms();
  goTo('home');
}});

═══════════════════════════════════════════════════════════
SECTIONS — build every one of these in order
═══════════════════════════════════════════════════════════

■ BOILERPLATE WRAPPERS
  <div id="scroll-bar"></div>
  <div id="toast"></div>
  <div id="drawer-overlay"></div>
  Wrap all page content: <div data-page="home" class="page active"> ... </div>

■ NAVBAR
  <nav id="main-nav">
    <div class="container" style="display:flex;align-items:center;justify-content:space-between">
      Logo: <a href="#" data-scroll="#hero" data-scroll> on click goTo('home')
            font-family:'Plus Jakarta Sans'; font-weight:900; font-size:1.25rem
      Center links (hide-mobile): 4-5 anchor links with data-scroll="#section-id"
            + data-thecee-id="nav-home" on first, "nav-products" on second
      Right: btn-primary "Get Started" (data-thecee-id="cta-primary" on one of these)
             + cart icon button with badge div id="cart-count"
             + hamburger #menu-btn (visible only mobile)
    </div>
  </nav>
  <div id="mobile-drawer">  ← mobile nav links + CTA inside </div>

■ HERO  (min-height:100vh, display:flex, align-items:center, position:relative, overflow:hidden)
  Background (position:absolute, inset:0):
    Blob 1: width:580px; height:580px; background:var(--brand); top:-120px; left:-80px
    Blob 2: width:480px; height:480px; background:#a78bfa; bottom:-100px; right:-60px
    Dot grid: repeating-linear-gradient at 2.5% opacity (dot every 24px)
      background-image: radial-gradient(var(--border-strong) 1px,transparent 1px);
      background-size: 24px 24px;
  Content left (max-width:600px, position:relative, z-index:1):
    — <span class="pill reveal">🚀 [Short compelling eyebrow — product milestone or launch]</span>
    — <h1 class="text-hero reveal d1"> [Headline] <span class="gradient-text">[key phrase]</span></h1>
    — <p class="text-body reveal d2" style="margin-top:1.2rem;max-width:480px"> [18-word sub-headline] </p>
    — CTA row (reveal d3): btn btn-primary btn-lg (data-thecee-id="cta-primary")  +  btn btn-ghost btn-lg
    — Stats row (reveal d4, margin-top:2.5rem):
        3 stats side by side, each:
          <strong class="counter" data-count-to="[number]" data-prefix="" data-suffix="+">0</strong>
          <span class="text-xs"> [label] </span>
        Separated by · character; use impressive product-specific numbers
  Content right (position:relative, z-index:1) — CSS mock product UI:
    A card (border-radius:var(--radius-xl); box-shadow:var(--shadow-lg); padding:1.5rem;
    transform:rotate(4deg); background:var(--surface); border:1px solid var(--border))
    Inside: fake rows, colored bar charts, mini data tables, fake buttons — simulate the actual product UI
    2–3 floating badges around the card (position:absolute, class="card", padding:8px 14px):
      each showing an icon + short status text (e.g. "✓ Invoice processed", "↑ 34% growth")

■ SOCIAL PROOF BAR  (section-sm, border top+bottom)
  style: background:linear-gradient(to right,transparent,var(--surface),transparent)
  Center text: overline "Trusted by 500+ teams building India's next generation of products"
  + .logo-track: 5 company names in styled text (different weights, colors, font-sizes)
    Use real Indian company/startup names (Razorpay, Zepto, Meesho, CRED, Groww, etc.)
    Each: class="logo-item" — font-weight:700–900, font-size:0.95–1.1rem

■ FEATURES  (section, bento grid)
  Section header (centered, reveal):
    overline label, text-h2 title, text-body subtitle (max-width:520px)
  Bento grid (grid-template-columns:repeat(3,1fr); gap:1.5rem; max-width:1100px; margin:0 auto):
    Card A  (grid-column:span 2, reveal from-left): class="card" padding:2rem
      Icon circle + text-h3 title + text-sm description
      Mini visualization: a div of 5 colored bars (different heights, gap:4px, border-radius:4px, height:120px)
      Each bar: background:linear-gradient(to top,var(--brand),var(--brand-dim)); border-radius:4px;
    Card B  (reveal d1): standard card, icon circle + title + description
    Card C  (reveal d2): standard card, icon circle + title + description
    Card D  (grid-column:span 2, reveal from-right): class="card" padding:2rem — different visual angle
      Contains a mini table or checklist (3 rows) to illustrate the feature
    Card E  (reveal d1): standard card, icon circle + title + description
  All cards get class="reveal" + appropriate delay class

■ HOW IT WORKS  (section, 3-step horizontal or vertical flow)
  Section header: overline, text-h2, text-body subtitle
  Steps: 3 items in a row (desktop) / stacked (mobile)
    Each step (reveal + delay):
      — <div class="step-dot">[N]</div>
      — text-h3 step title
      — text-sm explanation (2 sentences max, benefit-focused)
      — small CSS illustration or icon that represents the step visually
    Between step 1 and 2, step 2 and 3: dashed line (border-top:2px dashed var(--border-strong))
    on desktop use ::before pseudo or a connecting div

■ TESTIMONIALS  (section, 3 cards in a row)
  Section header: overline, text-h2
  3 cards (grid-3, each reveal + d1/d2/d3):
    Top border trick (4px gradient):
      border-top: 4px solid transparent;
      background-image: linear-gradient(var(--surface),var(--surface)),
                        linear-gradient(to right,var(--brand),#a78bfa);
      background-origin: border-box; background-clip: padding-box,border-box;
    Content: ★★★★★ (color:var(--brand)) | italic quote | avatar row
    Avatar: 36px circle (background:linear-gradient(135deg,var(--brand),#a78bfa);
            color:#fff; font-weight:700; initials) + name + role/company
    Use Indian names: Arjun Mehta, Priya Sharma, Vikram Nair, Anjali Singh, Rohit Gupta, etc.
    Company: real Indian startups (Razorpay, Meesho, Zepto, CRED, etc.)

■ PRICING  (section, id="pricing-section", data-thecee-id="pricing-section")
  Section header + toggle switcher:
    Toggle: <div> with two <span class="plan-opt" data-plan="monthly">Monthly</span>
            and <span class="plan-opt" data-plan="annual">Annual</span> inside a
            pill container (background:var(--surface-2); border-radius:999px; padding:4px)
    + <span id="annual-badge" class="badge badge-brand" style="display:none">Save 20%</span>
  3 plan cards in a row (desktop):
    Plan 1 — Starter: class="card" padding:2rem
    Plan 2 — Pro (featured): class="card-featured" padding:2rem; position:relative
      "Most Popular" badge: position:absolute; top:0; right:0;
      background:var(--brand); color:#fff; padding:4px 14px;
      border-radius:0 var(--radius-xl) 0 var(--radius); font-size:0.68rem; font-weight:700;
      letter-spacing:0.06em; text-transform:uppercase
    Plan 3 — Scale: class="card" padding:2rem
  Each card:
    overline plan name | price: <span class="text-hero counter" style="font-size:3rem"
      data-price-m="₹[X]" data-price-y="₹[Y]">₹[X]</span>/mo
    Feature list (5–7 lines): each row:
      <div style="display:flex;align-items:flex-start;gap:10px;margin-top:0.75rem">
        <span style="color:var(--brand);font-size:0.9rem;margin-top:2px">✓</span>
        <span class="text-sm">[feature]</span>
      </div>
    CTA: Pro → btn btn-primary btn-lg (data-thecee-id="cta-primary"); others → btn btn-ghost btn-lg

■ FAQ  (section, max-width:720px; margin:0 auto)
  Section header: overline, text-h2
  5–7 items, each div class="faq-item":
    <button class="faq-q" style="width:100%;display:flex;justify-content:space-between;
    align-items:center;padding:1.25rem 0;background:none;border:none;border-bottom:
    1px solid var(--border);cursor:pointer;color:var(--text-1);font-weight:600;
    font-size:0.95rem;text-align:left">
      [Question] <span class="faq-icon" style="font-size:1.4rem;color:var(--text-3)">+</span>
    </button>
    <div class="faq-answer" style="padding:0 0">
      <p class="text-body" style="padding:1rem 0 1.5rem">[Answer — 2–3 sentences]</p>
    </div>

■ CTA BANNER  (section-sm, before footer)
  Full-width section (background:linear-gradient(135deg,var(--brand-dim),var(--surface-2));
  border:1px solid var(--border-strong); border-radius:var(--radius-xl); margin:0 1.5rem)
  Center: text-h2 headline + text-body sub + 2 CTAs (btn-primary + btn-ghost) + small trust copy
  position:relative; overflow:hidden — add 2 small blobs for texture

■ FOOTER  (section-sm, border-top:1px solid var(--border))
  4-column grid (desktop), 2-column (mobile):
    Col 1: Logo + 1-sentence brand description + social icon buttons (btn-icon × 3)
    Col 2: Product links (5 items)
    Col 3: Company links (4 items)
    Col 4: Contact info + "Built with ❤️ in India"
  Bottom bar: divider + flex row: "© 2025 [Brand]. All rights reserved." + Privacy + Terms

══════════════════════════════════════════════════
ADDITIONAL PAGES (linked from navbar, toggled via goTo())
══════════════════════════════════════════════════

■ PRODUCT PAGE  (data-page="product", data-thecee-id="nav-products")
  Large hero card (background:linear-gradient(135deg,var(--brand-dim),var(--surface-2));
  height:360px; border-radius:var(--radius-xl); display:flex; align-items:center; justify-content:center)
    id="product-main-img" — contains a large centered icon/SVG + product name
    transition:opacity 0.2s on swaps
  3 thumbnail cards below (onclick calls selectThumb(i)):
    class="thumb card" style="cursor:pointer;padding:1rem;transition:var(--transition)"
    .thumb.active style: border-color:var(--brand)
  Product name (text-h2) + badge + ★★★★★ (color:#fbbf24) + "(4.8 · 2,341 reviews)"
  Price: <span style="font-size:2.2rem;font-weight:900">₹X,XXX</span>
         <span class="badge badge-success">In Stock</span>
  Qty: − / qty value / + buttons (onclick adjust S.qty, update display)
  Buttons: "Add to Cart" (data-thecee-id="add-to-cart", onclick addToCart(name,price))
           "Buy Now" (onclick → addToCart then goTo('cart'))
  Trust row: 🚚 Free delivery above ₹499 · ↩ 7-day returns · 🔒 Secure checkout
  Tab switcher (id="product-tabs"): Description | Specifications | Reviews
    Each tab-panel has appropriate content

■ CART PAGE  (data-page="cart")
  <div id="cart-list"></div>  ← rendered by renderCart()
  Order summary card:
    Subtotal, Discount (SAVE10 = 10%), GST 18%, Total
    "Proceed to Checkout" → onclick goTo('payment')

■ PAYMENT PAGE  (data-page="payment")
  <form data-thecee-id="checkout-form">
    Fields: Full Name, Email, Phone, Address, City, Pincode (class="input" on all)
    Payment tabs (id="payment-tabs"): Card | UPI | Cash on Delivery
      Card: Card number, Expiry, CVV
      UPI: UPI ID input + Pay button
      COD: confirmation message
    "Place Order" submit button (btn btn-primary btn-lg full-width)
  </form>

■ CONFIRMATION  (data-page="confirmation")
  SVG checkmark circle (stroke:var(--brand); strokeWidth:2.5; animated stroke-dashoffset)
  "Order Confirmed!" text-h2
  Order number (random 8-digit fake), expected delivery date (3 days from today placeholder)
  "Continue Shopping" onclick goTo('home') btn-ghost

══════════════════════════════════════════════════
CONTENT & COPY STANDARDS
══════════════════════════════════════════════════
  ■ Invent a specific brand name that fits the product (NOT "ProductX", "AppName", "YourBrand")
  ■ Every headline is benefit-specific:
    GOOD: "Cut invoice processing from 4 hours to 8 minutes"
    BAD:  "Save time and increase productivity"
  ■ All pricing in ₹ (Indian Rupees) — realistic for the product type and price_point
  ■ Indian personas: Arjun Mehta · Priya Sharma · Vikram Nair · Anjali Desai · Rohit Gupta
  ■ Indian cities: Mumbai · Bangalore · Delhi · Hyderabad · Pune · Chennai
  ■ Indian companies/startups in logos: Razorpay · Zepto · Meesho · CRED · Groww · boAt · Ola
  ■ Stats must be specific and plausible: "2,847 invoices processed today" not "10k users"
  ■ FAQ answers: 2–3 sentences, specific, reassuring, no corporate speak

══════════════════════════════════════════════════
THECEE TRACKING — server-validated, must be on visible elements
══════════════════════════════════════════════════
  data-thecee-id="cta-primary"      → hero/pricing primary CTA button
  data-thecee-id="pricing-section"  → <section> wrapping pricing
  data-thecee-id="checkout-form"    → payment <form>
  data-thecee-id="nav-home"         → home nav link
  data-thecee-id="nav-products"     → products nav link
  data-thecee-id="nav-cart"         → cart icon button
  data-thecee-id="add-to-cart"      → add-to-cart button

══════════════════════════════════════════════════
OUTPUT FORMAT
══════════════════════════════════════════════════
Return ONLY <!DOCTYPE html>…</html>.
Zero markdown fences. Zero prose. Zero HTML comments.
If nearing token budget: shorten copy first, NEVER truncate sections or omit </html>.
Minimum output: 500 lines of HTML.
"""


# ── Refine prompt components ──────────────────────────────────────────────────
# Used by the refine_ui endpoint to make surgical changes to an existing prototype.

UI_REFINE_SYSTEM = """\
You are a senior frontend engineer making precise, surgical edits to a production HTML prototype.
The prototype uses Inter + Plus Jakarta Sans (Google Fonts), Tailwind CSS CDN, a CSS variable design
system, and vanilla JavaScript (no Alpine, no React, no framework).

Rules — violating any of these breaks the prototype:
1. Apply ONLY the requested change. Do not restyle, rename, or restructure anything not mentioned.
2. Preserve ALL :root CSS variables (--brand, --surface, --text-*, --radius, etc.) exactly.
3. Keep ALL data-thecee-id attributes on their current elements. Never move or remove them.
4. Keep ALL vanilla JS intact — the S state object, all init* functions, goTo(), renderCart(),
   showToast(), animateCounter(), IntersectionObserver reveal logic. Do not touch working JS.
5. Keep the Tailwind CDN <script>, tailwind.config block, and Google Fonts <link> tags unchanged.
6. Keep #scroll-bar, #toast, #drawer-overlay, #main-nav, #mobile-drawer elements present.
7. Return ONLY the complete updated <!DOCTYPE html>…</html> document. No markdown. No explanation.\
"""

UI_REFINE_PROMPT_TEMPLATE = """\
CURRENT HTML:
{html}

CHANGE REQUEST:
{instruction}

Return the complete updated HTML document starting with <!DOCTYPE html>.\
"""

# ══════════════════════════════════════════
# STEP 70 — HARDWARE SEMANTIC 3D SPEC (JSON)
# ══════════════════════════════════════════
# Locked schema consumed by Steps 72 (viewer), 75 (physics), 77 (failure overlay),
# 78 (cost). No mesh generation — structured spec only.

HARDWARE_SPEC_PROMPT = """\
You are a senior mechanical / hardware product engineer and DFM specialist.

The founder is NOT asking for 3D mesh files, GLB, or CAD exports. Generate a single
semantic hardware specification JSON that acts as the canonical "3D model" for this
product: envelope dimensions, material zones, assembly components, stress topology,
and failure thinking. This JSON will drive physics tests and a simple grid viewer.

Rules:
- Return ONLY valid JSON. No markdown. No backticks. No commentary before or after.
- Be physically plausible for the category and target price (INR).
- Use 2–8 components; each needs a stable string `id` (snake_case) referenced by stress_point_map.
- `material` on each component must be a short machine key in UPPER_SNAKE_CASE
  (e.g. ABS_SHELL, ALUMINUM_6061, POLYCARBONATE_LENS, SILICONE_GASKET, LITHIUM_CELL,
  PCB_FR4, STAINLESS_304, TPU_GRIP) so a material database can resolve properties later.
- `stress_rating` on each component is 0.0–1.0 (higher = more structural load / risk).
- `stress_point_map` entries link `component_id` to existing component `id` values.
- `render_hints` are symbolic only (no GPU); they guide a primitive 3D grid viewer.

Return a JSON object with EXACTLY this structure and key names (types as shown):

{{
  "product_name": "string",
  "category": "string",
  "dimensions": {{
    "length_mm": 0.0,
    "width_mm": 0.0,
    "height_mm": 0.0,
    "weight_grams": 0.0
  }},
  "components": [
    {{
      "id": "string",
      "name": "string",
      "material": "string",
      "zone": "top|bottom|left|right|core|shell",
      "volume_cm3": 0.0,
      "stress_rating": 0.0
    }}
  ],
  "stress_point_map": [
    {{ "component_id": "string", "stress_type": "string", "severity": 0.0 }}
  ],
  "render_hints": {{
    "primary_shape": "box|cylinder|L-shape|flat",
    "dominant_material": "string",
    "color_hex": "#RRGGBB",
    "highlight_zones": ["component_id", "..."]
  }},
  "known_failure_modes": ["string", "..."],
  "assembly_complexity": "simple|moderate|complex"
}}

Product description:
{description}

Category:
{category}

Target price (INR):
{price}
"""

# Step 71 — refine existing semantic spec (JSON appended in code; no .format on spec body).
HARDWARE_SPEC_REFINE_HEAD = """\
You are a senior mechanical / hardware product engineer and DFM specialist.

Revise the semantic hardware specification JSON shown below. Return ONLY valid JSON
with the EXACT same top-level keys and nested structure as the Step 70 hardware spec:
product_name, category, dimensions, components, stress_point_map, render_hints,
known_failure_modes, assembly_complexity.

Rules:
- No markdown, no backticks, no commentary outside the JSON object.
- Preserve stable component `id` values where the same physical part remains; rename or
  add/remove components if the refinement requires it. stress_point_map must reference
  valid component ids from the revised `components` list.
- Stay physically plausible for the category and target envelope.

--- EXISTING SPEC JSON ---
"""

HARDWARE_SPEC_REFINE_TAIL = """
--- REFINEMENT REQUEST ---
{refinement_prompt}

Return ONLY the complete revised JSON object.
"""


_REQUIRED_TRACKING_IDS = ("cta-primary", "pricing-section", "checkout-form")


def _has_tracking_id(html: str, tid: str) -> bool:
    return bool(re.search(rf'data-thecee-id\s*=\s*["\']{re.escape(tid)}["\']', html, re.IGNORECASE))


def validate_generated_html(html: str) -> tuple[bool, str]:
    if not html or len(html.strip()) < 500:
        return False, "HTML too short or empty"
    h = html.lower()
    if "<html" not in h or "</html>" not in h:
        return False, "Missing HTML structure"
    if "tailwindcss" not in h:
        return False, "Missing Tailwind CDN"
    if "alpinejs" not in h:
        return False, "Missing Alpine.js CDN"
    if "<button" not in h:
        return False, "Missing button"
    missing = [tid for tid in _REQUIRED_TRACKING_IDS if not _has_tracking_id(html, tid)]
    if missing:
        return False, f"Missing tracking attributes: {missing}"
    if len(html.split()) < 200:
        return False, "Insufficient content — HTML too sparse"
    return True, "OK"


# Step 70 — hardware semantic spec (locked schema; see HARDWARE_SPEC_PROMPT)
_REQUIRED_HW_SPEC_KEYS = frozenset({
    "product_name",
    "category",
    "dimensions",
    "components",
    "stress_point_map",
    "render_hints",
    "known_failure_modes",
    "assembly_complexity",
})
_REQUIRED_COMPONENT_FIELDS = frozenset(
    {"id", "name", "material", "zone", "volume_cm3", "stress_rating"}
)
_VALID_ZONES = frozenset({"top", "bottom", "left", "right", "core", "shell"})
_VALID_SHAPES = frozenset({"box", "cylinder", "L-shape", "flat"})
_VALID_ASSEMBLY = frozenset({"simple", "moderate", "complex"})
_RENDER_HINT_REQUIRED = frozenset(
    {"primary_shape", "dominant_material", "color_hex", "highlight_zones"}
)


def validate_hardware_spec(spec: dict) -> tuple[bool, str]:
    """
    Validate semantic hardware spec JSON after Claude generation (before DB save).
    Mirrors validate_generated_html for the hardware pipeline.
    """
    if not isinstance(spec, dict):
        return False, "Spec must be a JSON object (dict)"

    missing = sorted(_REQUIRED_HW_SPEC_KEYS - spec.keys())
    if missing:
        return False, f"Missing required keys: {', '.join(missing)}"

    dims = spec.get("dimensions")
    if not isinstance(dims, dict):
        return False, "dimensions must be an object"
    for dk in ("length_mm", "width_mm", "height_mm", "weight_grams"):
        if dk not in dims:
            return False, f"dimensions missing key: {dk}"
        if not isinstance(dims[dk], (int, float)):
            return False, f"dimensions.{dk} must be a number"

    components = spec.get("components")
    if not isinstance(components, list):
        return False, "components must be a list"
    if len(components) < 2:
        return False, "components must have at least 2 items"

    comp_ids: set[str] = set()
    for i, c in enumerate(components):
        if not isinstance(c, dict):
            return False, f"components[{i}] must be an object"
        cf = _REQUIRED_COMPONENT_FIELDS - c.keys()
        if cf:
            return False, f"components[{i}] missing keys: {', '.join(sorted(cf))}"
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            return False, f"components[{i}].id must be a non-empty string"
        if cid in comp_ids:
            return False, f"duplicate component id: {cid}"
        comp_ids.add(cid)
        zone = c.get("zone")
        if zone not in _VALID_ZONES:
            return False, f"components[{i}].zone invalid: {zone!r}"
        sr = c.get("stress_rating")
        if not isinstance(sr, (int, float)) or not (0.0 <= float(sr) <= 1.0):
            return False, f"components[{i}].stress_rating must be a number in [0, 1]"
        vol = c.get("volume_cm3")
        if not isinstance(vol, (int, float)) or float(vol) < 0:
            return False, f"components[{i}].volume_cm3 must be a non-negative number"

    spm = spec.get("stress_point_map")
    if not isinstance(spm, list):
        return False, "stress_point_map must be a list"
    for j, entry in enumerate(spm):
        if not isinstance(entry, dict):
            return False, f"stress_point_map[{j}] must be an object"
        for ek in ("component_id", "stress_type", "severity"):
            if ek not in entry:
                return False, f"stress_point_map[{j}] missing key: {ek}"
        ref = entry.get("component_id")
        if ref not in comp_ids:
            return False, f"stress_point_map[{j}].component_id not found in components: {ref!r}"
        if not isinstance(entry.get("stress_type"), str) or not str(entry["stress_type"]).strip():
            return False, f"stress_point_map[{j}].stress_type must be a non-empty string"
        sev = entry.get("severity")
        if not isinstance(sev, (int, float)) or not (0.0 <= float(sev) <= 1.0):
            return False, f"stress_point_map[{j}].severity must be a number in [0, 1]"

    rh = spec.get("render_hints")
    if not isinstance(rh, dict):
        return False, "render_hints must be an object"
    mh = _RENDER_HINT_REQUIRED - rh.keys()
    if mh:
        return False, f"render_hints missing keys: {', '.join(sorted(mh))}"
    ps = rh.get("primary_shape")
    if ps not in _VALID_SHAPES:
        return False, f"render_hints.primary_shape invalid: {ps!r}"
    ch = rh.get("color_hex")
    if not isinstance(ch, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", ch.strip()):
        return False, "render_hints.color_hex must be #RRGGBB (six hex digits)"
    dm = rh.get("dominant_material")
    if not isinstance(dm, str) or not dm.strip():
        return False, "render_hints.dominant_material must be a non-empty string"
    hz = rh.get("highlight_zones")
    if not isinstance(hz, list):
        return False, "render_hints.highlight_zones must be a list of component ids"
    for z in hz:
        if z not in comp_ids:
            return False, f"render_hints.highlight_zones references unknown id: {z!r}"

    kfm = spec.get("known_failure_modes")
    if not isinstance(kfm, list) or len(kfm) == 0:
        return False, "known_failure_modes must be a non-empty list of strings"
    for k, item in enumerate(kfm):
        if not isinstance(item, str) or not item.strip():
            return False, f"known_failure_modes[{k}] must be a non-empty string"

    ac = spec.get("assembly_complexity")
    if ac not in _VALID_ASSEMBLY:
        return False, f"assembly_complexity invalid: {ac!r}"

    # Step 73 — normalise Claude / alias material strings to canonical DB keys (in-place).
    from app.hardware.materials import resolve_material_name

    for c in components:
        if isinstance(c.get("material"), str):
            c["material"] = resolve_material_name(c["material"])
    if isinstance(rh.get("dominant_material"), str):
        rh["dominant_material"] = resolve_material_name(rh["dominant_material"])

    return True, "OK"
