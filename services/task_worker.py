"""TaskWorker — background thread that processes the centralized task queue.

Pulls tasks by priority from db.task_queue, dispatches to the appropriate
handler, and records results. Respects rate limits between AI-heavy tasks.

Usage:
    from services.task_worker import task_worker
    task_worker.start()   # called once from scheduler.py or app.py
"""
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskWorker:
    """Background worker that processes the task queue."""

    # Rate limit (seconds) between tasks that involve AI/API calls
    AI_TASK_COOLDOWN = 3.0
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
        self._register_handlers()

    def _register_handlers(self):
        """Register all known task type handlers.

        Each handler is a callable(params: dict) -> dict that does the work
        and returns a result dict.
        """
        self._dispatch = {
            # Scraping
            'scrape_mynavi':           self._run_scraper,
            'scrape_gaishishukatsu':   self._run_scraper,
            'scrape_career_tasu':      self._run_scraper,
            'scrape_onecareer':        self._run_scraper,
            'scrape_engineer_shukatu': self._run_scraper,
            # AI / enrichment
            'enrich':                  self._run_enrichment,
            # Email
            'email_check':             self._run_email_check,
            # Keyword search
            'keyword_search':          self._run_keyword_search,
            # Application queue
            'application_queue':       self._run_application_queue,
            # Deadline checks
            'check_deadlines':         self._run_check_deadlines,
            'check_interviews':        self._run_check_interviews,
            # Queue maintenance
            'cleanup_old_tasks':       self._run_cleanup,
            # MyPage automation
            'mypage_login':            self._run_mypage_login,
            'mypage_fill_profile':     self._run_mypage_fill_profile,
        }

    # ── Task handlers ───────────────────────────────────────────────

    def _run_scraper(self, params: dict) -> dict:
        """Run a specific site scraper."""
        # Extract site name from task_type (e.g. 'scrape_mynavi' → 'mynavi')
        site = params.get('_task_type', '').replace('scrape_', '')
        if not site:
            return {'error': 'No site specified'}

        SCRAPER_MAP = {
            'mynavi':           ('scrapers.mynavi',           'run_mynavi_scraper'),
            'gaishishukatsu':   ('scrapers.gaishishukatsu',   'run_gaishishukatsu_scraper'),
            'career_tasu':      ('scrapers.career_tasu',      'run_career_tasu_scraper'),
            'onecareer':        ('scrapers.onecareer',        'run_onecareer_scraper'),
            'engineer_shukatu': ('scrapers.engineer_shukatu', 'run_engineer_shukatu_scraper'),
        }

        if site not in SCRAPER_MAP:
            return {'error': f'Unknown scraper: {site}'}

        import importlib
        mod_path, func_name = SCRAPER_MAP[site]
        mod = importlib.import_module(mod_path)
        run_fn = getattr(mod, func_name)
        result = run_fn()

        # Log scrape result
        try:
            from database import log_scrape, create_notification
            log_scrape(
                result['source'], result['status'],
                result['jobs_found'], result['jobs_updated'],
                result.get('error_message', '')
            )
            if result['status'] == 'success' and result['jobs_updated'] > 0:
                create_notification(
                    'scrape_complete',
                    f"🔄 {site} スクレイピング完了",
                    f"{result['jobs_found']}件検出、{result['jobs_updated']}件新規追加",
                    ''
                )
        except Exception as e:
            logger.warning(f"[worker] Scrape log/notification error: {e}")

        return result

    def _run_enrichment(self, params: dict) -> dict:
        from services.enrichment_service import enrich_pending_jobs
        return enrich_pending_jobs()

    def _run_email_check(self, params: dict) -> dict:
        from scheduler import check_gmail
        check_gmail()
        return {'status': 'done'}

    def _run_keyword_search(self, params: dict) -> dict:
        from scheduler import run_keyword_search
        keyword = params.get('keyword')
        if keyword:
            # Email-backfill: search only for this specific company name
            run_keyword_search(keywords_override=[keyword])
        else:
            # Scheduled: search all preference keywords
            run_keyword_search()
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

    def _run_mypage_login(self, params: dict) -> dict:
        from services.mypage_bot import run_mypage_login
        job_id = params.get('job_id')
        new_password = params.get('new_password')
        if not job_id:
            return {'error': 'No job_id specified'}
        return run_mypage_login(job_id, new_password=new_password)

    def _run_mypage_fill_profile(self, params: dict) -> dict:
        from services.mypage_bot import run_mypage_fill_profile
        job_id = params.get('job_id')
        if not job_id:
            return {'error': 'No job_id specified'}
        return run_mypage_fill_profile(job_id)

    # ── Core worker loop ────────────────────────────────────────────

    def _is_ai_task(self, task_type: str) -> bool:
        """Check if a task type involves AI/API calls and needs rate limiting."""
        return task_type in ('enrich', 'email_check', 'keyword_search') or \
               task_type.startswith('scrape_')

    def _worker_loop(self):
        """Main worker loop — runs in a background thread."""
        logger.info("[worker] TaskWorker started")
        self._running = True

        while not self._stop_event.is_set():
            try:
                from db.task_queue import claim_next, complete, fail

                task = claim_next()
                if task is None:
                    self._stop_event.wait(self.IDLE_SLEEP)
                    continue

                task_type = task['task_type']
                task_id = task['id']
                params = task.get('params', {})
                if isinstance(params, str):
                    import json
                    params = json.loads(params) if params else {}

                # Inject task_type into params for handlers
                params['_task_type'] = task_type

                handler = self._dispatch.get(task_type)
                if not handler:
                    fail(task_id, f"Unknown task_type: {task_type}", retry=False)
                    logger.warning(f"[worker] No handler for: {task_type}")
                    continue

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
                    # Structured activity log
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
                    # Structured activity log
                    try:
                        from db.activity_log import log_activity
                        log_activity(
                            'error', f'{task_type} failed: {e}',
                            level='error',
                            details={'task_id': task_id, 'elapsed': elapsed}
                        )
                    except Exception:
                        pass

                # Rate limiting for AI-heavy tasks
                if self._is_ai_task(task_type):
                    self._stop_event.wait(self.AI_TASK_COOLDOWN)

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
            from db import get_db_connection
            with get_db_connection() as conn:
                stuck = conn.execute(
                    "UPDATE task_queue SET status = 'pending', started_at = NULL "
                    "WHERE status = 'running'"
                ).rowcount
                conn.commit()
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
            'registered_handlers': sorted(self._dispatch.keys()),
        }


# Global singleton
task_worker = TaskWorker()
