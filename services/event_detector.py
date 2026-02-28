"""Automatic event detection and registration from emails.

Detects interviews, ES deadlines, and rejections from email content
and automatically creates entries in the database.
"""
import logging
from datetime import datetime
from database import (
    create_notification, create_interview,
    get_all_jobs, create_job, update_job,
)
from services import (
    ES_DEADLINE_KEYWORDS,
    extract_company_name, detect_interview_type,
    extract_location, extract_online_url, extract_dates_from_text,
)

logger = logging.getLogger(__name__)

# ── Expanded status model ────────────────────────────────────────────
# Pre-selection
STATUSES_PRE = {'interested', 'seminar', 'seminar_fast', 'casual'}
# Selection in progress
STATUSES_IN_PROGRESS = {'applied', 'es_passed', 'spi', 'gd',
                         'interview_1', 'interview_2', 'interview_3',
                         'interview_final', '本選'}
# Terminal
STATUSES_TERMINAL = {'offered', 'accepted', 'rejected', 'withdrawn'}

# ── Priority-based upgrade (higher = further in pipeline) ─────────────
# Status only goes UP, never DOWN. Any interview/event that maps to a
# higher-priority status will upgrade the job record.
STATUS_PRIORITY = {
    'interested':       0,
    'seminar':         10,
    'seminar_fast':    10,
    'casual':          15,   # カジュアル面談
    'applied':         20,   # 応募済み
    '本選':             25,   # 本選考
    'es_passed':       30,   # ES通過
    'spi':             35,   # SPI/Webテスト
    'gd':              40,   # グループディスカッション
    'interview_1':     50,   # 一次面接
    'interview_2':     60,   # 二次面接
    'interview_3':     70,   # 三次面接
    'interview_final': 80,   # 最終面接
    'offered':         90,   # 内定
    'accepted':        95,
    'rejected':         1,   # お祈り (override 不要)
    'withdrawn':        1,
}

# Map AI interview_type → job status
INTERVIEW_TYPE_TO_STATUS = {
    '一次面接':     'interview_1',
    '二次面接':     'interview_2',
    '三次面接':     'interview_3',
    '最終面接':     'interview_final',
    '役員面接':     'interview_final',
    'GD':          'gd',
    'グループディスカッション': 'gd',
    'グループ面接': 'interview_1',
    'Webテスト':   'spi',
    '適性検査':    'spi',
    'SPI':         'spi',
    'ES提出':      '本選',
    '説明会':      'seminar',
    'カジュアル面談': 'casual',
    '面談':        'casual',
    '面接':        'interview_1',  # generic fallback
    'その他':      None,           # don't upgrade
}

# Map AI event_type → initial job status
EVENT_TYPE_TO_STATUS = {
    'seminar': 'seminar',
    'es_deadline': '本選',
    'webtest': 'spi',
    'interview': 'interview_1',
    'offer': 'offered',
    'rejection': 'rejected',
}


def _upgrade_job_status(job_id: int, new_status: str) -> bool:
    """Upgrade a job's status if new_status has higher priority.

    Returns True if status was actually changed.
    Never downgrades: interview_2 will NOT overwrite interview_final.
    """
    if not new_status:
        return False

    from db.jobs import get_job
    job = get_job(job_id)
    if not job:
        return False

    current = job.get('status', 'interested')
    current_prio = STATUS_PRIORITY.get(current, 0)
    new_prio = STATUS_PRIORITY.get(new_status, 0)

    if new_prio > current_prio:
        update_job(job_id, {'status': new_status})
        logger.info(f"📈 Status upgrade: {current} → {new_status} "
                   f"(prio {current_prio}→{new_prio}) for job {job_id}")
        return True
    else:
        logger.debug(f"Status not upgraded: {current}({current_prio}) "
                    f">= {new_status}({new_prio})")
        return False


