"""
Tests for CDP WebSocket page-fetch logic (UA override, navigation-commit
guard, deadline enforcement, empty-stub handling).

Run with: python -m pytest tests/test_cdp_timeout.py -v
"""
import json
import sys
import os
import time
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# websocket-client may not be installed in the test environment — provide a
# minimal stand-in module so these unit tests run anywhere.
if "websocket" not in sys.modules:
    _fake_ws_mod = types.ModuleType("websocket")

    class WebSocketTimeoutException(Exception):
        pass

    _fake_ws_mod.WebSocketTimeoutException = WebSocketTimeoutException
    _fake_ws_mod.create_connection = None  # patched per-test
    sys.modules["websocket"] = _fake_ws_mod

from yandex_maps_parser.cdp_client import _cdp_navigate_and_get_html, _CDP_USER_AGENT

_ORG_URL = "https://yandex.ru/maps/org/4312570888"


def _html(text="OK", size=2500):
    """HTML padded past the >800-byte meaningful-content threshold."""
    return f"<html>{text}{'x' * size}</html>"


def _state(href, ready, length):
    """Runtime.evaluate response for the href|readyState|len poll expression."""
    return {"id": 90001, "result": {"result": {"value": f"{href}|{ready}|{length}"}}}


def _eval(value):
    """Runtime.evaluate response carrying an arbitrary string value."""
    return {"id": 90001, "result": {"result": {"value": value}}}


class FakeWebSocket:
    """Fake websocket: returns queued responses, then simulates timeouts."""

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self._timeout = 10
        self._sent = []
        self._closed = False

    def settimeout(self, t):
        self._timeout = t

    def send(self, data):
        self._sent.append(json.loads(data))

    def recv(self):
        if self._responses:
            return json.dumps(self._responses.pop(0))
        import websocket
        raise websocket.WebSocketTimeoutException("simulated timeout")

    def close(self):
        self._closed = True


def _load_ws_module():
    import websocket
    return websocket


class TestCdpFetch:
    def test_returns_html_when_page_ready(self):
        """Normal case: document commits and is complete → HTML returned.
        A large-but-loading document must NOT trigger an early harvest — the
        socials block sits near the end of the server HTML."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "loading", 439168),   # big but NOT complete
            _state(_ORG_URL, "complete", 439168),  # now complete
            _eval(_html("Fast")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=5)

        assert result and _html("Fast") in result
        # 3 Runtime.evaluate calls: 2 polls + 1 harvest (no premature harvest)
        evals = [m for m in fake._sent if m["method"] == "Runtime.evaluate"]
        assert len(evals) == 3
        assert fake._closed

    def test_waits_for_navigation_commit(self):
        """Must not harvest the PREVIOUS page on a reused tab."""
        ws_mod = _load_ws_module()
        old_url = "https://yandex.ru/maps/org/999999999"  # previous business
        fake = FakeWebSocket(responses=[
            # first poll: old document still current → not committed to target
            _state(old_url, "complete", 400000),
            # navigation committed now
            _state(_ORG_URL, "loading", 500),
            _state(_ORG_URL, "complete", 439168),
            _eval(_html("Target")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=5)

        assert result and _html("Target") in result

    def test_empty_stub_page_returns_none(self):
        """Anti-bot stub (empty doc) → None so httpx fallback runs."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "complete", 158),      # stub: committed but tiny
            _eval("<html></html>"),                 # harvest returns stub
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            t0 = time.monotonic()
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=3)
            elapsed = time.monotonic() - t0

        assert result is None
        assert elapsed < 8  # must not wait out a long deadline

    def test_hard_deadline_enforced(self):
        """Total time must not far exceed timeout_s even if every eval times out."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            t0 = time.monotonic()
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=2)
            elapsed = time.monotonic() - t0

        assert elapsed < 8
        assert result is None
        assert fake._closed

    def test_websocket_connection_error_returns_none(self):
        """If the WS connection fails, return None (httpx fallback)."""
        ws_mod = _load_ws_module()
        with patch.object(ws_mod, "create_connection", side_effect=ConnectionRefusedError("refused")):
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=3)

        assert result is None

    def test_sends_enable_ua_and_navigate(self):
        """Must enable Page, override the UA and navigate before evaluating."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "complete", 439168),
            _eval(_html("ok")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=5)

        methods = [m["method"] for m in fake._sent]
        assert methods[0] == "Page.enable"
        assert methods[1] == "Network.setUserAgentOverride"
        assert "Page.navigate" in methods
        ua = fake._sent[1]["params"]["userAgent"]
        assert ua == _CDP_USER_AGENT
        assert "Headless" not in ua
        nav = next(m for m in fake._sent if m["method"] == "Page.navigate")
        assert nav["params"]["url"] == _ORG_URL
        assert any(m["method"] == "Runtime.evaluate" for m in fake._sent)
