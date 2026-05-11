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
You are a senior frontend engineer building a production-quality startup prototype.
Return only a complete <!DOCTYPE html>...</html> document. No markdown, no prose, no comments.
CSS is pre-loaded by TheCee before the prototype is served. Do not recreate a design system.
Use the listed class names and write only small component-specific CSS additions when unavoidable.
Your main job is semantic HTML structure, product-specific Indian copy, and full vanilla JavaScript.
No Alpine.js, React, Vue, external images, or framework code. Vanilla JavaScript only.
Keep all required data-thecee-id attributes on visible interactive elements.
Do not omit closing </body> or </html> tags.
"""

UI_GENERATION_PROMPT = """\
Build a polished self-contained HTML prototype using TheCee's pre-loaded CSS template.
Generate semantic HTML, product-specific copy, and full vanilla JavaScript. Keep CSS minimal.

═══════════════════════════════════════════════════════════
PRODUCT BRIEF
═══════════════════════════════════════════════════════════
Description:  {description}
Type:         {product_type}
Target:       {target_segment}
Price point:  {price_point}

═══════════════════════════════════════════════════════════
OUTPUT CONTRACT
═══════════════════════════════════════════════════════════
- Return ONLY <!DOCTYPE html>...</html>.
- No markdown fences, explanation, or HTML comments.
- Minimum 400 lines of HTML.
- Include complete <head>, <body>, and one bottom <script> block.
- CSS template classes already exist. Do not write a large CSS system.
- Use only vanilla JavaScript. Do not include Alpine.js.
- No external image dependencies. Use CSS mockups, inline SVG, emoji, gradients, and cards.

═══════════════════════════════════════════════════════════
MANDATORY HEAD
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
      sans:['Inter','system-ui','sans-serif'],
      display:['Plus Jakarta Sans','Inter','sans-serif']
    }}}}}}}}
  </script>
  <style>
    /* Optional tiny component-specific additions only. Do not recreate base CSS. */
  </style>
</head>

═══════════════════════════════════════════════════════════
AVAILABLE CSS CLASSES
═══════════════════════════════════════════════════════════
Typography:
.font-display .text-hero .text-h2 .text-h3 .text-body .text-sm .text-xs .overline .gradient-text

Buttons:
.btn .btn-primary .btn-ghost .btn-lg .btn-sm .btn-icon

Cards and surfaces:
.card .card-featured .glass .pill .badge .badge-brand .badge-success .badge-muted

Motion and layout:
.blob .blob-2 .reveal .from-left .from-right .scale-in .visible .d1 .d2 .d3 .d4 .d5
.page .active .section .section-sm .container .grid-2 .grid-3 .hide-mobile

Interaction components:
.faq-item .faq-q .faq-answer .faq-icon .tab-btn .tab-panel .plan-opt .input .form-label

Utilities:
.step-dot .icon-circle .divider .counter .stars .logo-track .logo-item .thumb .hero-grid

Required IDs:
#scroll-bar #toast #drawer-overlay #main-nav #mobile-drawer #menu-btn #cart-count #cart-list
#cart-gst #cart-total #annual-badge #product-tabs #payment-tabs #product-main-img

═══════════════════════════════════════════════════════════
THECEE TRACKING ATTRIBUTES
═══════════════════════════════════════════════════════════
Place these on visible elements:
- data-thecee-id="cta-primary"      hero or pricing primary CTA
- data-thecee-id="pricing-section"  pricing section wrapper
- data-thecee-id="checkout-form"    checkout/payment form
- data-thecee-id="nav-home"         home nav link
- data-thecee-id="nav-products"     products nav link
- data-thecee-id="nav-cart"         cart icon/button
- data-thecee-id="add-to-cart"      product add-to-cart button

═══════════════════════════════════════════════════════════
PAGE STRUCTURE
═══════════════════════════════════════════════════════════
Always create these wrappers first inside <body>:
<div id="scroll-bar"></div>
<div id="toast"></div>
<div id="drawer-overlay"></div>

Create these pages:
1. <div data-page="home" class="page active"> landing page content </div>
2. <div data-page="product" class="page"> product detail page </div>
3. <div data-page="cart" class="page"> cart page </div>
4. <div data-page="payment" class="page"> payment form </div>
5. <div data-page="confirmation" class="page"> order confirmation </div>

