"""外資就活ドットコム scraper — engineer page via browser automation.

Navigates to /engineer/recruiting_info, sorts by deadline,
and extracts listings directly from the rendered SPA DOM.
"""
import asyncio
import logging
import re
from datetime import datetime, date, timedelta
from .base import BaseScraper

logger = logging.getLogger(__name__)

GAISHI_BASE = "https://gaishishukatsu.com"
ENGINEER_URL = f"{GAISHI_BASE}/engineer/recruiting_info"


class GaishishukatsuScraper(BaseScraper):
    """Scraper for 外資就活ドットコム — エンジニア向け募集情報."""

    def __init__(self):
        super().__init__('gaishishukatsu')

    async def login(self) -> bool:
        """Login to gaishishukatsu.com using credentials from .env."""
        import os
        email = os.getenv('GAISHI_EMAIL', '')
        password = os.getenv('GAISHI_PASSWORD', '')
        if not email or not password:
            logger.info("[gaishi] No credentials configured")
            return True

        try:
            logger.info("[gaishi] Logging in...")
            await self.page.goto(
                f"{GAISHI_BASE}/login",
                wait_until='domcontentloaded', timeout=15000
            )
            await self.page.wait_for_timeout(1500)

            if '/login' not in self.page.url:
                logger.info("[gaishi] Already logged in")
                return True

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

            if '/login' in self.page.url:
                logger.warning("[gaishi] Login may have failed")
            else:
                logger.info(f"[gaishi] Login OK → {self.page.url}")
            return True
        except Exception as e:
            logger.warning(f"[gaishi] Login error: {e}")
            return True

    async def fetch_jobs(self) -> list:
        """Navigate to engineer page, sort by deadline, extract listings."""
        cutoff = date.today() + timedelta(days=3)
        today = date.today()
        logger.info(f"[gaishi] Navigating to engineer page (deadline ≤ {cutoff})...")

        # Navigate to engineer page sorted by deadline
        try:
            await self.page.goto(
                f"{ENGINEER_URL}?order=deadline",
                wait_until='domcontentloaded', timeout=20000
            )
        except Exception as e:
            logger.error(f"[gaishi] Failed to load engineer page: {e}")
            return []

        # Wait for SPA to render table content
        try:
            await self.page.wait_for_selector(
                'tr a[href*="/company/"]',
                timeout=15000
            )
            logger.info("[gaishi] SPA table content loaded")
        except Exception:
            logger.warning("[gaishi] Timeout waiting for table, retrying...")
            await self.page.wait_for_timeout(5000)

        # Extra wait for full render
        await self.page.wait_for_timeout(3000)

        raw = await self._extract_table_rows()
        logger.info(f"[gaishi] Extracted {len(raw)} listings from SPA DOM")

        # Convert to job dicts and filter by deadline
        year = datetime.now().year
        jobs = self._convert_raw_to_jobs(raw, year, cutoff, today)

        logger.info(f"[gaishi] {len(jobs)} listings within 3 days (from {len(raw)} total)")
        return jobs

    async def _extract_table_rows(self) -> list:
        """Extract listings from rendered SPA DOM, including companyID."""
        return await self.page.evaluate('''() => {
            const items = [];
            const rows = document.querySelectorAll('tr');
            for (const row of rows) {
                // Company logo link: <a href="/company/{companyID}">
                const companyLink = row.querySelector('a[href^="/company/"]');
                if (!companyLink) continue;

                const companyHref = companyLink.getAttribute('href') || '';
                const cidMatch = companyHref.match(/\\/company\\/(\\d+)/);
                if (!cidMatch) continue;
                const companyId = cidMatch[1];

                // Tracking link: <a href="/tracking/recruiting_info/{rid}?company_id=...">
                const trackLink = row.querySelector('a[href*="tracking/recruiting_info"]');
                let rid = '';
                if (trackLink) {
                    const tm = (trackLink.getAttribute('href') || '').match(/recruiting_info\\/(\\d+)/);
                    if (tm) rid = tm[1];
                }

                const rowText = row.textContent || '';

                // Type badge
                let jobType = '';
                if (rowText.indexOf('本選考') >= 0) jobType = '本選考';
                else if (rowText.indexOf('イベント') >= 0) jobType = 'イベント';
                else if (rowText.indexOf('インターン') >= 0) jobType = 'インターン';

                // Split text to get company name and title
                const parts = rowText.split('\\n')
                    .map(s => s.trim())
                    .filter(s => s.length > 0 && s !== 'エントリー');

                // Remove type badge if first
                if (parts.length > 0 && ['本選考','イベント','インターン'].includes(parts[0])) {
                    parts.shift();
                }

                // Company name from img alt (more reliable)
                const img = companyLink.querySelector('img');
                let company = '';
                if (img) {
                    company = (img.getAttribute('alt') || '').replace(/（エンジニア）/g, '').trim();
                }
                if (!company && parts.length > 0) {
                    company = parts[0].substring(0, 50);
                }

                const title = parts.length > 1 ? parts[1].substring(0, 200) : '';

                // Deadline: M/D (weekday) or M/D (weekday) HH:MM
                const dlm = rowText.match(/(\\d{1,2})\\/(\\d{1,2})\\s*\\([^)]*\\)/);
                let dm = '', dd = '';
                if (dlm) { dm = dlm[1]; dd = dlm[2]; }
                else {
                    const s = rowText.match(/(\\d{1,2})\\/(\\d{1,2})/);
                    if (s) { dm = s[1]; dd = s[2]; }
                }

                // Tags (卒年/理系/IT etc.)
                const tags = [];
                const tagEls = row.querySelectorAll('[class*="Badge"]');
                for (const t of tagEls) {
                    const txt = t.textContent.trim();
                    if (txt && !['エントリー'].includes(txt)) tags.push(txt);
                }

                items.push({
                    companyId, rid, company,
                    title: title.substring(0, 200),
                    jobType, dm, dd,
                    tags: tags.join(',')
                });
            }
            return items;
        }''')

    def _convert_raw_to_jobs(self, raw: list, year: int, cutoff=None, today=None) -> list:
        """Convert extracted DOM data to job dicts, optionally filtering by deadline."""
        jobs = []
        seen = set()
        for d in raw:
            rid = d['rid'] or d['companyId']
            key = f"{d['companyId']}_{rid}"
            if key in seen:
                continue
            seen.add(key)

            # Parse deadline
            deadline = None
            if d['dm'] and d['dd']:
                mo, day = int(d['dm']), int(d['dd'])
                yr = year if mo >= datetime.now().month else year + 1
                deadline = f"{yr}-{mo:02d}-{day:02d}"

            # Filter by deadline window if cutoff provided
            if cutoff and today and deadline:
                try:
                    dl_date = date.fromisoformat(deadline)
                    if dl_date < today or dl_date > cutoff:
                        continue
                except ValueError:
                    pass

            status = 'エンジニア'
            if d['jobType'] == '本選考':
                status = '本選'
            elif d['jobType'] == 'イベント':
                status = 'イベント'
            elif d['jobType'] == 'インターン':
                status = 'インターン'

            jobs.append({
                'company_name': d['company'],
                'company_name_jp': d['company'],
                'source': 'gaishishukatsu',
                'source_id': f"gaishi_{rid}",
                'job_url': f"{GAISHI_BASE}/engineer/recruiting_info/view/{rid}" if rid else f"{GAISHI_BASE}/company/{d['companyId']}",
                'position': d['title'],
                'status': status,
                'deadline': deadline,
                'industry': 'IT・通信',
                'notes': d.get('tags', 'エンジニア'),
                '_company_id': d['companyId'],  # internal: for enrichment
            })

        return jobs

    async def search_jobs(self, keywords: list, filters: dict = None) -> list:
        """Search engineer page with SPA checkbox filtering.

        Args:
            keywords: for local text filtering.
            filters: {'checkboxes': ['エンジニア志望向け', 'ITサービス']}
        """
        logger.info(f"[gaishi-search] Starting search, filters={filters}")

        # Navigate to engineer recruiting page
        try:
            await self.page.goto(
                f"{ENGINEER_URL}?order=deadline",
                wait_until='domcontentloaded', timeout=20000
            )
        except Exception as e:
            logger.error(f"[gaishi-search] Failed to load page: {e}")
            return []

        # Wait for SPA render
        try:
            await self.page.wait_for_selector(
                'tr a[href^="/company/"]', timeout=15000
            )
        except Exception:
            await self.page.wait_for_timeout(5000)

        await self.page.wait_for_timeout(3000)

        # Apply checkbox filters if provided
        if filters and filters.get('checkboxes'):
            for label in filters['checkboxes']:
                try:
                    checkbox = self.page.locator(f'label:has-text("{label}") input[type="checkbox"]').first
                    if await checkbox.count() > 0:
                        await checkbox.check()
                        logger.info(f"[gaishi-search] Checked: {label}")
                    else:
                        # Try text-based click
                        btn = self.page.locator(f'text="{label}"').first
                        if await btn.count() > 0:
                            await btn.click()
                            logger.info(f"[gaishi-search] Clicked: {label}")
                except Exception as e:
                    logger.warning(f"[gaishi-search] Could not toggle '{label}': {e}")

            # Wait for SPA to re-render with filters
            await self.page.wait_for_timeout(3000)

        # Extract all visible results
        raw = await self._extract_table_rows()
        year = datetime.now().year
        all_jobs = self._convert_raw_to_jobs(raw, year)

        logger.info(f"[gaishi-search] Extracted {len(all_jobs)} jobs before keyword filter")

        # Local keyword filtering
        if keywords:
            filtered = []
            for job in all_jobs:
                text = f"{job.get('company_name', '')} {job.get('position', '')} {job.get('notes', '')}"
                text_lower = text.lower()
                if any(kw.lower() in text_lower for kw in keywords):
                    filtered.append(job)
            logger.info(
                f"[gaishi-search] Keyword filter: {len(filtered)}/{len(all_jobs)} "
                f"matched [{', '.join(keywords)}]"
            )
            return filtered

        return all_jobs



def run_gaishishukatsu_scraper():
    """Synchronous entry point for the scheduler."""
    scraper = GaishishukatsuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run())
    finally:
        loop.close()


def run_gaishishukatsu_search(keywords: list, filters: dict = None, max_results: int = 0,
                              company_keyword: str = ''):
    """Synchronous wrapper to run search on 外資就活."""
    scraper = GaishishukatsuScraper()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(scraper.run_search(
            keywords, filters, max_results=max_results,
            company_keyword=company_keyword))
    finally:
        loop.close()
