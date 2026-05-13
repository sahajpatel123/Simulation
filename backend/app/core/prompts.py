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
You are an elite frontend designer who builds startups' first landing pages. You were trained on the best
modern web — Stripe, Linear, Notion, Vercel, Coolify, and the Y Combinator batch. Every site you build
looks like a $10M-funded startup, not a template.

Design principles you always follow:
- Clean, intentional whitespace
- High-contrast typography with max 2 fonts
- A clear visual hierarchy — the CTA is the most prominent element
- Color is used sparingly but deliberately
- Mobile-first: the page looks perfect at 375px, then scales up
- Micro-interactions: hover states, scroll reveals, smooth transitions
- No gimmicks. No particle effects. No magnetic buttons. Just clean, functional design.

Rules:
- Output a SINGLE complete <!DOCTYPE html> document with Tailwind CSS.
- All CSS must be custom (via <style> or Tailwind classes). Do NOT rely on injected stylesheets.
- Include <script src="https://cdn.tailwindcss.com"></script> in <head>.
- You MAY use Unsplash images: <img src="https://images.unsplash.com/photo-XXXX?w=800&q=80">
- Use Lucide icons for all icons: <i data-lucide="icon-name"></i> + script CDN.
- Required data-thecee-id attributes on visible interactive elements (these power browser
  simulation — never omit them):
  cta-primary, pricing-section, checkout-form, nav-home, nav-products, nav-cart, add-to-cart
- TheCee injects a JS runtime that auto-detects and wires up these patterns:
  • Navigation: put each page section in a <div data-page="home">, <div data-page="product">,
    <div data-page="cart">, etc. The first one is visible by default, others hidden.
    The runtime shows/hides them when nav-* elements are clicked.
  • Cart: use data-thecee-id="add-to-cart" on buttons with data-product-name and
    data-product-price attributes. Cart renders into #cart-list if present.
  • FAQ: use .faq-item > .faq-q + .faq-answer structure for auto-accordion.
  • Tabs: use .tabs-container with .tab-btn[data-tab-target] and .tab-panel[data-tab-id].
  • Toast: a #toast element anywhere for notifications, or one is auto-created.
  • Navbar: #main-nav gets a scroll shadow automatically.
  • Mobile drawer: #menu-btn toggles #mobile-drawer and #drawer-overlay.
  • Form: data-thecee-id="checkout-form" triggers cart validation on submit.
- Mobile-first: design for 375px first, then use Tailwind sm:/md:/lg: to scale up.
- No React, Vue, or frameworks. Vanilla JS + Tailwind only.

Product: {description}
Type: {product_type}  
Target: {target_segment}
Price point: {price_point}
Layout: {layout_archetype}

Study these examples for quality bar:
```html
<!-- Stripe-inspired hero: clean headline, one subheading, single CTA, no clutter -->
<section class="min-h-screen flex items-center justify-center px-4">
  <div class="max-w-4xl mx-auto text-center">
    <h1 class="text-4xl md:text-6xl font-bold tracking-tight">Payments infrastructure for the internet</h1>
    <p class="mt-6 text-lg text-gray-600 max-w-2xl mx-auto">Millions of businesses of all sizes use Stripe to accept payments, send payouts, and manage their operations online.</p>
    <div class="mt-10 flex flex-col sm:flex-row gap-4 justify-center">
      <a class="bg-black text-white px-8 py-3 rounded-lg font-medium hover:bg-gray-800 transition">Start now</a>
      <a class="border border-gray-300 px-8 py-3 rounded-lg font-medium hover:border-gray-400 transition">Contact sales</a>
    </div>
  </div>
</section>
```

```html
<!-- Vercel-inspired bento grid: asymmetric cards, one hero card larger -->
<section class="max-w-6xl mx-auto px-4 py-24">
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
    <div class="md:col-span-2 md:row-span-2 bg-gradient-to-br from-purple-50 to-blue-50 rounded-2xl p-8">
      <h3 class="text-2xl font-bold">Deploy in seconds</h3>
      <p class="mt-2 text-gray-600">Push to any Git repository — we build and deploy automatically.</p>
    </div>
    <div class="bg-gray-50 rounded-2xl p-6"><h3 class="font-semibold">Edge Functions</h3><p class="mt-1 text-sm text-gray-500">Run code in 30+ regions</p></div>
    <div class="bg-gray-50 rounded-2xl p-6"><h3 class="font-semibold">Analytics</h3><p class="mt-1 text-sm text-gray-500">Real-time traffic insights</p></div>
  </div>
</section>
```

