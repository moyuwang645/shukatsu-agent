import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from config import Config
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

COOKIE_FILE = os.path.join(Config.BASE_DIR, 'data', 'mynavi_cookies.json')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)

        corp_id = "88256"
        url = f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/pc/search/corp88256/outline.html"
        
        print(f"Fetching {url}...")
        response = await ctx.request.get(url)
        html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        data = {}
        # Mynavi outline tables often use class corpinfo-th / corpinfo-td, or just plain th/td
        for th in soup.find_all('th'):
            text = th.get_text(strip=True)
            td = th.find_next_sibling('td')
            if td:
                td_text = '\n'.join(list(td.stripped_strings))
                data[text] = td_text

        print(f"Extracted {len(data)} fields.")
        
        # We need Position (職種), Description (仕事内容, 事業内容), Location (勤務地), Deadline
        def get_field(*keywords):
            for k, v in data.items():
                if any(kw in k for kw in keywords):
                    return v.strip()
            return ""

        position = get_field('募集職種', '職種')
        desc = get_field('仕事内容', '事業内容', '募集対象')
        location = get_field('勤務地', '本社')
        deadline = get_field('エントリー', '締切', '期間')

        print(f"--- Position ---\n{position[:100]}\n")
        print(f"--- Description ---\n{desc[:100]}\n")
        print(f"--- Location ---\n{location[:100]}\n")
        print(f"--- Deadline ---\n{deadline[:100]}\n")
        
        # Test full page deadline scan
        full_text = soup.get_text()
        print(f"Full text length: {len(full_text)}")
        
        await browser.close()

asyncio.run(main())
