"""Gmail checking and email processing tasks."""
import logging

logger = logging.getLogger(__name__)


def check_gmail(backfill=False):
    """Check Gmail for new job-related emails and auto-register events.

    Delegates to the unified gmail dispatcher.

    Args:
        backfill: If True, fetch all emails from the past 30 days (first-run mode).
    """
    mode_label = 'backfill' if backfill else 'incremental'
    logger.info(f"📩 Gmail check starting ({mode_label} mode)...")
    try:
        from services.gmail_dispatcher import fetch_emails
        result = fetch_emails(backfill=backfill, apply_filter=True)
        logger.info(
            f"📩 Gmail check done: {result['emails_fetched']} fetched, "
            f"{result['events_registered']} events ({result['mode']})"
        )
    except Exception as e:
        logger.exception(f"Gmail check error: {e}")