═══════════════════════════════════════════════════════════
HOME PAGE SECTIONS
═══════════════════════════════════════════════════════════
NAVBAR:
- Fixed <nav id="main-nav"> with logo, 4 links, CTA, cart button, mobile menu button.
- First link has data-thecee-id="nav-home" and calls goTo('home').
- Product link has data-thecee-id="nav-products" and calls goTo('product').
- Cart button has data-thecee-id="nav-cart" and calls goTo('cart').
- Include <div id="mobile-drawer"> with mobile links and CTA.

HERO:
- Full viewport section with .container and .grid-2.
- Add two absolute .blob elements and a subtle .hero-grid background.
- Left: .pill, .text-hero headline with .gradient-text phrase, .text-body subheadline, two CTAs.
- Primary CTA must have data-thecee-id="cta-primary".
- Add 3 animated stats using .counter and data-count-to.
- Right: realistic CSS product mockup card with rows, charts, status pills, fake UI details.

SOCIAL PROOF:
- .section-sm with overline and .logo-track of five real/plausible Indian startup names.

FEATURES:
- .section with centered header, bento-like .grid-3 cards.
- At least five feature cards using .card, .icon-circle, .text-h3, .text-sm, .reveal.
- Include one visual card with bars/table/checklist based on the product.

HOW IT WORKS:
- Three step flow using .step-dot and connecting dividers.
- Explain the user's first successful journey through the product.

TESTIMONIALS:
- Three .card testimonials with .stars, Indian names, roles, and specific measurable quotes.

PRICING:
- <section id="pricing-section" data-thecee-id="pricing-section">.
- Include monthly/annual toggle with .plan-opt and #annual-badge.
- Three plans: Starter, Pro, Scale. Pro uses .card-featured.
- Use ₹ pricing that matches the product and price point.
- Use data-price-m and data-price-y for all price spans.

FAQ:
- Five to seven .faq-item blocks with .faq-q button, .faq-answer, .faq-icon.
- Answers must be specific and reassuring, not generic.

CTA BANNER AND FOOTER:
- Final conversion banner with CTA buttons.
- Footer with four columns and India-specific contact/trust copy.

═══════════════════════════════════════════════════════════
PRODUCT / CART / PAYMENT PAGES
═══════════════════════════════════════════════════════════
PRODUCT PAGE:
- Large hero product card with id="product-main-img".
- Three .thumb cards calling selectThumb(i).
- Product title, badge, .stars rating, price, quantity controls.
- Add-to-cart button with data-thecee-id="add-to-cart" calling addToCart(name, price).
- Buy-now button calls addToCart(...) then goTo('cart').
- Tabs in #product-tabs: Description, Specifications, Reviews.

CART PAGE:
- <div id="cart-list"></div> rendered by JS.
- Order summary with subtotal, discount, GST 18%, total.
- Checkout button calls goTo('payment').

PAYMENT PAGE:
- <form data-thecee-id="checkout-form"> with name, email, phone, address, city, pincode.
- Inputs use .input and labels use .form-label.
- Payment tabs in #payment-tabs: Card, UPI, Cash on Delivery.
- Submit button places order and calls goTo('confirmation').

CONFIRMATION PAGE:
- Success checkmark, order number, delivery expectation, Continue Shopping button.

═══════════════════════════════════════════════════════════
CONTENT STANDARDS
═══════════════════════════════════════════════════════════
- Invent a specific brand name. Never use ProductX, AppName, YourBrand, or placeholders.
- Every headline must be benefit-specific and measurable when possible.
- All pricing in Indian Rupees.
- Use Indian cities: Mumbai, Bangalore, Delhi, Hyderabad, Pune, Chennai.
- Use Indian personas: Arjun Mehta, Priya Sharma, Vikram Nair, Anjali Desai, Rohit Gupta.
- Use Indian startup references where useful: Razorpay, Zepto, Meesho, CRED, Groww, boAt, Ola.
- Stats must be plausible and specific, not vague vanity metrics.
- Make product copy match the product_type and description exactly.

═══════════════════════════════════════════════════════════
JAVASCRIPT BOILERPLATE
═══════════════════════════════════════════════════════════
Write a complete bottom-of-body <script> with this architecture and product-specific calls:

const S = {{
  page:'home', cart:[], plan:'monthly', navOpen:false,
  openFaq:-1, activeTab:0, formSent:false, qty:1, activeThumb:0
}};

const $ = (s,c=document) => c.querySelector(s);
const $$ = (s,c=document) => Array.from(c.querySelectorAll(s));
const on = (el,ev,fn) => el?.addEventListener(ev,fn);

