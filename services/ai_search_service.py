"""AI Search Service — orchestrates the full chat → scrape pipeline.

Flow:
  1. User sends a natural language message to the AI chat.
  2. `chat_and_generate_keywords` returns keywords + an AI reply.
  3. Each enabled scraper's `search_jobs()` is called with those keywords.
     Scrapers handle their own DB saving via `_run_pipeline()`.
  4. A notification is created with the summary.
"""
import logging
import time

logger = logging.getLogger(__name__)


def run_ai_search(user_message: str, session_id: str = None) -> dict:
    """Run a full AI-assisted job search from a natural language message.

    Args:
        user_message: What the user typed (e.g. "IT企業でリモートワーク希望").
        session_id: Optional chat session to continue.

    Returns:
        dict with: session_id, reply, keywords, jobs_found, jobs_new
    """
    from ai.chat_agent import chat_and_generate_keywords

    result = {
        'session_id': session_id,
        'reply': '',
        'keywords': [],
        'jobs_found': 0,
        'jobs_new': 0,
        'jobs_ai_enriched': 0,
        'scraper_results': [],
        'errors': [],
    }

    # ── Step 1: Generate keywords via AI ──────────────────────────────────
    try:
        chat_result = chat_and_generate_keywords(user_message, session_id)
        result['session_id'] = chat_result['session_id']
        result['reply'] = chat_result['reply']
        result['keywords'] = chat_result['keywords']
        result['site_filters'] = chat_result.get('site_filters', {})
        logger.info(f"[ai_search] Keywords: {chat_result['keywords']} Filters: {list(result['site_filters'].keys())}")
    except Exception as e:
        logger.error(f"[ai_search] Keyword generation failed: {e}")
        result['reply'] = 'キーワード生成に失敗しました。'
        result['errors'].append(str(e))
        return result

    if not result['keywords']:
        logger.info("[ai_search] No keywords generated, stopping.")
        return result

    # ── Step 2: Run scrapers ──────────────────────────────────────────────
    # Scrapers save directly to DB via _run_pipeline() → upsert_job_from_scraper()
    # They return a result dict: {source, status, jobs_found, jobs_updated, ...}
    scrapers = _get_enabled_scrapers()
    site_filters = result.get('site_filters', {})

    for scraper_name, scraper_fn in scrapers.items():
        try:
            # Extract per-scraper filters from AI-generated site_filters
            filters = site_filters.get(scraper_name) if site_filters else None
            logger.info(f"[ai_search] Scraping '{scraper_name}' for {result['keywords']} filters={filters}")
            scraper_result = scraper_fn(result['keywords'], filters=filters)

            if isinstance(scraper_result, dict):
                found = scraper_result.get('jobs_found', 0)
                updated = scraper_result.get('jobs_updated', 0)
                enriched = scraper_result.get('jobs_ai_enriched', 0)
                status = scraper_result.get('status', 'unknown')
                error = scraper_result.get('error_message', '')

                result['jobs_found'] += found
                result['jobs_new'] += updated
                result['jobs_ai_enriched'] += enriched
                result['scraper_results'].append({
                    'source': scraper_name,
                    'status': status,
                    'jobs_found': found,
                    'jobs_saved': updated,
                    'jobs_ai_enriched': enriched,
                })
                if error:
                    result['errors'].append(f"{scraper_name}: {error}")

                logger.info(f"[ai_search] {scraper_name}: {status}, found={found}, saved={updated}")
            else:
                logger.warning(f"[ai_search] Unexpected return from {scraper_name}: {type(scraper_result)}")

            time.sleep(2)  # Polite delay between scrapers
        except Exception as e:
            logger.warning(f"[ai_search] Scraper '{scraper_name}' failed: {e}")
            result['errors'].append(f"{scraper_name}: {e}")
            result['scraper_results'].append({
                'source': scraper_name,
                'status': 'error',
                'error': str(e),
            })

    logger.info(
        f"[ai_search] Done: {result['jobs_found']} found, "
        f"{result['jobs_new']} new, {len(result['errors'])} errors"
    )

    # ── Step 3: Notify ────────────────────────────────────────────────────
    if result['jobs_new'] > 0 or result['jobs_found'] > 0:
        try:
            from database import create_notification
            create_notification(
                'ai_search_complete',
                f"AI検索完了: {result['jobs_found']}件発見 / {result['jobs_new']}件保存",
                f"キーワード: {', '.join(result['keywords'])}",
                ''
            )
        except Exception as e:
            logger.warning(f"[ai_search] Notification failed: {e}")

    return result


