"""User preferences (search keywords) and scrape logs."""
from . import get_db_connection, get_db_read


# ========== User Preferences ==========

def get_preferences(enabled_only=False):
    with get_db_read() as conn:
        query = "SELECT * FROM user_preferences"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at ASC"
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]


def add_preference(keyword: str) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO user_preferences (keyword) VALUES (?)",
            (keyword.strip(),)
        )
        conn.commit()
        return cursor.lastrowid


def delete_preference(pref_id: int):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_preferences WHERE id = ?", (pref_id,))
        conn.commit()


def toggle_preference(pref_id: int):
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE user_preferences SET enabled = 1 - enabled WHERE id = ?",
            (pref_id,)
        )
        conn.commit()


# ========== Scrape Logs ==========

def log_scrape(source, status, jobs_found=0, jobs_updated=0, error_message=''):
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO scrape_logs (source, status, jobs_found, jobs_updated, error_message)
            VALUES (?, ?, ?, ?, ?)
        ''', (source, status, jobs_found, jobs_updated, error_message))
        conn.commit()


def get_last_scrape(source):
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_logs WHERE source = ? ORDER BY created_at DESC LIMIT 1",
            (source,)
        ).fetchone()
        return dict(row) if row else None


# Alias for service layer compatibility
get_all_preferences = get_preferences
