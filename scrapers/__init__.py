"""Scraper package — centralized dispatch for all scraper operations.

ALL scraper activation goes through dispatch() — the single entry point.
No caller should import run_xxx_scraper or run_xxx_search directly.
"""
import importlib
import logging
import time

logger = logging.getLogger(__name__)

# ── Unified scraper registry — SINGLE SOURCE OF TRUTH ────────────────
# Add a new scraper? Just add one entry here. Nothing else to change.
_SCRAPER_REGISTRY = [
    {
        'name': 'mynavi',
        'module': 'scrapers.mynavi',
        'fetch_fn': 'run_mynavi_scraper',
        'search_fn': 'run_mynavi_search',
        'login_url': 'https://job.mynavi.jp/2027/login',
    },
    {
        'name': 'career_tasu',
        'module': 'scrapers.career_tasu',
        'fetch_fn': 'run_career_tasu_scraper',
        'search_fn': 'run_career_tasu_search',
        'login_url': None,  # public, no login needed
    },
    {
        'name': 'onecareer',
        'module': 'scrapers.onecareer',
        'fetch_fn': 'run_onecareer_scraper',
        'search_fn': 'run_onecareer_search',
        'login_url': 'https://id.onecareer.jp/users/sign_in?redirect_url=https%3A%2F%2Fwww.onecareer.jp%2F',
    },
    {
        'name': 'gaishishukatsu',
        'module': 'scrapers.gaishishukatsu',
        'fetch_fn': 'run_gaishishukatsu_scraper',
        'search_fn': 'run_gaishishukatsu_search',
        'login_url': 'https://gaishishukatsu.com/login',
    },
    {
        'name': 'engineer_shukatu',
        'module': 'scrapers.engineer_shukatu',
        'fetch_fn': 'run_engineer_shukatu_scraper',
        'search_fn': 'run_engineer_shukatu_search',
        'login_url': 'https://engineer-shukatu.jp/login.php',
    },
]


def get_registry(action: str = 'search') -> dict:
    """Get {name: callable} for the given action type.

    Args:
        action: 'fetch' or 'search'

    Returns:
        dict of {scraper_name: function} for all loadable scrapers.
    """
    fn_key = 'fetch_fn' if action == 'fetch' else 'search_fn'
    registry = {}
    for entry in _SCRAPER_REGISTRY:
        try:
            mod = importlib.import_module(entry['module'])
            registry[entry['name']] = getattr(mod, entry[fn_key])
        except Exception as e:
            logger.debug(
                f"[registry] Could not load {entry['name']}.{fn_key}: {e}"
            )
    return registry


def get_scraper_names() -> list:
    """Return list of all registered scraper names."""
    return [entry['name'] for entry in _SCRAPER_REGISTRY]


def get_login_urls() -> dict:
    """Return {name: login_url} for scrapers that require login."""
    return {
        entry['name']: entry['login_url']
        for entry in _SCRAPER_REGISTRY
        if entry.get('login_url')
    }


