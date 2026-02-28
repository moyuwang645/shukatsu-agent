"""Debug: check what JS extraction sees on the engineer page."""
import asyncio
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    state_file = os.path.join('data', 'gaishishukatsu_state.json')
    ctx_args = {'locale': 'ja-JP', 'timezone_id': 'Asia/Tokyo'}
    if os.path.exists(state_file):
        ctx_args['storage_state'] = state_file
    ctx = await browser.new_context(**ctx_args)
    page = await ctx.new_page()

    # Login
    email = os.getenv('GAISHI_EMAIL', '')
    password = os.getenv('GAISHI_PASSWORD', '')
    await page.goto('https://gaishishukatsu.com/login', wait_until='domcontentloaded', timeout=15000)
    await page.wait_for_timeout(1500)
    if '/login' in page.url:
        await page.locator('input[name="email"], input[type="email"]').first.fill(email)
        await page.locator('input[name="password"], input[type="password"]').first.fill(password)
        await page.locator('button[type="submit"], input[type="submit"]').first.click()
        await page.wait_for_timeout(3000)
    print(f'Logged in: {page.url}')

    # Navigate to engineer page with deadline sort
    await page.goto(
        'https://gaishishukatsu.com/engineer/recruiting_info?order=deadline',
        wait_until='domcontentloaded', timeout=20000
    )
    try:
        await page.wait_for_selector('tr a[href*="recruiting_info"]', timeout=15000)
    except:
        print('Selector timeout!')
    await page.wait_for_timeout(3000)

    # Test JS extraction
    result = await page.evaluate("""() => {
        const debug = [];
        const rows = document.querySelectorAll('tr');
        debug.push('Total rows: ' + rows.length);
        
        let foundLinks = 0;
        for (const row of rows) {
            // Check all links in the row
            const allLinks = row.querySelectorAll('a[href]');
            for (const a of allLinks) {
                const href = a.getAttribute('href');
                if (href && href.includes('recruiting_info')) {
                    debug.push('LINK: ' + href);
                    foundLinks++;
                }
            }
            
            // Also try CSS query for specific selector
            const ri = row.querySelector('a[href*="recruiting_info/view"]');
            if (ri) {
                debug.push('  MATCH: a[href*="recruiting_info/view"] -> ' + ri.getAttribute('href'));
            }
            
            if (foundLinks >= 5) break;
        }
        debug.push('Total links with recruiting_info: ' + foundLinks);
        
        // Also check ALL links on the page
        const pageLinks = document.querySelectorAll('a[href*="recruiting_info"]');
        debug.push('Page-wide recruiting_info links: ' + pageLinks.length);
        for (let i = 0; i < Math.min(5, pageLinks.length); i++) {
            debug.push('  PAGE_LINK: ' + pageLinks[i].getAttribute('href'));
        }
        
        return debug;
    }""")

    for line in result:
        print(line)

    await browser.close()
    await pw.stop()

asyncio.run(main())
