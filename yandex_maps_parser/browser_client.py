"""
Playwright-based browser pool for fetching Yandex Maps detail pages.

Uses a real Chromium browser with proper TLS fingerprint, cookies, and JS
rendering — Yandex does NOT throttle browser requests the way it throttles
raw HTTP requests.

Features:
  - Auto-check: verifies Playwright is installed, auto-installs if missing
  - Disk cache: saves fetched HTML to avoid re-fetching
  - Resilience: auto-restarts Chromium on crash
  - Rate-limiting: semaphore to prevent overwhelming Yandex

Usage:
  from .browser_client import init_browser, fetch_page, close_browser

  init_browser(pool_size=8)     # call once at run start
  html = fetch_page(url)        # thread-safe, blocks until a page is free
  close_browser()               # cleanup at run end
"""

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import state

# Lazy import — playwright may not be installed
_playwright_mod = None
_pw_instance = None
_browser = None
_page_pool: queue.Queue | None = None
_pool_size = 0
_init_lock = threading.Lock()
_browser_lock = threading.Lock()  # guards _pw_instance, _browser, _page_pool

# Rate-limiting: semaphore to limit concurrent browser navigations
_rate_semaphore: threading.Semaphore | None = None
_rate_lock = threading.Lock()

# Cache directory
_CACHE_DIR = None
_CACHE_MAX_SIZE = 500  # max cached pages
_cache_index: dict[str, float] = {}  # biz_id -> mtime
_cache_lock = threading.Lock()
_cache_last_cleanup: float = 0.0

# Stats
_stats_lock = threading.Lock()
_stats = {"pages_fetched": 0, "pages_error": 0, "total_time": 0.0,
          "cache_hits": 0, "cache_misses": 0, "restarts": 0}

# Installation status (checked once, cached)
_playwright_installed: bool | None = None  # None = not checked yet


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


