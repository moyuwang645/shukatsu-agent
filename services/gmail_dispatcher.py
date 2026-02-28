"""Gmail dispatcher — unified email fetching and processing.

ALL Gmail email fetching goes through fetch_emails() — the single entry point.
Handles browser vs API selection, caching, and processing pipeline.
"""
import logging
from config import Config

logger = logging.getLogger(__name__)


def fetch_emails(
    backfill: bool = False,
    max_results: int = 20,
    apply_filter: bool = True,
) -> dict:
    """Unified Gmail fetch — browser vs API auto-selection + processing pipeline.

    Args:
        backfill: If True, fetch past 30 days (first-run mode).
        max_results: Max emails to fetch.
        apply_filter: If True, apply 3-tier email filter before AI processing.

    Returns:
        dict with 'emails_fetched', 'events_registered', 'mode', 'emails'.
    """
    from gmail_browser import is_gmail_browser_configured, fetch_emails_via_browser
    from services.event_detector import auto_register_interview
    from database import (
        cache_email, get_cached_emails,
        is_email_processed, mark_email_processed, create_notification,
    )

    emails = []
    mode = 'none'

    # ── Step 1: Fetch emails (browser > API auto-select) ────────────
    if is_gmail_browser_configured():
        if backfill:
            from gmail_browser import fetch_emails_backfill
            emails = fetch_emails_backfill(days=30)
            logger.info(f"📩 Backfill: fetched {len(emails)} emails from past 30 days")
        else:
            emails = fetch_emails_via_browser(max_results=max_results)
        mode = 'browser'
    elif Config.GMAIL_ENABLED:
        from gmail_service import fetch_recent_emails
        emails = fetch_recent_emails(max_results=max_results)
        mode = 'api'
    else:
        logger.info("Gmail not configured, skipping")
        return {
            'emails_fetched': 0, 'events_registered': 0,
            'mode': mode, 'emails': [],
        }

    if not emails:
        logger.info(f"📩 No emails fetched ({mode})")
        return {
            'emails_fetched': 0, 'events_registered': 0,
            'mode': mode, 'emails': [],
        }

    # ── Step 2: Cache new emails ────────────────────────────────────
    cached_ids = {
        e['gmail_id'] for e in get_cached_emails(limit=500)
        if e.get('gmail_id')
    }
    for email_data in emails:
        gmail_id = email_data.get('gmail_id', '')
        if gmail_id not in cached_ids:
            cache_email(email_data)

    # ── Step 3: Collect unprocessed emails ───────────────────────────
    unprocessed = [
        e for e in emails
        if not is_email_processed(e.get('gmail_id', ''))
    ]

    if not unprocessed:
        logger.info(
            f"📩 Gmail done ({mode}): {len(emails)} fetched, "
            f"all already processed"
        )
        return {
            'emails_fetched': len(emails), 'events_registered': 0,
            'mode': mode, 'emails': emails,
        }

    # ── Step 4: Optional 3-tier filter ──────────────────────────────
    if apply_filter:
        try:
            from services.email_filter import filter_emails
            filter_result = filter_emails(unprocessed)
            filtered_emails = filter_result.get('job_related', unprocessed)
            stats = filter_result.get('stats', {})
            logger.info(
                f"📩 Email filter: {stats.get('total', len(unprocessed))} total → "
                f"L1 filtered {stats.get('l1_filtered', 0)}, "
                f"L2 filtered {stats.get('l2_filtered', 0)}, "
                f"job-related {stats.get('l3_job', len(filtered_emails))}"
            )
        except Exception as e:
            logger.warning(f"📩 Email filter error, processing all: {e}")
            filtered_emails = unprocessed
    else:
        filtered_emails = unprocessed

    # ── Step 5: AI processing pipeline ──────────────────────────────
    events_registered = 0
    for email_data in filtered_emails:
        gmail_id = email_data.get('gmail_id', '')
        try:
            auto_register_interview(email_data)
            mark_email_processed(gmail_id)
            events_registered += 1
            logger.info(
                f"📩 Processed: {email_data.get('subject', '?')[:50]}"
            )
        except Exception as e:
            logger.warning(
                f"Auto-register error for "
                f"[{email_data.get('subject', '?')[:30]}]: {e}"
            )

    # Mark non-job emails as processed too (avoid re-filtering)
    for email_data in unprocessed:
        gmail_id = email_data.get('gmail_id', '')
        if not is_email_processed(gmail_id):
            mark_email_processed(gmail_id)

    logger.info(
        f"📩 Gmail done ({mode}): {len(emails)} fetched, "
        f"{len(unprocessed)} unprocessed, "
        f"{len(filtered_emails)} passed filter, "
        f"{events_registered} events registered"
    )

    # ── Step 6: Notification ────────────────────────────────────────
    if events_registered > 0:
        create_notification(
            'gmail_auto_events',
            f"📩 Gmail自動チェック: {events_registered}件のメールをAI解析",
            f"モード: {mode} | 取得: {len(emails)}件 | "
            f"フィルタ通過: {len(filtered_emails)}件 | "
            f"AI処理: {events_registered}件",
            '',
        )

    return {
        'emails_fetched': len(emails),
        'events_registered': events_registered,
        'mode': mode,
        'emails': emails,
    }
