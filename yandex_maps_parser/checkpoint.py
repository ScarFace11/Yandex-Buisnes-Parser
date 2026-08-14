"""
Checkpoint / resume: save and restore parser progress across runs.
"""
import json
import os

from . import state


def _ckpt_path(base: str) -> str:
    return os.path.join(state.OUTPUT_DIR, f"{base}.checkpoint.json")


def load_checkpoint(base: str) -> dict:
    path = _ckpt_path(base)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            seen  = set(data.get("seen_urls", []))
            done  = {(c["query"], c["lat"], c["lon"]) for c in data.get("completed", [])}
            state.info(f"  Checkpoint: {len(seen)} ранее найденных, {len(done)} точек уже обработано.")
            return {"seen_urls": seen, "completed": done}
        except Exception:
            pass
    return {"seen_urls": set(), "completed": set()}


def save_checkpoint(base: str, seen_urls: set[str], completed: set[tuple]) -> None:
    from datetime import datetime
    path = _ckpt_path(base)
    os.makedirs(state.OUTPUT_DIR, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "seen_urls": list(seen_urls),
                    "completed": [
                        {"query": q, "lat": lat, "lon": lon}
                        for q, lat, lon in completed
                    ],
                    "saved_at": datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass


def clear_checkpoint(base: str) -> None:
    path = _ckpt_path(base)
    if os.path.exists(path):
        os.remove(path)


# ── Global seen-store ─────────────────────────────────────────
# Unlike the per-base checkpoint, this one persists across ALL runs and all
# output files, so re-running the parser (e.g. from the web UI, which always
# uses a fresh timestamped filename) never touches a business twice.

def _global_seen_path() -> str:
    return os.path.join(state.OUTPUT_DIR, "_seen.json")


def load_global_seen() -> set[str]:
    path = _global_seen_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("seen_urls", []))
        except Exception:
            pass
    return set()


def save_global_seen(seen_urls: set[str]) -> None:
    from datetime import datetime
    path = _global_seen_path()
    os.makedirs(state.OUTPUT_DIR, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "seen_urls": list(seen_urls),
                    "saved_at": datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
            )
    except Exception:
        pass
