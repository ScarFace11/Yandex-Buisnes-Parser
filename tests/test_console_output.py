# -*- coding: utf-8 -*-
"""Консольный вывод: всегда UTF-8 и никогда не роняет приложение.

Регресс, найденный на локальной сборке .exe: если stdout перенаправлен
(лог-файл, пайп, запуск из скрипта), Python берёт системную кодировку консоли —
на русской Windows это cp1251/cp866 — и предупреждение с эмодзи
(«⚠️ Файл .env не найден») падало UnicodeEncodeError прямо при импорте
config.py. Замороженная сборка не запускалась вообще: вместо интерфейса —
трейсбек и выход.

Инварианты, которые здесь держатся:

* вывод переводится в UTF-8 одним общим механизмом (``console_io``), а не
  «каждый сам за себя»;
* в консольных сообщениях нет эмодзи — консоль это среда с неизвестной
  кодировкой, а интерфейс отдаётся браузеру, где кодировка всегда UTF-8;
* любое стартовое сообщение печатается даже там, где символ непредставим.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Эмодзи и пиктограммы. Рамки (═) и прочая псевдографика не в счёте: их
# понимают и cp1251, и cp866, и они часть оформления консольной шапки.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF"
                   "\u2B00-\u2BFF\uFE0F\u2705\u274C\u2757]")

SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "dist-mac", "build",
             "output", "docs", "__pycache__", ".pytest_cache", ".idea",
             "logs", "tests"}


def project_python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def console_calls(path: Path):
    """(номер строки, исходник) всех print/sys.stdout.write в файле."""
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_print = isinstance(fn, ast.Name) and fn.id == "print"
        is_sys_write = (isinstance(fn, ast.Attribute) and fn.attr in ("write", "writelines")
                        and isinstance(fn.value, ast.Attribute)
                        and getattr(fn.value.value, "id", "") == "sys")
        if is_print or is_sys_write:
            yield node.lineno, " ".join((ast.get_source_segment(src, node) or "").split())


def _run(code: str, encoding: str = "cp1251"):
    """Запуск кода в отдельном процессе с заданной кодировкой stdout."""
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, cwd=ROOT, env=env, timeout=120,
    )


class TestConsoleOutputHasNoEmoji:
    """Консоль — не браузер: эмодзи там нечем печатать."""

    def test_no_emoji_in_print_or_stdout_write(self):
        offenders = [
            f"{path.relative_to(ROOT)}:{lineno}: {src}"
            for path in project_python_files()
            for lineno, src in console_calls(path)
            if EMOJI.search(src)
        ]
        assert not offenders, (
            "эмодзи в консольном выводе — источник UnicodeEncodeError на "
            "cp1251/cp866 (см. docstring):\n  " + "\n  ".join(offenders))

    def test_emoji_pattern_actually_matches(self):
        """Проверка самой проверки: шаблон обязан ловить эмодзи."""
        assert EMOJI.search("⚠️ Плохо")
        assert EMOJI.search("🧹 Удалено")
        assert not EMOJI.search("═" * 10)
        assert not EMOJI.search("Дев-сборка: только для разработки")


class TestUtf8Output:
    def test_shared_helper_is_used_by_the_entry_points(self):
        for name in ("config.py", "app.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            assert "from console_io import" in text, (
                f"{name} должен брать вывод из console_io, а не чинить его сам")

    def test_enable_utf8_is_idempotent(self):
        from console_io import enable_utf8
        enable_utf8()
        enable_utf8()
        assert sys.stdout.encoding.lower().replace("-", "") == "utf8"

    def test_enable_utf8_survives_missing_streams(self, monkeypatch):
        """У .app без консоли stdout может быть None — это не повод падать."""
        from console_io import enable_utf8
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        enable_utf8()
        from console_io import say
        say("ничего не должно упасть")

    def test_say_survives_a_narrow_stream(self, monkeypatch):
        """Прямая проверка: say() печатает и там, где print() падал."""
        import io

        from console_io import say
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1251")
        monkeypatch.setattr(sys, "stdout", stream)
        say("⚠️ Предупреждение")
        stream.flush()
        assert "?" in stream.buffer.getvalue().decode("cp1251", "replace")


class TestStartupOnNarrowEncodings:
    @pytest.mark.parametrize("encoding", ["cp1251", "cp866", "ascii"])
    def test_config_import_is_safe(self, encoding):
        res = _run("import config", encoding)
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        assert b"Traceback" not in res.stderr

    def test_missing_env_warning_does_not_kill_the_app(self):
        """Именно этот print ронял старт .exe с перенаправленным выводом."""
        res = _run("import config; config.load_env('no-such-file.env')")
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        assert b"UnicodeEncodeError" not in res.stderr
        assert b"Traceback" not in res.stderr

    def test_output_is_utf8_not_system_codepage(self):
        """Перенаправленный лог читается как UTF-8 — кириллица и эмодзи целы."""
        res = _run("import config; print('Привет, ⚠️ мир')")
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
        assert "Привет, ⚠️ мир" in res.stdout.decode("utf-8")
