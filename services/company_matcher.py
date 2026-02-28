"""Unified company matching — single function for finding the best job match.

Consolidates the matching logic previously duplicated across:
  - event_detector.match_or_create_job() (4-pass)
  - scrapers/__init__._merge_backfill_results() (score-based)
  - company_normalizer.find_matching_job() (DB query)

Usage:
    from services.company_matcher import find_best_match, MatchResult

    result = find_best_match('株式会社テスト', jobs, url='https://...')
    if result:
        print(f"Matched {result.job['company_name']} (score={result.score})")
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse
from services.company_normalizer import normalize

logger = logging.getLogger(__name__)

# Minimum score to consider a match valid
MIN_MATCH_SCORE = 70


@dataclass
class MatchResult:
    """Result of a company matching operation."""
    job: dict           # The matched job record
    score: int          # Match confidence (0-100)
    method: str         # How the match was found


def find_best_match(
    company_name: str,
    jobs: list[dict],
    *,
    url: str = '',
    exclude_ids: set[int] | None = None,
    exclude_sources: set[str] | None = None,
    min_score: int = MIN_MATCH_SCORE,
) -> MatchResult | None:
    """Find the best matching job for a company name.

    Matching strategy (in priority order):
      1. Exact name match (score=100)
      2. Normalized name match (score=95)
      3. Domain match via URL (score=90)
      4. Substring match, only if name >= 3 chars (score=75)

    Args:
        company_name: The company name to search for.
        jobs: List of job dicts to search through.
        url: Optional URL for domain-based matching.
        exclude_ids: Job IDs to skip (e.g., self-match prevention).
        exclude_sources: Sources to skip (e.g., 'email' in backfill).
        min_score: Minimum score to return a match.

    Returns:
        MatchResult with the best match, or None if no match found.
    """
    if not company_name or not jobs:
        return None

    exclude_ids = exclude_ids or set()
    exclude_sources = exclude_sources or set()
    normalized_input = normalize(company_name)
    input_domain = _extract_domain(url)

    best: MatchResult | None = None

    for job in jobs:
        if job.get('id') in exclude_ids:
            continue
        if job.get('source') in exclude_sources:
            continue

        score = _score_match(
            company_name, normalized_input, input_domain, job
        )

        if score >= min_score and (best is None or score > best.score):
            method = _score_to_method(score)
            best = MatchResult(job=job, score=score, method=method)

            # Early exit on perfect match
            if score == 100:
                break

    if best:
        logger.debug(
            f"[matcher] Matched '{company_name}' → "
            f"'{best.job.get('company_name')}' "
            f"(score={best.score}, method={best.method})"
        )

    return best


def _score_match(
    raw_name: str,
    normalized_name: str,
    input_domain: str,
    job: dict,
) -> int:
    """Calculate match score between input and a job record."""
    job_name = job.get('company_name', '')
    job_name_jp = job.get('company_name_jp', '')

    # Pass 1: Exact name match (score=100)
    if raw_name and (raw_name == job_name or raw_name == job_name_jp):
        return 100

    # Pass 2: Normalized name match (score=95)
    if normalized_name:
        job_norm = normalize(job_name)
        job_norm_jp = normalize(job_name_jp)
        if normalized_name == job_norm or normalized_name == job_norm_jp:
            return 95

    # Pass 3: Domain match (score=90)
    if input_domain:
        job_domain = _extract_domain(job.get('job_url', ''))
        if job_domain and input_domain == job_domain:
            return 90

    # Pass 4: Substring match (score=75)
    if normalized_name and len(normalized_name) >= 3:
        if (raw_name in job_name or job_name in raw_name or
                raw_name in job_name_jp or job_name_jp in raw_name):
            return 75

    return 0


def _score_to_method(score: int) -> str:
    """Convert score to human-readable method name."""
    if score >= 100:
        return 'exact'
    if score >= 95:
        return 'normalized'
    if score >= 90:
        return 'domain'
    if score >= 70:
        return 'substring'
    return 'unknown'


def _extract_domain(url: str) -> str:
    """Extract domain from a URL for matching."""
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ''
        # Strip common prefixes
        for prefix in ('www.', 'job.', 'corp.', 'career.', 'recruit.'):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host.lower()
    except Exception:
        return ''
