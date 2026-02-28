"""AI Job Enricher — analyze and score individual job postings.

Combines job description, user preferences, and OpenWork company data
to generate a match score, summary, and relevant tags.
"""
import json
import logging
import time

from . import call_llm, is_ai_configured, clean_json_response

logger = logging.getLogger(__name__)

from .prompt_loader import get_prompt

_DEFAULT_ENRICHMENT_PROMPT = """求人を分析し、ユーザーの希望条件との適合度を0〜100で採点してください。

必ず以下の JSON 形式のみで回答:
{{"match_score": 75, "ai_summary": "短い要約(50字以内)", "tags": ["タグ1", "タグ2"]}}

採点基準: 職種マッチ(30%), 勤務地(20%), 給与(20%), 企業環境(30%)

タグ例: "リモートOK", "成長環境◎", "高年収", "大手企業", "風通し良"

--- 求人 ---
企業: {company_name} / 職種: {position} / 勤務地: {location}
給与: {salary} / 業界: {industry}
説明: {description}

--- ユーザー希望 ---
{user_prefs}

--- OpenWork ---
{openwork_info}
"""

def _get_enrichment_prompt() -> str:
    return get_prompt('job_enricher', _DEFAULT_ENRICHMENT_PROMPT)


def enrich_single_job(job_data: dict, user_preferences: list = None,
                      openwork_data: dict = None) -> dict | None:
    """Analyze a single job and return match score + summary + tags.

    Args:
        job_data: dict with keys like company_name, position, location, etc.
        user_preferences: list of keyword strings from user_preferences table.
        openwork_data: dict from openwork_cache (overall_score, sub_scores).

    Returns:
        dict with keys: match_score (int 0-100), ai_summary (str), tags (list[str])
        Or None if AI is not configured.
    """
    if not is_ai_configured():
        logger.debug("[enricher] AI not configured")
        return None

    # Build user preferences string
    if user_preferences:
        prefs_str = ", ".join(user_preferences)
    else:
        prefs_str = "（指定なし）"

    # Build OpenWork info string
    if openwork_data and openwork_data.get('overall_score'):
        ow_lines = [f"総合: {openwork_data['overall_score']}"]
        sub = openwork_data.get('sub_scores', {})
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except json.JSONDecodeError:
                sub = {}
        for label, score in sub.items():
            ow_lines.append(f"{label}: {score}")
        openwork_str = " / ".join(ow_lines)
    else:
        openwork_str = "なし"

    prompt = _get_enrichment_prompt().format(
        company_name=job_data.get('company_name', '') or job_data.get('company_name_jp', ''),
        position=job_data.get('position', '不明'),
        location=job_data.get('location', '不明'),
        salary=job_data.get('salary', '不明'),
        industry=job_data.get('industry', '不明'),
        description=(job_data.get('job_description', '') or '')[:800],
        user_prefs=prefs_str,
        openwork_info=openwork_str,
    )

    import re as _re

    logger.info(f"[enricher] Analyzing: {job_data.get('company_name', '?')}")

    try:
        raw = call_llm(prompt, priority=1, workflow='job')
        cleaned = clean_json_response(raw)

        # Fix unescaped newlines inside JSON string values
        # Replace actual newlines between quotes with escaped \n
        fixed = _re.sub(r'(?<=": ")(.+?)(?="[,}])',
                        lambda m: m.group(0).replace('\n', '\\n'),
                        cleaned, flags=_re.DOTALL)

        try:
            result = json.loads(fixed)
        except json.JSONDecodeError:
            # Fallback: extract fields individually via regex
            logger.warning("[enricher] JSON parse failed, using regex fallback")
            score_m = _re.search(r'"match_score"\s*:\s*(\d+)', cleaned)
            summary_m = _re.search(r'"ai_summary"\s*:\s*"([^"]*)', cleaned)
            tags_m = _re.findall(r'"tags"\s*:\s*\[([^\]]*)\]', cleaned)

            result = {
                'match_score': int(score_m.group(1)) if score_m else 50,
                'ai_summary': summary_m.group(1) if summary_m else '',
                'tags': [],
            }
            if tags_m:
                result['tags'] = _re.findall(r'"([^"]+)"', tags_m[0])

        # Validate and clamp
        match_score = int(result.get('match_score', 50))
        match_score = max(0, min(100, match_score))

        ai_summary = str(result.get('ai_summary', ''))
        tags = result.get('tags', [])
        if isinstance(tags, str):
            tags = [tags]
        tags = [str(t) for t in tags if t]

        logger.info(f"[enricher] Score={match_score}, Tags={tags}")

        return {
            'match_score': match_score,
            'ai_summary': ai_summary,
            'tags': tags,
        }

    except Exception as e:
        logger.warning(f"[enricher] Analysis failed: {e}")
        return None
