"""Data models for the shukatsu-agent application.

Provides TypedDict definitions for type-safe access to database records.
These are NOT enforced at runtime — they serve as documentation and IDE
type hints for autocompletion, refactoring, and static analysis.

Usage:
    from db.models import JobRecord

    def process_job(job: JobRecord) -> None:
        print(job['company_name'])  # IDE autocomplete works here
"""
from typing import Literal, TypedDict


# ── Job statuses ─────────────────────────────────────────────────────

JobStatus = Literal[
    # PRE (選考前)
    'interested', 'seminar', 'seminar_fast', 'casual',
    # IN_PROGRESS (選考中)
    'applied', 'es_passed', 'spi', 'gd',
    'interview_1', 'interview_2', 'interview_final', '本選',
    # TERMINAL (終了)
    'offered', 'accepted', 'rejected', 'withdrawn',
]

JobSource = Literal[
    'email', 'mynavi', 'career_tasu', 'onecareer',
    'gaishishukatsu', 'engineer_shukatu', 'manual',
]


# ── Job record ───────────────────────────────────────────────────────

class JobRecord(TypedDict, total=False):
    """A job record from the `jobs` table.

    All fields are optional (total=False) because DB rows may have
    NULL values and new records start with sparse data.
    """
    # Identity (locked)
    id: int
    source: JobSource
    source_id: str
    created_at: str

    # Company (write_once)
    company_name: str
    company_name_jp: str
    job_url: str

    # Core fields (updatable)
    position: str
    salary: str
    location: str
    industry: str
    job_type: str
    job_description: str
    deadline: str
    company_business: str
    company_culture: str
    notes: str
    status: JobStatus

    # AI enrichment (ai_only)
    match_score: int
    ai_summary: str
    tags: str
    ai_enriched: int


# ── Interview record ─────────────────────────────────────────────────

class InterviewRecord(TypedDict, total=False):
    """An interview record from the `interviews` table."""
    id: int
    job_id: int
    interview_type: str
    scheduled_at: str
    location: str
    online_url: str
    status: str
    notes: str


# ── Task queue record ────────────────────────────────────────────────

TaskStatus_Queue = Literal['pending', 'running', 'done', 'failed']


class TaskRecord(TypedDict, total=False):
    """A task queue record."""
    id: int
    task_type: str
    priority: int
    status: TaskStatus_Queue
    params: str       # JSON string
    result: str       # JSON string
    error: str
    retry_count: int
    max_retries: int
    created_at: str
    started_at: str
    completed_at: str
