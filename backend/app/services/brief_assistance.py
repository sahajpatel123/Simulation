"""
Brief assistance service for TheCee.
Supports three modes: refine, suggest, critique.
Each operates on one field at a time.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from anthropic import Anthropic

from app.core.config import settings
from app.core.prompts import (
    BRIEF_CRITIQUE_SYSTEM,
    BRIEF_REFINE_SYSTEM,
    BRIEF_SUGGEST_SYSTEM,
)

logger = logging.getLogger(__name__)

_client: Anthropic | None = None

BRIEF_MODEL = os.getenv(
    "BRIEF_MODEL",
    "claude-haiku-4-5-20251001",
)

FieldName = Literal["positioning", "features", "hook"]
Mode = Literal["refine", "suggest", "critique"]


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


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
        max_tokens = 200
    elif mode == "suggest":
        system = BRIEF_SUGGEST_SYSTEM
        user_msg = (
            f"Field: {field_ctx}\n\n"
            f"Dossier title: {dossier_title}\n"
            f"Dossier idea: {dossier_description}\n\n"
            f"Return 3 distinct options as a "
            f"JSON array of strings."
        )
        max_tokens = 400
    elif mode == "critique":
        if not current_value.strip():
            return {}
        system = BRIEF_CRITIQUE_SYSTEM
        user_msg = (
            f"Field: {field_ctx}\n\n"
            f"Founder's draft:\n{current_value}\n\n"
            f"Critique:"
        )
        max_tokens = 250
    else:
        return {}

    try:
        client = _get_client()
        response = client.messages.create(
            model=BRIEF_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        text = text.strip("```json").strip("```").strip()

        if mode == "suggest":
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return {"mode": mode, "result": [str(s) for s in parsed[:3]]}
            except json.JSONDecodeError:
                return {}
            return {}

        return {"mode": mode, "result": text}

    except Exception as exc:
        logger.warning("brief_assistance: %s/%s failed: %s", mode, field, exc)
        return {}
