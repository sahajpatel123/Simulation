"""Shared utility functions for TheCee backend."""

import json
import logging

logger = logging.getLogger(__name__)


def extract_json_from_markdown(raw: str) -> str:
    """Strip markdown code fences from a raw
    Claude response and return clean JSON string.

    Handles both ```json and ``` variants.
    """
    if not raw or not raw.strip().startswith("```"):
        return raw
    lines = raw.split("\n")
    cleaned = [
        line for line in lines
        if not line.strip().startswith("```")
    ]
    return "\n".join(cleaned)


def safe_parse_json(raw: str) -> dict | list:
    """Strip fences then parse JSON.

    On success returns a dict or list as parsed from the payload.
    On failure returns an empty dict and logs a warning.
    """
    try:
        return json.loads(extract_json_from_markdown(raw))
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "safe_parse_json failed: %s | raw[:120]=%s",
            e,
            str(raw)[:120],
        )
        return {}


def geo_tier(geo: str) -> str:
    """Classify a geography string into tier3,
    tier2, or metro. Shared by multiple architects.

    Examples:
        geo_tier("tier3_rural_mp") -> "tier3"
        geo_tier("tier2_pune")     -> "tier2"
        geo_tier("delhi_metro")    -> "metro"
    """
    geo = geo.lower()
    if "tier3" in geo or "rural" in geo:
        return "tier3"
    if "tier2" in geo:
        return "tier2"
    return "metro"