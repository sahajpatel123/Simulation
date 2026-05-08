"""Dossier intelligence generation. Generates the editorial Précis, structured
Readings, and a small précis-ledger (deck line + rubrics).

All LLM calls are routed through xAI Grok via ``claude_call_with_fallback``
(the historical helper name is preserved across the codebase to avoid
touching every call site).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.claude_client import claude_call_with_fallback
from app.core.prompts import DISPLAY_PRECIS_SYSTEM, build_display_precis_user_message
from app.core.utils import safe_parse_json

logger = logging.getLogger(__name__)

READINGS_SYSTEM = """You are an editor at TheCee performing a first read of a founder's idea. Surface 4 short structured observations in JSON format.

OUTPUT FORMAT — return ONLY a JSON array, nothing else:
[
  {"label": "WHAT IT IS",        "body": "<one short clause, ≤12 words>"},
  {"label": "WHY IT MATTERS",    "body": "<one short clause, ≤12 words>"},
  {"label": "HIDDEN TENSION",    "body": "<one short clause naming the unstated risk, ≤14 words>"},
  {"label": "UNTESTED CLAIM",    "body": "<one short clause, ≤14 words>"}
]

RULES:
- Each body must be a complete clause but short.
- HIDDEN TENSION must be sharp — name what the founder is not seeing.
- UNTESTED CLAIM must point to an assumption that needs evidence.
- Editorial tone, no sycophancy, no hedging.
- Return ONLY the JSON array. No markdown fences. No commentary."""

LEDGER_SYSTEM = """You are the desk editor at TheCee. From the founder's title and description, write four very short rubrics for the printed précis folio slip.

Return ONLY this JSON object (no markdown fences, no commentary):
{
  "deck_line": "<=8 words — formal folio line; not a tagline; no quotes>",
  "section_rubric": "<=10 words — which desk section this belongs in>",
  "status_rubric": "<=10 words — editorial status of the submission>",
  "folio_blurb": "<=18 words — one line for the folio path margin; may reference software vs hardware if clear>"
}

RULES:
- Do not invent product facts absent from the source.
- British English is fine; stay crisp and unsentimental.
- Values must be plain strings (no nested objects)."""


def _llm_text(
    *,
    system: str,
    user_msg: str,
    max_tokens: int,
    fallback_key: str,
    timeout: int = 30,
) -> str:
    """Single-turn LLM call returning trimmed text or ''."""
    out = claude_call_with_fallback(
        [{"role": "user", "content": user_msg}],
        system=system,
        model="claude-haiku-4-5",  # symbolic; routed to Grok by the client
        max_tokens=max_tokens,
        fallback_key=fallback_key,
        timeout=timeout,
    )
    if out.get("error"):
        return ""
    return (out.get("content") or "").strip()


def generate_precis(title: str, description: str) -> str:
    """Generate a shortened editorial line from the raw idea."""
    user_msg = build_display_precis_user_message(title, description)
    try:
        text = _llm_text(
            system=DISPLAY_PRECIS_SYSTEM,
            user_msg=user_msg,
            max_tokens=96,
            fallback_key="intake_landing",
        )
        return text.strip('"').strip("'").strip()
    except Exception as exc:
        logger.warning("precis generation failed: %s", exc)
        return ""


def generate_readings(title: str, description: str) -> list[dict[str, str]]:
    """Generate structured readings as a list of {label, body} dicts."""
    user_msg = f"Idea:\nTitle: {title}\n\nDescription: {description}\n\nReturn the JSON array of 4 readings."
    try:
        text = _llm_text(
            system=READINGS_SYSTEM,
            user_msg=user_msg,
            max_tokens=400,
            fallback_key="intake_landing",
        )
        parsed = safe_parse_json(text)
        if isinstance(parsed, list) and all(
            isinstance(p, dict) and "label" in p and "body" in p for p in parsed
        ):
            return [
                {
                    "label": str(p.get("label", "")).strip(),
                    "body": str(p.get("body", "")).strip(),
                }
                for p in parsed[:4]
            ]
        if isinstance(parsed, dict) and "readings" in parsed:
            inner = parsed["readings"]
            if isinstance(inner, list) and all(
                isinstance(p, dict) and "label" in p and "body" in p for p in inner
            ):
                return [
                    {
                        "label": str(p.get("label", "")).strip(),
                        "body": str(p.get("body", "")).strip(),
                    }
                    for p in inner[:4]
                ]
        return []
    except Exception as exc:
        logger.warning("readings generation failed: %s", exc)
        return []


def generate_ledger(title: str, description: str) -> dict[str, str]:
    """Short rubrics for the précis folio slip (deck line + margins)."""
    user_msg = (
        f"Title: {title}\n\nDescription: {description}\n\nReturn the JSON object only."
    )
    keys = ("deck_line", "section_rubric", "status_rubric", "folio_blurb")
    try:
        text = _llm_text(
            system=LEDGER_SYSTEM,
            user_msg=user_msg,
            max_tokens=220,
            fallback_key="intake_landing",
        )
        parsed = safe_parse_json(text)
        if not isinstance(parsed, dict):
            return {}
        out: dict[str, str] = {}
        for k in keys:
            v = parsed.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
        return out
    except Exception as exc:
        logger.warning("ledger generation failed: %s", exc)
        return {}


def readings_json_payload(
    readings: list[dict[str, Any]],
    ledger: dict[str, str],
) -> str | None:
    """Serialize readings + ledger for ``projects.readings_json``.

    Legacy rows may store a bare JSON array; new rows use an object
    ``{"readings": [...], "ledger": {...}}``.
    """
    readings = readings or []
    ledger = {k: v for k, v in (ledger or {}).items() if v}
    if not readings and not ledger:
        return None
    return json.dumps({"readings": readings, "ledger": ledger})


def generate_both(title: str, description: str) -> dict[str, Any]:
    """Returns precis, readings list, and ledger dict (any may be empty).

    Runs the three Haiku calls concurrently to keep dossier create/regenerate
    latency closer to a single round-trip.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_precis = pool.submit(generate_precis, title, description)
        fut_readings = pool.submit(generate_readings, title, description)
        fut_ledger = pool.submit(generate_ledger, title, description)
        precis = fut_precis.result()
        readings = fut_readings.result()
        ledger = fut_ledger.result()
    if not readings:
        readings = generate_readings(title, description)
    return {
        "precis": precis,
        "readings": readings,
        "ledger": ledger,
    }
