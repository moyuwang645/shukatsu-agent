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
    update_mypage_status(job_id, 'logging_in')
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
    update_mypage_status(job_id, 'filling_profile')
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
    """Generate company-specific ES answers using AI."""
    data = request.get_json(force=True)
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'error': 'job_id required'}), 400

    from db.task_queue import enqueue
    task_id = enqueue(
        task_type='generate_es',
        params={'job_id': int(job_id)},
        priority=5,
    )
    return jsonify({'task_id': task_id, 'status': 'queued'})
