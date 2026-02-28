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
    async def _run():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()

        os.makedirs(GMAIL_PROFILE_DIR, exist_ok=True)

        # Use real Edge or Chrome — Google trusts these, not Playwright Chromium
        # persistent_context keeps all cookies in the profile dir
        try:
            ctx = await pw.chromium.launch_persistent_context(
                GMAIL_PROFILE_DIR,
                headless=False,
                channel='msedge',  # Use real Microsoft Edge
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                args=['--disable-blink-features=AutomationControlled'],
            )
        except Exception:
            # Fall back to Chrome if Edge not available
            try:
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=False,
                    channel='chrome',  # Use real Google Chrome
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )
            except Exception:
                # Last resort: Chromium with anti-detection
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=False,
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                    ],
                )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(GMAIL_URL, wait_until='domcontentloaded', timeout=20000)

        # Wait for user to log in (max 180 seconds)
        logged_in = False
        for _ in range(90):
            await page.wait_for_timeout(2000)
            url = page.url
            if 'mail.google.com' in url and 'accounts.google.com' not in url:
                # Extra wait for Gmail to fully load
                await page.wait_for_timeout(3000)
                logged_in = True
                break

        # Also save storage_state for the fetch function
        if logged_in:
            os.makedirs(os.path.dirname(GMAIL_STATE_FILE), exist_ok=True)
            await ctx.storage_state(path=GMAIL_STATE_FILE)
            logger.info("[gmail-browser] Login successful, cookies saved")

        await ctx.close()
        await pw.stop()
        return logged_in

    loop = asyncio.new_event_loop()
    try:
        success = loop.run_until_complete(_run())
        if success:
            return True, 'Gmail cookies saved — ブラウザログイン完了'
        return False, 'ログインがタイムアウトしました'
    except Exception as e:
        logger.exception(f"[gmail-browser] Login error: {e}")
        return False, str(e)
    finally:
        loop.close()