def _auto_install_playwright() -> bool:
    """Try to install Playwright automatically.

    Returns True if installation succeeded, False otherwise.
    """
    state.syslog("browser_client: playwright not found, attempting auto-install...")
    try:
        # Install playwright package
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "playwright"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        # Install chromium browser
        subprocess.check_call(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
        state.syslog("browser_client: playwright auto-installed successfully")
        # Force reimport
        import importlib
        importlib.invalidate_caches()
        global _playwright_mod
        _playwright_mod = None
        return _try_import_playwright() is not None
    except Exception as e:
        state.syslog(f"browser_client: auto-install failed: {e}")
        return False


def _init_cache():
    """Initialize disk cache directory."""
    global _CACHE_DIR
    if _CACHE_DIR is not None:
        return
    cache_dir = Path(state.OUTPUT_DIR) / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR = cache_dir
    # Build index of existing cache files
    with _cache_lock:
        for f in cache_dir.glob("*.html"):
            try:
                _cache_index[f.stem] = f.stat().st_mtime
            except Exception:
                pass
    state.syslog(f"browser_client: cache initialized, {len(_cache_index)} entries")


def _get_cache_path(biz_id: str) -> Path | None:
    """Get cache file path for a biz_id."""
    if _CACHE_DIR is None:
        return None
    return _CACHE_DIR / f"{biz_id}.html"


def _cache_get(biz_id: str) -> str | None:
    """Get cached HTML for a biz_id. Returns None if not cached or expired."""
    if not biz_id:
        return None
    path = _get_cache_path(biz_id)
    if path is None:
        return None
    with _cache_lock:
        mtime = _cache_index.get(biz_id)
        if mtime is None:
            return None
        # Expire after 24 hours
        if time.time() - mtime > 86400:
            try:
                path.unlink()
            except Exception:
                pass
            _cache_index.pop(biz_id, None)
            return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _cache_maybe_evict() -> None:
    """Periodic cache eviction — only runs every 60s."""
    global _cache_last_cleanup
    now = time.time()
    if now - _cache_last_cleanup < 60:
        return
    _cache_last_cleanup = now
    with _cache_lock:
        # Remove expired entries (>24h)
        expired = [bid for bid, mt in _cache_index.items() if now - mt > 86400]
        for bid in expired:
            try:
                (_CACHE_DIR / f"{bid}.html").unlink()
            except Exception:
                pass
            _cache_index.pop(bid, None)
        # Evict oldest if over limit
        if len(_cache_index) > _CACHE_MAX_SIZE:
            excess = len(_cache_index) - _CACHE_MAX_SIZE
            oldest = sorted(_cache_index.items(), key=lambda x: x[1])[:excess]
            for old_id, _ in oldest:
                try:
                    (_CACHE_DIR / f"{old_id}.html").unlink()
                except Exception:
                    pass
                _cache_index.pop(old_id, None)


def _cache_set(biz_id: str, html: str) -> None:
    """Save HTML to disk cache."""
    if not biz_id:
        return
    path = _get_cache_path(biz_id)
    if path is None:
        return
    try:
        path.write_text(html, encoding="utf-8")
        with _cache_lock:
            _cache_index[biz_id] = time.time()
    except Exception:
        pass
    _cache_maybe_evict()


def _test_playwright_in_subprocess() -> bool:
    """Test if Playwright can launch Chromium in a subprocess.
    
    This catches hard crashes (0xC0000005) that can't be caught by try/except.
    Returns True if Playwright works, False otherwise.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "from playwright.sync_api import sync_playwright; "
             "p = sync_playwright().start(); "
             "b = p.chromium.launch(headless=True); "
             "b.close(); p.stop()"],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def init_browser(pool_size: int = 8) -> bool:
    """Initialize Playwright browser with a pool of pages.
    
    Auto-installs Playwright if not found.  Returns True if browser was
    initialized, False if Playwright is not available (fallback to httpx).
    
    Tests Chromium launch in a subprocess first to avoid hard crashes.
    """
    global _pw_instance, _browser, _page_pool, _pool_size, _rate_semaphore

    pw_mod = _try_import_playwright()
    if pw_mod is None:
        # Try auto-install
        if _auto_install_playwright():
            pw_mod = _try_import_playwright()
        if pw_mod is None:
            state.syslog("browser_client: playwright not available, using httpx fallback")
            state.warn("⚠ Playwright не установлен. Для ускорения: pip install playwright && playwright install chromium")
            return False

    # Test Chromium launch in subprocess to avoid hard crash
    state.syslog("browser_client: testing Chromium launch in subprocess...")
    if not _test_playwright_in_subprocess():
        state.syslog("browser_client: Chromium test failed, using httpx fallback")
        state.warn("⚠ Chromium не может запуститься. Используем httpx fallback.")
        return False
    state.syslog("browser_client: Chromium test passed")

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

                # Rate-limiting semaphore
                _rate_semaphore = threading.Semaphore(pool_size)

                # Initialize cache
                _init_cache()

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


def _restart_browser() -> bool:
    """Restart the browser after a crash. Thread-safe.

    Returns True if restart succeeded.
    """
    global _pw_instance, _browser, _page_pool, _rate_semaphore

    with _browser_lock:
        # Close existing browser
        try:
            if _browser:
                _browser.close()
        except Exception:
            pass
        _browser = None
        _page_pool = None

        # Wait a moment for cleanup
        time.sleep(1)

        try:
            pw_mod = _try_import_playwright()
            if pw_mod is None:
                return False

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

            for i in range(_pool_size):
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

            with _stats_lock:
                _stats["restarts"] += 1

            state.syslog(f"browser_client: restarted with {_pool_size} pages")
            return True

        except Exception as e:
            state.syslog(f"browser_client: restart failed: {e}")
            _pw_instance = None
            _browser = None
            _page_pool = None
            return False


def is_installed() -> bool:
    """Check if Playwright package is installed (cached after first check)."""
    global _playwright_installed
    if _playwright_installed is not None:
        return _playwright_installed
    _playwright_installed = _try_import_playwright() is not None
    return _playwright_installed


def is_available() -> bool:
    """Check if browser pool is initialized and ready."""
    return _browser is not None and _page_pool is not None


def fetch_page(url: str, timeout_ms: int = 30000, biz_id: str = "") -> str | None:
    """Fetch a page using Playwright browser and return HTML content.

    Thread-safe: borrows a page from the pool, navigates, returns HTML,
    then returns the page to the pool.  Blocks if all pages are busy.

    Checks disk cache first (keyed by biz_id).  Saves to cache after fetch.

    Returns None on error or if browser is not available.
    """
    if not is_available():
        return None

    # Check cache first
    if biz_id:
        cached = _cache_get(biz_id)
        if cached:
            with _stats_lock:
                _stats["cache_hits"] += 1
            return cached
        with _stats_lock:
            _stats["cache_misses"] += 1

    page = None
    t0 = time.monotonic()
    max_retries = 2

    for attempt in range(max_retries):
        # Stop/skip must interrupt a blocked acquire — a plain
        # acquire(timeout=60) would otherwise stall run shutdown for up to
        # a minute while the pool is saturated. Poll in short slices.
        if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
            return None
        try:
            # Rate-limiting: wait for semaphore slot
            if _rate_semaphore:
                _acquire_deadline = time.monotonic() + 60
                while True:
                    if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                        return None
                    if _rate_semaphore.acquire(blocking=False):
                        break
                    if time.monotonic() >= _acquire_deadline:
                        raise TimeoutError("rate semaphore timeout")
                    time.sleep(0.5)

            try:
                # Borrow a page from the pool (blocks until one is free)
                _pool_deadline = time.monotonic() + 60
                while True:
                    if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                        return None
                    try:
                        page = _page_pool.get_nowait()
                        break
                    except queue.Empty:
                        if time.monotonic() >= _pool_deadline:
                            raise TimeoutError("page pool timeout")
                        time.sleep(0.5)

                # Navigate
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Wait a bit for JS to render social links
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

                html = page.content()

                with _stats_lock:
                    _stats["pages_fetched"] += 1
                    _stats["total_time"] += time.monotonic() - t0

                # Save to cache
                if biz_id and html:
                    _cache_set(biz_id, html)

                return html

            finally:
                if _rate_semaphore:
                    _rate_semaphore.release()
                # Return page to pool
                if page is not None:
                    try:
                        _page_pool.put_nowait(page)
                    except queue.Full:
                        try:
                            page.close()
                        except Exception:
                            pass
                    page = None

        except Exception as e:
            with _stats_lock:
                _stats["pages_error"] += 1
            state.syslog(f"browser_client: error fetching {url[:80]}: {type(e).__name__}: {e}")

            # Return broken page to pool and create a fresh replacement
            # so the next caller doesn't get a page in a bad state
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
                page = None
                # Create replacement context + page
                try:
                    if _browser is not None:
                        ctx = _browser.new_context(
                            locale="ru-RU",
                            viewport={"width": 1400, "height": 900},
                            user_agent=(
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/125.0.0.0 Safari/537.36"
                            ),
                        )
                        _page_pool.put_nowait(ctx.new_page())
                except Exception:
                    pass

            # On crash, try to restart browser
            if attempt < max_retries - 1:
                state.syslog("browser_client: attempting restart...")
                if _restart_browser():
                    state.syslog("browser_client: restart successful, retrying...")
                    time.sleep(1)
                    continue

            return None

    return None


def close_browser() -> None:
    """Shut down the browser and free resources."""
    global _pw_instance, _browser, _page_pool, _pool_size, _rate_semaphore

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
        _rate_semaphore = None
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
