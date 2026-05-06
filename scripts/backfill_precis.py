"""
One-time backfill script.
Generates précis names for all existing projects 
that have NULL precis.

Usage:
    python -m scripts.backfill_precis

Safe to re-run — only processes NULL records.
"""

import logging
import sys
import time

from app.core.database import SessionLocal
from app.models.project import Project
from app.services.precis_service import (
    generate_precis_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")


def main() -> int:
    db = SessionLocal()
    try:
        targets = (
            db.query(Project)
            .filter(Project.precis.is_(None))
            .order_by(Project.id.asc())
            .all()
        )
    except Exception as exc:
        log.error("query failed: %s", exc)
        db.close()
        return 1

    total = len(targets)
    if total == 0:
        log.info("nothing to backfill — all projects have précis")
        db.close()
        return 0

    log.info("backfilling %d projects", total)
    succeeded = 0
    failed = 0

    for idx, project in enumerate(targets, start=1):
        try:
            precis = generate_precis_name(
                project.title,
                project.description,
            )
            if precis:
                project.precis = precis
                db.commit()
                db.refresh(project)
                succeeded += 1
                log.info(
                    "[%d/%d] id=%d ✓ %r",
                    idx, total, project.id, precis,
                )
            else:
                failed += 1
                log.warning(
                    "[%d/%d] id=%d ✗ generation returned None",
                    idx, total, project.id,
                )
        except Exception as exc:
            failed += 1
            db.rollback()
            log.warning(
                "[%d/%d] id=%d ✗ %s",
                idx, total, project.id, exc,
            )

        time.sleep(0.4)

    db.close()
    log.info(
        "done — %d succeeded, %d failed, %d total",
        succeeded, failed, total,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())