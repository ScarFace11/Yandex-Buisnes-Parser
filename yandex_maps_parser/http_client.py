"""
HTTP session management and low-level request helpers.
"""
import threading
import time

import requests
from requests.adapters import HTTPAdapter

from .constants import USER_AGENTS
from . import state

# ── Per-thread session storage ────────────────────────────────
_ua_lock     = threading.Lock()
_ua_index    = 0
_proxy_lock  = threading.Lock()
_proxy_index = 0
_local       = threading.local()

_MAX_RATE_LIMIT_RETRIES = 8

# Hard cap on requests/second to avoid triggering 429 errors.
# The token bucket uses this as the ceiling regardless of DELAY settings.
_MAX_RPS = 10.0


def _next_ua() -> str:
    global _ua_index
    with _ua_lock:
        ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
        _ua_index += 1
    return ua


def _next_proxy() -> dict | None:
    if not state.PROXIES:
        return None
    global _proxy_index
    with _proxy_lock:
        p = state.PROXIES[_proxy_index % len(state.PROXIES)]
        _proxy_index += 1
    return {"http": p, "https": p}


def _make_session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({
        "User-Agent": _next_ua(),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://yandex.ru/maps/",
        "Connection": "keep-alive",
    })
    if proxy := _next_proxy():
        s.proxies.update(proxy)
    return s


# Shared session for single-threaded requests (search, geocoding)
_main_session = _make_session()


def _worker_session() -> requests.Session:
    """Return (or lazily create) the current thread's dedicated session."""
    if not hasattr(_local, "session"):
        _local.session = _make_session()
    return _local.session


# ── Global rate limiting ─────────────────────────────────────

class _TokenBucket:
    __slots__ = ("_capacity", "_tokens", "_lock", "_last")

    def __init__(self, capacity: float) -> None:
        self._capacity = max(1.0, capacity)
        self._tokens = self._capacity
        self._lock = threading.Lock()
        self._last = time.monotonic()

    def try_acquire(self, rate: float) -> float:
        """
        Consume one token if available; otherwise return the seconds to
        wait for one (token not consumed). Thread-safe.
        """
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            return (1.0 - self._tokens) / max(rate, 1e-9)


_token_bucket = _TokenBucket(capacity=64.0)

_cooldown_until = 0.0
_cooldown_lock  = threading.Lock()


def _set_cooldown(seconds: float) -> None:
    """Pause the whole pool for *seconds* (extends any existing cooldown)."""
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _cooldown_remaining() -> float:
    with _cooldown_lock:
        return max(0.0, _cooldown_until - time.monotonic())


# ── Usage statistics ─────────────────────────────────────────
_stats_lock = threading.Lock()
_stats = {
    "requests": 0,
    "by_kind": {},
    "rate_limits": 0,
    "cooldown_seconds": 0.0,
    "retries": 0,
}


def _request_kind(url: str) -> str:
    if "search-maps.yandex" in url:
        return "search"
    if "geocode-maps.yandex" in url:
        return "geocode"
    if "yandex.ru/maps/org" in url:
        return "detail"
    return "other"


def _stats_add(key: str, n=1) -> None:
    with _stats_lock:
        if key == "by_kind":
            return
        _stats[key] = _stats.get(key, 0) + n


def _stats_count_request(url: str) -> None:
    kind = _request_kind(url)
    with _stats_lock:
        _stats["requests"] += 1
        _stats["by_kind"][kind] = _stats["by_kind"].get(kind, 0) + 1


def reset_stats() -> None:
    with _stats_lock:
        _stats["requests"] = 0
        _stats["by_kind"] = {}
        _stats["rate_limits"] = 0
        _stats["cooldown_seconds"] = 0.0
        _stats["retries"] = 0


def get_stats() -> dict:
    with _stats_lock:
        return dict(_stats, by_kind=dict(_stats["by_kind"]))


def _wait_for_token() -> bool:
    """
    Block until the token bucket grants a slot AND any 429 cooldown has
    elapsed. Returns True if the wait was interrupted by a stop/skip request.
    The rate is capped at _MAX_RPS to prevent 429 errors.
    """
    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return True
        if state.is_skip_city():
            return True
        wait = max(_token_bucket.try_acquire(_MAX_RPS), _cooldown_remaining())
        if wait <= 0:
            return False
        if _interruptible_sleep(wait, quiet=True):
            return True


