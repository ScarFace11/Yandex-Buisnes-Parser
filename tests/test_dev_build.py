"""Сборка разработчика: версия с суффиксом «-dev».

Проверяем контракт dev-сборки:
  * суффикс версии распознаётся (config.is_dev_build);
  * dev-сборка слушает свой порт (5010), публичная — 5000, YP_PORT главнее;
  * авто-обновление в dev-режиме отключено целиком (и в сеть не ходим);
  * в шапке появляется метка DEV, а в публичной сборке её нет;
  * файлы dev-пайплайна (build-dev.bat, workflow) на месте.
"""
import os
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def client():
    from routes import api as api_mod
    from routes import update as update_mod
    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    app.register_blueprint(update_mod.bp)
    return app.test_client()


@pytest.fixture
def dev(monkeypatch):
    """Установка — сборка разработчика."""
    import config
    monkeypatch.setattr(config, "APP_VERSION", "2.3.0-dev")
    return config


@pytest.fixture
def release(monkeypatch):
    """Установка — публичный релиз."""
    import config
    monkeypatch.setattr(config, "APP_VERSION", "2.3.0")
    return config


class _FakeResp:
    status_code = 200

    def json(self):
        return {"version": "9.9.9", "changelog": "future", "download_url": "https://x/y.zip"}


def _no_network(*_a, **_k):
    raise AssertionError("dev-сборка не должна ходить на GitHub")


# ── Признак сборки ────────────────────────────────────────────

class TestVersionFlag:
    @pytest.mark.parametrize("version,expected", [
        ("2.3.0-dev", True),
        ("2.3.0-dev.1", True),
        ("3.0.0-beta", True),
        ("2.3.0-DEV", True),
        ("2.3.0", False),
        ("2.2.1.1", False),
    ])
    def test_suffix_marks_a_dev_build(self, monkeypatch, version, expected):
        import config
        monkeypatch.setattr(config, "APP_VERSION", version)
        assert config.is_dev_build() is expected


# ── Порт ──────────────────────────────────────────────────────

class TestAppPort:
    def test_dev_build_listens_on_its_own_port(self, monkeypatch, dev):
        monkeypatch.delenv("YP_PORT", raising=False)
        assert dev.app_port() == dev.DEV_PORT == 5010
        # На macOS у dev-сборки тот же порт: dev проверяется раньше платформы.
        monkeypatch.setattr(dev.sys, "platform", "darwin")
        assert dev.app_port() == 5010

    def test_release_listens_on_the_public_port(self, monkeypatch, release):
        monkeypatch.delenv("YP_PORT", raising=False)
        monkeypatch.setattr(release.sys, "platform", "win32")
        assert release.app_port() == 5000

    def test_macos_release_avoids_the_airplay_port(self, monkeypatch, release):
        """На macOS 5000 занят системным AirPlay Receiver."""
        monkeypatch.delenv("YP_PORT", raising=False)
        monkeypatch.setattr(release.sys, "platform", "darwin")
        assert release.app_port() == release.MAC_PORT == 5050

    def test_env_variable_wins_and_garbage_is_ignored(self, monkeypatch, release):
        monkeypatch.setattr(release.sys, "platform", "win32")
        monkeypatch.setenv("YP_PORT", "5080")
        assert release.app_port() == 5080
        monkeypatch.setenv("YP_PORT", "не-порт")
        assert release.app_port() == 5000
        monkeypatch.setenv("YP_PORT", "70000")     # вне диапазона портов
        assert release.app_port() == 5000
        monkeypatch.setattr(release.sys, "platform", "darwin")
        assert release.app_port() == 5050           # fallback тоже platform-aware


# ── Авто-обновление выключено ─────────────────────────────────

class TestUpdateDisabledInDev:
    def test_status_reports_dev_without_touching_the_network(self, client, dev, monkeypatch):
        from routes import update as update_mod
        monkeypatch.setattr(update_mod, "_remote_meta", _no_network)
        d = client.get("/update/status").get_json()
        assert d["dev"] is True
        assert d["newer"] is False
        assert d["latest"] is None
        assert d["current"] == "2.3.0-dev"

    def test_download_and_apply_are_refused(self, client, dev):
        assert client.post("/update/download").status_code == 400
        r = client.post("/update/apply")
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
        assert "DEV" in r.get_json()["error"]

    def test_check_version_short_circuits(self, client, dev, monkeypatch):
        import requests
        monkeypatch.setattr(requests, "get", _no_network)
        d = client.get("/check-version").get_json()
        assert d["dev"] is True
        assert d["newer"] is False

    def test_release_build_still_checks_github(self, client, release, monkeypatch):
        import requests
        monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResp())
        d = client.get("/check-version").get_json()
        assert "dev" not in d
        assert d["newer"] is True
        assert d["remote"] == "9.9.9"

    def test_release_status_from_source_is_not_dev(self, client, release):
        d = client.get("/update/status").get_json()
        assert d["dev"] is False
        assert d["frozen"] is False


# ── Метка DEV в шапке ─────────────────────────────────────────

def _render_index(**ctx):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")))
    env.globals["url_for"] = lambda *a, **k: "/static/x"
    return env.get_template("index.html").render(**ctx)


class TestDevBadge:
    def test_badge_only_in_a_dev_build(self):
        dev_html = _render_index(APP_VERSION="2.3.0-dev", DEV_BUILD=True)
        assert 'id="app-dev"' in dev_html
        assert "v2.3.0-dev" in dev_html

        rel_html = _render_index(APP_VERSION="2.3.0", DEV_BUILD=False)
        assert 'id="app-dev"' not in rel_html
        assert "v2.3.0" in rel_html


# ── Dev-пайплайн на месте ─────────────────────────────────────

class TestDevPipeline:
    def test_local_dev_build_script(self):
        bat = (ROOT / "build-dev.bat").read_text(encoding="utf-8")
        assert "YP_DEV=1" in bat
        assert "dist-dev" in bat
        assert "parser.spec" in bat

    def test_spec_switches_the_exe_name(self):
        spec = (ROOT / "parser.spec").read_text(encoding="utf-8")
        assert 'os.environ.get("YP_DEV"' in spec
        assert '"YandexBusinessParserDev" if DEV_BUILD else "YandexBusinessParser"' in spec

    def test_ci_builds_dev_from_the_dev_branch(self):
        wf = (ROOT / ".github" / "workflows" / "build-dev.yml").read_text(encoding="utf-8")
        assert "- dev" in wf                      # триггер на ветку dev
        assert "YP_DEV: '1'" in wf
        assert "--distpath dist-dev" in wf
        assert "upload-artifact" in wf
        assert "gh-release" not in wf             # релиз не создаём

    def test_release_workflow_guards_against_dev_versions(self):
        wf = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        assert "config.is_dev_build()" in wf

    def test_dev_dist_is_not_committed(self):
        assert "dist-dev/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
