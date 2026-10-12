# -*- coding: utf-8 -*-
"""UTF-8 вывод и безопасная печать — одно место на всё приложение.

Зачем: на русской Windows консоль работает в cp1251/cp866, а stdout,
перенаправленный в файл или пайп, вообще получает системную кодировку.
Сообщение с эмодзи падало ``UnicodeEncodeError`` прямо при импорте
``config.py`` — собранный .exe не запускался, вместо интерфейса был трейсбек.

Что здесь есть:

* ``enable_utf8()`` — переводит ``sys.stdout``/``sys.stderr`` в UTF-8 с
  ``errors="replace"``. Для настоящей консоли это ничего не меняет (Python на
  Windows и так держит её в UTF-8), а перенаправленный вывод — лог-файл, пайп,
  вывод шага CI — читается как UTF-8 вместо cp1251;
* ``say()`` — печать, которая не может уронить приложение: на узкой кодировке
  непредставимые символы заменяются на «?».

Эмодзи в консольных сообщениях не используем: интерфейс отдаётся браузеру, где
кодировка всегда UTF-8, а консоль — среда с неизвестной кодировкой (иначе и
возникал баг со стартом). Инвариант держит ``tests/test_console_output.py``.
"""
from __future__ import annotations

import sys

__all__ = ["enable_utf8", "say"]


def enable_utf8() -> None:
    """UTF-8 для stdout/stderr. Никогда не бросает исключений.

    Вывод — не повод падать: у .app без консоли потока может не быть вовсе
    (``sys.stdout is None``), а у какого-нибудь окружения поток вообще не
    поддерживает ``reconfigure``.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(text: str = "") -> None:
    """Печать, которая не может уронить приложение.

    Сначала обычный ``print``; если кодировка потока узкая — печатаем версию
    строки в этой же кодировке с заменами, чтобы сообщение всё-таки было видно.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            print(str(text).encode(enc, "replace").decode(enc, "replace"))
        except Exception:
            pass
    except Exception:
        pass
