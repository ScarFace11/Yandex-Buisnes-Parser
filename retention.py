"""Автоудаление сохранённых результатов через N дней.

Срок хранения выбирается пользователем (7 / 14 / 30 дней или своё число,
максимум 30) и хранится в settings.json (ключ ``retention_days``). При
запуске приложения (и при смене срока) старые файлы результатов удаляются.

Служебные файлы приложения (кэш найденного ``_seen.json``, чекпоинты
``*.checkpoint.json``, история ``.search_history.json``, отметки
``_reviewed.json``, кэш координат ``.cache/``, бэкапы ``_backup/``) все
начинаются с точки или подчёркивания и поэтому НИКОГДА не попадают под
очистку — фильтры ниже пропускают такие имена.
"""
import os
import time
from pathlib import Path

import paths

RETENTION_KEY = "retention_days"
DEFAULT_DAYS = 30
MAX_DAYS = 30
MIN_DAYS = 1
PRESET_DAYS = (7, 14, 30)

# Расширения файлов результатов, которые подлежат очистке.
_RESULT_EXTS = {".xlsx", ".csv", ".html", ".json"}
# Служебные суффиксы, которые не чистим, даже если расширение подходит.
_SKIP_SUFFIXES = (".checkpoint.json", ".jsonl")
# Служебные папки, которые не трогаем (отзывы-бэкапы и т.п.).
_SKIP_DIRS = {"_backup"}


def _clamp(days) -> int:
    try:
        d = int(days)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(MIN_DAYS, min(MAX_DAYS, d))


def get_retention_days() -> int:
    """Текущий срок хранения (дни) из settings.json; по умолчанию 30."""
    return _clamp(paths.load_settings().get(RETENTION_KEY, DEFAULT_DAYS))


def set_retention_days(days) -> int:
    """Сохранить срок хранения (с ограничением 1..30) и вернуть его."""
    d = _clamp(days)
    paths.save_settings({RETENTION_KEY: d})
    return d


def cleanup_old_results(days=None) -> int:
    """Удалить файлы результатов старше N дней. Возвращает число удалённых.

    Обходит корень результатов (raw/, processed/, _archive/ и файлы в самом
    корне). Служебные имена (начинаются с «.»/«_», ``*.checkpoint.json``,
    ``*.jsonl``) и служебные папки пропускаются.
    """
    if days is None:
        days = get_retention_days()
    days = _clamp(days)
    cutoff = time.time() - days * 86400
    root = Path(paths.results_root())
    removed = 0
    if not root.exists():
        return 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Скрытые (.cache) и служебные (_backup) папки не обходим.
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.startswith(".") or fn.startswith("_") or fn.startswith("~$"):
                continue
            if fn.endswith(_SKIP_SUFFIXES):
                continue
            if Path(fn).suffix.lower() not in _RESULT_EXTS:
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    return removed
