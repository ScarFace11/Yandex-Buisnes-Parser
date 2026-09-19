"""
Run state management: process lifecycle, queue bridging, run registry.

Each search runs in its own process (multiprocessing) for true isolation.
A bridge thread reads from the multiprocessing.Queue and forwards to a
regular queue.Queue that the SSE endpoint can consume with timeout.
"""
import os
import json
import queue
import re
import threading
import time
import uuid
import multiprocessing

# Writable dir: next to the .exe when frozen, project root from source
try:
    import paths as _paths
    OUTPUT_DIR = _paths.output_dir()
except Exception:
    OUTPUT_DIR = "output"

# Marker telling the web UI which search is «the current one»: the
# «Текущий результат» tab reads only the files written after started_at, so
# results of older searches stay in «История файлов» instead of leaking into
# the live table (and into «Массовый обход», which follows the same view).
_CURRENT_SEARCH_FILE = ".current_search.json"

# Max time a process can run before we force-kill it (seconds)
_PROCESS_TIMEOUT = 600  # 10 minutes

# Delay before calling finish_run() after bridge exits.
# Gives the frontend time to receive the done message and close the
# SSE connection before a new queued run starts writing to the same queue.
_FINISH_DELAY = 3  # seconds

# Grace period for a graceful stop: after the stop file/event is set, the
# child is allowed this long to unwind (abort fetches, save checkpoint,
# finalize Excel, send "done") before a background thread force-kills it.
_STOP_GRACE_SEC = 8  # seconds
# A pause is a graceful stop the user WAITS on: the child must finish the
# checkpoint + Excel finalize and send its "done" (paused=true) message, or
# the UI would never offer «Продолжить». In-flight detail fetches can take
# tens of seconds, so a pause gets a longer grace than a plain stop.
_PAUSE_GRACE_SEC = 45  # seconds

