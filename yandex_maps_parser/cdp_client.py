"""
Chrome DevTools Protocol (CDP) browser pool — no Playwright dependency.

Launches Chrome via subprocess and controls it through CDP WebSocket.
Works on Python 3.14 where Playwright's Node.js driver segfaults.

Usage:
    from .cdp_client import init_browser, fetch_page, close_browser
    init_browser(pool_size=8)
    html = fetch_page(url, biz_id="123")
    close_browser()
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import state

# ── Config ──────────────────────────────────────────────────
_CHROME_PATHS = [
    # Playwright's bundled Chromium
    Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe",
    # Standard Chrome installation
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    # Edge (Chromium-based)
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
]

_CDP_PORT = 0  # 0 = auto-detect free port
_MAX_RETRIES = 2

# ── State ───────────────────────────────────────────────────
_proc = None  # Chrome subprocess
_base_port: int = 0
_tab_pool: queue.Queue | None = None
_pool_size = 0
_init_lock = threading.Lock()
_browser_lock = threading.Lock()

# Rate limiting
_rate_semaphore: threading.Semaphore | None = None

# Cache
_CACHE_DIR = None
_CACHE_MAX_SIZE = 500
_cache_index: dict[str, float] = {}
_cache_lock = threading.Lock()
_cache_last_cleanup: float = 0.0  # timestamp of last eviction pass

# Stats
_stats_lock = threading.Lock()
_stats = {"pages_fetched": 0, "pages_error": 0, "total_time": 0.0,
          "cache_hits": 0, "cache_misses": 0, "restarts": 0}

# ── Chrome discovery ────────────────────────────────────────

def _find_chrome() -> str | None:
    """Find a working Chrome/Chromium executable."""
    for p in _CHROME_PATHS:
        if p.exists():
            return str(p)
    # Try system PATH
    import shutil
    for name in ("chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _cdp_get(port: int, path: str) -> dict | list | None:
    """HTTP GET to Chrome DevTools Protocol."""
    try:
        url = f"http://127.0.0.1:{port}{path}"
        data = urllib.request.urlopen(url, timeout=5).read()
        return json.loads(data)
    except Exception:
        return None


def _cdp_put(port: int, path: str) -> bool:
    """HTTP PUT to Chrome DevTools Protocol."""
    try:
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url, method="PUT")
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def _cdp_new_tab(port: int, url: str = "about:blank") -> str | None:
    """Create a new tab via Target.createTarget, return its WebSocket debug URL."""
    try:
        import websocket
        # Get browser-level WebSocket URL
        ver = _cdp_get(port, "/json/version")
        if not ver:
            return None
        browser_ws = ver.get("webSocketDebuggerUrl")
        if not browser_ws:
            return None

        # Connect to browser WS and create target
        ws = websocket.create_connection(browser_ws, timeout=10)
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Target.createTarget",
                "params": {"url": url}
            }))
            resp = json.loads(ws.recv())
            target_id = resp.get("result", {}).get("targetId", "")
            if not target_id:
                return None
        finally:
            ws.close()

        # Get the page's WebSocket URL from /json
        tabs = _cdp_get(port, "/json")
        if tabs and isinstance(tabs, list):
            for t in tabs:
                if t.get("id") == target_id:
                    return t.get("webSocketDebuggerUrl")
        return None
    except Exception:
        return None


def _cdp_close_tab(port: int, tab_id: str) -> bool:
    """Close a tab by ID."""
    return _cdp_put(port, f"/json/close/{tab_id}")


# Realistic desktop Chrome UA — Yandex serves an EMPTY anti-bot document to
# the default "HeadlessChrome" user agent (verified live: 158-byte page body).
# Pages must be fetched with Network.setUserAgentOverride or the browser path
# is useless and every fetch falls back to slow, throttled httpx.
_CDP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_CDP_EVAL_ID = 90001  # id for Runtime.evaluate responses on a fresh WS


def _cdp_eval(ws, expression: str, deadline: float) -> str | None:
    """Evaluate `expression` via Runtime.evaluate, bounded by `deadline`."""
    try:
        ws.send(json.dumps({
            "id": _CDP_EVAL_ID,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }))
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                ws.settimeout(min(remaining, 5.0))
                data = json.loads(ws.recv())
                if data.get("id") == _CDP_EVAL_ID:
                    value = data.get("result", {}).get("result", {}).get("value")
                    return value if isinstance(value, str) else (str(value) if value is not None else None)
            except Exception:
                break
    except Exception:
        pass
    return None


def _cdp_navigate_and_get_html(ws_url: str, url: str, timeout_s: float = 40) -> str | None:
    """Navigate to URL via CDP WebSocket and return page HTML.

    Why polling instead of waiting on load events:
      - A desktop Chrome User-Agent override is REQUIRED — Yandex serves an
        empty anti-bot document (158 bytes) to the default HeadlessChrome UA.
      - Load events only arrive after Page.enable, and some pages never fire
        them — waiting on events burns the whole deadline for nothing.
      - Tabs are reused across fetches, so we must confirm the navigation has
        actually committed (the org id appears in location.href) before
        harvesting, otherwise we'd return the PREVIOUS business's HTML.

    Returns the HTML once meaningful content is available, or None on real
    failures / empty anti-bot stubs so the caller can fall back to httpx.
    """
    try:
        import websocket
    except ImportError:
        state.syslog("cdp_client: websocket-client not installed")
        return None

    overall_deadline = time.monotonic() + timeout_s
    ws = None
    try:
        ws = websocket.create_connection(ws_url, timeout=min(timeout_s, 10))

        msg_seq = {"id": 0}

        def _send(method: str, params: dict | None = None) -> int:
            msg_seq["id"] += 1
            ws.send(json.dumps({
                "id": msg_seq["id"],
                "method": method,
                "params": params or {},
            }))
            return msg_seq["id"]

        _send("Page.enable")
        _send("Network.setUserAgentOverride", {"userAgent": _CDP_USER_AGENT})
        _send("Page.navigate", {"url": url})

        # Numeric org id from the target URL — appears in the final location.href
        # even after Yandex rewrites the URL to a slug form.
        from urllib.parse import urlparse
        path_segs = [s for s in urlparse(url).path.split("/") if s]
        token = path_segs[-1] if (path_segs and path_segs[-1].isdigit()) else None

        # Poll until the navigation commits AND readyState == "complete".
        # Harvesting earlier (e.g. once the doc is merely large) returns a
        # PARTIAL document — the socials block sits near the end of the
        # server HTML and was missing in live tests (125KB no-links page).
        # Expression: href|readyState|len (len kept for debugging).
        expr = (
            "location.href + '|' + document.readyState + '|' + "
            "document.documentElement.outerHTML.length"
        )
        started = time.monotonic()
        committed = token is None  # nothing to match → assume committed
        while time.monotonic() < overall_deadline:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                break
            status = _cdp_eval(ws, expr, min(overall_deadline, time.monotonic() + 6.0))
            if status:
                parts = status.split("|")
                href = parts[0] if parts else ""
                ready = parts[1] if len(parts) > 1 else ""
                if token:
                    if token in href:
                        committed = True
                if committed and ready == "complete":
                    break
                # Tail of the deadline — harvest whatever exists instead of
                # burning the whole budget on a page that never reports ready.
                waited = time.monotonic() - started
                if remaining <= 8.0 and waited >= timeout_s * 0.6:
                    break
            time.sleep(min(0.75, remaining))

        # Harvest outerHTML. Retry a few times — content can render just after
        # the document commits. Bounded by the overall deadline.
        attempts = 0
        while attempts < 3 and time.monotonic() < overall_deadline - 1.0:
            html = _cdp_eval(
                ws,
                "document.documentElement.outerHTML",
                min(overall_deadline, time.monotonic() + 8.0),
            )
            if html and len(html) > 800:
                return html
            attempts += 1
            time.sleep(1.0)
        # Empty / stub page (anti-bot) — let the httpx fallback handle it.
        return None
    except ImportError:
        state.syslog("cdp_client: websocket-client not installed")
        return None
    except Exception as e:
        state.syslog(f"cdp_client: CDP error: {e}")
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


# ── Cache ───────────────────────────────────────────────────

def _init_cache():
    global _CACHE_DIR
    if _CACHE_DIR is not None:
        return
    cache_dir = Path(state.OUTPUT_DIR) / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR = cache_dir
    with _cache_lock:
        for f in cache_dir.glob("*.html"):
            try:
                _cache_index[f.stem] = f.stat().st_mtime
            except Exception:
                pass
    state.syslog(f"cdp_client: cache initialized, {len(_cache_index)} entries")


def _cache_get(biz_id: str) -> str | None:
    # Caching disabled — always return None
    return None


def _cache_maybe_evict():
    """Evict old cache entries if over limit. Only runs every 60s."""
    global _cache_last_cleanup
    now = time.time()
    if now - _cache_last_cleanup < 60:
        return
    _cache_last_cleanup = now
    with _cache_lock:
        # First: remove expired entries (>24h)
        expired = [bid for bid, mt in _cache_index.items() if now - mt > 86400]
        for bid in expired:
            try:
                (_CACHE_DIR / f"{bid}.html").unlink()
            except Exception:
                pass
            _cache_index.pop(bid, None)
        # Then: evict oldest if over limit
        if len(_cache_index) > _CACHE_MAX_SIZE:
            excess = len(_cache_index) - _CACHE_MAX_SIZE
            oldest = sorted(_cache_index.items(), key=lambda x: x[1])[:excess]
            for old_id, _ in oldest:
                try:
                    (_CACHE_DIR / f"{old_id}.html").unlink()
                except Exception:
                    pass
                _cache_index.pop(old_id, None)


def _cache_set(biz_id: str, html: str):
    # Caching disabled — no-op
    pass


# ── Tab pool management ─────────────────────────────────────

def _create_tab() -> str | None:
    """Create a new Chrome tab and return its WebSocket URL."""
    ws_url = _cdp_new_tab(_base_port)
    if ws_url:
        # Convert ws://127.0.0.1:PORT/devtools/page/ID to use our port
        # The WS URL from Chrome already has the correct port
        pass
    return ws_url


def _is_tab_alive(ws_url: str) -> bool:
    """Quick check if a tab's WebSocket is reachable."""
    ws = None
    try:
        import websocket
        ws = websocket.create_connection(ws_url, timeout=3)
        return True
    except Exception:
        return False
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


