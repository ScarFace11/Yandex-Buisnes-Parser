"""Run state management: process lifecycle, queue bridging, run registry."""
import os
import json
import queue
import re
import threading
import time
import uuid
import urllib.request
import multiprocessing

# Writable dir: next to the .exe when frozen, project root from source
try:
    import paths as _paths
    OUTPUT_DIR = _paths.output_dir()        # служебные файлы (маркер, стоп-файл)
    RESULTS_DIR = str(_paths.results_root())  # куда пишутся результаты
except Exception:
    OUTPUT_DIR = "output"
    RESULTS_DIR = "output"

# Marker telling the web UI which search is «the current one»: the «Текущий результат» tab reads only the files written after started_at, so results of older searches stay in «История файлов» instead of leaking into the live table (and into «Массовый обход», which follows the same view).
_CURRENT_SEARCH_FILE = ".current_search.json"

# Silence before a process is presumed hung and force-killed (seconds).
_PROCESS_TIMEOUT = 900  # 15 minutes

# Delay before calling finish_run() after bridge exits.
_FINISH_DELAY = 6  # seconds: enough for a slow client to read done and close SSE

# Grace period for a graceful stop: after the stop file/event is set, the child is allowed this long to unwind (abort fetches, save checkpoint, finalize Excel, send "done") before a background thread force-kills it.
_STOP_GRACE_SEC = 8  # seconds
# A pause is a graceful stop the user WAITS on: the child must finish the checkpoint + Excel finalize and send its "done" (paused=true) message, or the UI would never offer «Продолжить».
_PAUSE_GRACE_SEC = 45  # seconds

# ── Жизнь записей в реестре прогонов ──────────────────────────
_RUN_TTL_S = 24 * 3600        # завершённые прогоны живут сутки
_MAX_FINISHED_RUNS = 100      # ... но не больше сотни завершённых за сессию
_MAX_PAUSED_RUNS = 20         # свежие паузы бережём для «Продолжить», старые — нет
_SWEEP_INTERVAL_S = 60        # чаще раза в минуту реестр не перебираем

# Compiled ANSI escape pattern for stripping colour codes from log lines
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ── API callback (webhook) ────────────────────────────────────
_CB_TIMEOUT_S = 10   # таймаут одного POST на callback_url
_CB_RETRIES = 2      # попыток доставки (с паузой между ними)
_CB_RETRY_DELAY_S = 1.0


def _pause_resume_payload(entry: dict) -> dict | None:
    """Data the frontend needs to continue a paused run later."""
    params = entry.get("params") or {}
    cities = params.get("cities") or []
    # Города, которые осталось обработать, начиная с ТЕКУЩЕГО: завершённые не должны перепрогоняться при «Продолжить», а недобранный город стартует заново без дублей (seen-cache пропускает уже спарсенное).
    remaining_cities: list = list(cities)
    pos = {}
    try:
        # The child owns the live position — the parent's state.py copy never sees update_pause_info(), so prefer the position cached from the child's own done message (set in _bridge_reader) and only fall back to the parent copy for the crash path.
        cached = entry.get("_position")
        if isinstance(cached, dict) and cached:
            pos = cached
        else:
            import yandex_maps_parser.state as _state
            pos = _state.pause_position()
        if cities and pos.get("city"):
            cur = pos.get("city")
            idx = next((i for i, c in enumerate(cities) if c == cur), None)
            if idx is not None:
                remaining_cities = cities[idx:]
    except Exception:
        pos = {}
    return {
        "queries": params.get("queries") or [],
        "all_cities": cities,
        # «Продолжить» гоняет только этот срез: старые города уже готовы.
        "remaining_cities": remaining_cities,
        "params": params,
        "run_id": entry.get("id"),
        "position": pos,
    }


