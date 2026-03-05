"""Gmail fetch progress tracker — thread-safe progress state for frontend polling."""
import threading
from datetime import datetime

_lock = threading.Lock()
_progress = {
    'active': False,
    'mode': '',
    'stage': '',        # 'downloading', 'caching', 'filtering', 'processing', 'done'
    'current': 0,
    'total': 0,
    'message': '',
    'started_at': '',
    'updated_at': '',
}


def update_progress(stage: str, current: int = 0, total: int = 0,
                    message: str = '', mode: str = '', active: bool = True):
    """Update the global progress state (thread-safe)."""
    with _lock:
        _progress['active'] = active
        _progress['stage'] = stage
        _progress['current'] = current
        _progress['total'] = total
        _progress['message'] = message
        _progress['updated_at'] = datetime.now().isoformat()
        if mode:
            _progress['mode'] = mode
        if active and not _progress.get('started_at'):
            _progress['started_at'] = datetime.now().isoformat()
        if not active:
            _progress['started_at'] = ''


def get_progress() -> dict:
    """Get a snapshot of current progress (thread-safe)."""
    with _lock:
        return dict(_progress)


def finish_progress(message: str = '完了'):
    """Mark progress as complete."""
    update_progress(stage='done', message=message, active=False)
