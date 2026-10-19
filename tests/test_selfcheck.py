# -*- coding: utf-8 -*-
"""Самопроверка без интерфейса: `app.py --check` (selfcheck.py).

Зачем отдельные тесты. Команда запускается там, где интерфейса нет вовсе
(SSH, CI, фон), и её результат читают глазами по коду возврата. Поэтому
проверяем три свойства:

1. Отчёт человеческий: группы, строки, «что делать» и итог на месте.
2. Код возврата честный: ошибка — 1, только предупреждения — 0.
3. Сервер не поднимается и порт не занимается: иначе «проверка без запуска
   сайта» была бы неправдой.

Запуск: python -m pytest tests/test_selfcheck.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import selfcheck
from routes import diagnostics as diag


def _rows(*statuses):
    return [diag._res(f"id{i}", "files", st, f"Строка {i}", "подробность", "что делать")
            for i, st in enumerate(statuses)]


class TestReport:
    def test_report_has_groups_rows_and_hints(self):
        text = selfcheck.format_report(_rows("ok", "warn"), groups=["files"])
        assert "Файлы и папки" in text
        assert "Строка 0" in text and "подробность" in text
        assert "что делать" in text, "подсказка — половина смысла диагностики"

    def test_summary_counts_every_status(self):
        text = selfcheck.format_report(_rows("ok", "ok", "warn", "error"))
        assert "4 проверки" in text
        assert "2 в порядке" in text
        assert "1 с предупреждениями" in text
        assert "1 с ошибками" in text
        assert "сбор не пойдёт" in text

    def test_clean_report_says_ready(self):
        assert "Всё готово к работе." in selfcheck.format_report(_rows("ok"))

    def test_broken_row_does_not_crash_the_report(self):
        text = selfcheck.format_report([{}, {"status": "weird"}, None])
        assert "Самопроверка" in text

    def test_status_marks_are_distinct(self):
        text = selfcheck.format_report(_rows("ok", "warn", "error"))
        for mark in ("✔", "▲", "✖"):
            assert mark in text


class TestExitCode:
    def test_warnings_are_not_a_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(diag, "run_checks", lambda groups=None, deep=False: _rows("warn"))
        assert selfcheck.main(["--check"]) == 0
        assert "предупреждениями" in capsys.readouterr().out

    def test_error_returns_one(self, monkeypatch, capsys):
        monkeypatch.setattr(diag, "run_checks", lambda groups=None, deep=False: _rows("error"))
        assert selfcheck.main(["--check"]) == 1

    def test_unknown_group_is_refused_with_two(self, capsys):
        assert selfcheck.main(["--groups", "nonsense"]) == 2
        assert "Неизвестные группы" in capsys.readouterr().err

    def test_known_groups_are_forwarded(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(diag, "run_checks",
                            lambda groups=None, deep=False: seen.update(groups=groups, deep=deep) or _rows("ok"))
        selfcheck.main(["--check", "--groups", "files,runs", "--deep"])
        assert seen == {"groups": ["files", "runs"], "deep": True}

    def test_deep_is_off_by_default(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(diag, "run_checks",
                            lambda groups=None, deep=False: seen.update(deep=deep) or _rows("ok"))
        selfcheck.main(["--check"])
        assert seen["deep"] is False, "живая проба браузера не должна включаться сама"

    def test_json_report_is_machine_readable(self, monkeypatch, capsys):
        monkeypatch.setattr(diag, "run_checks", lambda groups=None, deep=False: _rows("ok", "error"))
        assert selfcheck.main(["--check", "--json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["counts"] == {"ok": 1, "warn": 0, "error": 1}
        assert data["results"][0]["id"] == "id0"


class TestNoServer:
    def test_check_flag_never_starts_flask(self, monkeypatch, capsys):
        """`--check` — это отчёт и выход: ни сервера, ни открытого окна."""
        import app as app_module

        monkeypatch.setattr(diag, "run_checks",
                            lambda groups=None, deep=False: _rows("ok"))
        monkeypatch.setattr(sys, "argv", ["app.py", "--check"])
        with pytest.raises(SystemExit) as stop:
            app_module._maybe_run_selfcheck()
        assert stop.value.code == 0
        out = capsys.readouterr().out
        assert "Running on" not in out
        assert "Всё готово к работе." in out

    def test_without_flag_nothing_runs(self):
        import app as app_module

        assert app_module._maybe_run_selfcheck() is None
