"""
Search history manager.

Stores search history in a JSON file for browsing past searches,
re-running with same parameters, and viewing results.

History file: output/.search_history.json
"""

import json
import os
import threading
import time
from pathlib import Path

from config import OUTPUT_DIR

HISTORY_FILE = os.path.join(OUTPUT_DIR, ".search_history.json")
MAX_HISTORY_ENTRIES = 100  # keep last N searches

_lock = threading.Lock()
_cache: list[dict] | None = None


def _load() -> list[dict]:
    """Load history from disk."""
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
                return _cache
        except Exception:
            pass
    _cache = []
    return _cache


def _save() -> None:
    """Save history to disk."""
    global _cache
    if _cache is None:
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def add_entry(
    run_id: str,
    queries: list[str],
    cities: list[str],
    social_mode: str = "all",
    results_count: int = 0,
    files: list[str] | None = None,
    elapsed_sec: float = 0,
    status: str = "completed",
) -> None:
    """Add a new entry to search history."""
    with _lock:
        history = _load()
        entry = {
            "run_id": run_id,
            "timestamp": time.time(),
            "queries": queries,
            "cities": cities,
            "social_mode": social_mode,
            "results_count": results_count,
            "files": files or [],
            "elapsed_sec": round(elapsed_sec, 1),
            "status": status,
        }
        # Insert at beginning (newest first)
        history.insert(0, entry)
        # Trim to max size
        if len(history) > MAX_HISTORY_ENTRIES:
            history = history[:MAX_HISTORY_ENTRIES]
        _cache = history
        _save()


def update_entry(run_id: str, **kwargs) -> None:
    """Update an existing entry by run_id."""
    with _lock:
        history = _load()
        for entry in history:
            if entry["run_id"] == run_id:
                entry.update(kwargs)
                break
        _save()


def get_history(limit: int = 50) -> list[dict]:
    """Get search history, newest first."""
    with _lock:
        history = _load()
        return history[:limit]


def get_entry(run_id: str) -> dict | None:
    """Get a specific entry by run_id."""
    with _lock:
        history = _load()
        for entry in history:
            if entry["run_id"] == run_id:
                return entry
        return None


def delete_entry(run_id: str) -> bool:
    """Delete an entry by run_id."""
    with _lock:
        history = _load()
        original_len = len(history)
        history = [e for e in history if e["run_id"] != run_id]
        if len(history) < original_len:
            _cache = history
            _save()
            return True
        return False


def clear_history() -> None:
    """Clear all history."""
    with _lock:
        _cache = []
        _save()


def get_stats() -> dict:
    """Get history statistics."""
    with _lock:
        history = _load()
        if not history:
            return {"total": 0, "total_results": 0, "total_time": 0}
        total_results = sum(e.get("results_count", 0) for e in history)
        total_time = sum(e.get("elapsed_sec", 0) for e in history)
        return {
            "total": len(history),
            "total_results": total_results,
            "total_time": round(total_time, 1),
        }
