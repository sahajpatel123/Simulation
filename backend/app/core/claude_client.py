"""LLM client.

This module is named ``claude_client`` for historical reasons; while in the
development phase the project routes every call through NVIDIA NIMs (OpenAI-
compatible). The public function ``claude_call_with_fallback`` keeps its
original signature so all call sites continue to work unchanged.

Environment:
- NVIDIA_API_KEY  (required)
- NVIDIA_BASE_URL (default: https://integrate.api.nvidia.com/v1)
- NVIDIA_MODEL    (default: meta/llama-3.3-70b-instruct)
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


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy-construct the OpenAI client pointed at NVIDIA NIM.

    Lazy so a missing key at import time doesn't crash the worker; the call
    site gets a clean error string via the fallback path instead.
    """
    global _client
    if _client is None:
        api_key = (settings.NVIDIA_API_KEY or "").strip()
        if not api_key:
            raise RuntimeError(
                "NVIDIA_API_KEY is not configured. Set it in the deployment environment."
            )
        base_url = (settings.NVIDIA_BASE_URL or "https://integrate.api.nvidia.com/v1").strip()
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def _resolve_model(model: str) -> str:
    """Map legacy Anthropic model strings to the configured NVIDIA NIM model.

    Callers across the codebase still pass ``claude-sonnet-4-…`` /
    ``claude-haiku-4-5-…`` model names. Rather than touching every call site,
    we route them all to the configured NVIDIA model. Pass-through for any
    name that already looks like a NIM model id (contains ``/``).
    """
    if model and "/" in model:
        return model
    if model and model.lower().startswith("claude-haiku"):
        return settings.NVIDIA_FAST_MODEL or settings.NVIDIA_MODEL
    return settings.NVIDIA_MODEL


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
    """Call the configured LLM provider (NVIDIA NIM) and return ``{"content": str, "error": None}``.

    On timeout or API error returns the static fallback registered under
    ``fallback_key`` so call sites can degrade gracefully.
    """
    try:
        client = _get_client()
    except RuntimeError as exc:
        logger.error("LLM client init failed: %s", exc)
        return TIMEOUT_FALLBACK.get(fallback_key, {"error": str(exc)})

    nim_model = _resolve_model(model)
    chat_messages = _build_messages(messages, system)

    try:
        resp = client.chat.completions.create(
            model=nim_model,
            messages=chat_messages,
            max_tokens=max_tokens,
            timeout=float(timeout),
        )
        text = ""
        if resp.choices:
            text = (resp.choices[0].message.content or "").strip()
        return {"content": text, "error": None}
    except APITimeoutError:
        logger.warning("NIM timeout on %s (model=%s)", fallback_key, nim_model)
        return TIMEOUT_FALLBACK.get(fallback_key, {"error": "timeout"})
    except APIError as e:
        sc = getattr(e, "status_code", None)
        logger.error("NIM API error on %s: status=%s err=%s", fallback_key, sc, e)
        return TIMEOUT_FALLBACK.get(
            fallback_key, {"error": str(sc) if sc is not None else str(e)}
        )
    except Exception as e:  # noqa: BLE001 — last-resort: never let the LLM crash a request.
        logger.exception("NIM unexpected error on %s: %s", fallback_key, e)
        return TIMEOUT_FALLBACK.get(fallback_key, {"error": str(e)})
