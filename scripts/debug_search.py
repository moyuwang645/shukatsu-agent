"""
Debug: visit MyNavi search results with logged-in session and dump what's on the page.
Run with: python debug_search.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from playwright.async_api import async_playwright


COOKIE_FILE = os.path.join(Config.BASE_DIR, 'data', 'mynavi_cookies.json')
YEAR = Config.MYNAVI_YEAR


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()

        # Load saved cookies
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)
            print(f"Loaded {len(cookies)} cookies")
        else:
            print("No cookie file found – may not be logged in")

        page = await ctx.new_page()

        # ---- Test 1: direct cond=FW: URL ----
        url1 = f"https://job.mynavi.jp/{YEAR}/pc/corpinfo/searchCorpListByGenCond/index/?cond=FW:IT/func=PCTopQuickSearch/FWTGT:1"
        print(f"\n=== Test 1: Direct URL ===\n{url1}")
        await page.goto(url1, wait_until='networkidle', timeout=40000)
        body1 = await page.locator('body').inner_text()
        print(f"Title: {await page.title()}")
        print(f"URL after: {page.url}")
        print(f"Body (first 500):\n{body1[:500]}")
        links1 = await page.locator('a.js-add-examination-list-text').count()
        print(f"js-add-examination-list-text: {links1}")
        corp_links = await page.locator('a[href*="/pc/search/corp"]').count()
        print(f'a[href*="/pc/search/corp"]: {corp_links}')

        # ---- Test 2: top-page form submit ----
        print(f"\n=== Test 2: Form submit from top page ===")
        top_url = f"https://job.mynavi.jp/{YEAR}/"
        await page.goto(top_url, wait_until='networkidle', timeout=40000)
        print(f"Top page title: {await page.title()}")

        # Find search input
        for sel in ['input[name="freeKeyword"]', 'input[placeholder*="フリーワード"]',
                    'input[placeholder*="キーワード"]', 'input[type="text"]']:
            loc = page.locator(sel)
            cnt = await loc.count()
            if cnt > 0:
                print(f"Found input: {sel} ({cnt} elements)")
                await loc.first.fill('IT')
                await page.wait_for_timeout(500)
                await loc.first.press('Enter')
                await page.wait_for_load_state('networkidle', timeout=30000)
                break

        print(f"After form submit: {page.url}")
        print(f"Title: {await page.title()}")
        body2 = await page.locator('body').inner_text()
        print(f"Body (first 500):\n{body2[:500]}")
        links2 = await page.locator('a.js-add-examination-list-text').count()
        print(f"js-add-examination-list-text: {links2}")
        corp_links2 = await page.locator('a[href*="/pc/search/corp"]').count()
        print(f'a[href*="/pc/search/corp"]: {corp_links2}')

        # Sample links
        if links2 > 0:
            for i in range(min(links2, 3)):
                lnk = page.locator('a.js-add-examination-list-text').nth(i)
                print(f"  Link {i}: {await lnk.inner_text()} -> {await lnk.get_attribute('href')}")

        await browser.close()


asyncio.run(main())
