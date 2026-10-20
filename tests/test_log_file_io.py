# -*- coding: utf-8 -*-
"""Лог прогона: как строки попадают на диск.

Почему отдельный файл: лог — не «текст для красоты», а горячий путь. Строки
пишут двадцать потоков сбора, несколько на каждую организацию, и раньше каждая
строка ОТКРЫВАЛА файл заново (замер: 0.45 мс на строку под общим замком — на
прогоне в 5000 организаций это десятки секунд, выстроенных в очередь, и лог
переставал быть бесплатным). Ошибку здесь видно только в работе, поэтому
проверяются свойства записи, а не отдельная строка кода:

* файл открыт один раз на прогон (буфер), а не на строку (считаем открытия,
  а не миллисекунды: счётчик не зависит от файловой системы);
* буферизованный путь заметно быстрее построчного;
* содержимое лога не теряется: flush/close/finish выкладывают всё, ANSI снят,
  порядок строк сохранён;
* если файл открыть не удалось, строки всё равно попадают на диск (запасной
  путь), а не пропадают молча.

Run with: python -m pytest tests/test_log_file_io.py -v
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_logger  # noqa: E402


@pytest.fixture
def logger(tmp_path, monkeypatch):
    """RunLogger в отдельной папке — настоящие логи прогонов не трогаем."""
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path))
    log = run_logger.RunLogger("testrun", ["Уфа"], ["кафе"])
    try:
        yield log
    finally:
        log.close()


def read_lines(log) -> list:
    return Path(log.path).read_text(encoding="utf-8").splitlines()


# ── Файл открыт один раз на прогон ────────────────────────────
def test_log_file_stays_open_instead_of_opening_per_line(logger):
    """Дескриптор держится открытым — иначе на каждую строку уходило бы открытие."""
    logger.log("sys", "первая строка")
    logger.log("info", "вторая строка")
    assert logger._handle is not None, "лог открывает файл на каждую строку"
    assert logger._handle.closed is False


def test_lines_are_buffered_until_a_flush(logger, monkeypatch):
    """Строки копятся в буфере: сброс — по счётчику или по времени, не на каждую."""
    monkeypatch.setattr(run_logger, "FLUSH_EVERY_LINES", 500)
    monkeypatch.setattr(run_logger, "FLUSH_SECONDS", 3600.0)
    for i in range(50):
        logger.log("sys", f"строка {i}")
    on_disk = read_lines(logger)
    logger.flush()
    after_flush = read_lines(logger)
    assert len(after_flush) > len(on_disk), "сброс буфера ничего не дописал"
    assert any("строка 49" in line for line in after_flush)


def test_flush_on_line_limit_keeps_the_file_fresh(logger, monkeypatch):
    """Достигли порога строк — буфер ушёл на диск сам, без явного flush."""
    monkeypatch.setattr(run_logger, "FLUSH_EVERY_LINES", 10)
    monkeypatch.setattr(run_logger, "FLUSH_SECONDS", 3600.0)
    logger.flush()          # шапка прогона пишется до порога — сбрасываем её
    for i in range(10):
        logger.log("sys", f"строка {i}")
    assert logger._unsaved == 0, "порог строк не привёл к сбросу буфера"
    assert any("строка 9" in line for line in read_lines(logger))


def test_close_writes_everything_and_is_idempotent(logger):
    """close() доносит остаток до диска; повторный вызов ничего не ломает."""
    for i in range(300):
        logger.log("sys", f"строка {i}")
    logger.close()
    lines = read_lines(logger)
    assert sum("строка " in line for line in lines) == 300
    assert logger._handle is None
    logger.close()  # не должно бросить


def test_finish_leaves_a_complete_file_and_closes_it(logger):
    """Итог прогона читается сразу после finish() — и включает сам итог."""
    logger.log("info", "работа")
    logger.finish(3, ["a.xlsx"], stopped=False)
    text = Path(logger.path).read_text(encoding="utf-8")
    assert "ИТОГИ ПОИСКА" in text
    assert "Найдено записей: 3" in text
    assert "работа" in text
    assert logger._handle is None, "после итога дескриптор остался открытым"


# ── Содержимое не портится ────────────────────────────────────
def test_lines_keep_order_and_lose_ansi_colors(logger):
    logger.log("info", "\x1b[32mзелёная строка\x1b[0m")
    logger.log("warn", "предупреждение")
    logger.flush()
    lines = [ln for ln in read_lines(logger) if "строка" in ln or "предупреждение" in ln]
    assert "зелёная строка" in lines[0]
    assert not re.search(r"\x1b\[", lines[0]), "ANSI-коды остались в логе"
    assert "предупреждение" in lines[1], "порядок строк не сохранён"


def test_every_level_lands_in_the_file(logger):
    for level in ("info", "warn", "ok", "sys", "result"):
        logger.log(level, f"сообщение {level}")
    logger.flush()
    text = Path(logger.path).read_text(encoding="utf-8")
    for level in ("info", "warn", "ok", "sys", "result"):
        assert f"сообщение {level}" in text
    assert "[SYS]" in text, "системные строки должны быть отличимы в логе"


# ── Запасной путь: дескриптор не открылся ─────────────────────
def test_lines_survive_when_the_file_could_not_be_opened(tmp_path, monkeypatch):
    """Файл открыть не удалось — строки всё равно пишутся, а не пропадают."""
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(run_logger.RunLogger, "_open_handle",
                        lambda self: setattr(self, "_handle", None))
    log = run_logger.RunLogger("fallback", ["Уфа"], ["кафе"])
    log.log("info", "строка без дескриптора")
    text = Path(log.path).read_text(encoding="utf-8")
    assert "строка без дескриптора" in text
    log.close()


def test_write_failure_is_reported_once_on_stderr(logger, monkeypatch, capsys):
    """Молчащий лог хуже ошибки: о поломке записи сообщаем, но один раз."""
    class Broken:
        closed = False

        def write(self, _line):
            raise OSError("диск заполнен")

        def flush(self):
            raise OSError("диск заполнен")

        def close(self):
            pass

    monkeypatch.setattr(logger, "_handle", Broken())
    for i in range(5):
        logger.log("sys", f"строка {i}")
    err = capsys.readouterr().err
    assert err.count("Не удалось записать строку лога") in (1, 2), err


# ── Скорость: ради неё всё и делалось ─────────────────────────
def _time_lines(log, n: int) -> float:
    import time
    t0 = time.perf_counter()
    for i in range(n):
        log.log("sys", f"fetch_detail: biz_id={i}, name=Фирма {i}, raw_socials=0")
    log.flush()
    return time.perf_counter() - t0


def _track_log_opens(monkeypatch, root: Path) -> list:
    """Считает, сколько раз открывался файл лога (все *.log внутри root).

    Счётчик, а не миллисекунды: он одинаков на любой машине, а сравнение
    времени зависит от того, сколько стоит open() на конкретной файловой
    системе. На CI-раннере открытие дешёвое, и разница между буфером и
    построчной записью — два с половиной раза, а не десятки.
    """
    import builtins
    import os

    real_open = builtins.open
    opened: list[str] = []

    def counting_open(file, *args, **kwargs):
        try:
            path = os.fspath(file)
            if (isinstance(path, str) and path.endswith(".log")
                    and str(path).startswith(str(root))):
                opened.append(path)
        except Exception:
            pass
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    return opened


def test_the_log_file_is_opened_once_per_run(tmp_path, monkeypatch):
    """Файл лога открывается ОДИН раз на прогон — в этом весь смысл буфера.

    Именно эта проверка ловит возврат к «открыть файл на каждую строку», и
    именно она не зависит от машины: счётчик открытий одинаков везде.
    """
    opened = _track_log_opens(monkeypatch, tmp_path)
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path / "buffered"))
    log = run_logger.RunLogger("count", ["Уфа"], ["кафе"])
    for i in range(200):
        log.log("sys", f"строка {i}")
    log.close()
    assert len(opened) == 1, (
        f"файл лога открыт {len(opened)} раз вместо одного — буфер не работает"
    )


def test_the_fallback_path_opens_the_file_per_line(tmp_path, monkeypatch):
    """Запасной путь (дескриптора нет) открывает файл на каждую строку.

    Это страховка, а не дефект: лог не должен ронять поиск, если файл
    открыть не удалось. Но возврат к построчной записи приходит именно
    отсюда, поэтому поведение зафиксировано и разница с буфером видна.
    """
    opened = _track_log_opens(monkeypatch, tmp_path)
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path / "per-line"))
    monkeypatch.setattr(run_logger.RunLogger, "_open_handle",
                        lambda self: setattr(self, "_handle", None))
    log = run_logger.RunLogger("fallback", ["Уфа"], ["кафе"])
    for i in range(20):
        log.log("sys", f"строка {i}")
    log.close()
    assert len(opened) >= 20, (
        f"запасной путь открыл файл {len(opened)} раз — он обязан писать построчно"
    )


def _time_one(tmp_path, monkeypatch, tag: str, n: int, per_line: bool) -> float:
    """Один замер одного из двух путей (по отдельной папке и файлу)."""
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path / tag))
    if per_line:
        monkeypatch.setattr(run_logger.RunLogger, "_open_handle",
                            lambda self: setattr(self, "_handle", None))
    log = run_logger.RunLogger("fast", ["Уфа"], ["кафе"])
    t = _time_lines(log, n)
    log.close()
    return t


def _compare_paths(tmp_path, monkeypatch, n: int, rounds: int = 3) -> tuple:
    """Замеряет оба пути по очереди и берёт лучший результат каждого.

    Замеры чередуются (буфер → построчно → буфер → …), чтобы шум машины
    ложился на оба пути одинаково, а не на один. Из результатов берётся
    минимум: он меньше всего зависит от того, что в этот момент делала
    система.
    """
    orig_open_handle = run_logger.RunLogger._open_handle
    best_buffered = best_per_line = None
    for i in range(rounds):
        monkeypatch.setattr(run_logger.RunLogger, "_open_handle", orig_open_handle)
        t_buffered = _time_one(tmp_path, monkeypatch, f"buffered-{i}", n, per_line=False)
        monkeypatch.setattr(run_logger.RunLogger, "_open_handle", orig_open_handle)
        t_per_line = _time_one(tmp_path, monkeypatch, f"per-line-{i}", n, per_line=True)
        best_buffered = t_buffered if best_buffered is None else min(best_buffered, t_buffered)
        best_per_line = t_per_line if best_per_line is None else min(best_per_line, t_per_line)
    return best_buffered, best_per_line


def test_buffered_logging_is_faster_than_opening_per_line(tmp_path, monkeypatch):
    """Буфер против открытия на строку — тот же файл, но заметно быстрее.

    Порог здесь скромный («в полтора раза»), а не «в три»: разница между
    путями зависит от цены open() на конкретной файловой системе. На
    локальной машине выходит 40–70×, на CI-раннере с дешёвым open() — 2.1×,
    и порог «в три раза» ронял ВЕРНЫЙ код на всех трёх системах. Гарантию
    «файл открыт один раз на прогон» проверяет отдельный тест со счётчиком
    открытий — он от файловой системы не зависит вовсе.
    """
    t_buffered, t_per_line = _compare_paths(tmp_path, monkeypatch, 2000)
    assert t_buffered * 1.5 < t_per_line, (
        f"буферизованный лог не быстрее построчного: {t_buffered:.3f}s "
        f"против {t_per_line:.3f}s"
    )
