# -*- coding: utf-8 -*-
"""Сбор из консоли по пресету: `app.py --run` (headless.py).

Проверяем то, что нельзя увидеть глазами до запуска: какие параметры реально
уйдут в движок, что dry-run ничего не запускает, что пресет ищется и по имени,
и по файлу, и что код возврата отличает «собралось» от «не смогло».

Настоящий сбор здесь не запускается: `runner.run_web` подменяется. Это
принципиально — тест не должен ни открывать браузер, ни ходить в Яндекс.

Запуск: python -m pytest tests/test_headless.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import headless
import presets_store


@pytest.fixture()
def store(monkeypatch):
    """settings.json в памяти — реальные настройки не трогаем."""
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


@pytest.fixture()
def fake_run(monkeypatch):
    """Подменяет сам прогон: запоминает параметры, отдаёт список файлов."""
    calls = {}

    def _run(params, log_fn):
        calls["params"] = params
        calls["log"] = log_fn
        log_fn("info", "  🔍 Поиск в «Уфа»")
        log_fn("ok", "✅ Готово")
        return ["organizations_Уфа.json"]

    from yandex_maps_parser import runner
    monkeypatch.setattr(runner, "run_web", _run)
    return calls


class TestDryRun:
    def test_dry_run_shows_the_plan_and_does_not_collect(self, monkeypatch, capsys):
        from yandex_maps_parser import runner

        def _boom(*_a, **_kw):
            raise AssertionError("--dry-run не должен запускать сбор")

        monkeypatch.setattr(runner, "run_web", _boom)
        code = headless.main(["--queries", "кафе, кофейня", "--cities", "Уфа, Казань",
                              "--pages", "2", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "кафе, кофейня" in out and "Уфа, Казань" in out
        assert "Страниц на точку: 2" in out
        assert "сбор не запускался" in out

    def test_dry_run_with_preset_file(self, tmp_path, capsys):
        path = tmp_path / "preset.json"
        path.write_text(json.dumps({
            "name": "Из файла",
            "settings": {"queries": "стоматология", "cities": ["Уфа"], "excel": False,
                         "json": True, "blacklist": ["детская"]},
        }, ensure_ascii=False), encoding="utf-8")
        assert headless.main(["--preset", str(path), "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "Из файла" in out
        assert "Форматы: JSON" in out, "Excel выключен в пресете — его не должно быть в плане"
        assert "Исключить слова: детская" in out


class TestValidation:
    def test_without_queries_or_preset_is_refused(self, store, capsys):
        assert headless.main([]) == 2
        assert "Нужен пресет" in capsys.readouterr().err

    def test_unknown_preset_is_refused(self, store, capsys):
        assert headless.main(["--preset", "нет такого", "--dry-run"]) == 2
        assert "не найден" in capsys.readouterr().err

    def test_preset_without_cities_is_refused(self, store, capsys):
        presets_store.save_presets([{"name": "Без городов", "settings": {"queries": "кафе"}}])
        assert headless.main(["--preset", "Без городов", "--dry-run"]) == 2
        assert "нет городов" in capsys.readouterr().err

    def test_unknown_argument_is_refused(self, store, capsys):
        assert headless.main(["--queries", "кафе", "--нет-такого"]) == 2
        assert "Незнакомые аргументы" in capsys.readouterr().err

    def test_list_presets_is_human_readable(self, store, capsys):
        presets_store.save_presets([
            {"name": "Уфа", "settings": {"queries": "кафе\nбар", "cities": ["Уфа", "Омск"]}},
        ])
        assert headless.main(["--list-presets"]) == 0
        out = capsys.readouterr().out
        assert "• Уфа: 2 запросов, 2 городов" in out

    def test_empty_list_explains_how_to_make_one(self, store, capsys):
        assert headless.main(["--list-presets"]) == 0
        assert "Сохранённых пресетов нет" in capsys.readouterr().out


class TestRun:
    def test_preset_is_translated_and_run(self, store, fake_run, capsys):
        presets_store.save_presets([{"name": "Уфа стоматология", "settings": {
            "queries": "стоматология", "cities": ["Уфа"], "pages": "2", "workers": "10",
            "json": True, "excel": False, "blacklist": ["детская"],
        }}])
        assert headless.main(["--preset", "Уфа стоматология"]) == 0
        params = fake_run["params"]
        assert params["queries"] == ["стоматология"]
        assert params["cities"] == ["Уфа"]
        assert params["max_pages"] == 2 and params["max_workers"] == 10
        assert params["output_json"] is True and params["output_excel"] is False
        out = capsys.readouterr().out
        assert "Уфа стоматология" in out
        assert "organizations_Уфа.json" in out

    def test_console_flags_beat_the_preset(self, store, fake_run):
        presets_store.save_presets([{"name": "P", "settings": {
            "queries": "кафе", "cities": ["Уфа"], "pages": "1"}}])
        assert headless.main(["--preset", "P", "--pages", "3", "--cities", "Казань"]) == 0
        assert fake_run["params"]["max_pages"] == 3
        assert fake_run["params"]["cities"] == ["Казань"]

    def test_crash_returns_one(self, store, monkeypatch, capsys):
        from yandex_maps_parser import runner

        def _boom(*_a, **_kw):
            raise RuntimeError("браузер не запустился")

        monkeypatch.setattr(runner, "run_web", _boom)
        code = headless.main(["--queries", "кафе", "--cities", "Уфа"])
        assert code == 1
        assert "браузер не запустился" in capsys.readouterr().err


class TestLogger:
    def test_technical_lines_are_hidden(self, capsys):
        log = headless.make_logger()
        log("tech", "DEBUG http 200")
        log("progress", "quota 12")
        log("info", "Поиск в «Уфа»")
        assert capsys.readouterr().out.strip() == "Поиск в «Уфа»"

    def test_verbose_shows_everything(self, capsys):
        log = headless.make_logger(verbose=True)
        log("tech", "DEBUG http 200")
        assert "DEBUG http 200" in capsys.readouterr().out

    def test_ansi_is_stripped(self, capsys):
        log = headless.make_logger()
        log("ok", "\x1b[32mГотово\x1b[0m")
        out = capsys.readouterr().out
        assert "Готово" in out
        assert "\x1b[" not in out


class TestDescribe:
    def test_describe_lists_formats_and_mode(self):
        text = headless.describe({
            "queries": ["кафе"], "cities": ["Уфа"], "output_excel": True,
            "output_json": True, "max_pages": 1, "max_workers": 20,
            "max_candidates": 200, "parse_mode": "all", "social_mode": "all",
            "use_grid": False,
        })
        assert "Форматы: Excel, JSON" in text
        assert "все организации" in text
