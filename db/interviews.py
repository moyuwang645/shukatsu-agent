"""Interview CRUD operations."""
from . import get_db_connection, get_db_read


def create_interview(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO interviews (job_id, interview_type, scheduled_at, location,
                                   online_url, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('job_id'),
            data.get('interview_type', ''),
            data.get('scheduled_at'),
            data.get('location', ''),
            data.get('online_url', ''),
            data.get('notes', ''),
            data.get('status', 'scheduled')
        ))
        iid = cursor.lastrowid
        conn.commit()
    return iid


def get_interviews_for_job(job_id):
    with get_db_read() as conn:
        rows = conn.execute(
            "SELECT * FROM interviews WHERE job_id = ? ORDER BY scheduled_at ASC",
            (job_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_upcoming_interviews(days=7):
    with get_db_read() as conn:
        rows = conn.execute('''
            SELECT i.*, j.company_name, j.company_name_jp, j.position
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            WHERE i.scheduled_at >= datetime('now')
              AND i.scheduled_at <= datetime('now', '+' || ? || ' days')
              AND i.status = 'scheduled'
            ORDER BY i.scheduled_at ASC
        ''', (days,)).fetchall()
    return [dict(r) for r in rows]


def get_all_interviews():
    with get_db_read() as conn:
        rows = conn.execute('''
            SELECT i.*, j.company_name, j.company_name_jp, j.position
            FROM interviews i
            JOIN jobs j ON i.job_id = j.id
            ORDER BY i.scheduled_at DESC
        ''').fetchall()
    return [dict(r) for r in rows]


def update_interview(interview_id, data):
    with get_db_connection() as conn:
        fields = []
        values = []
        for key in ['interview_type', 'scheduled_at', 'location', 'online_url', 'notes', 'status']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if not fields:
            return False
        values.append(interview_id)
        conn.execute(f"UPDATE interviews SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return True


def delete_interview(interview_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        conn.commit()
