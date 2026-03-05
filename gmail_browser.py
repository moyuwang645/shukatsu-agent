"""Gmail browser-based email fetcher — uses Playwright cookies instead of OAuth2.

Opens Gmail in a REAL Chrome/Edge browser (not Playwright Chromium),
saves cookies, and scrapes recent emails from the Gmail web interface.
No Google Cloud credentials needed.
"""
import asyncio
import os
import re
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

GMAIL_URL = "https://mail.google.com/mail/u/0/"
GMAIL_STATE_FILE = os.path.join(Config.BASE_DIR, 'data', 'gmail_state.json')
# Persistent browser profile directory — keeps cookies between sessions
GMAIL_PROFILE_DIR = os.path.join(Config.BASE_DIR, 'data', 'gmail_profile')


def gmail_cookie_login():
    """Open a REAL browser (Edge/Chrome) for user to log into Gmail.
    Uses persistent_context so cookies are saved automatically.
    Returns (True, message) or (False, error).
    """
    try:
        from playwright.sync_api import sync_playwright

        os.makedirs(GMAIL_PROFILE_DIR, exist_ok=True)

        pw = sync_playwright().start()

        # Use real Edge or Chrome — Google trusts these, not Playwright Chromium
        # persistent_context keeps all cookies in the profile dir
        ctx = None
        for channel in ('msedge', 'chrome', None):
            try:
                kwargs = dict(
                    user_data_dir=GMAIL_PROFILE_DIR,
                    headless=False,
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )
                if channel:
                    kwargs['channel'] = channel
                ctx = pw.chromium.launch_persistent_context(**kwargs)
                break
            except Exception:
                continue

        if not ctx:
            pw.stop()
            return False, 'ブラウザの起動に失敗しました'

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(GMAIL_URL, wait_until='domcontentloaded', timeout=20000)

        # Wait for user to log in (max 180 seconds)
        logged_in = False
        for _ in range(90):
            page.wait_for_timeout(2000)
            url = page.url
            if 'mail.google.com' in url and 'accounts.google.com' not in url:
                # Extra wait for Gmail to fully load
                page.wait_for_timeout(3000)
                logged_in = True
                break

        # Also save storage_state for the fetch function
        if logged_in:
            os.makedirs(os.path.dirname(GMAIL_STATE_FILE), exist_ok=True)
            ctx.storage_state(path=GMAIL_STATE_FILE)
            logger.info("[gmail-browser] Login successful, cookies saved")

        ctx.close()
        pw.stop()

        if logged_in:
            return True, 'Gmail cookies saved — ブラウザログイン完了'
        return False, 'ログインがタイムアウトしました'
    except Exception as e:
        logger.exception(f"[gmail-browser] Login error: {e}")
        return False, str(e)


