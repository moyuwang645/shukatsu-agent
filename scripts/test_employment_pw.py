import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from config import Config
from playwright.async_api import async_playwright

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
        url = f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/pc/corpinfo/displayEmployment/index?corpId={corp_id}"
        page = await ctx.new_page()
        print(f"Loading {url}...")
        await page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Use JS to extract all th/td pairs
        data = await page.evaluate('''() => {
            const table = document.querySelector('table');
            if (!table) return {error: "No table found"};
            const result = {};
            document.querySelectorAll('th').forEach(th => {
                const td = th.nextElementSibling;
                if (td) result[th.innerText.trim()] = td.innerText.trim();
            });
            return result;
        }''')
        
        print("Data extacted via JS:")
        for k, v in data.items():
            if 'error' in k:
                print(f"Error: {v}")
                break
            if '募集職種' in k or '仕事内容' in k or '勤務地' in k or '締切' in k or '期間' in k:
                print(f"[{k}]\n{v[:200]}...")
        
        await browser.close()

asyncio.run(main())
