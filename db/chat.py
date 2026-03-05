"""AI Chat session CRUD operations."""
import uuid
from . import get_db_connection, get_db_read


def new_session_id() -> str:
    """Generate a new unique session ID."""
    return str(uuid.uuid4())


def add_message(session_id: str, role: str, content: str, metadata: str = None) -> int:
    """Add a message to a chat session."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO ai_chats (session_id, role, content, metadata)
            VALUES (?, ?, ?, ?)
        ''', (session_id, role, content, metadata))
        msg_id = cursor.lastrowid
        conn.commit()
    return msg_id


def get_session_messages(session_id: str) -> list:
    """Get all messages for a session, ordered chronologically."""
    with get_db_read() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_chats WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_sessions() -> list:
    """Get a list of all unique sessions with their first message and timestamp."""
    with get_db_read() as conn:
        rows = conn.execute('''
            SELECT session_id,
                   MIN(created_at) as started_at,
                   MAX(created_at) as last_message_at,
                   COUNT(*) as message_count
            FROM ai_chats
            GROUP BY session_id
            ORDER BY MAX(created_at) DESC
        ''').fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str):
    """Delete all messages in a session."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ai_chats WHERE session_id = ?", (session_id,))
        conn.commit()
