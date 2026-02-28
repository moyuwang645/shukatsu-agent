import asyncio
import logging
import re
from datetime import datetime
from bs4 import BeautifulSoup
from .base import BaseScraper
from config import Config

logger = logging.getLogger(__name__)

MYNAVI_BASE = f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}"
MYNAVI_LOGIN_URL = f"{MYNAVI_BASE}/pc/common/displayRelayScreen/displayForLogin"
MYNAVI_MYPAGE_URL = f"{MYNAVI_BASE}/mypage"
MYNAVI_FAVORITE_URL = f"{MYNAVI_BASE}/mypage/bookmark"
MYNAVI_ENTRY_URL = f"{MYNAVI_BASE}/mypage/entry"

# Keywords that appear next to deadline date fields on company detail pages
DEADLINE_KEYWORDS = [
    'エントリー締め切り',
    'エントリー締切',
    '応募締め切り',
    '応募締切',
    '選考締め切り',
    '選考締切',
    'セミナー締め切り',
    '説明会締め切り',
    '締め切り',
    '締切',
    'deadline',
]

# Date patterns to find in extracted text
_DATE_PATTERNS = [
    r'\d{4}年\d{1,2}月\d{1,2}日',
    r'\d{4}/\d{1,2}/\d{1,2}',
    r'\d{1,2}月\d{1,2}日',
    r'\d{1,2}/\d{1,2}',
]


