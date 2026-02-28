"""LLM Settings DB module — encrypted API key pool, model config, filter rules, daily usage.

Uses Fernet symmetric encryption (AES-128-CBC via cryptography library)
derived from the application's SECRET_KEY to protect stored API keys.
"""
import json
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encryption helpers (lazy-init to avoid import errors if cryptography missing)
# ---------------------------------------------------------------------------

_fernet = None


def _get_fernet():
    """Get or create a Fernet instance derived from SECRET_KEY."""
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib
    except ImportError:
        logger.warning("[llm_settings] cryptography not installed — keys stored in plaintext")
        return None

    from config import Config
    secret = Config.SECRET_KEY or 'dev-secret-key-change-me'
    # Derive a 32-byte key from SECRET_KEY using SHA-256, then base64 for Fernet
    key_bytes = hashlib.sha256(secret.encode('utf-8')).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    _fernet = Fernet(fernet_key)
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext, or plaintext if crypto unavailable."""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a string. Returns plaintext, or the input unchanged if crypto unavailable."""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except Exception:
        # Might be stored in plaintext from before encryption was enabled
        return ciphertext


# ---------------------------------------------------------------------------
# Table creation SQL (called from db/__init__.py → init_db)
# ---------------------------------------------------------------------------

LLM_TABLES_SQL = """
-- API Key pool (encrypted storage)
CREATE TABLE IF NOT EXISTS llm_api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL DEFAULT 'gemini',
    api_key_encrypted TEXT NOT NULL,
    label TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    rpm_limit INTEGER DEFAULT 10,
    daily_limit INTEGER DEFAULT 1000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-workflow model configuration
CREATE TABLE IF NOT EXISTS llm_model_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL DEFAULT 'gemini',
    model_name TEXT NOT NULL DEFAULT 'gemini-3-flash-preview',
    endpoint_url TEXT DEFAULT '',
    temperature REAL DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4096,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Email filter rules (regex blacklist for sender / subject)
CREATE TABLE IF NOT EXISTS email_filter_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL CHECK(rule_type IN ('sender', 'subject')),
    pattern TEXT NOT NULL,
    description TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily LLM usage counters
CREATE TABLE IF NOT EXISTS llm_daily_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date DATE NOT NULL,
    key_id INTEGER,
    call_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    UNIQUE(usage_date, key_id),
    FOREIGN KEY (key_id) REFERENCES llm_api_keys(id) ON DELETE CASCADE
);
"""

# Default filter rules to seed on first run
_DEFAULT_FILTER_RULES = [
    ('sender', r'noreply@github\.com', 'GitHub notifications'),
    ('sender', r'no-reply@.*amazon', 'Amazon notifications'),
    ('sender', r'newsletter@', 'Generic newsletters'),
    ('subject', r'セール|半額|クーポン|ポイント', 'Shopping promotions'),
    ('subject', r'verify your|password reset|パスワード再設定', 'Account security'),
    ('subject', r'配送|お届け|tracking|shipment', 'Delivery notifications'),
]


def init_llm_tables(cursor=None):
    """Create LLM-related tables and seed default filter rules.
    
    Uses its own DB connection to avoid SQLite transaction conflicts
    when called from init_db() which uses executescript().
    """
    from db import get_db
    conn = get_db()
    c = conn.cursor()
    
    # Execute each CREATE TABLE as individual statements
    import re
    clean_sql = re.sub(r'--[^\n]*', '', LLM_TABLES_SQL)
    for stmt in clean_sql.split(';'):
        stmt = stmt.strip()
        if stmt:
            c.execute(stmt)

    # Seed default filter rules if table is empty
    c.execute("SELECT COUNT(*) FROM email_filter_rules")
    if c.fetchone()[0] == 0:
        for rule_type, pattern, desc in _DEFAULT_FILTER_RULES:
            c.execute(
                "INSERT INTO email_filter_rules (rule_type, pattern, description) VALUES (?, ?, ?)",
                (rule_type, pattern, desc)
            )

    # Seed default model configs if table is empty
    c.execute("SELECT COUNT(*) FROM llm_model_config")
    if c.fetchone()[0] == 0:
        defaults = [
            ('chat', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.7, 4096),
            ('email', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.3, 2048),
            ('job', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.5, 2048),
            ('job_detail', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.2, 3000),
            ('filter', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.1, 1024),
            ('es', 'deepseek', 'deepseek-chat', 'https://api.deepseek.com/v1', 0.7, 4096),
        ]
        for wf, prov, model, url, temp, tokens in defaults:
            c.execute(
                "INSERT INTO llm_model_config (workflow, provider, model_name, endpoint_url, temperature, max_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (wf, prov, model, url, temp, tokens)
            )

    conn.commit()
    conn.close()


