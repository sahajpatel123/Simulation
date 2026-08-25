"""Periodic credential-hygiene maintenance.

The auth flows never delete token rows — refresh tokens accumulate one row
per login/rotation and API tokens keep their metadata after revocation or
expiry. Left alone both tables grow without bound while keeping dead
credential hashes forever, which widens the offline-cracking target after
any future database leak. The sweep here removes rows that have been
unusable (revoked or expired) for longer than the retention window, so
recent history survives for reuse-detection forensics while truly dead
credentials stop accumulating.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# Dead rows stay for this many days after becoming unusable — long enough
# for incident forensics around reuse-detection events, short enough that
# the table tracks live sessions rather than all-time history.
REFRESH_TOKEN_RETENTION_DAYS = 90

# Alias kept for readability at the call sites below; both credential
# families share the same retention policy on purpose.
API_TOKEN_RETENTION_DAYS = REFRESH_TOKEN_RETENTION_DAYS


def purge_cutoff(now: datetime | None = None) -> datetime:
    """Return the UTC instant before which a dead token row may be deleted."""
    base = now or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    return base - timedelta(days=REFRESH_TOKEN_RETENTION_DAYS)


@celery_app.task(name="maintenance.purge_stale_auth_tokens")
def purge_stale_auth_tokens() -> dict[str, int]:
    """Delete dead refresh- and API-token rows past the retention window.

    Refresh tokens have three stale shapes: revoked with a stamped
    ``revoked_at``, legacy rows revoked before that column existed (their
    ``expires_at`` is the best available death bound), and rows that simply
    expired unused. API tokens are stale once revoked or expired. Live
    tokens match none of these predicates and are never touched.
    """
    cutoff = purge_cutoff()
    db = SessionLocal()
    try:
        refreshed = db.execute(
            text(
                """
                DELETE FROM refresh_tokens
                WHERE (revoked = TRUE AND revoked_at IS NOT NULL AND revoked_at < :cutoff)
                   OR (revoked = TRUE AND revoked_at IS NULL AND expires_at < :cutoff)
                   OR (revoked = FALSE AND expires_at < :cutoff)
                """
            ),
            {"cutoff": cutoff},
        )
        api_rows = db.execute(
            text(
                """
                DELETE FROM api_tokens
                WHERE (revoked_at IS NOT NULL AND revoked_at < :cutoff)
                   OR (revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at < :cutoff)
                """
            ),
            {"cutoff": cutoff},
        )
        db.commit()
        deleted_refresh = int(refreshed.rowcount or 0)
        deleted_api = int(api_rows.rowcount or 0)
        logger.info(
            "Purged %d stale refresh-token and %d stale API-token rows (retention=%dd, cutoff=%s)",
            deleted_refresh,
            deleted_api,
            API_TOKEN_RETENTION_DAYS,
            cutoff.isoformat(),
        )
        return {"refresh_tokens": deleted_refresh, "api_tokens": deleted_api}
    except Exception:
        db.rollback()
        logger.exception("Stale auth-token purge failed")
        raise
    finally:
        db.close()
