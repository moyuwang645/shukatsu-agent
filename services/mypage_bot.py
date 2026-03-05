"""MyPage automation bot — Playwright-based login, password change, and profile fill.

Uses headless Chromium to:
1. Navigate to MyPage login URL
2. Auto-detect and fill login form (username + password)
3. Detect initial password change prompt → change to unified password
4. Auto-fill profile form with user data (Phase 2.5)
5. Capture screenshot of the post-login state
6. Update DB with new status and password
"""
import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = Path('data/screenshots')


async def _run_login_async(job_id: int, login_url: str, username: str,
                           password: str, new_password: str) -> dict:
    """Core async login logic using Playwright."""
    from playwright.async_api import async_playwright

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(SCREENSHOT_DIR / f'{job_id}.png')
    result = {
        'status': 'failed',
        'job_id': job_id,
        'screenshot': None,
        'password_changed': False,
        'error': None,
    }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
            )
            page = await context.new_page()
            page.set_default_timeout(15000)

            # ── Step 1: Navigate to login page ──
            logger.info(f"[mypage_bot] Navigating to {login_url}")
            await page.goto(login_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(2000)

            # ── Step 2: Find and fill login form ──
            login_filled = await _fill_login_form(page, username, password)
            if not login_filled:
                result['error'] = 'Could not detect login form'
                await page.screenshot(path=screenshot_path, full_page=False)
                result['screenshot'] = screenshot_path
                result['status'] = 'manual_intervention_needed'
                await browser.close()
                return result

            # ── Step 3: Submit and wait for navigation ──
            logger.info("[mypage_bot] Submitting login form...")
            url_before = page.url
            await _submit_form(page, url_before)
            await page.wait_for_timeout(3000)

            # ── Step 4: Check for password change prompt ──
            if new_password and new_password != password:
                pw_changed = await _try_password_change(
                    page, password, new_password
                )
                if pw_changed:
                    result['password_changed'] = True
                    logger.info("[mypage_bot] Password changed successfully")
                    await page.wait_for_timeout(2000)

            # ── Step 5: Screenshot ──
            await page.screenshot(path=screenshot_path, full_page=False)
            result['screenshot'] = screenshot_path
            result['status'] = 'password_changed' if result['password_changed'] else 'logged_in'

            logger.info(f"[mypage_bot] Done: {result['status']} for job_id={job_id}")
            await browser.close()

    except Exception as e:
        logger.error(f"[mypage_bot] Error for job_id={job_id}: {e}")
        result['error'] = str(e)
        result['status'] = 'failed'

    return result


async def _fill_login_form(page, username: str, password: str) -> bool:
    """Auto-detect login form and fill credentials.

    Tries multiple common selector patterns used by Japanese job portals.
    Returns True if form was found and filled.
    """
    # Common username field selectors (order: most specific → generic)
    username_selectors = [
        'input[name*="id" i]',
        'input[name*="user" i]',
        'input[name*="login" i]',
        'input[name*="mail" i]',
        'input[name*="account" i]',
        'input[type="email"]',
        'input[type="text"]:not([name*="pass"])',
    ]

    # Common password field selectors
    password_selectors = [
        'input[type="password"]',
        'input[name*="pass" i]',
    ]

    username_el = None
    for sel in username_selectors:
        try:
            els = await page.query_selector_all(sel)
            visible = [e for e in els if await e.is_visible()]
            if visible:
                username_el = visible[0]
                logger.info(f"[mypage_bot] Found username field: {sel}")
                break
        except Exception:
            continue

    password_el = None
    for sel in password_selectors:
        try:
            els = await page.query_selector_all(sel)
            visible = [e for e in els if await e.is_visible()]
            if visible:
                password_el = visible[0]
                logger.info(f"[mypage_bot] Found password field: {sel}")
                break
        except Exception:
            continue

    if not username_el or not password_el:
        logger.warning("[mypage_bot] Could not find login form fields")
        return False

    await username_el.fill(username)
    await password_el.fill(password)
    return True


async def _url_changed(page, url_before: str) -> bool:
    """Check if the page URL changed (indicates successful navigation)."""
    try:
        await page.wait_for_timeout(1500)
        return page.url != url_before
    except Exception:
        return False


async def _submit_form(page, url_before: str = ''):
    """Multi-round polling submit — tries many strategies for diverse sites.

    Rounds (each checks URL change after attempt):
      1. CSS selector matching (expanded: 14 patterns)
      2. Text-based search (any visible element containing login keywords)
      3. Proximity search (clickable elements near the password field)
      4. JavaScript form.submit()
      5. Focused Enter key on password field
    """
    if not url_before:
        url_before = page.url

    # ── Round 1: Expanded CSS selectors ──
    submit_selectors = [
        # Standard form submit
        'button[type="submit"]',
        'input[type="submit"]',
        # Image submit buttons
        'input[type="image"]',
        # Text-matching buttons (JP + EN)
        'button:has-text("ログイン")',
        'button:has-text("Login")',
        'button:has-text("ログ・イン")',
        'button:has-text("サインイン")',
        'button:has-text("Sign in")',
        # Input value matching
        'input[value*="ログイン"]',
        'input[value*="login" i]',
        'input[value*="サインイン"]',
        # Links styled as buttons
        'a:has-text("ログイン")',
        'a:has-text("Login")',
    ]

    for sel in submit_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                logger.info(f"[mypage_bot] R1 clicked: {sel}")
                if await _url_changed(page, url_before):
                    return
                # URL didn't change, but click might have triggered AJAX
                # Continue to check other rounds only if truly stuck
                await page.wait_for_timeout(500)
                if page.url != url_before:
                    return
        except Exception:
            continue

    # ── Round 2: Text/role-based broad search ──
    # Search all visible elements for login-related text
    login_keywords = ['ログイン', 'Login', 'login', 'サインイン', 'Sign in',
                       'ログ・イン', '送信', 'Submit']
    try:
        all_clickable = await page.query_selector_all(
            'button, input[type="button"], a, div[role="button"], '
            'span[role="button"], div[onclick], span[onclick]'
        )
        for el in all_clickable:
            try:
                if not await el.is_visible():
                    continue
                text = (await el.inner_text()).strip()
                if not text:
                    # Check value attribute for input elements
                    text = await el.get_attribute('value') or ''
                if any(kw in text for kw in login_keywords):
                    await el.click()
                    logger.info(f"[mypage_bot] R2 clicked element with text: '{text[:30]}'")
                    if await _url_changed(page, url_before):
                        return
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[mypage_bot] R2 search failed: {e}")

    # ── Round 3: Proximity search near password field ──
    # Find clickable elements within the same form or nearby
    try:
        # Try to find the form containing the password field
        form_submit = await page.evaluate('''() => {
            const pwField = document.querySelector('input[type="password"]');
            if (!pwField) return null;
            // Walk up to find the containing form
            const form = pwField.closest('form');
            if (form) {
                // Find any submit-like element in the form
                const candidates = form.querySelectorAll(
                    'button, input[type="submit"], input[type="button"], '
                    + 'input[type="image"], a, div[onclick], [role="button"]'
                );
                for (const el of candidates) {
                    if (el.offsetParent !== null) {  // visible check
                        el.click();
                        return 'form_element_clicked';
                    }
                }
            }
            return null;
        }''')
        if form_submit:
            logger.info(f"[mypage_bot] R3 clicked element in password form")
            if await _url_changed(page, url_before):
                return
    except Exception as e:
        logger.debug(f"[mypage_bot] R3 proximity search failed: {e}")

    # ── Round 4: JavaScript form.submit() ──
    try:
        submitted = await page.evaluate('''() => {
            const pwField = document.querySelector('input[type="password"]');
            if (pwField) {
                const form = pwField.closest('form');
                if (form) {
                    form.submit();
                    return true;
                }
            }
            // Fallback: submit first visible form on page
            const forms = document.querySelectorAll('form');
            for (const f of forms) {
                if (f.offsetParent !== null || f.querySelector('input[type="password"]')) {
                    f.submit();
                    return true;
                }
            }
            return false;
        }''')
        if submitted:
            logger.info("[mypage_bot] R4 submitted via form.submit()")
            if await _url_changed(page, url_before):
                return
    except Exception as e:
        logger.debug(f"[mypage_bot] R4 form.submit() failed: {e}")

    # ── Round 5: Focus password field and press Enter ──
    try:
        pw_field = await page.query_selector('input[type="password"]')
        if pw_field:
            await pw_field.focus()
            await page.wait_for_timeout(200)
        await page.keyboard.press('Enter')
        logger.info("[mypage_bot] R5 pressed Enter on focused password field")
    except Exception:
        logger.info("[mypage_bot] R5 fallback: pressing Enter")
        await page.keyboard.press('Enter')


async def _try_password_change(page, old_password: str,
                               new_password: str) -> bool:
    """Detect and handle password change form (common on first login).

    Returns True if password was successfully changed.
    """
    # Look for password change indicators
    change_indicators = [
        'パスワード変更', 'パスワードの変更', '初期パスワード',
        'password change', 'change password', '新しいパスワード',
    ]

    page_text = await page.inner_text('body')
    found = any(kw in page_text.lower() for kw in
                [k.lower() for k in change_indicators])

    if not found:
        logger.info("[mypage_bot] No password change prompt detected")
        return False

    logger.info("[mypage_bot] Password change form detected")

    # Find password fields (expect 2-3: current, new, confirm)
    pw_fields = await page.query_selector_all('input[type="password"]')
    visible_pw_fields = [f for f in pw_fields if await f.is_visible()]

    if len(visible_pw_fields) < 2:
        logger.warning(f"[mypage_bot] Expected 2+ password fields, found {len(visible_pw_fields)}")
        return False

    if len(visible_pw_fields) == 2:
        # Pattern: new_password + confirm
        await visible_pw_fields[0].fill(new_password)
        await visible_pw_fields[1].fill(new_password)
    elif len(visible_pw_fields) >= 3:
        # Pattern: current + new + confirm
        await visible_pw_fields[0].fill(old_password)
        await visible_pw_fields[1].fill(new_password)
        await visible_pw_fields[2].fill(new_password)

    # Submit the change
    await _submit_form(page)
    await page.wait_for_timeout(2000)
    return True


def run_mypage_login(job_id: int, **kwargs) -> dict:
    """Synchronous wrapper for the async login flow.

    Called by TaskWorker. Reads credentials from DB, runs Playwright,
    and updates DB with results.
    """
    from db.mypages import (
        get_mypage_credential, update_mypage_status,
        update_mypage_password, save_mypage_screenshot,
    )
    from db.user_profile import get_mypage_password

    # Load credentials
    cred = get_mypage_credential(job_id)
    if not cred:
        logger.error(f"[mypage_bot] No credential for job_id={job_id}")
        return {'status': 'failed', 'error': 'no credential'}

    login_url = cred.get('login_url')
    username = cred.get('username')
    password = cred.get('current_password') or cred.get('initial_password')
    unified_password = get_mypage_password()

    if not login_url or not username:
        update_mypage_status(job_id, 'failed', 'Missing login_url or username')
        return {'status': 'failed', 'error': 'missing login_url or username'}

    # Run async login
    try:
        result = asyncio.run(_run_login_async(
            job_id, login_url, username, password, unified_password
        ))
    except Exception as e:
        logger.error(f"[mypage_bot] Fatal error: {e}")
        update_mypage_status(job_id, 'failed', str(e))
        return {'status': 'failed', 'error': str(e)}

    # Update DB based on result
    if result.get('screenshot'):
        save_mypage_screenshot(job_id, result['screenshot'])

    if result['status'] == 'password_changed' and unified_password:
        update_mypage_password(job_id, unified_password)
        update_mypage_status(job_id, 'password_changed')
    elif result['status'] == 'logged_in':
        update_mypage_status(job_id, 'password_changed')  # logged in at least
    elif result['status'] == 'manual_intervention_needed':
        update_mypage_status(job_id, 'manual_intervention_needed',
                             result.get('error'))
    else:
        update_mypage_status(job_id, 'failed', result.get('error'))

    return result


# ── Phase 2.5: Profile auto-fill ─────────────────────────────────────


def _split_name(full_name: str) -> tuple[str, str]:
    """Split '姓 名' into (surname, given_name)."""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[0], ' '.join(parts[1:])
    return full_name.strip(), ''


def _split_phone(phone: str) -> tuple[str, str, str]:
    """Split phone like '080-1234-5678' into 3 parts."""
    import re
    digits = re.sub(r'[-‐\s]', '', phone)
    if len(digits) == 11:  # mobile: 080-xxxx-xxxx
        return digits[:3], digits[3:7], digits[7:]
    elif len(digits) == 10:  # landline: 03-1234-5678
        return digits[:2], digits[2:6], digits[6:]
    # fallback: split roughly
    return digits[:3], digits[3:7], digits[7:] if len(digits) > 7 else ('', '', '')


def _parse_birthday(birthday_str: str) -> tuple[str, str, str]:
    """Parse birthday like '2003年4月15日' or '2003/4/15' into (year, month, day)."""
    import re
    # Try Japanese format: 2003年4月15日
    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', birthday_str)
    if m:
        return m.group(1), m.group(2), m.group(3)
    # Try slash/dash format: 2003/4/15 or 2003-04-15
    m = re.search(r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})', birthday_str)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return '', '', ''


