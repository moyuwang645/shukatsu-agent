"""Company name normalization and cross-source matching.

Used by upsert_job_from_scraper() to detect the same company listed
on different job sites with slightly different names.

Examples:
    normalize('株式会社テスト')   → 'てすと'
    normalize('（株）テスト')     → 'てすと'
    normalize('テスト株式会社')   → 'てすと'
    normalize('ＮＴＴデータ')     → 'nttでーた'
"""
import logging
import re

logger = logging.getLogger(__name__)

# Company suffixes/prefixes to strip
_COMPANY_MARKERS = [
    '株式会社', '(株)', '（株）',
    '有限会社', '(有)', '（有）',
    '合同会社', '合名会社', '合資会社',
    '一般社団法人', '一般財団法人',
    '公益社団法人', '公益財団法人',
    '社会福祉法人', '医療法人',
    '特定非営利活動法人', 'NPO法人',
    'Co.,Ltd.', 'Co., Ltd.', 'Inc.', 'Corp.',
    'Corporation', 'Ltd.', 'LLC', 'LLP',
]

# Full-width → half-width translation table
_FW_TO_HW = str.maketrans(
    '０１２３４５６７８９'
    'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
    'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'
    '（）【】「」　',
    '0123456789'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'abcdefghijklmnopqrstuvwxyz'
    '()[]「」 '
)


def normalize(name: str) -> str:
    """Normalize a company name for comparison.

    Strips legal entity markers, normalizes width, whitespace, and case.
    Returns a lowercase, trimmed string suitable for equality comparison.
    """
    if not name:
        return ''

    n = name.strip()

    # Full-width → half-width
    n = n.translate(_FW_TO_HW)

    # Remove company legal markers (case-insensitive)
    for marker in _COMPANY_MARKERS:
        n = n.replace(marker, '')
        n = n.replace(marker.lower(), '')

    # Remove common decorations
    n = re.sub(r'[\s\u3000]+', '', n)          # All whitespace
    n = re.sub(r'[【】\[\]()「」『』]', '', n)  # Brackets
    n = re.sub(r'[・\-–—]', '', n)              # Dashes/dots

    return n.strip().lower()


def find_matching_job(company_name: str, exclude_id: int = None) -> dict | None:
    """Find an existing job record matching this company name across all sources.

    Uses normalized name comparison. Returns the matching job dict, or None.
    If exclude_id is given, that record is excluded from matching (to prevent
    self-matching during updates).
    """
    from db import get_db_connection

    target = normalize(company_name)
    if not target or len(target) < 2:
        return None

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, company_name, company_name_jp, source, source_id "
            "FROM jobs"
        ).fetchall()

        for row in rows:
            if exclude_id and row['id'] == exclude_id:
                continue

            if normalize(row['company_name']) == target:
                logger.debug(
                    f"[normalizer] Cross-source match: "
                    f"'{company_name}' ≈ '{row['company_name']}' "
                    f"(id={row['id']}, source={row['source']})"
                )
                return dict(row)

            # Also check Japanese name
            if row['company_name_jp'] and normalize(row['company_name_jp']) == target:
                logger.debug(
                    f"[normalizer] JP name match: "
                    f"'{company_name}' ≈ '{row['company_name_jp']}' "
                    f"(id={row['id']}, source={row['source']})"
                )
                return dict(row)

        return None
