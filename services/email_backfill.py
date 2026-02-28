"""Email backfill service — one-shot scraper search to enrich email-created jobs.

When a new company is discovered from an email, this module triggers a targeted
scraper search and merges the results into the existing job record.

Includes the merge logic (previously in scrapers/__init__.py) that finds the
best matching scraper result and merges it into the email-created job.
"""
import logging

logger = logging.getLogger(__name__)


def run_email_backfill(keyword: str, job_id: int, scrapers: list = None):
    """One-shot scraper search to backfill an email-created job.

    Reuses the existing search pipeline (scraper search → AI enrich → save),
    then merges the best matching result into the target email job.

    After a successful backfill (job now has a job_url), automatically chains
    a detail_enrich task to fill missing fields (position, industry, location).

    Args:
        keyword: company name to search for.
        job_id: target job ID to merge results into.
        scrapers: optional list of specific scrapers to use.
                  None = use all available scrapers.
    """
    from scrapers import dispatch

    logger.info(f"[email_backfill] Starting backfill for job {job_id}: '{keyword}'")
    result = dispatch(
        action='search',
        mode='email_backfill',
        keywords=[keyword],
        job_id=job_id,
        scrapers=scrapers,
    )
    found = result.get('total_found', 0)
    new = result.get('total_new', 0)
    logger.info(
        f"[email_backfill] Done for job {job_id}: "
        f"{found} found, {new} new"
    )

    # Chain: if backfill found data, the job likely now has a job_url.
    # Trigger detail_enrich to extract position/industry/location from
    # the detail page.
    if found > 0 or new > 0:
        try:
            from db.task_queue import enqueue
            enqueue('detail_enrich', priority=5,
                    params={'job_id': job_id})
            logger.info(
                f"[email_backfill] Chained detail_enrich for job {job_id}"
            )
        except Exception as e:
            logger.warning(f"[email_backfill] detail_enrich enqueue failed: {e}")

    return result


def merge_backfill_results(company_keyword: str, job_id: int,
                           candidates: list = None):
    """Find best scraper match and merge into target email job.

    Called after dispatch runs scrapers with company_keyword filter.
    In the new architecture, scrapers do NOT save to DB in backfill mode —
    they return raw data as `candidates` dicts for direct merge.

    Args:
        company_keyword: company name used for matching.
        job_id: target email job ID to merge into.
        candidates: raw scraped job dicts (not yet in DB).
    """
    try:
        from db.jobs import get_job, update_job
        from services.company_matcher import find_best_match

        if not candidates:
            logger.info(f"[backfill] No candidates for '{company_keyword}'")
            return

        target = get_job(job_id)
        if not target:
            logger.warning(f"[backfill] Target job {job_id} not found")
            return

        # Check if target already has key fields filled
        key_fields = ('position', 'salary', 'location', 'industry')
        filled = sum(1 for f in key_fields if target.get(f))
        if filled >= 3:
            logger.info(
                f"[backfill] Job {job_id} already has {filled}/4 "
                f"key fields, skipping"
            )
            return

        # Find best match from raw scraper candidates (NOT from DB)
        match = find_best_match(company_keyword, candidates)

        if match:
            # Unified merge: AI decides which fields to keep/fill
            from ai.ai_merge import ai_merge, MergeMode

            scraper_source = match.job.get('source', 'scraper')
            merged = ai_merge(
                existing=dict(target),
                new_data=dict(match.job),
                data_source=scraper_source,
                mode=MergeMode.AUTO,
                prompt_key='backfill',
            )

            # Calculate which fields actually changed
            changed_fields = {}
            for key, val in merged.items():
                if key in ('id', 'source', 'created_at'):
                    continue
                old_val = target.get(key)
                if val and val != old_val:
                    changed_fields[key] = val

            if changed_fields:
                update_job(job_id, changed_fields, force=False)
                logger.info(
                    f"[backfill] Merged {len(changed_fields)} fields from "
                    f"'{match.job.get('company_name')}' "
                    f"(score={match.score}, method={match.method}) "
                    f"into job {job_id}: {list(changed_fields.keys())}"
                )

                # Enqueue detail_enrich if we got a job_url
                if changed_fields.get('job_url'):
                    try:
                        from db.task_queue import enqueue
                        enqueue('detail_enrich', priority=4,
                                params={'job_id': job_id})
                        logger.info(
                            f"[backfill] Enqueued detail_enrich for "
                            f"job {job_id} (url={changed_fields['job_url'][:60]})"
                        )
                    except Exception as e:
                        logger.warning(f"[backfill] detail_enrich enqueue failed: {e}")
            else:
                logger.info(
                    f"[backfill] No new fields to merge for job {job_id}"
                )
        else:
            logger.info(
                f"[backfill] No good match found for '{company_keyword}'"
            )
    except Exception as e:
        logger.warning(f"[backfill] Merge error: {e}")
