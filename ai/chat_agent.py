"""AI Chat Agent — conversational keyword generation for job search.

Converts natural language user preferences into structured search keywords
that can be fed into the scrapers' search_jobs() methods.
"""
import json
import logging
from datetime import datetime

from . import call_llm, is_ai_configured, clean_json_response
from db.chat import add_message, get_session_messages, new_session_id

logger = logging.getLogger(__name__)

from .prompt_loader import get_prompt

_DEFAULT_CHAT_PROMPT = """あなたは日本の新卒就活アドバイザーAIです。
ユーザーの希望（業界、職種、勤務地、給与、働き方など）をヒアリングし、
就活サイトで使える効果的な検索キーワードと、各サイトの絞り込みフィルターを生成してください。

必ず以下の JSON 形式のみで回答してください。説明文は一切不要です。

{
  "reply": "ユーザーへの返答（日本語、1〜3文）",
  "keywords": ["キーワード1", "キーワード2", "キーワード3"],
  "site_filters": {
    "engineer_shukatu": {"arr_industry": [], "arr_occupation": [], "arr_language": []},
    "gaishishukatsu": {"checkboxes": []},
    "onecareer": {"categories": []}
  }
}

ルール:
- キーワードは3〜5個生成してください。
- 各キーワードは就活サイトの検索ボックスにそのまま入力できる形式にしてください。
- 業種名、職種名、勤務地、企業規模などを組み合わせてください。
- 同義語や関連語も含めて検索範囲を広げてください。
  例: 「ITエンジニア」→ ["ITエンジニア", "SE システムエンジニア", "プログラマー 開発"]
- ユーザーの情報が不足している場合は、reply で追加質問してください。
  その場合でも keywords は現時点で推測できるものを最低1つは含めてください。
- JSON のみを出力し、マークダウンのコードブロック(```)で囲まないでください。

site_filters のサイト別フィルタ:
- engineer_shukatu.arr_industry: SIer, ゲーム, WEBサービス, AI・人工知能, SaaS, ITコンサル 等
- engineer_shukatu.arr_occupation: システムエンジニア, プログラマー, WEBエンジニア, データサイエンティスト 等
- engineer_shukatu.arr_language: Python, Java, TypeScript, Go, C++, Rust 等
- gaishishukatsu.checkboxes: エンジニア志望向け, 海外大生歓迎, 理系学生歓迎, ITサービス, 外資IT 等
- onecareer.categories: 1=コンサル, 2=金融, 3=メーカー, 4=商社, 5=IT・通信, 6=広告, 7=人材, 8=インフラ 等
- site_filters に該当するものがなければ空配列にしてください。
"""

def _get_system_prompt() -> str:
    return get_prompt('chat_agent', _DEFAULT_CHAT_PROMPT)


def chat_and_generate_keywords(user_message: str, session_id: str = None) -> dict:
    """Process a user message and generate search keywords.

    Args:
        user_message: The user's natural language input.
        session_id: Optional session ID to continue a conversation.
                    If None, a new session is created.

    Returns:
        dict with keys:
            session_id: str — the session ID (new or existing)
            reply: str — AI's reply to the user
            keywords: list[str] — generated search keywords
    """
    if not is_ai_configured():
        return {
            'session_id': session_id or new_session_id(),
            'reply': 'AI が設定されていません。設定ページから API キーを登録してください。',
            'keywords': []
        }

    # Create or continue session
    if not session_id:
        session_id = new_session_id()

    # Save user message to chat history
    add_message(session_id, 'user', user_message)

    # Build conversation context from history
    history = get_session_messages(session_id)
    conversation = []
    for msg in history:
        conversation.append(f"{'ユーザー' if msg['role'] == 'user' else 'アシスタント'}: {msg['content']}")

    today = datetime.now().strftime('%Y-%m-%d')
    base_prompt = _get_system_prompt()
    prompt = base_prompt + f"\n今日の日付: {today}\n\n--- 会話履歴 ---\n"
    prompt += "\n".join(conversation)
    prompt += "\n\n上記の会話に基づいて、キーワードを生成してください。"

    try:
        raw = call_llm(prompt, priority=0, workflow='chat')
        cleaned = clean_json_response(raw)
        result = json.loads(cleaned)

        reply = result.get('reply', '')
        keywords = result.get('keywords', [])
        site_filters = result.get('site_filters', {})

        # Ensure keywords is always a list of strings
        if isinstance(keywords, str):
            keywords = [keywords]
        keywords = [str(k) for k in keywords if k]

        # Ensure site_filters is a dict
        if not isinstance(site_filters, dict):
            site_filters = {}

        logger.info(f"[chat] Reply: {reply[:50]}... Keywords: {keywords} Filters: {list(site_filters.keys())}")

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[chat] Parse error: {e}")
        reply = '申し訳ありません、処理中にエラーが発生しました。もう一度お試しください。'
        keywords = []

    # Save assistant reply to chat history
    add_message(session_id, 'assistant', reply,
                metadata=json.dumps({'keywords': keywords, 'site_filters': site_filters}, ensure_ascii=False))

    return {
        'session_id': session_id,
        'reply': reply,
        'keywords': keywords,
        'site_filters': site_filters,
    }
