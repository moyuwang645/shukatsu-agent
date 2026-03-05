"""Gmail settings management — centralized config via user_settings table.

Stores Gmail fetch configuration (last_fetched_at, backfill_days,
keyword_limit, etc.) so modes can read/write their settings.
"""
import logging
from . import get_db_connection, get_db_read

logger = logging.getLogger(__name__)

# Default configuration values
_DEFAULTS = {
    'gmail_last_fetched_at': '',      # ISO timestamp of newest email from last fetch
    'gmail_backfill_days': '30',      # Days to look back on first run
    'gmail_keyword_limit': '10',      # Default limit for keyword search mode
}


def get_gmail_config() -> dict:
    """Return all gmail_* settings as a dict."""
    config = dict(_DEFAULTS)
    try:
        with get_db_read() as conn:
            rows = conn.execute(
                "SELECT key, value FROM user_settings WHERE key LIKE 'gmail_%'"
            ).fetchall()
        for row in rows:
            config[row['key']] = row['value']
    except Exception as e:
        logger.warning(f"[gmail_settings] Failed to read config: {e}")
    return config


def update_gmail_config(updates: dict):
    """Update one or more gmail_* settings."""
    try:
        with get_db_connection() as conn:
            for key, value in updates.items():
                if not key.startswith('gmail_'):
                    continue
                existing = conn.execute(
                    "SELECT id FROM user_settings WHERE key = ?", (key,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE user_settings SET value = ? WHERE key = ?",
                        (str(value), key)
                    )
                else:
                    conn.execute(
                        "INSERT INTO user_settings (key, value) VALUES (?, ?)",
                        (key, str(value))
                    )
            conn.commit()
    except Exception as e:
        logger.warning(f"[gmail_settings] Failed to update config: {e}")


def get_last_fetched_at() -> str:
    """Get the timestamp of the last successful Gmail fetch."""
    config = get_gmail_config()
    return config.get('gmail_last_fetched_at', '')


def set_last_fetched_at(timestamp: str):
    """Record the timestamp of the newest email from this fetch."""
    update_gmail_config({'gmail_last_fetched_at': timestamp})
    logger.info(f"[gmail_settings] last_fetched_at updated to {timestamp}")
