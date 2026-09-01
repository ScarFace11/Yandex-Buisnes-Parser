"""
HTTP session management and low-level request helpers.

Uses httpx with HTTP/2 for multiplexed connections — multiple requests
share a single TCP+TLS connection, reducing handshake overhead from
~500ms per request to ~0ms after the first.
"""
import threading
import time

import httpx

from .constants import USER_AGENTS
from . import state

# ── Per-thread session storage ────────────────────────────────
_ua_lock     = threading.Lock()
_ua_index    = 0
_proxy_lock  = threading.Lock()
_proxy_index = 0
_local       = threading.local()

_MAX_RATE_LIMIT_RETRIES = 8

# Adaptive RPS: starts at MIN, increases by STEP every UP_INTERVAL
# seconds when no 429 errors occur, drops by half on 429.
_MIN_RPS = 10.0
_MAX_RPS = 40.0
_RPS_STEP = 5.0
_RPS_UP_INTERVAL = 30  # seconds between auto-increments

_current_rps: float = _MIN_RPS
_rps_last_up: float = 0.0
_rps_lock = threading.Lock()


def _get_rps() -> float:
    """Return the current adaptive RPS limit."""
    global _current_rps, _rps_last_up
    with _rps_lock:
        now = time.monotonic()
        # Auto-increase if no rate limits for _RPS_UP_INTERVAL seconds
        if now - _rps_last_up >= _RPS_UP_INTERVAL and _current_rps < _MAX_RPS:
            _current_rps = min(_current_rps + _RPS_STEP, _MAX_RPS)
            _rps_last_up = now
            state.syslog(f"rps_up: {_current_rps:.0f} RPS")
        return _current_rps


def _rps_drop() -> None:
    """Drop RPS by half on 429 error."""
    global _current_rps, _rps_last_up
    with _rps_lock:
        _current_rps = max(_MIN_RPS, _current_rps / 2)
        _rps_last_up = time.monotonic()  # reset timer
        state.syslog(f"rps_drop: {_current_rps:.0f} RPS (after 429)")


def _rps_reset() -> None:
    """Reset RPS to minimum at the start of a new city."""
    global _current_rps, _rps_last_up
    with _rps_lock:
        _current_rps = _MIN_RPS
        _rps_last_up = time.monotonic()


def _next_ua() -> str:
    global _ua_index
    with _ua_lock:
        ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
        _ua_index += 1
    return ua


def _next_proxy() -> str | None:
    if not state.PROXIES:
        return None
    global _proxy_index
    with _proxy_lock:
        p = state.PROXIES[_proxy_index % len(state.PROXIES)]
        _proxy_index += 1
    return p


def _make_client(proxy: str | None = None) -> httpx.Client:
    """Create an httpx client with HTTP/2 support.

    Each client maintains its own connection pool.  With HTTP/2, multiple
    concurrent requests are multiplexed over a single TCP+TLS connection,
    eliminating the ~500ms handshake overhead per request.
    """
    transport_kwargs = {
        "http2": True,
        "limits": httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30,
        ),
    }
    if proxy:
        transport_kwargs["proxy"] = proxy

    return httpx.Client(
        **transport_kwargs,
        timeout=httpx.Timeout(connect=8, read=20, write=8, pool=5),
        headers={
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://yandex.ru/maps/",
        },
        follow_redirects=True,
    )


# Shared client for single-threaded requests (search, geocoding)
_main_client = _make_client()


def _worker_client() -> httpx.Client:
    """Return (or lazily create) the current thread's dedicated client."""
    if not hasattr(_local, "client"):
        proxy = _next_proxy()
        _local.client = _make_client(proxy)
    return _local.client


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

# Anti-bot backoff: increase delay after detecting anti-bot page
_anti_bot_count = 0
_anti_bot_lock  = threading.Lock()


def _set_cooldown(seconds: float) -> None:
    """Pause the whole pool for *seconds* (extends any existing cooldown)."""
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _anti_bot_detected() -> None:
    """Called when an anti-bot page is detected.  Increases cooldown for
    subsequent requests to avoid further triggers.
    """
    global _anti_bot_count, _cooldown_until
    with _anti_bot_lock:
        _anti_bot_count += 1
        # Exponential backoff: 10s, 20s, 40s, capped at 120s
        backoff = min(10 * (2 ** (_anti_bot_count - 1)), 120)
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + backoff)
    state.syslog(f"anti_bot_backoff: count={_anti_bot_count}, cooldown={backoff}s")
    state.warn(f"⚠ Anti-bot обнаружен (#{_anti_bot_count}). Автопауза {backoff}с...")


def _anti_bot_reset() -> None:
    """Reset anti-bot counter at the start of a new city."""
    global _anti_bot_count
    with _anti_bot_lock:
        _anti_bot_count = 0


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
        wait = max(_token_bucket.try_acquire(_get_rps()), _cooldown_remaining())
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
                state.warn(f"  ⏸ Автопауза — продолжим через ≈{bucket} сек…")
        time.sleep(min(1.0, remaining))


def _abortable_get(client, url, params, timeout, allow_redirects, stop_event, skip_event):
    """Run GET in a thread, abort if stop/skip is set during the request.

    This allows the search to respond to stop/skip within ~1 second
    even during a long HTTP request (which normally blocks for up to 20s).
    """
    result = [None]  # mutable container for thread result
    error = [None]

    def _do_request():
        try:
            # httpx timeout is set on the client; per-request override via keyword
            timeout_obj = httpx.Timeout(timeout[0], read=timeout[1]) if isinstance(timeout, tuple) else httpx.Timeout(timeout)
            result[0] = client.get(url, params=params, timeout=timeout_obj)
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
    session: httpx.Client | None = None,
    timeout: int | tuple = (8, 20),
    allow_redirects: bool = True,
) -> httpx.Response | None:
    s = session or _main_client
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
                _rps_drop()  # adaptive: reduce RPS on rate limit
                if rate_limit_hits > _MAX_RATE_LIMIT_RETRIES:
                    state.warn(
                        f"Лимит API (429) — слишком много повторов ({rate_limit_hits}), пропускаем URL."
                    )
                    return None
                retry_after = 0
                try:
                    retry_after = int(r.headers.get("Retry-After", 0))
                except (ValueError, TypeError):
                    pass
                wait = retry_after if retry_after > 0 else min(20 * rate_limit_hits, 120)
                state.warn(
                    f"⏸ Лимит API (429). Автопауза {wait} сек, затем продолжим… "
                    f"(попытка {rate_limit_hits}/{_MAX_RATE_LIMIT_RETRIES})"
                )
                _set_cooldown(wait)
                _stats_add("cooldown_seconds", wait)
                if _interruptible_sleep(wait):
                    return None
                state.warn("▶ Пауза завершена, продолжаем…")
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

        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError) as e:
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
        proxy = _next_proxy()
        client_kwargs = {"http2": True, "timeout": httpx.Timeout(timeout), "headers": headers, "follow_redirects": True}
        if proxy:
            client_kwargs["proxy"] = proxy
        with httpx.Client(**client_kwargs) as client:
            r = client.head(url)
            return r.status_code
    except Exception:
        return 0