def fetch_emails_by_search(query: str = '', max_results: int = 0):
    """Unified Gmail browser fetch — supports any Gmail search query.

    Args:
        query: Gmail search query (e.g. 'after:2026/02/01', '三菱商事', 'is:unread').
               Empty string fetches inbox.
        max_results: Max emails to return. 0 = unlimited (scroll to load all).

    Returns:
        List of email dicts compatible with the rest of the app.
    """
    if not os.path.exists(GMAIL_PROFILE_DIR):
        logger.warning("[gmail-browser] No saved profile — please login first")
        return []

    async def _run():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()

        # Launch browser with persistent context
        ctx = None
        for channel in ('msedge', 'chrome', None):
            try:
                kwargs = dict(
                    user_data_dir=GMAIL_PROFILE_DIR,
                    headless=True,
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )
                if channel:
                    kwargs['channel'] = channel
                ctx = await pw.chromium.launch_persistent_context(**kwargs)
                break
            except Exception:
                continue

        if not ctx:
            await pw.stop()
            return []

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            # Navigate to Gmail with search query
            if query:
                target_url = f"{GMAIL_URL}#search/{query}"
            else:
                target_url = GMAIL_URL

            await page.goto(target_url, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(4000)

            # Check if we're logged in
            if 'accounts.google.com' in page.url or '/signin' in page.url:
                logger.error("[gmail-browser] Not logged in — cookies expired")
                return []

            logger.info(f"[gmail-browser] Page loaded: {page.url}")

            # Wait for results to render
            try:
                await page.wait_for_selector('tr.zA', timeout=15000)
            except Exception:
                logger.warning("[gmail-browser] No email rows found")
                return []

            await page.wait_for_timeout(2000)

            # Scroll to load all results (Gmail lazy-loads ~50 rows at a time)
            # If max_results > 0, stop when we have enough
            prev_count = 0
            no_change_rounds = 0
            max_scroll_rounds = 50  # Safety limit

            for scroll_round in range(max_scroll_rounds):
                current_count = await page.evaluate(
                    "document.querySelectorAll('tr.zA').length"
                )

                # If we have a limit and we've loaded enough, stop
                if max_results > 0 and current_count >= max_results:
                    logger.info(
                        f"[gmail-browser] Loaded {current_count} rows "
                        f"(limit: {max_results}), stopping scroll"
                    )
                    break

                if current_count == prev_count:
                    no_change_rounds += 1
                    if no_change_rounds >= 2:
                        break  # No new rows after 2 scrolls — all loaded
                else:
                    no_change_rounds = 0

                prev_count = current_count

                # Scroll to trigger lazy-loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                if scroll_round % 5 == 0 and scroll_round > 0:
                    logger.info(
                        f"[gmail-browser] Scroll round {scroll_round + 1}: "
                        f"{current_count} emails loaded"
                    )

            final_count = await page.evaluate(
                "document.querySelectorAll('tr.zA').length"
            )
            logger.info(f"[gmail-browser] Total rows loaded: {final_count}")

            # Extract email rows via JS
            extract_limit = max_results if max_results > 0 else 0
            emails = await page.evaluate('''(limit) => {
                const emails = [];
                const rows = document.querySelectorAll('tr.zA');

                for (const row of rows) {
                    if (limit > 0 && emails.length >= limit) break;

                    const senderEl = row.querySelector('.yX .yW span[email], .yX .yW span[name]');
                    const sender = senderEl
                        ? (senderEl.getAttribute('email') || senderEl.getAttribute('name') || senderEl.textContent.trim())
                        : '';

                    const subjectEl = row.querySelector('.y6 span[data-thread-id], .y6 span.bog, .y6');
                    const subject = subjectEl ? subjectEl.textContent.trim() : '';

                    const snippetEl = row.querySelector('.y2');
                    const snippet = snippetEl ? snippetEl.textContent.replace(/^\\s*[-–—]\\s*/, '').trim() : '';

                    const dateEl = row.querySelector('.xW span[title], td.xW');
                    const dateText = dateEl ? (dateEl.getAttribute('title') || dateEl.textContent.trim()) : '';

                    const threadId = row.getAttribute('data-legacy-thread-id')
                        || row.querySelector('[data-thread-id]')?.getAttribute('data-thread-id')
                        || `browser_${emails.length}_${Date.now()}`;

                    const isUnread = row.classList.contains('zE');

                    if (sender || subject) {
                        emails.push({
                            gmail_id: threadId,
                            sender: sender,
                            subject: subject,
                            body_preview: snippet.substring(0, 500),
                            date_text: dateText,
                            is_unread: isUnread,
                        });
                    }
                }
                return emails;
            }''', extract_limit)

            logger.info(f"[gmail-browser] Extracted {len(emails)} emails")

            # --- Open job-related emails to get full body text ---
            job_kw_check = [
                '面接', '面談', '選考', 'ES', 'エントリー', '説明会',
                '書類', '内定', '一次', '二次', '最終', '適性検査',
                'Webテスト', '締切', '締め切り', '〆切', '提出',
                '日程', '予約', 'GD', 'グループディスカッション',
                '応募', 'マイナビ', 'リクナビ', '就活',
                'マイページ', 'mypage', 'MyPage', 'パスワード',
            ]
            job_email_indices = []
            for i, e in enumerate(emails):
                combined = f"{e['subject']} {e['body_preview']}"
                if any(kw in combined for kw in job_kw_check):
                    job_email_indices.append(i)

            # Limit body fetching to 30 to control execution time
            body_fetch_limit = min(len(job_email_indices), 30)
            logger.info(
                f"[gmail-browser] {len(job_email_indices)} job-related, "
                f"opening {body_fetch_limit} for full body"
            )

            for idx in job_email_indices[:body_fetch_limit]:
                try:
                    rows = await page.query_selector_all('tr.zA')
                    if idx < len(rows):
                        await rows[idx].click()
                        await page.wait_for_timeout(2000)

                        full_body = await page.evaluate('''() => {
                            const bodyEls = document.querySelectorAll(
                                'div[data-message-id] div.a3s, ' +
                                'div.ii.gt div.a3s, ' +
                                'div[role="listitem"] div.a3s'
                            );
                            if (bodyEls.length > 0) {
                                return Array.from(bodyEls)
                                    .map(el => el.innerText)
                                    .join('\\n---\\n')
                                    .substring(0, 5000);
                            }
                            const mainContent = document.querySelector('div[role="main"]');
                            return mainContent ? mainContent.innerText.substring(0, 5000) : '';
                        }''')

                        if full_body and len(full_body) > 20:
                            emails[idx]['full_body'] = full_body

                        await page.go_back()
                        await page.wait_for_timeout(1500)

                except Exception as e_detail:
                    logger.debug(f"[gmail-browser] Error opening email {idx}: {e_detail}")
                    try:
                        await page.goto(target_url, wait_until='domcontentloaded', timeout=10000)
                        await page.wait_for_timeout(2000)
                    except Exception:
                        pass

        finally:
            await ctx.close()
            await pw.stop()

        return emails

    loop = asyncio.new_event_loop()
    try:
        raw_emails = loop.run_until_complete(_run())
    except Exception as e:
        logger.exception(f"[gmail-browser] Fetch error: {e}")
        return []
    finally:
        loop.close()

    # Convert to standard format
    from services import (
        JOB_KEYWORDS, INTERVIEW_KEYWORDS, CONFIRMATION_KEYWORDS,
        ES_DEADLINE_KEYWORDS
    )

    results = []
    for e in raw_emails:
        body = e.get('full_body', '') or e['body_preview']
        full_text = f"{e['subject']} {e['sender']} {body}"

        is_job = any(kw in full_text for kw in JOB_KEYWORDS)
        has_interview = any(kw in full_text for kw in INTERVIEW_KEYWORDS)
        has_confirm = any(kw in full_text for kw in CONFIRMATION_KEYWORDS)
        has_es_deadline = any(kw in full_text for kw in ES_DEADLINE_KEYWORDS)

        results.append({
            'gmail_id': e['gmail_id'],
            'subject': e['subject'],
            'sender': e['sender'],
            'body_preview': e['body_preview'],
            'full_body': body,
            'received_at': e.get('date_text', datetime.now().isoformat()),
            'is_job_related': 1 if is_job else 0,
            'is_interview_invite': 1 if (has_interview or has_confirm or has_es_deadline) else 0,
        })

    logger.info(
        f"[gmail-browser] Done: {len(results)} total, "
        f"{sum(1 for r in results if r['is_job_related'])} job-related"
    )
    return results


# ── Legacy aliases (backward compatibility) ──────────────────────────

def fetch_emails_via_browser(max_results=30):
    """Legacy wrapper → fetch_emails_by_search."""
    return fetch_emails_by_search(query='', max_results=max_results)


def fetch_emails_backfill(days=30):
    """Legacy wrapper → fetch_emails_by_search with date filter."""
    from datetime import timedelta
    after_date = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
    return fetch_emails_by_search(query=f'after:{after_date}', max_results=0)


def is_gmail_browser_configured():
    """Check if Gmail browser profile or cookies exist."""
    return os.path.exists(GMAIL_PROFILE_DIR) or os.path.exists(GMAIL_STATE_FILE)
