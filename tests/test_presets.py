# -*- coding: utf-8 -*-
"""Пресеты: серверная копия и перевод в параметры прогона.

Пресеты собираются в браузере, но консольный запуск (`app.py --run`) читает
их из settings.json. Ошибка здесь тихая: прогон пойдёт, просто не с теми
городами или форматами, что сохранены в интерфейсе. Поэтому проверяем:

1. чистку: битый или раздутый пресет не ломает чтение настроек;
2. перевод: строка «кафе, кофейня» и настройки формы превращаются в те же
   параметры, что отправляет интерфейс;
3. эндпоинт /presets: чтение, замена и отказ на мусор.

Запуск: python -m pytest tests/test_presets.py -q
"""
import json
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import presets_store
from routes import api as api_routes


@pytest.fixture()
def store(monkeypatch):
    """Подменяет settings.json в памяти: тесты не трогают реальные настройки."""
    data = {}

    class _Paths:
        @staticmethod
        def load_settings():
            return dict(data)

        @staticmethod
        def save_settings(values):
            data.update(values or {})

    monkeypatch.setitem(sys.modules, "paths", _Paths)
    return data


class TestCleaning:
    def test_trims_and_dedupes(self):
        got = presets_store.clean_presets([
            {"name": "  Уфа   стоматология ", "settings": {"queries": "стоматология"}},
            {"name": "уфа стоматология", "settings": {"queries": "другое"}},
        ])
        assert [p["name"] for p in got] == ["Уфа стоматология"]

    def test_drops_junk_without_crashing(self):
        got = presets_store.clean_presets([
            None, "строка", {"name": "", "settings": {}},
            {"name": "x", "settings": "не словарь"},
            {"name": "ok", "settings": {"queries": "кафе"}},
        ])
        assert [p["name"] for p in got] == ["ok"]

    def test_caps_the_list(self):
        raw = [{"name": f"p{i}", "settings": {"queries": "q"}} for i in range(30)]
        assert len(presets_store.clean_presets(raw)) == presets_store.MAX_PRESETS

    def test_keeps_only_simple_values(self):
        got = presets_store.clean_presets([{
            "name": "p",
            "settings": {
                "queries": "кафе",
                "cities": ["Уфа", "Казань"],
                "pages": 2,
                "grid": True,
                "nested": {"a": 1},
                "huge": ["x"] * 500,
            },
        }])[0]["settings"]
        assert got["cities"] == ["Уфа", "Казань"]
        assert got["pages"] == 2 and got["grid"] is True
        assert "nested" not in got, "вложенные словари в пресете не нужны"
        assert len(got["huge"]) == presets_store.MAX_LIST

    def test_long_strings_are_cut_not_rejected(self):
        got = presets_store.clean_presets([{
            "name": "p", "settings": {"queries": "я" * 2000}}])[0]
        assert len(got["settings"]["queries"]) == presets_store.MAX_STR


class TestStore:
    def test_save_then_load(self, store):
        presets_store.save_presets([{"name": "Уфа", "settings": {"queries": "кафе"}}])
        assert [p["name"] for p in presets_store.load_presets()] == ["Уфа"]

    def test_find_preset_is_case_and_space_insensitive(self, store):
        presets_store.save_presets([{"name": "Уфа Стоматология", "settings": {"queries": "x"}}])
        assert presets_store.find_preset("  уфа   стоматология ") is not None
        assert presets_store.find_preset("нет такого") is None

    def test_load_preset_file_with_settings(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({"name": "Из файла", "settings": {"queries": "кафе"}}),
                        encoding="utf-8")
        got = presets_store.load_preset_source(str(path))
        assert got["name"] == "Из файла" and got["settings"]["queries"] == "кафе"

    def test_load_preset_file_with_flat_settings(self, tmp_path):
        path = tmp_path / "flat.json"
        path.write_text(json.dumps({"queries": "бар", "cities": ["Сочи"]}), encoding="utf-8")
        got = presets_store.load_preset_source(str(path))
        assert got["settings"]["cities"] == ["Сочи"]

    def test_missing_preset_explains_what_is_saved(self, store):
        with pytest.raises(KeyError) as exc:
            presets_store.load_preset_source("нет такого")
        assert "не найден" in str(exc.value)
        assert "Сохранённых пресетов нет" in str(exc.value)


class TestParams:
    def test_queries_from_multiline_and_commas(self):
        params = presets_store.preset_to_params({"queries": "кафе, кофейня\nбар"})
        assert params["queries"] == ["кафе", "кофейня", "бар"]

    def test_cities_and_formats(self):
        params = presets_store.preset_to_params({
            "queries": "кафе", "cities": ["Уфа"], "excel": True, "json": False, "csv": True,
        })
        assert params["cities"] == ["Уфа"]
        assert (params["output_excel"], params["output_json"], params["output_csv"]) == (True, False, True)

    def test_formats_flag_wins_over_preset(self):
        params = presets_store.preset_to_params(
            {"queries": "кафе", "excel": True}, {"formats": ["json"]})
        assert params["output_excel"] is False and params["output_json"] is True

    def test_numeric_overrides_win(self):
        params = presets_store.preset_to_params(
            {"queries": "кафе", "pages": "1", "workers": 20},
            {"pages": 3, "workers": 5, "max_candidates": 50})
        assert params["max_pages"] == 3
        assert params["max_workers"] == 5
        assert params["max_candidates"] == 50

    def test_defaults_are_sane(self):
        params = presets_store.preset_to_params({"queries": "кафе"})
        assert params["max_pages"] == 1
        assert params["max_workers"] == 20
        assert params["pipeline"] == "raw"
        assert params["parse_mode"] == "without_website"

    def test_filters_come_from_the_preset(self):
        params = presets_store.preset_to_params({
            "queries": "кафе", "blacklist": ["салон"], "parseMode": "all",
            "socialMode": "with_socials", "requiredSocials": ["vk"],
            "onlySingle": True, "onlyNew": True, "onlyNewPeriod": 3,
            "continueMode": True,
        })
        assert params["blacklist_words"] == ["салон"]
        assert params["parse_mode"] == "all"
        assert params["required_socials"] == ["vk"]
        assert params["only_single_branch"] is True
        assert params["only_new_months"] == 3
        assert params["continue_cities"] is True

    def test_continue_can_be_switched_off_from_the_console(self):
        params = presets_store.preset_to_params(
            {"queries": "кафе", "continueMode": True}, {"no_continue": True})
        assert params["continue_cities"] is False

    def test_disabled_new_filter_drops_the_period(self):
        params = presets_store.preset_to_params(
            {"queries": "кафе", "onlyNew": False, "onlyNewPeriod": 3})
        assert params["only_new_months"] is None


class TestApi:
    @pytest.fixture()
    def client(self, store):
        app = Flask(__name__)
        app.register_blueprint(api_routes.bp)
        return app.test_client()

    def test_get_is_empty_at_first(self, client):
        data = client.get("/presets").get_json()
        assert data == {"ok": True, "presets": [], "count": 0}

    def test_post_replaces_the_list(self, client):
        data = client.post("/presets", json={"presets": [
            {"name": "Уфа", "settings": {"queries": "кафе", "cities": ["Уфа"]}}]}).get_json()
        assert data["ok"] is True and data["count"] == 1
        got = client.get("/presets").get_json()
        assert got["presets"][0]["settings"]["cities"] == ["Уфа"]

    def test_post_without_presets_is_refused(self, client):
        resp = client.post("/presets", json={"wrong": []})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False
