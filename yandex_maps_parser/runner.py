# runner.py
"""
Top-level entry points: run() for CLI and run_web() for the Flask interface.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from colorama import init as colorama_init
from tqdm import tqdm

from yandex_maps_parser import state
from yandex_maps_parser.checkpoint import (
    load_checkpoint, save_checkpoint, clear_checkpoint,
    load_global_seen, save_global_seen,
)
from yandex_maps_parser.enrichment import collect_candidates, enrich
from yandex_maps_parser.http_client import _worker_session, reset_stats
from yandex_maps_parser.exporters import (
    _resolve, load_existing_urls, load_jsonl, dedupe_records,
    save_csv, save_json, save_excel, save_map,
    _init_excel, _finalize_excel,
)
from yandex_maps_parser.geocoding import geocode_city, build_grid, build_grid_index
from yandex_maps_parser.stats import print_stats, print_limit_stats

colorama_init(autoreset=True)


def run() -> None:
    """
    Main parse loop — reads config from the `state` module so that
    run_web() can override settings before calling this function.
    """
    print()
    state.ok("╔══════════════════════════════════════════════════════════╗")
    state.ok("║   Яндекс.Карты — бизнесы без сайта + с соцсетями        ║")
    state.ok("╚══════════════════════════════════════════════════════════╝")
    state.info(f"  Запросы    : {', '.join(state.SEARCH_QUERIES)}")
    state.info(f"  Город      : {state.CITY}")
    state.info(
        f"  Сетка      : "
        f"{'да (%d км, шаг %d км)' % (state.GRID_RADIUS_KM, state.GRID_STEP_KM) if state.USE_GRID else 'нет'}"
    )
    state.info(
        f"  Потоки     : детали {state.MAX_WORKERS}  | "
        f"поиск {state.SEARCH_WORKERS}  | Retry: {state.RETRY_COUNT}x"
    )
    state.info(f"  Фильтры    : рейтинг ≥ {state.MIN_RATING}  |  отзывов ≥ {state.MIN_REVIEWS}")
    state.info(f"  Checkpoint : {'resume' if state.RESUME_MODE else 'с нуля'}")
    state.info(f"  Валидация  : {'да' if state.VALIDATE_SOCIALS else 'нет'}")
    state.info(
        f"  Прокси    : {len(state.PROXIES)} шт."
        if state.PROXIES else "  Прокси    : нет"
    )
    state.info(
        f"  Вывод      : "
        f"{'CSV ' if state.OUTPUT_CSV else ''}"
        f"{'JSON ' if state.OUTPUT_JSON else ''}"
        f"{'Excel ' if state.OUTPUT_EXCEL else ''}"
        f"{'Карта' if state.OUTPUT_MAP else ''}"
    )
    print()

    state.info(f"  Геокодирую «{state.CITY}»…")
    coords = geocode_city(state.CITY)
    envelope = None
    if coords:
        center_lat, center_lon, envelope = coords
        state.ok(f"  → {center_lat:.5f}, {center_lon:.5f}")
    else:
        center_lat, center_lon = 55.7558, 37.6173
        state.warn("Геокодинг не удался, использую координаты Москвы")

    grid_points = build_grid(center_lat, center_lon, envelope) if state.USE_GRID else [(center_lat, center_lon)]
    if state.USE_GRID:
        state.info(
            f"  Точек в сетке: {len(grid_points)}"
            + (" (по границам города)" if envelope else "")
        )

    if state.OUTPUT_FILENAME:
        base = state.OUTPUT_FILENAME
    else:
        slug = re.sub(r"[^\w]", "_", state.CITY).lower()
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{slug}_{ts}"

    paths = _resolve(base)

    state._reset_found()
    reset_stats()

    # Every enriched record is appended to the JSONL sidecar as it is found
    # (see state._emit_result), so a hard kill loses nothing already fetched.
    state._RESULT_FILE = paths["jsonl"]
    try:
        state._RESULT_HANDLE = open(paths["jsonl"], "a", encoding="utf-8")
    except Exception:
        state._RESULT_HANDLE = None

    # Start incremental Excel: create workbook with headers on first record
    if state.OUTPUT_EXCEL:
        state._EXCEL_APPEND_ENABLED = True
        try:
            _init_excel(paths["xlsx"])
        except Exception:
            state._EXCEL_APPEND_ENABLED = False
    else:
        state._EXCEL_APPEND_ENABLED = False

    ckpt       = load_checkpoint(base) if state.RESUME_MODE else {"seen_urls": set(), "completed": set()}
    seen_urls  = ckpt["seen_urls"]
    completed  = ckpt["completed"]

    # Never re-touch businesses already parsed in ANY earlier run.
    seen_urls |= load_global_seen()

    if state.APPEND_MODE:
        seen_urls |= load_existing_urls(paths["csv"])

    all_results:  list[dict] = []
    total_points = len(grid_points) * len(state.SEARCH_QUERIES)

    pbar_pts = tqdm(
        total=total_points, desc="Точки/запросы", unit="шт", position=0,
        colour="green", disable=state._TQDM_DISABLE,
    )
    pbar_search = tqdm(
        total=None, desc="  Поиск", unit="орг", position=1,
        colour="blue", leave=False, disable=state._TQDM_DISABLE,
    )
    pbar_detail = tqdm(
        total=0, desc="  Детали", unit="орг", position=2,
        colour="cyan", leave=False, disable=state._TQDM_DISABLE,
    )

    seen_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress_count = len(completed)

    grid_index = build_grid_index(grid_points) if state.USE_GRID else {}
    dead_points: dict[tuple[float, float], bool] = {}

    def mark_progress(query: str) -> None:
        nonlocal progress_count
        with progress_lock:
            progress_count += 1
            pbar_pts.update(1)
            state._progress(progress_count, total_points, query)

    def run_query(query: str):
        query_records: list[dict] = []
        processed_keys: list[tuple] = []
        search_session = _worker_session()

        batch_results: dict = {}
        batch_key: tuple | None = None
        batch_thread: threading.Thread | None = None

        def run_enrich_batch(cands, k) -> None:
            try:
                batch_results[k] = enrich(cands, pbar_detail, pool=detail_pool)
            except Exception as exc:
                state.warn(f"Ошибка загрузки деталей: {exc}")
                batch_results[k] = []

        def start_batch(key, candidates) -> None:
            nonlocal batch_key, batch_thread
            batch_key = key
            batch_thread = threading.Thread(
                target=run_enrich_batch, args=(candidates, key), daemon=True
            )
            batch_thread.start()

        for lat, lon in grid_points:
            if state._STOP_EVENT and state._STOP_EVENT.is_set():
                break

            key = (query, lat, lon)
            if key in completed:
                continue

            point_num = progress_count + 1

            nb = grid_index.get((lat, lon), {})
            known_nb = [n for n in (nb.get("up"), nb.get("left"), nb.get("up_left")) if n]
            if len(known_nb) >= 2 and all(dead_points.get(n) for n in known_nb):
                state.info(
                    f"  ↯ Точка {point_num}/{total_points} [{lat:.3f}, {lon:.3f}] "
                    f"пропущена — у соседей пусто"
                )
                processed_keys.append(key)
                mark_progress(query)
                continue

            if state.USE_GRID:
                state.info(
                    f"  📍 Точка {point_num}/{total_points} · «{query}» "
                    f"[{lat:.3f}, {lon:.3f}]"
                )
            else:
                state.info(f"  🔍 Ищу: «{query}» в {state.CITY}…")

            pbar_search.set_description(f"«{query}»")

            candidates, found, new_candidates = collect_candidates(
                query, state.CITY, lat, lon, seen_urls,
                pbar_search, pbar_detail, seen_lock=seen_lock,
                search_session=search_session,
            )

            dead_points[(lat, lon)] = bool(
                found is not None and (found == 0 or new_candidates == 0)
            )

            if batch_thread is not None:
                batch_thread.join()
                recs = batch_results.pop(batch_key, [])
                query_records.extend(recs)
                processed_keys.append(batch_key)
                mark_progress(query)

            start_batch(key, candidates)

        if batch_thread is not None:
            batch_thread.join()
            recs = batch_results.pop(batch_key, [])
            query_records.extend(recs)
            processed_keys.append(batch_key)
            mark_progress(query)

        return processed_keys, query_records

    pending_queries = [
        query for query in state.SEARCH_QUERIES
        if any((query, lat, lon) not in completed for lat, lon in grid_points)
    ]
    pbar_pts.update(len(completed))
    state._progress(len(completed), total_points, "")

    detail_pool = ThreadPoolExecutor(max_workers=state.MAX_WORKERS)

    try:
        if pending_queries:
            worker_count = min(state.SEARCH_WORKERS, len(pending_queries))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = {pool.submit(run_query, query): query for query in pending_queries}
                for future in as_completed(futures):
                    query = futures[future]
                    try:
                        processed_keys, records = future.result()
                    except Exception as exc:
                        state.warn(f"Ошибка в запросе «{query}»: {exc}")
                        continue

                    all_results.extend(records)
                    completed.update(processed_keys)
                    if records and state.OUTPUT_CSV:
                        save_csv(records, paths["csv"], append=True)

                    if processed_keys:
                        save_checkpoint(base, seen_urls, completed)
                        save_global_seen(seen_urls)

                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        break

        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            state.info("Остановлено пользователем.")

    except KeyboardInterrupt:
        state.warn("Прервано пользователем. Прогресс сохранён в checkpoint.")
    finally:
        detail_pool.shutdown(wait=True, cancel_futures=True)
        pbar_pts.close()
        pbar_search.close()
        pbar_detail.close()
        state._RESULT_FILE = None
        if state._RESULT_HANDLE is not None:
            try:
                state._RESULT_HANDLE.close()
            except Exception:
                pass
            state._RESULT_HANDLE = None
        save_global_seen(seen_urls)

    # Rebuild the full list from the crash-safe JSONL sidecar.
    jsonl_records = load_jsonl(paths["jsonl"])
    full_records  = dedupe_records(jsonl_records)
    if state.APPEND_MODE and os.path.exists(paths["json"]):
        try:
            with open(paths["json"], encoding="utf-8") as f:
                full_records = dedupe_records(json.load(f) + jsonl_records)
        except Exception:
            pass

    if state.OUTPUT_JSON and jsonl_records:
        try:
            save_json(full_records, paths["json"], append=False)
        except Exception:
            pass

    # Remove the JSONL sidecar
    try:
        if os.path.exists(paths["jsonl"]):
            os.remove(paths["jsonl"])
    except Exception:
        pass

    # Finalize Excel: add table, conditional formatting, legend/help/stats sheets
    if state.OUTPUT_EXCEL and state._EXCEL_APPEND_ENABLED:
        try:
            _finalize_excel(full_records or all_results)
        except Exception as exc:
            state.warn(f"Ошибка финализации Excel: {exc}")
            # Fallback: rebuild from scratch
            try:
                if full_records:
                    save_excel(full_records, paths["xlsx"])
            except Exception:
                pass
    elif state.OUTPUT_EXCEL and full_records:
        # CLI fallback (shouldn't normally happen)
        try:
            save_excel(full_records, paths["xlsx"])
        except Exception:
            pass

    state._EXCEL_APPEND_ENABLED = False

    if full_records:
        if state.OUTPUT_MAP:
            save_map(full_records, paths["map"], center_lat, center_lon)

    print_stats(all_results)
    print_limit_stats()

    state.ok(f"{'═' * 58}")
    state.ok(f"  Найдено записей : {len(all_results)}")
    if full_records:
        if state.OUTPUT_CSV:   state.ok(f"  CSV   → {paths['csv']}")
        if state.OUTPUT_JSON:  state.ok(f"  JSON  → {paths['json']}")
        if state.OUTPUT_EXCEL: state.ok(f"  Excel → {paths['xlsx']}")
        if state.OUTPUT_MAP:   state.ok(f"  Карта → {paths['map']}")

    if len(completed) == total_points:
        clear_checkpoint(base)
        state.info("  Checkpoint удалён (все точки обработаны).")

    state.ok(f"{'═' * 58}\n")

    if not full_records:
        state.info("  Подходящих записей не найдено.")
        state.info("  • Попробуйте другой запрос в config.py → SEARCH_QUERIES")
        state.info("  • Включите USE_GRID = True")
        state.info("  • Снизьте MIN_RATING / MIN_REVIEWS до 0")


def _apply_params(params: dict) -> None:
    """Apply form parameters to the global state module."""
    state.SEARCH_QUERIES  = [q.strip() for q in params.get("queries", []) if q.strip()]
    state.OUTPUT_CSV      = bool(params.get("output_csv", False))
    state.OUTPUT_JSON     = bool(params.get("output_json", False))
    state.OUTPUT_EXCEL    = bool(params.get("output_excel", True))
    state.OUTPUT_MAP      = bool(params.get("output_map", False))
    state.OUTPUT_FILENAME = None
    state.APPEND_MODE     = False
    state.RESUME_MODE     = False
    state.MIN_RATING      = float(params.get("min_rating", 0))
    state.MIN_REVIEWS     = int(params.get("min_reviews", 0))
    state.VALIDATE_SOCIALS = bool(params.get("validate_socials", False))
    state.USE_GRID        = bool(params.get("use_grid", False))
    state.GRID_RADIUS_KM  = int(params.get("grid_radius", 20))
    state.GRID_STEP_KM    = int(params.get("grid_step", 5))
    state.MAX_WORKERS     = max(1, int(params.get("max_workers", 20)))
    state.SEARCH_WORKERS  = max(1, min(5, int(params.get("query_workers", 2))))
    state.MAX_PAGES       = max(1, int(params.get("max_pages", 1)))
    state.FETCH_DETAIL    = bool(params.get("fetch_detail", True))
    state.SOCIAL_MODE      = params.get("social_mode", "all")
    # When user only wants businesses WITHOUT socials, skip expensive
    # detail-page fetching — we don't need social links at all.
    if state.SOCIAL_MODE == "without_socials":
        state.FETCH_DETAIL = False
    if params.get("api_key", "").strip():
        state.YANDEX_API_KEY = params["api_key"].strip()
    # Re-create semaphore to match the new MAX_WORKERS setting
    state._detail_semaphore = threading.Semaphore(state.MAX_WORKERS)


def _collect_run_files(started_at: float) -> list[str]:
    """Collect output files created after started_at."""
    result_files: list[str] = []
    if os.path.isdir(state.OUTPUT_DIR):
        for fname in sorted(os.listdir(state.OUTPUT_DIR)):
            fpath = os.path.join(state.OUTPUT_DIR, fname)
            if (
                os.path.isfile(fpath)
                and os.path.getmtime(fpath) >= started_at
                and not fname.startswith("_")
                and not fname.endswith(".checkpoint.json")
                and not fname.endswith(".jsonl")
            ):
                result_files.append(fname)
    return result_files


def run_web(params: dict, log_fn, stop_event=None) -> list[str]:
    """
    Run the parser with settings from the web form.
    Supports multi-city: if 'cities' list is provided, processes each
    city sequentially, creating separate files per city.

    params    — dict of settings from the browser form.
    log_fn    — callable(level: str, msg: str) for streaming logs to the browser.
    Returns a list of filenames (relative to OUTPUT_DIR) created during this run.
    """
    _apply_params(params)

    # Build city list: 'cities' takes priority, fallback to 'city' string
    raw_cities = params.get("cities", [])
    if not raw_cities:
        raw_cities = [params.get("city", state.CITY)]
    cities = [c.strip() for c in raw_cities if c.strip()]
    if not cities:
        cities = [state.CITY]

    all_files: list[str] = []
    total_cities = len(cities)

    state._LOG_FN        = log_fn
    state._TQDM_DISABLE  = True
    state._STOP_EVENT    = stop_event

    try:
        for city_idx, city in enumerate(cities):
            if stop_event and stop_event.is_set():
                break

            if total_cities > 1:
                state.info(
                    f"\n{'═' * 50}\n"
                    f"  🏙  Город {city_idx + 1}/{total_cities}: {city}\n"
                    f"{'═' * 50}"
                )
                # Signal city transition to frontend
                if log_fn:
                    log_fn("progress", f"city/{city_idx + 1}/{total_cities}/{city}")

            state.CITY = city
            started_at = time.time()
            run()

            # Collect files from this city run
            city_files = _collect_run_files(started_at)
            all_files.extend(city_files)

            if total_cities > 1 and city_files:
                state.ok(f"  ✅ {city}: {len(city_files)} файл(ов) сохранено")
    finally:
        state._LOG_FN       = None
        state._TQDM_DISABLE = False

    return all_files


# ── Multiprocessing entry point ─────────────────────────────

def run_process(params: dict, mp_queue, stop_file: str | None = None) -> None:
    """Entry point for a child process running a search.

    Each child process gets its own copy of state.py (via fork/spawn),
    so there are no conflicts between parallel searches.

    params     — search parameters (serializable).
    mp_queue   — multiprocessing.Queue for streaming logs/results.
    stop_file  — optional file path; if it exists, the run stops gracefully.
    """
    import threading as _threading

    # Create a stop event for this child process
    stop_event = _threading.Event()

    # Watch the stop file in a background thread
    if stop_file:
        def _watch_stop():
            while not stop_event.is_set():
                if os.path.exists(stop_file):
                    stop_event.set()
                    return
                import time as _t
                _t.sleep(0.5)
        _threading.Thread(target=_watch_stop, daemon=True).start()

    def _q_log(level: str, msg: str):
        """Log callback that puts messages into the multiprocessing queue."""
        try:
            if level == "result":
                mp_queue.put({"type": "result", "data": json.loads(msg)})
            else:
                mp_queue.put({"type": "log", "level": level, "msg": _strip_ansi(msg)})
        except Exception:
            pass

    try:
        files = run_web(params, _q_log, stop_event)
        # If multiple cities, merge all JSON files into a combined one
        # so the frontend can load all results at once for the map/stats.
        json_files = [f for f in files if f.endswith(".json") and "_combined" not in f]
        if len(json_files) > 1:
            combined = []
            for jf_name in json_files:
                try:
                    fpath = os.path.join(state.OUTPUT_DIR, jf_name)
                    with open(fpath, encoding="utf-8") as fh:
                        combined.extend(json.load(fh))
                except Exception:
                    pass
            if combined:
                combined_name = "_combined_results.json"
                combined_path = os.path.join(state.OUTPUT_DIR, combined_name)
                with open(combined_path, "w", encoding="utf-8") as fh:
                    json.dump(combined, fh, ensure_ascii=False, indent=2)
                files.insert(0, combined_name)
        count = 0
        for f in files:
            if f.endswith(".json"):
                try:
                    with open(os.path.join(state.OUTPUT_DIR, f), encoding="utf-8") as jf:
                        count = len(json.load(jf))
                    break
                except Exception:
                    pass
        # Build formats list
        fmts = []
        if params.get("output_csv"):   fmts.append("csv")
        if params.get("output_json"):  fmts.append("json")
        if params.get("output_excel"): fmts.append("xlsx")
        if params.get("output_map"):   fmts.append("map")
        mp_queue.put({"type": "done", "files": files, "count": count,
                      "stopped": stop_event.is_set(), "formats": fmts})
    except Exception as exc:
        try:
            mp_queue.put({"type": "log",  "level": "warn", "msg": f"Ошибка: {exc}"})
            mp_queue.put({"type": "done", "files": [], "count": 0,
                          "stopped": stop_event.is_set(), "formats": []})
        except Exception:
            pass
    finally:
        # Send sentinel so bridge thread knows we're done
        try:
            mp_queue.put(None)
        except Exception:
            pass
        # Clean up stop file if it exists
        if stop_file:
            try:
                os.remove(stop_file)
            except OSError:
                pass


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


if __name__ == "__main__":
    run()
