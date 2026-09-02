"""
Disk cache for Yandex Maps detail page responses.

Stores HTML responses keyed by biz_id to avoid re-fetching pages
we've already downloaded.  TTL = 24 hours.

Usage:
    from .cache import get_cached, set_cached
    html = get_cached("1234567890")
    if html is None:
        html = fetch_html(url)
        if html:
            set_cached("1234567890", html)
"""
import json
import os
import time
import threading

from . import state

_CACHE_DIR = os.path.join(state.OUTPUT_DIR, ".cache")
_TTL_SECONDS = 24 * 3600  # 24 hours
_lock = threading.Lock()


def _ensure_cache_dir() -> None:
    """Create cache directory if it doesn't exist."""
    os.makedirs(_CACHE_DIR, exist_ok=True)


def get_cached(biz_id: str) -> str | None:
    """Return cached HTML for biz_id, or None.

    Caching is currently disabled — always returns None.
    Re-enable by uncommenting the logic below.
    """
    return None


def set_cached(biz_id: str, html: str) -> None:
    """No-op — caching disabled."""
    pass


def cache_stats() -> dict:
    """Return cache statistics."""
    _ensure_cache_dir()
    try:
        files = [f for f in os.listdir(_CACHE_DIR) if f.endswith(".html")]
        total = len(files)
        valid = 0
        now = time.time()
        for fname in files:
            fpath = os.path.join(_CACHE_DIR, fname)
            if now - os.path.getmtime(fpath) <= _TTL_SECONDS:
                valid += 1
        return {"total": total, "valid": valid, "expired": total - valid}
    except Exception:
        return {"total": 0, "valid": 0, "expired": 0}


def cleanup_expired() -> int:
    """Remove expired cache files.  Returns number of files removed."""
    _ensure_cache_dir()
    removed = 0
    now = time.time()
    try:
        for fname in os.listdir(_CACHE_DIR):
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(_CACHE_DIR, fname)
            if now - os.path.getmtime(fpath) > _TTL_SECONDS:
                try:
                    os.remove(fpath)
                    removed += 1
                except OSError:
                    pass
    except Exception:
        pass
    return removed
