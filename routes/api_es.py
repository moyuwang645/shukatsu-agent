"""API routes for ES (Entry Sheet) management."""
import os
import json
from flask import Blueprint, request, jsonify
from config import Config

es_bp = Blueprint('es', __name__)


@es_bp.route('/api/es/upload', methods=['POST'])
def upload_es():
    """Upload and parse an ES file (PDF, DOCX, or image)."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    # Save file
    upload_dir = Config.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    file.save(file_path)

    # Parse
    from services.es_parser import parse_es_file, save_es_to_db
    parsed = parse_es_file(file_path)
    title = request.form.get('title', file.filename)

    # If this is a resume, include photo_path in the document
    photo_path = ''
    if parsed.get('is_resume') and parsed.get('resume_data'):
        photo_path = parsed['resume_data'].get('photo_path', '')
        # Auto-save to user profile
        try:
            from db.user_profile import save_user_profile
            rd = parsed['resume_data']
            save_user_profile({
                'name': rd.get('name', ''),
                'name_kana': rd.get('name_kana', ''),
                'email': rd.get('email', ''),
                'phone': rd.get('phone', ''),
                'postcode': rd.get('postcode', ''),
                'address': rd.get('address', ''),
                'birthday': rd.get('birthday', ''),
                'photo_path': photo_path,
                'education': rd.get('education', []),
                'qualifications': rd.get('qualifications', ''),
            })
        except Exception:
            pass  # Non-critical

    doc_id = save_es_to_db(file_path, title, parsed, photo_path=photo_path)

    result = {
        'id': doc_id,
        'title': title,
        'self_pr': parsed.get('self_pr', '')[:200],
        'motivation': parsed.get('motivation', '')[:200],
        'strengths': parsed.get('strengths', []),
        'message': 'ES parsed and saved.',
        'is_resume': parsed.get('is_resume', False),
    }
    if parsed.get('resume_data'):
        rd = parsed['resume_data']
        result['resume'] = {
            'name': rd.get('name', ''),
            'email': rd.get('email', ''),
            'phone': rd.get('phone', ''),
            'has_photo': bool(photo_path),
        }
    return jsonify(result)


@es_bp.route('/api/es/<int:doc_id>/photo')
def get_es_photo(doc_id):
    """Serve the extracted resume photo."""
    from flask import send_file
    from db.es import get_es_document
    doc = get_es_document(doc_id)
    if not doc or not doc.get('photo_path'):
        return jsonify({'error': 'No photo'}), 404
    photo_path = doc['photo_path']
    if not os.path.exists(photo_path):
        return jsonify({'error': 'Photo file not found'}), 404
    return send_file(photo_path, mimetype='image/jpeg')


@es_bp.route('/api/es/list')
def list_es():
    """List all saved ES documents."""
    from db.es import get_all_es_documents
    docs = get_all_es_documents()
    return jsonify(docs)


@es_bp.route('/api/es/<int:doc_id>')
def get_es(doc_id):
    """Get a single ES document by ID."""
    from db.es import get_es_document
    doc = get_es_document(doc_id)
    if not doc:
        return jsonify({'error': 'Not found'}), 404
    result = dict(doc)
    # Unpack parsed_data JSON
    if result.get('parsed_data'):
        try:
            result['parsed'] = json.loads(result['parsed_data'])
        except (ValueError, TypeError):
            result['parsed'] = {}
    return jsonify(result)


@es_bp.route('/api/es/<int:doc_id>', methods=['DELETE'])
def delete_es(doc_id):
    """Delete an ES document."""
    from db.es import delete_es_document
    delete_es_document(doc_id)
    return jsonify({'ok': True})


@es_bp.route('/api/es/generate', methods=['POST'])
def generate_custom_es():
    """Generate company-customized ES for a specific job."""
    data = request.get_json(force=True)
    es_id = data.get('es_id')
    job_id = data.get('job_id')

    if not es_id or not job_id:
        return jsonify({'error': 'es_id and job_id are required'}), 400

    from db.es import get_es_document
    from db.jobs import get_job
    from db.openwork import get_openwork_data
    from ai.es_writer import generate_custom_es as gen_es

    es_doc = get_es_document(es_id)
    if not es_doc:
        return jsonify({'error': 'ES document not found'}), 404

    job = get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    # Parse base ES
    try:
        base_es = json.loads(es_doc.get('parsed_data', '{}'))
    except (ValueError, TypeError):
        base_es = {'self_pr': es_doc.get('raw_text', ''), 'motivation': '', 'strengths': []}

    # Get OpenWork data
    openwork_data = None
    try:
        ow = get_openwork_data(job.get('company_name', ''))
        if ow:
            openwork_data = dict(ow)
    except Exception:
        pass

    try:
        result = gen_es(base_es, dict(job), openwork_data)
    except Exception as e:
        return jsonify({'error': f'AI generation error: {e}'}), 503

    if result:
        return jsonify(result)
    else:
        return jsonify({'error': 'AI generation failed (rate limit or config issue)'}), 503

