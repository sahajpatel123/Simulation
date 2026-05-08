"""AI + heuristic labels for the hardware TechnicalPlate engineering title strip."""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.claude_client import claude_call_with_fallback
from app.core.config import settings

_MAX_SPEC_CHARS = 18_000

_LEN_CAP = {
    "project": 52,
    "category": 36,
    "components": 88,
    "est_mass": 24,
    "scale": 48,
}


def _truncate_spec_json(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, ensure_ascii=False, indent=2)
    if len(raw) <= _MAX_SPEC_CHARS:
        return raw
    return raw[:_MAX_SPEC_CHARS] + "\n…(truncated)"


def _clip(key: str, value: str) -> str:
    cap = _LEN_CAP.get(key, 80)
    v = value.strip()
    if len(v) <= cap:
        return v
    return v[: max(0, cap - 1)] + "…"


def heuristic_engineering_plate_labels(
    spec: dict[str, Any],
    *,
    product_name_fallback: str,
    category_fallback: str,
) -> dict[str, str]:
    dims = spec.get("dimensions") or {}
    wg = dims.get("weight_grams")
    if wg is None:
        wg = spec.get("weight_grams")
    try:
        wg_f = float(wg) if wg is not None else None
    except (TypeError, ValueError):
        wg_f = None
    mass = f"≈ {wg_f:.0f} g" if wg_f is not None else "—"

    L, W, H = dims.get("length_mm"), dims.get("width_mm"), dims.get("height_mm")
    try:
        if L is not None and W is not None and H is not None:
            scale = f"{float(L):.0f}×{float(W):.0f}×{float(H):.0f} mm"
        else:
            scale = "BENCH 1:1"
    except (TypeError, ValueError):
        scale = "BENCH 1:1"

    comps = spec.get("components") or []
    names: list[str] = []
    for c in comps:
        if not isinstance(c, dict):
            continue
        nm = str(c.get("name") or c.get("id") or "").strip()
        if nm:
            names.append(nm)
    head = ", ".join(names[:4])
    extra = len(names) - 4
    tail = f" +{extra}" if extra > 0 else ""
    if names:
        comp_line = f"{len(comps)} · {head}{tail}"
    else:
        comp_line = "—"

    pn = str(spec.get("product_name") or product_name_fallback or "—").strip() or "—"
    cat_raw = str(spec.get("category") or category_fallback or "—").strip() or "—"
    cat = cat_raw.replace("_", " ").upper()

    return {
        "project": _clip("project", pn),
        "category": _clip("category", cat),
        "components": _clip("components", comp_line),
        "est_mass": _clip("est_mass", mass),
        "scale": _clip("scale", scale),
    }


def compute_engineering_plate_labels(
    spec: dict[str, Any],
    *,
    product_name_fallback: str,
    category_fallback: str,
) -> dict[str, str]:
    """
    One Haiku call: concise title-strip values from the semantic spec JSON.
    Falls back to deterministic heuristics on parse errors or Claude failure.
    """
    base = heuristic_engineering_plate_labels(
        spec,
        product_name_fallback=product_name_fallback,
        category_fallback=category_fallback,
    )
    if not (settings.NVIDIA_API_KEY or "").strip():
        return base
    brief = _truncate_spec_json(spec)
    system = (
        "You fill an engineering title strip on a hardware dossier. "
        "Return ONLY one JSON object with exactly these string keys: "
        "project, category, components, est_mass, scale.\n"
        "- project: product title, ≤52 chars, readable.\n"
        "- category: human-readable category, ≤36 chars.\n"
        "- components: count and principal part names from the spec, ≤88 chars.\n"
        "- est_mass: mass with unit (g or kg), use ≈ if estimated from spec, ≤24 chars.\n"
        "- scale: envelope L×W×H in mm when dimensions present, else BENCH 1:1, ≤48 chars.\n"
        "Prefer values implied by spec.dimensions and spec.components; do not invent absurd numbers."
    )
    user = (
        f"Fallbacks if spec is sparse:\nproduct_name: {product_name_fallback}\n"
        f"category: {category_fallback}\n\nSPEC JSON:\n{brief}"
    )
    out = claude_call_with_fallback(
        [{"role": "user", "content": user}],
        system=system,
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        fallback_key="engineering_plate",
        timeout=45,
    )
    if out.get("error"):
        return base
    raw = (out.get("content") or "").strip()
    if not raw:
        return base
    try:
        text = raw
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(line for line in lines if not line.strip().startswith("```"))
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return base
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            return base
        merged = dict(base)
        for key in _LEN_CAP:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                merged[key] = _clip(key, val)
        return merged
    except (json.JSONDecodeError, TypeError, ValueError):
        return base
