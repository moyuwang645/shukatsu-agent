"""Backward-compatible shim — re-exports everything from the new db/ package.

All existing code that does ``from database import X`` continues to work
without any changes.  New code should import directly from ``db.*``.
"""
# Core
from db import get_db, init_db  # noqa: F401

# Jobs
from db.jobs import (  # noqa: F401
    create_job,
    update_job,
    delete_job,
    get_job,
    get_all_jobs,
    get_jobs_by_deadline,
    get_upcoming_deadlines,
    get_honsen_urgent_deadlines,
    upsert_job_from_scraper,
    get_job_stats,
    get_job_by_source_id,
)

# Interviews
from db.interviews import (  # noqa: F401
    create_interview,
    get_interviews_for_job,
    get_upcoming_interviews,
    get_all_interviews,
    update_interview,
    delete_interview,
)

# Notifications
from db.notifications import (  # noqa: F401
    create_notification,
    get_unread_notifications,
    get_all_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)

# Email cache
from db.emails import (  # noqa: F401
    cache_email,
    get_cached_emails,
    mark_email_processed,
    is_email_processed,
    get_email_count,
)

# User preferences & scrape logs
from db.preferences import (  # noqa: F401
    get_preferences,
    add_preference,
    delete_preference,
    toggle_preference,
    log_scrape,
    get_last_scrape,
)

# Task queue
from db.task_queue import (  # noqa: F401
    enqueue as enqueue_task,
    get_queue as get_task_queue,
    get_queue_stats as get_task_queue_stats,
)

# Gmail settings
from db.gmail_settings import (  # noqa: F401
    get_gmail_config,
    update_gmail_config,
    get_last_fetched_at as get_gmail_last_fetched_at,
    set_last_fetched_at as set_gmail_last_fetched_at,
)
