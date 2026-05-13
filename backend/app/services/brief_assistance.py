"""
Brief assistance service for TheCee.
Supports three modes: refine, suggest, critique.
Each operates on one field at a time.

Uses the project's primary LLM provider (Grok via claude_call_with_fallback)
rather than hardcoding Anthropic, so it works with whatever API key is configured.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from app.core.claude_client import claude_call_with_fallback
from app.core.prompts import (
    BRIEF_CRITIQUE_SYSTEM,
    BRIEF_REFINE_SYSTEM,
    BRIEF_SUGGEST_SYSTEM,
)

logger = logging.getLogger(__name__)

FieldName = Literal["positioning", "features", "hook"]
Mode = Literal["refine", "suggest", "critique"]


def _field_context(field: FieldName) -> str:
    if field == "positioning":
        return (
            "POSITIONING — one sentence: "
            "who this is for and what it does. "
            "Strong positioning names the user "
            "and the outcome, not the technology."
        )
    if field == "features":
        return (
            "FEATURES — three defining capabilities, "
            "ranked by importance. Each feature is "
            "a short noun phrase, not a sentence."
        )
    if field == "hook":
        return (
            "HOOK — one sentence, 6-12 words. "
            "The single line that makes a stranger "
            "want to know more. No buzzwords."
        )
    return ""


def assist(
    mode: Mode,
    field: FieldName,
    dossier_title: str,
    dossier_description: str,
    current_value: str = "",
) -> dict:
    """
    Returns:
      {"mode": "refine",   "result": str}
      {"mode": "suggest",  "result": list[str]}
      {"mode": "critique", "result": str}
    Empty dict on failure.
    """
    _ = dossier_title
    field_ctx = _field_context(field)

    if mode == "refine":
        if not current_value.strip():
            return {}
        system = BRIEF_REFINE_SYSTEM
        user_msg = (
            f"Field: {field_ctx}\n\n"
            f"Dossier idea: {dossier_description}\n\n"
            f"Founder's draft:\n{current_value}\n\n"
            f"Refined version:"
        )
    elif mode == "suggest":
        system = BRIEF_SUGGEST_SYSTEM
        user_msg = (
            f"Field: {field_ctx}\n\n"
            f"Dossier title: {dossier_title}\n"
            f"Dossier idea: {dossier_description}\n\n"
            f"Return 3 distinct options as a "
            f"JSON array of strings."
        )
    elif mode == "critique":
        if not current_value.strip():
            return {}
        system = BRIEF_CRITIQUE_SYSTEM
        user_msg = (
            f"Field: {field_ctx}\n\n"
            f"Founder's draft:\n{current_value}\n\n"
            f"Critique:"
        )
    else:
        return {}

    try:
        out = claude_call_with_fallback(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            max_tokens=400,
            fallback_key="brief_assistance",
        )
        text = (out.get("content") or "").strip()
        if not text:
            return {}

        if mode == "suggest":
            cleaned = text.strip("```json").strip("```").strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    return {"mode": mode, "result": [str(s) for s in parsed[:3]]}
            except json.JSONDecodeError:
                pass
            return {}

        return {"mode": mode, "result": text}

    except Exception as exc:
        logger.warning("brief_assistance: %s/%s failed: %s", mode, field, exc)
        return {}
