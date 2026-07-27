"""MyPage API endpoints — credential management, bot triggers, screenshots."""
import os
import logging
from flask import Blueprint, request, jsonify, send_file

from db.mypages import (
    get_all_mypage_credentials, get_mypage_credential,
    save_mypage_credential, delete_mypage_credential,
    save_mypage_screenshot, update_mypage_status,
)
from db.user_profile import get_mypage_password, save_mypage_password
from domain.statuses import MyPageStatus

logger = logging.getLogger(__name__)

mypage_bp = Blueprint('mypage', __name__)


# ── List / Detail ──────────────────────────────────────────────────

@mypage_bp.route('/api/mypage/list')
def api_mypage_list():
    """Get all MyPage credentials (with company info via JOIN)."""
    creds = get_all_mypage_credentials()
    return jsonify(creds)


@mypage_bp.route('/api/mypage/<int:job_id>')
def api_mypage_detail(job_id):
    """Get MyPage credential for a specific job."""
    cred = get_mypage_credential(job_id)
    if not cred:
        return jsonify({'error': 'not found'}), 404
    return jsonify(cred)


# ── Save / Delete ──────────────────────────────────────────────────

@mypage_bp.route('/api/mypage/save', methods=['POST'])
def api_mypage_save():
    """Save or update a MyPage credential."""
    data = request.get_json(force=True)
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'error': 'job_id required'}), 400

    cred_id = save_mypage_credential(
        job_id=int(job_id),
        login_url=data.get('login_url', ''),
        username=data.get('username', ''),
        password=data.get('password', ''),
        source_email_id=data.get('source_email_id'),
    )
    return jsonify({'id': cred_id, 'status': 'saved'})


@mypage_bp.route('/api/mypage/<int:job_id>', methods=['DELETE'])
def api_mypage_delete(job_id):
    """Delete a MyPage credential."""
    delete_mypage_credential(job_id)
    return jsonify({'status': 'deleted'})


# ── Unified Password ──────────────────────────────────────────────

@mypage_bp.route('/api/mypage/password')
def api_mypage_get_password():
    """Get the unified MyPage password."""
    pw = get_mypage_password()
    return jsonify({'password': pw})


@mypage_bp.route('/api/mypage/password', methods=['POST'])
def api_mypage_set_password():
    """Save the unified MyPage password."""
    data = request.get_json(force=True)
    pw = data.get('password', '')
    if not pw:
        return jsonify({'error': 'password required'}), 400
    save_mypage_password(pw)
    return jsonify({'status': 'saved'})


# ── Bot Trigger ────────────────────────────────────────────────────

@mypage_bp.route('/api/mypage/<int:job_id>/login', methods=['POST'])
def api_mypage_login(job_id):
    """Trigger MyPage login bot via task queue."""
    cred = get_mypage_credential(job_id)
    if not cred:
        return jsonify({'error': 'no credential found'}), 404

    from db.task_queue import enqueue
    task_id = enqueue(
        task_type='mypage_login',
        params={'job_id': job_id},
        priority=5,
    )
    update_mypage_status(job_id, MyPageStatus.LOGGING_IN)
    return jsonify({'task_id': task_id, 'status': 'queued'})


@mypage_bp.route('/api/mypage/<int:job_id>/fill-profile', methods=['POST'])
def api_mypage_fill_profile(job_id):
    """Trigger MyPage profile fill bot via task queue."""
    cred = get_mypage_credential(job_id)
    if not cred:
        return jsonify({'error': 'no credential found'}), 404

    from db.task_queue import enqueue
    task_id = enqueue(
        task_type='mypage_fill_profile',
        params={'job_id': job_id},
        priority=5,
    )
    update_mypage_status(job_id, MyPageStatus.FILLING_PROFILE)
    return jsonify({'task_id': task_id, 'status': 'queued'})


# ── Screenshot ─────────────────────────────────────────────────────

@mypage_bp.route('/api/mypage/<int:job_id>/screenshot')
def api_mypage_screenshot(job_id):
    """Serve the latest screenshot for a MyPage."""
    cred = get_mypage_credential(job_id)
    if not cred or not cred.get('last_screenshot'):
        return jsonify({'error': 'no screenshot'}), 404

    path = cred['last_screenshot']
    if not os.path.isfile(path):
        return jsonify({'error': 'file not found'}), 404

    return send_file(path, mimetype='image/png')


# ── ES Generation ─────────────────────────────────────────────────

@mypage_bp.route('/api/mypage/generate-es', methods=['POST'])
def api_mypage_generate_es():
    """Generate a character-limited ES answer and return it immediately.

    The MyPage UI expects the generated text in this HTTP response, so this is
    deliberately synchronous instead of placing an unobservable queue task.
    """
    data = request.get_json(force=True)
    job_id = data.get('job_id')
    question = str(data.get('question', '')).strip()
    try:
        max_chars = int(data.get('max_chars', 400))
    except (TypeError, ValueError):
        return jsonify({'error': 'max_chars must be an integer'}), 400

    if not job_id or not question:
        return jsonify({'error': 'job_id and question are required'}), 400
    if not 50 <= max_chars <= 2000:
        return jsonify({'error': 'max_chars must be between 50 and 2000'}), 400

    from db.jobs import get_job
    from db.es import get_all_es_documents
    from db.openwork import get_openwork_data
    from services.strict_es_generator import generate_strict_es

    job = get_job(int(job_id))
    if not job:
        return jsonify({'error': 'job not found'}), 404

    base_es = {}
    docs = get_all_es_documents(templates_only=True) or get_all_es_documents()
    if docs:
        import json
        try:
            base_es = json.loads(docs[0].get('parsed_data') or '{}')
        except (TypeError, ValueError):
            base_es = {'self_pr': docs[0].get('raw_text', '')}

    openwork_data = None
    try:
        openwork_data = get_openwork_data(job.get('company_name', ''))
        if openwork_data:
            openwork_data = dict(openwork_data)
    except Exception:
        logger.debug("OpenWork data unavailable for job_id=%s", job_id)

    result = generate_strict_es(
        question=question,
        max_chars=max_chars,
        company_name=job.get('company_name', ''),
        base_es=base_es,
        openwork_data=openwork_data,
    )
    if not result.get('text'):
        return jsonify({'error': 'ES generation failed', **result}), 503
    return jsonify(result)
