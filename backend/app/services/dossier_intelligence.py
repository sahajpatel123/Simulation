"""Dossier intelligence generation using Claude
Haiku 4.5. Generates the editorial Précis and
structured Readings for a project."""

import logging
from anthropic import Anthropic
from app.core.config import settings
from app.core.utils import safe_parse_json

logger = logging.getLogger(__name__)

_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

PRECIS_SYSTEM = """You are an editor at TheCee, an editorial product validation paper. Your job is to rewrite a founder's raw idea description into a sharp, polished one-sentence editorial line.

RULES:
- Output exactly ONE sentence, between 6 and 14 words.
- Remove filler like "I want to make", "I'm building", "we are creating".
- Fix grammar mistakes silently.
- Keep the actual substance (what it is, who it's for if mentioned).
- Editorial voice — like a magazine subhead, not a tagline.
- No buzzwords like "revolutionary", "next-gen", "cutting-edge".
- Do not invent details that are not in the source.
- Output ONLY the rewritten sentence. No quotes, no explanation, no preamble."""

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


def generate_precis(title: str, description: str) -> str:
    """Generate a shortened editorial line from the
    raw idea. Returns the polished sentence."""
    user_msg = f"Raw idea:\nTitle: {title}\n\nDescription: {description}\n\nWrite the one-sentence Précis."

    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=PRECIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        text = text.strip('"').strip("'").strip()
        return text
    except Exception as exc:
        logger.warning("precis generation failed: %s", exc)
        return ""


def generate_readings(title: str, description: str) -> list[dict]:
    """Generate structured readings as a list of
    {label, body} dicts. Returns empty list on
    failure."""
    user_msg = f"Idea:\nTitle: {title}\n\nDescription: {description}\n\nReturn the JSON array of 4 readings."

    try:
        response = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=READINGS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        parsed = safe_parse_json(text)
        if isinstance(parsed, list) and all(
            isinstance(p, dict) and "label" in p and "body" in p
            for p in parsed
        ):
            return parsed[:4]
        if isinstance(parsed, dict) and "readings" in parsed:
            return parsed["readings"][:4]
        return []
    except Exception as exc:
        logger.warning("readings generation failed: %s", exc)
        return []


def generate_both(title: str, description: str) -> dict:
    """Convenience wrapper. Returns both fields
    in one call. Either may be empty on failure."""
    return {
        "precis": generate_precis(title, description),
        "readings": generate_readings(title, description),
    }