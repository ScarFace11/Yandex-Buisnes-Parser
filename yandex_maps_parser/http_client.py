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
# All worker threads share one token bucket so the pool paces as a
# unit instead of every thread hammering the API independently.
# A 429 hit anywhere sets a global cooldown that pauses the whole pool.


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
# Counters for quota / rate-limit transparency: requests by kind, 429 hits,
# total cooldown time, and network retries. Reset per run via reset_stats().
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
    elapsed. Returns True if the wait was interrupted by a stop request.
    The bucket rate is derived from the live config (MAX_WORKERS /
    average DELAY), so run_web() overrides take effect automatically.
    """
    workers   = max(1, getattr(state, "MAX_WORKERS", 8))
    avg_delay = (state.DELAY_MIN + state.DELAY_MAX) / 2.0
    rate      = workers / max(0.05, avg_delay)
    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return True
        wait = max(_token_bucket.try_acquire(rate), _cooldown_remaining())
        if wait <= 0:
            return False
        if _interruptible_sleep(wait, quiet=True):
            return True


def _interruptible_sleep(seconds: float, quiet: bool = False) -> bool:
    """
    Wait *seconds*, checking stop_event every second.
    Returns True if interrupted (stop was requested).
    """
    end = time.time() + seconds
    reported: set[int] = set()
    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
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
        if _wait_for_token():
            return None
        try:
            r = s.get(url, params=params, timeout=timeout, allow_redirects=allow_redirects)

            if r.status_code == 429:
                rate_limit_hits += 1
                _stats_add("rate_limits")
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
                # Pause the WHOLE pool, not just this thread — other workers
                # will also wait out the cooldown before their next request.
                _set_cooldown(wait)
                _stats_add("cooldown_seconds", wait)
                if _interruptible_sleep(wait):
                    return None
                state.warn("▶ Пауза завершена, продолжаем…")
                continue

            if r.status_code == 403:
                state.warn("Доступ запрещён (403) — возможно, лимит API или блокировка IP.")
                return None
            if r.status_code < 500:
                return r

            # 5xx — временная ошибка сервера
            net_attempts += 1
            _stats_add("retries")
            if net_attempts >= state.RETRY_COUNT:
                return None
            if _interruptible_sleep(state.RETRY_DELAY * net_attempts, quiet=True):
                return None

        except (requests.ConnectionError, requests.Timeout, OSError):
            net_attempts += 1
            _stats_add("retries")
            if net_attempts >= state.RETRY_COUNT:
                return None
            if _interruptible_sleep(state.RETRY_DELAY * net_attempts, quiet=True):
                return None


def _head(url: str, timeout: int = 10) -> int:
    """
    HEAD-check a URL (used for social-link validation). Reuses the proxy
    rotation so links to sites that are only reachable through a proxy
    (Instagram / Facebook / X from RU IPs) aren't wrongly flagged as dead.
    Paced through the same token bucket — without it, validating a batch of
    records fires an unpaced burst of HEAD requests.
    """
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
