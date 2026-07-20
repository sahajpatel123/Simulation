from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.claude_client import claude_call_with_fallback

# Claim confidence adjustment per intake_mode
INTAKE_CONFIDENCE_MAP: dict[str, dict[str, Any]] = {
    "IDEA": {
        "default_confidence": "DESIGN_INTENT",
        "pricing_confidence": "DESIGN_INTENT",
        "feature_confidence": "DESIGN_INTENT",
        "validation_multiplier": 1.0,
    },
    "MID_BUILD": {
        "default_confidence": "VALIDATED_INTERNAL",
        "pricing_confidence": "VALIDATED_INTERNAL",
        "feature_confidence": "VALIDATED_INTERNAL",
        "validation_multiplier": 0.75,
    },
    "PRE_LAUNCH": {
        "default_confidence": "VALIDATED_INTERNAL",
        "pricing_confidence": "VALIDATED_EXTERNAL",
        "feature_confidence": "VALIDATED_INTERNAL",
        "validation_multiplier": 0.55,
    },
}


def fetch_landing_page_summary(url: str) -> str:
    """
    Fetches a landing page URL and summarises it via Claude.
    Returns a 2-3 sentence summary of product claims.
    """
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        html = resp.text[:8000]
        text_body = re.sub(r"<[^>]+>", " ", html)
        text_body = re.sub(r"\s+", " ", text_body).strip()[:3000]

        summary_resp = claude_call_with_fallback(
            [
                {
                    "role": "user",
                    "content": (
                        "Summarise the key product claims on this landing page in 2-3 sentences. "
                        f"Focus on pricing, features, and target audience. Page text: {text_body}"
                    ),
                }
            ],
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            fallback_key="intake_landing",
            timeout=30,
        )
        if summary_resp.get("error"):
            return (
                "Landing page summary unavailable — "
                f"{summary_resp.get('error', 'try again')}"
            )
        return (summary_resp.get("content") or "").strip()
    except Exception as e:
        return f"Could not fetch landing page: {e!s}"


def build_enriched_description(
    description: str,
    intake_mode: str,
    landing_page_url: str | None = None,
    mvp_feature_list: list[str] | None = None,
    existing_product_description: str | None = None,
) -> tuple[str, str]:
    """
    Returns (enriched_description, intake_mode_used).
    Enriches description based on intake_mode.
    """
    if intake_mode == "IDEA":
        return description, "IDEA"

    parts: list[str] = [description]

    if intake_mode in ("MID_BUILD", "PRE_LAUNCH"):
        if mvp_feature_list:
            features_text = "Shipped features: " + ", ".join(mvp_feature_list)
            parts.append(features_text)
        if existing_product_description:
            parts.append(f"Current product state: {existing_product_description}")
        if landing_page_url:
            summary = fetch_landing_page_summary(landing_page_url)
            parts.append(f"Landing page claims: {summary}")

    return "\n\n".join(parts), intake_mode


def _assumption_text(a: dict) -> str:
    return str(a.get("assumption", "") or a.get("text", "")).lower()


def adjust_assumption_confidence(
    assumptions: list[dict],
    intake_mode: str,
) -> list[dict]:
    """
    Adjusts claim_confidence tags on all assumptions
    based on intake_mode. MID_BUILD and PRE_LAUNCH
    get higher baseline confidence.
    """
    config = INTAKE_CONFIDENCE_MAP.get(intake_mode, INTAKE_CONFIDENCE_MAP["IDEA"])
    adjusted: list[dict] = []
    confidence_rank: dict[str, int] = {
        "ASPIRATIONAL": 0,
        "DESIGN_INTENT": 1,
        "VALIDATED_INTERNAL": 2,
        "VALIDATED_EXTERNAL": 3,
    }

    for a in assumptions:
        existing = a.get("claim_confidence", "DESIGN_INTENT")
        if intake_mode == "IDEA":
            adjusted.append(a)
            continue

        is_pricing = any(
            w in _assumption_text(a) for w in ("price", "cost", "₹", "plan", "subscription", "fee")
        )
        new_conf: str = (
            config["pricing_confidence"] if is_pricing else str(config["default_confidence"])
        )
        current_rank = confidence_rank.get(str(existing), 0)
        new_rank = confidence_rank.get(new_conf, 0)
        if str(existing) == "VALIDATED_EXTERNAL":
            # never override
            adjusted.append({**a, "claim_confidence": existing})
            continue
        adjusted.append(
            {
                **a,
                "claim_confidence": (new_conf if new_rank > current_rank else str(existing)),
            }
        )
    return adjusted
