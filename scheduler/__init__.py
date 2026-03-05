"""Background scheduler package for periodic tasks.

All task functions are split into sub-modules by responsibility.
This __init__ re-exports everything so existing code like
``from scheduler import check_gmail`` continues to work.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from config import Config

# ── Re-export task functions for backward compatibility ──
from scheduler.enrich_tasks import run_enrichment, run_application_queue
from scheduler.check_tasks import (
    check_deadlines_today, check_upcoming_deadlines, check_interviews_today
)
from scheduler.scraper_tasks import (
    run_all_scrapers, run_scraper
)
from scheduler.gmail_tasks import check_gmail
from scheduler.keyword_tasks import run_keyword_search

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=Config.TIMEZONE)


def _enqueue_cleanup():
    """Enqueue task queue cleanup."""
    try:
        from db.task_queue import enqueue
        enqueue('cleanup_old_tasks', priority=10, params={'days': 7})
    except Exception as e:
        logger.warning(f"[scheduler] Cleanup enqueue error: {e}")


def init_scheduler():
    """Initialize and start the background scheduler."""
    if scheduler.running:
        return

    # Morning scraper run FIRST (to get fresh data before alerts)
    scheduler.add_job(
        run_scraper,
        CronTrigger(hour=Config.MORNING_ALERT_HOUR, minute=0),
        id='scrape_morning',
        replace_existing=True,
        name='Morning scrape'
    )

    # Morning alerts AFTER scrape (deadlines + interviews)
    scheduler.add_job(
        check_deadlines_today,
        CronTrigger(hour=Config.MORNING_ALERT_HOUR, minute=30),
        id='check_deadlines_today',
        replace_existing=True,
        name='Check deadlines today'
    )

    scheduler.add_job(
        check_upcoming_deadlines,
        CronTrigger(hour=Config.MORNING_ALERT_HOUR, minute=35),
        id='check_upcoming_deadlines',
        replace_existing=True,
        name='Check upcoming deadlines (本選考 3日以内)'
    )

    scheduler.add_job(
        check_interviews_today,
        CronTrigger(hour=Config.MORNING_ALERT_HOUR, minute=30),
        id='check_interviews_today',
        replace_existing=True,
        name='Check interviews today'
    )
    scheduler.add_job(
        run_scraper,
        CronTrigger(hour=Config.SCRAPE_EVENING_HOUR, minute=Config.SCRAPE_EVENING_MINUTE),
        id='scrape_evening',
        replace_existing=True,
        name='Evening scrape'
    )

    # Gmail checks: 6:00 AM and 6:00 PM (with auto event registration)
    scheduler.add_job(
        check_gmail,
        CronTrigger(hour=6, minute=0),
        id='check_gmail_morning',
        replace_existing=True,
        name='Gmail morning check (6:00)'
    )

    scheduler.add_job(
        check_gmail,
        CronTrigger(hour=18, minute=0),
        id='check_gmail_evening',
        replace_existing=True,
        name='Gmail evening check (18:00)'
    )

    # AI enrichment: every 3 hours (staggered from scraping)
    scheduler.add_job(
        run_enrichment,
        IntervalTrigger(hours=3),
        id='run_enrichment',
        replace_existing=True,
        name='AI enrichment (every 3h)'
    )

    # Application queue processing: every 30 minutes
    scheduler.add_job(
        run_application_queue,
        IntervalTrigger(minutes=30),
        id='run_application_queue',
        replace_existing=True,
        name='Application queue processor (every 30min)'
    )

    # Keyword-based search: 10:00 AM and 3:00 PM (using user_preferences keywords)
    scheduler.add_job(
        run_keyword_search,
        CronTrigger(hour=10, minute=0),
        id='keyword_search_morning',
        replace_existing=True,
        name='Keyword search morning (10:00)'
    )

    scheduler.add_job(
        run_keyword_search,
        CronTrigger(hour=15, minute=0),
        id='keyword_search_afternoon',
        replace_existing=True,
        name='Keyword search afternoon (15:00)'
    )
    # Periodic Gmail check — delay first run to avoid duplicating the startup Timer
    from datetime import datetime as _dt, timedelta as _td
    scheduler.add_job(
        check_gmail,
        IntervalTrigger(hours=2, start_date=_dt.now() + _td(hours=2)),
        id='check_gmail_periodic',
        replace_existing=True,
        name='Gmail periodic check'
    )

    # Daily cleanup of old task queue entries
    scheduler.add_job(
        _enqueue_cleanup,
        CronTrigger(hour=3, minute=0),
        id='task_queue_cleanup',
        replace_existing=True,
        name='Task queue cleanup (daily 3:00)'
    )

    scheduler.start()
    logger.info("Scheduler started with all jobs registered")

    # Start the TaskWorker background thread
    try:
        from services.task_worker import task_worker
        task_worker.start()
        logger.info("TaskWorker started")
    except Exception as e:
        logger.warning(f"TaskWorker start failed: {e}")

    # --- Run Gmail check on startup (30 sec delay to let server warm up) ---
    from threading import Timer

    def _startup_gmail_check():
        """Run Gmail check on startup. If email_cache is empty, do a 30-day backfill."""
        try:
            from db.emails import get_email_count
            count = get_email_count()
            if count == 0:
                logger.info("📩 First run detected (email_cache empty) — running 30-day backfill")
                check_gmail(backfill=True)
            else:
                logger.info(f"📩 Startup Gmail check (incremental, {count} cached emails)")
                check_gmail()
        except Exception as e:
            logger.warning(f"Startup Gmail check failed: {e}")

    Timer(30.0, _startup_gmail_check).start()
    logger.info("Startup Gmail check scheduled (30s delay)")


def shutdown_scheduler():
    """Shut down the scheduler and worker."""
    # Stop TaskWorker first
    try:
        from services.task_worker import task_worker
        if task_worker.is_running():
            task_worker.stop()
            logger.info("TaskWorker stopped")
    except Exception as e:
        logger.warning(f"TaskWorker stop error: {e}")

    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down")
