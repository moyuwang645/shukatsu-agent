"""API routes for Gmail authentication, email fetching, and mode management."""
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

gmail_bp = Blueprint('gmail', __name__)


@gmail_bp.route('/api/gmail/auth', methods=['POST'])
def api_gmail_auth():
    """Initiate Gmail auth — launches browser cookie login."""
    logger.info("[gmail] Auth request — launching browser cookie login")
    try:
        from gmail_browser import gmail_cookie_login
        from threading import Thread

        def _run_login():
            try:
                logger.info("[gmail-auth] Thread started, launching browser...")
                success, msg = gmail_cookie_login()
                logger.info(f"[gmail-auth] Login result: success={success}, msg={msg}")
            except Exception as e:
                logger.exception(f"[gmail-auth] Login thread crashed: {e}")

        # daemon=False so the thread survives even if Flask request ends
        thread = Thread(target=_run_login, daemon=False, name="gmail-cookie-login")
        thread.start()
        return jsonify({
            'message': 'Gmailログインブラウザを開きました。ログインするとCookieが保存されます。'
        })
    except Exception as e:
        logger.exception(f"[gmail] Auth error: {e}")
        return jsonify({'error': str(e)}), 500


@gmail_bp.route('/api/gmail/fetch', methods=['POST'])
def api_gmail_fetch():
    """Fetch Gmail emails using the mode registry.

    Request body (JSON):
        mode:    'backfill' | 'incremental' | 'keyword_search' (default: 'incremental')
        keyword: Search keyword (required for keyword_search mode)
        limit:   Max emails for keyword_search (default from settings)
        days:    Override backfill days (default from settings)
    """
    body = request.get_json(silent=True) or {}
    mode = body.get('mode', 'incremental')
    params = {k: v for k, v in body.items() if k != 'mode'}

    logger.info(f"[gmail] Manual fetch: mode={mode}, params={params}")

    try:
        from services.gmail_dispatcher import fetch_emails

        # Keyword search: don't apply filter (user explicitly wants these)
        apply_filter = mode != 'keyword_search'
        result = fetch_emails(mode=mode, params=params, apply_filter=apply_filter)

        return jsonify({
            'count': result['emails_fetched'],
            'events_registered': result['events_registered'],
            'mode': result.get('mode_name', mode),
            'transport': result.get('mode', ''),
            'emails': result.get('emails', []),
            'error': result.get('error', ''),
        })
    except Exception as e:
        logger.exception(f"[gmail] Fetch error: {e}")
        return jsonify({'error': str(e)}), 500


@gmail_bp.route('/api/gmail/modes')
def api_gmail_modes():
    """List all registered Gmail fetch modes."""
    from services.gmail_modes import registry
    return jsonify(registry.list_modes())


@gmail_bp.route('/api/gmail/settings', methods=['GET', 'POST'])
def api_gmail_settings():
    """Get or update Gmail settings."""
    from db.gmail_settings import get_gmail_config, update_gmail_config

    if request.method == 'GET':
        return jsonify(get_gmail_config())

    # POST
    body = request.get_json(silent=True) or {}
    update_gmail_config(body)
    return jsonify({'ok': True, 'config': get_gmail_config()})


@gmail_bp.route('/api/gmail/progress')
def api_gmail_progress():
    """Get current Gmail fetch progress (polled by frontend)."""
    from services.gmail_progress import get_progress
    return jsonify(get_progress())
