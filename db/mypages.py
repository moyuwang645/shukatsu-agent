"""MyPage credentials CRUD — stores login URL, ID, and current password for each company."""
import json
from datetime import datetime
from . import get_db_connection


def save_mypage_credential(job_id: int, login_url: str, username: str,
                           password: str, source_email_id: str = None) -> int:
    """Create or update MyPage credential for a job.

    Always keeps the latest password. Returns the credential row id.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # Upsert: update if job_id exists, else insert
        existing = cursor.execute(
            "SELECT id FROM mypage_credentials WHERE job_id = ?", (job_id,)
        ).fetchone()

        if existing:
            cursor.execute('''
                UPDATE mypage_credentials
                SET login_url = ?, username = ?, current_password = ?,
                    source_email_id = ?, updated_at = ?
                WHERE job_id = ?
            ''', (login_url, username, password, source_email_id, now, job_id))
            cred_id = existing['id']
        else:
            cursor.execute('''
                INSERT INTO mypage_credentials
                    (job_id, login_url, username, initial_password,
                     current_password, source_email_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'received', ?, ?)
            ''', (job_id, login_url, username, password, password,
                  source_email_id, now, now))
            cred_id = cursor.lastrowid

        conn.commit()
        return cred_id


def update_mypage_password(job_id: int, new_password: str):
    """Update the current password after a password change."""
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE mypage_credentials
            SET current_password = ?, updated_at = ?
            WHERE job_id = ?
        ''', (new_password, datetime.now().isoformat(), job_id))
        conn.commit()


def update_mypage_status(job_id: int, status: str, error_msg: str = None):
    """Update MyPage processing status.

    Statuses: received, logging_in, password_changed, profile_filled,
              es_filling, draft_saved, ready_for_review,
              manual_intervention_needed, submitted, failed
    """
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE mypage_credentials
            SET status = ?, error_message = ?, updated_at = ?
            WHERE job_id = ?
        ''', (status, error_msg, datetime.now().isoformat(), job_id))
        conn.commit()


def get_mypage_credential(job_id: int) -> dict | None:
    """Get saved credentials for a specific job."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM mypage_credentials WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_mypage_credentials() -> list:
    """Get all saved MyPage credentials with company names (via JOIN)."""
    with get_db_connection() as conn:
        rows = conn.execute('''
            SELECT mc.*, j.company_name, j.position, j.job_url
            FROM mypage_credentials mc
            LEFT JOIN jobs j ON mc.job_id = j.id
            ORDER BY mc.updated_at DESC
        ''').fetchall()
        return [dict(r) for r in rows]


def get_mypage_by_status(status: str) -> list:
    """Get all MyPage credentials with a specific status."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM mypage_credentials WHERE status = ? ORDER BY updated_at ASC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_mypage_screenshot(job_id: int, screenshot_path: str):
    """Save the path to a screenshot of the MyPage state."""
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE mypage_credentials
            SET last_screenshot = ?, updated_at = ?
            WHERE job_id = ?
        ''', (screenshot_path, datetime.now().isoformat(), job_id))
        conn.commit()


def delete_mypage_credential(job_id: int):
    """Delete MyPage credential for a job."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM mypage_credentials WHERE job_id = ?", (job_id,))
        conn.commit()
