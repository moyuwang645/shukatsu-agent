"""OpenWork cache CRUD operations."""
import json
from datetime import datetime
from . import get_db


def cache_openwork_data(company_name: str, overall_score: float,
                        sub_scores: dict, review_summary: str = '') -> int:
    """Cache OpenWork data for a company. Upserts (insert or update)."""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    sub_scores_json = json.dumps(sub_scores, ensure_ascii=False) if sub_scores else None

    # Try update first
    cursor.execute(
        "SELECT id FROM openwork_cache WHERE company_name = ?",
        (company_name,)
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute('''
            UPDATE openwork_cache
            SET overall_score = ?, sub_scores = ?, review_summary = ?, fetched_at = ?
            WHERE company_name = ?
        ''', (overall_score, sub_scores_json, review_summary, now, company_name))
        cache_id = existing['id']
    else:
        cursor.execute('''
            INSERT INTO openwork_cache (company_name, overall_score, sub_scores,
                                        review_summary, fetched_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (company_name, overall_score, sub_scores_json, review_summary, now))
        cache_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return cache_id


def get_openwork_data(company_name: str) -> dict | None:
    """Get cached OpenWork data for a company."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM openwork_cache WHERE company_name = ?",
        (company_name,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    # Parse sub_scores JSON back to dict
    if result.get('sub_scores'):
        try:
            result['sub_scores'] = json.loads(result['sub_scores'])
        except json.JSONDecodeError:
            result['sub_scores'] = {}
    return result


def is_cache_fresh(company_name: str, max_age_days: int = 7) -> bool:
    """Check if cached data is still fresh (within max_age_days)."""
    conn = get_db()
    row = conn.execute('''
        SELECT fetched_at FROM openwork_cache
        WHERE company_name = ?
          AND fetched_at >= datetime('now', '-' || ? || ' days')
    ''', (company_name, max_age_days)).fetchone()
    conn.close()
    return row is not None


def get_all_cached_companies() -> list:
    """Get all cached company data."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM openwork_cache ORDER BY fetched_at DESC"
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        if r.get('sub_scores'):
            try:
                r['sub_scores'] = json.loads(r['sub_scores'])
            except json.JSONDecodeError:
                r['sub_scores'] = {}
        results.append(r)
    return results


def delete_openwork_cache(company_name: str):
    """Delete cached data for a company."""
    conn = get_db()
    conn.execute("DELETE FROM openwork_cache WHERE company_name = ?", (company_name,))
    conn.commit()
    conn.close()
