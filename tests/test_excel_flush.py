# -*- coding: utf-8 -*-
"""Инкрементальный xlsx: когда книга уходит на диск и что при этом теряется.

Зачем: во время поиска каждая найденная организация дозаписывается в книгу
Excel, а openpyxl сохраняет книгу ЦЕЛИКОМ — то есть «сохранить на каждую
запись» это квадратичная работа. Замер на 1500 организациях: сброс каждые
5 записей — 288 с, каждые 200 — 12 с. Сбор идёт часами, поэтому расписание
сброса — вопрос не удобства, а того, доедет ли прогон до конца.

Проверяется контракт: строки не теряются (они в книге памяти сразу, полный
файл собирается в конце), на диск книга уходит по порогу записей или по
времени, а ошибка сохранения не выглядит как «нашлось мало организаций».

Run with: python -m pytest tests/test_excel_flush.py -v
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from yandex_maps_parser import exporters as ex  # noqa: E402


def _record(i: int) -> dict:
    return {"name": f"Фирма {i}", "city": "Москва", "address": f"ул. Ленина {i}",
            "category": "Кафе", "phone": "+7 999 000-00-00",
            "yandex_maps_url": f"https://yandex.ru/maps/org/{i}", "rating": 4.5,
            "reviews_count": 10, "lead_score": 5}


@pytest.fixture
def book(tmp_path, monkeypatch):
    """Чистая книга в отдельном файле + возврат модульного синглтона на место."""
    saved = ex._excel
    ex._excel = ex._ExcelState()
    try:
        yield ex._excel, tmp_path / "live.xlsx"
    finally:
        ex._excel.open, ex._excel.wb = False, None
        ex._excel = saved


@pytest.fixture
def count_saves(monkeypatch):
    """Сколько раз книга ушла на диск и сколько строк было в каждой записи."""
    calls = []
    real = ex._save_excel_file

    def wrapper(state_obj):
        calls.append(state_obj.wb.active.max_row - 1)
        return real(state_obj)

    monkeypatch.setattr(ex, "_save_excel_file", wrapper)
    return calls


# ── Расписание: порог записей ─────────────────────────────────
def test_disk_save_happens_on_the_record_threshold(book, count_saves, monkeypatch):
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 10)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 3600.0)
    ex._init_excel(str(path))
    for i in range(25):
        ex._append_excel(_record(i))
    # 10 и 20 записей — два сброса; 25-я ещё в книге памяти.
    assert count_saves == [10, 20], count_saves
    assert state._dirty == 5


def test_no_save_before_the_threshold(book, count_saves, monkeypatch):
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 200)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 3600.0)
    ex._init_excel(str(path))
    for i in range(50):
        ex._append_excel(_record(i))
    assert count_saves == [], "книга сохранялась до порога"
    assert state._dirty == 50


def test_rows_waiting_in_memory_still_reach_the_file_at_the_end(book, monkeypatch):
    """Порог не сработал — записи не потеряны: финальный файл полный."""
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 500)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 3600.0)
    ex._init_excel(str(path))
    records = [_record(i) for i in range(30)]
    for r in records:
        ex._append_excel(r)
    ex._finalize_excel(records)
    rows = ex._records_from_xlsx(str(path))
    assert len(rows) == 30
    assert rows[29]["name"] == "Фирма 29"


# ── Расписание: время ─────────────────────────────────────────
def test_time_since_the_last_save_also_triggers_it(book, count_saves, monkeypatch):
    """Порог записей не достигнут, но книга «старая» — сброс по времени."""
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 1000)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 30.0)
    ex._init_excel(str(path))
    ex._append_excel(_record(0))
    assert count_saves == []
    state._last_save -= 31.0          # прошло больше минуты
    ex._append_excel(_record(1))
    assert count_saves == [2], count_saves
    assert state._dirty == 0


def test_fresh_book_is_not_saved_again_immediately(book, count_saves, monkeypatch):
    """После сброса следующая запись не тянет за собой ещё один сброс."""
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 2)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 30.0)
    ex._init_excel(str(path))
    for i in range(4):
        ex._append_excel(_record(i))
    assert count_saves == [2, 4], count_saves


# ── Ошибка сохранения не молчит и не тормозит ─────────────────
def test_save_failure_is_reported_once(book, monkeypatch):
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 1)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 3600.0)
    warnings = []
    from yandex_maps_parser import state as parser_state
    monkeypatch.setattr(parser_state, "warn", lambda msg: warnings.append(msg))

    ex._init_excel(str(path))

    def explode(_path):
        raise OSError("диск заполнен")

    monkeypatch.setattr(state.wb, "save", explode)
    for i in range(5):
        ex._append_excel(_record(i))
    assert len(warnings) == 1, f"о поломке сохранения сообщено {len(warnings)} раз"
    assert "диск заполнен" in warnings[0]


def test_failed_save_keeps_the_schedule_instead_of_retrying_per_record(
        book, monkeypatch, count_saves):
    """Сбойный сброс ждёт следующего порога, а не повторяется на каждой записи.

    Сброс стирает счётчик несохранённых строк: попытка идёт под тот же
    порог, иначе каждая следующая запись дёргала бы диск.
    """
    state, path = book
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_RECORDS", 3)
    monkeypatch.setattr(ex, "_EXCEL_FLUSH_SECONDS", 3600.0)
    from yandex_maps_parser import state as parser_state
    monkeypatch.setattr(parser_state, "warn", lambda msg: None)
    ex._init_excel(str(path))
    monkeypatch.setattr(state.wb, "save",
                        lambda _p: (_ for _ in ()).throw(OSError("нет места")))
    for i in range(6):
        ex._append_excel(_record(i))
    assert len(count_saves) == 2, (
        f"6 записей при пороге 3 — не больше двух попыток, а было {len(count_saves)}"
    )
    assert state._dirty == 0, "сбойная попытка не сбросила счётчик строк"


# ── Скорость: ради неё расписание и менялось ──────────────────
def _append_many(n: int, path: Path, batch: int) -> float:
    ex._EXCEL_FLUSH_RECORDS = batch
    ex._EXCEL_FLUSH_SECONDS = 3600.0
    ex._excel = ex._ExcelState()
    ex._init_excel(str(path))
    t0 = time.perf_counter()
    for i in range(n):
        ex._append_excel(_record(i))
    return time.perf_counter() - t0


def test_rarer_saves_make_a_visible_difference(tmp_path, monkeypatch):
    """Редкий сброс против частого: на 300 записях разница обязана быть видна.

    Порог «в 2 раза» — с большим запасом: замер на 500 записях даёт 40 с
    против 2 с. Проверка сторожит возврат к «сохранить каждые 5 записей».
    """
    t_frequent = _append_many(120, tmp_path / "frequent.xlsx", 5)
    t_rare = _append_many(120, tmp_path / "rare.xlsx", 120)
    ex._excel.open, ex._excel.wb = False, None
    assert t_rare * 2 < t_frequent, (
        f"частый сброс книги не дороже редкого: {t_frequent:.2f}s против {t_rare:.2f}s"
    )
