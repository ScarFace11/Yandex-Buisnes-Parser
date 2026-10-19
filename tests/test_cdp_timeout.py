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

from yandex_maps_parser.cdp_client import (
    _cdp_eval,
    _cdp_navigate_and_get_html,
    _href_committed,
    _navigation_target,
    _CDP_USER_AGENT,
)

_ORG_URL = "https://yandex.ru/maps/org/4312570888"


def _html(text="OK", size=2500):
    """HTML настоящей карточки: с блоком контактов и длиной больше порога.

    Признак содержимого обязателен: без него страница организации считается
    непрочитанной (см. TestCardContent), и тесты возврата HTML должны
    выглядеть как живая карточка, а не как заглушка.
    """
    card = '<div class="business-contacts-view" itemprop="telephone">+7 999</div>'
    return f"<html>{text}{card}{'x' * size}</html>"


def _bare_html(text="Shell", size=2500):
    """HTML без признаков карточки: шапка/заглушка вместо содержимого."""
    return f"<html>{text}{'x' * size}</html>"


def _state(href, ready, length, card=None):
    """Runtime.evaluate response for the href|readyState|len[|card] poll expression."""
    value = f"{href}|{ready}|{length}"
    if card is not None:
        value += "|" + ("true" if card else "false")
    return {"id": 90001, "result": {"result": {"value": value}}}


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
        assert _focus_emulated(fake), "вкладка пула должна считаться активной"


