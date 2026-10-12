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
import re
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import state

# ── Config ──────────────────────────────────────────────────
# Порядок — по «похожести на обычного пользователя». Сначала настоящие
# браузеры машины (Chrome, Edge, Chromium): они обновляются, имеют обычные
# версии и профиль, и именно так страницы открывает человек. Сборка
# Chromium из кеша Playwright идёт последней: она осталась у тех, кто ставил
# прежние версии приложения, и нужна только как запасной вариант — встроенный
# Chromium отстаёт по версии и его автоматизация виднее антиботу.
_CHROME_PATHS = [
    # Windows: стандартный Google Chrome (user- и system-wide установки)
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    # Windows: Edge — тот же Chromium, обычный браузер системы
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    # macOS: app bundles (Chrome / Chromium / Edge)
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    # Запасной вариант: Chromium из кеша Playwright (старые установки)
    Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe",
    Path.home() / "Library/Caches/ms-playwright/chromium-1234/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    Path.home() / "Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
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

# Debug window (separate visible Chrome, CDP only, own temp profile)
_debug_proc = None
_debug_port: int = 0
_debug_profile_dir: str | None = None
# Собственный временный профиль основного браузера: сессии, куки и история
# пользователя остаются нетронутыми, а вкладки приложения не видят его
# аккаунтов (а он — наших). Папка удаляется при закрытии браузера.
_pool_profile_dir: str | None = None
# RLock: open_debug_window() may call close_debug_window() on failure.
_debug_lock = threading.RLock()

# Rate limiting
_rate_semaphore: threading.Semaphore | None = None

# Warned about a block/stub page this run (once per process).
_museum_warned = False

# Stats
_stats_lock = threading.Lock()
_stats = {"pages_fetched": 0, "pages_error": 0, "total_time": 0.0,
          "restarts": 0}

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
#
# The default here must stay close to the bundled Chromium's real version;
# init_browser() re-syncs it with the actual running browser at startup.
_CDP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def eval_in_page(
    url: str,
    expression: str,
    wait_expr: str = "",
    timeout_s: float = 45.0,
    biz_id: str = "",
) -> str | None:
    """Открыть `url` в настоящем Chrome и выполнить JS-выражение на странице.

    Единственный способ сбора данных в приложении — реальный браузер:
      * `wait_expr` — выражение, которое должно стать истинным до замера
        (например, «карточки поиска появились»).
      * `expression` — что вернуть; это может быть async-функция, тогда
        браузер сам прокрутит список и отдаст готовый JSON.

    Возвращает строку-результат или None (страница/браузер недоступны,
    сработала остановка). Вкладка возвращается в пул в любом случае.
    """
    global _museum_warned
    try:
        import websocket
    except ImportError:
        state.syslog("cdp_client: websocket-client not installed")
        return None
    if not is_available():
        return None

    ws_url = None
    _rate_acquired = False
    try:
        if _rate_semaphore:
            if not _poll_acquire(_rate_semaphore, 5.0):
                return None
            _rate_acquired = True
        try:
            ws_url = _poll_queue_get(_tab_pool, 5.0)
        except queue.Empty:
            return None
        if not _is_tab_alive(ws_url):
            _close_dead_tab(ws_url)
            ws_url = _create_tab()
            if not ws_url:
                return None

        with _stats_lock:
            _stats["pages_fetched"] += 1
        return _cdp_eval_page(ws_url, url, expression, wait_expr, timeout_s)
    except Exception as e:
        state.syslog(f"cdp_client: eval_in_page error: {type(e).__name__}: {e}")
        return None
    finally:
        if _rate_acquired and _rate_semaphore:
            try:
                _rate_semaphore.release()
            except Exception:
                pass
        if ws_url and _tab_pool is not None:
            try:
                _tab_pool.put_nowait(ws_url)
            except queue.Full:
                pass


def _cdp_eval_page(
    ws_url: str,
    url: str,
    expression: str,
    wait_expr: str,
    timeout_s: float,
) -> str | None:
    """Навигация + ожидание + замер в одном WebSocket-соединении."""
    try:
        import websocket
    except ImportError:
        return None

    deadline = time.monotonic() + timeout_s
    ws = None
    try:
        ws = websocket.create_connection(ws_url, timeout=min(timeout_s, 10))
        seq = {"id": 0}

        def _send(method: str, params: dict | None = None):
            seq["id"] += 1
            ws.send(json.dumps({"id": seq["id"], "method": method, "params": params or {}}))

        _send("Page.enable")
        _send("Network.setUserAgentOverride", {"userAgent": _CDP_USER_AGENT})
        # Вкладка из пула — фоновая: Chrome отдаёт ей visibilityState="hidden",
        # а страница Яндекс.Карт в скрытой вкладке НЕ догружает продолжение
        # списка (в живом замере 5 карточек вместо 25). Эмуляция активной
        # страницы возвращает вкладке visible+focused — тогда виртуализованный
        # список ведёт себя как у обычного пользователя.
        _send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        _send("Page.navigate", {"url": url})

        # Ждём готовности страницы (и, если задано, появления нужного узла).
        while time.monotonic() < deadline:
            if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                return None
            expr = "document.readyState" if not wait_expr else (
                "document.readyState + '|' + String(!!(" + wait_expr + "))"
            )
            status = _cdp_eval(ws, expr, min(deadline, time.monotonic() + 6.0))
            if status:
                parts = status.split("|")
                ready = parts[0]
                found = len(parts) > 1 and parts[1] == "true"
                if ready == "complete" and (found or not wait_expr):
                    break
            time.sleep(min(0.7, max(0.0, deadline - time.monotonic())))

        return _cdp_eval(
            ws, expression, deadline, await_promise=True
        )
    except Exception as e:
        state.syslog(f"cdp_client: eval page error: {type(e).__name__}: {e}")
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


_CDP_EVAL_ID = 90001  # id for Runtime.evaluate responses on a fresh WS


def _cdp_eval(ws, expression: str, deadline: float, await_promise: bool = False) -> str | None:
    """Evaluate `expression` via Runtime.evaluate, bounded by `deadline`.

    await_promise=True — дожидаемся результата async-функции в самой странице
    (нужно для поиска: прокрутка и сбор карточек идут внутри браузера, чтобы
    наружу уходил один готовый JSON, а не десятки запросов к странице).
    """
    try:
        ws.send(json.dumps({
            "id": _CDP_EVAL_ID,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": bool(await_promise),
            },
        }))
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                # Тишина в сокете — не ошибка, а ожидание: обещание в
                # странице может считаться дольше пяти секунд (сбор выдачи
                # Яндекс.Карт с прокруткой — 6–10 с, до 250 карточек —
                # дольше). Раньше здесь стоял break, поэтому такой замер
                # обрывался на пятой секунде и возвращал None, хотя дедлайн
                # (до 90 с) был ещё далеко: поиск «иногда» не находил ни
                # одной карточки и показывал «выдача не открылась».
                ws.settimeout(min(remaining, 5.0))
                data = json.loads(ws.recv())
            except Exception as exc:
                if not _is_socket_timeout(exc):
                    break
                if _stop_requested():
                    break
                continue
            if data.get("id") == _CDP_EVAL_ID:
                value = data.get("result", {}).get("result", {}).get("value")
                return value if isinstance(value, str) else (str(value) if value is not None else None)
    except Exception:
        pass
    return None


