"""Job CRUD operations."""
import logging
from datetime import datetime
from . import get_db_connection

logger = logging.getLogger(__name__)


def create_job(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO jobs (company_name, company_name_jp, position, job_url, source,
                             source_id, deadline, status, notes, salary, location, job_type,
                             industry, job_description, ai_summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('company_name', ''),
            data.get('company_name_jp', ''),
            data.get('position', ''),
            data.get('job_url', ''),
            data.get('source', 'manual'),
            data.get('source_id'),
            data.get('deadline'),
            data.get('status', 'interested'),
            data.get('notes', ''),
            data.get('salary', ''),
            data.get('location', ''),
            data.get('job_type', ''),
            data.get('industry', ''),
            data.get('job_description', ''),
            data.get('ai_summary', ''),
            now, now
        ))
        conn.commit()
        job_id = cursor.lastrowid

    # Real-time push to frontend
    try:
        from services.sse_hub import publish_job_event
        job_data = dict(data)
        job_data['id'] = job_id
        job_data['created_at'] = now
        job_data['updated_at'] = now
        publish_job_event('created', job_data)
    except Exception as e:
        logger.warning(f"[jobs] SSE push failed for create_job: {e}")

    return job_id


def update_job(job_id, data, force=False):
    """Update a job record.

    By default (force=False), only overwrites fields that are currently
    empty/None in the DB — protecting good AI-enriched data from being
    replaced by empty scraper values.

    Set force=True for manual edits where the user explicitly wants to
    overwrite existing values.
    """
    with get_db_connection() as conn:
        current = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not current:
            return False
        current = dict(current)

        fields = []
        values = []
        for key in ['company_name', 'company_name_jp', 'position', 'job_url',
                    'deadline', 'status', 'notes', 'salary', 'location', 'job_type',
                    'industry', 'job_description', 'ai_summary']:
            if key not in data:
                continue
            new_val = data[key]
            old_val = current.get(key)

            if force:
                # Manual edit — always overwrite
                fields.append(f"{key} = ?")
                values.append(new_val)
            else:
                # Auto-update — only fill empty fields or accept longer values
                if not old_val or (new_val and len(str(new_val)) > len(str(old_val or ''))):
                    fields.append(f"{key} = ?")
                    values.append(new_val)

        if not fields:
            return False
        now = datetime.now().isoformat()
        fields.append("updated_at = ?")
        values.append(now)
        values.append(job_id)
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    # Real-time push to frontend
    try:
        from services.sse_hub import publish_job_event
        updated_data = dict(data)
        updated_data['id'] = job_id
        updated_data['updated_at'] = now
        publish_job_event('updated', updated_data)
    except Exception as e:
        logger.warning(f"[jobs] SSE push failed for update_job id={job_id}: {e}")

    return True