def dispatch(
    action: str = 'search',
    mode: str = 'scheduled',
    keywords: list = None,
    scrapers: list = None,
    max_results: int = 0,
    job_id: int = None,
) -> dict:
    """Unified scraper dispatcher — ALL scraper activation goes through here.

    Args:
        action: what to do:
            'fetch'  — fetch bookmarks/favorites (no keywords needed)
            'search' — keyword search
        mode: dispatch mode:
            'scheduled'      — periodic task from scheduler
            'email_backfill' — one-shot search, merge into existing job
            'one_shot'       — manual/API-triggered
        keywords: list of keyword strings (required for action='search')
        scrapers: only run these scrapers (list of names).
                  None = run all available scrapers.
        max_results: if > 0, only process this many results per scraper.
                     email_backfill defaults to 1.
        job_id: target job ID for email_backfill mode.

    Returns:
        dict with 'total_found', 'total_new', and per-scraper 'results'.
    """
    registry = get_registry(action)

    # Email backfill: limit to 1 result per scraper (not 1 scraper)
    if mode == 'email_backfill':
        if max_results == 0:
            max_results = 1

    # Filter to requested scrapers
    if scrapers:
        registry = {k: v for k, v in registry.items() if k in scrapers}

    if not registry:
        logger.info(
            f"[dispatch] No scrapers available "
            f"(action={action}, filter={scrapers})"
        )
        return {'total_found': 0, 'total_new': 0, 'results': []}

    logger.info(
        f"[dispatch] action={action}, mode={mode}, "
        f"scrapers={list(registry.keys())}"
        f"{f', keywords={keywords}' if keywords else ''}"
        f"{f', job_id={job_id}' if job_id else ''}"
        f"{f', max_results={max_results}' if max_results else ''}"
    )

    total_found = 0
    total_new = 0
    results = []

    for name, run_fn in registry.items():
        try:
            logger.info(f"[dispatch] Running {name} ({action})...")

            if action == 'fetch':
                result = run_fn()
            else:
                # In email_backfill mode, pass company_keyword so scrapers
                # only save results matching the target company name
                kw_arg = (keywords[0] if keywords else '') if mode == 'email_backfill' else ''
                result = run_fn(
                    keywords or [], max_results=max_results,
                    company_keyword=kw_arg
                )

            # Normalize result
            if isinstance(result, dict):
                found = result.get('jobs_found', 0)
                new = result.get('jobs_new', result.get('jobs_updated', 0))
                total_found += found
                total_new += new
                results.append(result)

                # Log scrape result
                _log_scrape_result(name, result)
            elif isinstance(result, tuple):
                total_found += result[0]
                total_new += result[1] if len(result) > 1 else 0

            time.sleep(2)

        except Exception as e:
            logger.warning(f"[dispatch] {name} failed: {e}")
            results.append({
                'source': name,
                'status': 'error',
                'error_message': str(e),
            })

    logger.info(
        f"[dispatch] Done: action={action}, "
        f"{total_found} found, {total_new} new"
    )

    # Email backfill: merge best scraped result into target job
    # Scrapers in backfill mode don't save to DB — they return raw data
    # in result['backfill_data']. We collect all and pass to merge.
    if mode == 'email_backfill' and job_id and keywords:
        backfill_candidates = []
        for r in results:
            if isinstance(r, dict):
                backfill_candidates.extend(r.get('backfill_data', []))
        _merge_backfill_results(keywords[0], job_id, backfill_candidates)

    return {
        'total_found': total_found,
        'total_new': total_new,
        'results': results,
    }


# ── Backward compatibility aliases ──────────────────────────────────
# These will be removed once all callers migrate to dispatch()

def dispatch_search(keywords, mode='scheduled', job_id=None,
                    scrapers=None, max_results=0):
    """Backward-compatible alias for dispatch(action='search', ...)."""
    return dispatch(
        action='search', mode=mode, keywords=keywords,
        scrapers=scrapers, max_results=max_results, job_id=job_id,
    )


def get_search_registry():
    """Backward-compatible alias for get_registry('search')."""
    return get_registry('search')


# ── Internal helpers ────────────────────────────────────────────────

def _log_scrape_result(name: str, result: dict):
    """Log scrape result and create notification if applicable."""
    try:
        from database import log_scrape, create_notification
        log_scrape(
            result.get('source', name),
            result.get('status', 'unknown'),
            result.get('jobs_found', 0),
            result.get('jobs_updated', 0),
            result.get('error_message', ''),
        )
        if result.get('status') == 'success' and result.get('jobs_updated', 0) > 0:
            create_notification(
                'scrape_complete',
                f"🔄 {name} スクレイピング完了",
                f"{result['jobs_found']}件検出、{result['jobs_updated']}件新規追加",
                '',
            )
        elif result.get('status') == 'error':
            create_notification(
                'scrape_error',
                f"❌ {name} スクレイピングエラー",
                result.get('error_message', 'Unknown error'),
                '',
            )
    except Exception as e:
        logger.debug(f"[dispatch] Log/notification error for {name}: {e}")


def _merge_backfill_results(company_keyword: str, job_id: int,
                            candidates: list = None):
    """Forward to services.email_backfill (moved in P2 refactor)."""
    from services.email_backfill import merge_backfill_results
    merge_backfill_results(company_keyword, job_id, candidates)