function goTo(page) {{
  $$('.page').forEach(p => p.classList.remove('active'));
  const target = $(`[data-page="${{page}}"]`);
  if (target) {{ target.classList.add('active'); window.scrollTo({{top:0, behavior:'smooth'}}); }}
  S.page = page;
  initReveal();
}}

function initNavbar() {{
  const nav = $('#main-nav');
  window.addEventListener('scroll', () => nav?.classList.toggle('scrolled', scrollY > 60), {{passive:true}});
  on($('#menu-btn'), 'click', () => {{
    S.navOpen = !S.navOpen;
    $('#mobile-drawer')?.classList.toggle('open', S.navOpen);
    $('#drawer-overlay')?.classList.toggle('open', S.navOpen);
  }});
  on($('#drawer-overlay'), 'click', closeDrawer);
}}
function closeDrawer() {{
  S.navOpen = false;
  $('#mobile-drawer')?.classList.remove('open');
  $('#drawer-overlay')?.classList.remove('open');
}}

function initScrollProgress() {{
  const bar = $('#scroll-bar');
  if (!bar) return;
  window.addEventListener('scroll', () => {{
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.width = (max > 0 ? scrollY / max * 100 : 0) + '%';
  }}, {{passive:true}});
}}

function initReveal() {{
  if (!('IntersectionObserver' in window)) {{ $$('.reveal').forEach(el => el.classList.add('visible')); return; }}
  const obs = new IntersectionObserver(entries => {{
    entries.forEach((entry, i) => {{
      if (entry.isIntersecting) {{
        setTimeout(() => {{
          entry.target.classList.add('visible');
          const countTo = entry.target.dataset.countTo;
          if (countTo) animateCounter(entry.target, parseFloat(countTo));
        }}, i * 65);
        obs.unobserve(entry.target);
      }}
    }});
  }}, {{threshold:0.1, rootMargin:'0px 0px -36px 0px'}});
  $$('.reveal').forEach(el => obs.observe(el));
}}

