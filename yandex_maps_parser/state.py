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
import time as _time

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
    MAX_CANDIDATES_PER_CITY,
    YANDEX_API_KEY,
    PROXIES,
)

# Social mode: "all" | "with_socials" | "without_socials"
# Set by run_web(); controls whether enrichment fetches detail pages
# and whether the frontend filters results by social media presence.
SOCIAL_MODE = "all"

# ── Runtime-only state ────────────────────────────────────────
_LOG_FN = None           # callable(level, msg) set by run_web; None = CLI mode
_SYSLOG_FN = None        # callable(msg) for file-only system traces (developer logs)
_TQDM_DISABLE = False    # True when running from web interface
_STOP_EVENT = None       # threading.Event; set to request graceful stop
_SKIP_CITY_EVENT = None  # threading.Event; set to skip current city (not the whole run)
_SKIPPED_CITIES: list[dict] = []  # [{"name": str, "records_found": int}]
_CITY_RECORDS_FOUND = 0  # records found in current city (for skip confirmation)
_city_records_lock = threading.Lock()

# Found-counter — written from multiple detail-fetching threads; protected by _found_lock
_found_count = 0
_found_lock = threading.Lock()

# Last time we emitted a progress ping from _inc_found (monotonic seconds)
_last_inc_emit: float = 0.0
# INC_EMIT_INTERVAL: minimum seconds between progress pings triggered by _inc_found
_INC_EMIT_INTERVAL = 0.5

# Analytics throttling: emit at most once per _ANALYTICS_INTERVAL seconds
_last_analytics_emit: float = 0.0
_ANALYTICS_INTERVAL = 5.0  # seconds

# Cached progress values so _inc_found can emit a full progress event at any time
_prog_cur: int = 0
_prog_tot: int = 0
_prog_stage: str = ""

# ── Work-based progress tracking ──────────────────────────────
# Combined progress = search_points_done + enrichment_done
#                     ─────────────────────────────────────────
#                     search_points_total + candidates_total
#
# This gives accurate percentage throughout the entire run, not just the
# search phase.  Candidates total grows during search; enrichment_done
# grows during enrichment; the percentage reflects real work completed.
_work_candidates_total: int = 0   # total candidates discovered (grows during search)
_work_candidates_done: int = 0    # candidates fully enriched so far

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
    """User-facing log: goes to browser + file."""
    if _LOG_FN:
        _LOG_FN("info", msg)
        return
    tqdm.write(Fore.GREEN + msg + Style.RESET_ALL)


def warn(msg: str) -> None:
    """User-facing warning: goes to browser + file."""
    if _LOG_FN:
        _LOG_FN("warn", "  [!] " + msg)
        return
    tqdm.write(Fore.YELLOW + "  [!] " + msg + Style.RESET_ALL)


def ok(msg: str) -> None:
    """User-facing success: goes to browser + file."""
    if _LOG_FN:
        _LOG_FN("ok", msg)
        return
    tqdm.write(Fore.CYAN + msg + Style.RESET_ALL)


def syslog(msg: str) -> None:
    """System/developer log: goes to file only, NOT to browser.
    Use for internal traces: HTTP details, function calls, timings."""
    if _SYSLOG_FN:
        _SYSLOG_FN(msg)


def _progress(current: int, total: int, stage: str = "") -> None:
    """Push progress event to the web interface (no-op in CLI mode).

    Updates the search-phase counters and emits a work-based progress event.
    The progress value represents: (search_done + enrich_done) / (search_total + candidates_total).
    Progress payload format: "work_done/work_total/stage/found"
    """
    global _prog_cur, _prog_tot, _prog_stage, _last_inc_emit
    _prog_cur = current
    _prog_tot = total
    _prog_stage = stage
    if _LOG_FN:
        _last_inc_emit = _time.monotonic()
        with _found_lock:
            count = _found_count
            work_done = current + _work_candidates_done
            work_total = total + _work_candidates_total
        _LOG_FN("progress", f"{work_done}/{work_total}/{stage}/{count}")


