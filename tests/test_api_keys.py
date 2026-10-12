# -*- coding: utf-8 -*-
"""Сохранение токена ВКонтакте: hot-reload без перезапуска процесса.

Единственный ключ приложения — VK_TOKEN (проверка активности сообществ на
этапе 2). Ключей платных API Карт больше нет: поиск, координаты города и
карточки читает браузер.

Здесь фиксируется, что после сохранения токен обновляется сразу в config,
в state, в os.environ и в файле .env — без перезапуска приложения.
"""
import os

import pytest
from flask import Flask


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask client + изолированный .env рядом с зачищенными значениями."""
    import paths
    from routes import api as api_mod

    env_file = tmp_path / ".env"
    env_file.write_text('VK_TOKEN = "old_token"\n', encoding="utf-8")
    monkeypatch.setattr(paths, "env_path", lambda: env_file)
    # Ключи приложения читаются через config/paths — берём изолированный файл.
    import config
    monkeypatch.setattr(config, "env_path", lambda: env_file, raising=False)

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client(), env_file


def _isolate(monkeypatch, value=""):
    """Обнулить токен в config/state/os.environ на время теста."""
    import config
    from yandex_maps_parser import state as pstate
    from yandex_maps_parser import vk_stats
    monkeypatch.setattr(config, "VK_TOKEN", value)
    monkeypatch.setattr(pstate, "VK_TOKEN", value, raising=False)
    monkeypatch.setattr(vk_stats, "_token", lambda: value, raising=False)
    if value:
        monkeypatch.setenv("VK_TOKEN", value)
    else:
        monkeypatch.delenv("VK_TOKEN", raising=False)
    return config, pstate


class TestSaveApiKeysHotReload:
    def test_vk_token_lands_everywhere(self, client, monkeypatch):
        c, env_file = client
        config, _pstate = _isolate(monkeypatch, "old_token")

        r = c.post("/save-api-keys", json={"vk_token": "new_token"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["ok"] is True

        # Токен виден всем потребителям сразу, без рестарта.
        assert config.VK_TOKEN == "new_token"
        assert os.environ.get("VK_TOKEN") == "new_token"
        assert 'VK_TOKEN = "new_token"' in env_file.read_text(encoding="utf-8")

    def test_status_endpoint_reports_true_after_save(self, client, monkeypatch):
        c, _ = client
        _isolate(monkeypatch, "")           # токена нет → бейдж «не задан»
        assert c.get("/api-keys/status").get_json()["vk"] is False

        c.post("/save-api-keys", json={"vk_token": "new_token"})
        assert c.get("/api-keys/status").get_json()["vk"] is True

    def test_status_endpoint_never_returns_the_token(self, client, monkeypatch):
        c, _ = client
        _isolate(monkeypatch, "SECRET-TOKEN-123")
        body = c.get("/api-keys/status").get_data(as_text=True)
        assert "SECRET-TOKEN-123" not in body
        assert body.strip().endswith("}")

    def test_key_with_forbidden_chars_rejected_and_not_written(self, client,
                                                               monkeypatch):
        c, env_file = client
        _isolate(monkeypatch, "old_token")
        before = env_file.read_text(encoding="utf-8")

        r = c.post("/save-api-keys", json={"vk_token": 'bad#key"'})
        assert r.status_code == 400
        assert "#" in r.get_json()["error"] or "символы" in r.get_json()["error"]

        # Файл и config не тронуты.
        assert env_file.read_text(encoding="utf-8") == before
        assert config_vk() == "old_token"

    def test_empty_value_changes_nothing(self, client, monkeypatch):
        c, env_file = client
        _isolate(monkeypatch, "old_token")
        before = env_file.read_text(encoding="utf-8")
        r = c.post("/save-api-keys", json={"vk_token": "   "})
        assert r.status_code == 400
        assert env_file.read_text(encoding="utf-8") == before

    def test_no_paid_map_keys_left_in_the_route(self, client, monkeypatch):
        """Ключи платных API Карт не должны приниматься вовсе."""
        c, _ = client
        _isolate(monkeypatch, "")
        r = c.post("/save-api-keys", json={"yandex_api_key": "x", "twogis_api_key": "y"})
        assert r.status_code == 400, "неизвестные ключи не сохраняются молча"
        status = c.get("/api-keys/status").get_json()
        assert set(status) == {"vk"}


def config_vk() -> str:
    import config
    return config.VK_TOKEN