def _get_enabled_scrapers() -> dict:
    """Return a dict of {name: search_fn} for all importable scrapers.

    Uses the synchronous wrapper functions (run_*_search) rather than
    the async search_jobs() methods directly, to avoid coroutine issues.

    Important: Each scraper_fn takes (keywords, filters=None) and returns a
    result dict (not a list of jobs). Jobs are saved to DB internally.
    """
    scrapers = {}
    # Map: name → (module_path, sync_search_function_name)
    scraper_map = {
        'career_tasu': ('scrapers.career_tasu', 'run_career_tasu_search'),
        'mynavi': ('scrapers.mynavi', 'run_mynavi_search'),
        'engineer_shukatu': ('scrapers.engineer_shukatu', 'run_engineer_shukatu_search'),
        'gaishishukatsu': ('scrapers.gaishishukatsu', 'run_gaishishukatsu_search'),
        'onecareer': ('scrapers.onecareer', 'run_onecareer_search'),
    }
    for name, (module_path, func_name) in scraper_map.items():
        try:
            import importlib
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            scrapers[name] = fn
        except Exception as e:
            logger.debug(f"[ai_search] Scraper '{name}' not available: {e}")
    return scrapers


def run_search_with_keywords(keywords: list, site_filters: dict = None) -> dict:
    """Run scrapers directly with an explicit keyword list — no AI involved.

    Used by /api/chat/search-direct to avoid the redundant AI re-generation
    that would contaminate searches with old keywords from chat history.

    Args:
        keywords: list of search keyword strings.
        site_filters: optional dict keyed by scraper name, e.g.
            {'engineer_shukatu': {'arr_industry': ['SIer']}}
    """
    import time
    from database import create_notification

    result = {
        'keywords': keywords,
        'jobs_found': 0,
        'jobs_new': 0,
        'jobs_ai_enriched': 0,
        'scraper_results': [],
        'errors': [],
    }

    scrapers = _get_enabled_scrapers()
    for scraper_name, scraper_fn in scrapers.items():
        try:
            # Extract per-scraper filters
            filters = None
            if site_filters and scraper_name in site_filters:
                filters = site_filters[scraper_name]

            logger.info(f"[search_direct] Scraping '{scraper_name}' for {keywords} filters={filters}")
            scraper_result = scraper_fn(keywords, filters=filters)

            if isinstance(scraper_result, dict):
                found = scraper_result.get('jobs_found', 0)
                updated = scraper_result.get('jobs_updated', 0)
                enriched = scraper_result.get('jobs_ai_enriched', 0)
                status = scraper_result.get('status', 'unknown')
                error = scraper_result.get('error_message', '')

                result['jobs_found'] += found
                result['jobs_new'] += updated
                result['jobs_ai_enriched'] += enriched
                result['scraper_results'].append({
                    'source': scraper_name,
                    'status': status,
                    'jobs_found': found,
                    'jobs_saved': updated,
                    'jobs_ai_enriched': enriched,
                })
                if error:
                    result['errors'].append(f"{scraper_name}: {error}")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"[search_direct] Scraper '{scraper_name}' failed: {e}")
            result['errors'].append(f"{scraper_name}: {e}")
            result['scraper_results'].append({
                'source': scraper_name, 'status': 'error', 'error': str(e),
            })

    if result['jobs_new'] > 0:
        try:
            create_notification(
                'ai_search_complete',
                f"🔍 検索完了: {result['jobs_found']}件発見 / {result['jobs_new']}件保存",
                f"キーワード: {', '.join(keywords)}",
                ''
            )
        except Exception:
            pass

    logger.info(f"[search_direct] Done: {result['jobs_found']} found, {result['jobs_new']} new")
    return result

