from __future__ import annotations

from typing import Literal

# ── Layout Archetypes ──────────────────────────────────────────
# Maps product types to page layout strategies for the LLM prompt.
# Each archetype dictates the overall page structure and visual rhythm.

LayoutArchetype = Literal[
    "bento", "editorial", "showcase", "wizard", "dashboard",
    "narrative", "mono", "luxe", "social", "utility", "landing", "portfolio",
]

_LAYOUT_MAP: dict[str, LayoutArchetype] = {
    "saas":              "bento",
    "marketplace":       "social",
    "mobile_app":        "wizard",
    "developer_tool":    "mono",
    "enterprise_software": "dashboard",
    "consumer_hardware": "showcase",
    "health_hardware":   "narrative",
    "iot_hardware":      "showcase",
    "wearable":          "showcase",
    "b2b_hardware":      "dashboard",
    "mobile_app":        "wizard",
    "fintech":           "utility",
    "ecommerce":         "luxe",
    "d2c":               "luxe",
    "edtech":            "narrative",
    "food":              "social",
    "productivity":      "bento",
    "crm":               "dashboard",
    "api":               "mono",
    "platform":          "bento",
    "banking":           "utility",
    "insurance":         "utility",
    "fitness":           "narrative",
    "health":            "narrative",
    "wellness":          "narrative",
    "learning":          "narrative",
    "course":            "narrative",
    "device":            "showcase",
}

_ARCHETYPE_INSTRUCTIONS: dict[LayoutArchetype, str] = {
    "bento":    "LAYOUT: Asymmetric card grid with one hero card spanning 2 columns. VISUAL: Gradient-heavy, modern. Use a bold brand color (NOT indigo — pick something unique to this product). Example feel: Notion or Linear.",
    "editorial":"LAYOUT: Large typography hero, article-style content flow, minimal chrome. VISUAL: High contrast, lots of whitespace, serif or large sans-serif headlines. Black/white with one accent color. Example feel: The Browser Company or Apple product pages.",
    "showcase": "LAYOUT: Full-bleed hero with product visuals, sparse copy sections, large product grid. VISUAL: Dark or light but minimal — let the product imagery dominate. Use Unsplash photos that show the actual product category.",
    "wizard":   "LAYOUT: Step-through progressive disclosure with a progress indicator at top. Each step reveals next section. VISUAL: Clean, card-based, with clear forward/back buttons. Example feel: Typeform or onboarding flows.",
    "dashboard":"LAYOUT: Data-dense card-first layout with sidebar navigation. VISUAL: Professional, muted colors, monospace or clean sans for data. Example feel: Vercel analytics or Retool.",
    "narrative":"LAYOUT: Full-screen sections that feel like scenes in a story. Scroll progress indicator. VISUAL: Rich backgrounds, large imagery, text overlays. Example feel: Apple Watch or Airbnb experiences pages.",
    "mono":     "LAYOUT: Brutalist — one column, single font, maximum contrast. VISUAL: Black/white/gray only (no brand colors). One typeface at different weights. Example feel: Stripe or Deel documentation.",
    "luxe":     "LAYOUT: Large whitespace, elegant product grid, sparse copy. VISUAL: Gold/champagne accent, dark or cream background, refined typography. Example feel: Aesop or Cartier.",
    "social":   "LAYOUT: Profile cards, activity feed, prominent search bar. VISUAL: Light background, rounded avatars, card shadows. Example feel: Twitter or Dribbble.",
    "utility":  "LAYOUT: Minimal chrome, function-first — the tool/calculator/is the hero. Clear input areas, prominent results display. VISUAL: Clean, neutral, accessibility-focused. Example feel: Calculator or banking apps.",
    "landing":  "LAYOUT: Single scroll page. Aggressive CTA above the fold, social proof logos, feature grid, pricing. VISUAL: Bold, confident, high-contrast. Example feel: Dropbox or Superhuman landing pages.",
    "portfolio":"LAYOUT: Masonry grid of project cards with filterable categories. Large hero with name/title. VISUAL: Creative, white space, elegant typography. Example feel: Awwwards winning portfolio sites.",
}


