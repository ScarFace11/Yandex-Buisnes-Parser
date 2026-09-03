"""
Tests for stop/skip responsiveness: polled acquires must notice a stop
within ~0.5s instead of blocking the full timeout, and CDP navigation
must abort mid-load when stop/skip is requested.

Run with: python -m pytest tests/test_stop_responsiveness.py -v
"""
import os
import queue
import sys
import threading
import time
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import state
from yandex_maps_parser.enrichment import _poll_semaphore_acquire, _stop_requested


class _StopHarness:
    """Set state._STOP_EVENT / _SKIP_CITY_EVENT and restore after."""

    def __init__(self, mode: str = "stop"):
        self.mode = mode

    def __enter__(self):
        self._old_stop = state._STOP_EVENT
        self._old_skip = state._SKIP_CITY_EVENT
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        if self.mode == "stop":
            state._STOP_EVENT.set()
        elif self.mode == "skip":
            state._SKIP_CITY_EVENT.set()
        return self

    def __exit__(self, *a):
        state._STOP_EVENT = self._old_stop
        state._SKIP_CITY_EVENT = self._old_skip
        return False


class TestPollSemaphoreAcquire:
    def test_acquires_when_free(self):
        """A free semaphore is acquired immediately (no stop interference)."""
        sem = threading.Semaphore(1)
        with _StopHarness(mode="none") as _h:
            pass  # events set but not triggered below

        # No stop requested → plain acquire path
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        try:
            t0 = time.monotonic()
            ok = _poll_semaphore_acquire(sem, 5.0)
            assert ok is True
            assert time.monotonic() - t0 < 1.0
            # held by us
            assert sem.acquire(blocking=False) is False
            sem.release()
        finally:
            sem.release()

    def test_stop_interrupts_immediately(self):
        """Stop must abort the wait within ~0.5s, not after the 5s timeout."""
        sem = threading.Semaphore(0)  # never available → would block 5s
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._STOP_EVENT.set()
        try:
            t0 = time.monotonic()
            ok = _poll_semaphore_acquire(sem, 5.0)
            elapsed = time.monotonic() - t0
            assert ok is False
            assert elapsed < 2.0, f"stop not noticed promptly ({elapsed:.1f}s)"
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None

    def test_skip_interrupts_immediately(self):
        """Skip-city must abort the wait as fast as stop."""
        sem = threading.Semaphore(0)
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._SKIP_CITY_EVENT.set()
        try:
            t0 = time.monotonic()
            ok = _poll_semaphore_acquire(sem, 5.0)
            elapsed = time.monotonic() - t0
            assert ok is False
            assert elapsed < 2.0
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None

    def test_stop_requested_helper(self):
        with _StopHarness(mode="stop"):
            assert _stop_requested() is True
        with _StopHarness(mode="skip"):
            assert _stop_requested() is True


class TestPollAcquireCdp:
    """cdp_client._poll_acquire / _poll_queue_get stop-awareness."""

    def _import(self):
        from yandex_maps_parser import cdp_client
        return cdp_client

    def test_queue_get_notices_stop(self):
        cdp = self._import()
        q = queue.Queue()
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._STOP_EVENT.set()
        try:
            t0 = time.monotonic()
            with patch.object(cdp, "_stop_requested", return_value=True):
                try:
                    cdp._poll_queue_get(q, 5.0)
                    raised = False
                except queue.Empty:
                    raised = True
            assert raised
            assert time.monotonic() - t0 < 2.0
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None

    def test_queue_get_returns_item_when_available(self):
        cdp = self._import()
        q = queue.Queue()
        q.put("tab1")
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        try:
            item = cdp._poll_queue_get(q, 5.0)
            assert item == "tab1"
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None

    def test_semaphore_acquire_notices_stop(self):
        cdp = self._import()
        sem = threading.Semaphore(0)
        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._SKIP_CITY_EVENT.set()
        try:
            t0 = time.monotonic()
            with patch.object(cdp, "_stop_requested", return_value=True):
                ok = cdp._poll_acquire(sem, 5.0)
            assert ok is False
            assert time.monotonic() - t0 < 2.0
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None


# ── CDP navigation abort on stop ─────────────────────────────

if "websocket" not in sys.modules:
    _fake_ws_mod = types.ModuleType("websocket")

    class WebSocketTimeoutException(Exception):
        pass

    _fake_ws_mod.WebSocketTimeoutException = WebSocketTimeoutException
    _fake_ws_mod.create_connection = None  # patched per-test
    sys.modules["websocket"] = _fake_ws_mod


class _EvalTimeoutWs:
    """WebSocket that never answers — every eval burns its own socket timeout."""

    def __init__(self):
        self._closed = False

    def settimeout(self, t):
        pass

    def send(self, data):
        pass

    def recv(self):
        import websocket
        raise websocket.WebSocketTimeoutException("simulated timeout")

    def close(self):
        self._closed = True


class TestCdpNavigateAbortsOnStop:
    def test_stop_aborts_page_load_fast(self):
        """CDP page load must abort quickly on stop, not burn its 40s deadline.

        Without the stop check in the poll loop this test would take ~40s;
        with it, _cdp_navigate_and_get_html returns None almost immediately.
        """
        from yandex_maps_parser import cdp_client

        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._STOP_EVENT.set()
        ws_mod = sys.modules["websocket"]
        fake = _EvalTimeoutWs()
        try:
            with patch.object(ws_mod, "create_connection", return_value=fake):
                t0 = time.monotonic()
                result = cdp_client._cdp_navigate_and_get_html(
                    "ws://fake", "https://yandex.ru/maps/org/12345", timeout_s=40
                )
                elapsed = time.monotonic() - t0
            assert result is None
            assert elapsed < 5.0, f"stop did not abort CDP load ({elapsed:.1f}s)"
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None

    def test_skip_aborts_page_load_fast(self):
        from yandex_maps_parser import cdp_client

        state._STOP_EVENT = threading.Event()
        state._SKIP_CITY_EVENT = threading.Event()
        state._SKIP_CITY_EVENT.set()
        ws_mod = sys.modules["websocket"]
        fake = _EvalTimeoutWs()
        try:
            with patch.object(ws_mod, "create_connection", return_value=fake):
                t0 = time.monotonic()
                result = cdp_client._cdp_navigate_and_get_html(
                    "ws://fake", "https://yandex.ru/maps/org/12345", timeout_s=40
                )
                elapsed = time.monotonic() - t0
            assert result is None
            assert elapsed < 5.0
        finally:
            state._STOP_EVENT = None
            state._SKIP_CITY_EVENT = None
