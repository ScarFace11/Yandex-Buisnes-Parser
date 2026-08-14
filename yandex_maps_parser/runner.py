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

import sys
from pathlib import Path

# Добавляем корневую папку в путь
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Теперь импортируем как из пакета
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

    # Each query gets its own worker and HTTP session. Detail fetching still
    # uses the shared semaphore, so query parallelism cannot exceed the
    # configured detail-request limit.
    seen_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress_count = len(completed)

    # Adaptive grid: a point is skipped without a request when >= 2 of its
    # already-visited neighbours (up / left / up-left) were empty — either
    # the API reported `found == 0` there, or everything was already seen
    # (zero new candidates). Unknown neighbours never block a probe.
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

        # Producer/consumer pipeline: the current point's SEARCH runs while the
        # PREVIOUS point's detail-fetch thread is still busy, so the Search API
        # no longer idles during the (much slower) detail phase.
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

            # ── Adaptive skip: neighbours all empty → don't query this point ──
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

            # ── Producer: search this point (fast) ──
            candidates, found, new_candidates = collect_candidates(
                query, state.CITY, lat, lon, seen_urls,
                pbar_search, pbar_detail, seen_lock=seen_lock,
                search_session=search_session,
            )

            # Mark empty immediately — neighbours' skip checks depend on it.
            # found == None (API error) → alive, no cascade of false skips.
            dead_points[(lat, lon)] = bool(
                found is not None and (found == 0 or new_candidates == 0)
            )

            # ── Consumer: drain the PREVIOUS point's details. Its thread was
            # running while we searched this point — join it now. ──
            if batch_thread is not None:
                batch_thread.join()
                recs = batch_results.pop(batch_key, [])
                query_records.extend(recs)
                processed_keys.append(batch_key)
                mark_progress(query)

            # ── Start this point's detail phase in the background. ──
            start_batch(key, candidates)

        # Drain the last point's details (also on stop).
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

    # One detail-fetch pool for the whole run: worker threads (and their
    # per-thread HTTP sessions / TLS connections) survive across grid points.
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

                    # Records already stream to the JSONL sidecar via
                    # _emit_result; persist the checkpoint after each query
                    # so resume stays reliable without concurrent writes.
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
        detail_pool.shutdown(wait=True)
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

    # Rebuild the full list from the crash-safe JSONL sidecar. APPEND_MODE
    # merges with the previous JSON; duplicates are removed in both cases.
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

    # The sidecar is fully merged — remove it so it doesn't linger in listings.
    try:
        if os.path.exists(paths["jsonl"]):
            os.remove(paths["jsonl"])
    except Exception:
        pass

    if full_records:
        if state.OUTPUT_EXCEL:
            save_excel(full_records, paths["xlsx"])
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


def run_web(params: dict, log_fn, stop_event=None) -> list[str]:
    """
    Run the parser with settings from the web form.

    params    — dict of settings from the browser form.
    log_fn    — callable(level: str, msg: str) for streaming logs to the browser.
    Returns a list of filenames (relative to OUTPUT_DIR) created during this run.
    """
    # Override state with form parameters
    state.SEARCH_QUERIES  = [q.strip() for q in params.get("queries", []) if q.strip()]
    state.CITY            = params.get("city", state.CITY).strip() or state.CITY
    state.OUTPUT_CSV      = bool(params.get("output_csv", False))
    state.OUTPUT_JSON     = True   # always save JSON so we can list result files
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
    if params.get("api_key", "").strip():
        state.YANDEX_API_KEY = params["api_key"].strip()

    # Re-create semaphore to match the new MAX_WORKERS setting
    state._detail_semaphore = threading.Semaphore(state.MAX_WORKERS)

    state._LOG_FN        = log_fn
    state._TQDM_DISABLE  = True
    state._STOP_EVENT    = stop_event

    started_at = time.time()
    try:
        run()
    finally:
        state._LOG_FN       = None
        state._TQDM_DISABLE = False

    # Collect files written during this run
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


if __name__ == "__main__":
    run()
