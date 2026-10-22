# -*- coding: utf-8 -*-
"""UTF-8 вывод и безопасная печать — одно место на всё приложение."""
from __future__ import annotations

import sys

__all__ = ["enable_utf8", "say"]


def enable_utf8() -> None:
    """UTF-8 для stdout/stderr."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(text: str = "") -> None:
    """Печать, которая не может уронить приложение."""
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
