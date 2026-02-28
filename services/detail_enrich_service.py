"""Detail Enrich Service — fetch detail pages and run AI analysis.

Decoupled from the scraper pipeline. Receives a job_id, fetches the
detail page(s) via HTTP GET (no browser needed), calls AI to extract
structured fields, and updates the existing DB record.

Per-site URL strategies are used to fetch multiple pages for richer AI input.
Always UPDATES existing records — never creates new ones.
"""
import logging
import re
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Fields to extract from detail pages
_COMPLETENESS_FIELDS = ('position', 'location', 'industry', 'job_description')

# Timeout for HTTP requests
_HTTP_TIMEOUT = 15

# ── Per-site URL strategies ──────────────────────────────────────────
# Each function returns a list of (label, url) tuples for pages to fetch.

def _mynavi_urls(job_url: str) -> list:
    """MyNavi: outline + employment pages."""
    urls = []
    urls.append(('企業概要', job_url.rstrip('/') + '/outline.html'))

    corp_match = re.search(r'corp(\d+)', job_url)
    if corp_match:
        corp_id = corp_match.group(1)
        urls.append(('採用情報', f"https://job.mynavi.jp/27/pc/corpinfo/displayEmployment/index?corpId={corp_id}"))
    return urls


def _career_tasu_urls(job_url: str) -> list:
    """CareerTasu: default page + employment page."""
    urls = [('企業ページ', job_url)]
    corp_match = re.search(r'/corp/(\d+)/', job_url)
    if corp_match:
        corp_id = corp_match.group(1)
        urls.append(('採用情報', f"https://job.career-tasu.jp/corp/{corp_id}/employment/"))
    return urls


def _onecareer_urls(job_url: str) -> list:
    """OneCareer: event/selection page + company page.

    The scraper saves job_url as the event page (e.g. /events/82159 or
    /events/selection/82159). This page already contains rich hiring info
    (選考フロー, 募集要項, deadlines).

    Strategy:
    1. Include the event page (job_url) — has hiring details
    2. Determine company ID from URL or by fetching event page HTML
    3. Include company page — has company overview and location
    """
    base = "https://www.onecareer.jp"
    urls = []

    # Determine company ID from job_url
    company_id = ''
    company_match = re.search(r'/companies/(\d+)', job_url)
    if company_match:
        company_id = company_match.group(1)

    # If job_url is an event page, add it and extract company ID from HTML
    event_match = re.search(r'/events/', job_url)
    if event_match:
        urls.append(('本選考/イベント', job_url))

        if not company_id:
            # Fetch event page to find company ID
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept-Language': 'ja,en;q=0.9',
                }
                resp = requests.get(job_url, headers=headers, timeout=_HTTP_TIMEOUT)
                if resp.ok:
                    cid_match = re.search(r'/companies/(\d+)', resp.text)
                    if cid_match:
                        company_id = cid_match.group(1)
            except Exception:
                pass

    # Add company page for overview + location info
    if company_id:
        urls.append(('企業情報', f"{base}/companies/{company_id}"))
    elif not urls:
        # Fallback: use job_url as-is
        urls.append(('詳細', job_url))

    return urls


def _engineer_shukatu_urls(job_url: str) -> list:
    """Engineer Shukatu: company top + recruitment info + job detail (3 pages)."""
    urls = []
    base = "https://engineer-shukatu.jp"

    company_match = re.search(r'company-(\d+)', job_url)
    if company_match:
        cid = company_match.group(1)
        urls.append(('企業TOP', f"{base}/company-{cid}/"))
        urls.append(('採用情報', f"{base}/company-anken-{cid}/"))
    else:
        urls.append(('詳細', job_url))

    return urls


def _gaishishukatsu_urls(job_url: str) -> list:
    """Gaishishukatsu: company page."""
    urls = [('詳細', job_url)]

    # Try to get company page from URL
    company_match = re.search(r'/company/(\d+)', job_url)
    if company_match:
        cid = company_match.group(1)
        urls = [('企業情報', f"https://gaishishukatsu.com/company/{cid}")]

    return urls


def _default_urls(job_url: str) -> list:
    """Default: just the job_url itself."""
    return [('詳細', job_url)]


# Registry: source name → URL strategy function
_URL_STRATEGIES = {
    'mynavi': _mynavi_urls,
    'career_tasu': _career_tasu_urls,
    'onecareer': _onecareer_urls,
    'engineer_shukatu': _engineer_shukatu_urls,
    'gaishishukatsu': _gaishishukatsu_urls,
}


# ── Core functions ───────────────────────────────────────────────────

