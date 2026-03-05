"""Email cache CRUD operations."""
import logging
from . import get_db_connection, get_db_read

logger = logging.getLogger(__name__)


def cache_email(data):
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT OR IGNORE INTO email_cache
                (gmail_id, subject, sender, body_preview, received_at,
                 is_job_related, is_interview_invite)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('gmail_id'),
                data.get('subject', ''),
                data.get('sender', ''),
                data.get('body_preview', ''),
                data.get('received_at'),
                data.get('is_job_related', 0),
                data.get('is_interview_invite', 0)
            ))
            conn.commit()
    except Exception as e:
        logger.warning(f"[emails] cache_email failed for '{data.get('subject', '?')[:30]}': {e}")


def get_cached_emails(job_related_only=False, limit=100):
    with get_db_read() as conn:
        query = "SELECT * FROM email_cache"
        if job_related_only:
            query += " WHERE is_job_related = 1"
        query += " ORDER BY received_at DESC LIMIT ?"
        rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def mark_email_processed(gmail_id):
    """Mark an email as processed (event extraction done)."""
    with get_db_connection() as conn:
        conn.execute("UPDATE email_cache SET processed = 1 WHERE gmail_id = ?", (gmail_id,))
        conn.commit()


def is_email_processed(gmail_id):
    """Check if an email has already been processed for event extraction."""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT processed FROM email_cache WHERE gmail_id = ? AND processed = 1",
            (gmail_id,)
        ).fetchone()
    return row is not None


def get_email_count():
    """Return the total number of cached emails (used for first-run detection)."""
    with get_db_read() as conn:
        row = conn.execute("SELECT COUNT(*) FROM email_cache").fetchone()
    return row[0] if row else 0
