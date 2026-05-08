"""LLM client.

This module is named ``claude_client`` for historical reasons; the project
routes every call through xAI Grok (OpenAI-compatible API). The public
function ``claude_call_with_fallback`` keeps its original signature so all
call sites continue to work unchanged.

Environment:
- GROK_API_KEY   (required)
- GROK_BASE_URL  (default: https://api.x.ai/v1)
- GROK_MODEL     (default: grok-3-mini)
"""

from __future__ import annotations

import logging
from typing import Any

from openai import APIError, APITimeoutError, OpenAI

from app.core.config import settings

logger = logging.getLogger("thecee.llm")

TIMEOUT_FALLBACK: dict[str, dict[str, Any]] = {
    "assumption_extraction": {"assumptions": [], "error": "LLM timeout — try again"},
    "ui_generation": {"html": "<p>Generation timed out. Please retry.</p>", "error": "timeout"},
    "hardware_spec": {"components": [], "error": "LLM timeout — try again"},
    "engineering_plate": {
        "project": "—",
        "category": "—",
        "components": "—",
        "est_mass": "—",
        "scale": "—",
        "error": "timeout",
    },
    "prototype_generation": {"error": "LLM timeout — try again"},
    "premortem": {"error": "LLM timeout — try again"},
    "interventions": {"error": "LLM timeout — try again"},
    "competitive": {"error": "LLM timeout — try again"},
    "intake_landing": {"error": "LLM timeout — try again"},
}


def _error_fallback(fallback_key: str, error_msg: str) -> dict[str, Any]:
    """Build a response that preserves the registered fallback structure but
    injects the *real* error message instead of the generic timeout string.

    Without this, TIMEOUT_FALLBACK.get(key, default) silently discards the
    default whenever the key exists — so auth errors (401), validation errors
    (422), and a missing API key all surface as "Generation timed out." to the
    frontend, making them impossible to diagnose.
    """
    base = dict(TIMEOUT_FALLBACK.get(fallback_key, {}))
    base["error"] = error_msg
    return base or {"error": error_msg}


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy-construct the OpenAI client pointed at xAI Grok.

    Lazy so a missing key at import time doesn't crash the worker; the call
    site gets a clean error string via the fallback path instead.
    """
    global _client
    if _client is None:
        api_key = (settings.GROK_API_KEY or "").strip()
        if not api_key:
            raise RuntimeError(
                "GROK_API_KEY is not configured. Set it in the deployment environment."
            )
        base_url = (settings.GROK_BASE_URL or "https://api.x.ai/v1").strip()
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def _resolve_model(model: str) -> str:
    """Map legacy Anthropic model strings to the configured Grok model.

    Callers across the codebase still pass ``claude-sonnet-4-…`` /
    ``claude-haiku-4-5-…`` model names. Rather than touching every call site,
    we route them all to the configured Grok model. Pass-through for any
    name that already looks like a provider model id (contains ``/`` or ``grok``).
    """
    if model and ("/" in model or "grok" in model.lower()):
        return model
    if model and model.lower().startswith("claude-haiku"):
        return settings.GROK_FAST_MODEL or settings.GROK_MODEL
    return settings.GROK_MODEL


def _build_messages(
    messages: list[dict],
    system: str | None,
) -> list[dict]:
    """Translate Anthropic-style messages to OpenAI chat-completions format.

    Anthropic and OpenAI both use {role, content} but Anthropic carries the
    system prompt as a top-level kwarg; OpenAI carries it as the first
    message with role=system. Coerce dict content blocks to plain text.
    """
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # Anthropic content-blocks → flatten to text.
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    t = block.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            content = "".join(parts)
        out.append({"role": role, "content": content if isinstance(content, str) else str(content)})
    return out


def claude_call_with_fallback(
    messages: list[dict],
    *,
    system: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1000,
    fallback_key: str = "assumption_extraction",
    timeout: int = 30,
) -> dict[str, Any]:
    """Call the configured LLM provider (xAI Grok) and return ``{"content": str, "error": None}``.

    On timeout or API error returns the static fallback registered under
    ``fallback_key`` so call sites can degrade gracefully.
    """
    try:
        client = _get_client()
    except RuntimeError as exc:
        logger.error("LLM client init failed: %s", exc)
        return _error_fallback(fallback_key, str(exc))

    grok_model = _resolve_model(model)
    chat_messages = _build_messages(messages, system)

    try:
        resp = client.chat.completions.create(
            model=grok_model,
            messages=chat_messages,
            max_tokens=max_tokens,
            timeout=float(timeout),
        )
        text = ""
        if resp.choices:
            text = (resp.choices[0].message.content or "").strip()
        return {"content": text, "error": None}
    except APITimeoutError:
        logger.warning("Grok timeout on %s (model=%s)", fallback_key, grok_model)
        return TIMEOUT_FALLBACK.get(fallback_key, {"error": "timeout"})
    except APIError as e:
        sc = getattr(e, "status_code", None)
        logger.error("Grok API error on %s: status=%s err=%s", fallback_key, sc, e)
        error_msg = f"API error {sc}: {e}" if sc is not None else str(e)
        return _error_fallback(fallback_key, error_msg)
    except Exception as e:  # noqa: BLE001 — last-resort: never let the LLM crash a request.
        logger.exception("Grok unexpected error on %s: %s", fallback_key, e)
        return _error_fallback(fallback_key, str(e))