def select_layout_archetype(product_type: str) -> tuple[LayoutArchetype, str]:
    """Return (archetype, instruction) for the given product type string."""
    key = (product_type or "").lower().strip()
    arch = _LAYOUT_MAP.get(key, "landing")
    return arch, _ARCHETYPE_INSTRUCTIONS[arch]


def _template(
    *,
    brand: str,
    brand_dark: str,
    secondary: str,
    accent: str,
    bg: str,
    surface: str,
    surface_2: str,
    text_1: str,
    text_2: str,
    text_3: str,
    border: str,
    border_strong: str,
    glass: str,
    nav_bg: str,
    hero_grid: str,
    shadow: str,
    shadow_lg: str,
    success: str = "#10b981",
) -> str:
    return f"""
:root {{
  --brand: {brand};
  --brand-dark: {brand_dark};
  --brand-secondary: {secondary};
  --brand-accent: {accent};
  --brand-dim: color-mix(in srgb, var(--brand) 12%, transparent);
  --brand-glow: color-mix(in srgb, var(--brand) 30%, transparent);
  --bg: {bg};
  --surface: {surface};
  --surface-2: {surface_2};
  --border: {border};
  --border-strong: {border_strong};
  --text-1: {text_1};
  --text-2: {text_2};
  --text-3: {text_3};
  --success: {success};
  --radius: 10px;
  --radius-lg: 16px;
  --radius-xl: 22px;
  --shadow: {shadow};
  --shadow-lg: {shadow_lg};
  --ease: cubic-bezier(0.4,0,0.2,1);
  --transition: all 0.18s cubic-bezier(0.4,0,0.2,1);
}}

*,*::before,*::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  min-height: 100vh;
  background: var(--bg);
  color: var(--text-1);
  font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  overflow-x: hidden;
}}
a {{ color: inherit; text-decoration: none; }}
button,input,textarea,select {{ font: inherit; }}
button {{ cursor: pointer; }}
img,svg {{ max-width: 100%; display: block; }}
::selection {{ background: var(--brand); color: #fff; }}
#scroll-bar {{
  position: fixed; top: 0; left: 0; height: 2px; width: 0%;
  background: linear-gradient(to right, var(--brand), var(--brand-secondary), var(--brand-accent));
  z-index: 9999; transition: width 0.08s linear; pointer-events: none;
}}
.font-display {{ font-family: 'Plus Jakarta Sans', 'Inter', sans-serif; }}
.text-hero {{
  font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
  font-weight: 900; font-size: clamp(2.6rem, 5.5vw, 4.85rem);
  letter-spacing: -0.045em; line-height: 1.04;
}}
.text-h2 {{
  font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
  font-weight: 850; font-size: clamp(1.85rem, 3.4vw, 2.75rem);
  letter-spacing: -0.035em; line-height: 1.12;
}}
.text-h3 {{
  font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
  font-weight: 750; font-size: 1.12rem; line-height: 1.35;
}}
.text-body {{ font-size: 1rem; line-height: 1.72; color: var(--text-2); }}
.text-sm {{ font-size: 0.875rem; line-height: 1.65; color: var(--text-2); }}
.text-xs {{ font-size: 0.75rem; line-height: 1.5; color: var(--text-3); }}
.overline {{
  font-size: 0.7rem; font-weight: 800; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--text-3);
}}
.gradient-text {{
  background: linear-gradient(130deg, var(--brand) 0%, var(--brand-secondary) 55%, var(--brand-accent) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}}
.btn {{
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  border: none; cursor: pointer; white-space: nowrap; text-decoration: none;
}}
.btn-primary {{
  background: linear-gradient(135deg, var(--brand), var(--brand-dark)); color: #fff;
  padding: 0.75rem 1.8rem; border-radius: var(--radius); font-weight: 700;
  font-size: 0.9rem; letter-spacing: 0.01em; transition: var(--transition);
  box-shadow: 0 4px 18px var(--brand-glow);
}}
.btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 10px 32px var(--brand-glow); filter: saturate(1.08); }}
.btn-primary:active {{ transform: scale(0.97); }}
.btn-ghost {{
  background: transparent; border: 1px solid var(--border-strong); color: var(--text-2);
  padding: 0.75rem 1.8rem; border-radius: var(--radius); font-weight: 600;
  font-size: 0.9rem; transition: var(--transition);
}}
.btn-ghost:hover {{ background: var(--brand-dim); border-color: var(--brand); color: var(--text-1); }}
.btn-lg {{ padding: 1rem 2.2rem; font-size: 0.975rem; border-radius: var(--radius-lg); }}
.btn-sm {{ padding: 0.45rem 1rem; font-size: 0.8rem; }}
.btn-icon {{
  width: 38px; height: 38px; padding: 0; border-radius: 50%; justify-content: center;
  border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2);
  transition: var(--transition);
}}
.btn-icon:hover {{ border-color: var(--brand); color: var(--brand); background: var(--brand-dim); }}
.card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
  transition: var(--transition); box-shadow: var(--shadow);
}}
.card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-lg); border-color: var(--border-strong); }}
.card-featured {{
  background: linear-gradient(145deg, var(--surface-2), var(--surface));
  border: 1px solid var(--brand); border-radius: var(--radius-xl); position: relative;
  overflow: hidden; box-shadow: 0 0 0 1px var(--brand-dim), var(--shadow-lg);
}}
.card-featured::before {{
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(ellipse at 20% 20%, var(--brand-dim), transparent 65%);
  pointer-events: none;
}}
.glass {{
  background: {glass}; backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%); border: 1px solid var(--border-strong);
}}
.pill {{
  display: inline-flex; align-items: center; gap: 6px; background: var(--brand-dim);
  border: 1px solid var(--brand-glow); color: var(--brand); border-radius: 999px;
  padding: 5px 14px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.01em;
}}
.badge {{
  display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 0.68rem;
  font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase;
}}
.badge-brand {{ background: var(--brand); color: #fff; }}
.badge-success {{ background: var(--success); color: #fff; }}
.badge-muted {{ background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }}
.blob {{
  position: absolute; border-radius: 50%; filter: blur(80px); opacity: 0.18;
  pointer-events: none; z-index: 0; animation: blobDrift 12s ease-in-out infinite;
}}
.blob-2 {{ animation-delay: -6s; animation-duration: 15s; }}
@keyframes blobDrift {{
  0%,100% {{ transform: translate(0,0) scale(1); }}
  33% {{ transform: translate(30px,-20px) scale(1.05); }}
  66% {{ transform: translate(-15px,25px) scale(0.96); }}
}}
.section {{ padding: 6rem 0; }}
.section-sm {{ padding: 3.5rem 0; }}
.container {{ max-width: 1120px; margin: 0 auto; padding: 0 1.5rem; }}
.grid-3 {{ display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 1.5rem; }}
.grid-2 {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 1.5rem; }}
#main-nav {{
  position: fixed; top: 0; left: 0; right: 0; z-index: 100; padding: 1.1rem 0;
  transition: background 0.35s ease, padding 0.3s ease, border-color 0.3s ease;
  border-bottom: 1px solid transparent;
}}
#main-nav.scrolled {{ background: {nav_bg}; backdrop-filter: blur(20px); border-color: var(--border); padding: 0.7rem 0; }}
#mobile-drawer {{
  position: fixed; top: 0; right: 0; bottom: 0; width: 280px; background: var(--surface);
  border-left: 1px solid var(--border); transform: translateX(100%);
  transition: transform 0.32s var(--ease); z-index: 300; padding: 4.5rem 2rem 2rem;
  display: flex; flex-direction: column; gap: 1rem;
}}
#mobile-drawer.open {{ transform: translateX(0); }}
#drawer-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 200; opacity: 0; pointer-events: none; transition: opacity 0.3s; }}
#drawer-overlay.open {{ opacity: 1; pointer-events: all; }}
.reveal {{ opacity: 0; transform: translateY(30px); transition: opacity 0.65s ease, transform 0.65s ease; }}
.reveal.from-left {{ transform: translateX(-30px); }}
.reveal.from-right {{ transform: translateX(30px); }}
.reveal.scale-in {{ transform: scale(0.93); }}
.reveal.visible {{ opacity: 1; transform: none; }}
.d1 {{ transition-delay: 0.07s; }} .d2 {{ transition-delay: 0.14s; }} .d3 {{ transition-delay: 0.21s; }} .d4 {{ transition-delay: 0.28s; }} .d5 {{ transition-delay: 0.35s; }}
.page {{ display: none; }}
.page.active {{ display: block; animation: pageIn 0.28s ease; }}
@keyframes pageIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.faq-answer {{ max-height: 0; overflow: hidden; opacity: 0; transition: max-height 0.42s ease, opacity 0.32s ease; }}
.faq-icon {{ display: inline-block; transition: transform 0.3s ease; line-height: 1; }}
.tab-btn {{
  cursor: pointer; padding: 0.55rem 1.25rem; border-radius: var(--radius); font-size: 0.875rem;
  font-weight: 600; color: var(--text-2); border: 1px solid transparent; transition: var(--transition);
}}
.tab-btn.active {{ background: var(--brand); color: #fff; box-shadow: 0 4px 14px var(--brand-glow); }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; animation: pageIn 0.2s ease; }}
.plan-opt {{
  padding: 7px 22px; border-radius: 999px; cursor: pointer; font-size: 0.875rem;
  font-weight: 600; color: var(--text-2); transition: var(--transition);
}}
.plan-opt.active {{ background: var(--brand); color: #fff; }}
#toast {{
  position: fixed; bottom: 1.75rem; left: 50%; transform: translateX(-50%) translateY(80px);
  background: var(--surface-2); border: 1px solid var(--border-strong); color: var(--text-1);
  padding: 0.75rem 1.5rem; border-radius: var(--radius); font-size: 0.875rem;
  font-weight: 650; z-index: 9998; transition: transform 0.38s cubic-bezier(0.34,1.56,0.64,1), opacity 0.3s ease;
  opacity: 0; pointer-events: none; white-space: nowrap; box-shadow: var(--shadow-lg);
}}
#toast.show {{ transform: translateX(-50%) translateY(0); opacity: 1; }}
.input {{
  width: 100%; background: var(--surface-2); border: 1px solid var(--border-strong);
  color: var(--text-1); border-radius: var(--radius); padding: 0.75rem 1rem;
  font-size: 0.9rem; transition: var(--transition); outline: none;
}}
.input:focus {{ border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-dim); }}
.input::placeholder {{ color: var(--text-3); }}
.form-label {{ display: block; font-size: 0.78rem; font-weight: 700; color: var(--text-2); margin-bottom: 6px; letter-spacing: 0.03em; }}
.step-dot {{
  width: 38px; height: 38px; border-radius: 50%; background: var(--brand); color: #fff;
  display: flex; align-items: center; justify-content: center; font-weight: 850; font-size: 0.9rem; flex-shrink: 0;
}}
.icon-circle {{
  width: 48px; height: 48px; border-radius: 50%; background: var(--brand-dim);
  border: 1px solid var(--brand-glow); display: flex; align-items: center; justify-content: center;
  font-size: 22px; flex-shrink: 0;
}}
.divider {{ height: 1px; background: linear-gradient(to right, transparent, var(--border-strong), transparent); }}
.counter {{ font-variant-numeric: tabular-nums; }}
.stars {{ color: #fbbf24; letter-spacing: 0.06em; }}
.logo-track {{ display: flex; align-items: center; justify-content: center; gap: clamp(1rem, 4vw, 3rem); flex-wrap: wrap; }}
.logo-item {{ color: var(--text-2); font-weight: 850; letter-spacing: -0.03em; opacity: 0.82; }}
.thumb.active {{ border-color: var(--brand) !important; box-shadow: 0 0 0 3px var(--brand-dim); }}
.hero-grid {{ background-image: radial-gradient({hero_grid} 1px, transparent 1px); background-size: 24px 24px; }}
@media (max-width: 900px) {{
  .grid-3,.grid-2 {{ grid-template-columns: 1fr; }}
  .hide-mobile {{ display: none !important; }}
  .section {{ padding: 4rem 0; }}
  .section-sm {{ padding: 2.75rem 0; }}
  .container {{ padding: 0 1.15rem; }}
  .text-hero {{ font-size: clamp(2.35rem, 12vw, 3.65rem); }}
  #mobile-drawer {{ width: min(86vw, 320px); }}
}}
""".strip()


