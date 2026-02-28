"""Keyword-based search tasks.

Uses the centralized keyword dispatcher from scrapers package.
"""
import logging

logger = logging.getLogger(__name__)


def run_keyword_search(keywords_override: list = None, scrapers: list = None):
    """Run automated keyword search using saved user_preferences.

    Reads enabled keywords from user_preferences table and dispatches them
    to all registered search-capable scrapers via the centralized dispatcher.

    Args:
        keywords_override: If provided, search only these keywords instead of
                          reading from user_preferences.
        scrapers: If provided, only run these specific scrapers.
                  None = run all available search scrapers.
    """
    try:
        from scrapers import dispatch

        if keywords_override:
            keywords = keywords_override
        else:
            from db.preferences import get_preferences
            prefs = get_preferences()
            keywords = [p['keyword'] for p in prefs if p.get('enabled', 1)]

        if not keywords:
            logger.info("[keyword_search] No enabled keywords found, skipping")
            return

        logger.info(f"[keyword_search] Running search for {len(keywords)} keywords: {keywords}")

        result = dispatch(
            action='search', mode='scheduled',
            keywords=keywords, scrapers=scrapers,
        )
        total_found = result.get('total_found', 0)
        total_new = result.get('total_new', 0)

        # Notifications are handled by dispatch() internally
        logger.info(
            f"[keyword_search] Done: {total_found} found, {total_new} new"
        )

    except Exception as e:
        logger.exception(f"[keyword_search] Error: {e}")
