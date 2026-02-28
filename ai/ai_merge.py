"""Unified AI Merge — single entry point for all data creation and update.

Every data operation in the system is expressed as:
    ai_merge(existing_state, new_data, source, mode, constraints) → merged

Where existing_state=None means create a new record (∅ → card).

Modes:
    AI:     LLM judges which fields to merge/keep  (default if AI available)
    DIRECT: Rule-based merge without LLM (existing wins, fill blanks)
    AUTO:   Try AI first, fallback to DIRECT on failure
"""
import json
import logging

logger = logging.getLogger(__name__)


# ── Merge modes ──────────────────────────────────────────────────────

class MergeMode:
    AI = 'ai'
    DIRECT = 'direct'
    AUTO = 'auto'


# ── Default field constraints ────────────────────────────────────────

DEFAULT_CONSTRAINTS = {
    # Never modified after creation
    'locked': ['id', 'source', 'created_at'],

    # Set once; not overwritten unless empty (or force=True)
    'write_once': ['job_url', 'source_id', 'company_name', 'company_name_jp'],

    # New data can replace if more detailed
    'updatable': [
        'position', 'salary', 'location', 'industry',
        'job_description', 'deadline', 'company_business',
        'company_culture', 'job_type', 'notes',
    ],

    # Only written by the scoring pipeline (job_enricher), never by merge
    'ai_only': ['match_score', 'tags', 'ai_enriched', 'ai_summary'],
}


# ── Public API ───────────────────────────────────────────────────────

def ai_merge(
    existing: dict | None,
    new_data: dict,
    data_source: str = '',
    mode: str = MergeMode.AUTO,
    prompt_key: str = '',
    constraints: dict | None = None,
) -> dict:
    """Unified merge function.

    Args:
        existing: Current card data (None = creating a new record).
        new_data: Incoming data to merge.
        data_source: Label for the source ('email', 'career_tasu', etc.)
        mode: 'ai' | 'direct' | 'auto'
        prompt_key: Key to load mode-specific prompt (e.g., 'backfill',
                    'detail', 'email'). Maps to prompts/merge_{key}.txt.
                    If empty, uses data_source as key.
        constraints: Field constraint rules (None = use DEFAULT_CONSTRAINTS)

    Returns:
        Merged dict ready for DB upsert.
    """
    if constraints is None:
        constraints = DEFAULT_CONSTRAINTS

    # Normalize: treat None as empty card
    base = dict(existing) if existing else {}

    if mode == MergeMode.DIRECT:
        return _direct_merge(base, new_data, data_source, constraints)

    if mode == MergeMode.AI:
        return _ai_merge(base, new_data, data_source,
                         prompt_key or data_source, constraints)

    # AUTO: try AI, fallback to DIRECT
    from ai import is_ai_configured
    if not is_ai_configured():
        logger.debug('[ai_merge] AI not configured, using DIRECT mode')
        return _direct_merge(base, new_data, data_source, constraints)

    try:
        result = _ai_merge(base, new_data, data_source,
                           prompt_key or data_source, constraints)
        if result:
            return result
    except Exception as e:
        logger.warning(f'[ai_merge] AI merge failed ({e}), fallback to DIRECT')

    return _direct_merge(base, new_data, data_source, constraints)


# ── DIRECT merge (rule-based, no LLM) ───────────────────────────────

def _direct_merge(
    base: dict,
    new_data: dict,
    data_source: str,
    constraints: dict,
) -> dict:
    """Rule-based merge: existing values win, fill blanks from new_data.

    Rules:
        - locked fields: never touched
        - write_once fields: set only if currently empty
        - updatable fields: set if currently empty OR new value is longer
        - ai_only fields: skip entirely
        - source field: set to data_source only if creating new (base is empty)
    """
    result = dict(base)
    locked = set(constraints.get('locked', []))
    write_once = set(constraints.get('write_once', []))
    ai_only = set(constraints.get('ai_only', []))
    skip = locked | ai_only

    is_new = not base  # creating new record

    for key, new_val in new_data.items():
        if key in skip:
            continue

        # Normalize empty-ish values
        if new_val is None or (isinstance(new_val, str) and
                               new_val.strip() in ('', 'なし', 'null', 'None')):
            continue

        current = result.get(key)
        current_empty = (
            current is None or
            (isinstance(current, str) and
             current.strip() in ('', 'なし', 'null', 'None'))
        )

        if key in write_once:
            if current_empty:
                result[key] = new_val
        else:
            # updatable: fill if empty, or replace if new is more detailed
            if current_empty:
                result[key] = new_val
            elif (isinstance(new_val, str) and isinstance(current, str) and
                  len(new_val.strip()) > len(current.strip()) * 1.5):
                # New value is significantly longer → likely more detailed
                result[key] = new_val

    # Set source for new cards
    if is_new and 'source' not in result:
        result['source'] = data_source

    return result


# ── AI merge (LLM-powered, modular prompts) ─────────────────────────

