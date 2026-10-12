# -*- coding: utf-8 -*-
"""Минимально допустимая версия: приложение ниже порога не работает.

Порог (`min_version`) публикуется вместе с релизом в static/version.json и
нужен, когда старая сборка перестаёт быть совместимой с форматом данных или
маршрутами API. Тесты держат обе стороны контракта:

  * блокировка действительно наступает — иначе смысла в пороге нет;
  * блокировка НЕ наступает там, где она была бы вредна: DEV-сборка, порог
    не задан, GitHub недоступен (пропавшая сеть не должна «кирпить»
    установленное приложение).

Плюс разметочный контракт: окно блокировки есть в шаблоне, скрыто по
умолчанию и подключено к своему обработчику — иначе сервер может сколько
угодно отвечать `blocked: true`, а пользователь этого не увидит.
"""
import json
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
APP_CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
APP_INIT_JS = (ROOT / "static" / "js" / "11-app-init.js").read_text(encoding="utf-8")


def _client(tmp_path, monkeypatch, *, current, meta=None, raise_meta=False,
            dev=False, cached=None, cached_age=0.0):
    """Flask-клиент только с blueprints/update и подменённым окружением."""
    from routes import update as upd
    import config

    monkeypatch.setattr(upd, "_work_dir", lambda: tmp_path)
    monkeypatch.setattr(upd, "_is_dev", lambda: bool(dev))
    monkeypatch.setattr(upd, "_is_frozen", lambda: False)
    monkeypatch.setattr(upd, "_self_update_supported", lambda: False)
    monkeypatch.setattr(config, "APP_VERSION", current)

    def _meta():
        if raise_meta:
            raise RuntimeError("network down")
        return meta or {}

    monkeypatch.setattr(upd, "_remote_meta", _meta)

    if cached is not None:
        (tmp_path / upd.STATE_FILE).write_text(
            json.dumps({"min_version": {"payload": cached, "at": _now() - cached_age}}),
            encoding="utf-8")

    app = Flask(__name__)
    app.register_blueprint(upd.bp)
    return app.test_client(), upd


def _now():
    import time
    return time.time()


class TestBlocking:
    def test_below_minimum_is_blocked(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0",
                            meta={"min_version": "2.2.0", "version": "2.4.0"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is True
        assert d["current"] == "2.1.0" and d["minimum"] == "2.2.0"
        assert "2.4.0" in d["notice"]           # куда обновляться — сказано
        assert d["download_url"].startswith("https://github.com/")

    def test_equal_or_newer_is_not_blocked(self, tmp_path, monkeypatch):
        for current in ("2.2.0", "2.2.1", "2.10.0"):
            client, _ = _client(tmp_path, monkeypatch, current=current,
                                meta={"min_version": "2.2.0", "version": "2.4.0"})
            assert client.get("/version/minimum").get_json()["blocked"] is False

    def test_missing_threshold_never_blocks(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="1.0.0",
                            meta={"version": "2.4.0"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is False and d["minimum"] == ""

    def test_dev_build_is_never_blocked(self, tmp_path, monkeypatch):
        """DEV-ветка не блокируется даже при высоком пороге: иначе она
        перестаёт запускаться и её нельзя починить."""
        client, _ = _client(tmp_path, monkeypatch, current="0.0.1", dev=True,
                            meta={"min_version": "99.0.0", "version": "2.4.0"})
        d = client.get("/version/minimum").get_json()
        assert d["dev"] is True and d["blocked"] is False


class TestOffline:
    def test_offline_without_cache_keeps_the_app_running(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0", raise_meta=True)
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is False
        assert "GitHub" in d["notice"]          # честно сказано, что не проверили

    def test_offline_with_fresh_cache_still_enforces(self, tmp_path, monkeypatch):
        """Порог уже известен — сеть для его применения не нужна."""
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0", raise_meta=True,
                            cached={"min_version": "2.2.0", "version": "2.4.0"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is True and d["minimum"] == "2.2.0"

    def test_stale_cache_is_refreshed(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0",
                            meta={"min_version": "2.0.0", "version": "2.4.0"},
                            cached={"min_version": "99.0.0", "version": "9.9.9"},
                            cached_age=10 ** 6)
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is False and d["minimum"] == "2.0.0"


class TestVersionOrdering:
    def test_numeric_not_lexicographic(self, tmp_path, monkeypatch):
        _, upd = _client(tmp_path, monkeypatch, current="2.3.9",
                         meta={"min_version": "2.3.10"})
        assert upd._versions_below("2.3.9", "2.3.10") is True
        assert upd._versions_below("2.3.10", "2.3.9") is False

    def test_missing_tail_is_zero(self, tmp_path, monkeypatch):
        _, upd = _client(tmp_path, monkeypatch, current="2.3", meta={})
        assert upd._versions_below("2.3", "2.3.0") is False
        assert upd._versions_below("2.3", "2.3.1") is True


class TestNoStaleUi:
    """Исправление обязано долетать до вкладки пользователя.

    Без явных заголовков браузер кешировал HTML/CSS эвристически, и после
    перезапуска показывал старую вёрстку: пользователь видел прежний экран
    и решал, что ничего не исправлено.
    """

    def test_html_and_assets_are_never_served_stale(self):
        import app as app_mod
        client = app_mod.create_app().test_client()
        html = client.get("/")
        assert html.status_code == 200
        assert html.headers["Cache-Control"] == "no-store"
        css = client.get("/static/css/style.css")
        assert css.status_code == 200
        assert "no-cache" in css.headers["Cache-Control"]

    def test_interface_never_waits_for_a_hard_reload(self):
        css = APP_CSS
        assert "[hidden]{display:none!important}" in css, (
            "скрытые оверлеи должны скрываться без хард-релоада")


class TestUiContract:
    def test_gate_exists_and_starts_hidden(self):
        assert 'id="version-gate" hidden' in TEMPLATE
        assert 'id="version-gate-text"' in TEMPLATE
        assert "openReleasesPage()" in TEMPLATE

    def test_gate_is_rendered_over_the_app(self):
        assert "@bp.route(\"/version/minimum\")" in (
            ROOT / "routes" / "update.py").read_text(encoding="utf-8")

    def test_init_wires_the_gate(self):
        assert "initVersionGate()" in APP_INIT_JS
        assert "fetch('/version/minimum')" in APP_INIT_JS
        assert "getElementById('version-gate')" in APP_INIT_JS