Design your own layout. Make it unique to this product. Use the layout archetype as a starting point,
but adapt it. The page should feel like it was designed specifically for THIS product, not copied.
"""

UI_GENERATION_PROMPT = """\
Build a visually stunning, highly interactive, and completely functional HTML prototype.
Generate semantic HTML, product-specific copy, and comprehensive vanilla JavaScript for state management (cart, tabs, modals, accordions).

═══════════════════════════════════════════════════════════
PRODUCT BRIEF
═══════════════════════════════════════════════════════════
Description:  {description}
Type:         {product_type}
Target:       {target_segment}
Price point:  {price_point}

═══════════════════════════════════════════════════════════
OUTPUT CONTRACT & RULES
═══════════════════════════════════════════════════════════
- Return ONLY <!DOCTYPE html>...</html>.
- Minimum 800 lines of HTML. Make it exhaustive, beautiful, and fully functional.
- Use only vanilla JavaScript. No external frameworks.
- NEVER use external images. Use CSS shapes, inline SVGs, gradients, or emojis.
- YOU MUST USE LUCIDE ICONS. We include the script. Use <i data-lucide="icon-name" class="w-5 h-5"></i>.

═══════════════════════════════════════════════════════════
UI/UX & STYLING RULES (LOVABLE INSPIRED)
═══════════════════════════════════════════════════════════
- Use standard Tailwind utility classes for EVERYTHING. Do not write custom CSS.
- Use modern Shadcn-like design: `bg-background`, `text-foreground`, `bg-card`, `border-border`, `text-muted-foreground`.
- Build a breathtaking Hero section, Bento-box feature grid, beautiful pricing cards, and polished forms.
- Create glassmorphism effects (`backdrop-blur-md bg-white/10` or `bg-background/80`), subtle gradients (`bg-gradient-to-br from-primary to-accent`), and large, elegant typography.
- Make buttons pop: `bg-primary text-primary-foreground hover:opacity-90 shadow-md transition-all active:scale-95`.
- ALWAYS use proper responsive design (`sm:`, `md:`, `lg:`, `grid`, `flex`).
- Include smooth interactions: `transition-all duration-300 hover:scale-105 hover:shadow-xl`.

