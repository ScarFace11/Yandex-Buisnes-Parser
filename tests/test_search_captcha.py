# -*- coding: utf-8 -*-
"""Проверка «Вы не робот?» вместо выдачи: быстро, честно и без ложных советов.

Живой случай 17.10.2026: прогон «кафе» по Москве отработал 3 минуты 2 секунды
и нашёл 0 записей, а в лог ушло «Не удалось открыть выдачу Яндекс.Карт.
Проверьте, что браузер запускается … и есть доступ в интернет». Браузер был
жив, интернет тоже — Яндекс отвечал SmartCaptcha. Здесь фиксируется контракт:

* проверка узнаётся на самой странице, а не после двух таймаутов по 90 секунд;
* на странице-проверке не включается запасной разбор вёрстки (там нечего
  разбирать, а ожидание стоило бы ещё полторы минуты);
* пользователь получает объяснение про проверку, а не про браузер и интернет;
* Chrome запускается с TLS 1.2: на TLS 1.3 край Яндекса отдаёт ту же капчу
  на нормальный запрос (замер: 15 КБ капчи против 1.6 МБ выдачи).

Run with: python -m pytest tests/test_search_captcha.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from yandex_maps_parser import browser_search, search, state


@pytest.fixture(autouse=True)
def _fresh_block(monkeypatch):
    """Каждый тест начинает без «капчи в прошлом прогоне» и не оставляет её."""
    browser_search.reset_blocked()
    monkeypatch.setattr(state, "SEARCH_BLOCKED", "", raising=False)
    yield
    browser_search.reset_blocked()
    monkeypatch.setattr(state, "SEARCH_BLOCKED", "", raising=False)


def _blocked_json():
    return '{"blocked": "captcha"}'


class TestDetection:
    def test_wait_expression_also_stops_on_the_check_page(self):
        """Ожидание готовности не должно выжидать 90 с на странице-проверке."""
        expr = browser_search._state_wait_expr()
        assert "showcaptcha" in expr
        assert "вы не робот" in expr.lower()

    def test_harvest_reports_the_check_instead_of_zero_cards(self, monkeypatch):
        monkeypatch.setattr(browser_search.cdp_client, "eval_in_page",
                            lambda *a, **kw: _blocked_json())
        cards = browser_search.harvest_cards("кафе", "Калуга", 54.51, 36.26, 50)
        assert cards == []
        assert browser_search.blocked_reason() == "captcha"

    def test_no_layout_fallback_on_a_check_page(self, monkeypatch):
        """Вёрстку на странице-проверке не разбираем: это ещё 90 секунд зря."""
        calls = []

        def fake_eval(url, expression, wait_expr="", timeout_s=45.0, biz_id=""):
            calls.append(wait_expr)
            return _blocked_json()

        monkeypatch.setattr(browser_search.cdp_client, "eval_in_page", fake_eval)
        assert browser_search.harvest_cards("кафе", "Калуга", 54.51, 36.26, 50) == []
        assert len(calls) == 1, "второго открытия страницы быть не должно"

    def test_dom_fallback_also_recognises_the_check(self, monkeypatch):
        """Если выдача не пришла и разбор вёрстки включился — он тоже сдаётся."""
        monkeypatch.setattr(browser_search, "_harvest_from_state", lambda *a: [])
        monkeypatch.setattr(browser_search.cdp_client, "eval_in_page",
                            lambda *a, **kw: _blocked_json())
        assert browser_search.harvest_cards("кафе", "Калуга", 54.51, 36.26, 50) == []
        assert browser_search.blocked_reason() == "captcha"


class TestMessage:
    def test_hint_names_the_check_not_the_browser(self):
        browser_search._set_blocked("captcha")
        hint = search.search_failure_hint()
        assert "Вы не робот" in hint
        assert "Диагностика" not in hint and "интернет тут ни при чём" in hint

    def test_plain_failure_keeps_the_old_hint(self):
        hint = search.search_failure_hint()
        assert "Диагностика" in hint and "интернет" in hint

    def test_warning_is_printed_once_per_run(self, monkeypatch):
        """Каждый город и запрос не должен повторять ту же строку в «Важных»."""
        warned = []
        monkeypatch.setattr(state, "warn", lambda m: warned.append(m))
        monkeypatch.setattr(state, "tech", lambda m: None)
        monkeypatch.setattr(search, "_harvest_cache", {})

        def blocked(*a, **kw):
            browser_search._set_blocked("captcha")
            return []

        monkeypatch.setattr(search, "harvest_cards", blocked)
        for query in ("кафе", "бар", "столовая"):
            assert search.search_page(query, "Калуга", 54.51, 36.26, 0) == ([], None)
        assert len(warned) == 1, warned
        assert "Вы не робот" in warned[0]
        assert state.SEARCH_BLOCKED == "captcha"

    def test_reset_clears_the_reason(self):
        browser_search._set_blocked("captcha")
        browser_search.reset_blocked()
        assert browser_search.blocked_reason() == ""


class TestLaunchFlags:
    def test_tls13_is_capped_for_the_edge_that_serves_the_check(self, monkeypatch):
        """TLS 1.3 в Chrome 155 — и Яндекс отвечает капчей; 1.2 — выдачей."""
        from yandex_maps_parser import cdp_client

        seen = {}

        class FakeProc:
            def poll(self):
                return None

            def terminate(self):
                pass

        def fake_popen(cmd, **kw):
            seen["cmd"] = list(cmd)
            return FakeProc()

        monkeypatch.setattr(cdp_client, "_find_chrome", lambda: "chrome.exe")
        monkeypatch.setattr(cdp_client, "browser_info", lambda: {
            "path": "chrome.exe", "name": "Google Chrome",
            "chromium": True, "unsupported": []})
        monkeypatch.setattr(cdp_client.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(cdp_client, "_cdp_get",
                            lambda port, path: {"Browser": "Chrome/155.0.8059.80"})
        monkeypatch.setattr(cdp_client, "_create_tab", lambda: "ws://127.0.0.1/x")
        try:
            assert cdp_client.init_browser(pool_size=1) is True
        finally:
            cdp_client.close_browser()

        assert "--ssl-version-max=tls1.2" in seen["cmd"], seen["cmd"]
