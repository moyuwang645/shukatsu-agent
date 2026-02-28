"""Base scraper class for job sites."""
from abc import ABC, abstractmethod
import logging
import os

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all job site scrapers."""

    def __init__(self, name):
        self.name = name
        self.browser = None
        self.context = None
        self.page = None

    @abstractmethod
    async def login(self) -> bool:
        """Login to the job site. Returns True if successful."""
        pass

    @abstractmethod
    async def fetch_jobs(self) -> list:
        """Fetch all tracked jobs from the site (bookmarks / entries)."""
        pass

    async def fetch_deadlines(self) -> list:
        """Fetch upcoming deadlines. Deprecated — deadlines live in fetch_jobs now."""
        return []

    async def search_jobs(self, keywords: list, filters: dict = None) -> list:
        """Search for jobs by keywords and optional site-specific filters.

        Args:
            keywords: list of search keyword strings.
            filters: optional dict of site-specific filter params
                     (e.g. {'arr_industry': ['SIer'], 'categories': [5]}).

        Default returns empty list so new scrapers can be added incrementally
        without breaking the search pipeline.
        """
        return []

    def _state_file(self) -> str:
        """Path to the saved browser state file for this scraper."""
        from config import Config
        return os.path.join(Config.BASE_DIR, 'data', f'{self.name}_state.json')

    async def fetch_detail_text(self, url: str) -> str:
        """Fetch a detail page and return cleaned text content.

        Uses browser context HTTP request (no navigation needed).
        Returns empty string on failure.
        """
        if not url or not self.page:
            return ''
        try:
            resp = await self.page.context.request.get(url, timeout=15000)
            if not resp.ok:
                return ''
            html = await resp.text()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            # Remove script/style tags
            for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
            # Collapse blank lines
            import re
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text[:4000]
        except Exception as e:
            logger.debug(f"[{self.name}] fetch_detail_text failed for {url}: {e}")
            return ''

    # Fields that define "data completeness" for incremental skipping
    _COMPLETENESS_FIELDS = ('position', 'location', 'industry', 'job_description')

    @staticmethod
    def _is_data_complete(db_record: dict) -> bool:
        """Check whether a DB record has all key fields filled.

        Uses a relaxed check: position + location + industry + job_description
        must all be non-empty. salary and deadline are excluded because many
        companies genuinely don't provide them.
        """
        for field in BaseScraper._COMPLETENESS_FIELDS:
            val = db_record.get(field)
            if not val or (isinstance(val, str) and not val.strip()):
                return False
        return True

    async def _run_pipeline(self, job_fetcher, *args, max_results: int = 0,
                            company_keyword: str = '') -> dict:
        """Core pipeline: launch browser → login → fetch → save → enqueue AI.

        Phase 1 (this method): Scrape and save raw data immediately.
        Phase 2 (TaskWorker): AI detail enrichment runs asynchronously via queue.

        Incremental: jobs already in DB with complete data are skipped.
        Incomplete records are saved and queued for AI enrichment.

        Args:
            job_fetcher: coroutine to call after login (fetch_jobs or search_jobs)
            *args: arguments to pass to job_fetcher
            max_results: if > 0, only process this many results (for backfill)
            company_keyword: if set, only save results matching this company name
        """
        from playwright.async_api import async_playwright

        result = {
            'source': self.name,
            'status': 'error',
            'jobs_found': 0,
            'jobs_updated': 0,
            'jobs_enqueued_for_ai': 0,
            'jobs_skipped': 0,
            'jobs_incomplete': 0,
            'error_message': ''
        }

        try:
            pw = await async_playwright().start()
            from config import Config
            from scrapers.stealth import create_context_options, apply_stealth
            
            self.browser = await pw.chromium.launch(headless=Config.HEADLESS)

            # Load saved browser state (cookies) if available
            state_file = self._state_file()
            ctx_args = create_context_options()
            
            if os.path.exists(state_file):
                ctx_args['storage_state'] = state_file
                logger.info(f"[{self.name}] Loaded saved browser state from {state_file}")

            self.context = await self.browser.new_context(**ctx_args)
            self.page = await self.context.new_page()
            await apply_stealth(self.page)

            logger.info(f"[{self.name}] Starting pipeline...")

            logged_in = await self.login()
            if not logged_in:
                detail = getattr(self, '_last_error', '') or 'Login failed'
                result['error_message'] = detail
                logger.error(f"[{self.name}] Login failed: {detail}")
                return result

            # Save browser state after successful login
            try:
                await self.context.storage_state(path=state_file)
                logger.info(f"[{self.name}] Browser state saved to {state_file}")
            except Exception as e:
                logger.warning(f"[{self.name}] Could not save browser state: {e}")

            logger.info(f"[{self.name}] Login successful, fetching...")

            jobs = await job_fetcher(*args)
            result['jobs_found'] = len(jobs)

            # ── Company name filtering (backfill mode) ──
            if company_keyword and max_results > 0:
                from services.company_normalizer import normalize
                norm_kw = normalize(company_keyword)
                matched = []
                for job in jobs:
                    name = normalize(job.get('company_name', ''))
                    name_jp = normalize(job.get('company_name_jp', ''))
                    # Exact match, containment in either direction
                    if (norm_kw == name or norm_kw == name_jp or
                        norm_kw in name or name in norm_kw or
                        norm_kw in name_jp or name_jp in norm_kw):
                        matched.append(job)
                filtered_out = len(jobs) - len(matched)
                if filtered_out:
                    logger.info(
                        f"[{self.name}] Company filter: {len(matched)} match "
                        f"'{company_keyword}', {filtered_out} filtered out"
                    )
                jobs = matched

            # ── Incremental: classify jobs before saving ──
            from db.jobs import get_job_by_source_id

            new_jobs = []          # Not in DB → full pipeline
            incomplete_jobs = []   # In DB but missing fields → partial enrich
            skipped = 0            # In DB and complete → skip entirely

            for job in jobs:
                source_id = job.get('source_id', '')
                source = job.get('source', self.name)
                db_record = get_job_by_source_id(source_id, source) if source_id else None

                if not db_record:
                    new_jobs.append(job)
                elif self._is_data_complete(db_record):
                    skipped += 1
                else:
                    incomplete_jobs.append(job)

            result['jobs_skipped'] = skipped
            result['jobs_incomplete'] = len(incomplete_jobs)

            logger.info(
                f"[{self.name}] Incremental: {len(new_jobs)} new, "
                f"{len(incomplete_jobs)} incomplete, {skipped} skipped (complete)"
            )

            # Merge: process new jobs first, then incomplete ones
            to_process = new_jobs + incomplete_jobs

            # Limit results if max_results is set (e.g. email_backfill mode)
            if max_results > 0 and len(to_process) > max_results:
                logger.info(
                    f"[{self.name}] Limiting to {max_results} results "
                    f"(was {len(to_process)})"
                )
                to_process = to_process[:max_results]

            # ── Save each job immediately (no AI, fast) ──
            from database import upsert_job_from_scraper
            new_count = 0
            ai_enqueue_ids = []  # Job IDs that need AI enrichment

            for i, job in enumerate(to_process):
                company = job.get('company_name', '?')

                # Backfill mode: do NOT save to DB — just collect raw data
                # for merge_backfill_results() to merge directly into email job.
                # This prevents creating extra scraper-sourced records.
                if company_keyword:
                    result.setdefault('backfill_data', []).append(job)
                    logger.info(
                        f"[{self.name}] [{i+1}/{len(to_process)}] {company}: "
                        f"collected for backfill (not saved)"
                    )
                    continue

                # Normal mode: save immediately (raw data only)
                job_id, is_new = upsert_job_from_scraper(job)
                if is_new:
                    new_count += 1

                # Queue for AI detail enrichment if data is incomplete
                if is_new or not self._is_data_complete(job):
                    ai_enqueue_ids.append(job_id)

                logger.info(
                    f"[{self.name}] [{i+1}/{len(to_process)}] {company}: "
                    f"{'NEW' if is_new else 'updated'}"
                )

            # ── Enqueue AI detail enrichment tasks ──
            enqueued = 0
            if ai_enqueue_ids:
                try:
                    from db.task_queue import enqueue
                    for job_id in ai_enqueue_ids:
                        enqueue(
                            'detail_enrich',
                            priority=4,
                            params={'job_id': job_id}
                        )
                        enqueued += 1
                    logger.info(
                        f"[{self.name}] Enqueued {enqueued} detail_enrich tasks"
                    )
                except Exception as e:
                    logger.warning(
                        f"[{self.name}] Failed to enqueue AI tasks: {e}"
                    )

            result['jobs_updated'] = new_count
            result['jobs_enqueued_for_ai'] = enqueued
            result['status'] = 'success'
            logger.info(
                f"[{self.name}] Pipeline complete: {len(jobs)} found, "
                f"{new_count} new, {enqueued} queued for AI, "
                f"{skipped} skipped (already complete)"
            )

        except Exception as e:
            result['error_message'] = str(e)
            logger.exception(f"[{self.name}] Pipeline error: {e}")
        finally:
            if self.browser:
                await self.browser.close()

        return result

    async def run(self) -> dict:
        """Run the full scraping pipeline."""
        return await self._run_pipeline(self.fetch_jobs)

    async def run_search(self, keywords: list, filters: dict = None,
                         max_results: int = 0,
                         company_keyword: str = '') -> dict:
        """Run the keyword search pipeline.

        Args:
            max_results: if > 0, only process this many results.
            company_keyword: if set, only save results matching this company.
        """
        return await self._run_pipeline(
            self.search_jobs, keywords, filters,
            max_results=max_results, company_keyword=company_keyword
        )