DARK_SAAS_CSS = _template(
    brand="#6366f1", brand_dark="#4f46e5", secondary="#a78bfa", accent="#f472b6",
    bg="#08080e", surface="#111119", surface_2="#181825", text_1="#f4f4fb",
    text_2="#a1a1b8", text_3="#64647a", border="rgba(255,255,255,0.07)",
    border_strong="rgba(255,255,255,0.13)", glass="rgba(255,255,255,0.045)",
    nav_bg="rgba(8,8,14,0.88)", hero_grid="rgba(255,255,255,0.08)",
    shadow="0 2px 16px rgba(0,0,0,0.22)", shadow_lg="0 20px 56px rgba(0,0,0,0.38)",
)

DARK_DEVTOOLS_CSS = _template(
    brand="#22c55e", brand_dark="#16a34a", secondary="#14b8a6", accent="#84cc16",
    bg="#060a06", surface="#0e160f", surface_2="#142018", text_1="#effff4",
    text_2="#9ab7a3", text_3="#5f7566", border="rgba(187,247,208,0.08)",
    border_strong="rgba(187,247,208,0.16)", glass="rgba(20,60,32,0.36)",
    nav_bg="rgba(6,10,6,0.9)", hero_grid="rgba(34,197,94,0.12)",
    shadow="0 2px 16px rgba(0,0,0,0.26)", shadow_lg="0 20px 58px rgba(0,0,0,0.44)",
)

