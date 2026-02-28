"""Scraper scheduling — enqueues scrape tasks via the unified dispatcher.

All actual scraper execution goes through scrapers.dispatch().
This module only handles enqueuing tasks into the task queue.
"""
import logging

logger = logging.getLogger(__name__)


def run_all_scrapers(scrapers: list = None):
    """Enqueue scrape tasks for all (or specified) scrapers.

    Args:
        scrapers: optional list of scraper names to run.
                  None = run all registered scrapers.
    """
    try:
        from db.task_queue import enqueue
        from scrapers import get_scraper_names

        names = scrapers or get_scraper_names()
        for name in names:
            enqueue(f'scrape_{name}', priority=5, params={'scraper': name})
        logger.info(f"[scheduler] Enqueued {len(names)} scrape tasks: {names}")
    except Exception as e:
        logger.exception(f"[scheduler] Enqueue scraper tasks error: {e}")
        # Fallback: run directly via dispatch
        _run_all_scrapers_direct(scrapers)


def _run_all_scrapers_direct(scrapers: list = None):
    """Fallback: run scrapers directly via unified dispatch."""
    from scrapers import dispatch
    result = dispatch(action='fetch', scrapers=scrapers)
    logger.info(
        f"[scheduler] Direct scrape complete: "
        f"{result['total_found']} found, {result['total_new']} new"
    )


# Backward compatibility alias
run_scraper = run_all_scrapers
