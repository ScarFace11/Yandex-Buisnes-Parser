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


def _cdp_navigate_and_get_html(ws_url: str, url: str, timeout_s: float = 30) -> str | None:
    """Navigate to URL via CDP WebSocket and return page HTML.

    Uses websocket-client for synchronous CDP communication.
    """
    try:
        import websocket
        ws = websocket.create_connection(ws_url, timeout=timeout_s)
        try:
            # Navigate
            msg_id = 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": url}
            }))

            # Wait for loadEventFired or timeout
            deadline = time.monotonic() + timeout_s
            loaded = False
            while time.monotonic() < deadline:
                try:
                    raw = ws.recv()
                    data = json.loads(raw)
                    if data.get("method") == "Page.loadEventFired":
                        loaded = True
                        break
                    # Also accept Page.frameStoppedLoading
                    if data.get("method") == "Page.frameStoppedLoading":
                        loaded = True
                        break
                except websocket.WebSocketTimeoutException:
                    break
                except Exception:
                    break

            if not loaded:
                # Give JS a moment to render
                time.sleep(1.5)

            # Get HTML content
            msg_id += 1
            ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML"}
            }))

            # Read response
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    raw = ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == msg_id:
                        result = data.get("result", {}).get("result", {})
                        return result.get("value", "")
                except Exception:
                    break

            return None
        finally:
            ws.close()
    except ImportError:
        state.syslog("cdp_client: websocket-client not installed")
        return None
    except Exception as e:
        state.syslog(f"cdp_client: CDP error: {e}")
        return None


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


def fetch_page(url: str, timeout_ms: int = 30000, biz_id: str = "") -> str | None:
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
        try:
            if _rate_semaphore:
                _rate_semaphore.acquire(timeout=5)

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
            if _rate_semaphore:
                try:
                    _rate_semaphore.release()
                except Exception:
                    pass
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
