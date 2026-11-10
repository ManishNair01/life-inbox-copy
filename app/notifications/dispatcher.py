"""One-shot entry point for cron or another deployment scheduler."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> int:
    load_dotenv()
    from app.notifications.service import dispatch_due_notifications

    try:
        result = dispatch_due_notifications()
    except Exception:
        logging.getLogger(__name__).exception("Notification dispatch failed.")
        return 1
    logging.getLogger(__name__).info(
        "Notification dispatch finished: sent=%d skipped=%d failed=%d",
        result["sent"],
        result["skipped"],
        result["failed"],
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
