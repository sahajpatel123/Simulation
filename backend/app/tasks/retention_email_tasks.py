from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.database import SessionLocal
from app.worker import celery_app

logger = logging.getLogger("thecee.retention")


@celery_app.task(name="retention.send_week4_retention_emails")
def send_week4_retention_emails() -> dict:
    """
    Celery beat task. Runs weekly.
    Finds simulations created in a ~5-day window ~4 weeks ago with no founder_outcome.
    Sends return email to those founders (one email per user per run; batch by user_id).
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        four_weeks_ago_start = now - timedelta(days=30)
        four_weeks_ago_end = now - timedelta(days=25)

        rows = db.execute(
            text("""
            SELECT s.id AS sim_id, s.project_id,
                   u.email, u.id AS user_id,
                   u.retention_email_sent_at
            FROM simulations s
            JOIN projects p  ON p.id = s.project_id
            JOIN users u     ON u.id = p.user_id
            LEFT JOIN founder_outcomes fo ON fo.simulation_id = s.id
            WHERE UPPER(s.status) = 'COMPLETED'
              AND s.created_at >= :start AND s.created_at < :end
              AND fo.id IS NULL
              AND u.retention_email_sent_at IS NULL
        """),
            {
                "start": four_weeks_ago_start,
                "end": four_weeks_ago_end,
            },
        ).mappings().all()

        sent = 0
        for row in rows:
            _send_retention_email(str(row["email"]), int(row["sim_id"]), int(row["project_id"]))
            db.execute(
                text("UPDATE users SET retention_email_sent_at = :now WHERE id = :uid"),
                {"now": datetime.now(timezone.utc), "uid": int(row["user_id"])},
            )
            sent += 1

        db.commit()
        logger.info("Week-4 retention emails sent: %s", sent)
        return {"sent": sent}
    finally:
        db.close()


def _send_retention_email(email: str, sim_id: int, project_id: int) -> None:
    """
    Sends the week-4 return email.
    Replace logging with Resend / SendGrid / SMTP as needed.
    """
    try:
        subject = "Did you launch? Your prediction gap is waiting."
        body = (
            f"Hey,\n\n"
            f"4 weeks ago you ran a simulation on TheCee.\n\n"
            f"If you launched — even a soft launch, a waitlist, a demo — "
            f"your real-world results are sitting next to your predicted ones.\n\n"
            f"Tell us how it went. It takes 2 minutes and makes your next "
            f"simulation significantly more accurate.\n\n"
            f"Return with your results →\n"
            f"https://thecee.app/project/{project_id}/results?sim={sim_id}&outcome=true\n\n"
            f"— TheCee"
        )
        logger.info(
            "[RETENTION EMAIL] To: %s | sim=%s project=%s | Subject: %s",
            email,
            sim_id,
            project_id,
            subject,
        )
    except Exception as e:
        logger.error("Retention email failed for %s: %s", email, e)