def _is_socket_timeout(exc: BaseException) -> bool:
    """Таймаут чтения сокета (в отличие от разрыва связи с вкладкой)."""
    import socket
    kinds: list[type] = [TimeoutError, socket.timeout]
    try:
        import websocket
        cls = getattr(websocket, "WebSocketTimeoutException", None)
        if cls is not None:
            kinds.append(cls)
    except Exception:
        pass
    return isinstance(exc, tuple(kinds))


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
        # См. _cdp_eval_page: фоновая вкладка пула должна считать себя
        # активной, иначе страница тормозит ленивую догрузку (соцсети и
        # блоки карточки рисуются по мере появления на экране).
        _send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        _send("Page.navigate", {"url": url})

        # Numeric org id from the target URL — appears in the final location.href
        # even after Yandex rewrites the URL to a slug form.
        from urllib.parse import urlparse
        path_segs = [s for s in urlparse(url).path.split("/") if s]
        token = path_segs[-1] if (path_segs and path_segs[-1].isdigit()) else None

        # Expression: href|readyState|len (len kept for debugging).
        expr = (
            "location.href + '|' + document.readyState + '|' + "
            "document.documentElement.outerHTML.length"
        )

        # Poll until the navigation commits AND readyState == "complete".
        # Harvesting earlier (e.g. once the doc is merely large) returns a
        # PARTIAL document — the socials block sits near the end of the
        # server HTML and was missing in live tests (125KB no-links page).
        started = time.monotonic()
        committed = token is None  # nothing to match → assume committed
        while time.monotonic() < overall_deadline:
            # Stop/skip must abort a page mid-load, not burn the whole
            # deadline — otherwise run()'s detail_pool.shutdown(wait=True)
            # blocks the stop/skip response for up to 40s per in-flight page.
            if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                return None
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                break
            status = _cdp_eval(ws, expr, min(overall_deadline, time.monotonic() + 6.0))
            if status:
                parts = status.split("|")
                href = parts[0] if parts else ""
                ready = parts[1] if len(parts) > 1 else ""
                if token:
                    if committed is False and token in href:
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
        # the document commits. Bounded by the overall deadline. Stop/skip
        # aborts here too so a stuck page never delays run shutdown.
        attempts = 0
        while attempts < 3 and time.monotonic() < overall_deadline - 1.0:
            if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                return None
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


