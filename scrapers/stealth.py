"""Stealth utilities for Playwright browser automation.

Provides anti-detection measures so scraping sessions look like
normal user browsing. Used by BaseScraper, openwork scraper, and entry_bot.
"""
import asyncio
import random
import logging

logger = logging.getLogger(__name__)


def create_context_options() -> dict:
    """Create browser context options that mimic a real user.

    Returns:
        dict of kwargs for browser.new_context().
    """
    return {
        'viewport': {'width': 1366, 'height': 768},
        'user_agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
        'locale': 'ja-JP',
        'timezone_id': 'Asia/Tokyo',
        'java_script_enabled': True,
        'bypass_csp': True,
        'ignore_https_errors': True,
    }


async def apply_stealth(page) -> None:
    """Apply anti-detection patches to a Playwright page.

    Uses playwright-stealth library for comprehensive fingerprint masking.
    Falls back to manual JS injection if the library is unavailable.
    """
    # Try playwright-stealth library first (more comprehensive)
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
        logger.debug("[stealth] Applied playwright-stealth library patches")
        return
    except ImportError:
        logger.debug("[stealth] playwright-stealth not installed, using manual patches")
    except Exception as e:
        logger.debug(f"[stealth] playwright-stealth failed: {e}, using manual patches")

    # Fallback: manual JS injection
    try:
        await page.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });

            // Mock chrome.runtime
            window.chrome = { runtime: {} };

            // Override navigator.plugins to look real
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // Override navigator.languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ja', 'en-US', 'en'],
            });

            // Override permissions query
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters);
        """)
    except Exception as e:
        logger.debug(f"[stealth] Could not apply manual stealth: {e}")


async def random_delay(min_ms: int = 500, max_ms: int = 2000) -> None:
    """Wait a random amount of time to simulate human behavior."""
    delay = random.randint(min_ms, max_ms) / 1000.0
    await asyncio.sleep(delay)
