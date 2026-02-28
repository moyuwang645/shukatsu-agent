"""エンジニア就活 (engineer-shukatu.jp) scraper.

Scrapes engineer job listings and events from engineer-shukatu.jp.
Static HTML site — no SPA rendering needed.
"""
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from .base import BaseScraper

logger = logging.getLogger(__name__)

ES_BASE = "https://engineer-shukatu.jp"
# New graduate job listings
JOBS_URL = f"{ES_BASE}/list.php?arr_employment%5B%5D=101"
# Events/internship listings
EVENTS_URL = f"{ES_BASE}/event_list.php"


class EngineerShukatsuScraper(BaseScraper):
    """Scraper for エンジニア就活 — IT特化新卒求人."""

    def __init__(self):
        super().__init__('engineer_shukatu')

    async def login(self) -> bool:
        """Login to engineer-shukatu.jp if credentials available."""
        import os
        email = os.getenv('ENGSHUKATU_EMAIL', '')
        password = os.getenv('ENGSHUKATU_PASSWORD', '')

        if not email or not password:
            logger.info("[eng-shukatu] No credentials — browsing as guest")
            return True

        try:
            logger.info("[eng-shukatu] Logging in...")
            await self.page.goto(
                f"{ES_BASE}/login.php",
                wait_until='domcontentloaded', timeout=15000
            )
            await self.page.wait_for_timeout(1500)

            await self.page.locator(
                'input[name="email"], input[type="email"]'
            ).first.fill(email)
            await self.page.locator(
                'input[name="password"], input[type="password"]'
            ).first.fill(password)
            await self.page.locator(
                'button[type="submit"], input[type="submit"]'
            ).first.click()
            await self.page.wait_for_timeout(3000)
            logger.info(f"[eng-shukatu] Login → {self.page.url}")
            return True
        except Exception as e:
            logger.warning(f"[eng-shukatu] Login error: {e}")
            return True

    async def fetch_jobs(self) -> list:
        """Fetch both job listings and events."""
        cutoff = date.today() + timedelta(days=3)
        today = date.today()
        all_items = []

        # Fetch job listings
        logger.info("[eng-shukatu] Fetching job listings...")
        jobs = await self._fetch_page(JOBS_URL, 'job')
        all_items.extend(jobs)

        # Fetch events
        logger.info("[eng-shukatu] Fetching events...")
        events = await self._fetch_page(EVENTS_URL, 'event')
        all_items.extend(events)

        logger.info(f"[eng-shukatu] Total extracted: {len(all_items)} listings")

        # Filter by deadline within 3 days
        filtered = []
        for item in all_items:
            dl = item.get('deadline')
            if not dl:
                continue
            try:
                dl_date = date.fromisoformat(dl)
                if today <= dl_date <= cutoff:
                    filtered.append(item)
            except ValueError:
                continue

        logger.info(
            f"[eng-shukatu] {len(filtered)} listings within 3 days "
            f"(from {len(all_items)} total)"
        )
        return filtered

    async def _fetch_page(self, url: str, page_type: str) -> list:
        """Fetch and parse a listing page."""
        try:
            await self.page.goto(
                url, wait_until='domcontentloaded', timeout=20000
            )
        except Exception as e:
            logger.error(f"[eng-shukatu] Failed to load {page_type}: {e}")
            return []

        await self.page.wait_for_timeout(2000)

        year = datetime.now().year

        if page_type == 'event':
            return await self._extract_events(year)
        else:
            return await self._extract_jobs(year)

    async def _extract_jobs(self, year: int) -> list:
        """Extract job listings from the jobs page."""
        raw = await self.page.evaluate('''() => {
            const items = [];
            // Job cards: div.list_anken_box or links to company-{id}
            const links = document.querySelectorAll('a[href*="company-"]');
            const seen = new Set();

            for (const link of links) {
                const href = link.getAttribute('href') || '';
                const m = href.match(/company-(\\d+)/);
                if (!m || seen.has(m[1])) continue;
                seen.add(m[1]);

                const cid = m[1];
                // Get containing card/box
                const card = link.closest('.list_anken_box, .rec_box, div, section')
                    || link.parentElement;
                const cardText = card ? card.textContent : link.textContent;

                // Company name: usually in a title or heading
                const titleEl = card.querySelector('h3, h4, .company_name, strong');
                const company = titleEl
                    ? titleEl.textContent.trim()
                    : link.textContent.trim();

                // Deadline pattern: YYYY年MM月DD日 or MM/DD
                let dm = '', dd = '';
                const dlMatch = cardText.match(/(\\d{4})年(\\d{1,2})月(\\d{1,2})日/);
                if (dlMatch) {
                    dm = dlMatch[2];
                    dd = dlMatch[3];
                } else {
                    const simpleMatch = cardText.match(/(\\d{1,2})\\/(\\d{1,2})/);
                    if (simpleMatch) {
                        dm = simpleMatch[1];
                        dd = simpleMatch[2];
                    }
                }

                items.push({
                    cid: cid,
                    company: company.substring(0, 50),
                    title: link.textContent.trim().substring(0, 120),
                    dm: dm,
                    dd: dd,
                    href: href,
                    type: 'job',
                });
            }
            return items;
        }''')

        return self._convert_items(raw, year, 'job')

    async def _extract_events(self, year: int) -> list:
        """Extract events from the events page."""
        raw = await self.page.evaluate('''() => {
            const items = [];
            // Event cards: links to event-{id}
            const links = document.querySelectorAll('a[href*="event-"]');
            const seen = new Set();

            for (const link of links) {
                const href = link.getAttribute('href') || '';
                const m = href.match(/event-(\\d+)/);
                if (!m || seen.has(m[1])) continue;
                seen.add(m[1]);

                const eid = m[1];
                const card = link.closest('.list_event_box, .event-box, div, section')
                    || link.parentElement;
                const cardText = card ? card.textContent : link.textContent;

                // Company name
                const titleEl = card.querySelector('h3, h4, .company_name, strong, p');
                const company = titleEl
                    ? titleEl.textContent.trim()
                    : '';

                // Event title
                const title = link.textContent.trim();

                // Date patterns
                let dm = '', dd = '';
                const dlMatch = cardText.match(/(\\d{4})年(\\d{1,2})月(\\d{1,2})日/);
                if (dlMatch) {
                    dm = dlMatch[2];
                    dd = dlMatch[3];
                } else {
                    const simpleMatch = cardText.match(/(\\d{1,2})\\/(\\d{1,2})/);
                    if (simpleMatch) {
                        dm = simpleMatch[1];
                        dd = simpleMatch[2];
                    }
                }

                items.push({
                    cid: eid,
                    company: company.substring(0, 50),
                    title: title.substring(0, 120),
                    dm: dm,
                    dd: dd,
                    href: href,
                    type: 'event',
                });
            }
            return items;
        }''')

        return self._convert_items(raw, year, 'event')

    def _convert_items(self, raw: list, year: int, item_type: str) -> list:
        """Convert raw JS data to job dicts."""
        items = []
        seen = set()
        for d in raw:
            sid = f"engshukatu_{item_type}_{d['cid']}"
            if sid in seen:
                continue
            seen.add(sid)

            deadline = None
            if d['dm'] and d['dd']:
                mo, day = int(d['dm']), int(d['dd'])
                yr = year if mo >= datetime.now().month else year + 1
                deadline = f"{yr}-{mo:02d}-{day:02d}"

            href = d['href']
            if href.startswith('/') or not href.startswith('http'):
                href = f"{ES_BASE}/{href.lstrip('/')}"

            # Extract company ID from href like /company-{ID}/
            company_id = ''
            cid_match = re.search(r'company-(\d+)', href)
            if cid_match:
                company_id = cid_match.group(1)

            status = 'イベント' if item_type == 'event' else '本選'

            items.append({
                'company_name': d['company'] or d['title'][:30],
                'company_name_jp': d['company'] or d['title'][:30],
                'source': 'engineer_shukatu',
                'source_id': sid,
                'job_url': href,
                'position': d['title'][:100],
                'status': status,
                'deadline': deadline,
                'notes': 'エンジニア就活',
                '_company_id': company_id,  # internal: for enrichment
            })

        return items

    def _build_search_url(self, filters: dict = None, page: int = 1) -> str:
        """Build list.php URL with arr_* filters, sort=new, page=N."""
        from urllib.parse import quote

        params = ['arr_employment%5B%5D=101']  # 正社員 default

        if filters:
            # arr_industry[]=SIer&arr_industry[]=AI・人工知能 ...
            for key in ['arr_industry', 'arr_occupation', 'arr_commitment', 'arr_language']:
                values = filters.get(key, [])
                for v in values:
                    params.append(f"{key}%5B%5D={quote(v)}")

        params.append('sort=new')  # 新着順
        if page > 1:
            params.append(f'page={page}')

        return f"{ES_BASE}/list.php?{'&'.join(params)}"

    async def search_jobs(self, keywords: list, filters: dict = None) -> list:
        """Search engineer-shukatu with URL filters + local keyword matching.

        Args:
            keywords: keyword strings for local text filtering.
            filters: dict with arr_industry, arr_occupation, etc.
        """
        max_pages = 5
        all_items = []
        seen = set()

        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(filters, page=page_num)
            logger.info(f"[eng-shukatu-search] Page {page_num}: {url[:100]}...")

            try:
                await self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
            except Exception as e:
                logger.error(f"[eng-shukatu-search] Failed page {page_num}: {e}")
                break

            await self.page.wait_for_timeout(2000)

            year = datetime.now().year
            page_items = await self._extract_jobs(year)

            if not page_items:
                logger.info(f"[eng-shukatu-search] No results on page {page_num}, stopping")
                break

            # Deduplicate across pages
            new_count = 0
            for item in page_items:
                sid = item['source_id']
                if sid not in seen:
                    seen.add(sid)
                    all_items.append(item)
                    new_count += 1

            logger.info(f"[eng-shukatu-search] Page {page_num}: {new_count} new items")

            if new_count == 0:
                logger.info("[eng-shukatu-search] All duplicates, stopping pagination")
                break

        # Local keyword filtering (if keywords provided)
        if keywords:
            filtered = []
            for item in all_items:
                text = f"{item.get('company_name', '')} {item.get('position', '')} {item.get('notes', '')}"
                text_lower = text.lower()
                if any(kw.lower() in text_lower for kw in keywords):
                    filtered.append(item)
            logger.info(
                f"[eng-shukatu-search] Keyword filter: {len(filtered)}/{len(all_items)} "
                f"matched [{', '.join(keywords)}]"
            )
            return filtered

        logger.info(f"[eng-shukatu-search] Total: {len(all_items)} items (no keyword filter)")
        return all_items



def run_engineer_shukatu_scraper():
    """Synchronous entry point for the scheduler."""
    scraper = EngineerShukatsuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run())
    finally:
        loop.close()


def run_engineer_shukatu_search(keywords: list, filters: dict = None, max_results: int = 0,
                                company_keyword: str = ''):
    """Synchronous wrapper to run keyword + filter search on エンジニア就活."""
    scraper = EngineerShukatsuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run_search(
            keywords, filters, max_results=max_results,
            company_keyword=company_keyword))
    finally:
        loop.close()