def auto_register_interview(email_data: dict) -> None:
    """Automatically detect interview/ES deadline info from email
    and register it in the database. Calls AI parser first."""
    subject = email_data.get('subject', '')
    sender = email_data.get('sender', '')
    body = email_data.get('full_body', '') or email_data.get('body_preview', '')
    full_text = f"{subject}\n{body}"

    # --- Step 0: Call AI parser to get structured data ---
    ai = email_data.get('ai_result')  # pre-parsed if available
    if ai is None:
        try:
            from ai.email_parser import parse_email_with_ai
            ai = parse_email_with_ai(subject, body, sender)
            if ai:
                email_data['ai_result'] = ai
                logger.info(f"📩 AI parsed: company={ai.get('company_name')}, type={ai.get('event_type')}")
        except Exception as e:
            logger.warning(f"AI parse failed for [{subject[:30]}]: {e}")

    # Skip non-job-related emails (AI said not related)
    if ai and ai.get('is_job_related') is False:
        logger.info(f"📩 Skipping non-job email: {subject[:50]}")
        return

    logger.info(f"📩 Auto-detecting event from: {subject}")

    # 1. Extract company name
    company_name = (ai.get('company_name') if ai else None) or extract_company_name(sender, subject, body)
    if not company_name:
        logger.info("Could not extract company name, skipping auto-register")
        create_notification(
            'interview_detected',
            f"📩 就活メール検出（企業名不明）",
            f"件名: {subject}\n送信者: {sender}\n※ 自動登録できませんでした。手動で確認してください。",
            ''
        )
        return

    # 2. Determine event type
    if ai:
        is_es_deadline = ai.get('event_type') == 'es_deadline'
        is_rejection = ai.get('event_type') == 'rejection'
    else:
        is_es_deadline = any(kw in full_text for kw in ES_DEADLINE_KEYWORDS)
        is_rejection = False

    # Skip rejections (お祈りメール) — but update status
    if is_rejection:
        # Force rejected status (ignores priority — rejection is terminal)
        job_id_rej = match_or_create_job(company_name, ai)
        update_job(job_id_rej, {'status': 'rejected'})
        create_notification(
            'rejection_detected',
            f"📩 選考結果: {company_name}",
            f"件名: {subject}\n{ai.get('summary', '') if ai else ''}",
            ''
        )
        logger.info(f"📩 Rejection detected → status=rejected: {company_name}")
        return

    # Handle offer
    is_offer = ai and ai.get('event_type') == 'offer'
    if is_offer:
        job_id_offer = match_or_create_job(company_name, ai)
        update_job(job_id_offer, {'status': 'offered'})
        create_notification(
            'offer_detected',
            f"🎉 内定通知: {company_name}",
            f"件名: {subject}\n{ai.get('summary', '') if ai else ''}",
            ''
        )
        logger.info(f"🎉 Offer detected → status=offered: {company_name}")
        return

    # 3. Extract date/time (AI-first, then regex fallback)
    scheduled_at = None
    deadline_date = None

    if ai:
        sd = ai.get('scheduled_date', '')
        st = ai.get('scheduled_time', '')
        dd = ai.get('deadline_date', '')
        # Treat 'なし' as empty
        if sd and sd not in ('なし', 'null', None):
            time_part = st if st and st not in ('なし', 'null', None) else '00:00'
            try:
                dt = datetime.strptime(f"{sd} {time_part}", '%Y-%m-%d %H:%M')
                scheduled_at = dt.isoformat()
            except ValueError:
                scheduled_at = f"{sd}T00:00:00"
        if dd and dd not in ('なし', 'null', None):
            deadline_date = dd

    if not scheduled_at and not deadline_date:
        # Regex fallback
        dates = extract_dates_from_text(full_text)
        if dates:
            now = datetime.now()
            future_dates = [d for d in dates if d > now]
            if future_dates:
                timed = [d for d in future_dates if d.hour != 0]
                if is_es_deadline:
                    deadline_date = future_dates[0].strftime('%Y-%m-%d')
                else:
                    scheduled_at = (timed[0] if timed else future_dates[0]).isoformat()

    # 4. Match to existing job or create new one
    job_id = match_or_create_job(company_name, ai)

    # Helper: treat 'なし' and null as empty
    def _ai_val(key):
        v = ai.get(key, '') if ai else ''
        return '' if v in (None, 'なし', 'null') else v

    # Extract structured fields from AI
    position = _ai_val('position')
    job_type = _ai_val('job_type')
    salary = _ai_val('salary')
    job_url = _ai_val('job_url')
    location_ai = _ai_val('location')

    if is_es_deadline:
        # --- ES Deadline: update job deadline ---
        summary = _ai_val('summary')
        update_data = {'notes': summary or f'📩 件名: {subject}'}
        if position:
            update_data['position'] = position
        if job_type:
            update_data['job_type'] = job_type
        if salary:
            update_data['salary'] = salary
        if job_url:
            update_data['job_url'] = job_url
        if location_ai:
            update_data['location'] = location_ai
        if deadline_date:
            update_data['deadline'] = deadline_date
            update_data['status'] = '本選'
        update_job(job_id, update_data)

        date_str = deadline_date or '日付不明'
        create_notification(
            'es_deadline_detected',
            f"📝 ES締切検出: {company_name}",
            f"締切日: {date_str}\n件名: {subject}",
            ''
        )
        logger.info(f"📝 ES deadline detected: {company_name} | {date_str}")
    else:
        # --- Interview: create interview record ---
        interview_type = (ai.get('interview_type') if ai else None) or detect_interview_type(full_text)
        location = (ai.get('location') if ai else None) or extract_location(full_text)
        online_url = (ai.get('online_url') if ai else None) or extract_online_url(full_text)

        summary = ai.get('summary', '') if ai else ''
        interview_data = {
            'job_id': job_id,
            'interview_type': interview_type,
            'scheduled_at': scheduled_at,
            'location': location or '',
            'online_url': online_url or '',
            'notes': f"📩 メールから自動登録\n件名: {subject}\n{summary}",
            'status': 'scheduled',
        }
        create_interview(interview_data)

        # --- Auto-upgrade job status based on interview type ---
        new_status = INTERVIEW_TYPE_TO_STATUS.get(interview_type)
        if new_status:
            _upgrade_job_status(job_id, new_status)

        time_str = scheduled_at[:16].replace('T', ' ') if scheduled_at else '日時不明'
        loc_str = location or online_url or '場所未定'
        ai_tag = ' 🤖' if ai else ''
        create_notification(
            'interview_auto_registered',
            f"✅ 面接自動登録{ai_tag}: {company_name}",
            f"種類: {interview_type} | 日時: {time_str} | 場所: {loc_str}",
            ''
        )
        logger.info(
            f"✅ Auto-registered interview{ai_tag}: {company_name} | "
            f"{interview_type} | {time_str} | {loc_str}"
        )