DARK_FINTECH_CSS = _template(
    brand="#3b82f6", brand_dark="#2563eb", secondary="#06b6d4", accent="#60a5fa",
    bg="#070810", surface="#101321", surface_2="#171b2d", text_1="#f1f7ff",
    text_2="#9aa9c2", text_3="#627089", border="rgba(191,219,254,0.08)",
    border_strong="rgba(191,219,254,0.15)", glass="rgba(15,23,42,0.5)",
    nav_bg="rgba(7,8,16,0.9)", hero_grid="rgba(96,165,250,0.12)",
    shadow="0 2px 16px rgba(0,0,0,0.24)", shadow_lg="0 22px 60px rgba(0,0,0,0.42)",
)

LIGHT_CONSUMER_CSS = _template(
    brand="#f59e0b", brand_dark="#d97706", secondary="#fb7185", accent="#f97316",
    bg="#f7f6f2", surface="#ffffff", surface_2="#f0eee7", text_1="#17130b",
    text_2="#6f6758", text_3="#9a907f", border="rgba(0,0,0,0.07)",
    border_strong="rgba(0,0,0,0.13)", glass="rgba(255,255,255,0.68)",
    nav_bg="rgba(247,246,242,0.88)", hero_grid="rgba(0,0,0,0.08)",
    shadow="0 2px 16px rgba(35,24,10,0.08)", shadow_lg="0 22px 58px rgba(35,24,10,0.16)",
)