def _parse_education_dates(education: list) -> tuple[str, str]:
    """Extract university entrance year and month from education list.

    Returns (year, month) for university entrance.
    """
    import re
    for entry in education:
        school = entry.get('school', '')
        period = entry.get('period', '')
        # Look for university entrance
        if '大学' in school and ('入学' in school or '入学' in period):
            m = re.search(r'(\d{4})\s*年?\s*(\d{1,2})', period)
            if m:
                return m.group(1), m.group(2)
            m = re.search(r'(\d{4})\s*年?\s*(\d{1,2})', school)
            if m:
                return m.group(1), m.group(2)
    # Fallback: look for any entry with 大学
    for entry in education:
        school = entry.get('school', '')
        period = entry.get('period', '')
        if '大学' in school:
            m = re.search(r'(\d{4})\s*年?\s*(\d{1,2})', period)
            if m:
                return m.group(1), m.group(2)
    return '', ''


async def _fill_profile_form(page, profile: dict) -> bool:
    """Fill profile form fields using user profile data.

    Best-effort approach: fills whatever fields are found, skips missing ones.
    Does NOT submit the form.

    Returns True if at least some fields were filled.
    """
    filled_count = 0

    async def _safe_fill(selector: str, value: str, label: str = '') -> bool:
        """Fill a field if it exists and is visible."""
        nonlocal filled_count
        if not value:
            return False
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.fill(value)
                filled_count += 1
                logger.info(f"[mypage_bot] Filled {label or selector}: '{value[:20]}'")
                return True
        except Exception as e:
            logger.debug(f"[mypage_bot] Fill failed for {label or selector}: {e}")
        return False

    async def _safe_select(selector: str, value: str, label: str = '') -> bool:
        """Select an option if the select element exists."""
        nonlocal filled_count
        if not value:
            return False
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.select_option(value=value)
                filled_count += 1
                logger.info(f"[mypage_bot] Selected {label or selector}: '{value}'")
                return True
        except Exception:
            pass
        # Try selecting by label text instead
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.select_option(label=value)
                filled_count += 1
                logger.info(f"[mypage_bot] Selected by label {label or selector}: '{value}'")
                return True
        except Exception as e:
            logger.debug(f"[mypage_bot] Select failed for {label or selector}: {e}")
        return False

    async def _safe_click(selector: str, label: str = '') -> bool:
        """Click an element if it exists."""
        nonlocal filled_count
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.click()
                filled_count += 1
                logger.info(f"[mypage_bot] Clicked {label or selector}")
                return True
        except Exception as e:
            logger.debug(f"[mypage_bot] Click failed for {label or selector}: {e}")
        return False

    # ── 1. Gender (性別) ──
    gender = profile.get('gender', '')
    if gender:
        if '男' in gender:
            await _safe_click('input[type="radio"][value*="男"]', '性別:男性')
            if not filled_count:
                # Try by label text
                await _safe_click('label:has-text("男性") input[type="radio"]', '性別:男性')
        elif '女' in gender:
            await _safe_click('input[type="radio"][value*="女"]', '性別:女性')
            if not filled_count:
                await _safe_click('label:has-text("女性") input[type="radio"]', '性別:女性')
        # Try broader approach: find radio by evaluating page
        if filled_count == 0 and gender:
            try:
                await page.evaluate(f'''() => {{
                    const radios = document.querySelectorAll('input[type="radio"]');
                    for (const r of radios) {{
                        const label = r.closest('label') || document.querySelector('label[for="' + r.id + '"]');
                        const text = label ? label.textContent : r.value;
                        if (text && text.includes("{gender[0]}")) {{
                            r.click();
                            return true;
                        }}
                    }}
                    return false;
                }}''')
                filled_count += 1
                logger.info(f"[mypage_bot] Clicked gender radio via JS: '{gender}'")
            except Exception as e:
                logger.debug(f"[mypage_bot] Gender JS click failed: {e}")

    # ── 2. Birthday (生年月日) ──
    birthday = profile.get('birthday', '')
    if birthday:
        year, month, day = _parse_birthday(birthday)
        if year:
            # Try common select patterns for year/month/day
            year_selectors = [
                'select[name*="birth" i][name*="year" i]',
                'select[name*="birth" i][name*="y" i]',
                'select[name*="year" i]',
            ]
            month_selectors = [
                'select[name*="birth" i][name*="month" i]',
                'select[name*="birth" i][name*="m" i]',
                'select[name*="month" i]',
            ]
            day_selectors = [
                'select[name*="birth" i][name*="day" i]',
                'select[name*="birth" i][name*="d" i]',
                'select[name*="day" i]',
            ]

            # Find all selects, try to identify birthday group by proximity
            # The MUIT form has 3 selects in a row near the 生年月日 label
            try:
                bday_selects = await page.evaluate('''() => {
                    const labels = document.querySelectorAll('th, td, label, span, div');
                    for (const el of labels) {
                        if (el.textContent.includes('生年月日')) {
                            // Find the parent row/section
                            let container = el.closest('tr') || el.closest('div') || el.parentElement;
                            // Walk up if needed
                            for (let i = 0; i < 3 && container; i++) {
                                const selects = container.querySelectorAll('select');
                                if (selects.length >= 3) {
                                    return Array.from(selects).slice(0, 3).map((s, idx) => {
                                        return {id: s.id, name: s.name, index: idx};
                                    });
                                }
                                container = container.parentElement;
                            }
                        }
                    }
                    return null;
                }''')

                if bday_selects and len(bday_selects) >= 3:
                    for i, sel_info in enumerate(bday_selects):
                        val = [year, month.lstrip('0'), day.lstrip('0')][i]
                        selector = f'select[name="{sel_info["name"]}"]' if sel_info['name'] \
                            else f'select#{sel_info["id"]}' if sel_info['id'] \
                            else None
                        if selector and val:
                            await _safe_select(selector, val,
                                               f'生年月日[{["年","月","日"][i]}]')
                else:
                    # Fallback: try named selects
                    for sel in year_selectors:
                        if await _safe_select(sel, year, '生年月日:年'):
                            break
                    for sel in month_selectors:
                        m_val = month.lstrip('0')
                        if await _safe_select(sel, m_val, '生年月日:月'):
                            break
                    for sel in day_selectors:
                        d_val = day.lstrip('0')
                        if await _safe_select(sel, d_val, '生年月日:日'):
                            break
            except Exception as e:
                logger.debug(f"[mypage_bot] Birthday JS detection failed: {e}")

    # ── 3. Address fields (市区郡町村, 町域・番地) ──
    address = profile.get('address', '')
    if address:
        import re
        # Remove postcode prefix if present
        addr_clean = re.sub(r'^〒?\s*\d{3}[-‐]?\d{4}\s*', '', address).strip()
        # Remove prefecture (already selected)
        prefectures = [
            '北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県',
            '茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県',
            '新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県',
            '静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県',
            '奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県',
            '徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県',
            '熊本県','大分県','宮崎県','鹿児島県','沖縄県',
        ]
        for pref in prefectures:
            if addr_clean.startswith(pref):
                addr_clean = addr_clean[len(pref):].strip()
                break

        # Split into city and street parts
        # Common pattern: "北九州市若松区xxx 1-2-3"
        city_match = re.match(r'^(.+?[市区町村郡])', addr_clean)
        if city_match:
            city = city_match.group(1)
            street = addr_clean[len(city):].strip()
        else:
            # Can't split well, put everything in city
            city = addr_clean
            street = ''

        # Try to fill city field (市区郡町村)
        city_selectors = [
            'input[name*="city" i]',
            'input[name*="shiku" i]',
            'input[placeholder*="市区郡町村"]',
            'input[placeholder*="市区町村"]',
        ]
        for sel in city_selectors:
            if await _safe_fill(sel, city, '市区郡町村'):
                break
        else:
            # Try JS approach: find input near 市区郡町村 label
            try:
                await page.evaluate(f'''() => {{
                    const labels = document.querySelectorAll('th, td, label, span, div');
                    for (const el of labels) {{
                        if (el.textContent.includes('市区郡町村') || el.textContent.includes('市区町村')) {{
                            let container = el.closest('tr') || el.closest('div') || el.parentElement;
                            for (let i = 0; i < 3 && container; i++) {{
                                const input = container.querySelector('input[type="text"]');
                                if (input && input.offsetParent !== null) {{
                                    input.value = '';
                                    input.focus();
                                    return true;
                                }}
                                container = container.parentElement;
                            }}
                        }}
                    }}
                    return false;
                }}''')
                # Use Playwright fill on the focused element
                focused = await page.evaluate('() => document.activeElement && document.activeElement.tagName === "INPUT"')
                if focused:
                    await page.keyboard.type(city)
                    filled_count += 1
                    logger.info(f"[mypage_bot] Filled city via JS focus: '{city}'")
            except Exception as e:
                logger.debug(f"[mypage_bot] City JS fill failed: {e}")

        # Try to fill street field (町域・番地)
        if street:
            street_selectors = [
                'input[name*="town" i]',
                'input[name*="choumei" i]',
                'input[name*="address" i]:not([name*="city" i])',
                'input[placeholder*="町域"]',
                'input[placeholder*="番地"]',
            ]
            for sel in street_selectors:
                if await _safe_fill(sel, street, '町域・番地'):
                    break

    # ── 4. Phone (携帯電話番号 3分割) ──
    phone = profile.get('phone', '')
    if phone:
        p1, p2, p3 = _split_phone(phone)
        if p1:
            # Try to find mobile phone fields (3 input fields in a row)
            try:
                phone_filled = await page.evaluate(f'''() => {{
                    const labels = document.querySelectorAll('th, td, label, span, div');
                    for (const el of labels) {{
                        if (el.textContent.includes('携帯電話')) {{
                            let container = el.closest('tr') || el.closest('div') || el.parentElement;
                            for (let i = 0; i < 3 && container; i++) {{
                                const inputs = container.querySelectorAll('input[type="text"], input[type="tel"]');
                                if (inputs.length >= 3) {{
                                    // Clear and set values using native input setter
                                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype, 'value').set;
                                    const vals = ["{p1}", "{p2}", "{p3}"];
                                    for (let j = 0; j < 3; j++) {{
                                        nativeInputValueSetter.call(inputs[j], vals[j]);
                                        inputs[j].dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        inputs[j].dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    }}
                                    return true;
                                }}
                                container = container.parentElement;
                            }}
                        }}
                    }}
                    return false;
                }}''')
                if phone_filled:
                    filled_count += 3
                    logger.info(f"[mypage_bot] Filled 携帯電話: {p1}-{p2}-{p3}")
            except Exception as e:
                logger.debug(f"[mypage_bot] Phone JS fill failed: {e}")

    # ── 5. 休暇中の連絡先 — check "現在の連絡先と同じ" ──
    try:
        vacation_checked = await page.evaluate('''() => {
            const labels = document.querySelectorAll('label, span, div');
            for (const el of labels) {
                if (el.textContent.includes('現在の連絡先と同じ')) {
                    const cb = el.querySelector('input[type="checkbox"]') ||
                               el.closest('label')?.querySelector('input[type="checkbox"]');
                    if (cb && !cb.checked) {
                        cb.click();
                        return true;
                    }
                    // Maybe the checkbox is a sibling
                    const parent = el.parentElement;
                    if (parent) {
                        const cb2 = parent.querySelector('input[type="checkbox"]');
                        if (cb2 && !cb2.checked) {
                            cb2.click();
                            return true;
                        }
                    }
                }
            }
            return false;
        }''')
        if vacation_checked:
            filled_count += 1
            logger.info("[mypage_bot] Checked '現在の連絡先と同じ'")
            await page.wait_for_timeout(500)
    except Exception as e:
        logger.debug(f"[mypage_bot] Vacation contact checkbox failed: {e}")

    # ── 6. Email (メールアドレス2 + 確認用) ──
    email = profile.get('email', '')
    if email:
        # The first email is usually pre-filled. Fill the second email pair.
        try:
            email_filled = await page.evaluate(f'''() => {{
                const labels = document.querySelectorAll('th, td, label, span, div');
                let filledCount = 0;
                for (const el of labels) {{
                    if (el.textContent.includes('メールアドレス2') ||
                        el.textContent.includes('メールアドレス２')) {{
                        let container = el.closest('tr') || el.closest('div') || el.parentElement;
                        for (let i = 0; i < 3 && container; i++) {{
                            const inputs = container.querySelectorAll('input[type="text"], input[type="email"]');
                            if (inputs.length >= 1) {{
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'value').set;
                                for (const inp of inputs) {{
                                    nativeInputValueSetter.call(inp, "{email}");
                                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    filledCount++;
                                }}
                                return filledCount;
                            }}
                            container = container.parentElement;
                        }}
                    }}
                }}
                return filledCount;
            }}''')
            if email_filled:
                filled_count += email_filled
                logger.info(f"[mypage_bot] Filled メールアドレス2: {email_filled} fields")
        except Exception as e:
            logger.debug(f"[mypage_bot] Email2 fill failed: {e}")

    # ── 7. School selection (学校リスト) ──
    university = profile.get('university', '')
    if university:
        try:
            school_selected = await page.evaluate(f'''() => {{
                // Find the school select (大きなリスト)
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {{
                    // Check if it's near a 学校 label
                    let container = sel.closest('tr') || sel.closest('div') || sel.parentElement;
                    for (let i = 0; i < 3 && container; i++) {{
                        if (container.textContent.includes('学校') &&
                            !container.textContent.includes('高校') &&
                            sel.options.length > 5) {{
                            // Find the matching option
                            for (const opt of sel.options) {{
                                if (opt.text.includes("{university}")) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                        }}
                        container = container.parentElement;
                    }}
                }}
                return false;
            }}''')
            if school_selected:
                filled_count += 1
                logger.info(f"[mypage_bot] Selected university: '{university}'")
                await page.wait_for_timeout(1000)  # Wait for faculty options to load
        except Exception as e:
            logger.debug(f"[mypage_bot] School selection failed: {e}")

    # ── 8. Faculty / Department (学部 / 学科) ──
    faculty = profile.get('faculty', '')
    department = profile.get('department', '')

    if faculty:
        try:
            fac_selected = await page.evaluate(f'''() => {{
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {{
                    let container = sel.closest('tr') || sel.closest('div') || sel.parentElement;
                    for (let i = 0; i < 3 && container; i++) {{
                        if (container.textContent.includes('学部') &&
                            !container.textContent.includes('学科')) {{
                            for (const opt of sel.options) {{
                                if (opt.text.includes("{faculty}")) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                        }}
                        container = container.parentElement;
                    }}
                }}
                return false;
            }}''')
            if fac_selected:
                filled_count += 1
                logger.info(f"[mypage_bot] Selected faculty: '{faculty}'")
                await page.wait_for_timeout(1000)
        except Exception as e:
            logger.debug(f"[mypage_bot] Faculty selection failed: {e}")

    if department:
        try:
            dept_selected = await page.evaluate(f'''() => {{
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {{
                    let container = sel.closest('tr') || sel.closest('div') || sel.parentElement;
                    for (let i = 0; i < 3 && container; i++) {{
                        if (container.textContent.includes('学科')) {{
                            for (const opt of sel.options) {{
                                if (opt.text.includes("{department}")) {{
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                        }}
                        container = container.parentElement;
                    }}
                }}
                return false;
            }}''')
            if dept_selected:
                filled_count += 1
                logger.info(f"[mypage_bot] Selected department: '{department}'")
        except Exception as e:
            logger.debug(f"[mypage_bot] Department selection failed: {e}")

    # ── 9. Entrance year/month (入学年月) ──
    education = profile.get('education', [])
    if education:
        ent_year, ent_month = _parse_education_dates(education)
        if ent_year:
            try:
                ent_filled = await page.evaluate(f'''() => {{
                    const labels = document.querySelectorAll('th, td, label, span, div');
                    for (const el of labels) {{
                        if (el.textContent.includes('入学年月') &&
                            !el.textContent.includes('高校')) {{
                            let container = el.closest('tr') || el.closest('div') || el.parentElement;
                            for (let i = 0; i < 3 && container; i++) {{
                                const selects = container.querySelectorAll('select');
                                if (selects.length >= 2) {{
                                    // Year select
                                    for (const opt of selects[0].options) {{
                                        if (opt.value === "{ent_year}" || opt.text.includes("{ent_year}")) {{
                                            selects[0].value = opt.value;
                                            selects[0].dispatchEvent(new Event('change', {{ bubbles: true }}));
                                            break;
                                        }}
                                    }}
                                    // Month select
                                    for (const opt of selects[1].options) {{
                                        if (opt.value === "{ent_month}" ||
                                            opt.value === "{ent_month.lstrip('0')}" ||
                                            opt.text.includes("{ent_month}")) {{
                                            selects[1].value = opt.value;
                                            selects[1].dispatchEvent(new Event('change', {{ bubbles: true }}));
                                            break;
                                        }}
                                    }}
                                    return true;
                                }}
                                container = container.parentElement;
                            }}
                        }}
                    }}
                    return false;
                }}''')
                if ent_filled:
                    filled_count += 2
                    logger.info(f"[mypage_bot] Set entrance date: {ent_year}/{ent_month}")
            except Exception as e:
                logger.debug(f"[mypage_bot] Entrance date failed: {e}")

    # ── 10. Questionnaire (アンケート) ──
    # Q1: 現在在籍中の学校の種別 → "大学"
    # Q2: 転学・編入はありますか → "いいえ" / "なし"
    try:
        q_filled = await page.evaluate('''() => {
            const labels = document.querySelectorAll('th, td, label, span, div');
            let filled = 0;
            for (const el of labels) {
                const text = el.textContent;
                if (text.includes('学校の種別') || text.includes('在籍中の学校')) {
                    let container = el.closest('tr') || el.closest('div') || el.parentElement;
                    for (let i = 0; i < 3 && container; i++) {
                        const sel = container.querySelector('select');
                        if (sel) {
                            for (const opt of sel.options) {
                                if (opt.text === '大学' || opt.value === '大学') {
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                                    filled++;
                                    break;
                                }
                            }
                            break;
                        }
                        container = container.parentElement;
                    }
                }
                if (text.includes('転学') || text.includes('編入')) {
                    let container = el.closest('tr') || el.closest('div') || el.parentElement;
                    for (let i = 0; i < 3 && container; i++) {
                        const sel = container.querySelector('select');
                        if (sel) {
                            for (const opt of sel.options) {
                                if (opt.text.includes('なし') || opt.text.includes('いいえ') ||
                                    opt.text === 'なし' || opt.value === 'なし') {
                                    sel.value = opt.value;
                                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                                    filled++;
                                    break;
                                }
                            }
                            break;
                        }
                        container = container.parentElement;
                    }
                }
            }
            return filled;
        }''')
        if q_filled:
            filled_count += q_filled
            logger.info(f"[mypage_bot] Filled {q_filled} questionnaire fields")
    except Exception as e:
        logger.debug(f"[mypage_bot] Questionnaire fill failed: {e}")

    logger.info(f"[mypage_bot] Profile form fill complete: {filled_count} fields filled")
    return filled_count > 0


