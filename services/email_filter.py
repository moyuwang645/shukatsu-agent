"""3-Tier Email Filtering Pipeline.

Dramatically reduces LLM API calls by pre-filtering emails before
sending them for deep AI analysis:

    Layer 1: Local regex matching (zero API calls)
             → Removes ~50% of non-job emails using sender/subject patterns
    Layer 2: LLM batch pre-screening (1 API call per 5-10 emails)
             → Quick binary classification in batches
    Layer 3: Single-email deep analysis (1 API call per email)
             → Full structured extraction via existing email_parser
"""
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


# ===================================================================
# Layer 1: Local Regex Pre-Filter (zero API calls)
# ===================================================================

def layer1_regex_filter(emails: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply regex rules from DB to quickly filter out obvious non-job emails.

    Args:
        emails: List of email dicts with at least 'sender' and 'subject' keys.

    Returns:
        (passed, filtered) — emails that passed, and emails that were filtered out.
    """
    try:
        from db.llm_settings import get_enabled_filter_rules
        rules = get_enabled_filter_rules()
    except Exception as e:
        logger.warning(f"[email_filter] Failed to load filter rules: {e}")
        return emails, []

    sender_patterns = []
    subject_patterns = []
    for rule in rules:
        try:
            pattern = re.compile(rule['pattern'], re.IGNORECASE)
            if rule['rule_type'] == 'sender':
                sender_patterns.append(pattern)
            elif rule['rule_type'] == 'subject':
                subject_patterns.append(pattern)
        except re.error as e:
            logger.warning(f"[email_filter] Invalid regex in rule {rule['id']}: {e}")

    passed = []
    filtered = []

    for email in emails:
        sender = email.get('sender', '') or ''
        subject = email.get('subject', '') or ''
        is_filtered = False

        for pattern in sender_patterns:
            if pattern.search(sender):
                is_filtered = True
                break

        if not is_filtered:
            for pattern in subject_patterns:
                if pattern.search(subject):
                    is_filtered = True
                    break

        if is_filtered:
            filtered.append(email)
        else:
            passed.append(email)

    if filtered:
        logger.info(f"[email_filter] Layer 1: {len(filtered)}/{len(emails)} "
                    f"emails filtered by regex rules")

    return passed, filtered


# ===================================================================
# Layer 2: LLM Batch Pre-Screen (1 call per batch)
# ===================================================================

_BATCH_PROMPT = """以下のメール一覧から、**自分が応募した企業からの直接連絡**のみを就活関連と判別してください。

✅ 就活関連メール（通過させる）:
- 企業の採用担当者からの選考案内、面接通知、結果通知
- 企業のマイページ登録・ES提出・Webテスト案内
- 企業からの説明会・インターンシップ案内（自分宛て）
- 内定通知、お祈りメール
- エントリー受付確認（自分が応募したもの）

❌ 就活に関係ないメール（フィルタする）:
- **就活サイトからの一括推薦・おすすめ求人メール**（マイナビ、リクナビ、doda、ワンキャリア、キャリタス等からの「おすすめ企業」「新着求人」「あなたへの推薦」）
- **就活サイトからのイベント一覧・合同説明会の広告メール**
- **就活サイトのニュースレター、コラム、就活Tips**
- 広告、セール、クーポン
- SNS通知、アプリ通知
- 配送、注文確認
- サービス利用規約変更

⚠️ 重要な判断基準:
- 送信者が「noreply@」「info@」「mail@」等の一般アドレスで、件名に「おすすめ」「ピックアップ」「新着」「推薦」「〇〇選」等を含む → フィルタ
- 送信者が特定の企業名で、件名に「選考」「面接」「ES」「説明会」等を含む → 通過

JSON形式のみで回答してください:
{{"job_related_ids": ["email_0", "email_3"]}}

--- メール一覧 ---
{email_list}
"""


def layer2_batch_prescreen(emails: list[dict], batch_size: int = 8) -> tuple[list[dict], list[dict]]:
    """Send emails to LLM in batches for quick binary job-relevance classification.

    Args:
        emails: List of email dicts (already passed Layer 1).
        batch_size: Number of emails per batch (default: 8).

    Returns:
        (job_related, non_job) — classified email lists.
    """
    from ai import call_llm, is_ai_configured, clean_json_response

    if not is_ai_configured():
        logger.debug("[email_filter] AI not configured, passing all emails through")
        return emails, []

    if not emails:
        return [], []

    job_related = []
    non_job = []

    # Process in batches
    for i in range(0, len(emails), batch_size):
        batch = emails[i:i + batch_size]
        email_list_str = ""

        for idx, email in enumerate(batch):
            email_id = f"email_{idx}"
            sender = (email.get('sender', '') or '')[:60]
            subject = (email.get('subject', '') or '')[:80]
            body_preview = (email.get('body_preview', '') or '')[:150]
            email_list_str += f"\n[{email_id}]\n送信者: {sender}\n件名: {subject}\n本文冒頭: {body_preview}\n"

        prompt = _BATCH_PROMPT.format(email_list=email_list_str)

        try:
            raw = call_llm(prompt, priority=2, workflow='email',
                          temperature=0.1, max_tokens=512)
            cleaned = clean_json_response(raw)
            result = json.loads(cleaned)
            related_ids = set(result.get('job_related_ids', []))

            for idx, email in enumerate(batch):
                email_id = f"email_{idx}"
                if email_id in related_ids:
                    job_related.append(email)
                else:
                    non_job.append(email)

            logger.info(f"[email_filter] Layer 2 batch {i//batch_size + 1}: "
                       f"{len(related_ids)}/{len(batch)} marked as job-related")

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[email_filter] Layer 2 batch parse error: {e}, "
                         f"passing all {len(batch)} emails through")
            # On failure, pass all through to Layer 3 (safe fallback)
            job_related.extend(batch)

    return job_related, non_job


# ===================================================================
# Layer 3: Deep Analysis (existing email_parser)
# ===================================================================

def layer3_deep_analysis(emails: list[dict]) -> list[dict]:
    """Run full AI analysis on each email using the existing parser.

    Args:
        emails: List of email dicts that passed Layers 1+2.

    Returns:
        List of email dicts enriched with AI analysis results.
    """
    from ai.email_parser import parse_email_with_ai

    results = []
    for email in emails:
        try:
            ai_result = parse_email_with_ai(
                subject=email.get('subject', ''),
                sender=email.get('sender', ''),
                body=email.get('body_preview', '') or email.get('body', ''),
            )
            enriched = {**email}
            if ai_result:
                enriched['ai_analysis'] = ai_result
                enriched['is_job_related'] = ai_result.get('is_job_related', False)
            else:
                enriched['ai_analysis'] = None
                enriched['is_job_related'] = False
            results.append(enriched)

        except Exception as e:
            logger.warning(f"[email_filter] Layer 3 analysis failed for "
                         f"'{email.get('subject', '?')[:40]}': {e}")
            results.append({**email, 'ai_analysis': None, 'is_job_related': False})

    job_count = sum(1 for r in results if r.get('is_job_related'))
    logger.info(f"[email_filter] Layer 3: {job_count}/{len(results)} "
               f"confirmed as job-related after deep analysis")

    return results


# ===================================================================
# Main Pipeline Entry Point
# ===================================================================

def filter_emails(emails: list[dict], skip_layer2: bool = False) -> dict:
    """Run the full 3-tier email filtering pipeline.

    Args:
        emails: Raw list of email dicts from Gmail.
        skip_layer2: If True, skip LLM batch pre-screening (useful if
                     very few emails or AI not configured).

    Returns:
        dict with keys:
            'job_related': list of emails confirmed as job-related (with AI analysis)
            'filtered_l1': list filtered by Layer 1 (regex)
            'filtered_l2': list filtered by Layer 2 (LLM batch)
            'non_job_l3': list that Layer 3 determined as not job-related
            'stats': dict with filtering statistics
    """
    total = len(emails)
    logger.info(f"[email_filter] Starting pipeline with {total} emails")

    if not emails:
        return {
            'job_related': [],
            'filtered_l1': [],
            'filtered_l2': [],
            'non_job_l3': [],
            'stats': {'total': 0, 'l1_filtered': 0, 'l2_filtered': 0,
                     'l3_job': 0, 'l3_non_job': 0},
        }

    # Layer 1: Regex
    passed_l1, filtered_l1 = layer1_regex_filter(emails)

    # Layer 2: LLM batch (optional)
    if skip_layer2 or len(passed_l1) <= 3:
        # Few enough emails to skip batch step
        passed_l2 = passed_l1
        filtered_l2 = []
    else:
        passed_l2, filtered_l2 = layer2_batch_prescreen(passed_l1)

    # Layer 3: Deep analysis
    analyzed = layer3_deep_analysis(passed_l2)

    job_related = [e for e in analyzed if e.get('is_job_related')]
    non_job_l3 = [e for e in analyzed if not e.get('is_job_related')]

    stats = {
        'total': total,
        'l1_filtered': len(filtered_l1),
        'l2_filtered': len(filtered_l2),
        'l3_job': len(job_related),
        'l3_non_job': len(non_job_l3),
    }

    logger.info(f"[email_filter] Pipeline complete: {stats}")

    return {
        'job_related': job_related,
        'filtered_l1': filtered_l1,
        'filtered_l2': filtered_l2,
        'non_job_l3': non_job_l3,
        'stats': stats,
    }
