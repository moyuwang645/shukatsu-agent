"""AI ES Writer — generate company-specific ES content.

Takes a user's base ES (self_pr, motivation, strengths) and customizes
it for a specific company, incorporating OpenWork company culture data
to make the ES more compelling and tailored.
"""
import json
import logging
import time

from ai import call_llm, is_ai_configured, clean_json_response

logger = logging.getLogger(__name__)

from .prompt_loader import get_prompt

_DEFAULT_REWRITE_PROMPT = """あなたは日本の就活ES添削のプロです。
以下のベースES(自己PR・志望動機)を、指定企業向けにリライトしてください。

ルール:
- 企業の特徴・社風に合わせてアピールポイントを調整する
- OpenWorkデータがあれば、その企業文化に響く表現を使う
- 元の内容(経験・強み)は維持しつつ、表現を改善する
- custom_self_pr: 400字以内
- custom_motivation: 400字以内
- 「です・ます」調で統一

JSON形式のみで回答:
{{"custom_self_pr": "...", "custom_motivation": "..."}}

--- ベースES ---
自己PR: {self_pr}
志望動機: {motivation}
強み: {strengths}

--- 企業情報 ---
企業名: {company_name}
職種: {position}
業界: {industry}

--- OpenWork企業文化 ---
{openwork_info}
"""

def _get_rewrite_prompt() -> str:
    return get_prompt('es_writer', _DEFAULT_REWRITE_PROMPT)


def generate_custom_es(base_es: dict, job_data: dict,
                       openwork_data: dict = None) -> dict | None:
    """Generate company-customized ES content.

    Args:
        base_es: dict with self_pr, motivation, strengths keys.
        job_data: dict with company_name, position, industry.
        openwork_data: optional OpenWork scores dict.

    Returns:
        dict with custom_self_pr and custom_motivation, or None on failure.
    """
    if not is_ai_configured():
        logger.debug("[es_writer] AI not configured")
        return None

    # Build OpenWork context
    if openwork_data and openwork_data.get('overall_score'):
        sub = openwork_data.get('sub_scores', {})
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except json.JSONDecodeError:
                sub = {}
        ow_lines = [f"総合: {openwork_data['overall_score']}"]
        for label, score in sub.items():
            ow_lines.append(f"{label}: {score}")
        openwork_str = " / ".join(ow_lines)
    else:
        openwork_str = "（データなし）"

    strengths = base_es.get('strengths', [])
    if isinstance(strengths, list):
        strengths_str = ", ".join(strengths) if strengths else "（未記載）"
    else:
        strengths_str = str(strengths)

    prompt = _get_rewrite_prompt().format(
        self_pr=base_es.get('self_pr', '')[:800] or '（未記載）',
        motivation=base_es.get('motivation', '')[:800] or '（未記載）',
        strengths=strengths_str,
        company_name=job_data.get('company_name', '不明'),
        position=job_data.get('position', '不明'),
        industry=job_data.get('industry', '不明'),
        openwork_info=openwork_str,
    )

    logger.info(f"[es_writer] Generating ES for: {job_data.get('company_name', '?')}")

    try:
        import re
        raw = call_llm(prompt, priority=3, workflow='es')
        cleaned = clean_json_response(raw)

        # Fix unescaped newlines
        fixed = re.sub(r'(?<=": ")(.+?)(?="[,}])',
                       lambda m: m.group(0).replace('\n', '\\n'),
                       cleaned, flags=re.DOTALL)

        try:
            result = json.loads(fixed)
        except json.JSONDecodeError:
            # Regex fallback
            pr_m = re.search(r'"custom_self_pr"\s*:\s*"([^"]*)', cleaned)
            mo_m = re.search(r'"custom_motivation"\s*:\s*"([^"]*)', cleaned)
            result = {
                'custom_self_pr': pr_m.group(1) if pr_m else '',
                'custom_motivation': mo_m.group(1) if mo_m else '',
            }

        result.setdefault('custom_self_pr', '')
        result.setdefault('custom_motivation', '')

        logger.info(f"[es_writer] Generated: PR={len(result['custom_self_pr'])}chars, "
                     f"Motivation={len(result['custom_motivation'])}chars")
        return result

    except Exception as e:
        logger.warning(f"[es_writer] Generation failed: {e}")
        return None
