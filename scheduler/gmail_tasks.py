"""Gmail checking and email processing tasks."""
import logging

logger = logging.getLogger(__name__)


def check_gmail(backfill=False):
    """Check Gmail for new job-related emails and auto-register events.

    Uses the mode registry via gmail_dispatcher:
      - backfill=True  → 'backfill' mode (past N days, no limit)
      - backfill=False → 'incremental' mode (since last_fetched_at)

    Args:
        backfill: If True, fetch all emails from the past 30 days (first-run mode).
    """
    mode = 'backfill' if backfill else 'incremental'
    logger.info(f"📩 Gmail check starting (mode={mode})...")
    try:
        from services.gmail_dispatcher import fetch_emails
        result = fetch_emails(mode=mode, apply_filter=True)
        logger.info(
            f"📩 Gmail check done: {result['emails_fetched']} fetched, "
            f"{result['events_registered']} events ({result.get('mode_name', mode)})"
        )
    except Exception as e:
        logger.exception(f"Gmail check error: {e}")