def fetch_emails_via_browser(max_results=30):
    """Fetch recent emails from Gmail using saved browser profile.
    Returns list of email dicts compatible with the existing format.
    """
    if not os.path.exists(GMAIL_PROFILE_DIR):
        logger.warning("[gmail-browser] No saved profile — please login first")
        return []

    async def _run():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()

        # Use persistent context with real browser (same as login)
        try:
            ctx = await pw.chromium.launch_persistent_context(
                GMAIL_PROFILE_DIR,
                headless=True,
                channel='msedge',
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                args=['--disable-blink-features=AutomationControlled'],
            )
        except Exception:
            try:
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=True,
                    channel='chrome',
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )
            except Exception:
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=True,
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            # Navigate to Gmail
            await page.goto(GMAIL_URL, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(3000)

            # Check if we're logged in
            if 'accounts.google.com' in page.url or '/signin' in page.url:
                logger.error("[gmail-browser] Not logged in — cookies expired")
                return []

            logger.info(f"[gmail-browser] Gmail loaded: {page.url}")

            # Wait for inbox to render
            try:
                await page.wait_for_selector('tr[jscontroller], div[role="main"]', timeout=15000)
            except Exception:
                logger.warning("[gmail-browser] Inbox selector timeout, trying anyway")

            await page.wait_for_timeout(2000)

            # Extract emails via JS from inbox list
            emails = await page.evaluate('''(maxResults) => {
                const emails = [];
                // Gmail renders emails as table rows
                const rows = document.querySelectorAll('tr.zA');
                let count = 0;

                for (const row of rows) {
                    if (count >= maxResults) break;

                    // Sender
                    const senderEl = row.querySelector('.yX .yW span[email], .yX .yW span[name]');
                    const sender = senderEl
                        ? (senderEl.getAttribute('email') || senderEl.getAttribute('name') || senderEl.textContent.trim())
                        : '';

                    // Subject
                    const subjectEl = row.querySelector('.y6 span[data-thread-id], .y6 span.bog, .y6');
                    const subject = subjectEl ? subjectEl.textContent.trim() : '';

                    // Snippet/preview
                    const snippetEl = row.querySelector('.y2');
                    const snippet = snippetEl ? snippetEl.textContent.replace(/^\\s*[-–—]\\s*/, '').trim() : '';

                    // Date
                    const dateEl = row.querySelector('.xW span[title], td.xW');
                    const dateText = dateEl ? (dateEl.getAttribute('title') || dateEl.textContent.trim()) : '';

                    // Thread ID (data attribute)
                    const threadId = row.getAttribute('data-legacy-thread-id')
                        || row.querySelector('[data-thread-id]')?.getAttribute('data-thread-id')
                        || `browser_${count}_${Date.now()}`;

                    // Is unread?
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
                        count++;
                    }
                }
                return emails;
            }''', max_results)

            logger.info(f"[gmail-browser] Extracted {len(emails)} emails from inbox")

            # --- Open job-related emails to get full body text ---
            # Identify which emails are job-related based on keywords
            job_kw_check = [
                '面接', '面談', '選考', 'ES', 'エントリー', '説明会',
                '書類', '内定', '一次', '二次', '最終', '適性検査',
                'Webテスト', '締切', '締め切り', '〆切', '提出',
                '日程', '予約', 'GD', 'グループディスカッション',
                '応募', 'マイナビ', 'リクナビ', '就活',
            ]
            job_email_indices = []
            for i, e in enumerate(emails):
                combined = f"{e['subject']} {e['body_preview']}"
                if any(kw in combined for kw in job_kw_check):
                    job_email_indices.append(i)

            # Open each job-related email to get full body (limit to 10)
            for idx in job_email_indices[:10]:
                try:
                    email = emails[idx]
                    logger.info(f"[gmail-browser] Opening email: {email['subject'][:50]}...")

                    # Click on the email row
                    rows = await page.query_selector_all('tr.zA')
                    if idx < len(rows):
                        await rows[idx].click()
                        await page.wait_for_timeout(2000)

                        # Extract full email body text
                        full_body = await page.evaluate('''() => {
                            // Gmail email body containers
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
                            // Fallback: get all visible text in the email view
                            const mainContent = document.querySelector('div[role="main"]');
                            return mainContent ? mainContent.innerText.substring(0, 5000) : '';
                        }''')

                        if full_body and len(full_body) > 20:
                            emails[idx]['full_body'] = full_body
                            logger.info(f"[gmail-browser] Got {len(full_body)} chars of body text")

                        # Go back to inbox
                        await page.go_back()
                        await page.wait_for_timeout(1500)

                except Exception as e_detail:
                    logger.debug(f"[gmail-browser] Error opening email {idx}: {e_detail}")
                    # Try to get back to inbox
                    try:
                        await page.goto(GMAIL_URL, wait_until='domcontentloaded', timeout=10000)
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

    # Convert to the format expected by the rest of the app
    from services import (
        JOB_KEYWORDS, INTERVIEW_KEYWORDS, CONFIRMATION_KEYWORDS,
        ES_DEADLINE_KEYWORDS
    )

    results = []
    for e in raw_emails:
        full_text = f"{e['subject']} {e['sender']} {e['body_preview']}"
        # Also check the full_body if present (from opening individual emails)
        body = e.get('full_body', '') or e['body_preview']
        full_text_with_body = f"{e['subject']} {e['sender']} {body}"

        is_job = any(kw in full_text_with_body for kw in JOB_KEYWORDS)
        has_interview = any(kw in full_text_with_body for kw in INTERVIEW_KEYWORDS)
        has_confirm = any(kw in full_text_with_body for kw in CONFIRMATION_KEYWORDS)
        has_es_deadline = any(kw in full_text_with_body for kw in ES_DEADLINE_KEYWORDS)

        results.append({
            'gmail_id': e['gmail_id'],
            'subject': e['subject'],
            'sender': e['sender'],
            'body_preview': e['body_preview'],
            'full_body': body,  # Full email body for analysis
            'received_at': e.get('date_text', datetime.now().isoformat()),
            'is_job_related': 1 if is_job else 0,
            'is_interview_invite': 1 if (has_interview or has_confirm or has_es_deadline) else 0,
        })

    return results


def fetch_emails_backfill(days=30):
    """Fetch ALL emails from the past N days using Gmail search.

    Uses the Gmail search URL `#search/after:YYYY/MM/DD` to filter by date,
    then scrolls to load all results (Gmail lazy-loads ~50 rows at a time).
    This is used for the initial backfill on first run.

    Args:
        days: Number of days to look back (default 30).

    Returns:
        List of email dicts in the same format as fetch_emails_via_browser.
    """
    if not os.path.exists(GMAIL_PROFILE_DIR):
        logger.warning("[gmail-browser] No saved profile — please login first")
        return []

    from datetime import timedelta
    after_date = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
    search_url = f"{GMAIL_URL}#search/after:{after_date}"
    logger.info(f"[gmail-backfill] Fetching all emails after {after_date}")

    async def _run():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()

        # Launch browser (same as fetch_emails_via_browser)
        try:
            ctx = await pw.chromium.launch_persistent_context(
                GMAIL_PROFILE_DIR,
                headless=True,
                channel='msedge',
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                args=['--disable-blink-features=AutomationControlled'],
            )
        except Exception:
            try:
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=True,
                    channel='chrome',
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )
            except Exception:
                ctx = await pw.chromium.launch_persistent_context(
                    GMAIL_PROFILE_DIR,
                    headless=True,
                    locale='ja-JP',
                    timezone_id='Asia/Tokyo',
                    args=['--disable-blink-features=AutomationControlled'],
                )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            # Navigate to Gmail search with date filter
            await page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(4000)

            # Check login status
            if 'accounts.google.com' in page.url or '/signin' in page.url:
                logger.error("[gmail-backfill] Not logged in — cookies expired")
                return []

            logger.info(f"[gmail-backfill] Search page loaded: {page.url}")

            # Wait for results to render
            try:
                await page.wait_for_selector('tr.zA', timeout=15000)
            except Exception:
                logger.warning("[gmail-backfill] No search results found")
                return []

            await page.wait_for_timeout(2000)

            # Scroll to load ALL results (Gmail lazy-loads ~50 rows at a time)
            prev_count = 0
            no_change_rounds = 0
            max_scroll_rounds = 30  # Safety limit (~1500 emails max)

            for scroll_round in range(max_scroll_rounds):
                current_count = await page.evaluate(
                    "document.querySelectorAll('tr.zA').length"
                )
                logger.info(
                    f"[gmail-backfill] Scroll round {scroll_round + 1}: "
                    f"{current_count} emails loaded"
                )

                if current_count == prev_count:
                    no_change_rounds += 1
                    if no_change_rounds >= 2:
                        # No new rows after 2 consecutive scrolls — we've loaded all
                        break
                else:
                    no_change_rounds = 0

                prev_count = current_count

                # Scroll down to trigger lazy-loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            final_count = await page.evaluate(
                "document.querySelectorAll('tr.zA').length"
            )
            logger.info(f"[gmail-backfill] Total emails loaded: {final_count}")

            # Extract ALL email rows (reuse same JS as regular fetch, but no limit)
            emails = await page.evaluate('''() => {
                const emails = [];
                const rows = document.querySelectorAll('tr.zA');

                for (const row of rows) {
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
                        || `backfill_${emails.length}_${Date.now()}`;

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
            }''')

            logger.info(f"[gmail-backfill] Extracted {len(emails)} emails")

            # Open job-related emails for full body (limit to 30 to control time)
            job_kw_check = [
                '面接', '面談', '選考', 'ES', 'エントリー', '説明会',
                '書類', '内定', '一次', '二次', '最終', '適性検査',
                'Webテスト', '締切', '締め切り', '〆切', '提出',
                '日程', '予約', 'GD', 'グループディスカッション',
                '応募', 'マイナビ', 'リクナビ', '就活',
            ]
            job_email_indices = []
            for i, e in enumerate(emails):
                combined = f"{e['subject']} {e['body_preview']}"
                if any(kw in combined for kw in job_kw_check):
                    job_email_indices.append(i)

            logger.info(
                f"[gmail-backfill] {len(job_email_indices)} job-related emails found, "
                f"opening up to 30 for full body"
            )

            for idx in job_email_indices[:30]:
                try:
                    email = emails[idx]
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
                    logger.debug(f"[gmail-backfill] Error opening email {idx}: {e_detail}")
                    try:
                        await page.goto(search_url, wait_until='domcontentloaded', timeout=10000)
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
        logger.exception(f"[gmail-backfill] Fetch error: {e}")
        return []
    finally:
        loop.close()

    # Convert to standard format (same as fetch_emails_via_browser)
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

    logger.info(f"[gmail-backfill] Done: {len(results)} total, "
                f"{sum(1 for r in results if r['is_job_related'])} job-related")
    return results


def is_gmail_browser_configured():
    """Check if Gmail browser profile or cookies exist."""
    return os.path.exists(GMAIL_PROFILE_DIR) or os.path.exists(GMAIL_STATE_FILE)
