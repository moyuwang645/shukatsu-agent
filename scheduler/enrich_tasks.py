"""AI enrichment and application queue tasks."""
import logging

logger = logging.getLogger(__name__)


def run_enrichment():
    """Enqueue AI enrichment task."""
    try:
        from db.task_queue import enqueue
        enqueue('enrich', priority=6)
        logger.info("[scheduler] Enqueued enrichment task")
    except Exception as e:
        logger.exception(f"[scheduler] Enrichment enqueue error: {e}")


def run_application_queue():
    """Enqueue application queue processing task."""
    try:
        from db.task_queue import enqueue
        enqueue('application_queue', priority=6)
        logger.info("[scheduler] Enqueued application_queue task")
    except Exception as e:
        logger.exception(f"[scheduler] Application queue enqueue error: {e}")
        # Fallback: run directly
        try:
            from services.application_service import process_application_queue
            process_application_queue()
        except Exception:
            pass
