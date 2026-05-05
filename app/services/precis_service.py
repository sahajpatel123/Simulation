"""
Précis name generation service.
Compresses a raw idea into a 5-word maximum 
product name using Claude Haiku 4.5.
"""

import logging

from anthropic import Anthropic

from app.core.config import settings
from app.core.prompts import PRECIS_NAME_PROMPT

logger = logging.getLogger(__name__)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def generate_precis_name(
    title: str,
    description: str,
) -> str | None:
    """
    Generate a compressed 5-word-max product name
    from the raw idea title and description.
    
    Returns the name string on success.
    Returns None on any failure — callers must 
    handle None gracefully.
    
    Never raises — all exceptions are logged 
    and suppressed.
    """
    raw_idea = description.strip() or title.strip()
    if not raw_idea:
        return None

    prompt = f"{PRECIS_NAME_PROMPT}\n\n{raw_idea}"

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )
        name = response.content[0].text.strip()
        name = name.strip('"').strip("'").strip()
        words = name.split()
        if len(words) > 5:
            name = " ".join(words[:5])
        return name if name else None
    except Exception as exc:
        logger.debug(
            "precis_service: generation suppressed: %s",
            exc,
        )
        return None