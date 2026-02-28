"""ONE CAREER (ワンキャリア) scraper — events by industry category.

Iterates through OneCareer's business_categories pages to fetch events,
so each event has its industry classification at scrape time.
No login required for browsing.
"""
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from .base import BaseScraper

logger = logging.getLogger(__name__)

ONECAREER_BASE = "https://www.onecareer.jp"

# Category ID → industry name mapping (from OneCareer's business_categories)
INDUSTRY_CATEGORIES = {
    1: 'コンサル・シンクタンク',
    2: '金融',
    3: 'メーカー',
    4: '商社',
    5: 'IT・通信',
    6: '広告・マスコミ',
    7: '人材・教育',
    8: 'インフラ・交通',
    9: '不動産・建設',
    10: '旅行・観光',
    11: 'サービス・小売',
    12: '官公庁・非営利',
}


class OneCareerScraper(BaseScraper):
    """Scraper for ONE CAREER — イベント/説明会 by industry category."""

    def __init__(self):
        super().__init__('onecareer')

    async def login(self) -> bool:
        """ONE CAREER doesn't require login for event browsing."""
        import os
        email = os.getenv('ONECAREER_EMAIL', '')
        password = os.getenv('ONECAREER_PASSWORD', '')

        if not email or not password:
            logger.info("[onecareer] No credentials — browsing as guest")
            return True

        try:
            logger.info("[onecareer] Logging in...")
            await self.page.goto(
                "https://id.onecareer.jp/users/sign_in?redirect_url=https%3A%2F%2Fwww.onecareer.jp%2F",
                wait_until='domcontentloaded', timeout=15000
            )
            await self.page.wait_for_timeout(1500)

            if '/sign_in' not in self.page.url:
                logger.info("[onecareer] Already logged in")
                return True

            await self.page.locator(
                'input[name="email"], input[type="email"]'
            ).first.fill(email)
            await self.page.locator(
                'input[name="password"], input[type="password"]'
            ).first.fill(password)
            await self.page.locator(
                'button[type="submit"]'
            ).first.click()
            await self.page.wait_for_timeout(3000)
            logger.info(f"[onecareer] Login → {self.page.url}")
            return True
        except Exception as e:
            logger.warning(f"[onecareer] Login error: {e}")
            return True

    async def fetch_jobs(self) -> list:
        """Fetch events from each industry category page."""
        cutoff = date.today() + timedelta(days=3)
        today = date.today()
        all_jobs = []
        seen = set()

        logger.info(f"[onecareer] Fetching events by category (deadline ≤ {cutoff})...")

        for cat_id, industry_name in INDUSTRY_CATEGORIES.items():
            url = (
                f"{ONECAREER_BASE}/events/seminar/business_categories/{cat_id}"
                "?sort=time_limit_at"
            )
            logger.info(f"[onecareer] Category {cat_id}: {industry_name}")

            items = await self._fetch_category_page(url, industry_name)

            for job in items:
                eid = job['source_id']
                if eid in seen:
                    continue
                seen.add(eid)

                # Filter by deadline
                deadline = job.get('deadline')
                if deadline:
                    try:
                        dl_date = date.fromisoformat(deadline)
                        if dl_date < today or dl_date > cutoff:
                            continue
                    except ValueError:
                        pass

                all_jobs.append(job)

            logger.info(f"[onecareer] {industry_name}: {len([j for j in all_jobs if j['industry'] == industry_name])} events within 3 days")

        logger.info(f"[onecareer] Total: {len(all_jobs)} events across all categories")
        return all_jobs

    async def _fetch_category_page(self, url: str, industry_name: str) -> list:
        """Fetch and parse a single category page, return job dicts."""
        try:
            await self.page.goto(url, wait_until='domcontentloaded', timeout=20000)
        except Exception as e:
            logger.warning(f"[onecareer] Failed to load {industry_name}: {e}")
            return []

        # Wait for event cards to render
        try:
            await self.page.wait_for_selector(
                'a[href*="/events/"]', timeout=10000
            )
        except Exception:
            logger.info(f"[onecareer] No events for {industry_name}")
            return []

        await self.page.wait_for_timeout(2000)

        # Extract events via JS
        year = datetime.now().year
        raw = await self.page.evaluate('''() => {
            const items = [];
            const cards = document.querySelectorAll('a[href*="/events/"]');
            for (const card of cards) {
                const href = card.getAttribute('href') || '';
                const m = href.match(/\\/events\\/(?:seminar\\/)?(\\d+)/);
                if (!m) continue;

                const eid = m[1];
                const compEl = card.querySelector('h3, [class*="company"]');
                const company = compEl ? compEl.textContent.trim() : '';
                const titleEl = card.querySelector('h4, [class*="title"]');
                const title = titleEl ? titleEl.textContent.trim() : '';
                const dlEl = card.querySelector('[class*="deadline"]');
                const dlText = dlEl ? dlEl.textContent.trim() : '';
                const dlMatch = dlText.match(/(\\d{1,2})\\/(\\d{1,2})/);
                let dm = '', dd = '';
                if (dlMatch) { dm = dlMatch[1]; dd = dlMatch[2]; }

                // Try to extract companyID from company link
                let companyId = '';
                const compLink = card.querySelector('a[href*="/companies/"]');
                if (compLink) {
                    const cm = (compLink.getAttribute('href') || '').match(/\\/companies\\/(\\d+)/);
                    if (cm) companyId = cm[1];
                }
                // Also check parent or nearby links
                if (!companyId) {
                    const allLinks = card.querySelectorAll('a[href*="/companies/"]');
                    for (const cl of allLinks) {
                        const cm2 = (cl.getAttribute('href') || '').match(/\\/companies\\/(\\d+)/);
                        if (cm2) { companyId = cm2[1]; break; }
                    }
                }

                if (company || title) {
                    items.push({
                        eid, company: company.substring(0, 50),
                        title: title.substring(0, 120),
                        dm, dd, dlText, href, companyId
                    });
                }
            }
            return items;
        }''')

        # Convert to job dicts
        jobs = []
        for d in raw:
            deadline = None
            if d['dm'] and d['dd']:
                mo, day = int(d['dm']), int(d['dd'])
                yr = year if mo >= datetime.now().month else year + 1
                deadline = f"{yr}-{mo:02d}-{day:02d}"

            full_url = d['href']
            if full_url.startswith('/'):
                full_url = f"{ONECAREER_BASE}{full_url}"

            jobs.append({
                'company_name': d['company'],
                'company_name_jp': d['company'],
                'source': 'onecareer',
                'source_id': f"onecareer_{d['eid']}",
                'job_url': full_url,
                'position': d['title'][:100],
                'status': 'イベント',
                'deadline': deadline,
                'industry': industry_name,
                'notes': f"ワンキャリア {industry_name} {d['dlText'][:30]}",
                '_company_id': d.get('companyId', ''),
                '_event_id': d['eid'],
            })

        return jobs

    async def search_jobs(self, keywords: list, filters: dict = None) -> list:
        """Search OneCareer by category filter + keyword.

        Args:
            keywords: for local text filtering.
            filters: {'categories': [5, 1]} — only scrape these category IDs.
        """
        all_jobs = []
        seen = set()

        # Determine which categories to scrape
        if filters and filters.get('categories'):
            cat_ids = [int(c) for c in filters['categories']]
            categories = {k: v for k, v in INDUSTRY_CATEGORIES.items() if k in cat_ids}
        else:
            categories = INDUSTRY_CATEGORIES

        logger.info(f"[onecareer-search] Searching {len(categories)} categories, keywords={keywords}")

        for cat_id, industry_name in categories.items():
            url = (
                f"{ONECAREER_BASE}/events/seminar/business_categories/{cat_id}"
                "?sort=newest"  # Use newest sort for search
            )
            logger.info(f"[onecareer-search] Category {cat_id}: {industry_name}")

            items = await self._fetch_category_page(url, industry_name)

            for job in items:
                sid = job['source_id']
                if sid not in seen:
                    seen.add(sid)
                    all_jobs.append(job)

        logger.info(f"[onecareer-search] {len(all_jobs)} events total before keyword filter")

        # Local keyword filtering
        if keywords:
            filtered = []
            for job in all_jobs:
                text = f"{job.get('company_name', '')} {job.get('position', '')} {job.get('industry', '')} {job.get('notes', '')}"
                text_lower = text.lower()
                if any(kw.lower() in text_lower for kw in keywords):
                    filtered.append(job)
            logger.info(
                f"[onecareer-search] Keyword filter: {len(filtered)}/{len(all_jobs)} "
                f"matched [{', '.join(keywords)}]"
            )
            return filtered

        return all_jobs




def run_onecareer_scraper():
    """Synchronous entry point for the scheduler."""
    scraper = OneCareerScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run())
    finally:
        loop.close()


def run_onecareer_search(keywords: list, filters: dict = None, max_results: int = 0,
                         company_keyword: str = ''):
    """Synchronous wrapper to run search on ワンキャリア."""
    scraper = OneCareerScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run_search(
            keywords, filters, max_results=max_results,
            company_keyword=company_keyword))
    finally:
        loop.close()
