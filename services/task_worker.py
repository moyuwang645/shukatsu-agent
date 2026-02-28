"""TaskWorker — background thread pool that processes the centralized task queue.

Pulls tasks by priority from db.task_queue, dispatches to the appropriate
handler using a configurable thread pool for concurrent execution.
LLMDispatcher handles API rate limiting; DBWriter serializes DB writes.

The number of concurrent workers is configurable via the 'task_worker_max_concurrent'
key in the user_settings table (default: 3, recommended: 1-5).

Usage:
    from services.task_worker import task_worker
    task_worker.start()   # called once from scheduler.py or app.py
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 3  # 推奨値: 3 (1-5の範囲で調整可能)
SETTINGS_KEY = 'task_worker_max_concurrent'


class TaskWorker:
    """Background worker that processes the task queue with concurrent execution."""

    # How long to sleep when the queue is empty
    IDLE_SLEEP = 5.0
    # Max consecutive errors before pausing
    MAX_CONSECUTIVE_ERRORS = 5
    PAUSE_AFTER_ERRORS = 60.0  # seconds to pause after too many errors

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._dispatch: dict[str, callable] = {}
        self._running = False
        self._consecutive_errors = 0
        self._tasks_processed = 0
        self._last_task_at: str | None = None
        self._active_count = 0          # currently executing tasks
        self._active_lock = threading.Lock()
        self._register_handlers()

    def _register_handlers(self):
        """Register all known task type handlers.

        Each handler is a callable(params: dict) -> dict that does the work
        and returns a result dict.
        """
        self._dispatch = {
            # Scraping (all go through unified dispatcher)
            'scrape_mynavi':           self._run_scraper,
            'scrape_gaishishukatsu':   self._run_scraper,
            'scrape_career_tasu':      self._run_scraper,
            'scrape_onecareer':        self._run_scraper,
            'scrape_engineer_shukatu': self._run_scraper,
            # AI / enrichment
            'enrich':                  self._run_enrichment,
            'detail_enrich':           self._run_detail_enrich,
            # Email
            'email_check':             self._run_email_check,
            # Keyword search
            'keyword_search':          self._run_keyword_search,
            # Email backfill (one-shot search to enrich email jobs)
            'email_backfill':          self._run_email_backfill,
            # Application queue
            'application_queue':       self._run_application_queue,
            # Deadline checks
            'check_deadlines':         self._run_check_deadlines,
            'check_interviews':        self._run_check_interviews,
            # Queue maintenance
            'cleanup_old_tasks':       self._run_cleanup,
        }

    # ── Task handlers ───────────────────────────────────────────────

    def _run_scraper(self, params: dict) -> dict:
        """Run a specific site scraper via unified dispatch."""
        # Get site name from params or task_type
        site = params.get('scraper') or \
               params.get('_task_type', '').replace('scrape_', '')
        if not site:
            return {'error': 'No site specified'}

        from scrapers import dispatch
        result = dispatch(action='fetch', scrapers=[site])
        return result

    def _run_enrichment(self, params: dict) -> dict:
        from services.enrichment_service import enrich_pending_jobs
        return enrich_pending_jobs()

    def _run_detail_enrich(self, params: dict) -> dict:
        """Run AI detail enrichment for a single job."""
        from services.detail_enrich_service import enrich_job_detail
        job_id = params.get('job_id')
        if not job_id:
            return {'error': 'job_id required'}
        return enrich_job_detail(job_id)

    def _run_email_check(self, params: dict) -> dict:
        from scheduler import check_gmail
        check_gmail()
        return {'status': 'done'}

    def _run_keyword_search(self, params: dict) -> dict:
        from scheduler import run_keyword_search
        keyword = params.get('keyword')
        scrapers = params.get('scrapers')  # optional scraper filter
        if keyword:
            run_keyword_search(keywords_override=[keyword], scrapers=scrapers)
        else:
            run_keyword_search(scrapers=scrapers)
        return {'status': 'done'}

    def _run_email_backfill(self, params: dict) -> dict:
        """One-shot search to backfill an email-created job."""
        from services.email_backfill import run_email_backfill
        keyword = params.get('keyword', '')
        job_id = params.get('job_id')
        scrapers = params.get('scrapers')  # optional scraper filter
        if not keyword or not job_id:
            return {'error': 'keyword and job_id required'}
        run_email_backfill(keyword, job_id, scrapers=scrapers)
        return {'status': 'done'}

    def _run_application_queue(self, params: dict) -> dict:
        from services.application_service import process_application_queue
        return process_application_queue()

    def _run_check_deadlines(self, params: dict) -> dict:
        from scheduler import check_deadlines_today, check_upcoming_deadlines
        check_deadlines_today()
        check_upcoming_deadlines()
        return {'status': 'done'}

    def _run_check_interviews(self, params: dict) -> dict:
        from scheduler import check_interviews_today
        check_interviews_today()
        return {'status': 'done'}

    def _run_cleanup(self, params: dict) -> dict:
        from db.task_queue import cleanup_old_tasks
        deleted = cleanup_old_tasks(days=params.get('days', 7))
        return {'deleted': deleted}

    # ── Settings ─────────────────────────────────────────────────────

    def _get_max_workers(self) -> int:
        """Read max_workers from user_settings DB (default: 3)."""
        try:
            from db import get_db
            conn = get_db()
            row = conn.execute(
                "SELECT value FROM user_settings WHERE key = ?",
                (SETTINGS_KEY,)
            ).fetchone()
            conn.close()
            if row and row[0]:
                val = int(row[0])
                return max(1, min(val, 10))  # clamp to 1-10
        except Exception:
            pass
        return DEFAULT_MAX_WORKERS

    # ── Core worker loop (multi-threaded) ────────────────────────────

    def _execute_task(self, task, handler):
        """Execute a single task in a worker thread."""
        from db.task_queue import complete, fail

        task_type = task['task_type']
        task_id = task['id']
        params = task.get('params', {})
        if isinstance(params, str):
            import json
            params = json.loads(params) if params else {}
        params['_task_type'] = task_type

        with self._active_lock:
            self._active_count += 1

        logger.info(f"[worker] Executing: {task_type} (id={task_id})")
        start = time.time()

        try:
            result = handler(params)
            elapsed = time.time() - start
            if result is None:
                result = {}
            result['elapsed_seconds'] = round(elapsed, 1)
            complete(task_id, result)
            self._consecutive_errors = 0
            self._tasks_processed += 1
            self._last_task_at = datetime.now().isoformat()
            logger.info(
                f"[worker] Done: {task_type} (id={task_id}, "
                f"{elapsed:.1f}s)"
            )
            try:
                from db.activity_log import log_activity
                log_activity(
                    'task', f'{task_type} completed ({elapsed:.1f}s)',
                    level='info',
                    details={'task_id': task_id, 'elapsed': elapsed,
                             'result_keys': list(result.keys())}
                )
            except Exception:
                pass
        except Exception as e:
            elapsed = time.time() - start
            fail(task_id, str(e))
            self._consecutive_errors += 1
            logger.exception(
                f"[worker] Failed: {task_type} (id={task_id}, "
                f"{elapsed:.1f}s) — {e}"
            )
            try:
                from db.activity_log import log_activity
                log_activity(
                    'error', f'{task_type} failed: {e}',
                    level='error',
                    details={'task_id': task_id, 'elapsed': elapsed}
                )
            except Exception:
                pass
        finally:
            with self._active_lock:
                self._active_count -= 1

    def _worker_loop(self):
        """Main worker loop — dispatches tasks to thread pool."""
        max_workers = self._get_max_workers()
        logger.info(
            f"[worker] TaskWorker started (max_workers={max_workers}, "
            f"configurable via settings key '{SETTINGS_KEY}')"
        )
        self._running = True

        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix='TaskWorker'
        ) as pool:
            while not self._stop_event.is_set():
                try:
                    from db.task_queue import claim_next

                    # Wait if all workers busy
                    with self._active_lock:
                        active = self._active_count
                    if active >= max_workers:
                        self._stop_event.wait(1.0)
                        continue

                    task = claim_next()
                    if task is None:
                        self._stop_event.wait(self.IDLE_SLEEP)
                        continue

                    task_type = task['task_type']
                    handler = self._dispatch.get(task_type)
                    if not handler:
                        from db.task_queue import fail
                        fail(task['id'], f"Unknown task_type: {task_type}",
                             retry=False)
                        logger.warning(f"[worker] No handler for: {task_type}")
                        continue

                    # Submit to thread pool
                    pool.submit(self._execute_task, task, handler)

                    # Small delay to let DB commit before claiming next
                    time.sleep(0.5)

                    # Safety: pause after too many consecutive errors
                    if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        logger.error(
                            f"[worker] {self.MAX_CONSECUTIVE_ERRORS} consecutive "
                            f"errors, pausing for {self.PAUSE_AFTER_ERRORS}s"
                        )
                        try:
                            from database import create_notification
                            create_notification(
                                'worker_error',
                                '⚠️ TaskWorker 連続エラー',
                                f'{self._consecutive_errors}回連続で失敗。'
                                f'{int(self.PAUSE_AFTER_ERRORS)}秒間一時停止中。',
                                ''
                            )
                        except Exception:
                            pass
                        self._stop_event.wait(self.PAUSE_AFTER_ERRORS)
                        self._consecutive_errors = 0

                except Exception as e:
                    logger.exception(f"[worker] Unexpected error in loop: {e}")
                    self._stop_event.wait(10)

        self._running = False
        logger.info("[worker] TaskWorker stopped")

    # ── Public interface ────────────────────────────────────────────

    def start(self):
        """Start the worker thread (if not already running)."""
        if self._thread and self._thread.is_alive():
            logger.info("[worker] Already running")
            return

        # Recover stuck tasks from previous crash
        self._recover_stuck_tasks()

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name='TaskWorker',
            daemon=True
        )
        self._thread.start()
        logger.info("[worker] Started background thread")

    def _recover_stuck_tasks(self):
        """Reset 'running' tasks back to 'pending' on startup.

        These are leftover from a previous crash where the worker
        was killed mid-execution.
        """
        try:
            from db import get_db
            conn = get_db()
            stuck = conn.execute(
                "UPDATE task_queue SET status = 'pending', started_at = NULL "
                "WHERE status = 'running'"
            ).rowcount
            conn.commit()
            conn.close()
            if stuck:
                logger.warning(f"[worker] Recovered {stuck} stuck 'running' tasks → pending")
        except Exception as e:
            logger.warning(f"[worker] Stuck task recovery failed: {e}")

    def stop(self):
        """Signal the worker to stop."""
        self._stop_event.set()
        logger.info("[worker] Stop signal sent")

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict:
        """Get worker status for API."""
        return {
            'running': self.is_running(),
            'tasks_processed': self._tasks_processed,
            'consecutive_errors': self._consecutive_errors,
            'last_task_at': self._last_task_at,
            'max_workers': self._get_max_workers(),
            'active_workers': self._active_count,
            'registered_handlers': sorted(self._dispatch.keys()),
        }


# Global singleton
task_worker = TaskWorker()
