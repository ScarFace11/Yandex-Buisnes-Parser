"""
Rate limiting: token bucket, adaptive RPS, cooldown, anti-bot backoff.

All global rate-limiting state lives here. http_client.py imports
and calls these functions — it does NOT own rate-limiting policy.
"""
import threading
import time

from . import state

# ── Config ──────────────────────────────────────────────────
_MIN_RPS = 10.0     # resting RPS (reset / steady state)
_MAX_RPS = 15.0
_DROP_FLOOR_RPS = 2.0  # absolute floor after repeated drops (never 0)
_RPS_STEP = 2.0
_RPS_UP_INTERVAL = 45

# ── Adaptive RPS ────────────────────────────────────────────
_current_rps: float = _MIN_RPS
_rps_last_up: float = 0.0
_rps_lock = threading.Lock()


def _get_rps() -> float:
    global _current_rps, _rps_last_up
    with _rps_lock:
        now = time.monotonic()
        if now - _rps_last_up >= _RPS_UP_INTERVAL and _current_rps < _MAX_RPS:
            from .http_client import _get_latency_stats
            _, _, p95 = _get_latency_stats()
            if p95 > 30.0:
                return _current_rps
            _current_rps = min(_current_rps + _RPS_STEP, _MAX_RPS)
            _rps_last_up = now
            state.syslog(f"rps_up: {_current_rps:.0f} RPS")
        return _current_rps


def _rps_drop(reason: str = "429") -> None:
    global _current_rps, _rps_last_up
    with _rps_lock:
        # Halve the current rate. The floor must be BELOW the resting minimum,
        # otherwise dropping from the default 10 RPS is a no-op (10/2 = 5 < 10
        # gets clamped straight back to 10) and the adaptive throttle never
        # actually slows down under load.
        _current_rps = max(_DROP_FLOOR_RPS, _current_rps / 2)
        _rps_last_up = time.monotonic()
        state.syslog(f"rps_drop: {_current_rps:.1f} RPS (reason={reason})")


def _rps_reset() -> None:
    global _current_rps, _rps_last_up
    with _rps_lock:
        _current_rps = _MIN_RPS
        _rps_last_up = time.monotonic()


# ── Token bucket ────────────────────────────────────────────
class _TokenBucket:
    __slots__ = ("_capacity", "_tokens", "_lock", "_last")

    def __init__(self, capacity: float) -> None:
        self._capacity = max(1.0, capacity)
        self._tokens = self._capacity
        self._lock = threading.Lock()
        self._last = time.monotonic()

    def try_acquire(self, rate: float) -> float:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last) * rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            return (1.0 - self._tokens) / max(rate, 1e-9)


_token_bucket = _TokenBucket(capacity=64.0)

# ── Cooldown ────────────────────────────────────────────────
_cooldown_until = 0.0
_cooldown_lock = threading.Lock()

# ── Anti-bot backoff ────────────────────────────────────────
_anti_bot_count = 0
_anti_bot_lock = threading.Lock()


def _set_cooldown(seconds: float) -> None:
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)


def _cooldown_reset() -> None:
    """Clear any active cooldown (used at run/city start and in tests)."""
    global _cooldown_until
    with _cooldown_lock:
        _cooldown_until = 0.0


def _anti_bot_detected() -> None:
    global _anti_bot_count, _cooldown_until
    with _anti_bot_lock:
        _anti_bot_count += 1
        backoff = min(10 * (2 ** (_anti_bot_count - 1)), 120)
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + backoff)
    state.syslog(f"anti_bot_backoff: count={_anti_bot_count}, cooldown={backoff}s")
    state.warn(f"⚠ Anti-bot обнаружен (#{_anti_bot_count}). Автопауза {backoff}с...")


def _anti_bot_reset() -> None:
    global _anti_bot_count
    with _anti_bot_lock:
        _anti_bot_count = 0


def _cooldown_remaining() -> float:
    with _cooldown_lock:
        return max(0.0, _cooldown_until - time.monotonic())


# ── Wait for token ──────────────────────────────────────────
def _wait_for_token() -> bool:
    """Block until the token bucket grants a slot AND cooldown elapsed.
    Returns True if interrupted by stop/skip."""
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
    """Wait *seconds*, checking stop/skip every second.
    Returns True if interrupted."""
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
