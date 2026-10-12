"""
Tests for the «Способы парсинга» diagnostics group and /engines/status.

Единственный способ загрузки страниц — настоящий Chrome по CDP, поэтому:

- /engines/status: мгновенная доступность (найден ли Chrome) без сети.
- /terms/status + /terms/accept: пользовательское соглашение при первом входе.
- probe_engines(deep=False): одна строка — найден ли браузер.
- probe_engines(deep=True): пробная загрузка карточки и выдачи;
  сломанный браузер не должен уронить весь отчёт.
- GROUPS/run_checks wiring.

Run with: python -m pytest tests/test_engines_probe.py -v
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from flask import Flask

from routes import diagnostics as diag


@pytest.fixture()
def client():
    app = Flask(__name__)
    app.register_blueprint(diag.bp)
    return app.test_client()


class TestEnginesStatusEndpoint:
    """GET /engines/status — бейдж доступности в форме."""

    def test_reports_the_browser(self, client, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome",
                            lambda: r"C:\fake\chrome.exe", raising=False)
        resp = client.get("/engines/status")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["chrome"] is True
        assert data["chrome_path"] == r"C:\fake\chrome.exe"
        assert "frozen" in data
        # Playwright в приложении больше нет — и в ответе его быть не должно.
        assert "playwright" not in data

    def test_terms_gate_roundtrip(self, monkeypatch):
        """Соглашение: до принятия accepted=False, после POST — True
        (сохранение в settings.json переживает смену браузера)."""
        from routes import api as api_mod
        import paths as _paths
        app = Flask(__name__)
        app.register_blueprint(api_mod.bp)
        client = app.test_client()

        saved = {}
        orig_load, orig_save = _paths.load_settings, _paths.save_settings
        _paths.load_settings = lambda: {}
        _paths.save_settings = lambda v: saved.update(v)
        try:
            data = client.get("/terms/status").get_json()
            assert data["accepted"] is False
            assert data["version"]

            resp = client.post("/terms/accept")
            assert resp.status_code == 200
            assert resp.get_json()["accepted"] is True
            assert saved["terms"]["accepted"] is True

            # После принятия — accepted=True.
            _paths.load_settings = lambda: dict(saved)
            assert client.get("/terms/status").get_json()["accepted"] is True
        finally:
            _paths.load_settings = orig_load
            _paths.save_settings = orig_save

    def test_terms_version_change_requires_reaccept(self):
        """Согласие старой версии не считается принятым."""
        from routes import api as api_mod
        import paths as _paths
        app = Flask(__name__)
        app.register_blueprint(api_mod.bp)
        client = app.test_client()

        orig_load = _paths.load_settings
        _paths.load_settings = lambda: {"terms": {"accepted": True, "version": "0.9"}}
        try:
            assert client.get("/terms/status").get_json()["accepted"] is False
        finally:
            _paths.load_settings = orig_load

    def test_missing_browser(self, client, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome", lambda: None, raising=False)
        data = client.get("/engines/status").get_json()
        assert data["ok"] is True
        assert data["chrome"] is False
        assert data["chrome_path"] == ""

    def test_engine_modules_failing_still_answer(self, client, monkeypatch):
        """Сбой модуля не должен ронять эндпоинт — бейдж просто не будет
        показан (JS его прячет при ошибке), но ответ обязан быть 200."""
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")),
                            raising=False)
        data = client.get("/engines/status").get_json()
        assert data.get("ok") is True


def resp_ok(data):
    return data.get("ok") is True


class TestProbeEnginesShallow:
    """deep=False — только наличие браузера, без сетевых проб."""

    def test_single_browser_row(self, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome", lambda: r"C:\fake\chrome.exe",
                            raising=False)
        rows = diag.probe_engines(deep=False)
        assert {r["id"] for r in rows} == {"engine_cdp"}

    def test_missing_browser_is_an_error_with_advice(self, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome", lambda: None, raising=False)
        row = diag.probe_engines(deep=False)[0]
        assert row["status"] == "error"
        assert "Chrome" in row["hint"]

    def test_all_rows_have_the_report_shape(self, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome", lambda: r"C:\fake\chrome.exe",
                            raising=False)
        for r in diag.probe_engines(deep=False):
            assert {"id", "group", "status", "title", "detail"} <= set(r)
            assert r["group"] == "engines"
            assert r["status"] in ("ok", "warn", "error")


class TestProbeEnginesDeep:
    """deep=True — пробная загрузка карточки и страницы выдачи."""

    @staticmethod
    def _fake_cdp(available=True, page="x" * 2000, cards="12", running=True):
        """running — браузер уже был поднят до пробы (идёт прогон)."""
        return types.SimpleNamespace(
            _find_chrome=lambda: r"C:\fake\chrome.exe" if available else None,
            init_browser=lambda pool_size=8, visible=False: available,
            fetch_page=lambda url, biz_id="", timeout_ms=40000: page,
            eval_in_page=lambda url, expr, **kw: cards,
            close_browser=lambda: None,
            is_available=lambda: bool(running),
        )

    def _probe(self, monkeypatch, *, cdp, live=None):
        """probe_engines делает `from yandex_maps_parser import cdp_client` —
        то есть работает с САМИМ модулем. Патчим все атрибуты, которые он у
        него вызывает (иначе в тесте запустился бы настоящий Chrome)."""
        import yandex_maps_parser.cdp_client as cdp_mod
        # Живой сбор выдачи ходит в интернет — в тестах его не запускаем.
        monkeypatch.setattr(diag, "_live_search_rows", live or (lambda: []))
        monkeypatch.setattr(cdp_mod, "_find_chrome",
                            getattr(cdp, "_find_chrome", lambda: None),
                            raising=False)
        for attr in ("init_browser", "fetch_page", "close_browser", "eval_in_page",
                     "is_available"):
            if hasattr(cdp, attr):
                monkeypatch.setattr(cdp_mod, attr, getattr(cdp, attr),
                                    raising=False)
        return diag.probe_engines(deep=True)

    def test_working_browser(self, monkeypatch):
        rows = self._probe(monkeypatch, cdp=self._fake_cdp())
        row = rows[0]
        assert row["id"] == "engine_cdp"
        assert row["status"] == "ok"
        assert "карточек в выдаче: 12" in row["detail"]

    def test_empty_search_results_is_a_warning_not_a_crash(self, monkeypatch):
        rows = self._probe(monkeypatch, cdp=self._fake_cdp(cards="0"))
        row = rows[0]
        assert row["status"] == "warn"
        assert row["hint"], "нужен совет, что проверить"

    def test_missing_chrome_is_an_error(self, monkeypatch):
        rows = self._probe(monkeypatch, cdp=self._fake_cdp(available=False))
        row = rows[0]
        assert row["status"] == "error"
        assert "не найден" in row["title"].lower()

    def test_active_tab_is_reported(self, monkeypatch):
        """Вкладка активна: её состояние видно в отчёте (проверка фокуса)."""
        cdp = self._fake_cdp()
        cdp.eval_in_page = lambda url, expr, **kw: (
            '{"cards": 12, "visibility": "visible", "focus": true}')
        rows = self._probe(monkeypatch, cdp=cdp)
        tab = next(r for r in rows if r["id"] == "tab_active")
        assert tab["status"] == "ok"
        assert "visibilityState=visible" in tab["detail"]
        # Проба выдачи по-прежнему первой строкой отчёта.
        assert rows[0]["id"] == "engine_cdp"

    def test_background_tab_is_a_warning_with_advice(self, monkeypatch):
        """Скрытая вкладка — именно тот случай, когда список не догружается:
        Яндекс отдаёт 5 карточек вместо 25, и в отчёте должен быть совет."""
        cdp = self._fake_cdp()
        cdp.eval_in_page = lambda url, expr, **kw: (
            '{"cards": 5, "visibility": "hidden", "focus": false}')
        rows = self._probe(monkeypatch, cdp=cdp)
        tab = next(r for r in rows if r["id"] == "tab_active")
        assert tab["status"] == "warn"
        assert "hidden" in tab["detail"]
        assert tab["hint"], "нужен совет, что это значит"

    def test_no_tab_row_when_state_cannot_be_read(self, monkeypatch):
        """Без машинного замера строку о вкладке не выдумываем."""
        rows = self._probe(monkeypatch, cdp=self._fake_cdp(cards="12"))
        assert all(r["id"] != "tab_active" for r in rows)

    def test_live_search_row_reports_found_organizations(self, monkeypatch):
        """Живой сбор выдачи: главная проверка — «поиск находит организации»."""
        import yandex_maps_parser.browser_search as bs_mod
        monkeypatch.setattr(bs_mod, "harvest_cards",
                            lambda *a, **kw: [{"name": "Monkey Grinder"}, {"name": "Душа"}])
        rows = self._probe(monkeypatch, cdp=self._fake_cdp(),
                           live=diag._live_search_rows)
        row = next(r for r in rows if r["id"] == "search_live")
        assert row["status"] == "ok"
        assert "2 организаций" in row["detail"]
        assert "Monkey Grinder" in row["detail"]

    def test_live_search_row_warns_on_empty_results(self, monkeypatch):
        import yandex_maps_parser.browser_search as bs_mod
        monkeypatch.setattr(bs_mod, "harvest_cards", lambda *a, **kw: [])
        rows = self._probe(monkeypatch, cdp=self._fake_cdp(),
                           live=diag._live_search_rows)
        row = next(r for r in rows if r["id"] == "search_live")
        assert row["status"] == "warn"
        assert row["hint"]

    def test_own_browser_is_closed_but_a_running_one_is_not(self, monkeypatch):
        """Проба не должна гасить браузер идущего прогона."""
        closed = []
        cdp = self._fake_cdp(running=False)
        cdp.close_browser = lambda: closed.append(True)
        self._probe(monkeypatch, cdp=cdp)
        assert closed, "свой браузер после пробы нужно закрыть"

        closed.clear()
        cdp_running = self._fake_cdp(running=True)
        cdp_running.close_browser = lambda: closed.append(True)
        self._probe(monkeypatch, cdp=cdp_running)
        assert not closed, "браузер идущего прогона закрывать нельзя"

    def test_broken_browser_does_not_kill_the_report(self, monkeypatch):
        cdp = self._fake_cdp()
        cdp.fetch_page = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("probe exploded"))
        rows = self._probe(monkeypatch, cdp=cdp)
        assert rows and rows[0]["id"] == "engine_cdp"
        assert rows[0]["status"] in ("warn", "error")


class TestGroupsWiring:
    def test_engines_in_groups(self):
        assert "engines" in diag.GROUPS

    def test_run_checks_engines_group_runs_probe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(diag, "probe_engines",
                            lambda deep=False: calls.append(deep) or [])
        diag.run_checks(["engines"])
        assert calls == [False], "run_checks зовёт быстрый вариант, не сетевой"

    def test_deep_flag_reaches_the_probe(self, monkeypatch):
        """Живая проба браузера (открывает Chrome) — только по явному флагу."""
        calls = []
        monkeypatch.setattr(diag, "probe_engines",
                            lambda deep=False: calls.append(deep) or [])
        diag.run_checks(["engines"], deep=True)
        assert calls == [True]

    def test_endpoint_forwards_the_deep_flag(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(diag, "probe_engines",
                            lambda deep=False: calls.append(deep) or [])
        resp = client.post("/diagnostics/run", json={"groups": ["engines"], "deep": True})
        assert resp.status_code == 200
        assert calls == [True]

    def test_endpoint_defaults_to_the_fast_probe(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(diag, "probe_engines",
                            lambda deep=False: calls.append(deep) or [])
        client.post("/diagnostics/run", json={"groups": ["engines"]})
        assert calls == [False]
