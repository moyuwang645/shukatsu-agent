"""キャリタス就活 (career-tasu.jp) scraper — public pages, no login required."""
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup
from .base import BaseScraper

logger = logging.getLogger(__name__)

CAREER_TASU_BASE = "https://job.career-tasu.jp"
# condition-search → company search by keyword
CAREER_TASU_SEARCH_URL = f"{CAREER_TASU_BASE}/condition-search/result/"
# employment-search → employment/recruitment info search
CAREER_TASU_EMPLOYMENT_URL = f"{CAREER_TASU_BASE}/employment-search/result/"


class CareerTasuScraper(BaseScraper):
    """Scraper for キャリタス就活 (career-tasu.jp).

    Public listings — no login required.
    Fetches companies from keyword search and employment search,
    filters to deadlines within 3 days.
    """

    def __init__(self):
        super().__init__('career_tasu')

    async def login(self) -> bool:
        """No login needed for public listings."""
        return True

    async def fetch_jobs(self) -> list:
        """Fetch employment listings from キャリタス就活.

        Uses the employment search page. Deadline filtering is NOT applied here
        because deadlines are extracted by AI enrichment (which runs after this).
        """
        all_jobs = []

        logger.info("[career_tasu] Fetching employment listings...")

        # Fetch employment search results (up to 3 pages)
        for page_num in range(1, 4):
            url = f"{CAREER_TASU_EMPLOYMENT_URL}?tcd=PickKwd"
            if page_num > 1:
                url += f"&page={page_num}"

            try:
                resp = await self.page.context.request.get(url, timeout=20000)
                if not resp.ok:
                    logger.warning(f"[career_tasu] Page {page_num} returned {resp.status}")
                    break
                html = await resp.text()
            except Exception as e:
                logger.error(f"[career_tasu] Failed to fetch page {page_num}: {e}")
                break

            soup = BeautifulSoup(html, 'html.parser')
            items = self._extract_company_items(soup)
            logger.info(f"[career_tasu] Page {page_num}: {len(items)} companies")

            if not items:
                break

            all_jobs.extend(items)

        # Fetch company names from detail pages (AI handles everything else)
        if all_jobs:
            logger.info(f"[career_tasu] Fetching company names for {len(all_jobs)} companies...")
            chunk_size = 10
            for i in range(0, len(all_jobs), chunk_size):
                chunk = all_jobs[i:i + chunk_size]
                tasks = [self._fetch_detail(job.get('job_url', '')) for job in chunk]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for job, detail in zip(chunk, results):
                    if isinstance(detail, dict) and detail.get('company_name'):
                        job['company_name'] = detail['company_name']
                        job['company_name_jp'] = detail['company_name']
                await self.page.wait_for_timeout(300)

        logger.info(f"[career_tasu] Found {len(all_jobs)} companies from employment listings")
        return all_jobs

    async def search_jobs(self, keywords: list, filters: dict = None) -> list:
        """Search キャリタス就活 for companies matching keywords."""
        all_jobs = []
        seen_ids = set()

        for keyword in keywords:
            logger.info(f"[career_tasu] Searching for keyword: '{keyword}'")
            items = []

            # Search via condition-search
            for page_num in range(1, 4):
                import urllib.parse
                kw_encoded = urllib.parse.quote(keyword, safe='')
                url = f"{CAREER_TASU_SEARCH_URL}?keyword={kw_encoded}&tcd=PickKwd"
                if page_num > 1:
                    url += f"&page={page_num}"

                try:
                    resp = await self.page.context.request.get(url, timeout=20000)
                    if not resp.ok:
                        logger.warning(f"[career_tasu] Search page {page_num} returned {resp.status}")
                        break
                    html = await resp.text()
                except Exception as e:
                    logger.error(f"[career_tasu] Search failed for '{keyword}' page {page_num}: {e}")
                    break

                soup = BeautifulSoup(html, 'html.parser')
                page_items = self._extract_company_items(soup)
                logger.info(f"[career_tasu] Keyword '{keyword}' page {page_num}: {len(page_items)} companies")

                if not page_items:
                    break
                items.extend(page_items)

            # Deduplicate
            new_items = []
            for job in items:
                sid = job.get('source_id')
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    job['notes'] = f"キーワード検索: {keyword}"
                    new_items.append(job)

            # Fetch company names from detail pages (AI handles everything else)
            if new_items:
                logger.info(f"[career_tasu] Fetching company names for {len(new_items)} companies...")
                chunk_size = 10
                for i in range(0, len(new_items), chunk_size):
                    chunk = new_items[i:i + chunk_size]
                    tasks = [self._fetch_detail(job.get('job_url', '')) for job in chunk]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for job, detail in zip(chunk, results):
                        if isinstance(detail, dict) and detail.get('company_name'):
                            job['company_name'] = detail['company_name']
                            job['company_name_jp'] = detail['company_name']
                    await self.page.wait_for_timeout(300)

            all_jobs.extend(new_items)

        logger.info(f"[career_tasu] Search complete: {len(all_jobs)} total companies")
        return all_jobs

    # Words that indicate a line is NOT a company name
    _SKIP_WORDS = [
        'フォロー', 'インターン', '従業員', '資本金', '売上高',
        '福利厚生', '初任給', '平均', '募集職種', '株式上場',
        'はたらく', '非上場', '上場', 'フォロワー', 'エントリー',
        '本選考', '説明会', '検索する', '注目キーワード', '職種別',
        '勤務地', 'を問わない', '万円', '年間', '月間',
        '#', '住宅手当', '社宅', '育児', '介護',
    ]
    # Suffixes that strongly indicate a company name
    _COMPANY_SUFFIXES = [
        '株式会社', '(株)', '（株）', 'グループ', '有限会社',
        '合同会社', '一般社団法人', '一般財団法人', '公益社団法人',
    ]

    def _extract_company_items(self, soup: BeautifulSoup) -> list:
        """Extract company items from a search results page.

        Company links follow the pattern: /corp/{8-digit-id}/default/
        """
        items = []
        seen = set()

        for a in soup.find_all('a', href=re.compile(r'/corp/\d+/default/')):
            href = a.get('href', '')
            match = re.search(r'/corp/(\d+)/default/', href)
            if not match:
                continue
            corp_id = match.group(1)
            if corp_id in seen:
                continue

            # -- Extract company name --
            company_name = self._extract_name_from_link(a)
            if not company_name or len(company_name) < 2:
                continue

            seen.add(corp_id)

            # -- Extract industry (lines with ｜ separator) --
            industry = ""
            location = ""
            text = a.get_text(separator='\n', strip=True)
            for line in text.split('\n'):
                line = line.strip()
                if '｜' in line and len(line) < 80:
                    industry = line
                    # Often starts with prefecture: "東京都ソフトウェア｜..."
                    pref_match = re.match(
                        r'^(北海道|東京都|大阪府|京都府|'
                        r'[一-龥]{2,3}県)', line)
                    if pref_match:
                        location = pref_match.group(1)
                    break

            full_url = f"{CAREER_TASU_BASE}/corp/{corp_id}/default/"

            items.append({
                'company_name': company_name,
                'company_name_jp': company_name,
                'source': 'career_tasu',
                'source_id': f"career_tasu_{corp_id}",
                'job_url': full_url,
                'status': 'interested',
                'industry': industry,
                'location': location,
                'notes': '',
            })

        return items

    def _extract_name_from_link(self, a) -> str:
        """Extract company name from an <a> element.

        Strategy:
          1. Collect all text lines from the link.
          2. Filter out junk (numbers, locations, keywords, etc.)
          3. Prefer lines containing company suffixes (株式会社 etc.)
          4. Fall back to longest remaining candidate.
        """
        text = a.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        candidates = []
        for line in lines:
            # Skip very short or very long lines
            if len(line) < 3 or len(line) > 60:
                continue
            # Skip lines with junk keywords
            if any(sw in line for sw in self._SKIP_WORDS):
                continue
            # Skip lines that are just numbers/ratings
            if re.match(r'^[\d.,]+$', line):
                continue
            # Skip pure location lines (just a prefecture name)
            if re.match(
                r'^(北海道|東京都|大阪府|京都府|[一-龥]{2,3}県)$', line):
                continue
            # Skip industry lines with ｜
            if '｜' in line:
                continue
            candidates.append(line)

        if not candidates:
            return ""

        # Prefer lines containing a company suffix
        for c in candidates:
            if any(sfx in c for sfx in self._COMPANY_SUFFIXES):
                return self._clean_company_name(c)

        # Otherwise return the first reasonable candidate
        return self._clean_company_name(candidates[0])

    @staticmethod
    def _clean_company_name(name: str) -> str:
        """Remove common suffixes from company names."""
        for sfx in ['の企業情報', 'の採用情報', 'のインターンシップ',
                    'の会社情報', ' 企業情報', ' 採用情報']:
            if name.endswith(sfx):
                name = name[:-len(sfx)].strip()
                break
        return name

    async def _fetch_detail(self, url: str) -> dict:
        """Fetch company default page and extract company name only.

        All other fields (salary, position, location, benefits, culture, etc.)
        are extracted by AI via the decoupled detail_enrich_service.
        """
        result = {'company_name': None}
        if not url:
            return result

        try:
            resp = await self.page.context.request.get(url, timeout=15000)
            if not resp.ok:
                return result
            html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')

            # ── Company name from OG:title or <title> ──
            for tag_source in [
                soup.find('meta', property='og:title'),
                soup.find('title'),
            ]:
                if tag_source:
                    raw = (tag_source.get('content', '') if tag_source.name == 'meta'
                           else tag_source.get_text(strip=True))
                    for sep in ['|', '｜', ' - ', ' – ']:
                        if sep in raw:
                            name = raw.split(sep)[0].strip()
                            if name and len(name) >= 2:
                                result['company_name'] = self._clean_company_name(name)
                                break
                    if result['company_name']:
                        break

        except Exception as e:
            logger.debug(f"[career_tasu] Detail fetch error for {url}: {e}")

        return result

    async def _get_combined_detail_text(self, job_url: str) -> str:
        """Fetch and combine text from default page + employment page.

        Returns cleaned text suitable for AI analysis (up to 5000 chars).
        """
        combined_parts = []

        # 1. Default page text
        default_text = await self.fetch_detail_text(job_url)
        if default_text:
            combined_parts.append("=== 企業ページ ===\n" + default_text)

        # 2. Employment page text
        corp_match = re.search(r'/corp/(\d+)/', job_url)
        if corp_match:
            corp_id = corp_match.group(1)
            emp_url = f"{CAREER_TASU_BASE}/corp/{corp_id}/employment/"
            emp_text = await self.fetch_detail_text(emp_url)
            if emp_text:
                combined_parts.append("=== 採用情報ページ ===\n" + emp_text)

        combined = '\n\n'.join(combined_parts)
        return combined[:6000] if combined else ''



    def _extract_first_date(self, text: str) -> str | None:
        """Extract the first recognisable date from text."""
        if not text:
            return None

        patterns = [
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日', 'ymd'),
            (r'(\d{4})/(\d{1,2})/(\d{1,2})', 'ymd_slash'),
            (r'(\d{1,2})月(\d{1,2})日', 'md'),
            (r'(\d{1,2})/(\d{1,2})', 'md_slash'),
        ]

        for pattern, fmt in patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    if fmt == 'ymd':
                        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    elif fmt == 'ymd_slash':
                        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    elif fmt in ('md', 'md_slash'):
                        mo, d = int(m.group(1)), int(m.group(2))
                        now = datetime.now()
                        year = now.year if mo >= now.month else now.year + 1
                        return f"{year}-{mo:02d}-{d:02d}"
                except Exception:
                    pass
        return None


def run_career_tasu_scraper():
    """Synchronous entry point for the scheduler."""
    scraper = CareerTasuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run())
    finally:
        loop.close()


def run_career_tasu_search(keywords: list, filters: dict = None, max_results: int = 0,
                           company_keyword: str = ''):
    """Synchronous wrapper to run a keyword search on キャリタス就活."""
    scraper = CareerTasuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run_search(
            keywords, filters, max_results=max_results,
            company_keyword=company_keyword))
    finally:
        loop.close()
