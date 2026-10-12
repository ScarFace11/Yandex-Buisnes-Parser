"""
Статистика сбора: счётчики, задержки, аналитика для интерфейса.

Здесь раньше жил HTTP-движок (httpx + curl_cffi с подменой TLS-отпечатка
Chrome). Он удалён вместе с HTTP-путём: страницы Яндекс.Карт читает только
настоящий браузер (см. cdp_client.py и browser_search.py). Прямые запросы
ловит антибот, а сам IP/аккаунт после серии таких обращений выглядит
подозрительно — приложение этим не пользуется вообще.

Осталось то, что нужно интерфейсу: сколько страниц открыто, сколько заняло,
какая задержка p95 (по ней enrichment включает мягкое торможение) и
реэкспорт лимитера из rate_limit.
"""
import threading
import time
from collections import deque

# Реэкспорт лимитера: extractors/enrichment/cdp_client импортируют эти имена
# отсюда исторически (pyflakes помечает часть как unused — ложное срабатывание).
from .rate_limit import (
    _get_rps, _rps_drop, _rps_reset,
    _set_cooldown, _anti_bot_detected, _anti_bot_reset, _cooldown_remaining,
    _wait_for_token, _interruptible_sleep,
)
from . import state

# ── Usage statistics + real-time analytics ───────────────────
_stats_lock = threading.Lock()
_stats = {
    "requests": 0,
    "by_kind": {},
    "rate_limits": 0,
    "cooldown_seconds": 0.0,
    "retries": 0,
    "errors": 0,
}

# Rolling latency window (last N pages)
_latency_window: deque[float] = deque(maxlen=200)
_latency_lock = threading.Lock()

# Cached P95 latency — recalculated only when window changes
_cached_p95: float = 0.0
_cached_p50: float = 0.0
_cached_avg: float = 0.0
_latency_version: int = 0  # incremented on each append
_latency_cache_version: int = 0  # last version we recomputed from

# RPS calculation
_rps_start_time: float = 0.0
_rps_request_count: int = 0


def _request_kind(url: str) -> str:
    """Что за страницу открываем: выдача поиска, карточка или что-то ещё."""
    if "yandex.ru/maps/org" in url:
        return "detail"
    if "/maps" in url:
        return "search"
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


def _record_latency(seconds: float) -> None:
    """Record a request latency for rolling average calculation."""
    global _rps_request_count, _latency_version
    with _latency_lock:
        _latency_window.append(seconds)  # deque(maxlen=200) auto-evicts oldest
        _latency_version += 1
    with _stats_lock:
        _rps_request_count += 1


def _get_latency_stats() -> tuple[float, float, float]:
    """Return (avg, p50, p95) from the rolling latency window.

    Caches the computation — only recalculates when the window has changed
    since the last call. Avoids O(n log n) sort on every request.
    """
    global _cached_avg, _cached_p50, _cached_p95, _latency_cache_version
    with _latency_lock:
        if _latency_version == _latency_cache_version and _latency_window:
            return _cached_avg, _cached_p50, _cached_p95
        if not _latency_window:
            return 0.0, 0.0, 0.0
        n = len(_latency_window)
        _cached_avg = sum(_latency_window) / n
        sorted_lat = sorted(_latency_window)
        _cached_p50 = sorted_lat[n // 2]
        _cached_p95 = sorted_lat[int(n * 0.95)]
        _latency_cache_version = _latency_version
    return _cached_avg, _cached_p50, _cached_p95


def get_analytics() -> dict:
    """Return real-time analytics for the web UI."""
    with _stats_lock:
        total_requests = _stats["requests"]
        errors = _stats["errors"]
        rate_limits = _stats["rate_limits"]
        retries = _stats["retries"]
    avg_latency, p50, p95 = _get_latency_stats()
    # Calculate actual RPS
    now = time.monotonic()
    if _rps_start_time > 0 and now > _rps_start_time:
        elapsed = now - _rps_start_time
        actual_rps = _rps_request_count / elapsed if elapsed > 0 else 0
    else:
        actual_rps = 0.0
    return {
        "rps_target": _get_rps(),
        "rps_actual": round(actual_rps, 1),
        "avg_latency": round(avg_latency, 2),
        "p50_latency": round(p50, 2),
        "p95_latency": round(p95, 2),
        "total_requests": total_requests,
        "errors": errors,
        "rate_limits": rate_limits,
        "retries": retries,
    }


def reset_stats() -> None:
    global _rps_start_time, _rps_request_count
    with _stats_lock:
        _stats["requests"] = 0
        _stats["by_kind"] = {}
        _stats["rate_limits"] = 0
        _stats["cooldown_seconds"] = 0.0
        _stats["retries"] = 0
        _stats["errors"] = 0
    with _latency_lock:
        _latency_window.clear()
    _rps_start_time = time.monotonic()
    _rps_request_count = 0


def get_stats() -> dict:
    """Return detailed statistics with per-kind breakdown."""
    with _stats_lock:
        stats = dict(_stats, by_kind=dict(_stats["by_kind"]))
    try:
        import tracemalloc
        current, peak = tracemalloc.get_traced_memory()
        stats["memory_mb"] = round(current / 1024 / 1024, 1)
        stats["memory_peak_mb"] = round(peak / 1024 / 1024, 1)
    except Exception:
        stats["memory_mb"] = 0
        stats["memory_peak_mb"] = 0
    return stats


def browser_stats() -> dict:
    """Сводка по браузеру (вкладки, открытые страницы) — для панели статистики."""
    try:
        from . import cdp_client
        return cdp_client.get_stats()
    except Exception:
        return {}


def _count_error() -> None:
    """Учесть ошибку загрузки (браузер не открыл страницу)."""
    _stats_add("errors")
    _stats_add("retries")


# state импортируется для совместимости: modules читают статистику через него
_ = state
