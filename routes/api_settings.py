"""API routes for Settings: AI config, credentials, and user preferences."""
import os
import logging
from flask import Blueprint, request, jsonify
from config import Config
from database import get_preferences, add_preference, delete_preference, toggle_preference

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__)


# ========== AI Settings ==========

@settings_bp.route('/api/ai/settings', methods=['POST'])
def api_ai_settings():
    """Save AI provider settings to .env file."""
    data = request.json
    provider = data.get('provider', 'gemini')
    api_key = data.get('api_key', '')
    logger.info(f"[settings] AI settings update: provider={provider}, key_length={len(api_key)}")

    if not api_key:
        logger.warning("[settings] AI settings save — empty API key")
        return jsonify({'status': 'error', 'error': 'APIキーが空です'})

    env_path = os.path.join(Config.BASE_DIR, '.env')

    # Read existing .env
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    # Update or add keys
    key_map = {'AI_PROVIDER': provider}
    if provider == 'gemini':
        key_map['GEMINI_API_KEY'] = api_key
    elif provider == 'deepseek':
        key_map['DEEPSEEK_API_KEY'] = api_key

    # Update existing lines
    updated_keys = set()
    new_lines = []
    for line in lines:
        updated = False
        for key, value in key_map.items():
            if line.strip().startswith(f'{key}=') or line.strip().startswith(f'{key} ='):
                new_lines.append(f'{key}={value}\n')
                updated_keys.add(key)
                updated = True
                break
        if not updated:
            new_lines.append(line)

    # Add missing keys
    for key, value in key_map.items():
        if key not in updated_keys:
            new_lines.append(f'{key}={value}\n')

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    # Update runtime environment
    for key, value in key_map.items():
        os.environ[key] = value

    logger.info(f"[ai] Saved AI settings: provider={provider}")
    return jsonify({'status': 'success', 'message': f'{provider.upper()} 設定を保存しました'})


