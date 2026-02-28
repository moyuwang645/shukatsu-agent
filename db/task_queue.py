"""Task queue — centralized task scheduling and execution tracking.

All scheduled and manual tasks are enqueued here. The TaskWorker
(services/task_worker.py) pulls and executes them in priority order.

Priority: 1 = highest (manual triggers), 10 = lowest
"""
import json
import logging
from db import get_db, get_db_connection

logger = logging.getLogger(__name__)

# ── Table creation (called from db/__init__.py) ─────────────────────

TASK_QUEUE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    params TEXT DEFAULT '{}',
    result TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    started_at TEXT,
    completed_at TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 2
);

CREATE INDEX IF NOT EXISTS idx_task_queue_status_priority
    ON task_queue(status, priority, created_at);
"""


def init_task_queue_table():
    """Create task_queue table if it doesn't exist."""
    import re
    with get_db_connection() as conn:
        clean = re.sub(r'--[^\n]*', '', TASK_QUEUE_TABLE_SQL)
        for stmt in clean.split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()


# ── CRUD ────────────────────────────────────────────────────────────

def enqueue(task_type: str, priority: int = 5, params: dict = None) -> int:
    """Add a task to the queue. Returns the task ID.

    Deduplicates: if an identical pending task exists, returns its ID.
    """
    with get_db_connection() as conn:
        params_json = json.dumps(params or {}, ensure_ascii=False)

        # Check for duplicate pending task with same type+params
        existing = conn.execute(
            "SELECT id FROM task_queue WHERE task_type = ? AND params = ? "
            "AND status = 'pending'",
            (task_type, params_json)
        ).fetchone()

        if existing:
            logger.debug(f"[task_queue] Dedup: {task_type} already pending (id={existing['id']})")
            return existing['id']

        cursor = conn.execute(
            "INSERT INTO task_queue (task_type, priority, params) VALUES (?, ?, ?)",
            (task_type, priority, params_json)
        )
        conn.commit()
        task_id = cursor.lastrowid
        logger.info(f"[task_queue] Enqueued: {task_type} (id={task_id}, priority={priority})")
        return task_id


def claim_next() -> dict | None:
    """Atomically claim the highest-priority pending task.

    Returns the task dict, or None if no tasks available.
    Uses DBWriter serialization — no explicit locking needed.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM task_queue WHERE status = 'pending' "
            "ORDER BY priority ASC, created_at ASC LIMIT 1"
        ).fetchone()

        if not row:
            return None

        # Mark as running (safe — DBWriter lock prevents race conditions)
        conn.execute(
            "UPDATE task_queue SET status = 'running', "
            "started_at = datetime('now', 'localtime') "
            "WHERE id = ?",
            (row['id'],)
        )
        conn.commit()

        task = dict(row)
        task['status'] = 'running'
        try:
            task['params'] = json.loads(task.get('params') or '{}')
        except (json.JSONDecodeError, TypeError):
            task['params'] = {}

        logger.info(f"[task_queue] Claimed: {task['task_type']} (id={task['id']})")
        return task


def complete(task_id: int, result: dict = None):
    """Mark a task as done with optional result data."""
    with get_db_connection() as conn:
        result_json = json.dumps(result or {}, ensure_ascii=False)
        conn.execute(
            "UPDATE task_queue SET status = 'done', result = ?, "
            "completed_at = datetime('now', 'localtime') WHERE id = ?",
            (result_json, task_id)
        )
        conn.commit()
        logger.info(f"[task_queue] Completed: id={task_id}")


def fail(task_id: int, error: str, retry: bool = True):
    """Mark a task as failed. Auto-retries if under max_retries."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT retry_count, max_retries FROM task_queue WHERE id = ?",
            (task_id,)
        ).fetchone()

        if row and retry and row['retry_count'] < row['max_retries']:
            # Re-queue for retry
            conn.execute(
                "UPDATE task_queue SET status = 'pending', error = ?, "
                "retry_count = retry_count + 1, started_at = NULL WHERE id = ?",
                (error, task_id)
            )
            logger.warning(
                f"[task_queue] Retry queued: id={task_id} "
                f"(attempt {row['retry_count'] + 1}/{row['max_retries']})"
            )
        else:
            conn.execute(
                "UPDATE task_queue SET status = 'failed', error = ?, "
                "completed_at = datetime('now', 'localtime') WHERE id = ?",
                (error, task_id)
            )
            logger.error(f"[task_queue] Failed permanently: id={task_id} — {error}")

        conn.commit()


def cancel(task_id: int) -> bool:
    """Cancel a pending task. Returns True if cancelled."""
    with get_db_connection() as conn:
        affected = conn.execute(
            "UPDATE task_queue SET status = 'cancelled', "
            "completed_at = datetime('now', 'localtime') "
            "WHERE id = ? AND status = 'pending'",
            (task_id,)
        ).rowcount
        conn.commit()
        if affected:
            logger.info(f"[task_queue] Cancelled: id={task_id}")
        return affected > 0


# ── Query ───────────────────────────────────────────────────────────

def get_queue(status: str = None, limit: int = 50) -> list[dict]:
    """Get tasks from the queue, optionally filtered by status."""
    with get_db_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM task_queue WHERE status = ? "
                "ORDER BY priority ASC, created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_queue WHERE status IN ('pending', 'running') "
                "ORDER BY priority ASC, created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_history(limit: int = 30) -> list[dict]:
    """Get recently completed/failed tasks."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM task_queue WHERE status IN ('done', 'failed', 'cancelled') "
            "ORDER BY completed_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_task(task_id: int) -> dict | None:
    """Get a single task by ID."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM task_queue WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None


def get_queue_stats() -> dict:
    """Get task queue statistics."""
    with get_db_connection() as conn:
        stats = {}
        for status in ('pending', 'running', 'done', 'failed'):
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM task_queue WHERE status = ?",
                (status,)
            ).fetchone()
            stats[status] = row['cnt']

        # Today's completed count
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM task_queue "
            "WHERE status = 'done' AND DATE(completed_at) = DATE('now', 'localtime')"
        ).fetchone()
        stats['done_today'] = row['cnt']

        return stats


def cleanup_old_tasks(days: int = 7):
    """Remove completed/failed tasks older than N days."""
    with get_db_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM task_queue WHERE status IN ('done', 'failed', 'cancelled') "
            "AND completed_at < datetime('now', 'localtime', ?)",
            (f'-{days} days',)
        ).rowcount
        conn.commit()
        if deleted:
            logger.info(f"[task_queue] Cleaned up {deleted} old tasks")
        return deleted
