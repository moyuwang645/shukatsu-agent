"""API routes for application queue (hai-tou / mass-apply)."""
from flask import Blueprint, request, jsonify

applications_bp = Blueprint('applications', __name__)


@applications_bp.route('/api/applications/queue', methods=['POST'])
def create_queue():
    """Create application entries for multiple jobs.

    Expects JSON: { job_ids: [1,2,3], es_id: 5, dry_run: true }
    """
    data = request.get_json(force=True)
    job_ids = data.get('job_ids', [])
    es_id = data.get('es_id')
    dry_run = data.get('dry_run', True)

    if not job_ids or not es_id:
        return jsonify({'error': 'job_ids and es_id are required'}), 400

    from services.application_service import create_application_queue
    try:
        stats = create_application_queue(job_ids, es_id, dry_run=dry_run)
        return jsonify(stats)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@applications_bp.route('/api/applications/process', methods=['POST'])
def process_queue():
    """Manually trigger processing of pending applications."""
    max_per_run = request.get_json(force=True).get('max', 3) if request.is_json else 3
    from services.application_service import process_application_queue
    stats = process_application_queue(max_per_run=max_per_run)
    return jsonify(stats)


@applications_bp.route('/api/applications/status')
def queue_status():
    """Get application queue statistics."""
    from db.applications import get_application_stats, get_all_applications
    stats = get_application_stats()
    recent = get_all_applications()[:20]
    return jsonify({'stats': stats, 'recent': recent})


@applications_bp.route('/api/applications/enrich', methods=['POST'])
def run_enrichment():
    """Manually trigger AI enrichment of unenriched jobs."""
    max_jobs = request.get_json(force=True).get('max', 5) if request.is_json else 5
    from services.enrichment_service import enrich_pending_jobs
    stats = enrich_pending_jobs(max_jobs=max_jobs)
    return jsonify(stats)