@settings_bp.route('/api/ai/test', methods=['GET'])
def api_ai_test():
    """Test AI connection with a sample email."""
    from ai_parser import parse_email_with_ai, is_ai_configured
    if not is_ai_configured():
        return jsonify({'status': 'error', 'error': 'AIプロバイダーが設定されていません'})

    try:
        test_body = (
            'この度は弊社にご応募いただきありがとうございます。\n'
            '一次面接を以下の通り実施いたします。\n'
            '日時：2026年3月15日（月）14:00～\n'
            '場所：東京都渋谷区テストビル5F\n'
            'Zoom URL: https://zoom.us/j/123456789'
        )
        logger.info("[settings] AI test — calling parse_email_with_ai...")
        result = parse_email_with_ai(
            subject='【株式会社テスト】一次面接のご案内',
            sender='recruit@test-company.co.jp',
            body=test_body
        )
        logger.info(f"[settings] AI test result: {result}")
        if result:
            return jsonify({
                'status': 'success',
                'message': f"AI解析OK — 検出: {result.get('event_type', '?')} / {result.get('company_name', '?')}",
                'result': result
            })
        else:
            return jsonify({'status': 'error', 'error': 'AI解析結果が空でした'})
    except Exception as e:
        import traceback
        logger.error(f"[settings] AI test failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': f'{type(e).__name__}: {str(e)}'})


# ========== Credentials ==========

@settings_bp.route('/api/settings/credentials', methods=['POST'])
def api_save_credentials():
    """Save マイナビ credentials from the web UI into .env and update runtime Config."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    email = data.get('mynavi_email', '').strip()
    password = data.get('mynavi_password', '').strip()

    if not email or not password:
        return jsonify({'error': 'メールアドレスとパスワードを入力してください'}), 400

    try:
        env_path = os.path.join(Config.BASE_DIR, '.env')

        env_lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                env_lines = f.readlines()

        keys_to_set = {
            'MYNAVI_EMAIL': email,
            'MYNAVI_PASSWORD': password,
        }
        found_keys = set()
        new_lines = []
        for line in env_lines:
            stripped = line.strip()
            matched = False
            for key, val in keys_to_set.items():
                if stripped.startswith(f'{key}=') or stripped.startswith(f'# {key}='):
                    new_lines.append(f'{key}={val}\n')
                    found_keys.add(key)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        for key, val in keys_to_set.items():
            if key not in found_keys:
                new_lines.append(f'{key}={val}\n')

        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        Config.MYNAVI_EMAIL = email
        Config.MYNAVI_PASSWORD = password

        logger.info(f"Credentials updated for {email[:3]}***")
        return jsonify({'message': f'アカウント情報を保存しました ({email[:3]}...)'})

    except Exception as e:
        logger.exception(f"Error saving credentials: {e}")
        return jsonify({'error': str(e)}), 500


# ========== User Preferences (Search Keywords) ==========

@settings_bp.route('/api/preferences', methods=['GET'])
def api_get_preferences():
    return jsonify(get_preferences())


@settings_bp.route('/api/preferences', methods=['POST'])
def api_add_preference():
    data = request.get_json()
    keyword = (data or {}).get('keyword', '').strip()
    if not keyword:
        return jsonify({'error': 'keyword is required'}), 400
    if len(keyword) > 50:
        return jsonify({'error': 'キーワードは50文字以内にしてください'}), 400
    pref_id = add_preference(keyword)
    return jsonify({'id': pref_id, 'keyword': keyword, 'message': 'キーワードを追加しました'}), 201


@settings_bp.route('/api/preferences/<int:pref_id>', methods=['DELETE'])
def api_delete_preference(pref_id):
    delete_preference(pref_id)
    return jsonify({'message': 'キーワードを削除しました'})


@settings_bp.route('/api/preferences/<int:pref_id>/toggle', methods=['POST'])
def api_toggle_preference(pref_id):
    toggle_preference(pref_id)
    return jsonify({'message': 'キーワードを更新しました'})


# ========== Phase 7: Advanced LLM Settings ==========

@settings_bp.route('/api/llm/keys', methods=['GET'])
def api_llm_keys_list():
    """List all API keys (masked)."""
    from db.llm_settings import get_all_api_keys
    return jsonify(get_all_api_keys(include_secret=False))


@settings_bp.route('/api/llm/keys', methods=['POST'])
def api_llm_keys_add():
    """Add a new API key (encrypted in DB)."""
    from db.llm_settings import add_api_key
    data = request.get_json() or {}
    api_key = data.get('api_key', '').strip()
    provider = data.get('provider', 'gemini').strip()
    label = data.get('label', '').strip()
    rpm = int(data.get('rpm_limit', 10))
    daily = int(data.get('daily_limit', 1000))

    if not api_key:
        return jsonify({'error': 'APIキーを入力してください'}), 400

    key_id = add_api_key(provider, api_key, label, rpm, daily)

    # Also reload dispatcher keys
    try:
        from ai.dispatcher import dispatcher
        dispatcher.reload_keys()
    except Exception:
        pass

    return jsonify({'id': key_id, 'message': f'API Key を追加しました (ID: {key_id})'}), 201


@settings_bp.route('/api/llm/keys/<int:key_id>', methods=['DELETE'])
def api_llm_keys_delete(key_id):
    """Delete an API key."""
    from db.llm_settings import delete_api_key
    delete_api_key(key_id)
    try:
        from ai.dispatcher import dispatcher
        dispatcher.reload_keys()
    except Exception:
        pass
    return jsonify({'message': 'API Key を削除しました'})


@settings_bp.route('/api/llm/keys/<int:key_id>/toggle', methods=['POST'])
def api_llm_keys_toggle(key_id):
    """Toggle an API key enabled/disabled."""
    from db.llm_settings import toggle_api_key
    new_state = toggle_api_key(key_id)
    try:
        from ai.dispatcher import dispatcher
        dispatcher.reload_keys()
    except Exception:
        pass
    return jsonify({'enabled': new_state, 'message': f"Key {'有効' if new_state else '無効'}に切り替えました"})


@settings_bp.route('/api/llm/models', methods=['GET'])
def api_llm_models_list():
    """Get all workflow model configurations."""
    from db.llm_settings import get_all_model_configs
    return jsonify(get_all_model_configs())


@settings_bp.route('/api/llm/models', methods=['POST'])
def api_llm_models_save():
    """Save model configuration for a workflow."""
    from db.llm_settings import save_model_config
    data = request.get_json() or {}
    workflow = data.get('workflow', '').strip()
    if workflow not in ('chat', 'email', 'job', 'job_detail', 'filter', 'es'):
        return jsonify({'error': '無効な workflow です'}), 400

    save_model_config(
        workflow=workflow,
        provider=data.get('provider', 'gemini'),
        model_name=data.get('model_name', 'gemini-3-flash-preview'),
        endpoint_url=data.get('endpoint_url', ''),
        temperature=float(data.get('temperature', 0.7)),
        max_tokens=int(data.get('max_tokens', 4096)),
    )
    return jsonify({'message': f'{workflow} のモデル設定を保存しました'})


@settings_bp.route('/api/llm/filters', methods=['GET'])
def api_llm_filters_list():
    """Get all email filter rules."""
    from db.llm_settings import get_all_filter_rules
    return jsonify(get_all_filter_rules())


@settings_bp.route('/api/llm/filters', methods=['POST'])
def api_llm_filters_add():
    """Add a new email filter rule."""
    from db.llm_settings import add_filter_rule
    data = request.get_json() or {}
    rule_type = data.get('rule_type', '').strip()
    pattern = data.get('pattern', '').strip()
    description = data.get('description', '').strip()

    if rule_type not in ('sender', 'subject'):
        return jsonify({'error': 'rule_type は sender または subject を指定してください'}), 400
    if not pattern:
        return jsonify({'error': 'パターンを入力してください'}), 400

    # Validate regex
    import re
    try:
        re.compile(pattern)
    except re.error as e:
        return jsonify({'error': f'無効な正規表現: {e}'}), 400

    rule_id = add_filter_rule(rule_type, pattern, description)
    return jsonify({'id': rule_id, 'message': 'フィルタルールを追加しました'}), 201


@settings_bp.route('/api/llm/filters/<int:rule_id>', methods=['DELETE'])
def api_llm_filters_delete(rule_id):
    """Delete an email filter rule."""
    from db.llm_settings import delete_filter_rule
    delete_filter_rule(rule_id)
    return jsonify({'message': 'フィルタルールを削除しました'})


@settings_bp.route('/api/llm/filters/<int:rule_id>/toggle', methods=['POST'])
def api_llm_filters_toggle(rule_id):
    """Toggle a filter rule enabled/disabled."""
    from db.llm_settings import toggle_filter_rule
    new_state = toggle_filter_rule(rule_id)
    return jsonify({'enabled': new_state, 'message': 'ルールを更新しました'})


@settings_bp.route('/api/llm/usage', methods=['GET'])
def api_llm_usage():
    """Get today's LLM usage stats."""
    from db.llm_settings import get_daily_usage, get_total_daily_calls
    return jsonify({
        'total_calls': get_total_daily_calls(),
        'per_key': get_daily_usage(),
    })


@settings_bp.route('/api/llm/status', methods=['GET'])
def api_llm_status():
    """Get dispatcher status."""
    try:
        from ai.dispatcher import dispatcher
        return jsonify(dispatcher.get_status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== Database Storage Location ==========

def _get_app_config_path():
    """Path to the app_config.ini file."""
    return os.path.join(Config.BASE_DIR, 'data', 'app_config.ini')


def _save_db_path_to_ini(new_path: str):
    """Save DB path to app_config.ini."""
    import configparser
    ini_path = _get_app_config_path()
    cfg = configparser.ConfigParser()
    if os.path.exists(ini_path):
        cfg.read(ini_path, encoding='utf-8')
    if 'database' not in cfg:
        cfg['database'] = {}
    cfg['database']['db_path'] = new_path
    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    with open(ini_path, 'w', encoding='utf-8') as f:
        cfg.write(f)


@settings_bp.route('/api/db/config', methods=['GET'])
def api_db_config():
    """Get current database configuration."""
    db_path = Config.DB_PATH
    default_path = os.path.join(Config.BASE_DIR, 'data', 'jobs.db')
    file_size = 0
    try:
        if os.path.exists(db_path):
            file_size = os.path.getsize(db_path)
    except Exception:
        pass

    return jsonify({
        'current_path': db_path,
        'default_path': default_path,
        'is_default': os.path.normpath(db_path) == os.path.normpath(default_path),
        'file_size_mb': round(file_size / (1024 * 1024), 2),
        'file_exists': os.path.exists(db_path),
    })


@settings_bp.route('/api/db/migrate', methods=['POST'])
def api_db_migrate():
    """Migrate database to a new location.

    1. Copy current DB → new path
    2. Verify integrity of copy
    3. Update app_config.ini
    4. Requires app restart to take effect
    """
    import shutil
    import sqlite3

    data = request.get_json() or {}
    new_path = data.get('new_path', '').strip()

    if not new_path:
        return jsonify({'error': '新しいパスを指定してください'}), 400

    # Normalize path
    new_path = os.path.normpath(new_path)

    # Must be absolute path
    if not os.path.isabs(new_path):
        return jsonify({'error': '絶対パスを指定してください（例: D:\\data\\jobs.db）'}), 400

    # Must end with .db
    if not new_path.endswith('.db'):
        new_path = os.path.join(new_path, 'jobs.db')

    # Check target directory exists or can be created
    target_dir = os.path.dirname(new_path)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        return jsonify({'error': f'ディレクトリ作成失敗: {e}'}), 400

    # Don't migrate to same path
    current_path = Config.DB_PATH
    if os.path.normpath(new_path) == os.path.normpath(current_path):
        return jsonify({'error': '移動先が現在のパスと同じです'}), 400

    # Copy database
    try:
        logger.info(f"[db-migrate] Copying {current_path} → {new_path}")
        shutil.copy2(current_path, new_path)
    except Exception as e:
        return jsonify({'error': f'コピー失敗: {e}'}), 500

    # Verify integrity of the copy
    try:
        conn = sqlite3.connect(new_path, timeout=5)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        conn.close()

        if result[0] != 'ok':
            os.remove(new_path)
            return jsonify({'error': f'整合性チェック失敗: {result[0]}'}), 500

        if table_count == 0:
            os.remove(new_path)
            return jsonify({'error': 'コピーされたDBにテーブルがありません'}), 500

    except Exception as e:
        try:
            os.remove(new_path)
        except Exception:
            pass
        return jsonify({'error': f'検証失敗: {e}'}), 500

    # Update config
    _save_db_path_to_ini(new_path)

    # Update runtime config (takes effect after restart for DB connections)
    Config.DB_PATH = new_path

    file_size = os.path.getsize(new_path)

    logger.info(f"[db-migrate] Migration complete: {new_path} ({file_size} bytes)")
    return jsonify({
        'success': True,
        'new_path': new_path,
        'file_size_mb': round(file_size / (1024 * 1024), 2),
        'message': f'データベースを移動しました: {new_path}\nアプリを再起動してください。',
        'needs_restart': True,
    })


@settings_bp.route('/api/db/reset', methods=['POST'])
def api_db_reset():
    """Reset database path to default (data/jobs.db)."""
    default_path = os.path.join(Config.BASE_DIR, 'data', 'jobs.db')
    _save_db_path_to_ini(default_path)
    Config.DB_PATH = default_path
    logger.info(f"[db-migrate] Reset to default: {default_path}")
    return jsonify({
        'success': True,
        'new_path': default_path,
        'message': 'デフォルトに戻しました。アプリを再起動してください。',
        'needs_restart': True,
    })
