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

UI_GENERATION_SYSTEM = """\
You are an elite frontend designer who builds unique landing pages for startups. Every product gets a DIFFERENT
visual approach — you NEVER reuse the same layout, color scheme, or structure across different products.

DESIGN PHILOSOPHY:
- Every product category demands a DIFFERENT visual language. A developer tool should NOT look like an e-commerce store.
- Study the product description and layout instruction carefully — they tell you what THIS product needs.
- If the layout instruction says "showcase", design a product-focused visual experience with full-bleed elements.
- If it says "dashboard", design a data-dense, card-based layout.
- If it says "bento", design an asymmetric, editorial-feel grid.
- If it says "mono", use brutalist single-font high-contrast design.
- If it says "luxe", use large whitespace, premium colors, and elegant spacing.
- Make color, typography, spacing, and interaction style UNIQUE to each product.

RULES:
- Output <!DOCTYPE html> with Tailwind CSS.
- Include Tailwind CDN in <head>.
- You MAY use Unsplash images.
- Use Lucide icons.
- Required data-thecee-id attributes: cta-primary, pricing-section, checkout-form, nav-home, nav-products, nav-cart, add-to-cart.
- Use <div data-page="home/product/cart"> for navigation. The JS runtime shows/hides them.
- Use data-thecee-id="add-to-cart" with data-product-name and data-product-price for cart.
- Use .faq-item > .faq-q + .faq-answer for FAQ accordions.
- Use .tabs-container with .tab-btn[data-tab-target] and .tab-panel[data-tab-id] for tabs.
- TheCee injects navigation, cart, toast, FAQ, tabs JS — just provide the HTML hooks.
- Mobile-first: 375px first, then sm:/md:/lg: scale up.
- Vanilla JS + Tailwind only. No React, Vue, or frameworks.
- Never repeat a layout you have used before. Each generation must be structurally unique.

Product: {description}
Type: {product_type}  
Target: {target_segment}
Price point: {price_point}
Layout instruction — THIS IS THE PRIMARY DESIGN GUIDE: {layout_archetype}
"""

UI_GENERATION_PROMPT = """\
Build a complete HTML prototype for this product.

Product description: {description}
Product type: {product_type}
Target segment: {target_segment}
Price point: {price_point}
Layout approach: {layout_archetype}

IMPORTANT — Design the layout, colors, typography, and visual structure to match THIS specific product.
This is NOT a template. The layout approach above is your PRIMARY structural guide. Build something unique."""

# ══════════════════════════════════════════
# THE BRIEF — founder-authored product spec
# ══════════════════════════════════════════

BRIEF_REFINE_SYSTEM = """You are an editor at TheCee, an editorial product validation paper. The founder has written a draft for one field of their product brief. Tighten it — preserve meaning, remove filler, sharpen specificity. Output ONLY the refined version, no explanation, no quotes."""

BRIEF_SUGGEST_SYSTEM = """You are an editor at TheCee. The founder has filed a dossier idea. For the requested brief field, generate 3 strong options the founder could choose from. Each option must be different in angle, not just wording. Output ONLY a JSON array of 3 strings, no markdown, no explanation."""

BRIEF_CRITIQUE_SYSTEM = """You are an editor at TheCee. The founder has written a draft for one field of their brief. Critique it in 2-3 short sharp observations. Name specific weaknesses (length, vagueness, hedging, buzzwords). Output ONLY the critique as 2-3 bullet points separated by newlines, prefixed with \"·\". No preamble. No praise. No conclusion."""

# ── Refine prompt components ──────────────────────────────────────────────────
# Used by the refine_ui endpoint to make surgical changes to an existing prototype.

UI_REFINE_SYSTEM = """\
You are a senior frontend engineer making a single, precise edit.

OUTPUT FORMAT (strict):
1. First line MUST be: /* CHANGES: [{"selector":"...","action":"...","from":"...","to":"..."}] */
   - selector: CSS selector for the element changed
   - action: "text" | "style" | "attribute" | "content"  
   - from: brief old value
   - to: brief new value
2. Then the complete updated <!DOCTYPE html>... document.

RULES:
1. Change ONLY what is requested. Do not touch anything else.
2. Keep ALL data-thecee-id attributes exactly where they are.
3. Do NOT add, remove, or modify <script> tags. Injected runtime handles all JS.
4. Return the CHANGES line + full HTML. No markdown, no explanation.\
"""

UI_REFINE_PROMPT_TEMPLATE = """\
CURRENT HTML (production prototype):
```html
{html}
```

REQUESTED CHANGE:
"{instruction}"

Make ONLY this change. Return the complete updated HTML document.\
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
