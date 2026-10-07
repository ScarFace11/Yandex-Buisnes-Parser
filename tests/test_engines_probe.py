"""
Tests for the «Способы парсинга» diagnostics group and /engines/status.

- /engines/status: instant availability (chrome found? playwright importable?
  frozen build?) without any network probes.
- probe_engines(deep=False): three rows (httpx/cdp/playwright), presence-only.
- probe_engines(deep=True): probe load through each engine with fake clients;
  a broken engine must not break the whole report.
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

    def test_reports_chrome_and_playwright(self, client, monkeypatch):
        monkeypatch.setattr(diag, "_status_fingerprint",
                            None, raising=False)
        # Fake engine availability: chrome found, playwright importable.
        import yandex_maps_parser.cdp_client as cdp
        import yandex_maps_parser.browser_client as bclient
        monkeypatch.setattr(cdp, "_find_chrome",
                            lambda: r"C:\fake\chrome.exe", raising=False)

        class _FakeMod:
            pass

        monkeypatch.setattr(bclient, "_try_import_playwright",
                            lambda: _FakeMod, raising=False)
        resp = client.get("/engines/status")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["chrome"] is True
        assert data["chrome_path"] == r"C:\fake\chrome.exe"
        assert data["playwright"] is True
        assert "frozen" in data

    def test_missing_chrome_and_playwright(self, client, monkeypatch):
        import yandex_maps_parser.cdp_client as cdp
        import yandex_maps_parser.browser_client as bclient
        monkeypatch.setattr(cdp, "_find_chrome", lambda: None, raising=False)
        monkeypatch.setattr(bclient, "_try_import_playwright",
                            lambda: None, raising=False)
        data = client.get("/engines/status").get_json()
        assert data["ok"] is True
        assert data["chrome"] is False
        assert data["playwright"] is False

    def test_engine_modules_failing_still_answer(self, client, monkeypatch):
        """Сбой модулей не должен ронять эндпоинт — бейдж просто не будет
        показан (JS его прячет при ошибке), но ответ обязан быть 200."""
        import yandex_maps_parser.cdp_client as cdp
        monkeypatch.setattr(cdp, "_find_chrome",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")),
                            raising=False)
        data = client.get("/engines/status").get_json()
        assert resp_ok(data)


def resp_ok(data):
    return data.get("ok") is True


class TestProbeEnginesShallow:
    """deep=False — только наличие, без сетевых проб."""

    def test_three_rows(self):
        rows = diag.probe_engines(deep=False)
        ids = {r["id"] for r in rows}
        assert ids == {"engine_httpx", "engine_cdp", "engine_playwright"}

    def test_all_rows_have_the_report_shape(self):
        for r in diag.probe_engines(deep=False):
            assert {"id", "group", "status", "title", "detail"} <= set(r)
            assert r["group"] == "engines"
            assert r["status"] in ("ok", "warn", "error")


class TestProbeEnginesDeep:
    """deep=True — пробная загрузка через фейковых клиентов."""

    @staticmethod
    def _fake_cdp(available=True, page="x" * 2000):
        return types.SimpleNamespace(
            _find_chrome=lambda: r"C:\fake\chrome.exe" if available else None,
            init_browser=lambda pool_size=8, visible=False: available,
            fetch_page=lambda url, biz_id="", timeout_ms=40000: page,
            close_browser=lambda: None,
        )

    @staticmethod
    def _fake_pw(available=True, page="x" * 2000):
        return types.SimpleNamespace(
            _try_import_playwright=lambda: object() if available else None,
            init_browser=lambda pool_size=8: available,
            fetch_page=lambda url, biz_id="", timeout_ms=30000: page,
            close_browser=lambda: None,
        )

    @pytest.fixture()
    def patch_engines(self, monkeypatch):
        def _patch(cdp=None, bclient=None, fetch_html=None):
            import yandex_maps_parser.cdp_client as cdp_mod
            import yandex_maps_parser.browser_client as bc_mod
            import yandex_maps_parser.enrichment  # noqa: F401  (ensure importable)
            monkeypatch.setitem(sys.modules, "yandex_maps_parser.cdp_client",
                                cdp_mod if cdp is None else cdp)
            monkeypatch.setitem(sys.modules, "yandex_maps_parser.browser_client",
                                bc_mod if bclient is None else bclient)
            if fetch_html is not None:
                import yandex_maps_parser.extractors as ex
                monkeypatch.setattr(ex, "fetch_html", fetch_html, raising=False)
        return _patch

    def _probe(self, monkeypatch, *, cdp, bclient, fetch_html):
        # probe_engines делает `from yandex_maps_parser import cdp_client` —
        # то есть работает с САМИМИ модулями. Патчим все атрибуты, которые
        # он у них вызывает (иначе в тесте запустился бы настоящий Chrome).
        import yandex_maps_parser.cdp_client as cdp_mod
        import yandex_maps_parser.browser_client as bc_mod
        import yandex_maps_parser.extractors as ex
        monkeypatch.setattr(cdp_mod, "_find_chrome",
                            getattr(cdp, "_find_chrome", lambda: None),
                            raising=False)
        for attr in ("init_browser", "fetch_page", "close_browser"):
            if hasattr(cdp, attr):
                monkeypatch.setattr(cdp_mod, attr, getattr(cdp, attr),
                                    raising=False)
        monkeypatch.setattr(bc_mod, "_try_import_playwright",
                            getattr(bclient, "_try_import_playwright",
                                    lambda: object),
                            raising=False)
        for attr in ("init_browser", "fetch_page", "close_browser"):
            if hasattr(bclient, attr):
                monkeypatch.setattr(bc_mod, attr, getattr(bclient, attr),
                                    raising=False)
        monkeypatch.setattr(ex, "fetch_html", fetch_html, raising=False)
        return diag.probe_engines(deep=True)

    def test_all_engines_working(self, monkeypatch):
        rows = self._probe(
            monkeypatch,
            cdp=self._fake_cdp(),
            bclient=self._fake_pw(),
            fetch_html=lambda url, biz_id="", session=None: "y" * 3000,
        )
        by_id = {r["id"]: r for r in rows}
        assert by_id["engine_httpx"]["status"] == "ok"
        assert by_id["engine_cdp"]["status"] == "ok"
        assert by_id["engine_playwright"]["status"] == "ok"

    def test_antibot_stub_is_a_warning_not_a_crash(self, monkeypatch):
        stub = "<html>robot captcha</html>"  # анти-бот заглушка
        rows = self._probe(
            monkeypatch,
            cdp=self._fake_cdp(),
            bclient=self._fake_pw(),
            fetch_html=lambda url, biz_id="", session=None: stub,
        )
        by_id = {r["id"]: r for r in rows}
        assert by_id["engine_httpx"]["status"] == "warn"
        assert "заглуш" in by_id["engine_httpx"]["title"].lower()

    def test_missing_chrome_is_a_warning(self, monkeypatch):
        rows = self._probe(
            monkeypatch,
            cdp=self._fake_cdp(available=False),
            bclient=self._fake_pw(),
            fetch_html=lambda url, biz_id="", session=None: "y" * 3000,
        )
        by_id = {r["id"]: r for r in rows}
        assert by_id["engine_cdp"]["status"] == "warn"
        assert "не найден" in by_id["engine_cdp"]["title"].lower()

    def test_broken_engine_does_not_kill_the_report(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("probe exploded")

        rows = self._probe(
            monkeypatch,
            cdp=self._fake_cdp(),
            bclient=self._fake_pw(),
            fetch_html=_boom,
        )
        by_id = {r["id"]: r for r in rows}
        assert by_id["engine_httpx"]["status"] == "error"
        # Остальные два живы — изоляция сработала.
        assert by_id["engine_cdp"]["status"] == "ok"
        assert by_id["engine_playwright"]["status"] == "ok"


class TestGroupsWiring:
    def test_engines_in_groups(self):
        assert "engines" in diag.GROUPS

    def test_run_checks_engines_group_runs_probe(self, monkeypatch):
        calls = []
        monkeypatch.setattr(diag, "probe_engines",
                            lambda deep=False: calls.append(deep) or [])
        diag.run_checks(["engines"])
        assert calls == [False], "run_checks зовёт быстрый вариант, не сетевой"