LIGHT_HEALTH_CSS = _template(
    brand="#10b981", brand_dark="#059669", secondary="#2dd4bf", accent="#84cc16",
    bg="#f4faf7", surface="#ffffff", surface_2="#eaf6f0", text_1="#0d1f18",
    text_2="#52665d", text_3="#84968d", border="rgba(6,95,70,0.09)",
    border_strong="rgba(6,95,70,0.16)", glass="rgba(255,255,255,0.72)",
    nav_bg="rgba(244,250,247,0.9)", hero_grid="rgba(16,185,129,0.13)",
    shadow="0 2px 16px rgba(6,95,70,0.08)", shadow_lg="0 22px 58px rgba(6,95,70,0.15)",
)

LIGHT_EDTECH_CSS = _template(
    brand="#a855f7", brand_dark="#9333ea", secondary="#6366f1", accent="#ec4899",
    bg="#f8f5ff", surface="#ffffff", surface_2="#f0eaff", text_1="#1e1535",
    text_2="#65587f", text_3="#9588ac", border="rgba(88,28,135,0.08)",
    border_strong="rgba(88,28,135,0.16)", glass="rgba(255,255,255,0.72)",
    nav_bg="rgba(248,245,255,0.9)", hero_grid="rgba(168,85,247,0.13)",
    shadow="0 2px 16px rgba(88,28,135,0.08)", shadow_lg="0 22px 58px rgba(88,28,135,0.16)",
)

