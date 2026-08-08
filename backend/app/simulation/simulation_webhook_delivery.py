"""Signed delivery helpers for simulation-completion webhooks.

The Celery worker uses :func:`deliver_webhook_event` after a simulation
finishes (or exhausts its retries) so founders get a push-style
notification without having to poll the API. Delivery is intentionally
non-fatal: a bad webhook endpoint never fails the simulation itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def build_webhook_payload(
    *,
    event_type: str,
    simulation_id: int,
    project_id: int,
    status: str,
    conversion_rate: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON body sent to a subscribed webhook endpoint."""
    payload: dict[str, Any] = {
        "event": event_type,
        "simulation_id": simulation_id,
        "project_id": project_id,
        "status": status,
        "timestamp": int(time.time()),
    }
    if conversion_rate is not None:
        payload["conversion_rate"] = round(float(conversion_rate), 6)
    if error:
        payload["error"] = error[:500]
    return payload


def sign_webhook_payload(secret: str, payload: dict[str, Any]) -> str:
    """Return an HMAC-SHA256 signature for a JSON payload."""
    message = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def deliver_webhook_event(
    *,
    url: str,
    secret: str,
    payload: dict[str, Any],
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """POST ``payload`` to ``url`` with an HMAC signature header.

    Returns ``{"ok": True, "status_code": int}`` on 2xx and
    ``{"ok": False, "error": str}`` otherwise. Never raises — the caller
    decides whether a delivery failure should surface (e.g. ping) or be
    swallowed (background delivery).
    """
    signature = sign_webhook_payload(secret, payload)
    headers = {
        "Content-Type": "application/json",
        "X-TheCee-Signature": f"sha256={signature}",
        "User-Agent": "TheCee-Simulation-Webhook/1.0",
    }
    body = json.dumps(payload).encode("utf-8")
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, content=body, headers=headers)
        status_code = int(response.status_code)
        if 200 <= status_code < 300:
            return {"ok": True, "status_code": status_code}
        return {
            "ok": False,
            "error": f"webhook endpoint returned HTTP {status_code}",
        }
    except Exception as exc:  # noqa: BLE001 - delivery is best-effort by design
        logger.warning(
            "[Webhook] Delivery failed url=%s error=%s",
            url,
            str(exc)[:300],
        )
        return {"ok": False, "error": str(exc)[:500]}