class MynaviScraper(BaseScraper):
    """Scraper for マイナビ2027 (新卒)."""

    def __init__(self):
        super().__init__('mynavi')
        self._last_error = ''

    async def login(self) -> bool:
        """Login to マイナビ using saved browser state (cookies).

        If no saved state exists, the user must use the 'manual login' feature
        from the settings page first.
        """
        import os

        state_file = self._state_file()
        has_cookies = os.path.exists(state_file)

        if has_cookies:
            logger.info("Attempting cookie-based login...")
            try:
                await self.page.goto(MYNAVI_MYPAGE_URL, wait_until='domcontentloaded', timeout=30000)
                await self.page.wait_for_timeout(3000)

                current_url = self.page.url
                logger.info(f"Cookie login check URL: {current_url}")

                if 'mypage' in current_url or (
                    'job.mynavi.jp' in current_url
                    and 'login' not in current_url
                    and 'mcid' not in current_url
                ):
                    logger.info("Cookie-based login successful!")
                    return True

                logger.warning("Saved cookies expired, deleting state file")
                os.remove(state_file)

            except Exception as e:
                logger.warning(f"Cookie login attempt failed: {e}")
                if os.path.exists(state_file):
                    os.remove(state_file)

        self._last_error = '手動ログインが必要です。設定ページの「手動ログイン」ボタンをクリックしてください'
        logger.error("No valid cookies. Manual login required.")
        return False

    # ------------------------------------------------------------------
    # Main fetch pipeline
    # ------------------------------------------------------------------

    async def fetch_jobs(self) -> list:
        """Fetch bookmarked and entered companies from マイナビ, with deadlines."""
        jobs = []

        try:
            bookmark_jobs = await self._fetch_bookmark_list()
            jobs.extend(bookmark_jobs)
        except Exception as e:
            logger.error(f"Error fetching bookmarks: {e}")

        try:
            entry_jobs = await self._fetch_entry_list()
            jobs.extend(entry_jobs)
        except Exception as e:
            logger.error(f"Error fetching entries: {e}")

        # --- Second pass: visit each company detail page for its deadline ---
        logger.info(f"Starting deadline extraction for {len(jobs)} companies...")
        for job in jobs:
            url = job.get('job_url')
            if not url:
                continue
            try:
                outline_url = url.rstrip('/') + '/outline.html'
                details = await self._fetch_employment_details_fast(outline_url)
                if details:
                    for key, val in details.items():
                        if val and not job.get(key):
                            job[key] = val
                    if details.get('deadline'):
                        logger.info(f"Deadline for {job.get('company_name')}: {details['deadline']}")
            except Exception as e:
                logger.debug(f"Detail fetch failed for {job.get('company_name')}: {e}")
            # Small throttle to avoid hammering the server
            await self.page.wait_for_timeout(800)

        return jobs

    # ------------------------------------------------------------------
    # Bookmark / Entry list fetchers
    # ------------------------------------------------------------------

    async def _fetch_bookmark_list(self) -> list:
        """Fetch お気に入り企業一覧."""
        jobs = []
        try:
            await self.page.goto(MYNAVI_FAVORITE_URL, wait_until='domcontentloaded', timeout=30000)
            await self.page.wait_for_timeout(3000)
            items = await self._extract_company_items('interested')
            jobs.extend(items)
            logger.info(f"Found {len(items)} bookmarked companies")
        except Exception as e:
            logger.error(f"Error in bookmark fetch: {e}")
        return jobs

    async def _fetch_entry_list(self) -> list:
        """Fetch エントリー済み企業一覧."""
        jobs = []
        try:
            await self.page.goto(MYNAVI_ENTRY_URL, wait_until='domcontentloaded', timeout=30000)
            await self.page.wait_for_timeout(3000)
            items = await self._extract_company_items('applied')
            jobs.extend(items)
            logger.info(f"Found {len(items)} entered companies")
        except Exception as e:
            logger.error(f"Error in entry fetch: {e}")
        return jobs

    async def _extract_company_items(self, default_status) -> list:
        """Extract company information from the current page."""
        jobs = []

        item_selectors = [
            '.cassetteRecruit',
            '.entryCorpList__item',
            '.boxList > li',
            '.company-list-item',
            '.bookmark-item',
            '.entry-item',
            '.companyList__item',
            '.company_item',
            'li[class*="company"]',
            '.search-result-item',
            'div[class*="Company"]',
            'div[class*="company"]',
            '.listBox',
        ]

        items_locator = None
        for sel in item_selectors:
            try:
                loc = self.page.locator(sel)
                count = await loc.count()
                if count > 0:
                    items_locator = loc
                    logger.info(f"Found {count} items with selector: {sel}")
                    break
            except Exception:
                continue

        if not items_locator:
            logger.warning("No company items found with known selectors, trying content extraction")
            return await self._extract_from_page_content(default_status)

        count = await items_locator.count()
        for i in range(count):
            try:
                item = items_locator.nth(i)
                job = await self._parse_company_item(item, default_status)
                if job and job.get('company_name'):
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"Error parsing item {i}: {e}")

        return jobs

    async def _parse_company_item(self, item, default_status) -> dict:
        """Parse a single company list item (without deadline — set in second pass)."""
        job = {
            'source': 'mynavi',
            'status': default_status,
        }

        # Company name
        name_selectors = [
            'a.js-add-examination-list-text',
            'a[id^="corpNameLink"]',
            'h3', 'h2', '.company-name', '.companyName',
            'a[class*="name"]', '.name', 'p.ttl', '.ttl',
        ]
        for sel in name_selectors:
            try:
                el = item.locator(sel).first
                if await el.count() > 0:
                    name = (await el.inner_text()).strip()
                    if name:
                        job['company_name_jp'] = name
                        job['company_name'] = name
                        break
            except Exception:
                continue

        # Status / notes
        status_selectors = [
            '.status',
            '.recruitStatus',
            'a[id^="recruitCourseInfo"] span',
        ]
        for sel in status_selectors:
            try:
                el = item.locator(sel).first
                if await el.count() > 0:
                    status_text = (await el.inner_text()).strip()
                    if status_text:
                        job['notes'] = status_text
                        break
            except Exception:
                continue

        # Link / URL
        try:
            link = item.locator('a').first
            href = await link.get_attribute('href')
            if href:
                if href.startswith('/'):
                    href = f"https://job.mynavi.jp{href}"
                job['job_url'] = href
                match = re.search(r'/(\d+)/?', href)
                if match:
                    job['source_id'] = f"mynavi_{match.group(1)}"
        except Exception:
            pass

        # Fallback source_id from name hash
        if not job.get('source_id') and job.get('company_name'):
            job['source_id'] = f"mynavi_{hash(job['company_name']) % 10**8}"

        # Position hint from list text
        try:
            text = await item.inner_text()
            if '総合職' in text:
                job['position'] = '総合職'
            elif 'エンジニア' in text:
                job['position'] = 'エンジニア'
            elif '技術職' in text:
                job['position'] = '技術職'
        except Exception:
            pass

        return job

    # Detail-page extraction  ← Fast Concurrent HTTP approach
    # ------------------------------------------------------------------

    async def _fetch_employment_details_fast(self, url: str) -> dict:
        """Fetch employment details quickly via browser context HTTP request.
        
        Fetches TWO pages per company:
          1. outline.html → 本社所在地 (address), deadline
          2. employment.html → 募集職種 (position), 仕事内容 (job description)
        """
        result = {
            'deadline': None,
            'position': None,
            'job_description': None,
            'location': None,
            'industry': None,
        }

        def _parse_table(soup):
            """Extract all th→td pairs from a page."""
            data = {}
            for th in soup.find_all('th'):
                text = th.get_text(strip=True)
                td = th.find_next_sibling('td')
                if td:
                    td_text = '\n'.join(list(td.stripped_strings))
                    data[text] = td_text
            return data

        def get_field(data, *keywords):
            for k, v in data.items():
                if any(kw in k for kw in keywords):
                    return v.strip()
            return ""

        # --- 1. Fetch outline.html (address + deadline) ---
        try:
            resp1 = await self.page.context.request.get(url, timeout=15000)
            if resp1.ok:
                soup1 = BeautifulSoup(await resp1.text(), 'html.parser')
                outline_data = _parse_table(soup1)

                # Location: use 本社所在地 (actual address), NOT 本社郵便番号
                result['location'] = get_field(outline_data, '勤務地', '本社所在地')

                # Industry from outline page (業種)
                result['industry'] = get_field(outline_data, '業種', '事業内容')

                # Deadline from outline page
                deadline_str = get_field(outline_data, 'エントリー', '締切', '期間')
                if deadline_str:
                    result['deadline'] = self._extract_first_date(deadline_str)

                if not result['deadline']:
                    full_text = soup1.get_text()
                    for keyword in DEADLINE_KEYWORDS:
                        idx = full_text.find(keyword)
                        if idx != -1:
                            snippet = full_text[idx: idx + 120]
                            date = self._extract_first_date(snippet)
                            if date:
                                result['deadline'] = date
                                break
        except Exception as e:
            logger.debug(f"Outline fetch failed for {url}: {e}")

        # --- 2. Fetch employment.html (position + job description) ---
        # Build employment URL from the outline URL
        # e.g. .../corp88256/outline.html → .../corpinfo/displayEmployment/index?corpId=88256
        try:
            corp_match = re.search(r'corp(\d+)', url)
            if corp_match:
                corp_id = corp_match.group(1)
                emp_url = f"{MYNAVI_BASE}/pc/corpinfo/displayEmployment/index?corpId={corp_id}"
                resp2 = await self.page.context.request.get(emp_url, timeout=15000)
                if resp2.ok:
                    soup2 = BeautifulSoup(await resp2.text(), 'html.parser')
                    emp_data = _parse_table(soup2)

                    result['position'] = get_field(emp_data, '募集職種', '職種')
                    desc = get_field(emp_data, '仕事内容', '業務内容', '募集対象')
                    result['job_description'] = desc[:500] if desc else None

                    # Also try employment page for location if outline didn't have it
                    if not result['location']:
                        result['location'] = get_field(emp_data, '勤務地', '配属先')

                    # Also try employment page for deadline if outline didn't have it
                    if not result['deadline']:
                        deadline_str2 = get_field(emp_data, 'エントリー', '締切', '期間')
                        if deadline_str2:
                            result['deadline'] = self._extract_first_date(deadline_str2)
        except Exception as e:
            logger.debug(f"Employment fetch failed for {url}: {e}")

        return result

    def _extract_first_date(self, text: str) -> str | None:
        """Extract and normalise the first recognisable date from a text snippet."""
        if not text:
            return None
        for pattern in _DATE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return self._parse_date(match.group(0))
        return None

    def _parse_date(self, date_str: str) -> str | None:
        """Parse a Japanese / slash-delimited date string to YYYY-MM-DD."""
        now = datetime.now()
        try:
            # YYYY年MM月DD日
            m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            # YYYY/MM/DD
            m = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            # MM月DD日  (assume current or next year)
            m = re.match(r'(\d{1,2})月(\d{1,2})日', date_str)
            if m:
                mo, d = int(m.group(1)), int(m.group(2))
                year = now.year if mo >= now.month else now.year + 1
                return f"{year}-{mo:02d}-{d:02d}"

            # MM/DD
            m = re.match(r'(\d{1,2})/(\d{1,2})', date_str)
            if m:
                mo, d = int(m.group(1)), int(m.group(2))
                year = now.year if mo >= now.month else now.year + 1
                return f"{year}-{mo:02d}-{d:02d}"

        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Fallback company extraction
    # ------------------------------------------------------------------

    async def _extract_from_page_content(self, default_status) -> list:
        """Fallback: extract job info from raw page content."""
        jobs = []
        try:
            links = self.page.locator(f'a[href*="/{Config.MYNAVI_YEAR}/"]')
            count = await links.count()
            seen_ids: set = set()
            for i in range(min(count, 100)):
                try:
                    link = links.nth(i)
                    href = await link.get_attribute('href')
                    text = (await link.inner_text()).strip()

                    if not text or len(text) < 2 or len(text) > 100:
                        continue

                    match = re.search(r'/(\d{4,})/?', href or '')
                    if match and text:
                        sid = f"mynavi_{match.group(1)}"
                        if sid not in seen_ids:
                            seen_ids.add(sid)
                            url = href
                            if url and url.startswith('/'):
                                url = f"https://job.mynavi.jp{url}"
                            jobs.append({
                                'company_name': text,
                                'company_name_jp': text,
                                'source': 'mynavi',
                                'source_id': sid,
                                'job_url': url,
                                'status': default_status,
                            })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Fallback extraction error: {e}")
        return jobs

    # ------------------------------------------------------------------
    # Keyword search  ← extensible entry point for interest-based search
    # ------------------------------------------------------------------

    async def search_jobs(self, keywords: list, filters: dict = None, max_pages: int = 5) -> list:
        """Search MyNavi for jobs matching user-defined keywords.

        For each keyword:
          1. Navigate using the known direct search URL (most reliable).
          2. Scroll the results page to trigger lazy-loaded entries.
          3. Paginate through up to `max_pages` result pages.
          4. Visit each company's detail page for the deadline.
        """
        import urllib.parse
        all_jobs: list = []
        seen_ids: set = set()

        for keyword in keywords:
            logger.info(f"[mynavi] Searching for keyword: '{keyword}'")
            items = []
            landed = False

            # --- Direct URL (confirmed working from debug_search.py) ---
            import urllib.parse
            kw_encoded = urllib.parse.quote(keyword, safe='')
            for url_tpl in [
                f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/pc/corpinfo/searchCorpListByGenCond/index/?cond=FW:{keyword}/func=PCTopQuickSearch/FWTGT:1",
                f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/pc/corpinfo/searchCorpListByGenCond/index/?cond=FW:{kw_encoded}/func=PCTopQuickSearch/FWTGT:1",
            ]:
                try:
                    # Use networkidle so JavaScript fully renders the company list
                    await self.page.goto(url_tpl, wait_until='networkidle', timeout=40000)
                    current = self.page.url
                    logger.info(f"[mynavi] Direct URL → {current}")
                    body_text = (await self.page.locator('body').inner_text())[:600]
                    # '検索条件を変更' is a NORMAL filter link on results pages — do NOT treat as error
                    # The actual error message when no condition is set is '検索条件を１つ以上'
                    is_error = '検索条件を１つ以上' in body_text or ('404' in body_text[:100])
                    if not is_error:
                        link_cnt = await self.page.locator('a.js-add-examination-list-text').count()
                        logger.info(f"[mynavi] Results page OK — {link_cnt} company links visible")
                        landed = True
                        break
                    else:
                        logger.warning(f"[mynavi] Error page for: {url_tpl[:80]}")
                except Exception as e:
                    logger.warning(f"[mynavi] Direct URL failed: {e}")

            # --- Fallback: top-page search form ---
            if not landed:
                try:
                    MYNAVI_TOP = f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/"
                    await self.page.goto(MYNAVI_TOP, wait_until='networkidle', timeout=40000)
                    for sel in [
                        'input[name="freeKeyword"]',
                        'input[name="keyword"]',
                        'input[placeholder*="フリーワード"]',
                        'input[placeholder*="キーワード"]',
                        'input[placeholder*="企業名"]',
                        '#keyword',
                        'input[type="text"]',
                    ]:
                        try:
                            loc = self.page.locator(sel)
                            if await loc.count() > 0:
                                await loc.first.fill(keyword)
                                await self.page.wait_for_timeout(500)
                                await loc.first.press('Enter')
                                # Wait for navigation + JS render
                                await self.page.wait_for_load_state('networkidle', timeout=30000)
                                url_after = self.page.url
                                logger.info(f"[mynavi] Form submit ({sel}) → {url_after}")
                                if 'mynavi.jp' in url_after and 'mypage' not in url_after:
                                    landed = True
                                break
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"[mynavi] Top-page form failed: {e}")

            if not landed:
                logger.error(f"[mynavi] Could not reach search results for '{keyword}'")
                continue

            # --- Paginate and collect ---
            for page_num in range(1, max_pages + 1):
                logger.info(f"[mynavi] '{keyword}' page {page_num}: {self.page.url}")
                await self._scroll_page_fully()
                page_items = await self._extract_search_result_items()
                logger.info(f"[mynavi] Page {page_num}: {len(page_items)} companies")
                items.extend(page_items)
                if not page_items:
                    break
                if not await self._goto_next_page():
                    break

            # Deduplicate across keywords
            new_items = []
            for job in items:
                sid = job.get('source_id')
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    job['notes'] = f"キーワード検索: {keyword}"
                    new_items.append(job)

            logger.info(f"[mynavi] Keyword '{keyword}': {len(new_items)} unique new companies")

            # Fetch details fast and concurrently (chunked to avoid rate limits)
            logger.info(f"[mynavi] Fetching details for {len(new_items)} companies concurrently...")
            chunk_size = 15
            for i in range(0, len(new_items), chunk_size):
                chunk = new_items[i:i + chunk_size]
                tasks = [self._fetch_employment_details_fast(job.get('job_url')) for job in chunk]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for job, detail in zip(chunk, results):
                    if isinstance(detail, dict):
                        if detail.get('deadline'):
                            job['deadline'] = detail['deadline']
                        if detail.get('position'):
                            job['position'] = detail['position']
                            # Match against standard japanese job categories
                            for cat in Config.JOB_CATEGORY_KEYWORDS:
                                if cat in detail['position']:
                                    job['job_type'] = cat
                                    break
                        if detail.get('job_description'):
                            job['job_description'] = detail['job_description']
                        if detail.get('location'):
                            job['location'] = detail['location']
                        if detail.get('industry'):
                            job['industry'] = detail['industry']
                            
                await self.page.wait_for_timeout(500)  # small pause between chunks

            all_jobs.extend(new_items)

        logger.info(f"[mynavi] Keyword search complete: {len(all_jobs)} total companies")
        return all_jobs

    async def _scroll_page_fully(self):
        """Scroll top-to-bottom so lazy-loaded company cards are rendered."""
        try:
            prev_h = await self.page.evaluate("document.body.scrollHeight")
            for _ in range(20):
                await self.page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
                await self.page.wait_for_timeout(500)
                new_h = await self.page.evaluate("document.body.scrollHeight")
                if new_h == prev_h:
                    break
                prev_h = new_h
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self.page.wait_for_timeout(400)
        except Exception as e:
            logger.debug(f"Scroll error: {e}")

    async def _goto_next_page(self) -> bool:
        """Click the next-page link on MyNavi search results. Returns True if navigated."""
        try:
            for sel in [
                'a[class*="next"]',
                'a[rel="next"]',
                '.pager a:has-text("次")',
                'a:has-text("次のページ")',
                '.btnPagerNext a',
                'li.next a',
            ]:
                loc = self.page.locator(sel)
                if await loc.count() > 0:
                    href = await loc.first.get_attribute('href') or ''
                    if href:
                        full = href if href.startswith('http') else f"https://job.mynavi.jp{href}"
                        await self.page.goto(full, wait_until='domcontentloaded', timeout=25000)
                        await self.page.wait_for_timeout(2000)
                        return True
        except Exception as e:
            logger.debug(f"Next page error: {e}")
        return False

    async def _extract_search_result_items(self) -> list:
        """Extract company links from the current MyNavi search results page.

        MyNavi renders the company list via JavaScript. We explicitly wait for
        at least one company link to appear (up to 12 seconds) before counting.
        """
        jobs = []
        # Selectors in priority order — try each, wait for the first one that appears
        SELECTORS = [
            'a.js-add-examination-list-text',
            'a[id^="corpNameLink"]',
            '.cassetteRecruit a[href*="/pc/search/corp"]',
            'a[href*="/pc/search/corp"]',
        ]
        try:
            # Wait for any of the selectors to appear (JS render complete)
            found_sel = None
            for sel in SELECTORS:
                try:
                    await self.page.wait_for_selector(sel, timeout=12000)
                    found_sel = sel
                    logger.info(f"[mynavi] JS render confirmed — selector '{sel}' appeared")
                    break
                except Exception:
                    continue

            if not found_sel:
                # Debug: log page title & first 200 chars to diagnose
                title = await self.page.title()
                snippet = (await self.page.locator('body').inner_text())[:300]
                logger.warning(f"[mynavi] No company elements found. Page='{title}' | {snippet!r}")
                return jobs

            for sel in SELECTORS:
                links = self.page.locator(sel)
                count = await links.count()
                if count == 0:
                    continue
                logger.info(f"[mynavi] Selector '{sel}': {count} links found")
                seen_hrefs: set = set()
                for i in range(min(count, 200)):
                    try:
                        link = links.nth(i)
                        href = (await link.get_attribute('href') or '').strip()
                        name = (await link.inner_text()).strip()
                        if not name or not href or href in seen_hrefs:
                            continue
                        if len(name) > 100:
                            continue
                        seen_hrefs.add(href)
                        if href.startswith('/'):
                            href = f"https://job.mynavi.jp{href}"
                        match = re.search(r'/corp(\d+)/', href)
                        if not match:
                            continue
                        jobs.append({
                            'company_name': name,
                            'company_name_jp': name,
                            'source': 'mynavi',
                            'source_id': f"mynavi_{match.group(1)}",
                            'job_url': href,
                            'status': 'interested',
                        })
                    except Exception:
                        continue
                if jobs:
                    break
        except Exception as e:
            logger.error(f"[mynavi] _extract_search_result_items error: {e}")
        return jobs


def run_mynavi_scraper():
    """Synchronous wrapper to run the マイナビ scraper (bookmarks/entries)."""
    scraper = MynaviScraper()
    return asyncio.run(scraper.run())


def run_mynavi_search(keywords: list, filters: dict = None, max_results: int = 0,
                      company_keyword: str = ''):
    """Synchronous wrapper to run a keyword search on マイナビ."""
    scraper = MynaviScraper()
    return asyncio.run(scraper.run_search(
        keywords, filters, max_results=max_results,
        company_keyword=company_keyword))
