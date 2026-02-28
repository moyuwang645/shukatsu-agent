"""API routes for AI Chat (keyword generation)."""
from flask import Blueprint, request, jsonify

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/api/chat', methods=['POST'])
def chat():
    """Send message to AI chat agent, receive keywords and reply."""
    data = request.get_json(force=True)
    user_message = data.get('message', '').strip()
    session_id = data.get('session_id')

    if not user_message:
        return jsonify({'error': 'message is required'}), 400

    from ai.chat_agent import chat_and_generate_keywords
    result = chat_and_generate_keywords(user_message, session_id)
    return jsonify(result)


@chat_bp.route('/api/chat/search', methods=['POST'])
def chat_search():
    """Run full AI search pipeline: chat -> keywords -> scrape -> save."""
    data = request.get_json(force=True)
    user_message = data.get('message', '').strip()
    session_id = data.get('session_id')

    if not user_message:
        return jsonify({'error': 'message is required'}), 400

    from services.ai_search_service import run_ai_search
    result = run_ai_search(user_message, session_id)
    return jsonify(result)


@chat_bp.route('/api/chat/search-direct', methods=['POST'])
def chat_search_direct():
    """Run scraper search with explicit keywords — no AI re-generation.

    Expects JSON: { "keywords": ["kw1", ...], "site_filters": {...} }
    Calls scrapers directly, skipping the chat→AI→keywords step.
    """
    data = request.get_json(force=True)
    keywords = data.get('keywords', [])
    site_filters = data.get('site_filters', None)

    if not keywords or not isinstance(keywords, list):
        return jsonify({'error': 'keywords (list) is required'}), 400

    from services.ai_search_service import run_search_with_keywords
    result = run_search_with_keywords(keywords, site_filters=site_filters)
    return jsonify(result)
