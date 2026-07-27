"""Canonical workflow states shared by routes, services, and DB access."""

from enum import Enum


class _StringEnum(str, Enum):
    """Python 3.10-compatible equivalent of enum.StrEnum."""

    def __str__(self) -> str:
        return self.value


class ApplicationStatus(_StringEnum):
    PENDING = 'pending'
    GENERATING = 'generating'
    PROCESSING = 'processing'
    READY = 'ready'
    DRY_RUN_DONE = 'dry_run_done'
    SUBMITTED = 'submitted'
    FAILED = 'failed'


class MyPageStatus(_StringEnum):
    RECEIVED = 'received'
    LOGGING_IN = 'logging_in'
    PASSWORD_CHANGED = 'password_changed'
    FILLING_PROFILE = 'filling_profile'
    PROFILE_FILLED = 'profile_filled'
    ES_FILLING = 'es_filling'
    DRAFT_SAVED = 'draft_saved'
    READY_FOR_REVIEW = 'ready_for_review'
    MANUAL_INTERVENTION_NEEDED = 'manual_intervention_needed'
    SUBMITTED = 'submitted'
    FAILED = 'failed'


APPLICATION_STATUS_VALUES = frozenset(item.value for item in ApplicationStatus)
MYPAGE_STATUS_VALUES = frozenset(item.value for item in MyPageStatus)