# ── Tab pool management ─────────────────────────────────────

def _create_tab() -> str | None:
    """Create a new Chrome tab and return its WebSocket URL."""
    ws_url = _cdp_new_tab(_base_port)
    if ws_url:
        # Convert ws://127.0.0.1:PORT/devtools/page/ID to use our port
        # The WS URL from Chrome already has the correct port
        pass
    return ws_url


def _close_dead_tab(ws_url: str) -> None:
    """Close a Chrome tab that failed the health check so it does not leak.

    Dead/unresponsive tabs previously stayed open in Chrome forever (each
    holding a renderer process); over a long run they accumulate. The tab id
    is the trailing path segment of the WebSocket debugger URL.
    """
    try:
        tab_id = ws_url.rstrip("/").rsplit("/", 1)[-1]
        if tab_id:
            _cdp_close_tab(_base_port, tab_id)
    except Exception:
        pass


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


# ── Debug window (visible Chrome, CDP only, no tab pool) ─────


def open_debug_window(start_url: str = "about:blank") -> int | None:
    """Отдельное ВИДИМОЕ окно Chrome с открытым CDP-портом.

    start_url — что открыть в первом окне (по умолчанию about:blank;
        приложение передаёт свой UI, чтобы не открывать его вручную).

    Запускается на собственном временном профиле (--user-data-dir), поэтому
    работает даже если системный Chrome сломан или уже запущен: новый
    процесс не перепривязывается к существующему экземпляру и CDP-порт
    действительно открывается. Бинарник берётся из _find_chrome() — сначала
    Chromium из Playwright, затем системный Chrome/Edge.

    Возвращает CDP-порт или None, если окно открыть не удалось.
    """
    global _debug_proc, _debug_port, _debug_profile_dir
    with _debug_lock:
        if _debug_proc is not None and _debug_proc.poll() is None:
            return _debug_port
        chrome_path = _find_chrome()
        if not chrome_path:
            state.warn("Отладочное окно: Chrome/Chromium не найден.")
            return None
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            _debug_port = s.getsockname()[1]
        # Свежий временный профиль: изолирует окно от запущенного Chrome
        # пользователя (иначе новый процесс просто откроет вкладку в нем
        # и завершится, а CDP-порт так и не откроется).
        import tempfile as _tempfile
        try:
            _debug_profile_dir = _tempfile.mkdtemp(prefix="yp-cdp-debug-")
        except Exception:
            _debug_profile_dir = None
        cmd = [
            chrome_path,
            f"--remote-debugging-port={_debug_port}",
            "--remote-allow-origins=*",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-translate",
            "--disable-breakpad",
            "--disable-domain-reliability",
            "--mute-audio",
            start_url,
        ]
        if _debug_profile_dir:
            cmd.insert(1, f"--user-data-dir={_debug_profile_dir}")
        try:
            _debug_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            state.syslog(f"debug: failed to launch Chrome: {e}")
            _debug_proc = None
            return None
        # Ждём ответ CDP-порта (до ~5 с), а не фиксированный sleep.
        for _ in range(10):
            time.sleep(0.5)
            if _cdp_get(_debug_port, "/json/version"):
                state.syslog(f"debug: Chrome window opened, CDP port={_debug_port}")
                return _debug_port
            if _debug_proc.poll() is not None:
                break
        state.syslog("debug: Chrome window did not open (process exited)")
        _close_debug_window_locked()
        return None