async def _run_fill_profile_async(job_id: int, login_url: str, username: str,
                                   password: str, profile: dict) -> dict:
    """Core async profile fill logic — login then fill form."""
    from playwright.async_api import async_playwright

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = str(SCREENSHOT_DIR / f'{job_id}_profile.png')
    result = {
        'status': 'failed',
        'job_id': job_id,
        'screenshot': None,
        'fields_filled': False,
        'error': None,
    }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 900},
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
            )
            page = await context.new_page()
            page.set_default_timeout(15000)

            # ── Step 1: Navigate + Login ──
            logger.info(f"[mypage_bot] [fill] Navigating to {login_url}")
            await page.goto(login_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(2000)

            login_filled = await _fill_login_form(page, username, password)
            if not login_filled:
                result['error'] = 'Could not detect login form'
                result['status'] = 'manual_intervention_needed'
                await page.screenshot(path=screenshot_path, full_page=True)
                result['screenshot'] = screenshot_path
                await browser.close()
                return result

            url_before = page.url
            await _submit_form(page, url_before)
            await page.wait_for_timeout(3000)

            # ── Step 2: Check for login errors ──
            page_text = await page.inner_text('body')
            error_indicators = ['間違っています', 'incorrect', 'エラー',
                                'ログインできません', 'failed']
            if any(kw in page_text.lower() for kw in
                   [k.lower() for k in error_indicators]):
                result['error'] = 'Login failed — check credentials'
                result['status'] = 'failed'
                await page.screenshot(path=screenshot_path, full_page=True)
                result['screenshot'] = screenshot_path
                await browser.close()
                return result

            # ── Step 3: Detect profile form ──
            page_text = await page.inner_text('body')
            form_indicators = ['基本情報', '初回ログイン回答', 'プロフィール入力']
            if not any(kw in page_text for kw in form_indicators):
                logger.info("[mypage_bot] [fill] No profile form detected on this page")
                result['error'] = 'No profile form found after login'
                result['status'] = 'manual_intervention_needed'
                await page.screenshot(path=screenshot_path, full_page=True)
                result['screenshot'] = screenshot_path
                await browser.close()
                return result

            logger.info("[mypage_bot] [fill] Profile form detected, filling...")

            # ── Step 4: Fill the form ──
            fields_filled = await _fill_profile_form(page, profile)
            result['fields_filled'] = fields_filled
            await page.wait_for_timeout(1000)

            # ── Step 5: Full page screenshot ──
            await page.screenshot(path=screenshot_path, full_page=True)
            result['screenshot'] = screenshot_path
            result['status'] = 'profile_filled'

            logger.info(f"[mypage_bot] [fill] Done for job_id={job_id}")
            await browser.close()

    except Exception as e:
        logger.error(f"[mypage_bot] [fill] Error for job_id={job_id}: {e}")
        result['error'] = str(e)
        result['status'] = 'failed'

    return result


def run_mypage_fill_profile(job_id: int, **kwargs) -> dict:
    """Synchronous wrapper for profile fill.

    Called by TaskWorker. Reads profile + credentials from DB, runs Playwright,
    and updates DB with results.
    """
    from db.mypages import (
        get_mypage_credential, update_mypage_status,
        save_mypage_screenshot,
    )
    from db.user_profile import get_mypage_password, get_user_profile

    # Load credentials
    cred = get_mypage_credential(job_id)
    if not cred:
        logger.error(f"[mypage_bot] [fill] No credential for job_id={job_id}")
        return {'status': 'failed', 'error': 'no credential'}

    login_url = cred.get('login_url')
    username = cred.get('username')
    unified_pw = get_mypage_password()
    # Use unified password (already changed)
    password = unified_pw or cred.get('current_password') or cred.get('initial_password')

    if not login_url or not username:
        update_mypage_status(job_id, 'failed', 'Missing login_url or username')
        return {'status': 'failed', 'error': 'missing login_url or username'}

    # Load user profile
    profile_row = get_user_profile()
    if not profile_row or not profile_row.get('parsed'):
        update_mypage_status(job_id, 'failed', 'No user profile data')
        return {'status': 'failed', 'error': 'no user profile'}

    profile = profile_row['parsed']
    logger.info(f"[mypage_bot] [fill] Profile fields: {list(profile.keys())}")

    update_mypage_status(job_id, 'filling_profile')

    # Run async fill
    try:
        result = asyncio.run(_run_fill_profile_async(
            job_id, login_url, username, password, profile
        ))
    except Exception as e:
        logger.error(f"[mypage_bot] [fill] Fatal error: {e}")
        update_mypage_status(job_id, 'failed', str(e))
        return {'status': 'failed', 'error': str(e)}

    # Update DB
    if result.get('screenshot'):
        save_mypage_screenshot(job_id, result['screenshot'])

    if result['status'] == 'profile_filled':
        update_mypage_status(job_id, 'profile_filled')
    elif result['status'] == 'manual_intervention_needed':
        update_mypage_status(job_id, 'manual_intervention_needed',
                             result.get('error'))
    else:
        update_mypage_status(job_id, 'failed', result.get('error'))

    return result

