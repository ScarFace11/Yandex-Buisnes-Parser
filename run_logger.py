"""
Per-run file logger.

Creates a timestamped log file for each search run in the logs/ directory.
All info/warn/ok messages and results are written to the file for later analysis.
Thread-safe: multiple enrichment threads can write concurrently.
"""
import os
import re
import threading
import time
from datetime import datetime

LOGS_DIR = "logs"
MAX_LOG_DAYS = 30  # auto-cleanup logs older than this


class RunLogger:
    """Writes structured logs for a single search run."""

    def __init__(self, run_id: str, cities: list[str], queries: list[str]):
        os.makedirs(LOGS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        city_slug = "_".join(c.replace(" ", "") for c in cities[:3])
        if len(cities) > 3:
            city_slug += f"_and{len(cities) - 3}more"
        self._path = os.path.join(LOGS_DIR, f"{ts}_{run_id}_{city_slug}.log")
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._lines = 0

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

    def _write(self, text: str) -> None:
        """Write a line to the log file (thread-safe)."""
        # Strip ANSI codes
        clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(clean + "\n")
                self._lines += 1
            except Exception:
                pass

    def log(self, level: str, msg: str) -> None:
        """Log a message from the search pipeline.

        Levels:
          info/warn/ok — user-facing messages (also sent to browser)
          sys          — system/developer traces (file only)
          result       — single enriched record summary
        """
        ts = time.time() - self._started_at
        mins, secs = divmod(int(ts), 60)
        timestamp = f"[{mins:02d}:{secs:02d}]"
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

    def finish(self, total_results: int, files: list[str], stopped: bool = False) -> None:
        """Write final summary."""
        elapsed = time.time() - self._started_at
        mins, secs = divmod(int(elapsed), 60)
        self._write("")
        self._write("═" * 60)
        self._write(f"  ИТОГИ ПОИСКА")
        self._write(f"  Время: {mins}м {secs}с")
        self._write(f"  Найдено записей: {total_results}")
        self._write(f"  Файлы: {', '.join(files) if files else 'нет'}")
        if stopped:
            self._write(f"  ⏹ Остановлено пользователем")
        self._write(f"  Лог: {self._path}")
        self._write("═" * 60)


def cleanup_old_logs() -> int:
    """Remove log files older than MAX_LOG_DAYS. Returns count of deleted files."""
    if not os.path.isdir(LOGS_DIR):
        return 0
    cutoff = time.time() - MAX_LOG_DAYS * 86400
    deleted = 0
    for fname in os.listdir(LOGS_DIR):
        if not fname.endswith(".log"):
            continue
        fpath = os.path.join(LOGS_DIR, fname)
        try:
            if os.path.getmtime(fpath) < cutoff:
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
