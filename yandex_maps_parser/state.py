"""
Mutable runtime state and configuration defaults.

All modules that need config values import this module as:
    from . import state
and access values as `state.CITY`, `state._LOG_FN`, etc.
This ensures run_web() updates are visible across all modules.

Logging helpers (info / warn / ok) also live here so every module
has a single import point for both config and logging.
"""
import threading

from colorama import Fore, Style
from tqdm import tqdm

from config import (
    SEARCH_QUERIES,
    CITY,
    OUTPUT_DIR,
    OUTPUT_FILENAME,
    APPEND_MODE,
    RESUME_MODE,
    OUTPUT_CSV,
    OUTPUT_JSON,
    OUTPUT_EXCEL,
    OUTPUT_MAP,
    MIN_RATING,
    MIN_REVIEWS,
    VALIDATE_SOCIALS,
    USE_GRID,
    GRID_RADIUS_KM,
    GRID_STEP_KM,
    MAX_WORKERS,
    SEARCH_WORKERS,
    RETRY_COUNT,
    RETRY_DELAY,
    DELAY_MIN,
    DELAY_MAX,
    MAX_PAGES,
    FETCH_DETAIL,
    YANDEX_API_KEY,
    PROXIES,
)

# ── Runtime-only state ────────────────────────────────────────
_LOG_FN = None           # callable(level, msg) set by run_web; None = CLI mode
_TQDM_DISABLE = False    # True when running from web interface
_STOP_EVENT = None       # threading.Event; set to request graceful stop

# Found-counter — written from multiple detail-fetching threads; protected by _found_lock
_found_count = 0
_found_lock = threading.Lock()

# Last time we emitted a progress ping from _inc_found (monotonic seconds)
_last_inc_emit: float = 0.0
# INC_EMIT_INTERVAL: minimum seconds between progress pings triggered by _inc_found
_INC_EMIT_INTERVAL = 0.5

# Cached progress values so _inc_found can emit a full progress event at any time
_prog_cur: int = 0
_prog_tot: int = 0
_prog_stage: str = ""

# Semaphore limiting concurrent detail-page requests; re-created by run_web
_detail_semaphore = threading.Semaphore(MAX_WORKERS)

# Incremental record persistence: runner sets _RESULT_FILE to a .jsonl path
# and every enriched record is appended there (thread-safe), so a hard crash
# loses nothing that was already fetched. Final consolidation happens in runner.
_RESULT_FILE: str | None = None
# Open file handle for the sidecar — avoids re-opening the file per record.
_RESULT_HANDLE = None
_RESULT_LOCK = threading.Lock()


# ── Logging helpers ───────────────────────────────────────────

def info(msg: str) -> None:
    if _LOG_FN:
        _LOG_FN("info", msg)
        return
    tqdm.write(Fore.GREEN + msg + Style.RESET_ALL)


def warn(msg: str) -> None:
    if _LOG_FN:
        _LOG_FN("warn", "  [!] " + msg)
        return
    tqdm.write(Fore.YELLOW + "  [!] " + msg + Style.RESET_ALL)


def ok(msg: str) -> None:
    if _LOG_FN:
        _LOG_FN("ok", msg)
        return
    tqdm.write(Fore.CYAN + msg + Style.RESET_ALL)


def _progress(current: int, total: int, stage: str = "") -> None:
    """Push progress event to the web interface (no-op in CLI mode).

    Also caches cur/tot/stage so _inc_found() can emit a full event at any time.
    Progress payload format: "cur/tot/stage/found"
    """
    import time as _time
    global _prog_cur, _prog_tot, _prog_stage, _last_inc_emit
    _prog_cur = current
    _prog_tot = total
    _prog_stage = stage
    if _LOG_FN:
        _last_inc_emit = _time.monotonic()
        with _found_lock:
            count = _found_count
        _LOG_FN("progress", f"{current}/{total}/{stage}/{count}")


def _inc_found() -> None:
    """Increment the found counter (thread-safe) and emit a throttled progress ping.

    Called from enrichment worker threads — may fire from multiple threads concurrently.
    Emits at most one progress event per _INC_EMIT_INTERVAL seconds to avoid flooding
    the SSE channel while still giving the UI live feedback during detail fetching.
    Progress payload format: "cur/tot/stage/found"
    """
    import time as _time
    global _found_count, _last_inc_emit
    with _found_lock:
        _found_count += 1
        count = _found_count

    if not _LOG_FN:
        return

    now = _time.monotonic()
    # Check throttle outside the lock; a small race here is harmless (worst case:
    # two threads both pass and emit — that's fine, just one extra ping).
    if now - _last_inc_emit >= _INC_EMIT_INTERVAL:
        _last_inc_emit = now
        _LOG_FN("progress", f"{_prog_cur}/{_prog_tot}/{_prog_stage}/{count}")


def _reset_found() -> None:
    """Reset found counter and cached progress state at the start of a new run."""
    global _found_count, _prog_cur, _prog_tot, _prog_stage, _last_inc_emit
    with _found_lock:
        _found_count = 0
    _prog_cur = 0
    _prog_tot = 0
    _prog_stage = ""
    _last_inc_emit = 0.0


def _emit_result(record: dict) -> None:
    """Persist a fully-enriched record (JSONL sidecar) and stream it to the web interface.

    Called from enrichment worker threads after a business record is complete.
    Thread-safe: queue.Queue.put() is thread-safe, and JSONL appends are guarded
    by _RESULT_LOCK. We only read _LOG_FN / _RESULT_FILE (set once before threads
    start) and pass a JSON string.
    """
    import json as _json
    line = _json.dumps(record, ensure_ascii=False, default=str)
    if _RESULT_FILE:
        try:
            with _RESULT_LOCK:
                if _RESULT_HANDLE is not None:
                    _RESULT_HANDLE.write(line + "\n")
                else:
                    with open(_RESULT_FILE, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
        except Exception:
            pass
    if _LOG_FN:
        _LOG_FN("result", line)
