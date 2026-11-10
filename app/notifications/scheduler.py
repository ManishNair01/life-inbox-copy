"""Simple minute-loop runner for local Compose deployments."""

from __future__ import annotations

import logging
import time

from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    from app.notifications.service import dispatch_due_notifications

    logger.info("Notification scheduler started; checking once per minute.")
    while True:
        try:
            result = dispatch_due_notifications()
            if result["sent"] or result["failed"]:
                logger.info(
                    "Notification dispatch finished: sent=%d skipped=%d failed=%d",
                    result["sent"],
                    result["skipped"],
                    result["failed"],
                )
        except Exception:
            logger.exception("Notification dispatch failed; retrying next minute.")
        try:
            # The weekly review (change 020): one call per user per week.
            from app.review import run_due_reviews

            reviewed = run_due_reviews()
            if reviewed:
                logger.info("Weekly reviews done: %d", reviewed)
        except Exception:
            logger.exception("Weekly reviews failed; retrying next minute.")
        time.sleep(60)


if __name__ == "__main__":
    main()
