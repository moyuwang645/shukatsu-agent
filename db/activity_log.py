"""Activity log — structured event logging for the frontend.

Records key system events (scraping, AI enrichment, email checks, errors)
in a queryable SQLite table. This complements the text-based app.log
with structured, filterable data.

Usage:
    from db.activity_log import log_activity, get_activity_log

    log_activity('scrape', 'career_tasu: 5 jobs found', level='info')
    log_activity('error', 'AI enrichment failed for job 123', level='error',
                  details={'job_id': 123, 'error': 'API timeout'})
"""
import json
import logging
from db import get_db, get_db_connection, get_db_read

logger = logging.getLogger(__name__)

# ── Table creation ──────────────────────────────────────────────────

ACTIVITY_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    level TEXT DEFAULT 'info' CHECK(level IN ('debug', 'info', 'warning', 'error')),
    details TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_activity_log_category
    ON activity_log(category, created_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_level
    ON activity_log(level, created_at);
"""


def init_activity_log_table():
    """Create activity_log table if not exists."""
    import re
    with get_db_connection() as conn:
        clean = re.sub(r'--[^\n]*', '', ACTIVITY_LOG_TABLE_SQL)
        for stmt in clean.split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()


# ── Write ───────────────────────────────────────────────────────────

def log_activity(category: str, message: str, level: str = 'info',
                 details: dict = None):
    """Record a structured activity log entry.

    Categories: scrape, enrich, email, task, system, error
    Levels: debug, info, warning, error
    """
    with get_db_connection() as conn:
        details_json = json.dumps(details or {}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO activity_log (category, message, level, details) "
            "VALUES (?, ?, ?, ?)",
            (category, message, level, details_json)
        )
        conn.commit()

    # Also forward to Python logger
    log_fn = getattr(logger, level, logger.info)
    log_fn(f"[{category}] {message}")


# ── Read ────────────────────────────────────────────────────────────

def get_activity_log(category: str = None, level: str = None,
                     limit: int = 50, offset: int = 0) -> list[dict]:
    """Get activity log entries, optionally filtered."""
    with get_db_read() as conn:
        query = "SELECT * FROM activity_log WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if level:
            query += " AND level = ?"
            params.append(level)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_activity_stats() -> dict:
    """Get today's activity summary."""
    with get_db_read() as conn:
        stats = {}

        # Counts by category today
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM activity_log "
            "WHERE DATE(created_at) = DATE('now', 'localtime') "
            "GROUP BY category"
        ).fetchall()
        stats['today_by_category'] = {r['category']: r['cnt'] for r in rows}

        # Error count today
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE level = 'error' AND DATE(created_at) = DATE('now', 'localtime')"
        ).fetchone()
        stats['errors_today'] = row['cnt']

        # Total today
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE DATE(created_at) = DATE('now', 'localtime')"
        ).fetchone()
        stats['total_today'] = row['cnt']

        return stats


def cleanup_old_logs(days: int = 30):
    """Remove activity log entries older than N days."""
    with get_db_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM activity_log WHERE created_at < datetime('now', 'localtime', ?)",
            (f'-{days} days',)
        ).rowcount
        conn.commit()
        if deleted:
            logger.info(f"[activity_log] Cleaned up {deleted} old entries")
        return deleted