class TestCardContent:
    """readyState=complete ≠ карточка прочитана.

    Блок контактов и встроенное состояние страницы доезжают позже (или не
    доезжают, если Яндекс отдал заглушку). Раньше признаком успеха был
    только размер документа, поэтому обгрызенный/пустой документ уходил в
    конвейер как карточка — а организация оставалась без телефона, сайта и
    соцсетей («карточка не читается, запись пропущена»).
    """

    def test_org_url_without_content_is_retried_then_none(self):
        """Документ готов, но карточки в нём нет → замер ещё раз, потом None."""
        from yandex_maps_parser import cdp_client

        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "complete", 1024),
            _eval(_bare_html("первый")),
            _eval(_bare_html("второй")),
            _eval(_bare_html("третий")),
        ])
        logged: list[str] = []
        with patch.object(ws_mod, "create_connection", return_value=fake), \
                patch.object(cdp_client.state, "syslog", logged.append):
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=5)

        assert result is None, "страница без содержимого не должна считаться карточкой"
        assert any("без содержимого карточки" in m for m in logged)

    def test_content_arriving_late_is_waited_for(self):
        """Первый замер — шапка, второй — уже настоящая карточка."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "complete", 1024),
            _eval(_bare_html("шапка")),
            _eval(_html("карточка")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            result = _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=10)

        assert result is not None and "карточка" in result

    def test_aggregator_page_needs_no_card_markers(self):
        """У страниц-агрегаторов (taplink) своих признаков карточки нет."""
        ws_mod = _load_ws_module()
        agg = "https://taplink.cc/coffee"
        fake = FakeWebSocket(responses=[
            _state(agg, "complete", 3000),
            _eval(_bare_html("Taplink")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            result = _cdp_navigate_and_get_html("ws://fake", agg, timeout_s=5)

        assert result is not None and "Taplink" in result

    def test_card_marker_detection(self):
        from yandex_maps_parser.cdp_client import (
            _is_org_card_url,
            _looks_like_org_card,
        )

        assert _is_org_card_url(_ORG_URL)
        assert _is_org_card_url("https://yandex.ru/maps/org/kafe/4312570888/")
        assert not _is_org_card_url("https://taplink.cc/coffee")
        assert not _is_org_card_url("https://yandex.ru/maps/?text=coffee")

        # Каждый признак по отдельности достаточен.
        for marker in ('class="business-contacts-view"',
                       '<h2 class="card-section-header__title">Контакты</h2>',
                       '<span itemprop="telephone">+7 999</span>',
                       'class="orgpage-header-view__header"',
                       '<script type="application/json">{}</script>',
                       '<script type="application/ld+json">{}</script>'):
            assert _looks_like_org_card("<html>" + marker + "x" * 2500 + "</html>")
        # Заглушка и короткий документ — не карточка.
        assert not _looks_like_org_card("<html></html>")
        assert not _looks_like_org_card(_bare_html("shell"))


class TestNavigationCommit:
    """Вкладка из пула действительно перешла НА ЦЕЛЬ, а не осталась прежней.

    Вкладка уже показывает предыдущую страницу с readyState=complete.
    Раньше это ловилось только по числовому id организации: для слагов и
    агрегаторов (taplink.cc/<ник>) проверки не было, и в результат попадал
    HTML ЧУЖОЙ организации — отсюда «одна и та же ссылка на ВК у десятка
    организаций» и телефон чужой фирмы.
    """

    def test_numeric_id_survives_yandex_url_rewrite(self):
        target = _navigation_target(_ORG_URL)
        assert _href_committed("https://yandex.ru/maps/org/кафе/4312570888/", target)
        assert not _href_committed("https://yandex.ru/maps/org/999999999", target)

    def test_slug_page_matches_by_exact_path(self):
        target = _navigation_target("https://taplink.cc/coffee")
        assert _href_committed("https://taplink.cc/coffee/", target)
        assert not _href_committed("https://taplink.cc/bar", target)

    def test_foreign_host_and_empty_href_are_not_committed(self):
        target = _navigation_target(_ORG_URL)
        assert not _href_committed("https://example.com/maps/org/4312570888", target)
        assert not _href_committed("", target)
        assert not _href_committed("about:blank", target)

    def test_reused_tab_never_yields_the_previous_page(self):
        """Агрегатор без числового id: прежняя страница вкладки не отдаётся."""
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state("https://taplink.cc/bar", "complete", 400000),  # чужая
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            result = _cdp_navigate_and_get_html("ws://fake",
                                                "https://taplink.cc/coffee",
                                                timeout_s=2)
        assert result is None, "возвращён HTML чужой страницы"


def _focus_emulated(fake) -> bool:
    for msg in fake._sent:
        if msg["method"] == "Emulation.setFocusEmulationEnabled":
            return msg["params"].get("enabled") is True
    return False


class TestPoolTabIsMarkedActive:
    """Вкладка из пула — фоновая: Chrome отдаёт visibilityState="hidden",
    и страница Яндекс.Карт не догружает продолжение списка.

    В живом замере это давало 5 карточек вместо 24 (список виртуализован,
    продолжение подгружается только у активной страницы). Поэтому перед
    навигацией вкладке включают эмуляцию активной страницы.
    """

    def test_eval_page_emulates_active_tab(self):
        from yandex_maps_parser.cdp_client import _cdp_eval_page

        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state("https://yandex.ru/maps/?text=x", "complete", 400000),
            _eval('{"cards": []}'),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            _cdp_eval_page("ws://fake", "https://yandex.ru/maps/?text=x",
                           "expr", "true", timeout_s=5)

        assert _focus_emulated(fake)
        methods = [m["method"] for m in fake._sent]
        # Порядок важен: вкладка должна быть активной ДО навигации.
        assert methods.index("Emulation.setFocusEmulationEnabled") \
            < methods.index("Page.navigate")


class _SilentThenAnswerWs(FakeWebSocket):
    """Молчит N циклов чтения (таймауты), затем отдаёт готовый ответ."""

    def __init__(self, silent_cycles: int, answer: str = "value", sleep: float = 0.01):
        super().__init__(responses=None)
        self._silent_left = silent_cycles
        self._answer = answer
        self._sleep = sleep
        self.recv_calls = 0

    def recv(self):
        self.recv_calls += 1
        if self._silent_left > 0:
            self._silent_left -= 1
            time.sleep(self._sleep)   # каждый таймаут занимает время, как настоящий
            import websocket
            raise websocket.WebSocketTimeoutException("silence")
        return json.dumps(_eval(self._answer))


class TestSlowPromiseIsNotDropped:
    """Замер не должен обрываться на тишине в сокете.

    Сбор выдачи Яндекс.Карт (прокрутка списка) выполняется как обещание
    в странице и считается 6–10 секунд и дольше. Обрыв замера на первом
    таймауте чтения возвращал None — поиск показывал «выдача не
    открылась», хотя ни одна карточка ещё не была прочитана.
    """

    def test_late_answer_survives_socket_silence(self):
        fake = _SilentThenAnswerWs(silent_cycles=3, answer='{"cards": 7}')
        result = _cdp_eval(fake, "someLongPromise()", time.monotonic() + 20.0,
                           await_promise=True)
        assert result == '{"cards": 7}'
        assert fake.recv_calls == 4

    def test_returns_none_only_at_deadline(self):
        fake = _SilentThenAnswerWs(silent_cycles=100)
        t0 = time.monotonic()
        result = _cdp_eval(fake, "neverResolves()", time.monotonic() + 1.0,
                           await_promise=True)
        elapsed = time.monotonic() - t0
        assert result is None
        assert elapsed < 4.0, f"deadline not honoured ({elapsed:.1f}s)"

    def test_broken_socket_gives_up_immediately(self):
        """Разрыв связи (не тишина) — ждать бессмысленно."""
        class ClosedWs(FakeWebSocket):
            def recv(self):
                raise ConnectionResetError("closed")

        t0 = time.monotonic()
        result = _cdp_eval(ClosedWs(), "x()", time.monotonic() + 30.0)
        assert result is None
        assert time.monotonic() - t0 < 2.0

    def test_stop_aborts_silent_wait(self):
        from yandex_maps_parser import cdp_client

        fake = _SilentThenAnswerWs(silent_cycles=100)
        t0 = time.monotonic()
        with patch.object(cdp_client, "_stop_requested", return_value=True):
            result = _cdp_eval(fake, "x()", time.monotonic() + 30.0)
        assert result is None
        assert time.monotonic() - t0 < 2.0


class TestReadFailureReason:
    """Причина отказа доходит до счётчика потерь (state.read_failure_*).

    Раньше все потери карточек выглядели в логе одинаково («карточка не
    открылась»), и нельзя было понять, что чинить: заглушка антибота, документ
    без содержимого карточки или навигация, которая вообще не состоялась.
    """

    def test_no_card_content_is_reported(self):
        from yandex_maps_parser import cdp_client

        cdp_client.set_failure_reason("")
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state(_ORG_URL, "complete", 1024),
            _eval(_bare_html("первый")),
            _eval(_bare_html("второй")),
            _eval(_bare_html("третий")),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            assert _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=5) is None

        assert cdp_client.take_failure_reason() == "no_content"
        # Причина читается один раз: чужой карточке она достаться не должна.
        assert cdp_client.take_failure_reason() == ""

    def test_tiny_stub_is_reported_as_antibot(self):
        from yandex_maps_parser import cdp_client

        cdp_client.set_failure_reason("")
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[_state(_ORG_URL, "complete", 158)])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            assert _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=2) is None

        assert cdp_client.take_failure_reason() == "antibot"

    def test_uncommitted_navigation_is_reported_as_no_page(self):
        from yandex_maps_parser import cdp_client

        cdp_client.set_failure_reason("")
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[
            _state("https://taplink.cc/bar", "complete", 400000),
        ])
        with patch.object(ws_mod, "create_connection", return_value=fake):
            assert _cdp_navigate_and_get_html("ws://fake",
                                              "https://taplink.cc/coffee",
                                              timeout_s=2) is None

        assert cdp_client.take_failure_reason() == "no_page"

    def test_stop_does_not_look_like_a_lost_card(self):
        """Остановка прогона — не потерянная карточка, причина пустая."""
        import threading
        from yandex_maps_parser import cdp_client

        cdp_client.set_failure_reason("")
        stop = threading.Event()
        stop.set()
        ws_mod = _load_ws_module()
        fake = FakeWebSocket(responses=[_state(_ORG_URL, "complete", 2500)])
        with patch.object(ws_mod, "create_connection", return_value=fake), \
                patch.object(cdp_client.state, "_STOP_EVENT", stop):
            assert _cdp_navigate_and_get_html("ws://fake", _ORG_URL, timeout_s=2) is None

        assert cdp_client.take_failure_reason() == ""

    def test_fetch_html_ignores_stopped_run(self):
        """Остановили прогон → fetch_html не записывает «не прочитано»."""
        import threading
        from yandex_maps_parser import cdp_client, extractors, state

        stop = threading.Event()
        stop.set()
        state.reset_read_failures()
        with patch.object(cdp_client, "fetch_page", return_value=None), \
                patch.object(state, "_STOP_EVENT", stop):
            assert extractors.fetch_html(_ORG_URL) == ""
        assert state.read_failure_summary()["total"] == 0
