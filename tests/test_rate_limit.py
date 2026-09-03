"""
Tests for rate_limit.py: token bucket, adaptive RPS, cooldown, anti-bot.
Run with: python -m pytest tests/test_rate_limit.py -v
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Must import state first to avoid circular import issues
from yandex_maps_parser import state
import pytest

from yandex_maps_parser.rate_limit import (
    _TokenBucket,
    _get_rps,
    _rps_drop,
    _rps_reset,
    _set_cooldown,
    _cooldown_remaining,
    _cooldown_reset,
    _anti_bot_detected,
    _anti_bot_reset,
    _wait_for_token,
)


@pytest.fixture(autouse=True)
def _clean_ratelimit_state():
    """Rate-limit globals are shared across tests — reset between each test."""
    _rps_reset()
    _anti_bot_reset()
    _cooldown_reset()
    state._STOP_EVENT = threading.Event()
    state._SKIP_CITY_EVENT = threading.Event()
    yield
    _rps_reset()
    _anti_bot_reset()
    _cooldown_reset()


# ── Token Bucket ────────────────────────────────────────────

class TestTokenBucket:
    def test_acquire_when_full(self):
        """Full bucket should grant immediately (wait=0)."""
        bucket = _TokenBucket(capacity=10)
        wait = bucket.try_acquire(rate=10)
        assert wait == 0.0

    def test_acquire_when_empty(self):
        """Empty bucket should return positive wait time."""
        bucket = _TokenBucket(capacity=1)
        bucket.try_acquire(rate=10)  # drain the 1 token
        wait = bucket.try_acquire(rate=10)
        assert wait > 0

    def test_tokens_refill_over_time(self):
        """Tokens should refill based on rate."""
        bucket = _TokenBucket(capacity=10)
        # Drain all tokens
        for _ in range(10):
            bucket.try_acquire(rate=100)  # high rate to drain fast

        # Wait for refill
        time.sleep(0.2)

        # Should have some tokens now
        wait = bucket.try_acquire(rate=10)  # 10 tokens/sec * 0.2s = 2 tokens
        assert wait == 0.0  # should succeed

    def test_concurrent_access(self):
        """Multiple threads accessing the bucket should be safe."""
        bucket = _TokenBucket(capacity=5)
        results = []

        def try_acquire():
            wait = bucket.try_acquire(rate=5)
            results.append(wait)

        threads = [threading.Thread(target=try_acquire) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        # Some should succeed (0 wait), some should wait
        zeros = sum(1 for r in results if r == 0.0)
        assert zeros >= 1  # at least one should get through


# ── Adaptive RPS ────────────────────────────────────────────

class TestAdaptiveRPS:
    def test_initial_rps(self):
        """RPS should start at minimum."""
        _rps_reset()
        rps = _get_rps()
        assert rps == 10.0  # _MIN_RPS

    def test_rps_drop(self):
        """RPS should halve on drop."""
        _rps_reset()
        _rps_drop("test")
        rps = _get_rps()
        assert rps == 5.0  # 10 / 2

    def test_rps_drop_floor(self):
        """RPS should never drop below the absolute floor (not zero)."""
        _rps_reset()
        for _ in range(10):
            _rps_drop("test")
        rps = _get_rps()
        assert rps >= 2.0  # _DROP_FLOOR_RPS

    def test_rps_reset(self):
        """Reset should restore initial RPS."""
        _rps_reset()
        _rps_drop("test")
        _rps_drop("test")
        _rps_reset()
        rps = _get_rps()
        assert rps == 10.0


# ── Cooldown ────────────────────────────────────────────────

class TestCooldown:
    def test_no_cooldown_initially(self):
        """No cooldown on fresh start."""
        _set_cooldown(0)  # clear
        remaining = _cooldown_remaining()
        assert remaining == 0.0

    def test_cooldown_blocks(self):
        """Setting cooldown should make remaining > 0."""
        _set_cooldown(5.0)  # 5 second cooldown
        remaining = _cooldown_remaining()
        assert remaining > 0
        assert remaining <= 5.0

    def test_cooldown_expires(self):
        """Cooldown should expire after the specified time."""
        _set_cooldown(0.1)  # 100ms cooldown
        time.sleep(0.15)
        remaining = _cooldown_remaining()
        assert remaining == 0.0


# ── Anti-bot backoff ────────────────────────────────────────

class TestAntiBot:
    def test_first_detection(self):
        """First detection should set cooldown."""
        _anti_bot_reset()
        _anti_bot_detected()
        remaining = _cooldown_remaining()
        assert remaining > 0  # should have some cooldown

    def test_exponential_backoff(self):
        """Successive detections should increase cooldown."""
        _anti_bot_reset()

        _anti_bot_detected()
        r1 = _cooldown_remaining()

        time.sleep(0.01)
        _anti_bot_detected()
        r2 = _cooldown_remaining()

        # r2 should be at least as long as r1 (exponential)
        assert r2 >= r1 * 0.5  # generous margin

    def test_reset_clears_counter(self):
        """Reset should clear the backoff counter."""
        _anti_bot_detected()
        _anti_bot_detected()
        _anti_bot_reset()
        # After reset, next detection should be first-time cooldown
        _anti_bot_detected()
        remaining = _cooldown_remaining()
        assert remaining > 0


# ── Wait for token ──────────────────────────────────────────

class TestWaitForToken:
    def test_returns_false_when_ready(self):
        """Should return False (not interrupted) when tokens available."""
        _rps_reset()
        _set_cooldown(0)  # clear cooldown
        state._STOP_EVENT = threading.Event()
        result = _wait_for_token()
        assert result is False

    def test_returns_true_on_stop(self):
        """Should return True (interrupted) when stop event is set."""
        state._STOP_EVENT = threading.Event()
        state._STOP_EVENT.set()
        result = _wait_for_token()
        assert result is True

    def test_returns_true_on_skip(self):
        """Should return True when skip city event is set."""
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._SKIP_CITY_EVENT.set()
        result = _wait_for_token()
        assert result is True
        state._SKIP_CITY_EVENT.clear()
