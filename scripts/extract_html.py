import asyncio
import os
import json
from playwright.async_api import async_playwright

async def dump_pages():
    pw = await async_playwright().start()
    
    state_file = 'data/mynavi_state.json'
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(
        storage_state=state_file,
        locale='ja-JP',
        timezone_id='Asia/Tokyo',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    )
    page = await context.new_page()

    responses = {}
    
    async def log_response(response):
        if 'application/json' in response.headers.get('content-type', '') or 'text/html' in response.headers.get('content-type', ''):
            if 'mynavi' in response.url:
                try:
                    text = await response.text()
                    responses[response.url] = text
                    print(f"Captured: {response.url} ({len(text)} bytes)")
                except Exception:
                    pass

    page.on('response', log_response)

    print("Navigating to top page...")
    await page.goto("https://job.mynavi.jp/27/pc/", wait_until='domcontentloaded')
    
    # Wait for things to settle
    await page.wait_for_timeout(3000)

    print("Navigating to Entries...")
    entry_url = "https://job.mynavi.jp/27/pc/user/displayAppliedEntryCorpList/index?selected=all"
    await page.goto(entry_url, wait_until='domcontentloaded')
    
    # Wait for API requests to complete
    await page.wait_for_timeout(8000)
    
    with open('data/responses.json', 'w', encoding='utf-8') as f:
        json.dump(responses, f, ensure_ascii=False, indent=2)
        
    print("Done. Saved network responses.")

    await browser.close()
    await pw.stop()

if __name__ == '__main__':
    asyncio.run(dump_pages())
