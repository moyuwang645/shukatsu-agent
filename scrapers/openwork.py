"""OpenWork scraper — fetch company scores from openwork.jp.

Uses Playwright to search for companies and extract:
- Overall rating (総合評価)
- 8 sub-category scores
- Basic company info

The scraper does NOT require login — it reads publicly visible data
from search result listings and company detail pages.
"""
import asyncio
import json
import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)

# The 8 sub-score categories in display order on OpenWork
SUB_SCORE_LABELS = [
    '待遇面の満足度',
    '社員の士気',
    '風通しの良さ',
    '社員の相互尊重',
    '20代成長環境',
    '人材の長期育成',
    '法令順守意識',
    '人事評価の適正感',
]


async def _fetch_scores(company_name: str) -> dict | None:
    """Search OpenWork for a company and extract scores."""
    from playwright.async_api import async_playwright
    from config import Config

    encoded = urllib.parse.quote(company_name)
    search_url = f"https://www.openwork.jp/company_list?src_str={encoded}&sort=1"

    result = None

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=Config.HEADLESS)
        from scrapers.stealth import create_context_options, apply_stealth, random_delay

        context = await browser.new_context(**create_context_options())
        page = await context.new_page()
        await apply_stealth(page)

        # ── Step 1: Search page ──
        logger.info(f"[openwork] Searching: {company_name}")
        await page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
        await random_delay(2000, 4000)

        # Check for block
        content = await page.content()
        if 'アクセスが制限' in content:
            logger.warning("[openwork] Access restricted")
            await browser.close()
            await pw.stop()
            return None

        # Find company links
        company_links = await page.query_selector_all('a[href*="company.php?m_id="]')
        if not company_links:
            logger.warning(f"[openwork] No results for: {company_name}")
            await browser.close()
            await pw.stop()
            return None

        logger.info(f"[openwork] Found {len(company_links)} company links")

        # Match the best company link (fuzzy)
        best_link = None
        best_name = None
        clean_search = re.sub(r'(株式会社|有限会社|合同会社)', '', company_name).strip()

        for link in company_links:
            text = (await link.inner_text()).strip().split('\n')[0].strip()
            clean_found = re.sub(r'(株式会社|有限会社|合同会社)', '', text).strip()
            if clean_search in clean_found or clean_found in clean_search:
                best_link = await link.get_attribute('href')
                best_name = text
                break

        if not best_link:
            # Fall back to first result
            best_link = await company_links[0].get_attribute('href')
            best_name = (await company_links[0].inner_text()).strip().split('\n')[0].strip()
            logger.info(f"[openwork] No exact match, using first: {best_name}")

        # Extract overall score from search results page
        # Selector: .totalEvaluation_item (contains score like "4.15")
        overall_score = None
        score_els = await page.query_selector_all('.totalEvaluation_item')
        if score_els:
            first_score_text = await score_els[0].inner_text()
            match = re.search(r'(\d\.\d{1,2})', first_score_text)
            if match:
                overall_score = float(match.group(1))
                logger.info(f"[openwork] Overall score from search: {overall_score}")

        # ── Step 2: Detail page for sub-scores ──
        if best_link.startswith('/'):
            best_link = f"https://www.openwork.jp{best_link}"

        logger.info(f"[openwork] Detail page: {best_link}")
        await page.goto(best_link, wait_until='domcontentloaded', timeout=15000)
        await random_delay(2000, 4000)

        detail_content = await page.content()

        # Extract overall from detail page if not found in search
        if overall_score is None:
            overall_match = re.search(r'class="fw-b"[^>]*>(\d\.\d{1,2})', detail_content)
            if overall_match:
                overall_score = float(overall_match.group(1))

        # Extract 8 sub-scores from detail page
        # They appear in class="fs-14 lh-1" elements in the order of SUB_SCORE_LABELS
        sub_score_values = re.findall(r'class="fs-14 lh-1"[^>]*>(\d\.\d)', detail_content)
        sub_scores = {}
        for i, label in enumerate(SUB_SCORE_LABELS):
            if i < len(sub_score_values):
                sub_scores[label] = float(sub_score_values[i])

        if sub_scores:
            logger.info(f"[openwork] Sub-scores: {len(sub_scores)}/8")
        else:
            logger.warning("[openwork] No sub-scores found (may need login)")

        result = {
            'company_name': best_name or company_name,
            'overall_score': overall_score,
            'sub_scores': sub_scores,
            'review_summary': '',  # Placeholder for future
            'source_url': best_link,
        }

        await browser.close()
        await pw.stop()

    except Exception as e:
        logger.exception(f"[openwork] Scraping failed for {company_name}: {e}")
        # Ensure Playwright is cleaned up even on error
        try:
            if 'pw' in dir() and pw:
                await pw.stop()
        except Exception:
            pass

    return result


def fetch_company_scores(company_name: str) -> dict | None:
    """Synchronous wrapper to fetch OpenWork scores for a company.

    Returns a dict with keys:
        company_name, overall_score, sub_scores (dict of 8 items),
        review_summary, source_url
    Or None if the company was not found or scraping failed.
    """
    from db.openwork import get_openwork_data, is_cache_fresh, cache_openwork_data

    # Check cache first (valid for 7 days)
    if is_cache_fresh(company_name):
        cached = get_openwork_data(company_name)
        if cached:
            logger.info(f"[openwork] Cache hit: {company_name}")
            return cached

    # Fetch from OpenWork
    logger.info(f"[openwork] Fetching: {company_name}")
    try:
        result = asyncio.run(_fetch_scores(company_name))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_fetch_scores(company_name))
        loop.close()

    if result and result.get('overall_score'):
        cache_openwork_data(
            company_name=company_name,
            overall_score=result['overall_score'],
            sub_scores=result.get('sub_scores', {}),
            review_summary=result.get('review_summary', '')
        )
        logger.info(f"[openwork] Cached: {company_name} ({result['overall_score']})")

    return result