LIGHT_FOOD_CSS = _template(
    brand="#fb923c", brand_dark="#ea580c", secondary="#ef4444", accent="#facc15",
    bg="#fff8f4", surface="#ffffff", surface_2="#fff0e6", text_1="#24130a",
    text_2="#735c4b", text_3="#a08a79", border="rgba(154,52,18,0.08)",
    border_strong="rgba(154,52,18,0.16)", glass="rgba(255,255,255,0.74)",
    nav_bg="rgba(255,248,244,0.9)", hero_grid="rgba(251,146,60,0.14)",
    shadow="0 2px 16px rgba(154,52,18,0.08)", shadow_lg="0 22px 58px rgba(154,52,18,0.16)",
)

HARDWARE_CSS = _template(
    brand="#0ea5e9", brand_dark="#0284c7", secondary="#22d3ee", accent="#38bdf8",
    bg="#070c10", surface="#101922", surface_2="#162331", text_1="#eff9ff",
    text_2="#9bb4c5", text_3="#637b8d", border="rgba(186,230,253,0.08)",
    border_strong="rgba(186,230,253,0.16)", glass="rgba(14,34,48,0.5)",
    nav_bg="rgba(7,12,16,0.9)", hero_grid="rgba(14,165,233,0.12)",
    shadow="0 2px 16px rgba(0,0,0,0.25)", shadow_lg="0 22px 60px rgba(0,0,0,0.45)",
)

_TEMPLATE_MAP = {
    "saas": DARK_SAAS_CSS,
    "productivity": DARK_SAAS_CSS,
    "crm": DARK_SAAS_CSS,
    "developer_tool": DARK_DEVTOOLS_CSS,
    "api": DARK_DEVTOOLS_CSS,
    "platform": DARK_DEVTOOLS_CSS,
    "fintech": DARK_FINTECH_CSS,
    "banking": DARK_FINTECH_CSS,
    "insurance": DARK_FINTECH_CSS,
    "b2b": DARK_FINTECH_CSS,
    "enterprise_software": DARK_FINTECH_CSS,
    "ecommerce": LIGHT_CONSUMER_CSS,
    "d2c": LIGHT_CONSUMER_CSS,
    "marketplace": LIGHT_CONSUMER_CSS,
    "consumer": LIGHT_CONSUMER_CSS,
    "health": LIGHT_HEALTH_CSS,
    "wellness": LIGHT_HEALTH_CSS,
    "fitness": LIGHT_HEALTH_CSS,
    "health_hardware": LIGHT_HEALTH_CSS,
    "edtech": LIGHT_EDTECH_CSS,
    "learning": LIGHT_EDTECH_CSS,
    "course": LIGHT_EDTECH_CSS,
    "food": LIGHT_FOOD_CSS,
    "restaurant": LIGHT_FOOD_CSS,
    "delivery": LIGHT_FOOD_CSS,
    "hardware": HARDWARE_CSS,
    "consumer_hardware": HARDWARE_CSS,
    "iot": HARDWARE_CSS,
    "iot_hardware": HARDWARE_CSS,
    "device": HARDWARE_CSS,
    "wearable": HARDWARE_CSS,
    "b2b_hardware": HARDWARE_CSS,
    "mobile_app": DARK_SAAS_CSS,
}


def select_template(product_type: str) -> str:
    return _TEMPLATE_MAP.get((product_type or "").lower().strip(), DARK_SAAS_CSS)
