"""API routes for Gmail authentication and email fetching."""
import logging
from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

gmail_bp = Blueprint('gmail', __name__)


@gmail_bp.route('/api/gmail/auth', methods=['POST'])
def api_gmail_auth():
    """Initiate Gmail auth — launches browser cookie login."""
    logger.info("[gmail] Auth request — launching browser cookie login")
    try:
        from gmail_browser import gmail_cookie_login
        from threading import Thread

        thread = Thread(target=gmail_cookie_login, daemon=True)
        thread.start()
        return jsonify({
            'message': 'Gmailログインブラウザを開きました。ログインするとCookieが保存されます。'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@gmail_bp.route('/api/gmail/fetch', methods=['POST'])
def api_gmail_fetch():
    """Manually fetch Gmail emails — uses same pipeline as scheduler.

    Processes ALL unprocessed emails through the unified gmail dispatcher
    (browser/API auto-select → cache → filter → AI → register).

    Query params:
        max_results: max emails to fetch (default 20)
    """
    from flask import request
    max_results = request.args.get('max_results', 20, type=int)
    logger.info(f"[gmail] Manual fetch request received (max_results={max_results})")
    try:
        from services.gmail_dispatcher import fetch_emails

        result = fetch_emails(apply_filter=False, max_results=max_results)

        return jsonify({
            'count': result['emails_fetched'],
            'events_registered': result['events_registered'],
            'emails': result['emails'],
            'mode': result['mode'],
        })
    except Exception as e:
        logger.exception(f"[gmail] Fetch error: {e}")
        return jsonify({'error': str(e)}), 500
