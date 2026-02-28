"""AI Job Detail Parser — extract structured data from scraped job detail pages.

Takes the full text content of a job listing detail page and uses LLM
to extract structured fields like salary, benefits, location, etc.
Also analyses company business, culture, recruitment process, and next steps.

Rate limiting is handled by the caller (BaseScraper._run_pipeline).
"""
import json
import logging

from . import call_llm, is_ai_configured, clean_json_response
from .prompt_loader import get_prompt

logger = logging.getLogger(__name__)

_DEFAULT_DETAIL_PROMPT = """あなたは日本の新卒就活支援AIです。
以下の企業ページテキストから構造化データを抽出してJSON形式で出力してください。

⚠️ 必ず以下の14キーを全て含むJSONを出力すること。省略は禁止。該当なしは "なし" と記入。

{{
  "company_business": "事業内容の要約（何を提供している会社か。200字以内）",
  "company_culture": "社風・雰囲気（例: 若手活躍、定着率高い、チーム重視。100字以内）",
  "selection_process": "選考フロー（例: 説明会→適性検査→一次面接→最終面接）",
  "next_action": "就活生が今すべき次のステップ（例: 説明会に申し込む）",
  "next_action_url": "次のアクションURL（例: https://job.career-tasu.jp/corp/XXXXX/seminar/）",
  "position": "募集職種",
  "salary": "給与（例: 月給25万円）",
  "location": "勤務地",
  "benefits": "福利厚生の要点",
  "work_style": "働き方（例: テレワーク、完全週休2日）",
  "requirements": "応募条件・求める人材",
  "job_description": "仕事内容の要約（100字以内）",
  "industry": "業界（例: IT・通信）",
  "deadline_date": "YYYY-MM-DD形式の締切日"
}}

=== 抽出ヒント ===
- company_business: 「私たちの事業」「事業内容」セクション
- company_culture: 「私たちの特徴」「社風」「定着率」等
- selection_process: 「STEP.1」「STEP.2」「選考プロセス」
- next_action_url: /corp/数字/seminar/ や /employment/ 等のURL

--- 企業名 ---
{company_name}

--- 既知データ ---
{existing_fields}

--- テキスト ---
{page_text}
"""


def _get_detail_prompt() -> str:
    return get_prompt('job_detail_parser', _DEFAULT_DETAIL_PROMPT)


def parse_job_detail_with_ai(
    raw_text: str,
    company_name: str = '',
    existing_data: dict = None,
) -> dict | None:
    """Parse a scraped job detail page using AI.

    Args:
        raw_text: Full text content of the detail page (trimmed to 5000 chars).
        company_name: Company name for context.
        existing_data: Already-extracted fields to skip.

    Returns:
        dict with keys: position, salary, location, benefits,
                        job_description, work_style, requirements,
                        deadline_date, industry,
                        company_business, company_culture,
                        selection_process, next_action, next_action_url
        Or None if AI not configured or parse fails.
    """
    if not is_ai_configured():
        logger.debug("[job_detail_parser] AI not configured")
        return None

    if not raw_text or len(raw_text.strip()) < 50:
        logger.debug("[job_detail_parser] Text too short, skipping")
        return None

    # Build existing fields summary
    existing_str = "（なし）"
    if existing_data:
        known = []
        for k, v in existing_data.items():
            if v and v not in ('', 'なし', None):
                known.append(f"{k}: {v}")
        if known:
            existing_str = "\n".join(known)

    prompt = _get_detail_prompt().format(
        company_name=company_name or '不明',
        existing_fields=existing_str,
        page_text=raw_text[:5000],
    )

    try:
        raw = call_llm(prompt, priority=1, workflow='job_detail')
        cleaned = clean_json_response(raw)
        result = json.loads(cleaned)

        # Build ai_summary from company analysis fields
        summary_parts = []
        if result.get('company_business') and result['company_business'] != 'なし':
            summary_parts.append(f"【事業】{result['company_business']}")
        if result.get('company_culture') and result['company_culture'] != 'なし':
            summary_parts.append(f"【社風】{result['company_culture']}")
        if result.get('selection_process') and result['selection_process'] != 'なし':
            summary_parts.append(f"【選考】{result['selection_process']}")
        if result.get('next_action') and result['next_action'] != 'なし':
            summary_parts.append(f"【次のステップ】{result['next_action']}")
        if result.get('next_action_url') and result['next_action_url'] != 'なし':
            summary_parts.append(f"【URL】{result['next_action_url']}")

        if summary_parts:
            result['ai_summary'] = '\n'.join(summary_parts)

        logger.info(
            f"[job_detail_parser] Parsed: {company_name} → "
            f"salary={result.get('salary', '?')}, "
            f"biz={result.get('company_business', '?')[:30]}, "
            f"process={result.get('selection_process', '?')[:30]}"
        )
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"[job_detail_parser] JSON error: {e}")
        return None
    except Exception as e:
        logger.warning(f"[job_detail_parser] Parse failed: {e}")
        return None