def _fetch_page_text(url: str) -> str:
    """Fetch a page via HTTP GET and return cleaned text content."""
    if not url:
        return ''
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'ja,en;q=0.9',
        }
        resp = requests.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        if resp.status_code != 200:
            logger.debug(f"[detail_enrich] HTTP {resp.status_code} for {url}")
            return ''

        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        text = soup.get_text(separator='\n', strip=True)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text[:5000]
    except Exception as e:
        logger.debug(f"[detail_enrich] fetch failed for {url}: {e}")
        return ''


def _fetch_combined_text(job_url: str, source: str) -> str:
    """Fetch multiple pages per site strategy and combine their text.

    Uses the per-site URL strategy to determine which pages to fetch,
    then combines them with section labels for better AI context.
    """
    strategy = _URL_STRATEGIES.get(source, _default_urls)
    url_list = strategy(job_url)

    parts = []
    for label, url in url_list:
        text = _fetch_page_text(url)
        if text and len(text) > 50:
            parts.append(f"=== {label} ===\n{text}")
            logger.debug(f"[detail_enrich] Fetched {label}: {len(text)} chars from {url[:60]}")

    combined = '\n\n'.join(parts)
    return combined[:8000] if combined else ''


def _is_data_complete(job: dict) -> bool:
    """Check whether a job record has all key fields filled."""
    for field in _COMPLETENESS_FIELDS:
        val = job.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            return False
    return True


def enrich_job_detail(job_id: int) -> dict:
    """Fetch detail page(s) and run AI analysis for a single job.

    This function ONLY updates existing records — never creates new ones.
    Uses per-site URL strategies to fetch multiple pages for richer context.

    Args:
        job_id: The database ID of the job to enrich.

    Returns:
        dict with: status, fields_updated, error (if any)
    """
    from db.jobs import get_job, update_job
    from ai import is_ai_configured
    from ai.job_detail_parser import parse_job_detail_with_ai

    result = {'status': 'skipped', 'fields_updated': [], 'job_id': job_id}

    # 1. Load job from DB
    job = get_job(job_id)
    if not job:
        result['status'] = 'error'
        result['error'] = f'Job {job_id} not found'
        logger.warning(f"[detail_enrich] Job {job_id} not found in DB")
        return result

    company = job.get('company_name', '?')
    source = job.get('source', '')

    # 2. Skip if already complete
    if _is_data_complete(job):
        logger.debug(f"[detail_enrich] Job {job_id} ({company}) already complete, skipping")
        return result

    # 3. Check AI configured
    if not is_ai_configured():
        result['status'] = 'skipped'
        result['error'] = 'AI not configured'
        logger.debug("[detail_enrich] AI not configured, skipping")
        return result

    # 4. Fetch detail page(s) using site-specific strategy
    url = job.get('job_url', '')
    if not url:
        result['status'] = 'error'
        result['error'] = 'No job_url'
        return result

    text = _fetch_combined_text(url, source)
    if not text or len(text) < 100:
        logger.debug(f"[detail_enrich] Text too short for {company} ({url})")
        result['status'] = 'error'
        result['error'] = 'Page text too short'
        return result

    # 5. Build existing data for AI context (only filled fields)
    existing = {k: v for k, v in job.items()
                if v and k in ('position', 'salary', 'location', 'industry',
                               'deadline', 'company_business', 'company_culture')}

    # 6. Call AI
    try:
        parsed = parse_job_detail_with_ai(
            raw_text=text,
            company_name=company,
            existing_data=existing,
        )
    except Exception as e:
        result['status'] = 'error'
        result['error'] = f'AI call failed: {e}'
        logger.warning(f"[detail_enrich] AI failed for {company}: {e}")
        return result

    if not parsed:
        result['status'] = 'error'
        result['error'] = 'AI returned None'
        return result

    # 7. Unified merge via ai_merge (DIRECT: AI already parsed, just apply rules)
    from ai.ai_merge import ai_merge, MergeMode

    if parsed.get('deadline_date') and parsed['deadline_date'] != 'なし':
        parsed['deadline'] = parsed.pop('deadline_date')

    merged = ai_merge(
        existing=dict(job),
        new_data=parsed,
        data_source='detail_page',
        mode=MergeMode.DIRECT,
        prompt_key='detail',
    )

    # Calculate which fields actually changed
    update_data = {}
    for key, val in merged.items():
        if key in ('id', 'source', 'created_at'):
            continue
        old_val = job.get(key)
        if val and val != old_val:
            update_data[key] = val

    if not update_data:
        logger.info(f"[detail_enrich] Job {job_id} ({company}): AI returned data but all fields already filled")
        result['status'] = 'no_update_needed'
        return result

    # 8. Update DB (never creates new records — update_job targets by id)
    update_job(job_id, update_data)
    result['status'] = 'success'
    result['fields_updated'] = list(update_data.keys())
    logger.info(
        f"[detail_enrich] Job {job_id} ({company}): "
        f"updated {len(update_data)} fields: {list(update_data.keys())}"
    )
    return result