def delete_job(job_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def delete_all_jobs():
    """Delete all jobs from the database."""
    with get_db_connection() as conn:
        deleted = conn.execute("DELETE FROM jobs").rowcount
        conn.commit()

    # Notify frontend
    try:
        from services.sse_hub import publish_job_event
        publish_job_event('all_deleted', {'deleted_count': deleted})
    except Exception as e:
        logger.warning(f"[jobs] SSE push failed for delete_all_jobs: {e}")

    return deleted


def get_job(job_id):
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_all_jobs(status=None, source=None):
    with get_db_connection() as conn:
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY deadline ASC NULLS LAST, updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_jobs_by_deadline(date_str):
    """Get jobs with deadline on a specific date."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE deadline = ? AND status NOT IN ('rejected', 'withdrawn')",
            (date_str,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_upcoming_deadlines(days=7):
    """Get jobs with deadlines in the next N days."""
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT * FROM jobs
            WHERE deadline IS NOT NULL
              AND deadline >= date('now')
              AND deadline <= date('now', '+' || ? || ' days')
              AND status NOT IN ('rejected', 'withdrawn')
            ORDER BY deadline ASC
        ''', (days,)).fetchall()
        return [dict(r) for r in rows]


def get_honsen_urgent_deadlines(days=3):
    """Get jobs in active selection with deadlines within the next N days."""
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT * FROM jobs
            WHERE deadline IS NOT NULL
              AND deadline >= date('now')
              AND deadline <= date('now', '+' || ? || ' days')
              AND status IN ('本選', 'applied', 'es_passed', 'spi', 'gd',
                             'interview_1', 'interview_2', 'interview_final',
                             'interviewing')
            ORDER BY deadline ASC
        ''', (days,)).fetchall()
        return [dict(r) for r in rows]


def upsert_job_from_scraper(data):
    """Insert or update a job from scraper data.

    Matching strategy (in order):
    1. Exact match by (source, source_id) → update existing
    2. Cross-source match by normalized company name → merge fields
    3. No match → create new record
    """
    import logging
    logger = logging.getLogger(__name__)

    # Step 1: Exact match by source + source_id
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE source = ? AND source_id = ?",
            (data.get('source'), data.get('source_id'))
        ).fetchone()

    if existing:
        update_job(existing['id'], data)
        return existing['id'], False  # id, is_new

    # Step 2: Cross-source match by normalized company name
    company_name = data.get('company_name', '')
    if company_name:
        try:
            from services.company_normalizer import find_matching_job
            match = find_matching_job(company_name)
            if match:
                logger.info(
                    f"[upsert] Cross-source merge: '{company_name}' "
                    f"→ existing id={match['id']} (source={match['source']})"
                )
                # Merge into existing record, preserving existing data
                update_job(match['id'], data)
                return match['id'], False
        except Exception as e:
            logger.warning(f"[upsert] Cross-source matching error: {e}")

    # Step 3: Create new record
    job_id = create_job(data)
    return job_id, True


def get_job_stats():
    """Get job counts grouped by status (dynamic — no hardcoded status list)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        stats = {row['status']: row['cnt'] for row in rows}
        stats['total'] = sum(stats.values())
        return stats


def job_exists_by_source_id(source_id: str) -> bool:
    """Return True if a job with this source_id already exists."""
    if not source_id:
        return False
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE source_id = ?", (source_id,)
        ).fetchone()
        return row is not None


def get_job_by_source_id(source_id: str, source: str = '') -> dict | None:
    """Return the full job record matching source_id (and optionally source).

    Returns None if not found.
    """
    if not source_id:
        return None
    with get_db_connection() as conn:
        if source:
            row = conn.execute(
                "SELECT * FROM jobs WHERE source_id = ? AND source = ?",
                (source_id, source)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM jobs WHERE source_id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None


def get_unenriched_jobs(limit: int = 10) -> list:
    """Return jobs that have not yet been AI-enriched (ai_enriched = 0 or NULL)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            '''SELECT * FROM jobs
               WHERE (ai_enriched IS NULL OR ai_enriched = 0)
                 AND status NOT IN ('rejected', 'withdrawn')
               ORDER BY created_at DESC
               LIMIT ?''',
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_job_enrichment(job_id: int, data: dict) -> bool:
    """Update AI enrichment fields for a job.

    Expected keys in data: match_score, ai_summary, tags, ai_enriched
    """
    with get_db_connection() as conn:
        conn.execute(
            '''UPDATE jobs
               SET match_score = ?, ai_summary = ?, tags = ?, ai_enriched = ?,
                   updated_at = ?
               WHERE id = ?''',
            (
                data.get('match_score', 0),
                data.get('ai_summary', ''),
                data.get('tags', ''),
                data.get('ai_enriched', 1),
                datetime.now().isoformat(),
                job_id
            )
        )
        conn.commit()

    # Real-time push to frontend
    try:
        from services.sse_hub import publish_job_event
        publish_job_event('updated', {
            'id': job_id,
            'match_score': data.get('match_score', 0),
            'ai_summary': data.get('ai_summary', ''),
            'ai_enriched': 1,
        })
    except Exception as e:
        logger.warning(f"[jobs] SSE push failed for enrichment id={job_id}: {e}")

    return True
