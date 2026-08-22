"""Regression tests: hardware spec generation must not leak provider error text.

``model_generator`` used to raise ``RuntimeError(f"Claude call failed: {e}")``
and ``RuntimeError(str(out["error"]))``, which ``hardware.py`` forwarded
verbatim as 502 response details. Upstream errors can embed request IDs,
account identifiers, and URLs — the generator now raises fixed safe labels
and keeps full detail server-side.
"""

from __future__ import annotations

import pytest

import app.hardware.model_generator as model_generator_module
from app.hardware.model_generator import HardwareModelGenerator


def _patch_fallback(monkeypatch: pytest.MonkeyPatch, out: dict) -> None:
    monkeypatch.setattr(
        model_generator_module, "claude_call_with_fallback", lambda *a, **k: out
    )


def test_provider_error_field_never_reaches_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fallback(
        monkeypatch,
        {"error": "401 from account acct_987654 internal-token=zzz-secret"},
    )
    gen = HardwareModelGenerator()

    with pytest.raises(RuntimeError) as excinfo:
        gen._complete_spec_from_prompt("generate a spec")

    assert str(excinfo.value) == "ClaudeUnavailable"
    assert "acct_987654" not in str(excinfo.value)
    assert "zzz-secret" not in str(excinfo.value)


def test_underlying_exception_text_never_reaches_raised_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> dict:
        raise TimeoutError("connect failed https://api.provider.com/v1?key=sk-live-abc")

    monkeypatch.setattr(
        model_generator_module, "claude_call_with_fallback", boom
    )
    gen = HardwareModelGenerator()

    with pytest.raises(RuntimeError) as excinfo:
        gen._complete_spec_from_prompt("generate a spec")

    assert str(excinfo.value) == "ClaudeCallFailed"
    assert "sk-live-abc" not in str(excinfo.value)
