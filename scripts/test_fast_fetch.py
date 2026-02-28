import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from playwright.async_api import async_playwright
try:
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'beautifulsoup4'])
    from bs4 import BeautifulSoup

COOKIE_FILE = os.path.join(Config.BASE_DIR, 'data', 'mynavi_cookies.json')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()

        # Load saved cookies
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)

        corp_id = "88256" # (株)第四北越ITソリューションズ
        emp_url = f"https://job.mynavi.jp/{Config.MYNAVI_YEAR}/pc/corpinfo/displayEmployment/index?corpId={corp_id}"
        
        print(f"Fetching {emp_url}...")
        response = await ctx.request.get(emp_url)
        html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # In MyNavi, employment info is generally in tables with th and td
        data = {}
        for th in soup.find_all('th'):
            text = th.get_text(strip=True)
            td = th.find_next_sibling('td')
            if td:
                # Add newline instead of smashing paragraphs together
                td_text = '\n'.join(list(td.stripped_strings))
                data[text] = td_text
        
        # Print a few matches
        print("Keys extracted:", list(data.keys()))
        
        # Find specific fields
        for k in data:
            if '募集職種' in k:
                print("\n[募集職種]\n", data[k])
            elif '仕事内容' in k or '業務内容' in k:
                print("\n[仕事内容]\n", data[k][:200] + '...')
            elif '勤務地' in k:
                print("\n[勤務地]\n", data[k])
            elif 'エントリー' in k and '締' in k:
                print("\n[締切]\n", data[k])

        await browser.close()

asyncio.run(main())
