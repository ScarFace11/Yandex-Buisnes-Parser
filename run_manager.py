"""
Run state management: process lifecycle, queue bridging, run registry.

Each search runs in its own process (multiprocessing) for true isolation.
A bridge thread reads from the multiprocessing.Queue and forwards to a
regular queue.Queue that the SSE endpoint can consume with timeout.
"""
import os
import json
import queue
import threading
import time
import uuid
import multiprocessing

OUTPUT_DIR = "output"


class RunManager:
    """Manages parallel search runs with process isolation."""

    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def new_run(self) -> dict:
        run_id = uuid.uuid4().hex[:8]
        entry = {
            "id":         run_id,
            "process":    None,
            "active":     True,
            "queued":     False,
            "log_queue":  queue.Queue(),
            "stop_event": threading.Event(),
            "params":     {},
            "files":      [],
            "count":      0,
            "cities":     [],
            "started_at": time.time(),
            "_done":      False,
        }
        with self._lock:
            self._runs[run_id] = entry
        return entry

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            return self._runs.get(run_id)

    def active_run_id(self) -> str | None:
        with self._lock:
            for rid, r in self._runs.items():
                if r["active"] and not r.get("queued"):
                    return rid
        return None

    def queue_position(self, run_id: str) -> int:
        pos = 1
        with self._lock:
            for rid, r in self._runs.items():
                if r.get("queued") and rid != run_id:
                    pos += 1
        return pos

    def finish_run(self, run_id: str):
        """Mark run done, start next queued run if any."""
        next_entry = None
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id]["active"] = False
            # Atomically find and claim the next queued run
            for rid, r in self._runs.items():
                if r.get("queued"):
                    r["queued"] = False
                    r["active"] = True
                    next_entry = r
                    break
            # Cleanup old finished runs (> 1 hour)
            now = time.time()
            to_remove = [rid for rid, r in self._runs.items()
                         if not r["active"] and not r.get("queued")
                         and now - r.get("started_at", 0) > 3600]
            for rid in to_remove:
                del self._runs[rid]
        if next_entry:
            self.start_process(next_entry)

    def start_process(self, entry: dict):
        """Start a search in a child process with bridge thread for SSE."""
        params   = entry["params"]
        run_id   = entry["id"]
        mp_queue = multiprocessing.Queue()

        stop_dir  = os.path.join(OUTPUT_DIR, ".run_stop")
        os.makedirs(stop_dir, exist_ok=True)
        stop_file = os.path.join(stop_dir, f"{run_id}.stop")

        from yandex_maps_parser.runner import run_process

        try:
            proc = multiprocessing.Process(
                target=run_process,
                args=(params, mp_queue, stop_file),
                daemon=True,
            )
            entry["process"] = proc
            entry["stop_file"] = stop_file
            proc.start()
        except Exception:
            # Fallback: run in a thread (no state isolation, but functional)
            self._start_thread_fallback(entry, mp_queue, stop_file)

        # Bridge thread: mp_queue → regular queue for SSE
        bridge = threading.Thread(
            target=_bridge_reader,
            args=(mp_queue, entry["log_queue"], entry),
            daemon=True,
        )
        bridge.start()

    def _start_thread_fallback(self, entry, mp_queue, stop_file):
        """Fallback: run search in a thread when multiprocessing fails."""
        import re
        import yandex_maps_parser as _parser

        _ansi_re = re.compile(r"\x1b\[[0-9;]*m")
        params = entry["params"]

        def _thread_run():
            try:
                stop_event = entry["stop_event"]
                files = _parser.run_web(params, lambda l, m: mp_queue.put(
                    {"type": "result", "data": json.loads(m)} if l == "result"
                    else {"type": "log", "level": l, "msg": _ansi_re.sub("", m)}
                ), stop_event)
                count = 0
                for f in files:
                    if f.endswith(".json"):
                        try:
                            with open(os.path.join(OUTPUT_DIR, f), encoding="utf-8") as jf:
                                count = len(json.load(jf))
                            break
                        except Exception:
                            pass
                fmts = []
                if params.get("output_csv"):   fmts.append("csv")
                if params.get("output_json"):  fmts.append("json")
                if params.get("output_excel"): fmts.append("xlsx")
                if params.get("output_map"):   fmts.append("map")
                mp_queue.put({"type": "done", "files": files, "count": count,
                              "stopped": stop_event.is_set(), "formats": fmts})
            except Exception as exc:
                try:
                    mp_queue.put({"type": "log", "level": "warn", "msg": f"Ошибка: {exc}"})
                    mp_queue.put({"type": "done", "files": [], "count": 0,
                                  "stopped": False, "formats": []})
                except Exception:
                    pass
            finally:
                try:
                    mp_queue.put(None)
                except Exception:
                    pass
                if stop_file:
                    try:
                        os.remove(stop_file)
                    except OSError:
                        pass

        t = threading.Thread(target=_thread_run, daemon=True)
        entry["_thread"] = t
        t.start()

    def stop_run(self, run_id: str = ""):
        """Stop a run by ID or the active run."""
        with self._lock:
            targets = []
            if run_id and run_id in self._runs:
                targets.append(self._runs[run_id])
            else:
                for r in self._runs.values():
                    if r["active"] and not r.get("queued"):
                        targets.append(r)
            for entry in targets:
                sf = entry.get("stop_file")
                if sf:
                    try:
                        with open(sf, "w") as f:
                            f.write("stop")
                    except Exception:
                        pass
                proc = entry.get("process")
                if proc and proc.is_alive():
                    proc.terminate()

    def list_runs(self) -> list[dict]:
        with self._lock:
            return [{
                "id":     r["id"],
                "active": r["active"],
                "queued": r.get("queued", False),
                "count":  r.get("count", 0),
                "cities": r.get("cities", []),
                "files":  r.get("files", []),
            } for r in self._runs.values()]

    def status(self) -> dict:
        active = self.active_run_id()
        queued = sum(1 for r in self._runs.values() if r.get("queued"))
        return {"active": active is not None, "active_run": active, "queued": queued}


# ── Singleton ─────────────────────────────────────────────────
run_manager = RunManager()


# ── Bridge thread helper ──────────────────────────────────────

def _bridge_reader(mp_queue, reg_queue, entry):
    """Read from multiprocessing.Queue, forward to regular Queue for SSE."""
    proc = entry.get("process")
    while True:
        try:
            msg = mp_queue.get(timeout=1.0)
            if msg is None:
                break
            reg_queue.put(msg)
        except queue.Empty:
            if proc and not proc.is_alive():
                while not mp_queue.empty():
                    try:
                        msg = mp_queue.get_nowait()
                        if msg is not None:
                            reg_queue.put(msg)
                    except queue.Empty:
                        break
                break
        except Exception:
            break
    entry["_done"] = True
    # Mark run as finished and start next queued run
    run_manager.finish_run(entry["id"])