def _add_candidates(n: int) -> None:
    """Record that n new candidates were discovered and will be enriched.

    Called from enrich() when a batch starts.  Increases the estimated total
    work so the progress percentage accurately reflects remaining effort.
    """
    global _work_candidates_total
    with _found_lock:
        _work_candidates_total += n


def _inc_found() -> None:
    """Increment the found counter (thread-safe) and emit a throttled progress ping.

    Called from enrichment worker threads — may fire from multiple threads concurrently.
    Emits at most one progress event per _INC_EMIT_INTERVAL seconds to avoid flooding
    the SSE channel while still giving the UI live feedback during detail fetching.
    Progress payload format: "work_done/work_total/stage/found"
    """
    global _found_count, _work_candidates_done, _last_inc_emit
    with _found_lock:
        _found_count += 1
        _work_candidates_done += 1
        count = _found_count

    now = _time.monotonic()
    # Check throttle outside the lock; a small race here is harmless (worst case:
    # two threads both pass and emit — that's fine, just one extra ping).
    if now - _last_inc_emit >= _INC_EMIT_INTERVAL:
        _last_inc_emit = now
        if _LOG_FN:
            with _found_lock:
                work_done = _prog_cur + _work_candidates_done
                work_total = _prog_tot + _work_candidates_total
            _LOG_FN("progress", f"{work_done}/{work_total}/{_prog_stage}/{count}")
            # Emit analytics every 5 seconds
            _emit_analytics_throttled(now)


def _emit_analytics_throttled(now: float) -> None:
    """Emit compact analytics summary every _ANALYTICS_INTERVAL seconds.
    
    Only writes a short one-line summary to syslog (file), NOT the full JSON.
    The full analytics dict is served via the /analytics API endpoint.
    """
    global _last_analytics_emit
    if now - _last_analytics_emit < _ANALYTICS_INTERVAL:
        return
    _last_analytics_emit = now
    if _SYSLOG_FN:
        try:
            from .http_client import get_analytics
            a = get_analytics()
            _SYSLOG_FN(f"analytics: rps={a['rps_actual']}/{a['rps_target']:.0f} "
                       f"lat={a['avg_latency']:.1f}s(p50={a['p50_latency']:.1f}s) "
                       f"req={a['total_requests']} err={a['errors']} 429={a['rate_limits']}")
        except Exception:
            pass


def _reset_found() -> None:
    """Reset found counter and cached progress state at the start of a new run."""
    global _found_count, _prog_cur, _prog_tot, _prog_stage, _last_inc_emit, _last_analytics_emit
    global _work_candidates_total, _work_candidates_done
    with _found_lock:
        _found_count = 0
        _work_candidates_total = 0
        _work_candidates_done = 0
    _prog_cur = 0
    _prog_tot = 0
    _prog_stage = ""
    _last_inc_emit = 0.0
    _last_analytics_emit = 0.0


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
    # Incremental Excel: append this record to the in-progress workbook
    if _EXCEL_APPEND_ENABLED:
        try:
            from .exporters import _append_excel
            _append_excel(record)
        except Exception as exc:
            if _LOG_FN:
                _LOG_FN("warn", f"  [!] Ошибка записи Excel: {exc}")
    if _LOG_FN:
        _LOG_FN("result", line)


# ── Incremental Excel toggle ──────────────────────────────────
# Enabled by run() / run_web() when OUTPUT_EXCEL is True.
_EXCEL_APPEND_ENABLED = False


# ── Skip city helpers ───────────────────────────────────────
def skip_city():
    """Signal to skip the current city (not the whole run)."""
    if _SKIP_CITY_EVENT:
        _SKIP_CITY_EVENT.set()


def reset_skip_city():
    """Reset skip event and record counter for a new city."""
    global _CITY_RECORDS_FOUND
    if _SKIP_CITY_EVENT:
        _SKIP_CITY_EVENT.clear()
    _CITY_RECORDS_FOUND = 0


def is_skip_city() -> bool:
    """Check if current city skip was requested."""
    return bool(_SKIP_CITY_EVENT and _SKIP_CITY_EVENT.is_set())


def inc_city_record():
    """Increment the per-city record counter (thread-safe)."""
    global _CITY_RECORDS_FOUND
    with _city_records_lock:
        _CITY_RECORDS_FOUND += 1
