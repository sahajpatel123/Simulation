"""Periodic credential-hygiene maintenance.

The auth flows never delete refresh-token rows — every login and every
rotation inserts one and only flips ``revoked``. Left alone the table
grows without bound while keeping dead credential hashes forever, which
widens the offline-cracking target after any future database leak. The
purge here removes rows that have been unusable (revoked or expired) for
longer than the retention window, so recent history survives for reuse-
detection forensics while truly dead credentials stop accumulating.
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


def purge_cutoff(now: datetime | None = None) -> datetime:
    """Return the UTC instant before which a dead token row may be deleted."""
    base = now or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    return base - timedelta(days=REFRESH_TOKEN_RETENTION_DAYS)


@celery_app.task(name="maintenance.purge_stale_refresh_tokens")
def purge_stale_refresh_tokens() -> dict[str, int]:
    """Delete refresh-token rows dead for longer than the retention window.

    Three stale shapes exist: revoked with a stamped ``revoked_at``, legacy
    rows revoked before that column existed (their ``expires_at`` is the
    best available death bound), and rows that simply expired unused. Live
    tokens match none of these and are never touched.
    """
    cutoff = purge_cutoff()
    db = SessionLocal()
    try:
        result = db.execute(
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
        db.commit()
        deleted = int(result.rowcount or 0)
        logger.info(
            "Purged %d stale refresh-token rows (retention=%dd, cutoff=%s)",
            deleted,
            REFRESH_TOKEN_RETENTION_DAYS,
            cutoff.isoformat(),
        )
        return {"deleted": deleted}
    except Exception:
        db.rollback()
        logger.exception("Stale refresh-token purge failed")
        raise
    finally:
        db.close()
