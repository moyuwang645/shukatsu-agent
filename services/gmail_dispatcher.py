"""Gmail dispatcher — unified email fetching and processing.

ALL Gmail email fetching goes through fetch_emails() — the single entry point.
Uses the mode registry (gmail_modes.py) to determine query and limits.
Handles browser vs API selection, caching, and processing pipeline.
"""
import logging
from config import Config

logger = logging.getLogger(__name__)


def fetch_emails(
    mode: str = 'incremental',
    params: dict = None,
    apply_filter: bool = True,
) -> dict:
    """Unified Gmail fetch — mode-driven pipeline.

    Args:
        mode: Fetch mode name ('backfill', 'incremental', 'keyword_search', etc.)
        params: Mode-specific parameters (e.g. {'keyword': '三菱', 'limit': 10}).
        apply_filter: If True, apply 3-tier email filter before AI processing.

    Returns:
        dict with 'emails_fetched', 'events_registered', 'mode', 'mode_name', 'emails'.
    """
    from services.gmail_modes import registry
    from services.event_detector import auto_register_interview
    from services.gmail_progress import update_progress, finish_progress
    from database import (
        cache_email, get_cached_emails,
        is_email_processed, mark_email_processed, create_notification,
    )

    if params is None:
        params = {}

    # ── Step 0: Resolve mode ────────────────────────────────────────
    try:
        fetch_mode = registry.get(mode)
    except KeyError as e:
        logger.error(f"📩 {e}")
        return {
            'emails_fetched': 0, 'events_registered': 0,
            'mode': 'error', 'mode_name': mode,
            'emails': [], 'error': str(e),
        }

    query = fetch_mode.build_query(params)
    limit = fetch_mode.get_limit(params)
    logger.info(f"📩 Gmail fetch: mode={mode}, query='{query}', limit={limit}")
    update_progress(stage='starting', message=f'Gmail取得開始 ({mode})', mode=mode)

    # ── Step 1: Fetch emails (browser > API, with fallback) ───────────
    emails = []
    transport = 'none'

    from gmail_browser import is_gmail_browser_configured

    if is_gmail_browser_configured():
        from gmail_browser import fetch_emails_by_search
        emails = fetch_emails_by_search(query=query, max_results=limit)
        transport = 'browser'

    # Fallback: if browser returned nothing (e.g. cookies expired), try API
    if not emails and Config.GMAIL_ENABLED:
        if transport == 'browser':
            logger.info("📩 Browser returned 0 emails, falling back to Gmail API")
        from gmail_service import fetch_recent_emails
        emails = fetch_recent_emails(query=query, max_results=limit)
        transport = 'api'

    if transport == 'none':
        logger.info("Gmail not configured, skipping")
        return {
            'emails_fetched': 0, 'events_registered': 0,
            'mode': transport, 'mode_name': mode,
            'emails': [],
        }


    if not emails:
        logger.info(f"📩 No emails fetched ({transport}, mode={mode})")
        finish_progress(f'メール0件 ({transport})')
        return {
            'emails_fetched': 0, 'events_registered': 0,
            'mode': transport, 'mode_name': mode,
            'emails': [],
        }

    logger.info(f"📩 Fetched {len(emails)} emails via {transport} (mode={mode})")
    update_progress(stage='caching', current=0, total=len(emails),
                    message=f'{len(emails)}件取得完了、キャッシュ中...')

    # ── Step 2: Mode post-fetch hook (update last_fetched_at etc.) ──
    try:
        fetch_mode.after_fetch(emails, params)
    except Exception as e:
        logger.warning(f"📩 Mode after_fetch error: {e}")

    # ── Step 3: Cache new emails ────────────────────────────────────
    cached_ids = {
        e['gmail_id'] for e in get_cached_emails(limit=2000)
        if e.get('gmail_id')
    }
    new_cached = 0
    for email_data in emails:
        gmail_id = email_data.get('gmail_id', '')
        if gmail_id not in cached_ids:
            cache_email(email_data)
            new_cached += 1

    # ── Step 4: Collect unprocessed emails ───────────────────────────
    unprocessed = [
        e for e in emails
        if not is_email_processed(e.get('gmail_id', ''))
    ]

    if not unprocessed:
        logger.info(
            f"📩 Gmail done ({transport}, {mode}): {len(emails)} fetched, "
            f"all already processed"
        )
        return {
            'emails_fetched': len(emails), 'events_registered': 0,
            'mode': transport, 'mode_name': mode,
            'emails': emails,
        }

    # ── Step 5: Optional 3-tier filter ──────────────────────────────
    if apply_filter:
        update_progress(stage='filtering', current=0, total=len(unprocessed),
                        message=f'{len(unprocessed)}件をAIフィルタ中...')
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

    # ── Step 6: AI processing pipeline ──────────────────────────────
    events_registered = 0
    total_to_process = len(filtered_emails)
    for proc_idx, email_data in enumerate(filtered_emails, 1):
        gmail_id = email_data.get('gmail_id', '')
        update_progress(stage='processing', current=proc_idx, total=total_to_process,
                        message=f'AI処理中: {proc_idx}/{total_to_process}件')
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
        f"📩 Gmail done ({transport}, {mode}): {len(emails)} fetched, "
        f"{new_cached} new cached, "
        f"{len(unprocessed)} unprocessed, "
        f"{len(filtered_emails)} passed filter, "
        f"{events_registered} events registered"
    )
    finish_progress(
        f'完了: {len(emails)}件取得, {events_registered}件AI処理'
    )

    # ── Step 7: Notification ────────────────────────────────────────
    if events_registered > 0:
        create_notification(
            'gmail_auto_events',
            f"📩 Gmail自動チェック: {events_registered}件のメールをAI解析",
            f"モード: {mode} ({transport}) | 取得: {len(emails)}件 | "
            f"フィルタ通過: {len(filtered_emails)}件 | "
            f"AI処理: {events_registered}件",
            '',
        )

    return {
        'emails_fetched': len(emails),
        'events_registered': events_registered,
        'mode': transport,
        'mode_name': mode,
        'emails': emails,
    }
