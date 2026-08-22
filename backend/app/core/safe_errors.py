"""Sanitize exception details for anything crossing a trust boundary.

Exception *messages* routinely embed infrastructure internals — SQL
fragments, host names, broker URLs, file paths. Raw ``str(exc)`` must
never flow into an API response or client-facing payload; full detail
belongs in server-side logs, where diagnosis happens.
"""

from __future__ import annotations


def safe_error_label(exc: BaseException) -> str:
    """Return the exception class name for client-visible error fields.

    Keeps operator signal (``OperationalError`` vs ``TimeoutError`` vs
    ``ConnectionRefusedError`` still distinguish a degraded dependency)
    while leaking none of the message content.
    """
    return type(exc).__name__
