"""Entry Bot — automated form filling for job applications.

Uses Playwright to navigate to entry pages and fill in ES content.
Supports dry_run mode (fill but don't submit) for safety.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def _fill_form(job_url: str, es_data: dict, dry_run: bool = True) -> dict:
    """Navigate to an entry form page and fill in ES data.

    Args:
        job_url: URL of the job entry page.
        es_data: dict with custom_self_pr, custom_motivation, etc.
        dry_run: If True, fill forms but do NOT click submit.

    Returns:
        dict with status, message, and optional screenshot paths.
    """
    from playwright.async_api import async_playwright
    from config import Config
    from scrapers.stealth import create_context_options, apply_stealth, random_delay

    result = {
        'status': 'error',
        'message': '',
        'screenshots': [],
        'dry_run': dry_run,
    }

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=Config.HEADLESS)
        context = await browser.new_context(**create_context_options())
        page = await context.new_page()
        await apply_stealth(page)

        # Load saved cookies if available (e.g. for MyNavi/OneCareer login)
        state_file = os.path.join(Config.BASE_DIR, 'data', 'entry_bot_state.json')
        if os.path.exists(state_file):
            # Re-create context with saved state
            await browser.close()
            browser = await pw.chromium.launch(headless=Config.HEADLESS)
            ctx_args = create_context_options()
            ctx_args['storage_state'] = state_file
            context = await browser.new_context(**ctx_args)
            page = await context.new_page()
            await apply_stealth(page)
            logger.info("[entry_bot] Loaded saved browser state")

        # Navigate to the entry page
        logger.info(f"[entry_bot] Navigating to: {job_url}")
        await page.goto(job_url, wait_until='domcontentloaded', timeout=20000)
        await random_delay(2000, 3000)

        # Detect form fields — try common selectors for Japanese job sites
        textarea_selectors = [
            'textarea[name*="pr"]', 'textarea[name*="PR"]',
            'textarea[name*="motivation"]', 'textarea[name*="志望"]',
            'textarea[name*="self"]', 'textarea[name*="自己"]',
            'textarea',  # fallback: any textarea
        ]

        filled_count = 0
        fields_to_fill = {
            'self_pr': es_data.get('custom_self_pr', '') or es_data.get('self_pr', ''),
            'motivation': es_data.get('custom_motivation', '') or es_data.get('motivation', ''),
        }

        for field_name, field_value in fields_to_fill.items():
            if not field_value:
                continue

            for sel in textarea_selectors:
                try:
                    elements = await page.query_selector_all(sel)
                    for el in elements:
                        # Check if this textarea is empty and visible
                        current_val = await el.input_value()
                        is_visible = await el.is_visible()
                        if is_visible and not current_val.strip():
                            await el.fill(field_value)
                            filled_count += 1
                            logger.info(f"[entry_bot] Filled {field_name} into {sel} "
                                         f"({len(field_value)} chars)")
                            break
                    if filled_count > 0:
                        break
                except Exception:
                    continue

        # Take screenshot of the filled form
        screenshot_dir = os.path.join(Config.BASE_DIR, 'data', 'screenshots')
        os.makedirs(screenshot_dir, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        screenshot_path = os.path.join(screenshot_dir, f'entry_{ts}.png')

        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            result['screenshots'].append(screenshot_path)
            logger.info(f"[entry_bot] Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.warning(f"[entry_bot] Screenshot failed: {e}")

        if dry_run:
            result['status'] = 'filled'
            result['message'] = (f'ドライラン完了: {filled_count}件のフィールドに入力済み。'
                                  'Submit は実行されていません。')
            logger.info(f"[entry_bot] Dry run complete: {filled_count} fields filled")
        else:
            # Look for submit button
            submit_selectors = [
                'button[type="submit"]', 'input[type="submit"]',
                'button:has-text("送信")', 'button:has-text("エントリー")',
                'button:has-text("応募")', 'a:has-text("確認")',
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await random_delay(2000, 4000)
                        submitted = True
                        logger.info(f"[entry_bot] Submitted via {sel}")
                        break
                except Exception:
                    continue

            if submitted:
                result['status'] = 'submitted'
                result['message'] = f'エントリー送信完了: {filled_count}件のフィールドに入力。'
            else:
                result['status'] = 'filled'
                result['message'] = f'フィールド入力完了({filled_count}件)だが、送信ボタンが見つかりませんでした。'

        await browser.close()
        await pw.stop()

    except Exception as e:
        result['message'] = str(e)
        logger.exception(f"[entry_bot] Error: {e}")

    return result


def auto_fill_form(job_url: str, es_data: dict, dry_run: bool = True) -> dict:
    """Synchronous wrapper for the form filler.

    Args:
        job_url: URL of the entry/application page.
        es_data: dict containing self_pr, motivation, or custom versions.
        dry_run: If True (default), fill forms but do NOT submit.

    Returns:
        dict with status ('filled', 'submitted', 'error'), message, screenshots.
    """
    logger.info(f"[entry_bot] Starting {'dry run' if dry_run else 'LIVE'} for: {job_url}")

    try:
        result = asyncio.run(_fill_form(job_url, es_data, dry_run))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_fill_form(job_url, es_data, dry_run))
        loop.close()

    return result
