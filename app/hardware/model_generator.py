from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic

from app.core.config import settings
from app.core.prompts import HARDWARE_SPEC_PROMPT, validate_hardware_spec


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.strip().startswith("```"))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in Claude response")
    return json.loads(match.group(0))


class HardwareModelGenerator:
    """
    Step 70 — semantic "3D" product spec (JSON), not mesh generation.

    Produces the locked schema validated by ``validate_hardware_spec`` for
    viewer, physics, failure overlay, and cost steps downstream.
    """

    def __init__(self, client: Anthropic | None = None) -> None:
        self._client = client or Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate_spec(
        self,
        description: str,
        category: str,
        price: float | int,
    ) -> dict[str, Any]:
        prompt = HARDWARE_SPEC_PROMPT.format(
            description=description.strip(),
            category=category.strip(),
            price=price,
        )
        try:
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
        except Exception as e:
            raise RuntimeError(f"Claude call failed: {e}") from e

        try:
            spec = _extract_json_object(raw)
        except json.JSONDecodeError as e:
            raise ValueError("Claude returned malformed JSON") from e

        ok, err = validate_hardware_spec(spec)
        if not ok:
            raise ValueError(f"Hardware spec failed validation: {err}")
        return spec
