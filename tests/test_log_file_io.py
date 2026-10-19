# -*- coding: utf-8 -*-
"""Лог прогона: как строки попадают на диск.

Почему отдельный файл: лог — не «текст для красоты», а горячий путь. Строки
пишут двадцать потоков сбора, несколько на каждую организацию, и раньше каждая
строка ОТКРЫВАЛА файл заново (замер: 0.45 мс на строку под общим замком — на
прогоне в 5000 организаций это десятки секунд, выстроенных в очередь, и лог
переставал быть бесплатным). Ошибку здесь видно только в работе, поэтому
проверяются свойства записи, а не отдельная строка кода:

* файл открыт один раз на прогон (буфер), а не на строку;
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


def test_buffered_logging_is_faster_than_opening_per_line(tmp_path, monkeypatch):
    """Буфер против открытия на строку — тот же файл, но в разы быстрее.

    Порог «в 3 раза» взят с запасом: замер на 20 000 строк даёт 130×, а
    зависит он от файловой системы, не от машины. Проверка нужна, чтобы
    возврат «открыть файл на каждую строку» не прошёл незамеченным.
    """
    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path / "buffered"))
    buffered = run_logger.RunLogger("fast", ["Уфа"], ["кафе"])
    t_buffered = _time_lines(buffered, 3000)
    buffered.close()

    monkeypatch.setattr(run_logger, "LOGS_DIR", str(tmp_path / "per-line"))
    monkeypatch.setattr(run_logger.RunLogger, "_open_handle",
                        lambda self: setattr(self, "_handle", None))
    per_line = run_logger.RunLogger("slow", ["Уфа"], ["кафе"])
    t_per_line = _time_lines(per_line, 3000)
    per_line.close()

    assert t_buffered * 3 < t_per_line, (
        f"буферизованный лог не быстрее построчного: {t_buffered:.3f}s "
        f"против {t_per_line:.3f}s"
    )