# ===================================================================
# API Key CRUD
# ===================================================================

def add_api_key(provider: str, api_key: str, label: str = '',
                rpm_limit: int = 10, daily_limit: int = 1000) -> int:
    """Add a new API key (encrypted) and return its ID."""
    from db import get_db
    conn = get_db()
    encrypted = encrypt_value(api_key)
    cursor = conn.execute(
        "INSERT INTO llm_api_keys (provider, api_key_encrypted, label, rpm_limit, daily_limit) "
        "VALUES (?, ?, ?, ?, ?)",
        (provider, encrypted, label, rpm_limit, daily_limit)
    )
    conn.commit()
    key_id = cursor.lastrowid
    conn.close()
    logger.info(f"[llm_settings] Added API key id={key_id} provider={provider} label={label}")
    return key_id


def get_all_api_keys(include_secret: bool = False) -> list[dict]:
    """List all API keys. Secrets are masked unless include_secret=True."""
    from db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT id, provider, api_key_encrypted, label, enabled, rpm_limit, daily_limit, created_at "
        "FROM llm_api_keys ORDER BY id"
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        entry = {
            'id': r['id'],
            'provider': r['provider'],
            'label': r['label'],
            'enabled': bool(r['enabled']),
            'rpm_limit': r['rpm_limit'],
            'daily_limit': r['daily_limit'],
            'created_at': r['created_at'],
        }
        if include_secret:
            entry['api_key'] = decrypt_value(r['api_key_encrypted'])
        else:
            raw = decrypt_value(r['api_key_encrypted'])
            entry['api_key_preview'] = f"...{raw[-4:]}" if len(raw) >= 4 else '****'
        result.append(entry)
    return result


