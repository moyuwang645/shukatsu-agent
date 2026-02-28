"""AI-powered email parser for extracting event info from job-hunting emails."""
import json
import logging
from datetime import datetime

from . import call_llm, is_ai_configured, clean_json_response

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Prompt template for email parsing
# ──────────────────────────────────────────────
from .prompt_loader import get_prompt

_DEFAULT_EMAIL_PROMPT = """You are an AI assistant that analyzes Japanese job-hunting (新卒採用) emails.
Extract structured information from the email (subject + body) provided below.

=== OUTPUT FORMAT (STRICT) ===
Respond with ONLY a single valid JSON object. No explanation, no markdown code fences, no extra text.
If a field cannot be determined from the email, use "なし" (NOT null).

{
  "is_job_related": true or false,
  "event_type": "interview" | "es_deadline" | "webtest" | "seminar" | "offer" | "rejection" | "other",
  "company_name": "正式な企業名（株式会社○○）",
  "position": "職種名（例: 総合職、SE職、技術職）",
  "job_url": "求人ページ・マイページ・エントリーページのURL",
  "deadline_date": "YYYY-MM-DD（締切日）",
  "location": "勤務地（例: 東京都港区）",
  "salary": "給与情報（例: 月給25万円、年収400万円）",
  "job_type": "コース名（例: オープンコース、技術系コース）",
  "interview_type": "一次面接 | 二次面接 | 最終面接 | GD | Webテスト | 適性検査 | ES提出 | 説明会 | その他",
  "scheduled_date": "YYYY-MM-DD（面接・イベント日）",
  "scheduled_time": "HH:MM（開始時刻）",
  "online_url": "Zoom/Teams/Google MeetのURL",
  "summary": "メールの要点を1行で日本語で"
}

=== EXTRACTION RULES ===

【company_name — 企業名の抽出】
- 「株式会社」「（株）」「合同会社」「有限会社」を含む正式法人名を抽出すること
- 件名の【】や［］内はキャッチコピー・コース名・職種名であり、企業名ではない
  (例) 件名「【職種・勤務地確約】富士フイルムシステムサービス（株）説明会」
  → company_name = "富士フイルムシステムサービス"  ← 正解
  → company_name = "職種・勤務地確約"  ← 不正解
- 送信者ドメインや本文の署名欄も参照して正確な企業名を特定すること

【position — 職種】
- 総合職、SE職、技術職、営業職、事務職 等
- 記載がない場合は "なし"

【job_url — 求人URL】
- マイページURL、エントリーページURL、求人詳細ページURL を抽出
- 企業の採用ページへのリンクも対象
- 記載がない場合は "なし"

【location — 勤務地】
- 都道府県 + 市区町村、またはビル名・住所
- 記載がない場合は "なし"

【salary — 給与】
- 月給、年収、初任給 等の給与情報
- 記載がない場合は "なし"

【event_type — イベント分類】
- 「説明会」「セミナー」「会社紹介」→ "seminar"
- 「ES提出」「エントリーシート締切」「ES締切」→ "es_deadline"
- 「面接」「面談」→ "interview"
- 「Webテスト」「適性検査」「SPI」→ "webtest"
- 「内定」「内々定」→ "offer"
- 「お祈り」「選考結果」「残念ながら」「今後のご活躍」→ "rejection"

【date — 日付計算】
- 今日は {today} です。「明日」「来週月曜」等の相対表現はこの日付基準で計算すること

【online_url】
- Zoom / Teams / Google Meet の会議URLのみ。マイページURLは job_url に入れること

【is_job_related】
- 広告・ニュースレター・配送通知・クーポン等は false
"""

def _get_email_prompt() -> str:
    return get_prompt('email_parser', _DEFAULT_EMAIL_PROMPT)


def parse_email_with_ai(subject: str, sender: str, body: str) -> dict | None:
    """Parse a job-hunting email using AI and return structured data.

    Returns a dict with keys:
        is_job_related, event_type, company_name, position, job_url,
        deadline_date, location, salary, job_type,
        interview_type, scheduled_date, scheduled_time,
        online_url, summary
    Values use 'なし' instead of null for missing fields.
    Returns None if AI is not configured or parsing fails.
    """
    if not is_ai_configured():
        logger.debug("[ai] AI not configured, skipping")
        return None

    today = datetime.now().strftime('%Y-%m-%d (%A)')

    prompt = _get_email_prompt().replace('{today}', today) + f"""

--- メール情報 ---
送信者: {sender}
件名: {subject}
本文:
{body[:3000]}
"""

    try:
        raw = call_llm(prompt, priority=2, workflow='email')
        logger.debug(f"[ai] Raw response ({len(raw)} chars): {raw[:300]}")
        cleaned = clean_json_response(raw)
        result = json.loads(cleaned)
        logger.info(f"[ai] Parsed: type={result.get('event_type')} company={result.get('company_name')}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"[ai] JSON parse error: {e}\nRaw ({len(raw)} chars): {raw[:500]}")
        return None
    except Exception as e:
        logger.warning(f"[ai] Parse failed: {e}")
        return None
