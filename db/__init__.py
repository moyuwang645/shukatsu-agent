"""Database package — split from the original monolithic database.py.

Usage:
    from db import init_db, get_db          # core
    from db.jobs import create_job, ...     # domain-specific

For backward compatibility the old `from database import X` still works
via the shim `database.py` that re-exports everything.
"""
import sqlite3
import os
from config import Config


def get_db():
    """Get database connection."""
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(Config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


from contextlib import contextmanager

@contextmanager
def get_db_connection():
    """Context manager for safe DB connections.

    Usage:
        with get_db_connection() as conn:
            conn.execute(...)
            conn.commit()
        # conn.close() called automatically, even on exceptions
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_read():
    """Context manager for read-only DB connections.

    Functionally identical to get_db_connection(), but semantically marks
    the operation as read-only for clarity.

    Usage:
        with get_db_read() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize all database tables."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_name_jp TEXT,
            position TEXT,
            job_url TEXT,
            source TEXT DEFAULT 'manual',
            source_id TEXT,
            deadline DATE,
            status TEXT DEFAULT 'interested',
            notes TEXT,
            salary TEXT,
            location TEXT,
            job_type TEXT,
            industry TEXT,
            job_description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_id)
        );
    ''')

    # Migration: add columns that may not exist yet
    for col, col_type, default in [
        ('job_description', 'TEXT', None),
        ('industry', 'TEXT', None),
        ('ai_enriched', 'INTEGER', '0'),
        ('tags', 'TEXT', None),
        ('ai_summary', 'TEXT', None),
        ('match_score', 'INTEGER', None),
        ('openwork_data', 'TEXT', None),
    ]:
        try:
            ddl = f"ALTER TABLE jobs ADD COLUMN {col} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            cursor.execute(ddl)
        except sqlite3.OperationalError:
            pass  # Column already exists

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            interview_type TEXT,
            scheduled_at TIMESTAMP,
            location TEXT,
            online_url TEXT,
            notes TEXT,
            status TEXT DEFAULT 'scheduled',
            reminder_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS email_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gmail_id TEXT UNIQUE,
            subject TEXT,
            sender TEXT,
            body_preview TEXT,
            received_at TIMESTAMP,
            is_job_related INTEGER DEFAULT 0,
            is_interview_invite INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS scrape_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            jobs_found INTEGER DEFAULT 0,
            jobs_updated INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL UNIQUE,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- AI Chat history
        CREATE TABLE IF NOT EXISTS ai_chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ES Documents
        CREATE TABLE IF NOT EXISTS es_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            file_path TEXT,
            file_type TEXT,
            raw_text TEXT,
            parsed_data TEXT,
            is_template INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Applications tracking
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            es_id INTEGER,
            ai_generated_es TEXT,
            status TEXT DEFAULT 'pending'
                CHECK(status IN ('pending', 'generating', 'ready', 'submitted', 'failed')),
            submitted_at TIMESTAMP,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY (es_id) REFERENCES es_documents(id) ON DELETE SET NULL
        );

        -- OpenWork cache
        CREATE TABLE IF NOT EXISTS openwork_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL UNIQUE,
            overall_score REAL,
            sub_scores TEXT,
            review_summary TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- MyPage credentials (persistent login storage per company)
        CREATE TABLE IF NOT EXISTS mypage_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL UNIQUE,
            login_url TEXT,
            username TEXT,
            initial_password TEXT,
            current_password TEXT,
            source_email_id TEXT,
            status TEXT DEFAULT 'received'
                CHECK(status IN ('received', 'logging_in', 'password_changed',
                    'profile_filled', 'es_filling', 'draft_saved',
                    'ready_for_review', 'manual_intervention_needed',
                    'submitted', 'failed')),
            error_message TEXT,
            last_screenshot TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );

        -- User profile (personal info extracted from ES)
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- User settings (key-value store for unified password, etc.)
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''');

    conn.commit()
    conn.close()

    # Phase 7: LLM settings tables (uses own connection to avoid lock)
    from db.llm_settings import init_llm_tables
    init_llm_tables()

    # Task queue table
    from db.task_queue import init_task_queue_table
    init_task_queue_table()

    # Activity log table
    from db.activity_log import init_activity_log_table
    init_activity_log_table()

