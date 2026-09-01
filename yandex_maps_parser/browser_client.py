"""
Playwright-based browser pool for fetching Yandex Maps detail pages.

Uses a real Chromium browser with proper TLS fingerprint, cookies, and JS
rendering — Yandex does NOT throttle browser requests the way it throttles
raw HTTP requests.  This is the key to unlocking ~1-2s per page instead of
30-60s with raw httpx.

Architecture:
  - One Chromium instance shared across all worker threads
  - N browser pages (tabs) managed via a thread-safe queue
  - Each worker borrows a page, navigates, extracts HTML, returns the page
  - Graceful fallback to httpx if Playwright is not installed

Usage:
  from .browser_client import init_browser, fetch_page, close_browser

  init_browser(pool_size=8)     # call once at run start
  html = fetch_page(url)        # thread-safe, blocks until a page is free
  close_browser()               # cleanup at run end
"""

import queue
import threading
import time
from typing import TYPE_CHECKING

from . import state

# Lazy import — playwright may not be installed
_playwright_mod = None
_pw_instance = None
_browser = None
_page_pool: queue.Queue | None = None
_pool_size = 0
_init_lock = threading.Lock()
_browser_lock = threading.Lock()  # guards _pw_instance, _browser, _page_pool

# Stats
_stats_lock = threading.Lock()
_stats = {"pages_fetched": 0, "pages_error": 0, "total_time": 0.0}


def _try_import_playwright():
    """Try to import playwright.sync_api. Returns module or None."""
    global _playwright_mod
    if _playwright_mod is not None:
        return _playwright_mod
    try:
        from playwright import sync_api
        _playwright_mod = sync_api
        return _playwright_mod
    except ImportError:
        return None


def init_browser(pool_size: int = 8) -> bool:
    """Initialize Playwright browser with a pool of pages.

    Returns True if browser was initialized, False if Playwright is not
    available (fallback to httpx should be used).
    """
    global _pw_instance, _browser, _page_pool, _pool_size

    pw_mod = _try_import_playwright()
    if pw_mod is None:
        state.syslog("browser_client: playwright not installed, using httpx fallback")
        return False

    with _init_lock:
        with _browser_lock:
            # Already initialized?
            if _browser is not None:
                return True

            try:
                _pw_instance = pw_mod.sync_playwright().start()
                _browser = _pw_instance.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                _page_pool = queue.Queue()
                _pool_size = pool_size

                # Create pages with realistic viewport and user agent
                for i in range(pool_size):
                    ctx = _browser.new_context(
                        locale="ru-RU",
                        viewport={"width": 1400, "height": 900},
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                    )
                    page = ctx.new_page()
                    _page_pool.put(page)

                state.syslog(f"browser_client: initialized with {pool_size} pages")
                return True
            except Exception as e:
                state.syslog(f"browser_client: init failed: {e}")
                # Cleanup partial init
                try:
                    if _pw_instance:
                        _pw_instance.stop()
                except Exception:
                    pass
                _pw_instance = None
                _browser = None
                _page_pool = None
                return False


def is_available() -> bool:
    """Check if browser pool is initialized and ready."""
    return _browser is not None and _page_pool is not None


def fetch_page(url: str, timeout_ms: int = 30000) -> str | None:
    """Fetch a page using Playwright browser and return HTML content.

    Thread-safe: borrows a page from the pool, navigates, returns HTML,
    then returns the page to the pool.  Blocks if all pages are busy.

    Returns None on error or if browser is not available.
    """
    if not is_available():
        return None

    page = None
    t0 = time.monotonic()
    try:
        # Borrow a page from the pool (blocks until one is free)
        page = _page_pool.get(timeout=60)

        # Navigate
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Wait a bit for JS to render social links
        # (Yandex Maps loads social links via JS after initial page load)
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass

        html = page.content()

        with _stats_lock:
            _stats["pages_fetched"] += 1
            _stats["total_time"] += time.monotonic() - t0

        return html

    except Exception as e:
        with _stats_lock:
            _stats["pages_error"] += 1
        state.syslog(f"browser_client: error fetching {url[:80]}: {type(e).__name__}")
        return None
    finally:
        # Return page to pool
        if page is not None:
            try:
                _page_pool.put_nowait(page)
            except queue.Full:
                # Pool is full (shouldn't happen), close the page
                try:
                    page.close()
                except Exception:
                    pass


def close_browser() -> None:
    """Shut down the browser and free resources."""
    global _pw_instance, _browser, _page_pool, _pool_size

    with _browser_lock:
        if _page_pool is not None:
            # Drain and close all pages
            while not _page_pool.empty():
                try:
                    page = _page_pool.get_nowait()
                    page.close()
                except Exception:
                    pass
            _page_pool = None

        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None

        if _pw_instance is not None:
            try:
                _pw_instance.stop()
            except Exception:
                pass
            _pw_instance = None

        _pool_size = 0
        state.syslog("browser_client: closed")


def get_stats() -> dict:
    """Return browser usage statistics."""
    with _stats_lock:
        s = dict(_stats)
    if s["pages_fetched"] > 0:
        s["avg_time"] = round(s["total_time"] / s["pages_fetched"], 2)
    else:
        s["avg_time"] = 0.0
    return s
