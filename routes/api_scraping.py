"""API routes for Scraping and Cookie Login.

Consolidates all per-site scraping triggers into a generic dispatcher
and provides a cookie-login endpoint for any registered site.
"""
import os
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

scraping_bp = Blueprint('scraping', __name__)


# ── Generic scrape endpoint ─────────────────────────────────────────

@scraping_bp.route('/api/scrape/<site>', methods=['POST'])
def api_scrape(site):
    """Trigger scraping for a specific site."""
    if site == 'search':
        return _api_scrape_search()

    from scrapers import get_scraper_names, dispatch

    if site not in get_scraper_names():
        logger.warning(f"[scraping] Unknown site requested: {site}")
        return jsonify({'error': f'Unknown site: {site}'}), 400

    logger.info(f"[scraping] Starting scrape for site={site}")
    try:
        result = dispatch(action='fetch', mode='one_shot', scrapers=[site])
        logger.info(
            f"[scraping] Completed site={site}: "
            f"found={result['total_found']}, new={result['total_new']}"
        )
        # Return first per-scraper result if available
        if result.get('results'):
            return jsonify(result['results'][0])
        return jsonify(result)
    except Exception as e:
        logger.exception(f"[scraping] Error scraping {site}: {e}")
        return jsonify({'error': str(e)}), 500


def _api_scrape_search():
    """Run keyword search across all registered scrapers."""
    try:
        from database import get_preferences
        from scrapers import dispatch

        keywords_data = get_preferences(enabled_only=True)
        keywords = [p['keyword'] for p in keywords_data]
        logger.info(f"[scraping] Search request with keywords={keywords}")

        if not keywords:
            return jsonify({
                'error': '興味分野が設定されていません。設定ページでキーワードを追加してください。'
            }), 400

        result = dispatch(
            action='search', mode='one_shot', keywords=keywords,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Cookie login ────────────────────────────────────────────────────

@scraping_bp.route('/api/login/<site>', methods=['POST'])
def api_cookie_login(site):
    """Open a visible browser for user to login and save cookies."""
    from scrapers import get_login_urls

    login_urls = get_login_urls()
    if site not in login_urls:
        return jsonify({'error': f'Unknown site: {site}'}), 400

    login_url = login_urls[site]

    def _do_login():
        import asyncio
        from playwright.async_api import async_playwright

        async def _run():
            pw = await async_playwright().start()
            from config import Config
            from scrapers.stealth import create_context_options, apply_stealth
            state_file = os.path.join(Config.BASE_DIR, 'data', f'{site}_state.json')

            ctx_args = create_context_options()
            if os.path.exists(state_file):
                ctx_args['storage_state'] = state_file

            browser = await pw.chromium.launch(headless=False)
            ctx = await browser.new_context(**ctx_args)
            page = await ctx.new_page()
            await apply_stealth(page)

            await page.goto(login_url, wait_until='domcontentloaded', timeout=15000)

            try:
                await page.wait_for_event('close', timeout=600000)
            except Exception:
                pass

            try:
                os.makedirs(os.path.dirname(state_file), exist_ok=True)
                await ctx.storage_state(path=state_file)
                logger.info(f"[cookie-login] Saved cookies for {site}")
            except Exception:
                pass

            try:
                await browser.close()
            except Exception:
                pass
            await pw.stop()
            return True

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()

    try:
        from threading import Thread
        thread = Thread(target=_do_login, daemon=True)
        thread.start()
        return jsonify({
            'status': 'success',
            'message': f'{site} のログインブラウザを開きました。ログイン後、自動的にCookieが保存されます。'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── MyNavi manual login ─────────────────────────────────────────────

@scraping_bp.route('/api/mynavi/manual-login', methods=['POST'])
def api_manual_login():
    """Open a visible browser for the user to log in manually to マイナビ."""
    import asyncio

    async def do_manual_login():
        from playwright.async_api import async_playwright
        from config import Config

        from scrapers.stealth import create_context_options, apply_stealth

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        ctx_args = create_context_options()
        ctx_args['locale'] = Config.BROWSER_LOCALE
        context = await browser.new_context(**ctx_args)
        page = await context.new_page()
        await apply_stealth(page)

        mynavi_year = Config.MYNAVI_YEAR
        login_url = f"https://job.mynavi.jp/{mynavi_year}/pc/common/displayRelayScreen/displayForLogin"
        mypage_url = f"https://job.mynavi.jp/{mynavi_year}/mypage"

        logger.info("Manual login: Opening browser...")
        await page.goto(login_url, wait_until='domcontentloaded', timeout=30000)

        logger.info("Manual login: Waiting for user to complete login (up to 10 min)...")
        login_success = False
        for attempt in range(120):
            await page.wait_for_timeout(5000)
            current_url = page.url

            if 'mcid.mynavi.jp' not in current_url and 'memberLogin' not in current_url and 'login' not in current_url.lower():
                login_success = True
                logger.info(f"Manual login: User logged in! URL: {current_url}")
                break

            if attempt % 6 == 0:
                logger.info(f"Manual login: Still waiting... ({attempt * 5}s / 600s)")

        if login_success:
            await page.goto(mypage_url, wait_until='domcontentloaded', timeout=15000)
            await page.wait_for_timeout(2000)

            state_file = os.path.join(Config.BASE_DIR, 'data', 'mynavi_state.json')
            await context.storage_state(path=state_file)
            logger.info(f"Manual login: Browser state saved to {state_file}")

        await browser.close()
        return login_success

    try:
        result = asyncio.run(do_manual_login())
        if result:
            return jsonify({'message': 'ログイン成功！Cookieを保存しました。今後の同期は自動的にログインします。'})
        else:
            return jsonify({'error': 'ログインがタイムアウトしました（10分）。もう一度お試しください。'}), 408
    except Exception as e:
        logger.exception(f"Manual login error: {e}")
        return jsonify({'error': f'エラー: {str(e)}'}), 500
