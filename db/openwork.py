"""OpenWork cache CRUD operations."""
import json
from datetime import datetime
from . import get_db_connection, get_db_read


def cache_openwork_data(company_name: str, overall_score: float,
                        sub_scores: dict, review_summary: str = '') -> int:
    """Cache OpenWork data for a company. Upserts (insert or update)."""
    now = datetime.now().isoformat()
    sub_scores_json = json.dumps(sub_scores, ensure_ascii=False) if sub_scores else None

    with get_db_connection() as conn:
        cursor = conn.cursor()
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
    return cache_id


def get_openwork_data(company_name: str) -> dict | None:
    """Get cached OpenWork data for a company."""
    with get_db_read() as conn:
        row = conn.execute(
            "SELECT * FROM openwork_cache WHERE company_name = ?",
            (company_name,)
        ).fetchone()
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
    with get_db_read() as conn:
        row = conn.execute('''
            SELECT fetched_at FROM openwork_cache
            WHERE company_name = ?
              AND fetched_at >= datetime('now', '-' || ? || ' days')
        ''', (company_name, max_age_days)).fetchone()
    return row is not None


def get_all_cached_companies() -> list:
    """Get all cached company data."""
    with get_db_read() as conn:
        rows = conn.execute(
            "SELECT * FROM openwork_cache ORDER BY fetched_at DESC"
        ).fetchall()
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
    with get_db_connection() as conn:
        conn.execute("DELETE FROM openwork_cache WHERE company_name = ?", (company_name,))
        conn.commit()