# ── Public API ──────────────────────────────────────────────

def is_available() -> bool:
    """Check if CDP browser pool is initialized."""
    return _proc is not None and _tab_pool is not None


def is_installed() -> bool:
    """Check if Chrome/Chromium is available on this system."""
    return _find_chrome() is not None


def init_browser(pool_size: int = 8) -> bool:
    """Launch Chrome and create a pool of tabs for parallel fetching."""
    global _proc, _base_port, _tab_pool, _pool_size, _rate_semaphore

    chrome_path = _find_chrome()
    if not chrome_path:
        state.warn("Chrome/Chromium не найден. Установите Google Chrome или Chromium.")
        return False

    state.syslog(f"cdp_client: found Chrome at {chrome_path}")

    with _init_lock:
        with _browser_lock:
            if _proc is not None and _proc.poll() is None:
                return True  # already running

            try:
                # Try up to 3 times with different ports
                for port_attempt in range(3):
                    # Find a free port
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.bind(("", 0))
                        _base_port = s.getsockname()[1]

                    _proc = subprocess.Popen(
                        [
                            chrome_path,
                            f"--remote-debugging-port={_base_port}",
                            "--remote-allow-origins=*",
                            "--headless=new",
                            "--no-sandbox",
                            "--disable-gpu",
                            "--disable-dev-shm-usage",
                            "--disable-features=VizDisplayCompositor",
                            "about:blank",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                    # Wait for Chrome to start
                    time.sleep(2)

                    # Verify Chrome is responding
                    version = _cdp_get(_base_port, "/json/version")
                    if version:
                        break  # Chrome is running

                    # Port conflict or Chrome failed — kill and retry
                    state.syslog(f"cdp_client: Chrome failed on port {_base_port}, retrying...")
                    try:
                        _proc.terminate()
                    except Exception:
                        pass
                    _proc = None
                    time.sleep(1)
                else:
                    state.warn("Chrome не отвечает после 3 попыток.")
                    return False

                state.syslog(f"cdp_client: Chrome started, version={version.get('Browser', '?')}")

                # Create tab pool
                _tab_pool = queue.Queue()
                _pool_size = pool_size
                for i in range(pool_size):
                    ws_url = _create_tab()
                    if ws_url:
                        _tab_pool.put(ws_url)
                    else:
                        state.syslog(f"cdp_client: failed to create tab {i}")

                if _tab_pool.qsize() == 0:
                    state.warn("Не удалось создать вкладки Chrome.")
                    _proc.terminate()
                    _proc = None
                    _tab_pool = None
                    return False

                _rate_semaphore = threading.Semaphore(pool_size)
                _init_cache()

                state.syslog(f"cdp_client: initialized with {_tab_pool.qsize()} tabs")
                return True

            except Exception as e:
                state.syslog(f"cdp_client: init failed: {e}")
                if _proc:
                    try:
                        _proc.terminate()
                    except Exception:
                        pass
                _proc = None
                _tab_pool = None
                return False


def fetch_page(url: str, timeout_ms: int = 40000, biz_id: str = "") -> str | None:
    """Fetch a page using Chrome CDP and return HTML."""
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

    t0 = time.monotonic()

    for attempt in range(_MAX_RETRIES):
        # Check stop before each attempt
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None
        if state.is_skip_city():
            return None
        ws_url = None
        _rate_acquired = False
        try:
            if _rate_semaphore:
                if not _rate_semaphore.acquire(timeout=5):
                    # Timeout — all tabs busy. Check stop before retrying.
                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        return None
                    continue
                _rate_acquired = True

            try:
                # Short timeout so stop can interrupt
                ws_url = _tab_pool.get(timeout=5)
            except queue.Empty:
                # Check stop before retrying
                if state._STOP_EVENT and state._STOP_EVENT.is_set():
                    return None
                state.syslog("cdp_client: no free tabs, waiting...")
                continue

            # Check tab health
            if not _is_tab_alive(ws_url):
                state.syslog(f"cdp_client: tab dead, creating replacement...")
                ws_url = _create_tab()
                if not ws_url:
                    return None

            # Navigate and get HTML
            from .http_client import _stats_count_request, _record_latency
            _stats_count_request(url)
            t_req = time.monotonic()
            html = _cdp_navigate_and_get_html(
                ws_url, url, timeout_s=timeout_ms / 1000
            )
            _record_latency(time.monotonic() - t_req)

            with _stats_lock:
                _stats["pages_fetched"] += 1
                _stats["total_time"] += time.monotonic() - t0

            # Save to cache
            if biz_id and html:
                _cache_set(biz_id, html)

            return html

        except Exception as e:
            with _stats_lock:
                _stats["pages_error"] += 1
            state.syslog(f"cdp_client: error: {type(e).__name__}: {e}")

            # Try to recover: create a fresh tab
            if attempt < _MAX_RETRIES - 1:
                state.syslog("cdp_client: attempting recovery...")
                try:
                    new_ws = _create_tab()
                    if new_ws:
                        ws_url = new_ws
                except Exception:
                    pass

        finally:
            if _rate_acquired and _rate_semaphore:
                try:
                    _rate_semaphore.release()
                except Exception:
                    pass
                _rate_acquired = False
            if ws_url and _tab_pool is not None:
                try:
                    _tab_pool.put_nowait(ws_url)
                except queue.Full:
                    pass

    return None


def close_browser() -> None:
    """Shut down Chrome and free resources."""
    global _proc, _tab_pool, _pool_size, _rate_semaphore

    with _browser_lock:
        _tab_pool = None
        _pool_size = 0
        _rate_semaphore = None

        if _proc is not None:
            try:
                _proc.terminate()
                _proc.wait(timeout=5)
            except Exception:
                try:
                    _proc.kill()
                except Exception:
                    pass
            _proc = None
            state.syslog("cdp_client: Chrome terminated")


def get_stats() -> dict:
    """Return browser usage statistics."""
    with _stats_lock:
        s = dict(_stats)
    if s["pages_fetched"] > 0:
        s["avg_time"] = round(s["total_time"] / s["pages_fetched"], 2)
    else:
        s["avg_time"] = 0.0
    return s
