"""Notification CRUD operations."""
from . import get_db_connection


def create_notification(ntype, title, message='', link=''):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO notifications (type, title, message, link) VALUES (?, ?, ?, ?)",
            (ntype, title, message, link)
        )
        conn.commit()


def get_unread_notifications():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_notifications(limit=50):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_notification_read(nid):
    with get_db_connection() as conn:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (nid,))
        conn.commit()


def mark_all_notifications_read():
    with get_db_connection() as conn:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        conn.commit()