def _interruptible_sleep(seconds: float, quiet: bool = False) -> bool:
    """
    Wait *seconds*, checking stop_event and skip_event every second.
    Returns True if interrupted (stop/skip was requested).
    """
    end = time.time() + seconds
    reported: set[int] = set()
    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return True
        if state.is_skip_city():
            return True
        remaining = end - time.time()
        if remaining <= 0:
            return False
        if not quiet:
            bucket = int(remaining // 10) * 10
            if bucket > 0 and bucket not in reported:
                reported.add(bucket)
                state.warn(f"  \u23f8 \u0410\u0432\u0442\u043e\u043f\u0430\u0443\u0437\u0430 \u2014 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u043c \u0447\u0435\u0440\u0435\u0437 \u2248{bucket} \u0441\u0435\u043a\u2026")
        time.sleep(min(1.0, remaining))


def _abortable_get(s, url, params, timeout, allow_redirects, stop_event, skip_event):
    """Run GET in a thread, abort if stop/skip is set during the request.

    This allows the search to respond to stop/skip within ~1 second
    even during a long HTTP request (which normally blocks for up to 20s).
    """
    result = [None]  # mutable container for thread result
    error = [None]

    def _do_request():
        try:
            result[0] = s.get(url, params=params, timeout=timeout, allow_redirects=allow_redirects)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_do_request, daemon=True)
    t.start()

    # Wait for request to complete OR for stop/skip signal
    while t.is_alive():
        t.join(timeout=0.5)  # check every 0.5s
        if stop_event and stop_event.is_set():
            return None  # stop requested — abort
        if skip_event and skip_event.is_set():
            return None  # skip requested — abort

    if error[0] is not None:
        raise error[0]
    return result[0]


def _get(
    url: str,
    params: dict | None = None,
    session: requests.Session | None = None,
    timeout: int | tuple = (8, 20),
    allow_redirects: bool = True,
) -> requests.Response | None:
    s = session or _main_session
    net_attempts    = 0
    rate_limit_hits = 0
    _stats_count_request(url)

    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None
        if state.is_skip_city():
            return None
        if _wait_for_token():
            return None
        try:
            state.syslog(f"http_get: {url[:80]}")
            r = _abortable_get(s, url, params, timeout, allow_redirects,
                               state._STOP_EVENT, state._SKIP_CITY_EVENT)

            state.syslog(f"http_response: status={r.status_code}, url={url[:80]}")
            if r.status_code == 429:
                rate_limit_hits += 1
                _stats_add("rate_limits")
                if rate_limit_hits > _MAX_RATE_LIMIT_RETRIES:
                    state.warn(
                        f"\u041b\u0438\u043c\u0438\u0442 API (429) \u2014 \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u043c\u043d\u043e\u0433\u043e \u043f\u043e\u0432\u0442\u043e\u0440\u043e\u0432 ({rate_limit_hits}), \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0430\u0435\u043c URL."
                    )
                    return None
                retry_after = 0
                try:
                    retry_after = int(r.headers.get("Retry-After", 0))
                except (ValueError, TypeError):
                    pass
                wait = retry_after if retry_after > 0 else min(20 * rate_limit_hits, 120)
                state.warn(
                    f"\u23f8 \u041b\u0438\u043c\u0438\u0442 API (429). \u0410\u0432\u0442\u043e\u043f\u0430\u0443\u0437\u0430 {wait} \u0441\u0435\u043a, \u0437\u0430\u0442\u0435\u043c \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u043c\u2026 "
                    f"(\u043f\u043e\u043f\u044b\u0442\u043a\u0430 {rate_limit_hits}/{_MAX_RATE_LIMIT_RETRIES})"
                )
                _set_cooldown(wait)
                _stats_add("cooldown_seconds", wait)
                if _interruptible_sleep(wait):
                    return None
                state.warn("\u25b6 \u041f\u0430\u0443\u0437\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430, \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0435\u043c\u2026")
                continue

            if r.status_code == 403:
                state.syslog(f"http_403: url={url[:100]}")
                state.warn("Доступ запрещён (403) — возможно, лимит API или блокировка IP.")
                return None
            if r.status_code < 500:
                return r

            # 5xx
            net_attempts += 1
            _stats_add("retries")
            state.syslog(f"http_5xx: status={r.status_code}, url={url[:100]}, attempt={net_attempts}/{state.RETRY_COUNT}")
            state.warn(f"⚠ HTTP {r.status_code} — повтор {net_attempts}/{state.RETRY_COUNT}")
            if net_attempts >= state.RETRY_COUNT:
                return None
            if _interruptible_sleep(state.RETRY_DELAY * net_attempts, quiet=True):
                return None

        except (requests.ConnectionError, requests.Timeout, OSError) as e:
            net_attempts += 1
            _stats_add("retries")
            state.syslog(f"http_error: {type(e).__name__}: {e}, url={url[:100]}, attempt={net_attempts}")
            state.warn(f"⚠ Сеть: {type(e).__name__} — повтор {net_attempts}/{state.RETRY_COUNT}")
            if net_attempts >= state.RETRY_COUNT:
                return None
            if _interruptible_sleep(state.RETRY_DELAY * net_attempts, quiet=True):
                return None


def _head(url: str, timeout: int = 10) -> int:
    """HEAD-check a URL (used for social-link validation)."""
    if state._STOP_EVENT and state._STOP_EVENT.is_set():
        return 0
    if state.is_skip_city():
        return 0
    if _wait_for_token():
        return 0
    _stats_count_request(url)
    try:
        headers = {
            "User-Agent": _next_ua(),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        proxies = None
        if state.PROXIES:
            p = _next_proxy()
            proxies = {"http": p, "https": p}
        r = requests.head(
            url, timeout=timeout, allow_redirects=True,
            headers=headers, proxies=proxies,
        )
        return r.status_code
    except Exception:
        return 0
