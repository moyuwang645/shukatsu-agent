"""Deadline and interview reminder checks."""
import logging
from datetime import date

logger = logging.getLogger(__name__)


def check_deadlines_today():
    """Enqueue deadline check tasks."""
    try:
        from db.task_queue import enqueue
        enqueue('check_deadlines', priority=3)
        logger.info("[scheduler] Enqueued check_deadlines task")
    except Exception as e:
        logger.exception(f"[scheduler] Deadline check enqueue error: {e}")
        _check_deadlines_direct()


def _check_deadlines_direct():
    """Fallback: run deadline checks directly."""
    from database import get_jobs_by_deadline, create_notification
    today = date.today().isoformat()
    jobs = get_jobs_by_deadline(today)
    for job in jobs:
        create_notification(
            'deadline_today',
            f"⚠️ 本日締切: {job['company_name']}",
            f"ポジション: {job.get('position', '未設定')} | 締切: {today}",
            job.get('job_url', '')
        )
        logger.info(f"Deadline notification: {job['company_name']}")

    if jobs:
        logger.info(f"Generated {len(jobs)} deadline notifications for today")


def check_upcoming_deadlines():
    """Check for 本選考 jobs with deadlines in the next 3 days.

    Focuses on companies the user is actively interested in
    (status: 本選, applied, interviewing) and generates
    detailed notifications with position + location info.
    """
    from database import get_honsen_urgent_deadlines, get_upcoming_deadlines, create_notification

    # --- 1. 本選考 urgent alerts (status = 本選 / applied / interviewing) ---
    honsen_jobs = get_honsen_urgent_deadlines(days=3)
    for job in honsen_jobs:
        pos = job.get('position') or '未設定'
        loc = job.get('location') or ''
        detail = f"職種: {pos}"
        if loc:
            detail += f" | 勤務地: {loc}"
        detail += f" | 締切: {job['deadline']}"

        create_notification(
            'deadline_honsen',
            f"🚨 本選締切間近: {job['company_name']}",
            detail,
            job.get('job_url', '')
        )
        logger.info(f"Honsen deadline alert: {job['company_name']} → {job['deadline']}")

    if honsen_jobs:
        logger.info(f"Generated {len(honsen_jobs)} 本選考 deadline alerts")

    # --- 2. General upcoming deadlines (all statuses) ---
    jobs = get_upcoming_deadlines(days=3)
    for job in jobs:
        # Skip if already covered by honsen alert above
        if job.get('status') in ('本選', 'applied', 'es_passed', 'spi', 'gd',
                                   'interview_1', 'interview_2', 'interview_final',
                                   'interviewing'):
            continue
        if job.get('deadline') and job['deadline'] != date.today().isoformat():
            create_notification(
                'deadline_upcoming',
                f"📅 締切間近: {job['company_name']}",
                f"締切日: {job['deadline']}",
                job.get('job_url', '')
            )


def check_interviews_today():
    """Check for interviews scheduled today and generate reminders."""
    from database import get_upcoming_interviews, create_notification
    interviews = get_upcoming_interviews(days=1)

    for iv in interviews:
        create_notification(
            'interview_reminder',
            f"🎯 本日面接: {iv['company_name']}",
            f"時間: {iv.get('scheduled_at', '未設定')} | 場所: {iv.get('location', '未設定')}",
            iv.get('online_url', '')
        )
        logger.info(f"Interview reminder: {iv['company_name']}")
