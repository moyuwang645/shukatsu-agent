"""Application Service — manages the mass-application (海投) pipeline.

Responsibilities:
  1. `create_application_queue`: Takes a list of job_ids, generates
     company-specific ES for each, and enqueues them as 'pending' applications.
  2. `process_application_queue`: Picks the next 'pending' application,
     calls entry_bot to auto-fill the entry form (dry_run by default),
     updates status to 'submitted' or 'failed'.
  3. `get_queue_status`: Returns a summary of all queue entries.
"""
import json
import logging
import time

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Queue creation — generate ES for each job and save to applications table
# ─────────────────────────────────────────────────────────────────────────────

def create_application_queue(job_ids: list[int], es_document_id: int,
                              dry_run: bool = True) -> dict:
    """Generate company-customized ES for each job and enqueue applications.

    Args:
        job_ids: List of job IDs to apply to.
        es_document_id: The ES document to use as the base.
        dry_run: If True, form filling will not submit (safe mode).

    Returns:
        dict with: queued, skipped, errors
    """
    from db.jobs import get_job
    from db.es import get_es_document
    from db.applications import create_application, application_exists
    from db.openwork import get_openwork_data
    from ai.es_writer import generate_custom_es
    from ai import is_ai_configured

    stats = {'queued': 0, 'skipped': 0, 'errors': []}

    # Load base ES
    es_doc = get_es_document(es_document_id)
    if not es_doc:
        raise ValueError(f"ES document {es_document_id} not found")

    try:
        parsed = json.loads(es_doc.get('parsed_data', '{}'))
    except json.JSONDecodeError:
        parsed = {'self_pr': es_doc.get('raw_text', ''), 'motivation': '', 'strengths': []}

    logger.info(f"[app_service] Creating queue: {len(job_ids)} jobs, dry_run={dry_run}")

    for job_id in job_ids:
        try:
            # Skip if already queued
            if application_exists(job_id, es_document_id):
                logger.debug(f"[app_service] Job {job_id} already in queue, skipping")
                stats['skipped'] += 1
                continue

            job = get_job(job_id)
            if not job:
                logger.warning(f"[app_service] Job {job_id} not found")
                stats['errors'].append(f"Job {job_id} not found")
                continue

            job_dict = dict(job)

            # Try to get OpenWork data for richer ES customization
            openwork_data = None
            try:
                ow = get_openwork_data(job_dict.get('company_name', ''))
                if ow:
                    openwork_data = dict(ow)
            except Exception:
                pass

            # Generate custom ES if AI is ready
            custom_es = None
            if is_ai_configured():
                try:
                    custom_es = generate_custom_es(parsed, job_dict, openwork_data)
                    time.sleep(5)  # Rate limiting
                except Exception as e:
                    logger.warning(f"[app_service] ES generation failed for job {job_id}: {e}")

            # Build application record
            app_data = {
                'job_id': job_id,
                'es_document_id': es_document_id,
                'status': 'pending',
                'dry_run': 1 if dry_run else 0,
                'custom_self_pr': (custom_es or {}).get('custom_self_pr', parsed.get('self_pr', '')),
                'custom_motivation': (custom_es or {}).get('custom_motivation', parsed.get('motivation', '')),
                'notes': f"AI ES {'生成済' if custom_es else '未生成（フォールバック）'}",
            }

            create_application(app_data)
            stats['queued'] += 1
            logger.info(f"[app_service] Queued job {job_id}: {job_dict.get('company_name')}")

        except Exception as e:
            logger.error(f"[app_service] Error queuing job {job_id}: {e}")
            stats['errors'].append(f"Job {job_id}: {e}")

    logger.info(
        f"[app_service] Queue created: {stats['queued']} queued, "
        f"{stats['skipped']} skipped, {len(stats['errors'])} errors"
    )
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Queue processing — run entry_bot on pending applications
# ─────────────────────────────────────────────────────────────────────────────

def process_application_queue(max_per_run: int = 3) -> dict:
    """Process pending applications in the queue.

    Picks up to `max_per_run` pending applications and runs entry_bot
    in dry_run or live mode based on the application's `dry_run` flag.

    Args:
        max_per_run: Maximum applications to process per invocation.

    Returns:
        dict with: processed, submitted, failed, dry_run_filled
    """
    from db.applications import get_pending_applications, update_application_status
    from db.jobs import get_job
    from automators.entry_bot import auto_fill_form

    stats = {'processed': 0, 'submitted': 0, 'failed': 0, 'dry_run_filled': 0}

    pending = get_pending_applications(limit=max_per_run)
    if not pending:
        logger.info("[app_service] No pending applications in queue.")
        return stats

    logger.info(f"[app_service] Processing {len(pending)} pending applications")

    for app in pending:
        app_id = app['id']
        job_id = app['job_id']
        is_dry = bool(app.get('dry_run', 1))

        try:
            job = get_job(job_id)
            if not job:
                logger.warning(f"[app_service] App {app_id}: job {job_id} not found")
                update_application_status(app_id, 'failed', 'Job not found')
                stats['failed'] += 1
                continue

            job_url = job.get('job_url', '')
            if not job_url:
                logger.warning(f"[app_service] App {app_id}: no job_url for job {job_id}")
                update_application_status(app_id, 'failed', 'No entry URL')
                stats['failed'] += 1
                continue

            es_data = {
                'custom_self_pr': app.get('custom_self_pr', ''),
                'custom_motivation': app.get('custom_motivation', ''),
            }

            logger.info(
                f"[app_service] App {app_id}: "
                f"{job.get('company_name')} | dry_run={is_dry}"
            )
            update_application_status(app_id, 'processing')

            result = auto_fill_form(job_url, es_data, dry_run=is_dry)

            status = result.get('status', 'error')
            message = result.get('message', '')
            screenshots = result.get('screenshots', [])
            notes = f"{message} | screenshots: {', '.join(screenshots)}" if screenshots else message

            if status == 'submitted':
                update_application_status(app_id, 'submitted', notes)
                stats['submitted'] += 1
            elif status == 'filled':
                # dry_run completed
                update_application_status(app_id, 'dry_run_done', notes)
                stats['dry_run_filled'] += 1
            else:
                update_application_status(app_id, 'failed', notes)
                stats['failed'] += 1

            stats['processed'] += 1

        except Exception as e:
            logger.error(f"[app_service] App {app_id} error: {e}")
            update_application_status(app_id, 'failed', str(e))
            stats['failed'] += 1

        time.sleep(3)  # Polite delay between applications

    logger.info(
        f"[app_service] Run done: {stats['submitted']} submitted, "
        f"{stats['dry_run_filled']} dry-run, {stats['failed']} failed"
    )

    if stats['processed'] > 0:
        try:
            from database import create_notification
            create_notification(
                'application_queue_run',
                f"海投キュー処理: {stats['processed']}件",
                (f"ドライラン: {stats['dry_run_filled']} | "
                 f"送信済: {stats['submitted']} | 失敗: {stats['failed']}"),
                ''
            )
        except Exception as e:
            logger.warning(f"[app_service] Notification failed: {e}")

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Status summary
# ─────────────────────────────────────────────────────────────────────────────

def get_queue_status() -> dict:
    """Return a summary of all application queue entries by status."""
    from db.applications import get_applications_summary
    try:
        return get_applications_summary()
    except Exception as e:
        logger.warning(f"[app_service] Could not get queue status: {e}")
        return {}