def _ai_merge(
    base: dict,
    new_data: dict,
    data_source: str,
    prompt_key: str,
    constraints: dict,
) -> dict | None:
    """AI-powered merge with modular prompt composition.

    Prompt = mode-specific instructions + shared constraints + data section.
    Mode-specific prompts are loaded from prompts/merge_{prompt_key}.txt.
    """
    from ai import call_llm, clean_json_response
    from ai.prompt_loader import get_prompt

    # Filter to relevant fields only (skip internal/meta fields)
    relevant_keys = set()
    for cat in ('write_once', 'updatable'):
        relevant_keys.update(constraints.get(cat, []))

    def _filter(d: dict) -> dict:
        return {k: v for k, v in d.items()
                if k in relevant_keys and v and
                str(v).strip() not in ('', 'なし', 'null', 'None')}

    existing_filtered = _filter(base) if base else {}
    new_filtered = _filter(new_data)

    if not new_filtered:
        logger.debug('[ai_merge] No new data to merge')
        return base if base else {}

    is_new = not base

    # ── Section 1: Mode-specific prompt ──
    mode_prompt = get_prompt(
        f'merge_{prompt_key}',
        _DEFAULT_MODE_PROMPTS.get(prompt_key, _FALLBACK_MODE_PROMPT),
    )

    # ── Section 2: Shared constraints ──
    constraint_section = _SHARED_CONSTRAINTS.format(
        updatable_fields=', '.join(constraints.get('updatable', [])),
        write_once_fields=', '.join(constraints.get('write_once', [])),
    )

    # ── Section 3: Data section ──
    data_section = _DATA_TEMPLATE.format(
        existing_json=json.dumps(existing_filtered, ensure_ascii=False, indent=2)
                      if existing_filtered else '{}  (新規作成)',
        new_data_json=json.dumps(new_filtered, ensure_ascii=False, indent=2),
        data_source=data_source,
    )

    # Compose final prompt
    prompt = f"{mode_prompt}\n\n{constraint_section}\n\n{data_section}"

    try:
        raw = call_llm(prompt, priority=2, workflow='job',
                       temperature=0.3, max_tokens=2048)
        cleaned = clean_json_response(raw)
        ai_result = json.loads(cleaned)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f'[ai_merge] AI parse error: {e}')
        return None

    # Apply AI result with constraint enforcement
    result = dict(base)
    locked = set(constraints.get('locked', []))
    ai_only = set(constraints.get('ai_only', []))
    write_once = set(constraints.get('write_once', []))

    for key, val in ai_result.items():
        if key in locked or key in ai_only:
            continue
        if val is None or (isinstance(val, str) and
                           val.strip() in ('', 'なし', 'null', 'None')):
            continue

        current = result.get(key)
        current_empty = (
            current is None or
            (isinstance(current, str) and
             current.strip() in ('', 'なし', 'null', 'None'))
        )

        if key in write_once and not current_empty:
            continue  # write_once: don't overwrite

        result[key] = val

    # Set source for new cards
    if is_new and 'source' not in result:
        result['source'] = data_source

    logger.info(
        f'[ai_merge] {"Created" if is_new else "Updated"} card '
        f'(prompt=merge_{prompt_key}, source={data_source}, '
        f'fields={list(ai_result.keys())})'
    )
    return result


# ── Prompt sections ──────────────────────────────────────────────────

# Section 2: Shared constraint rules (always appended)
_SHARED_CONSTRAINTS = """=== 統合ルール（共通） ===
1. 既存データの値を優先する（情報が豊富な方を残す）
2. 既存データが空のフィールドは新規データで補完する
3. 新規データの方が明らかに詳細な場合（文字数が1.5倍以上）は更新してよい
4. 矛盾がある場合は既存データを優先する
5. 企業名は正式法人名（株式会社○○）を優先する

更新可能フィールド: {updatable_fields}
書き込み一回限りフィールド（空の場合のみ設定可能）: {write_once_fields}

=== 出力形式 ===
統合結果をJSON形式のみで回答してください。
コードフェンスや説明文は不要です。
フィールド値が不明な場合は含めないでください。"""

# Section 3: Data template (always appended)
_DATA_TEMPLATE = """=== 既存データ ===
{existing_json}

=== 新規データ（ソース: {data_source}） ===
{new_data_json}"""

# Fallback for unknown prompt_key
_FALLBACK_MODE_PROMPT = """あなたは求人情報統合アシスタントです。
既存の求人データと新しいデータを統合してください。"""

# Default mode-specific prompts (overridable via prompts/merge_{key}.txt)
_DEFAULT_MODE_PROMPTS = {
    'backfill': """あなたは求人情報統合アシスタントです。
メールから作成された求人カードに、爬虫（スクレイパー）から取得したデータを統合します。

【このモードの特別ルール】
- メール由来の情報を最優先する
- 爬虫データは「補完」目的のみ — 既存の値を上書きしない
- 企業名が微妙に異なる場合は正式法人名を選択する
- job_url は爬虫データから採用してよい（メールカードには通常ない）""",

    'detail': """あなたは求人情報統合アシスタントです。
既存の求人カードに、企業の採用ページから抽出した詳細情報を統合します。

【このモードの特別ルール】
- 採用ページの情報は信頼性が高い（公式サイト由来）
- 職種・給与・勤務地は採用ページの情報が正確
- 既に値があるフィールドでも、採用ページの情報がより具体的なら更新可
- 企業概要・社風情報は積極的に取り込む""",

    'email': """あなたは求人情報統合アシスタントです。
メールから解析された情報で新しい求人カードを作成します。

【このモードの特別ルール】
- メールの情報のみで構成する（外部データなし）
- 企業名は正式法人名を使用する（株式会社○○）
- 日程情報は正確に抽出する""",
}

