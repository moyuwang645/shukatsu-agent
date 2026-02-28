"""Application (auto-apply / 海投) tracking CRUD operations."""
from datetime import datetime
from . import get_db


def create_application(data: dict) -> int:
    """Create a new application record from a dict.

    Accepted keys:
        job_id, es_document_id, status (default 'pending'),
        dry_run (0/1), custom_self_pr, custom_motivation, notes
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO applications
            (job_id, es_id, status, ai_generated_es, error_message, submitted_at)
        VALUES (?, ?, ?, ?, ?, NULL)
    ''', (
        data.get('job_id'),
        data.get('es_document_id') or data.get('es_id'),
        data.get('status', 'pending'),
        _pack_custom_es(data),
        data.get('notes', ''),
    ))
    app_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return app_id


def _pack_custom_es(data: dict) -> str:
    """Serialize custom ES fields into a JSON string stored in ai_generated_es."""
    import json
    payload = {}
    if data.get('custom_self_pr'):
        payload['custom_self_pr'] = data['custom_self_pr']
    if data.get('custom_motivation'):
        payload['custom_motivation'] = data['custom_motivation']
    if data.get('dry_run') is not None:
        payload['dry_run'] = bool(data['dry_run'])
    return json.dumps(payload, ensure_ascii=False) if payload else ''


def get_application(app_id: int) -> dict | None:
    """Get a single application by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def application_exists(job_id: int, es_document_id: int) -> bool:
    """Check if an application already exists for this job + ES document."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM applications WHERE job_id = ? AND es_id = ?",
        (job_id, es_document_id)
    ).fetchone()
    conn.close()
    return row is not None


def get_pending_applications(limit: int = 5) -> list:
    """Get pending applications, enriched with custom ES data."""
    import json
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.*, j.company_name, j.position, j.job_url
           FROM applications a
           JOIN jobs j ON a.job_id = j.id
           WHERE a.status = 'pending'
           ORDER BY a.id ASC
           LIMIT ?''',
        (limit,)
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        app = dict(row)
        # Unpack custom ES fields from ai_generated_es JSON
        raw = app.get('ai_generated_es', '')
        if raw:
            try:
                extras = json.loads(raw)
                app.update(extras)
            except (ValueError, TypeError):
                pass
        result.append(app)
    return result


def get_applications_for_job(job_id: int) -> list:
    """Get all applications for a specific job."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM applications WHERE job_id = ? ORDER BY created_at DESC",
        (job_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_applications(status: str = None) -> list:
    """Get all applications, optionally filtered by status."""
    conn = get_db()
    query = '''
        SELECT a.*, j.company_name, j.company_name_jp, j.position
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
    '''
    params = []
    if status:
        query += " WHERE a.status = ?"
        params.append(status)
    query += " ORDER BY a.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_application_status(app_id: int, status: str, message: str = None):
    """Update application status (and submitted_at for 'submitted')."""
    conn = get_db()
    if status == 'submitted':
        conn.execute(
            "UPDATE applications SET status = ?, submitted_at = ?, error_message = ? WHERE id = ?",
            (status, datetime.now().isoformat(), message, app_id)
        )
    else:
        conn.execute(
            "UPDATE applications SET status = ?, error_message = ? WHERE id = ?",
            (status, message, app_id)
        )
    conn.commit()
    conn.close()


def set_generated_es(app_id: int, ai_generated_es: str):
    """Store the AI-generated ES content for an application."""
    conn = get_db()
    conn.execute(
        "UPDATE applications SET ai_generated_es = ?, status = 'ready' WHERE id = ?",
        (ai_generated_es, app_id)
    )
    conn.commit()
    conn.close()


def delete_application(app_id: int):
    """Delete an application record."""
    conn = get_db()
    conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()


def get_application_stats() -> dict:
    """Get counts by application status."""
    conn = get_db()
    stats = {}
    for status in ['pending', 'processing', 'ready', 'dry_run_done', 'submitted', 'failed']:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM applications WHERE status = ?", (status,)
        ).fetchone()
        stats[status] = row['cnt']
    stats['total'] = sum(stats.values())
    conn.close()
    return stats


# alias
get_applications_summary = get_application_stats
