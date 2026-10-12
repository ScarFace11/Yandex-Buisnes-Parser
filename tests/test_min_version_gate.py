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
import re
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
APP_CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
APP_INIT_JS = (ROOT / "static" / "js" / "11-app-init.js").read_text(encoding="utf-8")


def _client(tmp_path, monkeypatch, *, current, meta=None, raise_meta=False,
            dev=False, cached=None, cached_age=0.0, local=False):
    """Flask-клиент только с blueprints/update и подменённым окружением.

    `local=False` по умолчанию неслучайно: тесты идут из исходников, а запуск
    из исходников — это как раз локальный режим, в котором порог не применяется.
    Здесь мы проверяем поведение УСТАНОВЛЕННОЙ сборки, поэтому обход выключен.
    """
    from routes import update as upd
    import config

    monkeypatch.setattr(upd, "_work_dir", lambda: tmp_path)
    monkeypatch.setattr(upd, "_is_dev", lambda: bool(dev))
    monkeypatch.setattr(upd, "_is_local_build", lambda: bool(local))
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


class TestLocalBuildBypass:
    """Своя сборка не подчиняется порогу — иначе автор не запустит старую версию."""

    def test_local_build_is_not_blocked(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.0.0", local=True,
                            meta={"min_version": "2.3.4", "version": "2.3.4"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is False
        assert d["bypass"] is True

    def test_installed_build_has_no_bypass(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.0.0",
                            meta={"min_version": "2.3.4", "version": "2.3.4"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is True and d["bypass"] is False

    def test_source_run_counts_as_local(self, monkeypatch):
        """`python app.py` — это не установленный релиз."""
        import config
        import paths
        monkeypatch.setattr(config, "APP_VERSION", "1.0.0")
        monkeypatch.delenv(config.SKIP_MIN_VERSION_ENV, raising=False)
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        assert config.skips_min_version() is True

    def test_frozen_copy_without_marker_obeys_the_threshold(self, monkeypatch, tmp_path):
        import config
        import paths
        monkeypatch.setattr(config, "APP_VERSION", "1.0.0")
        monkeypatch.delenv(config.SKIP_MIN_VERSION_ENV, raising=False)
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        marker = tmp_path / paths.LOCAL_BUILD_MARKER
        monkeypatch.setattr(paths, "local_build_marker", lambda: marker)
        assert config.skips_min_version() is False

    def test_marker_file_turns_the_threshold_off(self, monkeypatch, tmp_path):
        """build.bat / build-mac.sh / build-manual.yml ставят эту метку."""
        import config
        import paths
        monkeypatch.setattr(config, "APP_VERSION", "1.0.0")
        monkeypatch.delenv(config.SKIP_MIN_VERSION_ENV, raising=False)
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        marker = tmp_path / paths.LOCAL_BUILD_MARKER
        marker.write_text("", encoding="utf-8")
        monkeypatch.setattr(paths, "local_build_marker", lambda: marker)
        assert config.skips_min_version() is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
    def test_env_variable_turns_the_threshold_off(self, monkeypatch, value):
        import config
        import paths
        monkeypatch.setattr(config, "APP_VERSION", "1.0.0")
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setenv(config.SKIP_MIN_VERSION_ENV, value)
        assert config.skips_min_version() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_env_variable_off_keeps_the_threshold(self, monkeypatch, value, tmp_path):
        import config
        import paths
        monkeypatch.setattr(config, "APP_VERSION", "1.0.0")
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "local_build_marker",
                            lambda: tmp_path / paths.LOCAL_BUILD_MARKER)
        monkeypatch.setenv(config.SKIP_MIN_VERSION_ENV, value)
        assert config.skips_min_version() is False

    def test_release_builds_never_carry_the_marker(self):
        """Скачанная сборка обязана соблюдать порог — иначе ограничение фикция."""
        for name in ("build-exe.yml", "build-macos.yml"):
            text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            assert ".local-build" in text, f"{name}: релизная сборка должна УДАЛЯТЬ метку"
            assert "touch" not in text and "New-Item -ItemType File" not in text, \
                f"{name}: релизная сборка не ставит метку локальной сборки"

    def test_manual_builds_carry_the_marker(self):
        text = (ROOT / ".github" / "workflows" / "build-manual.yml").read_text(encoding="utf-8")
        assert text.count(".local-build") >= 2, "Windows и macOS сборки для проверки"
        for script in ("build.bat", "build-mac.sh"):
            body = (ROOT / script).read_text(encoding="utf-8")
            assert ".local-build" in body, script


class TestRunRefusal:
    """Порог держится и на сервере: окно можно закрыть, отказ — нет."""

    def _run(self, monkeypatch, blocked, payload=None):
        from routes import parser as parser_mod
        from routes import update as upd
        from flask import Flask
        calls = []

        monkeypatch.setattr(upd, "minimum_state", lambda: {
            "blocked": blocked, "current": "2.0.0", "minimum": "2.3.4",
            "notice": "Эта версия больше не поддерживается: обновитесь до v2.3.4",
            "download_url": "https://github.com/x/y/releases/latest"})
        monkeypatch.setattr(parser_mod.run_manager, "new_run",
                            lambda: calls.append("new_run") or {"id": "r1"})
        monkeypatch.setattr(parser_mod.run_manager, "start_process",
                            lambda entry: calls.append("start_process"))
        monkeypatch.setattr(parser_mod.run_manager, "active_run_id", lambda: None)

        app = Flask(__name__)
        app.register_blueprint(parser_mod.bp)
        client = app.test_client()
        res = client.post("/run", json=payload or {"queries": ["кафе"],
                                                    "cities": ["Москва"]})
        return res, calls

    def test_blocked_version_cannot_start_a_search(self, monkeypatch):
        res, calls = self._run(monkeypatch, blocked=True)
        assert res.status_code == 409
        data = res.get_json()
        assert data["blocked"] is True and "2.3.4" in data["error"]
        assert "download_url" in data
        assert calls == [], "поиск не должен даже запускаться"

    def test_allowed_version_starts_normally(self, monkeypatch):
        res, calls = self._run(monkeypatch, blocked=False)
        assert res.status_code == 200
        assert res.get_json()["ok"] is True
        assert calls == ["new_run", "start_process"]

    def test_a_broken_check_does_not_block_work(self, monkeypatch):
        """Падение самой проверки — не повод запретить поиск пользователю."""
        from routes import parser as parser_mod
        from routes import update as upd
        from flask import Flask
        calls = []

        def boom():
            raise RuntimeError("нет сети")

        monkeypatch.setattr(upd, "minimum_state", boom)
        monkeypatch.setattr(parser_mod.run_manager, "new_run",
                            lambda: calls.append("new_run") or {"id": "r1"})
        monkeypatch.setattr(parser_mod.run_manager, "start_process",
                            lambda entry: calls.append("start_process"))
        monkeypatch.setattr(parser_mod.run_manager, "active_run_id", lambda: None)
        app = Flask(__name__)
        app.register_blueprint(parser_mod.bp)
        res = app.test_client().post("/run", json={"queries": ["кафе"],
                                                   "cities": ["Москва"]})
        assert res.status_code == 200 and calls


class TestNoticeTarget:
    """Нельзя отправлять за версией, которая тоже не запустится."""

    def test_notice_points_at_the_minimum_when_latest_is_older(self, tmp_path, monkeypatch):
        # На main объявлена 2.3.3 (свежий релиз ещё черновик), порог — 2.3.4.
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0",
                            meta={"min_version": "2.3.4", "version": "2.3.3"})
        d = client.get("/version/minimum").get_json()
        assert d["blocked"] is True
        assert d["target"] == "2.3.4"
        assert "2.3.4" in d["notice"] and "2.3.3" not in d["notice"]

    def test_notice_points_at_the_latest_when_it_is_usable(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, current="2.1.0",
                            meta={"min_version": "2.3.4", "version": "2.5.0"})
        d = client.get("/version/minimum").get_json()
        assert d["target"] == "2.5.0" and "2.5.0" in d["notice"]


class TestPublishedThreshold:
    """Порог в репозитории: с 2.3.4 без согласия работать нельзя."""

    def test_min_version_is_never_below_the_agreement_version(self):
        data = json.loads((ROOT / "static" / "version.json").read_text(encoding="utf-8-sig"))
        minimum = str(data.get("min_version") or "")
        assert minimum, "в version.json не задан min_version"
        assert not _below(minimum, "2.3.4"), (
            "min_version ниже 2.3.4: сборки без пользовательского соглашения "
            "снова смогут работать")

    def test_min_version_is_a_plain_version(self):
        data = json.loads((ROOT / "static" / "version.json").read_text(encoding="utf-8-sig"))
        assert re.fullmatch(r"\d+(\.\d+)+", str(data.get("min_version") or ""))


def _below(a: str, b: str) -> bool:
    ta = tuple(int(x) for x in str(a).split(".") if x.isdigit())
    tb = tuple(int(x) for x in str(b).split(".") if x.isdigit())
    ta += (0,) * (len(tb) - len(ta))
    tb += (0,) * (len(ta) - len(tb))
    return ta < tb


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
