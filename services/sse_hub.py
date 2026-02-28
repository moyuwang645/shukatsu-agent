"""Server-Sent Events (SSE) hub for real-time job updates.

Allows the frontend to receive live notifications when new jobs
are created or updated by scrapers, email processing, etc.

Usage:
    # Publishing (from any module):
    from services.sse_hub import publish_job_event
    publish_job_event('created', job_dict)

    # Subscribing (via API → browser EventSource):
    GET /api/jobs/stream
"""
import json
import logging
import queue
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# Thread-safe list of subscriber queues
_subscribers: list[queue.Queue] = []
_lock = threading.Lock()


def subscribe() -> queue.Queue:
    """Register a new subscriber. Returns a Queue that receives events."""
    q = queue.Queue(maxsize=50)
    with _lock:
        _subscribers.append(q)
    logger.debug(f"[sse] New subscriber (total={len(_subscribers)})")
    return q


def unsubscribe(q: queue.Queue):
    """Remove a subscriber."""
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass
    logger.debug(f"[sse] Subscriber removed (total={len(_subscribers)})")


def publish_job_event(event_type: str, job: dict):
    """Publish a job event to all subscribers.

    event_type: 'created', 'updated', 'deleted', 'all_deleted'
    job: the job dict (or {} for bulk events)
    """
    data = {
        'event': event_type,
        'job': job,
        'timestamp': datetime.now().isoformat(),
    }
    payload = json.dumps(data, ensure_ascii=False, default=str)

    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        # Remove dead subscribers
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    if _subscribers:
        logger.debug(f"[sse] Published '{event_type}' to {len(_subscribers)} subscribers")
