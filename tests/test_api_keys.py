# -*- coding: utf-8 -*-
"""Сохранение API-ключей: hot-reload без перезапуска процесса.

У пути /save-api-keys раньше не было ни одного теста, и синхронизация
была асимметричной: TWOGIS_API_KEY пробрасывался в
yandex_maps_parser.state, а YANDEX_API_KEY — нет. state держит снапшот
config (импорт при старте), поэтому геокодер (state.YANDEX_API_KEY в
geocoding.py/search.py) до старта нового запуска читал бы старый ключ.
Здесь фиксируется, что после сохранения ключа обновляются сразу config,
state, os.environ и файл .env.
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
    env_file.write_text('YANDEX_API_KEY = "old_yandex"\n', encoding="utf-8")
    monkeypatch.setattr(paths, "env_path", lambda: env_file)

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client(), env_file


def _isolate(monkeypatch, value=""):
    """Обнулить ключи в config/state/os.environ на время теста."""
    import config
    from yandex_maps_parser import state as pstate
    monkeypatch.setattr(config, "YANDEX_API_KEY", value)
    monkeypatch.setattr(pstate, "YANDEX_API_KEY", value)
    if value:
        monkeypatch.setenv("YANDEX_API_KEY", value)
    else:
        monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    return config, pstate


class TestSaveApiKeysHotReload:
    def test_yandex_key_lands_everywhere(self, client, monkeypatch):
        c, env_file = client
        config, pstate = _isolate(monkeypatch, "old_yandex")

        r = c.post("/save-api-keys", json={"yandex_api_key": "new_yandex"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["ok"] is True

        # Все четыре потребителя видят новый ключ сразу, без рестарта.
        assert config.YANDEX_API_KEY == "new_yandex"
        assert pstate.YANDEX_API_KEY == "new_yandex"   # ← регрессия этого бага
        assert os.environ.get("YANDEX_API_KEY") == "new_yandex"
        assert 'YANDEX_API_KEY = "new_yandex"' in env_file.read_text(encoding="utf-8")

    def test_status_endpoint_reports_true_after_save(self, client, monkeypatch):
        c, _ = client
        _isolate(monkeypatch, "")          # ключа нет → бейдж «0/3»
        assert c.get("/api-keys/status").get_json()["yandex"] is False

        c.post("/save-api-keys", json={"yandex_api_key": "new_yandex"})
        assert c.get("/api-keys/status").get_json()["yandex"] is True

    def test_key_with_forbidden_chars_rejected_and_not_written(self, client,
                                                               monkeypatch):
        c, env_file = client
        _isolate(monkeypatch, "old_yandex")
        before = env_file.read_text(encoding="utf-8")

        r = c.post("/save-api-keys", json={"yandex_api_key": 'bad#key"'})
        assert r.status_code == 400
        assert "#" in r.get_json()["error"] or "символы" in r.get_json()["error"]

        # Файл и config не тронуты.
        assert env_file.read_text(encoding="utf-8") == before
        assert config_yandex() == "old_yandex"


def config_yandex() -> str:
    import config
    return config.YANDEX_API_KEY