def _close_debug_window_locked() -> None:
    """Гасит отладочное окно. Вызывается под _debug_lock."""
    global _debug_proc, _debug_port, _debug_profile_dir
    proc, profile = _debug_proc, _debug_profile_dir
    _debug_proc = None
    _debug_port = 0
    _debug_profile_dir = None
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    if profile:
        try:
            import shutil as _shutil
            _shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass


def close_debug_window() -> None:
    """Закрывает отладочное окно Chrome (процесс + временный профиль)."""
    with _debug_lock:
        _close_debug_window_locked()


def is_installed() -> bool:
    """Check if Chrome/Chromium is available on this system."""
    return _find_chrome() is not None


def init_browser(pool_size: int = 8, visible: bool = False) -> bool:
    """Launch Chrome and create a pool of tabs for parallel fetching.

    pool_size — number of tabs in the pool (each tab is a renderer process).
    visible — if True, launch a regular Chrome WINDOW instead of headless;
        the CDP tab pool works the same way, you just see it happening.
    """
    global _proc, _base_port, _tab_pool, _pool_size, _rate_semaphore, _CDP_USER_AGENT
    global _museum_warned, _pool_profile_dir
    _museum_warned = False  # fresh run — allow the block-page warning again

    chrome_path = _find_chrome()
    if not chrome_path:
        state.warn("Chrome/Chromium не найден. Установите Google Chrome или Chromium.")
        return False

    # Cap the tab pool: each tab is a separate renderer process (30-250 MB).
    # 20 tabs ≈ 2.3 GB RAM and 20 simultaneous navigations to the same host
    # also raise Yandex's bot-detection rate — 12 is a good speed/RAM/
    # anti-bot balance. 12 tabs ≈ 1.2-1.5 GB.
    pool_size = min(pool_size, 12)

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

                    # Свой временный профиль. Без него Chrome берёт профиль
                    # пользователя: вкладки приложения получили бы доступ к
                    # его сессиям, а сам запуск конфликтовал бы с уже открытым
                    # браузером. С отдельным профилем приложение не касается
                    # ни аккаунтов, ни истории — и «подставлять» тут нечего.
                    if not _pool_profile_dir:
                        try:
                            import tempfile as _tempfile
                            _pool_profile_dir = _tempfile.mkdtemp(prefix="yp-cdp-")
                        except Exception:
                            _pool_profile_dir = None

                    _cmd: list[str] = [
                        chrome_path,
                        f"--remote-debugging-port={_base_port}",
                        "--remote-allow-origins=*",
                        "--no-first-run",
                        "--no-default-browser-check",
                        # Не помечаем вкладки как «автоматизированные»: флаг
                        # поднимает ровно тот признак, от которого антибот и
                        # защищается, а его отсутствие — обычный браузер.
                        "--disable-blink-features=AutomationControlled",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--disable-features=VizDisplayCompositor",
                        # Фоновая вкладка не должна «засыпать»: списки на
                        # Яндекс.Картах догружаются только у активной страницы
                        # (таймеры, анимации и IntersectionObserver в фоне
                        # Chrome тормозит).
                        "--disable-background-timer-throttling",
                        "--disable-backgrounding-occluded-windows",
                        "--disable-renderer-backgrounding",
                        # Memory trim: kill background work (updates, sync,
                        # extensions, crash dumps) that otherwise adds
                        # processes and RAM for no benefit in headless.
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--disable-sync",
                        "--disable-translate",
                        "--disable-breakpad",
                        "--disable-domain-reliability",
                        "--mute-audio",
                    ]
                    if _pool_profile_dir:
                        _cmd.append(f"--user-data-dir={_pool_profile_dir}")
                    _cmd.append("about:blank")
                    if not visible:
                        # Headless (default): no window. visible=True keeps
                        # the Chrome window open — same CDP pool inside.
                        _cmd.insert(3, "--headless=new")
                    _proc = subprocess.Popen(
                        _cmd,
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

                # Sync the UA override with the REAL browser version — a
                # stale UA is one of the hollowest bot signals there is.
                try:
                    m_ver = re.search(r"Chrome/(\d+)", str(version.get("Browser") or ""))
                    if m_ver:
                        _CDP_USER_AGENT = re.sub(
                            r"Chrome/\d+", f"Chrome/{m_ver.group(1)}", _CDP_USER_AGENT
                        )
                        state.syslog(f"cdp_client: UA override synced to Chrome/{m_ver.group(1)}")
                except Exception:
                    pass

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


def _stop_requested() -> bool:
    """True when stop or skip-city was requested."""
    return bool(
        (state._STOP_EVENT and state._STOP_EVENT.is_set())
        or state.is_skip_city()
    )


def _poll_acquire(semaphore, timeout: float) -> bool:
    """Acquire a semaphore, polling stop/skip every 0.5s.

    Returns True when acquired. False means the caller should re-check
    stop/skip (and may retry) — the full timeout was NOT necessarily spent
    when stop is set, so stop/skip interrupts this wait within ~0.5s.
    """
    deadline = time.monotonic() + timeout
    while True:
        if _stop_requested():
            return False
        if semaphore.acquire(blocking=False):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.5, remaining))


