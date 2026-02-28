"""API routes for task queue management and scheduler status.

Provides endpoints to view scheduled jobs, manage the task queue,
and manually trigger tasks.
"""
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

scheduler_bp = Blueprint('scheduler', __name__)


# ── Scheduler status ────────────────────────────────────────────────

@scheduler_bp.route('/api/scheduler/status', methods=['GET'])
def api_scheduler_status():
    """Get overall scheduler and worker status."""
    from scheduler import scheduler
    from services.task_worker import task_worker
    from db.task_queue import get_queue_stats

    return jsonify({
        'scheduler': {
            'running': scheduler.running,
            'job_count': len(scheduler.get_jobs()),
        },
        'worker': task_worker.get_status(),
        'queue': get_queue_stats(),
    })


# ── APScheduler jobs ────────────────────────────────────────────────

@scheduler_bp.route('/api/scheduler/jobs', methods=['GET'])
def api_scheduler_jobs():
    """List all registered APScheduler jobs with next run times."""
    from scheduler import scheduler

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            'id': job.id,
            'name': job.name or job.id,
            'next_run': next_run.isoformat() if next_run else None,
            'trigger': str(job.trigger),
        })

    return jsonify({'jobs': jobs})


# ── Task queue ──────────────────────────────────────────────────────

@scheduler_bp.route('/api/scheduler/queue', methods=['GET'])
def api_get_queue():
    """Get pending and running tasks from the queue."""
    from db.task_queue import get_queue

    status = request.args.get('status')  # optional filter
    limit = request.args.get('limit', 50, type=int)
    tasks = get_queue(status=status, limit=limit)
    return jsonify({'tasks': tasks, 'count': len(tasks)})


@scheduler_bp.route('/api/scheduler/history', methods=['GET'])
def api_get_history():
    """Get recently completed/failed tasks."""
    from db.task_queue import get_history

    limit = request.args.get('limit', 30, type=int)
    tasks = get_history(limit=limit)
    return jsonify({'tasks': tasks, 'count': len(tasks)})


@scheduler_bp.route('/api/scheduler/queue/<int:task_id>', methods=['GET'])
def api_get_task(task_id):
    """Get a specific task by ID."""
    from db.task_queue import get_task

    task = get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)


@scheduler_bp.route('/api/scheduler/queue/<int:task_id>/cancel', methods=['POST'])
def api_cancel_task(task_id):
    """Cancel a pending task."""
    from db.task_queue import cancel

    if cancel(task_id):
        return jsonify({'message': f'Task {task_id} cancelled'})
    return jsonify({'error': 'Task not found or not pending'}), 400


# ── Manual trigger ──────────────────────────────────────────────────

# Valid task types that can be manually triggered
VALID_TASK_TYPES = {
    'scrape_mynavi', 'scrape_gaishishukatsu', 'scrape_career_tasu',
    'scrape_onecareer', 'scrape_engineer_shukatu',
    'scrape_all',
    'enrich', 'email_check', 'keyword_search',
    'check_deadlines', 'check_interviews',
    'application_queue', 'cleanup_old_tasks',
}

# Priority 1 for manual triggers (highest)
MANUAL_PRIORITY = 1


@scheduler_bp.route('/api/scheduler/trigger/<task_type>', methods=['POST'])
def api_trigger_task(task_type):
    """Manually trigger a task with highest priority."""
    from db.task_queue import enqueue

    if task_type not in VALID_TASK_TYPES:
        return jsonify({
            'error': f'Invalid task_type: {task_type}',
            'valid_types': sorted(VALID_TASK_TYPES),
        }), 400

    # Special: scrape_all enqueues all 5 scrapers
    if task_type == 'scrape_all':
        ids = []
        for site in ('mynavi', 'gaishishukatsu', 'career_tasu',
                      'onecareer', 'engineer_shukatu'):
            tid = enqueue(f'scrape_{site}', priority=MANUAL_PRIORITY)
            ids.append(tid)
        logger.info(f"[scheduler_api] Manual trigger: scrape_all → {ids}")
        return jsonify({
            'message': f'Enqueued {len(ids)} scrape tasks',
            'task_ids': ids,
        }), 201

    body = request.get_json(silent=True) or {}
    params = body.get('params', {})
    task_id = enqueue(task_type, priority=MANUAL_PRIORITY, params=params)

    logger.info(f"[scheduler_api] Manual trigger: {task_type} → id={task_id}")
    return jsonify({
        'message': f'Task enqueued: {task_type}',
        'task_id': task_id,
    }), 201


# ── Activity log ────────────────────────────────────────────────────

@scheduler_bp.route('/api/scheduler/logs', methods=['GET'])
def api_get_logs():
    """Get structured activity log entries."""
    from db.activity_log import get_activity_log

    category = request.args.get('category')
    level = request.args.get('level')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    logs = get_activity_log(category=category, level=level,
                            limit=limit, offset=offset)
    return jsonify({'logs': logs, 'count': len(logs)})


@scheduler_bp.route('/api/scheduler/logs/stats', methods=['GET'])
def api_get_log_stats():
    """Get today's activity log statistics."""
    from db.activity_log import get_activity_stats
    return jsonify(get_activity_stats())


# ── Worker control ──────────────────────────────────────────────────

@scheduler_bp.route('/api/scheduler/worker/start', methods=['POST'])
def api_start_worker():
    """Start the task worker thread."""
    from services.task_worker import task_worker
    task_worker.start()
    return jsonify({'message': 'Worker started', 'status': task_worker.get_status()})


@scheduler_bp.route('/api/scheduler/worker/stop', methods=['POST'])
def api_stop_worker():
    """Stop the task worker thread."""
    from services.task_worker import task_worker
    task_worker.stop()
    return jsonify({'message': 'Worker stop signal sent'})


@scheduler_bp.route('/api/scheduler/worker/settings', methods=['GET', 'POST'])
def api_worker_settings():
    """Get or update TaskWorker concurrency settings."""
    from services.task_worker import SETTINGS_KEY, DEFAULT_MAX_WORKERS
    from db import get_db

    if request.method == 'GET':
        conn = get_db()
        row = conn.execute(
            "SELECT value FROM user_settings WHERE key = ?",
            (SETTINGS_KEY,)
        ).fetchone()
        conn.close()
        current = int(row[0]) if row and row[0] else DEFAULT_MAX_WORKERS
        return jsonify({
            'max_workers': current,
            'default': DEFAULT_MAX_WORKERS,
            'min': 1,
            'max': 10,
            'description': '同時実行タスク数（推奨: 3。LLMのAPIキー数に応じて調整）',
            'note': '変更後、ワーカーを再起動すると反映されます',
        })

    # POST: update setting
    body = request.get_json(silent=True) or {}
    val = body.get('max_workers')
    if val is None:
        return jsonify({'error': 'max_workers required'}), 400
    val = max(1, min(int(val), 10))

    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM user_settings WHERE key = ?",
        (SETTINGS_KEY,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE user_settings SET value = ? WHERE key = ?",
            (str(val), SETTINGS_KEY)
        )
    else:
        conn.execute(
            "INSERT INTO user_settings (key, value) VALUES (?, ?)",
            (SETTINGS_KEY, str(val))
        )
    conn.commit()
    conn.close()

    logger.info(f"[scheduler_api] TaskWorker max_workers updated to {val}")
    return jsonify({
        'message': f'max_workers updated to {val}',
        'max_workers': val,
        'note': '変更後、ワーカーを再起動すると反映されます',
    })

