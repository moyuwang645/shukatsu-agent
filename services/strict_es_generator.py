"""Strict word-count ES generator for MyPage form fields.

Given a question/topic and character limits, generates ES text that satisfies:
    max_length * 0.9 <= actual_length <= max_length

Uses a retry loop with feedback to the LLM when length constraints are violated.
"""
import logging
import re

logger = logging.getLogger(__name__)


def count_chars(text: str) -> int:
    """Count characters the way Japanese MyPage systems do.

    Strips whitespace and newlines (most systems do NOT count them).
    """
    return len(text.replace(' ', '').replace('　', '')
               .replace('\n', '').replace('\r', '').strip())


def _load_prompt_template() -> str:
    """Load the MyPage ES generation prompt template."""
    import os
    prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
    prompt_path = os.path.join(prompts_dir, 'mypage_es_generator.txt')
    if os.path.isfile(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    # Fallback default prompt
    return DEFAULT_PROMPT


DEFAULT_PROMPT = """あなたは日本の新卒就活生のESライターです。
与えられた質問に対して、指定された文字数制限内で回答を日本語で生成してください。

重要なルール:
- 必ず{min_chars}文字以上、{max_chars}文字以下で生成すること
- 具体的なエピソードや数字を含めること
- 「です・ます」調で丁寧に書くこと
- 企業の特徴や求める人材像を意識すること

{feedback}

質問: {question}
企業名: {company_name}
ベースES情報: {base_es_summary}

回答（{min_chars}〜{max_chars}文字）:"""


def generate_strict_es(question: str, max_chars: int,
                       company_name: str = '',
                       base_es: dict = None,
                       openwork_data: dict = None,
                       max_retries: int = 3) -> dict:
    """Generate ES text with strict character count enforcement.

    Args:
        question: The ES question/topic from the MyPage form
        max_chars: Maximum character limit from the form
        company_name: Target company name
        base_es: Dict with self_pr, motivation, etc. from user's base ES
        openwork_data: OpenWork scores/data for the company
        max_retries: Maximum LLM generation attempts

    Returns:
        dict with keys:
            text: The generated ES text
            char_count: Actual character count
            max_chars: The limit
            min_chars: The 90% threshold
            attempts: Number of attempts used
            status: 'ok', 'truncated', or 'failed'
    """
    from ai import call_llm, is_ai_configured

    if not is_ai_configured():
        return {
            'text': '', 'char_count': 0, 'max_chars': max_chars,
            'min_chars': int(max_chars * 0.9), 'attempts': 0, 'status': 'failed'
        }

    min_chars = int(max_chars * 0.9)
    prompt_template = _load_prompt_template()

    # Build base ES summary
    base_summary = ''
    if base_es:
        parts = []
        if base_es.get('self_pr'):
            parts.append(f"自己PR: {base_es['self_pr'][:200]}")
        if base_es.get('motivation'):
            parts.append(f"志望動機: {base_es['motivation'][:200]}")
        if base_es.get('strengths'):
            strengths = base_es['strengths']
            if isinstance(strengths, list):
                strengths = '、'.join(strengths)
            parts.append(f"強み: {strengths}")
        if base_es.get('experience'):
            parts.append(f"経験: {base_es['experience'][:200]}")
        base_summary = '\n'.join(parts)

    # Add OpenWork context if available
    if openwork_data:
        ow_parts = []
        if openwork_data.get('overall_score'):
            ow_parts.append(f"OpenWork総合: {openwork_data['overall_score']}")
        if openwork_data.get('sub_scores') and isinstance(openwork_data['sub_scores'], dict):
            for k, v in list(openwork_data['sub_scores'].items())[:4]:
                ow_parts.append(f"  {k}: {v}")
        if ow_parts:
            base_summary += '\n\n企業評判:\n' + '\n'.join(ow_parts)

    feedback = ''
    best_text = ''
    best_diff = float('inf')

    for attempt in range(1, max_retries + 1):
        prompt = prompt_template.format(
            question=question,
            company_name=company_name or '(不明)',
            base_es_summary=base_summary or '(なし)',
            min_chars=min_chars,
            max_chars=max_chars,
            feedback=feedback,
        )

        try:
            result = call_llm(prompt)
        except Exception as e:
            logger.warning(f"[strict_es] LLM call failed attempt {attempt}: {e}")
            continue

        if not result:
            logger.warning(f"[strict_es] Empty LLM response on attempt {attempt}")
            continue

        # Clean up the text (remove markdown, leading/trailing junk)
        text = result.strip()
        text = re.sub(r'^```.*?\n', '', text)
        text = re.sub(r'\n```$', '', text)
        text = text.strip()

        actual = count_chars(text)
        logger.info(f"[strict_es] Attempt {attempt}: {actual} chars "
                    f"(target: {min_chars}-{max_chars})")

        # Track the best attempt so far
        if min_chars <= actual <= max_chars:
            # Perfect — within bounds
            return {
                'text': text, 'char_count': actual, 'max_chars': max_chars,
                'min_chars': min_chars, 'attempts': attempt, 'status': 'ok'
            }

        diff = abs(actual - max_chars) if actual > max_chars else abs(min_chars - actual)
        if diff < best_diff:
            best_diff = diff
            best_text = text

        # Build feedback for next attempt
        if actual > max_chars:
            over = actual - max_chars
            feedback = (f"【修正指示】前回の生成は{actual}文字で、"
                        f"上限{max_chars}文字を{over}文字超過しています。"
                        f"内容を維持しつつ{over}文字以上削減してください。")
        else:
            short = min_chars - actual
            feedback = (f"【修正指示】前回の生成は{actual}文字で、"
                        f"下限{min_chars}文字に{short}文字足りません。"
                        f"具体例やエピソードを追加して{short}文字以上増やしてください。")

    # All retries exhausted — use best attempt with forced truncation if needed
    if best_text:
        actual = count_chars(best_text)
        if actual > max_chars:
            best_text = _force_truncate(best_text, max_chars)
            actual = count_chars(best_text)
            status = 'truncated'
        else:
            status = 'short_accepted'

        return {
            'text': best_text, 'char_count': actual, 'max_chars': max_chars,
            'min_chars': min_chars, 'attempts': max_retries, 'status': status
        }

    return {
        'text': '', 'char_count': 0, 'max_chars': max_chars,
        'min_chars': min_chars, 'attempts': max_retries, 'status': 'failed'
    }


def _force_truncate(text: str, max_chars: int) -> str:
    """Force-truncate text to max_chars at the nearest sentence boundary.

    Tries to cut at 。, then at 、, then at any character.
    """
    if count_chars(text) <= max_chars:
        return text

    # Try truncating at sentence boundaries (。)
    sentences = text.split('。')
    result = ''
    for i, sentence in enumerate(sentences):
        candidate = result + sentence + '。' if i < len(sentences) - 1 else result + sentence
        if count_chars(candidate) > max_chars:
            break
        result = candidate

    if result and count_chars(result) >= int(max_chars * 0.85):
        return result.rstrip('。') + '。'

    # Fallback: hard cut
    chars_counted = 0
    cut_pos = 0
    for i, ch in enumerate(text):
        if ch not in (' ', '　', '\n', '\r'):
            chars_counted += 1
        if chars_counted >= max_chars:
            cut_pos = i
            break
    if cut_pos > 0:
        truncated = text[:cut_pos]
        # Try to end at a natural break
        last_period = truncated.rfind('。')
        if last_period > len(truncated) * 0.8:
            return truncated[:last_period + 1]
        return truncated

    return text[:max_chars]
