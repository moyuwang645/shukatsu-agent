"""Enrichment Service — batch-process unenriched jobs with AI analysis.

Scans the `jobs` table for rows where `ai_enriched = 0`, fetches
user preferences and OpenWork data, and calls `enrich_single_job`
to fill in `match_score`, `ai_summary`, and `tags` for each.

Rate-limiting: 5 second sleep between each API call (matched with the
job enricher) to avoid Gemini free-tier 429 errors.
"""
import logging
import time

logger = logging.getLogger(__name__)

MAX_PER_RUN = 10  # Maximum jobs to process in a single scheduler run


def enrich_pending_jobs(max_jobs: int = MAX_PER_RUN) -> dict:
    """Enrich up to `max_jobs` unenriched jobs from the database.

    Args:
        max_jobs: Upper limit of jobs to process per run (default: 10).

    Returns:
        dict with: processed, succeeded, failed, skipped
    """
    from ai.job_enricher import enrich_single_job
    from ai import is_ai_configured
    from db.jobs import get_unenriched_jobs, update_job_enrichment
    from db.preferences import get_preferences as get_all_preferences
    from db.openwork import get_openwork_data

    stats = {'processed': 0, 'succeeded': 0, 'failed': 0, 'skipped': 0}

    if not is_ai_configured():
        logger.info("[enrichment] AI not configured, skipping enrichment run.")
        stats['skipped'] = -1
        return stats

    # Fetch unenriched jobs
    jobs = get_unenriched_jobs(limit=max_jobs)
    if not jobs:
        logger.info("[enrichment] No unenriched jobs found.")
        return stats

    # Fetch user preferences once
    try:
        preferences = [p['keyword'] for p in get_all_preferences()]
    except Exception:
        preferences = []

    logger.info(f"[enrichment] Processing {len(jobs)} jobs (preferences: {len(preferences)})")

    for job in jobs:
        stats['processed'] += 1
        job_id = job['id']
        company = job.get('company_name', '?')

        # Fetch OpenWork data if available
        openwork_data = None
        try:
            ow = get_openwork_data(company)
            if ow:
                openwork_data = dict(ow)
        except Exception as e:
            logger.debug(f"[enrichment] No OpenWork for {company}: {e}")

        try:
            enriched = enrich_single_job(
                job_data=dict(job),
                user_preferences=preferences,
                openwork_data=openwork_data,
            )

            if enriched:
                update_job_enrichment(job_id, {
                    'match_score': enriched.get('match_score', 0),
                    'ai_summary': enriched.get('ai_summary', ''),
                    'tags': ','.join(enriched.get('tags', [])),
                    'ai_enriched': 1,
                })
                logger.info(
                    f"[enrichment] Job {job_id} ({company}): "
                    f"score={enriched.get('match_score')}, "
                    f"tags={enriched.get('tags', [])}"
                )
                stats['succeeded'] += 1
            else:
                logger.warning(f"[enrichment] Job {job_id} returned None from enricher")
                stats['failed'] += 1

        except Exception as e:
            logger.warning(f"[enrichment] Job {job_id} failed: {e}")
            stats['failed'] += 1

        # Rate limiting: 5s between each API call
        if stats['processed'] < len(jobs):
            time.sleep(5)

    logger.info(
        f"[enrichment] Run complete: "
        f"{stats['succeeded']} succeeded, {stats['failed']} failed"
    )

    # Notify if jobs were enriched
    if stats['succeeded'] > 0:
        try:
            from database import create_notification
            create_notification(
                'enrichment_complete',
                f"AI分析完了: {stats['succeeded']}件の求人をスコアリング",
                f"処理: {stats['processed']}件 | 成功: {stats['succeeded']} | 失敗: {stats['failed']}",
                ''
            )
        except Exception as e:
            logger.warning(f"[enrichment] Notification failed: {e}")

    return stats
