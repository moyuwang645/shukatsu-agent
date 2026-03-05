"""User profile CRUD — stores personal info extracted from ES for auto-filling MyPage forms."""
import json
from . import get_db_connection, get_db_read


def save_user_profile(profile_data: dict) -> int:
    """Save or update the user's profile.

    We keep only one profile row (id=1). Each save overwrites.
    profile_data should contain keys like:
        name, name_kana, email, phone, postcode, address,
        university, faculty, department, graduation_year, graduation_month
    """
    profile_json = json.dumps(profile_data, ensure_ascii=False)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        existing = cursor.execute("SELECT id FROM user_profile LIMIT 1").fetchone()
        if existing:
            cursor.execute('''
                UPDATE user_profile
                SET profile_data = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (profile_json, existing['id']))
            pid = existing['id']
        else:
            cursor.execute('''
                INSERT INTO user_profile (profile_data) VALUES (?)
            ''', (profile_json,))
            pid = cursor.lastrowid
        conn.commit()
    return pid


def get_user_profile() -> dict | None:
    """Get the stored user profile as a dict."""
    with get_db_read() as conn:
        row = conn.execute("SELECT * FROM user_profile LIMIT 1").fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get('profile_data'):
        try:
            result['parsed'] = json.loads(result['profile_data'])
        except (ValueError, TypeError):
            result['parsed'] = {}
    return result


def get_profile_field(field_name: str, default='') -> str:
    """Get a single profile field value (convenience helper)."""
    profile = get_user_profile()
    if not profile or 'parsed' not in profile:
        return default
    return profile['parsed'].get(field_name, default)


def save_mypage_password(password: str):
    """Save the unified MyPage password to user settings."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        existing = cursor.execute(
            "SELECT id FROM user_settings WHERE key = 'mypage_password'"
        ).fetchone()
        if existing:
            cursor.execute(
                "UPDATE user_settings SET value = ? WHERE key = 'mypage_password'",
                (password,)
            )
        else:
            cursor.execute(
                "INSERT INTO user_settings (key, value) VALUES ('mypage_password', ?)",
                (password,)
            )
        conn.commit()


def get_mypage_password() -> str:
    """Get the unified MyPage password."""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = 'mypage_password'"
        ).fetchone()
    return row['value'] if row else ''
