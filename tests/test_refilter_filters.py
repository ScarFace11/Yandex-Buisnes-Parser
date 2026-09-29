"""/process-filters: какие фильтры этапа 2 реально доходят до обработки.

Регресс: клиент отправлял лишь часть настроек, поэтому «Применить фильтры
заново» давал не тот срез, что тот же поиск с теми же настройками — терялись
проверка активности ВК и порог оценки лида. Тест фиксирует полный набор:
любое новое поле фильтрации должно появиться и в роуте, и в app.js.
"""
import os

import pytest
from flask import Flask


@pytest.fixture()
def app_client(monkeypatch):
    from routes import api as api_mod
    from yandex_maps_parser import processing

    captured = {}

    def fake_process_all(raw_files, filters, formats, log_fn=None, cleanup_mode="keep"):
        captured["raw_files"] = list(raw_files)
        captured["filters"] = dict(filters)
        captured["formats"] = list(formats)
        captured["cleanup_mode"] = cleanup_mode
        return {"count": 7, "empty": False, "files": ["/tmp/out.xlsx"]}

    monkeypatch.setattr(processing, "list_raw_files", lambda: ["raw_a.xlsx", "raw_b.xlsx"])
    monkeypatch.setattr(processing, "process_all", fake_process_all)

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client(), captured


def test_every_stage_two_filter_reaches_processing(app_client):
    client, captured = app_client

    resp = client.post("/process-filters", json={
        "formats": ["excel", "json"],
        "collapse_chains": True,
        "chain_key": "phone",
        "parse_mode": "without_website",
        "social_mode": "with_socials",
        "required_socials": ["vk", "telegram"],
        "raw_mode": "archive",
        # Фильтры, которые раньше терялись на клиенте:
        "vk_check": True,
        "vk_mode": "active",
        "vk_max_post_days": 30,
        "vk_min_followers": 250,
        "min_lead_score": 50,
        "sort_by_score": True,
        # Чёрный список слов («🚫 Исключить по словам"),
        "blacklist_words": ["Франшиза", "vip"],
        # «🎯 Тип компании» — одиночки и новые,
        "only_single_branch": True,
        "only_new_months": 12,
    })
    data = resp.get_json()

    assert data["ok"] is True and data["count"] == 7
    f = captured["filters"]
    assert f["vk_check"] is True
    assert f["vk_mode"] == "active"
    assert f["vk_max_post_days"] == 30
    assert f["vk_min_followers"] == 250
    assert f["min_lead_score"] == 50
    assert f["sort_by_score"] is True
    assert f["blacklist_words"] == ["Франшиза", "vip"]
    # «🎯 Тип компании»: период нормализует обработка, а не роут.
    assert f["only_single_branch"] is True
    assert f["only_new_months"] == 12
    assert f["parse_mode"] == "without_website"
    assert f["required_socials"] == ["vk", "telegram"]
    assert captured["cleanup_mode"] == "archive"
    assert captured["formats"] == ["excel", "json"]
    # Работаем по уже собранным файлам из raw/ — без повторного парсинга.
    assert [os.path.basename(p) for p in captured["raw_files"]] == ["raw_a.xlsx", "raw_b.xlsx"]


def test_defaults_are_safe_when_the_body_is_thin(app_client):
    client, captured = app_client

    client.post("/process-filters", json={})

    f = captured["filters"]
    assert f["vk_check"] is False
    assert f["vk_mode"] == "all"
    assert f["min_lead_score"] == 0
    assert f["blacklist_words"] == []
    assert f["only_single_branch"] is False
    assert f["only_new_months"] is None
    assert f["parse_mode"] == "all"
    assert captured["cleanup_mode"] == "keep"


def test_answer_carries_the_full_output_path(app_client):
    """Смена папки результатов: журнал показывает реальный путь, не «output/»."""
    client, _ = app_client

    d = client.post("/process-filters", json={}).get_json()

    assert d["out_dir"], "ответ обязан нести папку результатов"
    assert not d["out_dir"].endswith(("/", "\\"))


def test_runner_stage_two_gets_the_same_filters():
    """Обычный запуск собирает свой словарь фильтров — он тоже должен нести
    «тип компании», иначе галочки работали бы только по кнопке."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "yandex_maps_parser", "runner.py"), encoding="utf-8") as f:
        src = f.read()
    for key in ("only_single_branch", "only_new_months", "blacklist_words",
                "min_lead_score", "sort_by_score", "vk_check"):
        assert f'"{key}"' in src, f"{key} не доезжает до этапа 2 при обычном запуске"


def test_no_raw_files_is_a_readable_error(app_client, monkeypatch):
    from yandex_maps_parser import processing

    client, _ = app_client
    monkeypatch.setattr(processing, "list_raw_files", lambda: [])

    resp = client.post("/process-filters", json={})

    assert resp.status_code == 400
    assert "сырых данных" in resp.get_json()["error"].lower()