function animateCounter(el, target, dur=1500) {{
  const start = performance.now();
  const isFloat = target % 1 !== 0;
  const prefix = el.dataset.prefix || '';
  const suffix = el.dataset.suffix || '';
  const fmt = n => String(n).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
  (function tick(now) {{
    const p = Math.min((now - start) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = isFloat ? (eased * target).toFixed(1) : Math.floor(eased * target);
    el.textContent = prefix + fmt(val) + suffix;
    if (p < 1) requestAnimationFrame(tick);
  }})(start);
}}

function initFAQ() {{
  $$('.faq-item').forEach((item, i) => {{
    on(item.querySelector('.faq-q'), 'click', () => {{
      const ans = item.querySelector('.faq-answer');
      const icon = item.querySelector('.faq-icon');
      const isOpen = S.openFaq === i;
      $$('.faq-answer').forEach(a => {{ a.style.maxHeight = '0'; a.style.opacity = '0'; }});
      $$('.faq-icon').forEach(ic => ic.style.transform = 'rotate(0deg)');
      S.openFaq = isOpen ? -1 : i;
      if (!isOpen && ans) {{ ans.style.maxHeight = ans.scrollHeight + 'px'; ans.style.opacity = '1'; }}
      if (!isOpen && icon) icon.style.transform = 'rotate(45deg)';
    }});
  }});
}}

function initTabs(wrapperId) {{
  const wrapper = $('#' + wrapperId); if (!wrapper) return;
  const btns = $$('.tab-btn', wrapper);
  const panels = $$('.tab-panel', wrapper);
  btns.forEach((btn, i) => on(btn, 'click', () => {{
    btns.forEach(b => b.classList.remove('active'));
    panels.forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    panels[i]?.classList.add('active');
  }}));
  btns[0]?.click();
}}

function initPricing() {{
  const opts = $$('.plan-opt');
  opts.forEach(opt => on(opt, 'click', () => {{
    S.plan = opt.dataset.plan || 'monthly';
    opts.forEach(o => o.classList.toggle('active', o.dataset.plan === S.plan));
    $$('[data-price-m]').forEach(el => {{ el.textContent = S.plan === 'monthly' ? el.dataset.priceM : el.dataset.priceY; }});
    const badge = $('#annual-badge');
    if (badge) badge.style.display = S.plan === 'annual' ? 'inline-block' : 'none';
  }}));
  opts[0]?.click();
}}

function addToCart(name, price) {{
  S.cart.push({{name, price, qty:S.qty || 1}});
  renderCart();
  showToast(name + ' added to cart');
}}
function removeFromCart(i) {{ S.cart.splice(i,1); renderCart(); }}
function renderCart() {{
  const badge = $('#cart-count');
  const count = S.cart.reduce((sum, item) => sum + item.qty, 0);
  if (badge) {{ badge.textContent = count; badge.style.display = count ? 'flex' : 'none'; }}
  const list = $('#cart-list');
  if (!list) return;
  if (!S.cart.length) {{ list.innerHTML = '<p class="text-sm" style="padding:2rem;text-align:center">Your cart is empty</p>'; return; }}
  list.innerHTML = S.cart.map((item, i) => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:1rem 0;border-bottom:1px solid var(--border)">
      <div><div class="text-h3" style="font-size:0.95rem">${{item.name}}</div><div class="text-sm">Qty ${{item.qty}} · ₹${{item.price.toLocaleString('en-IN')}}</div></div>
      <button class="btn btn-sm btn-ghost" onclick="removeFromCart(${{i}})">Remove</button>
    </div>`).join('');
  const subtotal = S.cart.reduce((sum, item) => sum + item.price * item.qty, 0);
  const gst = Math.round(subtotal * 0.18);
  $('#cart-gst') && ($('#cart-gst').textContent = '₹' + gst.toLocaleString('en-IN'));
  $('#cart-total') && ($('#cart-total').textContent = '₹' + (subtotal + gst).toLocaleString('en-IN'));
}}

function showToast(msg) {{
  const t = $('#toast'); if (!t) return;
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._tid); t._tid = setTimeout(() => t.classList.remove('show'), 2600);
}}

function initSmoothScroll() {{
  $$('[data-scroll]').forEach(el => on(el, 'click', e => {{
    e.preventDefault();
    $(el.dataset.scroll)?.scrollIntoView({{behavior:'smooth', block:'start'}});
    closeDrawer();
  }}));
}}

function initForms() {{
  on($('[data-thecee-id="checkout-form"]'), 'submit', e => {{ e.preventDefault(); S.formSent = true; goTo('confirmation'); showToast('Order placed successfully'); }});
}}

function selectThumb(i) {{
  $$('.thumb').forEach((t, j) => t.classList.toggle('active', j === i));
  const main = $('#product-main-img');
  if (main) {{ main.style.opacity = '0.35'; setTimeout(() => main.style.opacity = '1', 180); }}
  S.activeThumb = i;
}}
function changeQty(delta) {{
  S.qty = Math.max(1, S.qty + delta);
  $$('.qty-value').forEach(el => el.textContent = S.qty);
}}

window.goTo = goTo;
window.addToCart = addToCart;
window.removeFromCart = removeFromCart;
window.selectThumb = selectThumb;
window.changeQty = changeQty;

document.addEventListener('DOMContentLoaded', () => {{
  initNavbar(); initScrollProgress(); initReveal(); initFAQ(); initPricing();
  initTabs('product-tabs'); initTabs('payment-tabs'); initSmoothScroll(); initForms(); renderCart();
}});

If nearing token budget, shorten copy first. Never omit required pages, tracking IDs, script, </body>, or </html>.
"""

# ── Refine prompt components ──────────────────────────────────────────────────
# Used by the refine_ui endpoint to make surgical changes to an existing prototype.

UI_REFINE_SYSTEM = """\
You are a senior frontend engineer making precise, surgical edits to a production HTML prototype.
TheCee injects the latest base CSS template before the prototype is served, so do not recreate
or preserve a large design-system style block. Use existing CSS classes and make only tiny
component-specific CSS additions when unavoidable. Vanilla JavaScript only.

Rules — violating any of these breaks the prototype:
1. Apply ONLY the requested change. Do not restyle, rename, or restructure anything not mentioned.
2. Keep ALL data-thecee-id attributes on their current elements. Never move or remove them.
3. Keep ALL vanilla JS intact — the S state object, all init* functions, goTo(), renderCart(),
   showToast(), animateCounter(), IntersectionObserver reveal logic. Do not touch working JS.
4. Keep the Tailwind CDN <script>, tailwind.config block, and Google Fonts <link> tags unchanged.
5. Keep #scroll-bar, #toast, #drawer-overlay, #main-nav, #mobile-drawer elements present.
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
