from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic

from app.core.config import settings
from app.core.prompts import (
    HARDWARE_SPEC_PROMPT,
    HARDWARE_SPEC_REFINE_HEAD,
    HARDWARE_SPEC_REFINE_TAIL,
    validate_hardware_spec,
)


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

    def _complete_spec_from_prompt(self, prompt: str) -> dict[str, Any]:
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

    def generate_spec(
        self,
        description: str,
        category: str,
        price: float | int,
        material_preference: str | None = None,
        dimensions_rough: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = ""
        if material_preference and str(material_preference).strip():
            extra += f"\n\nFounder material preference:\n{str(material_preference).strip()}"
        if dimensions_rough is not None:
            if isinstance(dimensions_rough, dict):
                extra += (
                    "\n\nRough dimensions / envelope notes (JSON):\n"
                    f"{json.dumps(dimensions_rough, ensure_ascii=False)}"
                )
            elif str(dimensions_rough).strip():
                extra += f"\n\nRough dimensions / form factor:\n{str(dimensions_rough).strip()}"
        prompt = (
            HARDWARE_SPEC_PROMPT.format(
                description=description.strip(),
                category=category.strip(),
                price=price,
            )
            + extra
        )
        return self._complete_spec_from_prompt(prompt)

    def refine_spec(
        self,
        existing_spec: dict[str, Any],
        refinement_prompt: str,
    ) -> dict[str, Any]:
        prompt = (
            HARDWARE_SPEC_REFINE_HEAD
            + json.dumps(existing_spec, ensure_ascii=False)
            + HARDWARE_SPEC_REFINE_TAIL.format(
                refinement_prompt=refinement_prompt.strip(),
            )
        )
        return self._complete_spec_from_prompt(prompt)
