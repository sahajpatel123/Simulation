from __future__ import annotations

import logging
from typing import Any

from anthropic import APIError, Anthropic, APITimeoutError

from app.core.config import settings

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
logger = logging.getLogger("thecee.claude")

TIMEOUT_FALLBACK: dict[str, dict[str, Any]] = {
    "assumption_extraction": {"assumptions": [], "error": "Claude timeout — try again"},
    "ui_generation": {"html": "<p>Generation timed out. Please retry.</p>", "error": "timeout"},
    "hardware_spec": {"components": [], "error": "Claude timeout — try again"},
    "engineering_plate": {
        "project": "—",
        "category": "—",
        "components": "—",
        "est_mass": "—",
        "scale": "—",
        "error": "timeout",
    },
    "prototype_generation": {"error": "Claude timeout — try again"},
    "premortem": {"error": "Claude timeout — try again"},
    "interventions": {"error": "Claude timeout — try again"},
    "competitive": {"error": "Claude timeout — try again"},
    "intake_landing": {"error": "Claude timeout — try again"},
}


def _message_text_blocks(resp: Any) -> str:
    parts: list[str] = []
    for block in resp.content or []:
        t = getattr(block, "text", None)
        if t:
            parts.append(t)
    return "".join(parts).strip()


def claude_call_with_fallback(
    messages: list[dict],
    *,
    system: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1000,
    fallback_key: str = "assumption_extraction",
    timeout: int = 30,
) -> dict[str, Any]:
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "timeout": float(timeout),
        }
        if system is not None:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return {"content": _message_text_blocks(resp), "error": None}
    except APITimeoutError:
        logger.warning("Claude timeout on %s", fallback_key)
        return TIMEOUT_FALLBACK.get(fallback_key, {"error": "timeout"})
    except APIError as e:
        sc = getattr(e, "status_code", None)
        logger.error("Claude API error: %s", sc)
        return TIMEOUT_FALLBACK.get(
            fallback_key, {"error": str(sc) if sc is not None else str(e)}
        )