class RunManager:
    """Manages parallel search runs with process isolation."""

    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0

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
            "finished_at": 0.0,      # 0 → прогон ещё не закончился
            # Ошибка раннера: отличает «сломалось» от «ничего не найдено» (см. _entry_status в routes/public_api.py).
            "error":      None,
            # Прогресс: заполняется мостом из сообщений городов (см. _forward).
            "cities_done": 0,
            "cities_total": 0,
            "records_so_far": 0,
            "_done":      False,
            "_run_mode":  "thread",   # "process" or "thread"
        }
        self._sweep()          # уборка реестра — до добавления новой записи
        with self._lock:
            self._runs[run_id] = entry
        return entry

    def _sweep(self) -> int:
        """Убрать из реестра старые записи прогонов; вернуть число удалённых. finish_run чистит только те прогоны, до которых дошёл, и лишь по сроку в 12 ч."""
        now = time.time()
        removed = 0
        with self._lock:
            if now - self._last_sweep < _SWEEP_INTERVAL_S:
                return 0            # реестр перебирается не чаще раза в минуту
            self._last_sweep = now

            def _idle(r: dict) -> bool:
                return not r.get("active") and not r.get("queued")

            # 1) По сроку жизни: всё завершённое старше _RUN_TTL_S.
            for rid in [rid for rid, r in self._runs.items()
                        if _idle(r) and not r.get("paused")
                        and now - r.get("started_at", 0) > _RUN_TTL_S]:
                del self._runs[rid]
                removed += 1
            # 2) Паузные: храним последние _MAX_PAUSED_RUNS штук.
            paused = sorted((kv for kv in self._runs.items()
                             if _idle(kv[1]) and kv[1].get("paused")),
                            key=lambda kv: kv[1].get("started_at", 0))
            for rid, _r in paused[:max(0, len(paused) - _MAX_PAUSED_RUNS)]:
                del self._runs[rid]
                removed += 1
            # 3) По количеству: самые старые завершённые сверх лимита (самая длинная сессия не должна растить реестр бесконечно).
            finished = sorted((kv for kv in self._runs.items()
                               if _idle(kv[1]) and not kv[1].get("paused")),
                              key=lambda kv: kv[1].get("started_at", 0))
            for rid, _r in finished[:max(0, len(finished) - _MAX_FINISHED_RUNS)]:
                del self._runs[rid]
                removed += 1
        return removed

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
        """Finalize a PAUSED run right now and return its id (else None)."""
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
        """Mark run done, start next queued run if any."""
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
            # Cleanup old finished runs.
            now = time.time()
            to_remove = [rid for rid, r in self._runs.items()
                         if not r["active"] and not r.get("queued")
                         and now - r.get("started_at", 0) > 43200]
            for rid in to_remove:
                del self._runs[rid]
        if next_entry:
            self.start_process(next_entry)

    def _mark_current_search(self, entry: dict) -> None:
        """Stamp the start of this search into output/.current_search.json."""
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
        # Домашняя уборка: файлы-сигналы запусков, убитых watchdog'ом, никто не удалял — они копились сотнями.
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
                    # msg is already a JSON string from _emit_result; parse it to get the dict for the frontend
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
                if pause_event.is_set():
                    stop_event.set()
                # pause_event MUST be handed to run_web: state._PAUSE_EVENT is what the closing lines and the done message read, and a fresh internal event would never be set by stop_run().
                _total_cities = len(params.get("cities") or [])
                if _total_cities:
                    mp_queue.put({"type": "progress", "cities_done": 0,
                                  "cities_total": _total_cities})
                files = _parser.run_web(params, _log_to_queue, stop_event, skip_event,
                                        pause_event)
                # Build the frontend-friendly merged JSON (english keys, all cities) so the results table and stats render correctly even when only Excel output was requested.
                try:
                    from yandex_maps_parser.exporters import write_frontend_json
                    ff = write_frontend_json(files, RESULTS_DIR, params.get("cities"))
                    if ff and ff not in files:
                        files.insert(0, ff)
                except Exception:
                    pass
                count = 0
                # Prefer the merged frontend file; fall back to any user json
                for f in files:
                    if f == "_results_for_frontend.json" or (f.endswith(".json") and not f.startswith("_")):
                        try:
                            with open(os.path.join(RESULTS_DIR, f), encoding="utf-8") as jf:
                                count = len(json.load(jf))
                            break
                        except Exception:
                            pass
                fmts = []
                if params.get("output_csv"):   fmts.append("csv")
                if params.get("output_json"):  fmts.append("json")
                if params.get("output_excel"): fmts.append("xlsx")
                if params.get("output_map"):   fmts.append("map")
                # CRITICAL: Send done to mp_queue so the bridge forwards it to the SSE endpoint BEFORE the sentinel.
                skipped = list(getattr(_parser.state, '_SKIPPED_CITIES', []))
                if _total_cities and not stop_event.is_set() and not pause_event.is_set():
                    mp_queue.put({"type": "progress", "cities_done": _total_cities,
                                  "cities_total": _total_cities,
                                  "records_so_far": count})
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
                    # Явная ошибка: мост пометит прогон failed, и клиент отличит «сломалось» от «ничего не найдено».
                    mp_queue.put({"type": "error", "message": str(exc)})
                    mp_queue.put({"type": "done", "files": [], "count": 0,
                                  "stopped": False, "paused": False,
                                  "error": str(exc),
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
                # The pause file too: a leftover one would pause the next run that reuses the same run_id path (resume reuses it).
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
        """Stop a run by ID or the active run; returns the affected run ids."""
        with self._lock:
            targets = []
            if run_id and run_id in self._runs:
                targets.append(self._runs[run_id])
            else:
                for r in self._runs.values():
                    if r["active"] and not r.get("queued"):
                        targets.append(r)
            for entry in targets:
                # A pause IS a graceful stop for the engine, but the two must stay distinguishable: the child runs TWO file watchers (`{run_id}.pause` and `{run_id}.stop`, each polling every 0.5 s).
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
                # Both events are shared objects in thread-fallback mode (the files are not watched there at all), so set them for a pause as well — only the flags decide what the UI is told.
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
                # Do NOT terminate() inline — that hard-kills the child before it can save its checkpoint / finalize Excel / send "done".
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
        # A PAUSED run stays out of `active_run` as soon as it is finalized, so the frontend had no way to learn about it after a page reload — the «Продолжить» button simply never appeared and users started a fresh search instead (and then reported that «пауза прекращает поиск»).
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

def _callback_payload(entry: dict) -> dict:
    """Итоги прогона для callback_url — те же поля, что отдаёт /api/v1/status."""
    stop_ev = entry.get("stop_event")
    pause_ev = entry.get("pause_event")
    was_paused = bool(entry.get("paused") or (pause_ev and pause_ev.is_set()))
    stopped = bool(stop_ev and stop_ev.is_set() and not was_paused)
    if entry.get("error"):
        status = "failed"          # упавший прогон — это не «done с нулём записей»
    elif was_paused:
        status = "paused"
    elif stopped:
        status = "stopped"
    else:
        status = "done"
    params = entry.get("params") or {}
    return {
        "event":      "run.finished",
        "run_id":     entry.get("id", ""),
        "status":     status,
        "count":      entry.get("count", 0),
        "files":      entry.get("files", []),
        "cities":     entry.get("cities", []),
        "started_at": entry.get("started_at", 0),
        "finished_at": time.time(),
        # Новые поля: клиент видит причину падения и прогресс, а не гадает по «count: 0».
        "error":      entry.get("error"),
        "progress":   {"cities_done":    int(entry.get("cities_done") or 0),
                       # Знаменатель берём из списка городов, если счётчик моста ещё не дошёл (прогон мог упасть до первого города).
                       "cities_total":   int(entry.get("cities_total") or 0)
                                         or len(entry.get("cities") or []),
                       "records_so_far": int(entry.get("records_so_far") or 0)},
        # Пакетный режим (/api/v1/batch): к какой пачке относится прогон.
        "batch_id":    params.get("batch_id"),
        "batch_index": params.get("batch_index"),
    }

def _post_callback(url: str, payload: dict) -> None:
    """POST JSON на callback_url; недоступность адреса — не ошибка прогона."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(_CB_RETRIES):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_CB_TIMEOUT_S) as resp:
                if 200 <= resp.status < 300:
                    return          # доставлено
                last_err = f"HTTP {resp.status}"
        except Exception as e:      # адрес недоступен / таймаут
            last_err = e
        if attempt + 1 < _CB_RETRIES:
            time.sleep(_CB_RETRY_DELAY_S)
    try:
        print(f"[api] callback не доставлен ({url}): {last_err}")
    except Exception:
        pass

def _apply_progress(entry: dict, data) -> None:
    """Обновить прогресс прогона: города и найденные записи."""
    if isinstance(data, dict):
        for key in ("cities_done", "cities_total", "records_so_far"):
            if data.get(key) is not None:
                try:
                    entry[key] = int(data[key])
                except (TypeError, ValueError):
                    pass
        if isinstance(data.get("cities"), list) and data["cities"]:
            entry["cities"] = data["cities"]
        return

    text = str(data or "")
    if text.startswith("city/"):
        parts = text.split("/")
        if len(parts) >= 3:
            try:
                # Текущий город ещё в работе — считаем только пройденные.
                entry["cities_done"] = max(0, int(parts[1]) - 1)
                entry["cities_total"] = int(parts[2])
            except (TypeError, ValueError):
                pass
    elif text.startswith("city_done|"):
        parts = text.split("|")
        if len(parts) >= 6:
            try:
                entry["cities_done"] = int(parts[1])
                entry["cities_total"] = int(parts[2])
                entry["records_so_far"] = int(entry.get("records_so_far") or 0) + int(parts[5])
            except (TypeError, ValueError):
                pass
    elif text.startswith("city_list|"):
        cities = [c for c in text.split("|", 1)[1].split("/") if c]
        if cities:
            entry["cities"] = cities


def _fire_api_callback(entry: dict) -> None:
    """Отправить итоги прогона на callback_url (если он задан) — в фоне."""
    url = str((entry.get("params") or {}).get("callback_url") or "").strip()
    if not url:
        return
    payload = _callback_payload(entry)
    threading.Thread(
        target=_post_callback, args=(url, payload),
        daemon=True, name=f"yp-callback-{entry.get('id', '')}",
    ).start()

def _offer(reg_queue, message) -> None:
    """Положить сообщение в очередь логов, не блокируясь на полной очереди.

    Интерфейс мог закрыться посреди прогона: блокирующий `put()` оставил бы
    нитку моста (и всё, что она держит) в памяти навсегда. Старые строки лога
    уже никто не прочитает — уступаем место свежей.
    """
    try:
        reg_queue.put_nowait(message)
        return
    except queue.Full:
        pass
    try:
        reg_queue.get_nowait()
    except queue.Empty:
        pass
    try:
        reg_queue.put_nowait(message)
    except queue.Full:
        pass


def _bridge_reader(mp_queue, reg_queue, entry):
    """Read from multiprocessing.Queue, forward to regular Queue for SSE."""
    mode = entry.get("_run_mode", "thread")
    proc = entry.get("process")
    thread = entry.get("_thread")
    empty_count = 0  # consecutive empty polls

    def _forward(m) -> None:
        """Forward one message; record a real done so the bridge never synthesises a second one (which used to arrive with stopped=False and empty files/formats and could report «Готово» for a real stop)."""
        if isinstance(m, dict):
            kind = m.get("type")
            if kind == "done":
                entry["_done"] = True
                entry["finished_at"] = time.time()
                # Итоги: файлы городов, всего записей, города прогона.
                if isinstance(m.get("files"), list):
                    entry["files"] = m["files"]
                if isinstance(m.get("cities"), list) and m["cities"]:
                    entry["cities"] = m["cities"]
                try:
                    entry["count"] = int(m.get("count") or 0)
                except (TypeError, ValueError):
                    pass
                if m.get("error"):
                    entry["error"] = str(m["error"])
                if m.get("paused"):
                    entry["paused"] = True
                _res = m.get("resume")
                if isinstance(_res, dict) and isinstance(_res.get("position"), dict):
                    entry["_position"] = _res["position"]   # for status() after reload
            elif kind == "error":
                # Явная ошибка раннера: прогон помечается failed, и клиент отличает «сломалось» от «ничего не найдено».
                entry["error"] = str(m.get("message") or m.get("error") or "unknown error")
                return
            elif kind == "progress":
                _apply_progress(entry, m)
            elif kind == "log" and m.get("level") == "progress":
                _apply_progress(entry, m.get("msg"))
        _offer(reg_queue, m)

    while True:
        try:
            msg = mp_queue.get(timeout=2.0)
            if msg is None:
                break  # sentinel — child is done
            entry["_last_msg"] = time.time()   # activity marker for the watchdog
            _forward(msg)
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
                            _forward(msg)
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
                            _forward(msg)
                    except queue.Empty:
                        break
                break

        except Exception:
            break

    entry["finished_at"] = entry.get("finished_at") or time.time()

    # CRASH SAFETY: If the producer died without sending a done message, send one now so the frontend gets a clean completion signal.
    if not entry.get("_done"):
        pause_ev = entry.get("pause_event")
        stop_ev = entry.get("stop_event")
        was_paused = bool(entry.get("paused") or (pause_ev and pause_ev.is_set()))
        # Mirror runner.run_process: a user-requested stop must not be reported as a clean «Готово» on the crash path.
        stopped = bool(stop_ev and stop_ev.is_set() and not was_paused)
        # Нормальный прогон ВСЕГДА отправляет done до сентинела.
        if not was_paused and not stopped:
            entry["error"] = entry.get("error") or (
                "run process ended without a done message (killed or crashed)")
        # The payload is built in its own try: a failure inside it must not cost the frontend the done message (and with it «Продолжить»).
        resume = None
        if was_paused:
            try:
                resume = _pause_resume_payload(entry)
            except Exception:
                resume = None
        _offer(reg_queue, {"type": "done", "files": entry.get("files", []),
                           "count": entry.get("count", 0),
                           "stopped": stopped, "paused": was_paused,
                           "resume": resume,
                           "formats": [], "skipped_cities": []})

    entry["_done"] = True

    # Уведомление для автоматизации (callback_url из /api/v1/search): прогон кончился — сообщаем об этом наружу, не заставляя опрашивать статус.
    try:
        _fire_api_callback(entry)
    except Exception:
        pass

    # CRITICAL: Delay finish_run() to give the frontend time to receive the done message and close the SSE connection.
    _rid = entry["id"]
    threading.Timer(_FINISH_DELAY, lambda: run_manager.finish_run(_rid)).start()


def _watchdog(entry):
    """Force-kill a process that has gone silent."""
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
