"""
Per-run file logger.

Creates a timestamped log file for each search run in the logs/ directory.
All info/warn/ok messages and results are written to the file for later analysis.
Thread-safe: multiple enrichment threads can write concurrently.
"""
import os
import re
import sys
import threading
import time
from datetime import datetime

# Writable dir: next to the .exe when frozen, project root from source
try:
    import paths as _paths
    LOGS_DIR = _paths.logs_dir()
except Exception:
    LOGS_DIR = "logs"
MAX_LOG_DAYS = 30      # auto-cleanup logs older than this
MAX_LOG_FILES = 200    # keep at most this many log files (newest wins)

# ── Как лог попадает на диск ───────────────────────────────────
# Раньше файл ОТКРЫВАЛСЯ на каждую строку: 0.45 мс на строку (замер на
# 20 000 строк — 6.3 с против 0.05 с у одного открытого дескриптора, 130×),
# и это под общим замком, то есть двадцать потоков сбора выстраивались в
# очередь на каждый syslog. Открытый дескриптор и сброс буфера пачкой дают
# тот же файл, но перестают быть узким местом прогона.
#
# Сброс — по числу строк ИЛИ по времени (что сработает раньше): пачка
# быстрая, а файл на диске отстаёт не больше чем на FLUSH_SECONDS.
# Записи поиска живут в JSONL-сайдкаре (state._emit_result) — лог это
# диагностика, поэтому «не больше секунд» здесь честная цена за скорость.
FLUSH_EVERY_LINES = 200
FLUSH_SECONDS = 5.0

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class RunLogger:
    """Writes structured logs for a single search run."""

    def __init__(self, run_id: str, cities: list[str], queries: list[str]):
        os.makedirs(LOGS_DIR, exist_ok=True)
        # Prune old logs at the start of every run (not only at app boot),
        # so a long-lived server doesn't accumulate logs forever.
        try:
            cleanup_old_logs()
        except Exception:
            pass
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        city_slug = "_".join(c.replace(" ", "") for c in cities[:3])
        if len(cities) > 3:
            city_slug += f"_and{len(cities) - 3}more"
        self._path = os.path.join(LOGS_DIR, f"{ts}_{run_id}_{city_slug}.log")
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._lines = 0
        # Открытый на запись файл и счётчики сброса буфера.
        self._handle = None
        self._unsaved = 0
        self._last_flush = time.monotonic()
        self._write_errors = 0
        self._open_handle()

        # Write header
        self._write("═" * 60)
        self._write(f"  ЗАПУСК ПОИСКА  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write(f"  Run ID: {run_id}")
        self._write(f"  Города: {', '.join(cities)}")
        self._write(f"  Запросы: {', '.join(queries)}")
        self._write("═" * 60)

    @property
    def path(self) -> str:
        return self._path

    def _open_handle(self) -> None:
        """Открыть файл на дозапись — один раз на прогон.

        Не удалось открыть (папка только для чтения, файл занят) — работаем
        прежним путём: каждая строка открывает файл сама. Лог не должен
        ронять поиск ни в каком случае.
        """
        try:
            self._handle = open(self._path, "a", encoding="utf-8",
                                buffering=64 * 1024)
        except Exception:
            self._handle = None

    def _flush_locked(self) -> None:
        """Сбросить буфер на диск (вызывается под замком)."""
        if self._handle is None:
            return
        try:
            self._handle.flush()
        except Exception:
            self._note_write_error()
        self._unsaved = 0
        self._last_flush = time.monotonic()

    def _note_write_error(self) -> None:
        """Один раз сообщить о поломке записи лога — молчащий лог хуже ошибки."""
        self._write_errors += 1
        if self._write_errors == 1:
            try:
                print(f"[!] Не удалось записать строку лога {self._path}",
                      file=sys.stderr)
            except Exception:
                pass

    def flush(self) -> None:
        """Записать буфер лога на диск (для проверок и завершения)."""
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        """Дописать буфер и закрыть файл. Повторный вызов безопасен."""
        with self._lock:
            self._flush_locked()
            if self._handle is not None:
                try:
                    self._handle.close()
                except Exception:
                    pass
                self._handle = None

    def _write(self, text: str) -> None:
        """Записать строку в лог (потокобезопасно, без открытия файла)."""
        clean = _ANSI_RE.sub("", text)
        line = clean + "\n"
        with self._lock:
            if self._handle is None:
                # Запасной путь: дескриптора нет — открываем файл на строку.
                self._write_without_handle(line)
                return
            try:
                self._handle.write(line)
                self._lines += 1
                self._unsaved += 1
                if (self._unsaved >= FLUSH_EVERY_LINES
                        or time.monotonic() - self._last_flush >= FLUSH_SECONDS):
                    self._flush_locked()
            except Exception:
                self._note_write_error()
                self._write_without_handle(line)

    def _write_without_handle(self, line: str) -> None:
        """Строка мимо открытого дескриптора — тем же способом, что и раньше."""
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
            self._lines += 1
        except Exception:
            self._note_write_error()

    def log(self, level: str, msg: str) -> None:
        """Log a message from the search pipeline.

        Levels:
          info/warn/ok — user-facing messages (also sent to browser)
          sys          — system/developer traces (file only)
          result       — single enriched record summary
        """
        # Structured statistics are a UI payload (JSON), not a log line — the
        # file gets a compact «stats: …» record from state.syslog instead.
        if level == "stats":
            return
        # Absolute wall-clock stamp [HH:MM:SS] — it survives restarts and
        # resume; the elapsed delta from the run start rides along in the
        # sys record so timings stay reconstructable.
        ts = time.time() - self._started_at
        mins, secs = divmod(int(ts), 60)
        timestamp = f"[{datetime.now().strftime('%H:%M:%S')} +{mins}:{secs:02d}]"
        prefix = {"info": "ℹ", "warn": "⚠", "ok": "✔", "result": "→", "sys": "⚙"}.get(level, "·")

        if level == "result":
            # Don't dump full JSON — just a summary line
            self._write(f"{timestamp} {prefix} {msg[:200]}")
        elif level == "sys":
            self._write(f"{timestamp} {prefix} [SYS] {msg}")
        else:
            self._write(f"{timestamp} {prefix} {msg}")

    def log_result_summary(self, record: dict) -> None:
        """Log a one-line summary of a found business."""
        name = record.get("name", "?")
        addr = record.get("address", "")
        socials = [p for p in ["vk", "instagram", "telegram", "whatsapp",
                               "facebook", "youtube", "tiktok", "ok", "twitter"]
                   if record.get(p)]
        social_str = ", ".join(socials) if socials else "нет"
        self._write(f"    📍 {name} | {addr} | соцсети: {social_str}")

    def log_city_start(self, city_idx: int, total: int, city: str) -> None:
        """Log city start."""
        self._write("")
        self._write("═" * 60)
        self._write(f"  🏙  Город {city_idx}/{total}: {city}")
        self._write("═" * 60)

    def log_city_done(self, city: str, records: int, skipped: bool = False) -> None:
        """Log city completion."""
        status = "ПРОПУЩЕН" if skipped else "ЗАВЕРШЁН"
        self._write(f"  ✅ {city}: {status} — {records} записей")
        self._write("─" * 60)

    def finish(self, total_results: int, files: list[str], stopped: bool = False,
               paused: bool = False) -> None:
        """Write final summary.

        A pause unwinds through the same graceful path as a stop, but its
        summary must not read «Остановлено пользователем»: the run is waiting
        to be continued, and the wrong wording made the pause look like the
        end of the search.
        """
        elapsed = time.time() - self._started_at
        mins, secs = divmod(int(elapsed), 60)
        self._write("")
        self._write("═" * 60)
        self._write("  ИТОГИ ПОИСКА")
        self._write(f"  Время: {mins}м {secs}с")
        self._write(f"  Найдено записей: {total_results}")
        self._write(f"  Файлы: {', '.join(files) if files else 'нет'}")
        if paused:
            self._write("  ⏸ Поставлен на паузу — прогресс сохранён, можно продолжить")
        elif stopped:
            self._write("  ⏹ Остановлено пользователем")
        self._write(f"  Лог: {self._path}")
        self._write("═" * 60)
        # Итог обязан быть на диске целиком: за ним сюда и заходят.
        self.close()


def cleanup_old_logs() -> int:
    """Remove old log files: older than MAX_LOG_DAYS, or beyond MAX_LOG_FILES.

    Returns count of deleted files.
    """
    if not os.path.isdir(LOGS_DIR):
        return 0
    cutoff = time.time() - MAX_LOG_DAYS * 86400
    deleted = 0
    try:
        logs = sorted(
            (os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.endswith(".log")),
            key=os.path.getmtime,
        )
    except Exception:
        logs = []
    # 1. Age-based deletion
    for fpath in logs:
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except Exception:
            pass
    # 2. Count-based cap (newest kept)
    try:
        remaining = sorted(
            (os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.endswith(".log")),
            key=os.path.getmtime,
        )
    except Exception:
        remaining = []
    excess = len(remaining) - MAX_LOG_FILES
    for fpath in remaining[:excess]:
        try:
            os.remove(fpath)
            deleted += 1
        except Exception:
            pass
    return deleted


def list_logs() -> list[dict]:
    """List all log files with metadata, newest first."""
    if not os.path.isdir(LOGS_DIR):
        return []
    logs = []
    for fname in sorted(os.listdir(LOGS_DIR), reverse=True):
        if not fname.endswith(".log"):
            continue
        fpath = os.path.join(LOGS_DIR, fname)
        try:
            stat = os.stat(fpath)
            logs.append({
                "name": fname,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
            })
        except Exception:
            pass
    return logs