def delete_api_key(key_id: int):
    """Delete an API key by ID."""
    from db import get_db
    conn = get_db()
    conn.execute("DELETE FROM llm_api_keys WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    logger.info(f"[llm_settings] Deleted API key id={key_id}")


def toggle_api_key(key_id: int) -> bool:
    """Toggle enabled status of an API key. Returns new enabled state."""
    from db import get_db
    conn = get_db()
    conn.execute("UPDATE llm_api_keys SET enabled = 1 - enabled WHERE id = ?", (key_id,))
    conn.commit()
    row = conn.execute("SELECT enabled FROM llm_api_keys WHERE id = ?", (key_id,)).fetchone()
    conn.close()
    new_state = bool(row['enabled']) if row else False
    logger.info(f"[llm_settings] Toggled API key id={key_id} → enabled={new_state}")
    return new_state


def get_enabled_keys(provider: str = None) -> list[dict]:
    """Get all enabled API keys, optionally filtered by provider. Includes decrypted key."""
    from db import get_db
    conn = get_db()
    if provider:
        rows = conn.execute(
            "SELECT id, provider, api_key_encrypted, label, rpm_limit, daily_limit "
            "FROM llm_api_keys WHERE enabled = 1 AND provider = ? ORDER BY id",
            (provider,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, provider, api_key_encrypted, label, rpm_limit, daily_limit "
            "FROM llm_api_keys WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    conn.close()

    return [{
        'id': r['id'],
        'provider': r['provider'],
        'api_key': decrypt_value(r['api_key_encrypted']),
        'label': r['label'],
        'rpm_limit': r['rpm_limit'],
        'daily_limit': r['daily_limit'],
    } for r in rows]


# ===================================================================
# Model Config CRUD
# ===================================================================

def get_model_config(workflow: str) -> dict | None:
    """Get model configuration for a specific workflow."""
    from db import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM llm_model_config WHERE workflow = ?", (workflow,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_all_model_configs() -> list[dict]:
    """Get all workflow model configurations."""
    from db import get_db
    conn = get_db()
    rows = conn.execute("SELECT * FROM llm_model_config ORDER BY workflow").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_model_config(workflow: str, provider: str, model_name: str,
                      endpoint_url: str = '', temperature: float = 0.7,
                      max_tokens: int = 4096):
    """Insert or update model config for a workflow."""
    from db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO llm_model_config (workflow, provider, model_name, endpoint_url, temperature, max_tokens, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(workflow) DO UPDATE SET "
        "provider=excluded.provider, model_name=excluded.model_name, "
        "endpoint_url=excluded.endpoint_url, temperature=excluded.temperature, "
        "max_tokens=excluded.max_tokens, updated_at=CURRENT_TIMESTAMP",
        (workflow, provider, model_name, endpoint_url, temperature, max_tokens)
    )
    conn.commit()
    conn.close()
    logger.info(f"[llm_settings] Saved model config: {workflow} → {provider}/{model_name}")


# ===================================================================
# Email Filter Rules CRUD
# ===================================================================

def get_all_filter_rules() -> list[dict]:
    """Get all email filter rules."""
    from db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM email_filter_rules ORDER BY rule_type, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_enabled_filter_rules() -> list[dict]:
    """Get only enabled filter rules."""
    from db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM email_filter_rules WHERE enabled = 1 ORDER BY rule_type, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_filter_rule(rule_type: str, pattern: str, description: str = '') -> int:
    """Add a new email filter rule. Returns the new rule ID."""
    from db import get_db
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO email_filter_rules (rule_type, pattern, description) VALUES (?, ?, ?)",
        (rule_type, pattern, description)
    )
    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()
    logger.info(f"[llm_settings] Added filter rule id={rule_id}: {rule_type} → {pattern}")
    return rule_id


def delete_filter_rule(rule_id: int):
    """Delete a filter rule by ID."""
    from db import get_db
    conn = get_db()
    conn.execute("DELETE FROM email_filter_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    logger.info(f"[llm_settings] Deleted filter rule id={rule_id}")


def toggle_filter_rule(rule_id: int) -> bool:
    """Toggle enabled status of a filter rule. Returns new state."""
    from db import get_db
    conn = get_db()
    conn.execute("UPDATE email_filter_rules SET enabled = 1 - enabled WHERE id = ?", (rule_id,))
    conn.commit()
    row = conn.execute("SELECT enabled FROM email_filter_rules WHERE id = ?", (rule_id,)).fetchone()
    conn.close()
    return bool(row['enabled']) if row else False


# ===================================================================
# Daily Usage Tracking
# ===================================================================

def increment_usage(key_id: int, tokens: int = 0):
    """Increment the daily call counter for a specific key."""
    from db import get_db
    today = date.today().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO llm_daily_usage (usage_date, key_id, call_count, token_count) "
        "VALUES (?, ?, 1, ?) "
        "ON CONFLICT(usage_date, key_id) DO UPDATE SET "
        "call_count = call_count + 1, token_count = token_count + ?",
        (today, key_id, tokens, tokens)
    )
    conn.commit()
    conn.close()


def get_daily_usage(key_id: int = None) -> list[dict]:
    """Get today's usage, optionally filtered by key."""
    from db import get_db
    today = date.today().isoformat()
    conn = get_db()
    if key_id is not None:
        rows = conn.execute(
            "SELECT * FROM llm_daily_usage WHERE usage_date = ? AND key_id = ?",
            (today, key_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT u.*, k.label, k.provider, k.daily_limit "
            "FROM llm_daily_usage u "
            "LEFT JOIN llm_api_keys k ON u.key_id = k.id "
            "WHERE u.usage_date = ?",
            (today,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_daily_calls() -> int:
    """Get total LLM calls made today across all keys."""
    from db import get_db
    today = date.today().isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(call_count), 0) as total FROM llm_daily_usage WHERE usage_date = ?",
        (today,)
    ).fetchone()
    conn.close()
    return row['total'] if row else 0


def is_key_over_daily_limit(key_id: int) -> bool:
    """Check if a specific key has exceeded its daily limit."""
    from db import get_db
    today = date.today().isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT u.call_count, k.daily_limit "
        "FROM llm_api_keys k "
        "LEFT JOIN llm_daily_usage u ON u.key_id = k.id AND u.usage_date = ? "
        "WHERE k.id = ?",
        (today, key_id)
    ).fetchone()
    conn.close()
    if not row:
        return False
    calls = row['call_count'] or 0
    limit = row['daily_limit'] or 1000
    return calls >= limit