# Compiled ANSI escape pattern for stripping colour codes from log lines
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _pause_resume_payload(entry: dict) -> dict | None:
    """Data the frontend needs to continue a paused run later.

    Returned inside the done message: queries + the cities that were NOT
    finished yet + WHERE the search stopped (city/query/point) + how much of
    the free-tier quota this run already spent. The global seen-URL cache and
    the per-run checkpoint make the resumed pass skip everything already
    parsed, so no duplicates.
    """
    params = entry.get("params") or {}
    cities = params.get("cities") or []
    # Города, которые осталось обработать, начиная с ТЕКУЩЕГО: завершённые
    # не должны перепрогоняться при «Продолжить», а недобранный город
    # стартует заново без дублей (seen-cache пропускает уже спарсенное).
    remaining_cities: list = list(cities)
    try:
        import yandex_maps_parser.state as _state
        pos = _state.pause_position()
        if cities and pos.get("city"):
            cur = pos.get("city")
            idx = next((i for i, c in enumerate(cities) if c == cur), None)
            if idx is not None:
                remaining_cities = cities[idx:]
        quota = None
        if (params.get("source") or "yandex") == "twogis":
            from yandex_maps_parser import twogis as _tg
            used = _tg.quota_used()
            quota = {"used": used, "cap": _tg.quota_cap(),
                     "spent_this_run": _tg.quota_spent_this_run()}
    except Exception:
        pos = {}
        quota = None
    return {
        "queries": params.get("queries") or [],
        "all_cities": cities,
        # «Продолжить» гоняет только этот срез: старые города уже готовы.
        "remaining_cities": remaining_cities,
        "params": params,
        "run_id": entry.get("id"),
        "position": pos,
        "quota": quota,
    }


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
            "log_queue":  queue.Queue(maxsize=5000),
            "stop_event": threading.Event(),
            "skip_event": threading.Event(),
            "pause_event": threading.Event(),
            "skip_file":  None,
            "pause_file": None,
            "paused":     False,
            "params":     {},
            "files":      [],
            "count":      0,
            "cities":     [],
            "started_at": time.time(),
            "_done":      False,
            "_run_mode":  "thread",   # "process" or "thread"
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

    def is_paused(self, run_id: str) -> bool:
        """True when the run exists and the user paused it."""
        with self._lock:
            r = self._runs.get(run_id)
            return bool(r and r.get("paused"))

    def clear_paused_run(self, run_id: str = "") -> str | None:
        """Finalize a PAUSED run right now and return its id (else None).

        «Продолжить» sends a fresh /run while the paused run may still be
        marked active — finish_run() only fires _FINISH_DELAY seconds after
        the done message. Without this the resume was pushed into the QUEUE
        behind a run that is never started again (finish_run skips the queue
        for a paused run), and the SSE stream (/logs without run_id) kept
        pointing at the dead paused run — so the search never resumed.

        The paused child has already sent its "done" (that is how the user
        got the «Продолжить» button); we give it a moment to exit so its last
        checkpoint/Excel writes can't collide with the resumed run.
        """
        target = run_id or self.active_run_id() or ""
        if not target:
            return None
        entry = self.get(target)
        if not entry or not entry.get("paused"):
            return None
        proc = entry.get("process")
        if proc is not None:
            try:
                proc.join(timeout=2.0)
            except Exception:
                pass
        self.finish_run(target)
        return target

    def queue_position(self, run_id: str) -> int:
        pos = 1
        with self._lock:
            for rid, r in self._runs.items():
                if r.get("queued") and rid != run_id:
                    pos += 1
        return pos

    def finish_run(self, run_id: str):
        """Mark run done, start next queued run if any.

        A PAUSED run keeps entry["paused"]=True so the frontend can offer
        «Продолжить»; queued runs are NOT autostarted after a pause —
        finishing a paused run must not silently launch the next search
        while the user believes everything is on hold.
        """
        next_entry = None
        was_paused = False
        with self._lock:
            if run_id in self._runs:
                was_paused = bool(self._runs[run_id].get("paused"))
                self._runs[run_id]["active"] = False
            # Atomically find and claim the next queued run (not after a pause)
            if not was_paused:
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

    def _mark_current_search(self, entry: dict) -> None:
        """Stamp the start of this search into output/.current_search.json.

        Written for every run that actually starts (queued ones are stamped
        when their turn comes), so a page reload or an app restart keeps
        «Текущий результат» pointing at the same search.
        """
        payload = {
            "run_id":     entry.get("id"),
            "started_at": time.time(),
            "cities":     entry.get("cities") or [],
            "queries":    (entry.get("params") or {}).get("queries") or [],
        }
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            path = os.path.join(OUTPUT_DIR, _CURRENT_SEARCH_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass   # the UI falls back to the whole folder when unmarked

    def start_process(self, entry: dict):
        """Start a search in a child process (or thread fallback) with bridge."""
        params   = entry["params"]
        run_id   = entry["id"]
        self._mark_current_search(entry)
        mp_queue = multiprocessing.Queue()

        stop_dir  = os.path.join(OUTPUT_DIR, ".run_stop")
        os.makedirs(stop_dir, exist_ok=True)
        stop_file = os.path.join(stop_dir, f"{run_id}.stop")
        entry["stop_file"] = stop_file
        skip_file = os.path.join(stop_dir, f"{run_id}.skip")
        entry["skip_file"] = skip_file
        pause_file = os.path.join(stop_dir, f"{run_id}.pause")
        entry["pause_file"] = pause_file
        # Домашняя уборка: файлы-сигналы запусков, убитых watchdog'ом, никто
        # не удалял — они копились сотнями. Чистим старше суток.
        try:
            now = time.time()
            for _name in os.listdir(stop_dir):
                _p = os.path.join(stop_dir, _name)
                if os.path.isfile(_p) and now - os.path.getmtime(_p) > 86400:
                    os.remove(_p)
        except Exception:
            pass

        # Try multiprocessing first
        used_process = False
        try:
            from yandex_maps_parser.runner import run_process
            proc = multiprocessing.Process(
                target=run_process,
                args=(params, mp_queue, stop_file, skip_file, pause_file),
                daemon=True,
            )
            proc.start()
            entry["process"] = proc
            entry["_run_mode"] = "process"
            used_process = True
        except Exception:
            # Fallback: run in a thread (no state isolation, but functional)
            entry["process"] = None   # CRITICAL: clear so bridge uses sentinel
            entry["_run_mode"] = "thread"
            self._start_thread_fallback(entry, mp_queue, stop_file)

        # Bridge thread: mp_queue → regular queue for SSE
        bridge = threading.Thread(
            target=_bridge_reader,
            args=(mp_queue, entry["log_queue"], entry),
            daemon=True,
        )
        bridge.start()

        # Watchdog: force-kill process if it runs too long
        if used_process:
            watchdog = threading.Thread(
                target=_watchdog,
                args=(entry,),
                daemon=True,
            )
            watchdog.start()

    def _start_thread_fallback(self, entry, mp_queue, stop_file):
        """Fallback: run search in a thread when multiprocessing fails."""
        import yandex_maps_parser as _parser

        params = entry["params"]

        def _log_to_queue(level: str, msg: str):
            """Log callback that puts messages into the multiprocessing queue."""
            try:
                clean = _ANSI_RE.sub("", msg)
                if level == "result":
                    # msg is already a JSON string from _emit_result;
                    # parse it to get the dict for the frontend
                    mp_queue.put({"type": "result", "data": json.loads(clean)})
                else:
                    mp_queue.put({"type": "log", "level": level, "msg": clean})
            except Exception:
                pass

        def _thread_run():
            try:
                stop_event = entry["stop_event"]
                skip_event = entry["skip_event"]
                pause_event = entry.get("pause_event") or threading.Event()
                # A pause is a graceful stop that REMEMBERS the run params:
                # run_web unwinds through the same checkpoint path as stop.
                if pause_event.is_set():
                    stop_event.set()
                # pause_event MUST be handed to run_web: state._PAUSE_EVENT is
                # what the closing lines and the done message read, and a fresh
                # internal event would never be set by stop_run().
                files = _parser.run_web(params, _log_to_queue, stop_event, skip_event,
                                        pause_event)
                # Build the frontend-friendly merged JSON (english keys, all
                # cities) so the results table and stats render correctly even
                # when only Excel output was requested. If per-city JSON files
                # exist they are merged directly; otherwise xlsx is read back
                # with header labels converted to english field keys.
                try:
                    from yandex_maps_parser.exporters import write_frontend_json
                    ff = write_frontend_json(files, OUTPUT_DIR, params.get("cities"))
                    if ff and ff not in files:
                        files.insert(0, ff)
                except Exception:
                    pass
                count = 0
                # Prefer the merged frontend file; fall back to any user json
                for f in files:
                    if f == "_results_for_frontend.json" or (f.endswith(".json") and not f.startswith("_")):
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
                # CRITICAL: Send done to mp_queue so the bridge forwards it
                # to the SSE endpoint BEFORE the sentinel. The bridge will
                # exit after seeing the sentinel, and the SSE endpoint will
                # deliver the done message to the frontend.
                # This is the ONLY place done is sent for normal completion.
                skipped = list(getattr(_parser.state, '_SKIPPED_CITIES', []))
                mp_queue.put({"type": "done", "files": files, "count": count,
                              "stopped": stop_event.is_set() and not pause_event.is_set(),
                              "paused": pause_event.is_set(),
                              # True → ничего нового: всё уже было спарсено раньше
                              "all_seen": bool(getattr(_parser.state, "_ALL_ALREADY_SEEN", False)),
                              "resume": _pause_resume_payload(entry),
                              "formats": fmts,
                              "skipped_cities": skipped})
            except Exception as exc:
                import traceback
                tb = traceback.format_exc()
                try:
                    mp_queue.put({"type": "log", "level": "warn",
                                  "msg": f"Ошибка: {exc}\n{tb}"})
                    mp_queue.put({"type": "done", "files": [], "count": 0,
                                  "stopped": False, "paused": False,
                                  "resume": None, "formats": []})
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
                skip_f = entry.get("skip_file")
                if skip_f:
                    try:
                        os.remove(skip_f)
                    except OSError:
                        pass
                # The pause file too: a leftover one would pause the next run
                # that reuses the same run_id path (resume reuses it).
                pause_f = entry.get("pause_file")
                if pause_f:
                    try:
                        os.remove(pause_f)
                    except OSError:
                        pass

        t = threading.Thread(target=_thread_run, daemon=True)
        entry["_thread"] = t
        t.start()

    def stop_run(self, run_id: str = "", pause: bool = False) -> list[str]:
        """Stop a run by ID or the active run; returns the affected run ids.

        With pause=True the run unwinds the same graceful way but the entry
        keeps its params and gets paused=True — the frontend then offers
        «Продолжить» instead of treating it as a finished search.

        GRACEFUL FIRST: the stop event/file is set and the run is allowed to
        unwind on its own (the in-process stop checks now abort detail
        fetches within ~1-3s, so a graceful stop is fast). Only if the child
        process is still alive after _STOP_GRACE_SEC does a background thread
        force-kill it. This preserves the final checkpoint/Excel writes and
        lets the child send its "done" message with real file list.
        """
        with self._lock:
            targets = []
            if run_id and run_id in self._runs:
                targets.append(self._runs[run_id])
            else:
                for r in self._runs.values():
                    if r["active"] and not r.get("queued"):
                        targets.append(r)
            for entry in targets:
                # A pause IS a graceful stop for the engine, but the two must
                # stay distinguishable: the child runs TWO file watchers
                # (`{run_id}.pause` and `{run_id}.stop`, each polling every
                # 0.5 s). Writing BOTH files for a pause made the outcome a
                # coin flip — when the stop watcher fired first, the child's
                # `state._PAUSE_EVENT` was never set and the engine unwound as
                # a plain stop: no «Продолжить», the search was simply over.
                # Now a pause writes ONLY the pause file; the child's pause
                # watcher (runner.run_process._watch_pause) sets both of ITS
                # events, so the unwind is graceful and remembered.
                if pause:
                    entry["paused"] = True
                    pf = entry.get("pause_file")
                    if pf:
                        try:
                            with open(pf, "w") as f:
                                f.write("pause")
                        except Exception:
                            pass
                else:
                    sf = entry.get("stop_file")
                    if sf:
                        try:
                            with open(sf, "w") as f:
                                f.write("stop")
                        except Exception:
                            pass
                # Both events are shared objects in thread-fallback mode (the
                # files are not watched there at all), so set them for a pause
                # as well — only the flags decide what the UI is told.
                pev = entry.get("pause_event") if pause else None
                if pev:
                    try:
                        pev.set()
                    except Exception:
                        pass
                stop_ev = entry.get("stop_event")
                if stop_ev:
                    try:
                        stop_ev.set()
                    except Exception:
                        pass
                # Do NOT terminate() inline — that hard-kills the child before
                # it can save its checkpoint / finalize Excel / send "done".
                # Escalate in the background only if it doesn't exit on its own.
                proc = entry.get("process")
                if proc and proc.is_alive():
                    _grace = _PAUSE_GRACE_SEC if pause else _STOP_GRACE_SEC

                    def _escalate(proc=proc, _grace=_grace):
                        try:
                            proc.join(timeout=_grace)
                        except Exception:
                            pass
                        if proc.is_alive():
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            try:
                                proc.join(timeout=3)
                            except Exception:
                                pass
                            if proc.is_alive():
                                try:
                                    proc.kill()
                                except Exception:
                                    pass
                    threading.Thread(target=_escalate, daemon=True).start()
            return [e["id"] for e in targets]

    def skip_city(self, run_id: str = ""):
        """Skip the current city in the active run."""
        with self._lock:
            targets = []
            if run_id and run_id in self._runs:
                targets.append(self._runs[run_id])
            else:
                for r in self._runs.values():
                    if r["active"] and not r.get("queued"):
                        targets.append(r)
            for entry in targets:
                # Signal thread fallback to skip city
                skip_ev = entry.get("skip_event")
                if skip_ev:
                    skip_ev.set()
                # Create skip file for multiprocessing mode
                sf = entry.get("skip_file")
                if sf:
                    try:
                        with open(sf, "w") as f:
                            f.write("skip")
                    except Exception:
                        pass

    def skip_city_info(self, run_id: str = "") -> dict:
        """Get info about the current city (records found so far)."""
        import yandex_maps_parser.state as _state
        with _state._city_records_lock:
            records = _state._CITY_RECORDS_FOUND
        return {
            "city": _state.CITY,
            "records_found": records,
        }

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
        # A PAUSED run stays out of `active_run` as soon as it is finalized, so
        # the frontend had no way to learn about it after a page reload — the
        # «Продолжить» button simply never appeared and users started a fresh
        # search instead (and then reported that «пауза прекращает поиск»).
        # The newest paused entry travels with the status so the dock can
        # restore itself. Its params/resume payload come from the same builder
        # the done message uses.
        paused = None
        with self._lock:
            entries = sorted(self._runs.values(),
                             key=lambda r: r.get("started_at", 0), reverse=True)
        for r in entries:
            if r.get("paused"):
                try:
                    paused = {"run_id": r.get("id"),
                              "resume": _pause_resume_payload(r)}
                except Exception:
                    paused = {"run_id": r.get("id"), "resume": None}
                break
        return {"active": active is not None, "active_run": active,
                "queued": queued, "paused": paused}


# ── Singleton ─────────────────────────────────────────────────
run_manager = RunManager()


# ── Bridge thread helper ──────────────────────────────────────

def _bridge_reader(mp_queue, reg_queue, entry):
    """Read from multiprocessing.Queue, forward to regular Queue for SSE.

    Exits when:
    - Child sends None sentinel (normal completion)
    - Child process/thread dies and queue is drained (crash)
    - Exception occurs

    CRITICAL DESIGN:
    - The done message is ONLY sent when the producer is confirmed dead
      (crash case). For normal completion, the producer itself sends
      the done message before the sentinel.
    - finish_run() is delayed by _FINISH_DELAY seconds after the bridge
      exits. This gives the frontend time to receive the done message
      and close the SSE connection before a new queued run starts.
    """
    mode = entry.get("_run_mode", "thread")
    proc = entry.get("process")
    thread = entry.get("_thread")
    empty_count = 0  # consecutive empty polls

    while True:
        try:
            msg = mp_queue.get(timeout=2.0)
            if msg is None:
                break  # sentinel — child is done
            entry["_last_msg"] = time.time()   # activity marker for the watchdog
            reg_queue.put(msg)
            empty_count = 0
        except queue.Empty:
            empty_count += 1
            # Check if the producer is still alive
            alive = False
            if mode == "process" and proc:
                alive = proc.is_alive()
            elif mode == "thread" and thread:
                alive = thread.is_alive()
            else:
                # Unknown mode — assume alive until sentinel
                alive = True

            if not alive:
                # Producer died — drain any remaining messages and exit
                while not mp_queue.empty():
                    try:
                        msg = mp_queue.get_nowait()
                        if msg is not None:
                            reg_queue.put(msg)
                    except queue.Empty:
                        break
                break

            # Safety: if idle for >60s with no sentinel, something is wrong
            if empty_count >= 30:
                # Drain remaining messages
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

    # CRASH SAFETY: If the producer died without sending a done message,
    # send one now so the frontend gets a clean completion signal. A PAUSED
    # run keeps its paused flag + resume payload here: a hard-killed child
    # never sent its own "done", and without this the user would see a plain
    # «завершено» and lose the «Продолжить» button after waiting for a pause.
    if not entry.get("_done"):
        was_paused = bool(entry.get("paused"))
        # The payload is built in its own try: a failure inside it must not
        # cost the frontend the done message (and with it «Продолжить»).
        resume = None
        if was_paused:
            try:
                resume = _pause_resume_payload(entry)
            except Exception:
                resume = None
        try:
            reg_queue.put({"type": "done", "files": entry.get("files", []),
                           "count": entry.get("count", 0),
                           "stopped": False, "paused": was_paused,
                           "resume": resume,
                           "formats": [], "skipped_cities": []})
        except Exception:
            pass

    entry["_done"] = True

    # CRITICAL: Delay finish_run() to give the frontend time to receive
    # the done message and close the SSE connection. Without this delay,
    # a queued run could start and write to the same SSE queue before
    # the frontend disconnects, causing results to be lost.
    _rid = entry["id"]
    threading.Timer(_FINISH_DELAY, lambda: run_manager.finish_run(_rid)).start()


def _watchdog(entry):
    """Force-kill a process that has gone silent.

    This is a STALL detector, not a wall-clock runtime limit: a healthy long
    run (e.g. continuation mode across many cities) keeps emitting messages
    through the bridge, which refreshes entry["_last_msg"]. Only when the
    child has produced nothing for _PROCESS_TIMEOUT seconds is it presumed
    hung and terminated.
    """
    while True:
        time.sleep(5)
        if entry.get("_done"):
            break
        last_activity = entry.get("_last_msg", entry["started_at"])
        if time.time() - last_activity > _PROCESS_TIMEOUT:
            proc = entry.get("process")
            if proc and proc.is_alive():
                try:
                    proc.terminate()
                except Exception:
                    pass
            break