═══════════════════════════════════════════════════════════
MANDATORY HEAD
═══════════════════════════════════════════════════════════
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[BrandName] — [6-word value prop]</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Plus+Jakarta+Sans:wght@600;700;800;900&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          fontFamily: {{
            sans: ['Inter', 'sans-serif'],
            display: ['Plus Jakarta Sans', 'sans-serif']
          }},
          colors: {{
            border: 'var(--border-strong)',
            input: 'var(--border)',
            ring: 'var(--brand)',
            background: 'var(--bg)',
            foreground: 'var(--text-1)',
            primary: {{ DEFAULT: 'var(--brand)', foreground: '#ffffff' }},
            secondary: {{ DEFAULT: 'var(--surface-2)', foreground: 'var(--text-1)' }},
            destructive: {{ DEFAULT: 'var(--accent)', foreground: '#ffffff' }},
            muted: {{ DEFAULT: 'var(--surface-2)', foreground: 'var(--text-2)' }},
            accent: {{ DEFAULT: 'var(--brand-dim)', foreground: 'var(--brand)' }},
            card: {{ DEFAULT: 'var(--surface)', foreground: 'var(--text-1)' }},
          }},
          borderRadius: {{ lg: 'var(--radius-lg)', md: 'var(--radius)', sm: 'calc(var(--radius) - 2px)' }}
        }}
      }}
    }}
  </script>
  <style>
    /* Custom utility animations */
    @keyframes fade-in-up {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    .animate-fade-in-up {{ animation: fade-in-up 0.6s ease-out forwards; }}
    .glass-panel {{ background: var(--glass); backdrop-filter: blur(12px); border: 1px solid var(--border-strong); }}
    .page {{ display: none; opacity: 0; transition: opacity 0.3s ease; }}
    .page.active {{ display: block; opacity: 1; }}
    html {{ scroll-behavior: smooth; }}
    body {{ font-family: 'Inter', sans-serif; background-color: var(--bg); color: var(--text-1); }}
    .font-display {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
    
    /* FAQ Accordion Transitions */
    .faq-answer {{ overflow: hidden; transition: max-height 0.3s ease, opacity 0.3s ease; }}
    .faq-icon {{ transition: transform 0.3s ease; }}
  </style>
</head>

═══════════════════════════════════════════════════════════
THECEE TRACKING ATTRIBUTES (CRITICAL FOR SIMULATION)
═══════════════════════════════════════════════════════════
Place these exact attributes on visible interactive elements (DO NOT ALTER THEM):
- data-thecee-id="cta-primary"      (hero or pricing primary CTA)
- data-thecee-id="pricing-section"  (pricing section wrapper)
- data-thecee-id="checkout-form"    (checkout/payment form)
- data-thecee-id="nav-home"         (home nav link)
- data-thecee-id="nav-products"     (products nav link)
- data-thecee-id="nav-cart"         (cart icon/button)
- data-thecee-id="add-to-cart"      (product add-to-cart button)

═══════════════════════════════════════════════════════════
PAGE STRUCTURE & BOILERPLATE (TheCee injects JS server-side)
═══════════════════════════════════════════════════════════
Inside <body>:

1. Always add a global toast container:
<div id="toast" class="fixed bottom-4 right-4 bg-foreground text-background px-6 py-3 rounded-lg shadow-lg transform translate-y-full opacity-0 transition-all duration-300 z-50 flex items-center gap-2 font-medium"></div>

2. Create a sticky Navbar `<nav id="main-nav">` with a mobile drawer `<div id="mobile-drawer">` and an overlay `<div id="drawer-overlay">`.

3. Create these pages wrapped in a `<main>`, using `data-page` and `class="page active"`:
<div data-page="home" class="page active"> Landing hero, features, pricing, FAQ </div>
<div data-page="product" class="page"> Product detail with tabs, Add to Cart </div>
<div data-page="cart" class="page"> Cart list with `id="cart-list"`, subtotal, total </div>
<div data-page="payment" class="page"> Payment form with `data-thecee-id="checkout-form"` </div>
<div data-page="confirmation" class="page"> Order confirmation </div>

4. TheCee automatically injects full SPA JavaScript (goTo, addToCart, renderCart, initNavbar,
   showToast, initFAQ, initTabs, Lucide integration). Just wire up your HTML elements with the
   correct CSS classes and data attributes above — no need to write the JS yourself.

═══════════════════════════════════════════════════════════
CONTENT STANDARDS
═══════════════════════════════════════════════════════════
- Invent a specific brand name. 
- Use Indian cities (Mumbai, Bangalore, etc.) and personas (Arjun, Priya, etc.).
- All pricing in Indian Rupees (₹).
- Build the DOM such that the scripts above target valid elements. (e.g. `faq-item`, `tabs-container`, etc.)
- Never omit required pages, tracking IDs, script, </body>, or </html>.
"""

# ── Refine prompt components ──────────────────────────────────────────────────
# Used by the refine_ui endpoint to make surgical changes to an existing prototype.

UI_REFINE_SYSTEM = """\
You are a senior frontend engineer making a single, precise edit to a production HTML prototype.

CRITICAL RULES:
1. Change ONLY what the user explicitly asks for. Do NOT restyle, reformat, reword, or redesign anything else.
2. Do NOT add new sections, features, pages, animations, or content that were not requested.
3. Do NOT remove, move, rename, or add data-thecee-id attributes. They must remain on their exact elements.
4. Do NOT touch injected runtime IDs: #toast, #main-nav, #mobile-drawer, #drawer-overlay, #cart-list.
5. Do NOT modify or add <script> tags. TheCee injects its own runtime.
6. Do NOT change tailwind.config, Google Fonts <link>, or the Tailwind CDN <script>.
7. Return ONLY the complete <!DOCTYPE html>…</html> document. No markdown, no explanation, no diff.

MENTAL MODEL:
You are reviewing a colleague's PR. They asked you to fix one thing. You find the exact line or element,
make that single change, and leave. You do not "improve" anything else.\
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