def _poll_queue_get(q, timeout: float):
    """queue.get with stop/skip polling every 0.5s (aborts early on stop)."""
    deadline = time.monotonic() + timeout
    while True:
        if _stop_requested():
            raise queue.Empty
        try:
            return q.get_nowait()
        except queue.Empty:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            time.sleep(min(0.5, remaining))


def fetch_page(url: str, timeout_ms: int = 40000, biz_id: str = "") -> str | None:
    """Fetch a page using Chrome CDP and return HTML."""
    global _museum_warned
    if not is_available():
        return None

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
                # Poll in short slices so a stop/skip is noticed within ~0.5s
                # even while the pool is fully saturated.
                if not _poll_acquire(_rate_semaphore, 5.0):
                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        return None
                    if state.is_skip_city():
                        return None
                    continue  # still busy, no stop — retry the attempt
                _rate_acquired = True

            try:
                ws_url = _poll_queue_get(_tab_pool, 5.0)
            except queue.Empty:
                # Check stop before retrying
                if state._STOP_EVENT and state._STOP_EVENT.is_set():
                    return None
                if state.is_skip_city():
                    return None
                state.syslog("cdp_client: no free tabs, waiting...")
                continue

            # Check tab health
            if not _is_tab_alive(ws_url):
                state.syslog("cdp_client: tab dead, creating replacement...")
                _close_dead_tab(ws_url)   # free the Chrome tab, don't leak it
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

            if html:
                return html
            # Пустая страница — не приговор: таймаут навигации или заглушка
            # антибота часто снимаются со свежей вкладкой. Раньше пустой
            # ответ возвращался сразу, и карточка терялась без повторной
            # попытки — отсюда жалоба «Карточка не открылась в браузере».
            state.syslog(f"cdp_client: empty page (attempt {attempt + 1}/{_MAX_RETRIES}) {url}")
            if attempt < _MAX_RETRIES - 1:
                try:
                    new_ws = _create_tab()
                    if new_ws:
                        if ws_url:
                            _close_dead_tab(ws_url)
                        ws_url = new_ws
                except Exception:
                    pass

        except Exception as e:
            with _stats_lock:
                _stats["pages_error"] += 1
            # Surface the failure in get_analytics()'s «errors» counter too
            # (it used to stay 0 forever, because the HTTP engine that fed it
            # is gone). Import locally: this handler may run before line 980.
            try:
                from .http_client import _count_error
                _count_error()
            except Exception:
                pass
            state.syslog(f"cdp_client: error: {type(e).__name__}: {e}")

            # Try to recover: create a fresh tab
            if attempt < _MAX_RETRIES - 1:
                state.syslog("cdp_client: attempting recovery...")
                try:
                    new_ws = _create_tab()
                    if new_ws:
                        if ws_url:
                            _close_dead_tab(ws_url)  # don't leak the old tab
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
    global _proc, _tab_pool, _pool_size, _rate_semaphore, _pool_profile_dir

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

        # Временный профиль живёт только до конца прогона: ни файлов
        # пользователя, ни следов между запусками в нём не остаётся.
        profile = _pool_profile_dir
        _pool_profile_dir = None
        if profile:
            try:
                import shutil
                shutil.rmtree(profile, ignore_errors=True)
            except Exception:
                pass


def get_stats() -> dict:
    """Return browser usage statistics."""
    with _stats_lock:
        s = dict(_stats)
    if s["pages_fetched"] > 0:
        s["avg_time"] = round(s["total_time"] / s["pages_fetched"], 2)
    else:
        s["avg_time"] = 0.0
    return s
