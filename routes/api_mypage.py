"""API routes for MyPage credential management and auto-apply pipeline."""
import json
from flask import Blueprint, request, jsonify

mypage_bp = Blueprint('mypage', __name__)


@mypage_bp.route('/api/mypage/list')
def list_mypages():
    """List all saved MyPage credentials with company info."""
    from db.mypages import get_all_mypage_credentials
    creds = get_all_mypage_credentials()
    # Mask passwords for API response (show only last 2 chars)
    for c in creds:
        if c.get('current_password'):
            pw = c['current_password']
            c['password_masked'] = '*' * (len(pw) - 2) + pw[-2:] if len(pw) > 2 else pw
        if c.get('initial_password'):
            pw = c['initial_password']
            c['initial_password_masked'] = '*' * (len(pw) - 2) + pw[-2:] if len(pw) > 2 else pw
    return jsonify(creds)


@mypage_bp.route('/api/mypage/<int:job_id>')
def get_mypage(job_id):
    """Get MyPage credentials for a specific job (full password visible)."""
    from db.mypages import get_mypage_credential
    cred = get_mypage_credential(job_id)
    if not cred:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(cred)


@mypage_bp.route('/api/mypage/save', methods=['POST'])
def save_mypage():
    """Manually save or update MyPage credentials."""
    data = request.get_json(force=True)
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({'error': 'job_id is required'}), 400

    from db.mypages import save_mypage_credential
    cred_id = save_mypage_credential(
        job_id=job_id,
        login_url=data.get('login_url', ''),
        username=data.get('username', ''),
        password=data.get('password', ''),
    )
    return jsonify({'id': cred_id, 'ok': True})


@mypage_bp.route('/api/mypage/<int:job_id>', methods=['DELETE'])
def delete_mypage(job_id):
    """Delete MyPage credential."""
    from db.mypages import delete_mypage_credential
    delete_mypage_credential(job_id)
    return jsonify({'ok': True})


# ── Profile Management ──

@mypage_bp.route('/api/profile')
def get_profile():
    """Get user profile data."""
    from db.user_profile import get_user_profile
    profile = get_user_profile()
    if not profile:
        return jsonify({'parsed': {}})
    return jsonify(profile)


@mypage_bp.route('/api/profile', methods=['POST'])
def save_profile():
    """Save or update user profile data."""
    data = request.get_json(force=True)
    from db.user_profile import save_user_profile
    pid = save_user_profile(data)
    return jsonify({'id': pid, 'ok': True})


@mypage_bp.route('/api/profile/extract', methods=['POST'])
def extract_profile():
    """Extract profile from the latest ES document."""
    es_id = request.get_json(force=True).get('es_id')
    if not es_id:
        return jsonify({'error': 'es_id is required'}), 400

    from db.es import get_es_document
    es_doc = get_es_document(es_id)
    if not es_doc:
        return jsonify({'error': 'ES document not found'}), 404

    from services.profile_extractor import extract_and_save_profile
    raw_text = es_doc.get('raw_text', '')
    profile = extract_and_save_profile(raw_text)
    if profile:
        return jsonify({'profile': profile, 'message': 'Profile extracted and saved'})
    else:
        return jsonify({'error': 'Failed to extract profile'}), 503


# ── Unified Password ──

@mypage_bp.route('/api/mypage/password')
def get_unified_password():
    """Get the unified MyPage password."""
    from db.user_profile import get_mypage_password
    return jsonify({'password': get_mypage_password()})


@mypage_bp.route('/api/mypage/password', methods=['POST'])
def set_unified_password():
    """Set the unified MyPage password."""
    data = request.get_json(force=True)
    password = data.get('password', '')
    if not password:
        return jsonify({'error': 'password is required'}), 400
    from db.user_profile import save_mypage_password
    save_mypage_password(password)
    return jsonify({'ok': True})


# ── Strict ES Generation ──

@mypage_bp.route('/api/mypage/generate-es', methods=['POST'])
def generate_strict_es_api():
    """Generate ES text with strict character count enforcement.

    Request body: {question, max_chars, job_id, es_id}
    """
    data = request.get_json(force=True)
    question = data.get('question', '')
    max_chars = data.get('max_chars', 400)

    if not question:
        return jsonify({'error': 'question is required'}), 400
    if not isinstance(max_chars, int) or max_chars < 50:
        return jsonify({'error': 'max_chars must be >= 50'}), 400

    # Get company name from job
    company_name = ''
    job_id = data.get('job_id')
    if job_id:
        from db.jobs import get_job
        job = get_job(job_id)
        if job:
            company_name = job.get('company_name', '')

    # Get base ES data
    base_es = None
    es_id = data.get('es_id')
    if es_id:
        from db.es import get_es_document
        es_doc = get_es_document(es_id)
        if es_doc and es_doc.get('parsed_data'):
            try:
                base_es = json.loads(es_doc['parsed_data'])
            except (ValueError, TypeError):
                pass

    # Get OpenWork data
    openwork_data = None
    if company_name:
        try:
            from db.openwork import get_openwork_data
            ow = get_openwork_data(company_name)
            if ow:
                openwork_data = dict(ow)
        except Exception:
            pass

    from services.strict_es_generator import generate_strict_es
    try:
        result = generate_strict_es(
            question=question, max_chars=max_chars,
            company_name=company_name, base_es=base_es,
            openwork_data=openwork_data
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Generation error: {e}'}), 503


# ── Copy-to-Clipboard Helper ──

@mypage_bp.route('/api/mypage/<int:job_id>/copy-data')
def get_copy_data(job_id):
    """Get all data needed for manual copy-paste into a MyPage.

    Returns profile, credential, and any generated ES texts.
    """
    from db.mypages import get_mypage_credential
    from db.user_profile import get_user_profile

    cred = get_mypage_credential(job_id)
    profile = get_user_profile()

    return jsonify({
        'credential': cred,
        'profile': profile.get('parsed', {}) if profile else {},
    })
