"""API routes for Jobs and Interviews CRUD."""
import logging
from flask import Blueprint, request, jsonify
from database import (
    get_all_jobs, get_job, create_job, update_job, delete_job,
    get_interviews_for_job, create_interview, get_all_interviews,
    update_interview, delete_interview, get_job_stats,
)

logger = logging.getLogger(__name__)

jobs_bp = Blueprint('jobs', __name__)


# ========== Jobs ==========

@jobs_bp.route('/api/jobs', methods=['GET'])
def api_get_jobs():
    status = request.args.get('status')
    source = request.args.get('source')
    logger.debug(f"[jobs] GET /api/jobs status={status} source={source}")
    jobs = get_all_jobs(status=status, source=source)
    logger.info(f"[jobs] Returning {len(jobs)} jobs")
    return jsonify(jobs)


@jobs_bp.route('/api/jobs', methods=['POST'])
def api_create_job():
    data = request.get_json()
    if not data or not data.get('company_name'):
        logger.warning("[jobs] POST /api/jobs — missing company_name")
        return jsonify({'error': 'company_name is required'}), 400
    job_id = create_job(data)
    logger.info(f"[jobs] Created job id={job_id} company={data.get('company_name')}")
    return jsonify({'id': job_id, 'message': 'Job created'}), 201


@jobs_bp.route('/api/jobs/<int:job_id>', methods=['GET'])
def api_get_job(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    interviews = get_interviews_for_job(job_id)
    job['interviews'] = interviews
    return jsonify(job)


@jobs_bp.route('/api/jobs/<int:job_id>', methods=['PUT'])
def api_update_job(job_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    success = update_job(job_id, data, force=True)
    logger.info(f"[jobs] Updated job id={job_id} fields={list(data.keys())} success={success}")
    return jsonify({'message': 'Job updated' if success else 'No changes'})


@jobs_bp.route('/api/jobs/<int:job_id>', methods=['DELETE'])
def api_delete_job(job_id):
    logger.info(f"[jobs] Deleting job id={job_id}")
    delete_job(job_id)
    return jsonify({'message': 'Job deleted'})


# ========== Interviews ==========

@jobs_bp.route('/api/interviews', methods=['GET'])
def api_get_interviews():
    interviews = get_all_interviews()
    return jsonify(interviews)


@jobs_bp.route('/api/interviews', methods=['POST'])
def api_create_interview():
    data = request.get_json()
    if not data or not data.get('job_id'):
        logger.warning("[interviews] POST /api/interviews — missing job_id")
        return jsonify({'error': 'job_id is required'}), 400
    iid = create_interview(data)
    logger.info(f"[interviews] Created interview id={iid} for job_id={data.get('job_id')} type={data.get('interview_type')}")
    return jsonify({'id': iid, 'message': 'Interview created'}), 201


@jobs_bp.route('/api/interviews/<int:interview_id>', methods=['PUT'])
def api_update_interview(interview_id):
    data = request.get_json()
    update_interview(interview_id, data)
    return jsonify({'message': 'Interview updated'})


@jobs_bp.route('/api/interviews/<int:interview_id>', methods=['DELETE'])
def api_delete_interview(interview_id):
    delete_interview(interview_id)
    return jsonify({'message': 'Interview deleted'})


# ========== Stats ==========

@jobs_bp.route('/api/stats', methods=['GET'])
def api_stats():
    stats = get_job_stats()
    return jsonify(stats)


# ========== Bulk Operations ==========

@jobs_bp.route('/api/jobs/all', methods=['DELETE'])
def api_delete_all_jobs():
    """Delete ALL jobs (for testing). Requires ?confirm=yes."""
    if request.args.get('confirm') != 'yes':
        return jsonify({'error': 'Add ?confirm=yes to confirm'}), 400
    from db.jobs import delete_all_jobs
    deleted = delete_all_jobs()
    logger.warning(f"[jobs] 🗑️ Deleted ALL jobs: {deleted} records")
    return jsonify({'message': f'{deleted}件の求人を削除しました', 'deleted': deleted})


# ========== SSE (Server-Sent Events) ==========

@jobs_bp.route('/api/jobs/stream')
def api_jobs_stream():
    """SSE endpoint for real-time job updates.

    The frontend connects via EventSource and receives events like:
    - created: new job added
    - updated: job modified
    - all_deleted: all jobs deleted
    """
    from services.sse_hub import subscribe, unsubscribe
    from flask import Response
    import queue as queue_mod

    def event_stream():
        q = subscribe()
        try:
            yield f"data: {json.dumps({'event': 'connected'})}\n\n"
            while True:
                try:
                    payload = q.get(timeout=30)
                    yield f"data: {payload}\n\n"
                except queue_mod.Empty:
                    # Keep-alive ping
                    yield ": keepalive\n\n"
        except GeneratorExit:
            unsubscribe(q)

    import json
    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