def match_or_create_job(company_name: str, ai: dict = None) -> int:
    """Find an existing job matching this company, or create a new one."""
    from services.company_matcher import find_best_match

    jobs = get_all_jobs()

    # Determine target status from AI event_type
    event_type = ai.get('event_type', '') if ai else ''
    target_status = EVENT_TYPE_TO_STATUS.get(event_type, 'interview_1')

    # AI-provided URL for domain matching
    ai_url = (ai.get('job_url', '') if ai else '') or ''

    # Unified matching via company_matcher
    match = find_best_match(company_name, jobs, url=ai_url)
    if match:
        _upgrade_job_status(match.job['id'],
                            EVENT_TYPE_TO_STATUS.get(event_type, 'interview_1'))
        return match.job['id']

    # No match — create new job via unified merge (existing=None → new card)
    from ai.ai_merge import ai_merge, MergeMode

    # Build new_data from AI-parsed email fields
    new_data = {
        'company_name': company_name,
        'company_name_jp': company_name,
        'status': target_status,
        'notes': '📩 メールから自動作成',
    }
    if ai:
        for field in ('position', 'job_type', 'location', 'salary', 'job_url',
                       'deadline', 'job_description'):
            val = ai.get(field, '')
            if val and val not in (None, 'なし', 'null'):
                new_data[field] = val

    # ai_merge(None, ...) = create new card
    # DIRECT mode: email_parser already extracted structured fields, no 2nd AI call
    job_data = ai_merge(
        existing=None,
        new_data=new_data,
        data_source='email',
        mode=MergeMode.DIRECT,
        prompt_key='email',
    )
    job_id = create_job(job_data)

    # Email-trigger-scrape: enqueue backfill to search and merge scraper data
    try:
        from db.task_queue import enqueue
        enqueue('email_backfill', priority=4,
                params={'keyword': company_name, 'job_id': job_id})
        logger.info(f"📩→🔍 Enqueued email backfill for: {company_name} (job_id={job_id})")
    except Exception as e:
        logger.warning(f"Email-trigger-scrape enqueue failed: {e}")

    # AI enrichment: immediately score/summarize the new job
    try:
        from db.task_queue import enqueue
        enqueue('enrich', priority=5)
        logger.info(f"📩→🤖 Enqueued AI enrichment after creating job for: {company_name}")
    except Exception as e:
        logger.warning(f"AI enrichment enqueue failed: {e}")

    return job_id
