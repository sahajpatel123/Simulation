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
You are an elite product designer who has shipped at Linear, Vercel, Framer, and Stripe.
Build a complete, self-contained HTML prototype that is indistinguishable from a funded product.
Your output should look like it was designed by a senior designer at a top-tier startup — not a template.

PRODUCT
Description: {description}
Type: {product_type}
Target segment: {target_segment}
Price point: {price_point}

══════════════════════════════
MANDATORY HEAD TAGS (copy these exactly — do not alter the URLs)
══════════════════════════════
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Plus+Jakarta+Sans:wght@600;700;800;900&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {{
  theme: {{ extend: {{ fontFamily: {{
    sans: ['"Inter"', 'system-ui', 'sans-serif'],
    display: ['"Plus Jakarta Sans"', '"Inter"', 'sans-serif']
  }}}}}}
}}
</script>
<script src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js" defer></script>

══════════════════════════════
DESIGN SYSTEM — write this in your <style> tag
══════════════════════════════
Choose a brand color that fits the product personality:
  SaaS / productivity → indigo or violet (#6366f1 or #8b5cf6)
  Health / wellness   → emerald or teal (#10b981 or #14b8a6)
  Finance / B2B       → blue or slate-blue (#3b82f6 or #4f6ef7)
  Consumer / D2C      → amber or rose (#f59e0b or #f43f5e)
  Developer tools     → electric green or cyan (#22c55e or #06b6d4)
  EdTech / learning   → violet or fuchsia (#a855f7 or #d946ef)

For SaaS, B2B, developer tools → use a DARK theme (bg: #08080e, cards: #111119)
For consumer, health, food, retail → use a LIGHT theme (bg: #f8f7ff, cards: #ffffff)

:root {{
  --brand: #6366f1;
  --brand-hover: #4f46e5;
  --brand-dim: rgba(99,102,241,0.12);
  --brand-glow: rgba(99,102,241,0.25);
  --bg: #08080e;
  --surface: #111119;
  --surface-2: #1a1a28;
  --border: rgba(255,255,255,0.07);
  --border-strong: rgba(255,255,255,0.14);
  --text-1: #f0f0f8;
  --text-2: #9090a8;
  --text-3: #55556a;
  --radius: 12px;
  --radius-lg: 18px;
  --radius-xl: 24px;
  --shadow: 0 4px 24px rgba(0,0,0,0.3);
  --shadow-lg: 0 24px 64px rgba(0,0,0,0.45);
  --transition: all 0.18s cubic-bezier(0.4,0,0.2,1);
}}
body {{ background:var(--bg); color:var(--text-1); font-family:'Inter',sans-serif; -webkit-font-smoothing:antialiased; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}

/* Reusable component classes */
.card {{
  background:var(--surface); border:1px solid var(--border);
  border-radius:var(--radius-lg); transition:var(--transition);
}}
.card:hover {{ transform:translateY(-3px); box-shadow:var(--shadow-lg); border-color:var(--border-strong); }}

.btn-primary {{
  display:inline-flex; align-items:center; gap:8px;
  background:var(--brand); color:#fff; padding:0.7rem 1.6rem;
  border-radius:var(--radius); font-weight:600; font-size:0.9rem;
  letter-spacing:0.01em; border:none; cursor:pointer;
  transition:var(--transition);
}}
.btn-primary:hover {{ background:var(--brand-hover); transform:translateY(-2px); box-shadow:0 8px 24px var(--brand-glow); }}
.btn-primary:active {{ transform:scale(0.97); }}

.btn-ghost {{
  display:inline-flex; align-items:center; gap:8px;
  background:transparent; border:1px solid var(--border-strong); color:var(--text-2);
  padding:0.7rem 1.6rem; border-radius:var(--radius); font-weight:500; font-size:0.9rem;
  cursor:pointer; transition:var(--transition);
}}
.btn-ghost:hover {{ background:var(--brand-dim); border-color:var(--brand); color:var(--text-1); }}

.gradient-text {{
  background:linear-gradient(135deg, var(--brand) 0%, #a78bfa 100%);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
}}

.glass {{
  background:rgba(255,255,255,0.03); backdrop-filter:blur(16px) saturate(180%);
  -webkit-backdrop-filter:blur(16px) saturate(180%);
  border:1px solid var(--border);
}}

/* Hero background blobs */
.blob {{
  position:absolute; border-radius:50%; filter:blur(90px);
  opacity:0.18; pointer-events:none; z-index:0;
}}

/* Animated gradient border for featured elements */
.gradient-border {{
  position:relative; background:var(--surface-2);
  border-radius:var(--radius-lg); padding:1px;
  background:linear-gradient(135deg, var(--brand), transparent, var(--brand));
}}
.gradient-border-inner {{ background:var(--surface); border-radius:calc(var(--radius-lg) - 1px); height:100%; }}

/* Input fields */
input, textarea, select {{
  background:var(--surface-2); border:1px solid var(--border-strong); color:var(--text-1);
  border-radius:var(--radius); padding:0.65rem 1rem; font-size:0.9rem;
  font-family:'Inter',sans-serif; transition:var(--transition); width:100%;
}}
input:focus, textarea:focus, select:focus {{
  outline:2px solid var(--brand); outline-offset:2px; border-color:var(--brand);
}}

/* Page transitions via Alpine */
[x-cloak] {{ display:none !important; }}

══════════════════════════════
ALPINE ROOT — mandatory structure
══════════════════════════════
<body x-cloak x-data="{{
  page:'home', cart:[], cartOpen:false, formSent:false,
  qty:1, tab:0, openFaq:null, plan:'monthly', navOpen:false, scrolled:false,
  addToCart(item){{this.cart.push(item);this.cartOpen=true}},
  removeFromCart(i){{this.cart.splice(i,1)}},
  init(){{window.addEventListener('scroll',()=>{{this.scrolled=window.scrollY>60}})}}
}}">

RULES — violating these breaks the prototype:
  - NEVER onclick="..." — Alpine @click ONLY
  - EVERY <button> must mutate visible Alpine state
  - EVERY <form> must have @submit.prevent="formSent=true"
  - x-transition on all page switches

══════════════════════════════
SECTIONS — build every one of these
══════════════════════════════

■ NAVBAR (sticky glass bar)
  Structure: logo | nav links | CTA button + cart icon
  Style: position:fixed; top:0; width:100%; z-index:50
         :class="scrolled ? 'glass border-b shadow-sm' : 'bg-transparent'"
         transition:background 0.3s
  Logo: <span style="font-family:'Plus Jakarta Sans',sans-serif; font-weight:900; font-size:1.3rem">
  Cart icon: show badge (x-show="cart.length>0") with count (x-text="cart.length")
  data-thecee-id: nav-home, nav-products, nav-cart
  Mobile: hamburger @click="navOpen=!navOpen" → slide-in drawer x-show="navOpen"

■ HERO (maximum visual impact — min-height:100vh)
  Background layers (in order, all position:relative/absolute, z-index controlled):
    1. Base: bg color var(--bg)
    2. Blob 1: width:600px; height:600px; background:var(--brand); top:-100px; left:-100px
    3. Blob 2: width:500px; height:500px; background:#a78bfa; bottom:-80px; right:-50px
    4. Subtle grid overlay: SVG dot-grid or CSS repeating-linear-gradient at 3% opacity

  Content (z-index:1, relative, centered):
    - Eyebrow pill: <span class="pill"> with 1px brand border, brand-dim bg, small text + "→"
      style: border:1px solid var(--border-strong); background:var(--brand-dim);
             border-radius:999px; padding:4px 14px; font-size:0.75rem; font-weight:500; color:var(--text-2)
    - Headline: font-family:'Plus Jakarta Sans',sans-serif; font-weight:900;
                font-size:clamp(2.8rem,6vw,5.2rem); letter-spacing:-0.04em; line-height:1.06
                Wrap the most impactful 2-3 words in <span class="gradient-text">
    - Sub-headline: max 18 words; color:var(--text-2); font-size:1.15rem; font-weight:400;
                    max-width:560px; line-height:1.65; margin-top:1rem
    - CTA row: btn-primary (data-thecee-id="cta-primary") + btn-ghost side by side, gap:12px
    - Stats row (margin-top:2.5rem): 3 metrics separated by ·
      Each: <strong style="font-size:1.5rem;font-weight:800;color:var(--text-1)">VALUE</strong>
            <span style="font-size:0.85rem;color:var(--text-2)">label</span>
      Use real numbers relevant to the product (users, ratings, saved time, etc.)
    - Hero visual (right side or below on mobile):
        A CSS-built mock UI card: background:var(--surface); border:1px solid var(--border);
        border-radius:var(--radius-xl); box-shadow:var(--shadow-lg); padding:1.5rem;
        containing fake UI rows (colored divs, fake buttons, mini table, fake chart bars)
        Rotate 3-6 degrees: transform:rotate(4deg)
        Floating badges around it: small pill-shaped cards with icons and short text

■ SOCIAL PROOF BAR (subtle band, padding:1.5rem 0)
  Style: border-top:1px solid var(--border); border-bottom:1px solid var(--border)
         background:linear-gradient(to right, transparent, var(--surface), transparent)
  Content: "Trusted by teams building India's next category leaders"
  + 4 company logos rendered as styled text in different font-weights and colors

■ FEATURES (bento grid — NOT boring equal columns)
  Section: padding:6rem 0; max-width:1100px; margin:0 auto
  Title + sub above grid (center-aligned)
  CSS Grid layout:
    grid-template-columns: repeat(3,1fr); gap:1.5rem
    Card A (top-left): grid-column:span 2 — large card, with a mini visualization inside
      (CSS bar chart: 4-5 colored bars of different heights inside a 160px-tall area)
    Cards B, C: standard single cards
    Card D (bottom-right): grid-column:span 2 — another wide card, different content angle
    Card E: standard single card
  Each card: class="card" padding:1.75rem
    Icon: 42px × 42px circle, background:var(--brand-dim), centered SVG or emoji, font-size:20px
    Feature name: font-family:'Plus Jakarta Sans',sans-serif; font-weight:700; font-size:1.05rem; margin-top:1rem
    Description: color:var(--text-2); font-size:0.875rem; line-height:1.65; margin-top:0.5rem

■ TESTIMONIALS (3 side-by-side cards)
  Section: padding:6rem 0
  Grid: 3 columns on desktop, 1 on mobile
  Each card: class="card" padding:1.75rem
    Top border: 4px gradient (linear-gradient(to right, var(--brand), #a78bfa))
      achieved via: border-top:none; background-image:linear-gradient(var(--surface),var(--surface)),
                   linear-gradient(to right, var(--brand), #a78bfa);
                   background-origin:border-box; background-clip:padding-box,border-box;
                   border-top:4px solid transparent;
    Stars: ★★★★★ in <span style="color:var(--brand)">
    Quote: font-style:italic; color:var(--text-2); line-height:1.7; margin:0.75rem 0 1rem
    Avatar row: 36px circle (background:linear-gradient(135deg,var(--brand),#a78bfa);
               border-radius:50%; display:flex; align-items:center; justify-content:center;
               color:#fff; font-weight:700; font-size:0.8rem) + name + role

■ PRICING (data-thecee-id="pricing-section") — 3 plans
  Toggle: Monthly / Annual pill switcher at top
    @click="plan=plan==='monthly'?'annual':'monthly'"
    :class active state shows filled bg on selected option
    x-show="plan==='annual'" badge: "Save 20%" in brand color
  3 plan cards in a row (desktop), stacked (mobile):
    Starter: class="card" padding:2rem
    Pro (featured):
      style: background:linear-gradient(135deg,var(--surface-2),var(--surface));
             border:1px solid var(--brand); border-radius:var(--radius-xl);
             transform:scale(1.04) on desktop (media query or Tailwind md:scale-105)
             position:relative (for badge)
      Badge: "Most Popular" positioned absolute top-right
             background:var(--brand); color:#fff; padding:4px 12px; border-radius:0 var(--radius-lg) 0 var(--radius)
             font-size:0.7rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase
    Scale: class="card" padding:2rem
  Each plan card has:
    - Plan name (font-weight:700, font-size:1rem, color:var(--text-2), text-transform:uppercase, letter-spacing:0.08em)
    - Price: large (font-size:3rem, font-weight:900, line-height:1) + /month small
      x-text showing monthly vs annual price (use @click toggle)
    - Feature list: ✓ in brand color + feature text; 5-7 items
    - CTA button (Pro: btn-primary with data-thecee-id="cta-primary"; others: btn-ghost)

■ FAQ SECTION (accordion, 5-7 items)
  @click="openFaq===i ? openFaq=null : openFaq=i" on each item
  :class="openFaq===i ? 'text-text-1' : 'text-text-2'" on question
  Answer: x-show="openFaq===i" with transition
  + icon: rotates 45deg when open (:style="openFaq===i?'transform:rotate(45deg)':''")
  Border-bottom between items; no border on last

■ FOOTER
  4-column grid: Brand + tagline | Product links | Company | Contact/Social
  Bottom bar: © year + privacy + terms; border-top:1px solid var(--border)

══════════════════════════════
PRODUCT PAGE (x-show="page==='product'")
══════════════════════════════
  Large product hero card (gradient bg, no real images)
  3 thumbnail cards below (change main on @click)
  Product name + badge + ★★★★★ rating + review count
  Price: ₹X,XXX, font-size:2rem, font-weight:800
  Qty selector: − qty + @click adjust
  Buttons: "Add to Cart" (data-thecee-id="add-to-cart") + "Buy Now" @click="page='payment'"
  3 trust badges: 🚚 Free delivery · ↩ 7-day returns · 🔒 Secure checkout
  Tab switcher: Description | Reviews (Alpine :class for active tab)

══════════════════════════════
CART PAGE (x-show="page==='cart'")
══════════════════════════════
  Items list with qty controls and × remove button
  Order summary card: subtotal, discount, GST (18%), total
  "Proceed to Checkout" → @click="page='payment'"

══════════════════════════════
PAYMENT PAGE (x-show="page==='payment'")
══════════════════════════════
  Form (data-thecee-id="checkout-form") @submit.prevent="formSent=true"
  Fields: full name, email, phone, address, city, pincode
  Payment method selector: Card | UPI | Cash on Delivery (Alpine tab)
    Card tab: card number, expiry, CVV (fake fields)
    UPI tab: UPI ID input field
    COD tab: confirmation message
  "Place Order" submit button
  x-show="formSent" → show success inline (no page change needed here)

══════════════════════════════
CONFIRMATION (x-show="page==='confirmation' || formSent")
══════════════════════════════
  SVG checkmark circle (green) + "Order Confirmed!" h2
  Order number (random fake), estimated delivery date
  "Continue Shopping" @click="page='home'; formSent=false; cart=[]"

══════════════════════════════
CONTENT STANDARDS
══════════════════════════════
  • Invent a SPECIFIC product brand name (not "ProductX" or "AppName") that fits the idea
  • Every copy line is benefit-specific: "Cut invoice processing from 4 hours to 8 minutes"
    NOT "Save time and increase productivity"
  • Indian context throughout: ₹ pricing, Indian names (Arjun Mehta, Priya Sharma),
    Indian cities (Mumbai, Bangalore, Delhi), Indian companies (Infosys, Zomato, Flipkart)
  • Testimonials: 3 real-sounding Indian personas with full name + job title + company
  • Stats row: impressive but plausible numbers with specific units

══════════════════════════════
PAGE TRANSITIONS (apply to all page switches)
══════════════════════════════
x-transition:enter="transition ease-out duration-200"
x-transition:enter-start="opacity-0 translate-y-2"
x-transition:enter-end="opacity-100 translate-y-0"
x-transition:leave="transition ease-in duration-150"
x-transition:leave-end="opacity-0 -translate-y-2"

══════════════════════════════
THECEE TRACKING — required, server-side validated
══════════════════════════════
On REAL visible elements (not hidden, not comments):
  data-thecee-id="cta-primary"      → primary hero CTA button
  data-thecee-id="pricing-section"  → pricing <section>
  data-thecee-id="checkout-form"    → payment <form>
  data-thecee-id="nav-home"         → home nav link
  data-thecee-id="nav-products"     → products nav link
  data-thecee-id="nav-cart"         → cart button in navbar
  data-thecee-id="add-to-cart"      → add-to-cart button(s)

══════════════════════════════
OUTPUT FORMAT
══════════════════════════════
Return ONLY <!DOCTYPE html>…</html>. Zero markdown fences. Zero prose. Zero comments outside HTML.
If running close to token budget: drop decorative copy first, NEVER drop sections or </html>.
Minimum 400 lines of HTML.
"""


# ── Refine prompt components ──────────────────────────────────────────────────
# Used by the refine_ui endpoint to make surgical changes to an existing prototype.

UI_REFINE_SYSTEM = """\
You are a senior frontend engineer making precise, surgical edits to a production HTML prototype.
The prototype uses Inter + Plus Jakarta Sans fonts, Tailwind CSS, Alpine.js, and a CSS variable design system.

Rules you must follow without exception:
1. Apply ONLY the requested change. Do not redesign sections that were not mentioned.
2. Preserve ALL CSS variables (--brand, --surface, --text-*, etc.) and their values unless the change specifically asks for a color update.
3. Keep ALL data-thecee-id attributes on their current elements. Never remove or relocate them.
4. Keep Alpine state (@click, x-show, x-data, x-transition) fully functional.
5. Keep Tailwind CDN, Alpine CDN, and Google Fonts link tags exactly as they are.
6. Return ONLY the complete updated <!DOCTYPE html>…</html> document. No markdown. No explanation.\
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
