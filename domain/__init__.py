"""Shared domain types and invariants."""

from .statuses import (
    APPLICATION_STATUS_VALUES,
    MYPAGE_STATUS_VALUES,
    ApplicationStatus,
    MyPageStatus,
)

__all__ = [
    'ApplicationStatus',
    'MyPageStatus',
    'APPLICATION_STATUS_VALUES',
    'MYPAGE_STATUS_VALUES',
]
