"""Gmail fetch mode registry — extensible strategy pattern.

Each FetchMode defines how to build a Gmail search query, what limit
to apply, and what to do after fetching. New modes are added by
subclassing FetchMode and calling registry.register().

Built-in modes:
  - backfill:        First-run, fetch all emails from past N days
  - incremental:     Daily check, only emails after last_fetched_at
  - keyword_search:  Manual search by keyword with configurable limit
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FetchMode(ABC):
    """Base class for Gmail fetch modes."""

    name: str = ''
    description: str = ''
    # Default config keys and values for this mode
    default_config: dict = {}

    @abstractmethod
    def build_query(self, params: dict) -> str:
        """Build a Gmail search query string.

        Args:
            params: Mode-specific parameters from the API request.

        Returns:
            Gmail search query (e.g. 'after:2026/02/01', 'is:unread', etc.)
        """

    def get_limit(self, params: dict) -> int:
        """Return max emails to fetch. 0 = unlimited.

        Args:
            params: Mode-specific parameters from the API request.
        """
        return 0

    def after_fetch(self, emails: list, params: dict):
        """Hook called after emails are fetched successfully.

        Use to update state (e.g. last_fetched_at timestamp).

        Args:
            emails: List of fetched email dicts.
            params: Mode-specific parameters.
        """
        pass

    def to_dict(self) -> dict:
        """Serialize mode info for API response."""
        return {
            'name': self.name,
            'description': self.description,
            'default_config': self.default_config,
        }


class GmailModeRegistry:
    """Registry of all available Gmail fetch modes."""

    def __init__(self):
        self._modes: dict[str, FetchMode] = {}

    def register(self, mode: FetchMode):
        """Register a fetch mode."""
        self._modes[mode.name] = mode
        logger.debug(f"[gmail_modes] Registered mode: {mode.name}")

    def get(self, name: str) -> FetchMode:
        """Get a mode by name. Raises KeyError if not found."""
        if name not in self._modes:
            available = ', '.join(self._modes.keys())
            raise KeyError(
                f"Unknown Gmail fetch mode: '{name}'. "
                f"Available: {available}"
            )
        return self._modes[name]

    def list_modes(self) -> list[dict]:
        """List all registered modes for API response."""
        return [m.to_dict() for m in self._modes.values()]


# ── Global registry ──────────────────────────────────────────────────
registry = GmailModeRegistry()


# ── Built-in modes ───────────────────────────────────────────────────

class BackfillMode(FetchMode):
    """First-run mode: fetch all emails from past N days."""

    name = 'backfill'
    description = '初回全量取得 — 過去N日間の全メールを取得（上限なし）'
    default_config = {'days': 30}

    def build_query(self, params: dict) -> str:
        from db.gmail_settings import get_gmail_config
        config = get_gmail_config()
        days = int(params.get('days', 0)) or int(config.get('gmail_backfill_days', 30))
        after = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
        return f'after:{after}'

    def after_fetch(self, emails: list, params: dict):
        self._update_last_fetched(emails)

    @staticmethod
    def _update_last_fetched(emails: list):
        """Record the newest email timestamp."""
        if not emails:
            return
        # Find the most recent received_at
        timestamps = []
        for e in emails:
            ts = e.get('received_at', '')
            if ts:
                timestamps.append(ts)
        if timestamps:
            timestamps.sort(reverse=True)
            from db.gmail_settings import set_last_fetched_at
            set_last_fetched_at(timestamps[0])


class IncrementalMode(FetchMode):
    """Daily incremental: only emails newer than last fetch."""

    name = 'incremental'
    description = '日常増分チェック — 前回取得以降の新着メールのみ（上限なし）'
    default_config = {}

    def build_query(self, params: dict) -> str:
        from db.gmail_settings import get_last_fetched_at
        last = get_last_fetched_at()
        if last:
            # Parse ISO timestamp to date for Gmail query
            try:
                dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
                return f'after:{dt.strftime("%Y/%m/%d")}'
            except (ValueError, TypeError):
                pass
        # Fallback: last 3 days if no timestamp recorded
        after = (datetime.now() - timedelta(days=3)).strftime('%Y/%m/%d')
        return f'after:{after}'

    def after_fetch(self, emails: list, params: dict):
        BackfillMode._update_last_fetched(emails)


class KeywordSearchMode(FetchMode):
    """Manual keyword search with configurable limit."""

    name = 'keyword_search'
    description = 'キーワード検索 — 指定キーワードに一致するメールを取得'
    default_config = {'limit': 10}

    def build_query(self, params: dict) -> str:
        keyword = params.get('keyword', '')
        if not keyword:
            raise ValueError("keyword_search mode requires 'keyword' parameter")
        return keyword

    def get_limit(self, params: dict) -> int:
        limit = params.get('limit')
        if limit is not None:
            return int(limit)
        # Read default from settings
        from db.gmail_settings import get_gmail_config
        config = get_gmail_config()
        return int(config.get('gmail_keyword_limit', 10))


# ── Register built-in modes ─────────────────────────────────────────
registry.register(BackfillMode())
registry.register(IncrementalMode())
registry.register(KeywordSearchMode())
