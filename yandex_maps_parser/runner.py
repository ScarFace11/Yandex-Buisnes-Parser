# runner.py
"""Top-level entry points: run() for CLI and run_web() for the Flask interface."""
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
from yandex_maps_parser.http_client import reset_stats
from yandex_maps_parser import cdp_client
from yandex_maps_parser.exporters import (
    _resolve, load_existing_urls, load_jsonl, dedupe_records,
    save_csv, save_json, save_excel, save_map,
    _init_excel, _finalize_excel, apply_output_filters,
)
from yandex_maps_parser.geocoding import geocode_city, build_grid, build_grid_index
from yandex_maps_parser.stats import print_stats, print_limit_stats

colorama_init(autoreset=True)


def _console_print(*args, **kwargs) -> None:
    """print() that never raises."""
    try:
        print(*args, **kwargs)
    except (OSError, ValueError):
        pass

# Start memory tracking for analytics (if available)
try:
    import tracemalloc
    if not tracemalloc.is_tracing():
        tracemalloc.start()
except ImportError:
    pass


def run() -> None:
    """Main parse loop — reads config from the `state` module so that run_web() can override settings before calling this function."""
    # File-only: full config dump for developer trace
    state.syslog(f"run() start: city={state.CITY}")
    state.syslog(f"  queries={state.SEARCH_QUERIES}")
    state.syslog(f"  grid: enabled={state.USE_GRID}, radius={state.GRID_RADIUS_KM}km, step={state.GRID_STEP_KM}km")
    state.syslog(f"  workers: detail={state.MAX_WORKERS}, search={state.SEARCH_WORKERS}, retry={state.RETRY_COUNT}")
    state.syslog(f"  checkpoint: {'resume' if state.RESUME_MODE else 'fresh'}")
    state.syslog(f"  proxies={len(state.PROXIES)}")
    state.syslog(f"  output: csv={state.OUTPUT_CSV}, json={state.OUTPUT_JSON}, excel={state.OUTPUT_EXCEL}, map={state.OUTPUT_MAP}")
    state.syslog(f"  social_mode={state.SOCIAL_MODE}, fetch_detail={state.FETCH_DETAIL}")
    state.syslog(f"  source={state.SOURCE}")

    # Web: minimal user-facing header (guarded — a broken Windows console handle must never kill the run, see _console_print).
    _console_print()
    state.info(f"  🔍 Поиск в «{state.CITY}» — запросы: {', '.join(state.SEARCH_QUERIES)}")
    state.info("  🗺  Источник: Яндекс.Карты")

    state.info(f"  Геокодирую «{state.CITY}»…")
    coords = geocode_city(state.CITY)
    envelope = None
    if coords:
        center_lat, center_lon, envelope = coords
        # Откуда взялись координаты: из офлайн-справочника или с карты (для городов вне каталога).
        try:
            from .city_coords import lookup as _coord_lookup
            _coord_src = "справочник городов" if _coord_lookup(state.CITY) else "карта"
        except Exception:
            _coord_src = ""
        state.ok(f"  → {center_lat:.5f}, {center_lon:.5f}"
                 + (f" ({_coord_src})" if _coord_src else ""))
    else:
        # Город не опознан.
        center_lat, center_lon = None, None
        state.warn(f"  Координаты «{state.CITY}» не найдены — ищу по названию "
                   "города в запросе (без сетки точек)")

    # Сетка имеет смысл только с координатами: без них среди точек нечего перебирать, а в логе появились бы «None» вместо широты.
    use_grid = bool(state.USE_GRID and center_lat is not None)
    if state.USE_GRID and not use_grid:
        state.info("  🗺  Сетка точек пропущена: у города нет координат")
    grid_points = build_grid(center_lat, center_lon, envelope) if use_grid \
        else [(center_lat, center_lon)]
    state.syslog(f"grid_points: {len(grid_points)}, envelope={'yes' if envelope else 'no'}")

    if state.OUTPUT_FILENAME:
        base = state.OUTPUT_FILENAME
    else:
        slug = re.sub(r"[^\w]", "_", state.CITY).lower()
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{slug}_{ts}"

    # Resume needs a STABLE checkpoint key across separate runs — the output base is timestamped, so a fresh run would never find the checkpoint.
    ckpt_key = f"{slug}_resume" if state.RESUME_MODE else base

    paths = _resolve(base)

    state._reset_found()
    # NOTE: pause position (city) is NOT reset here — run() is called per city from run_web's city loop, which has already set the current city.
    state.update_pause_info(query="", point=0, points_total=0)
    reset_stats()
    # Счётчики кэша страниц — тоже на прогон (см. stats.print_limit_stats).
    try:
        from .cache import reset_stats as _reset_cache_stats
        _reset_cache_stats()
    except Exception:
        pass

    # Every enriched record is appended to the JSONL sidecar as it is found (see state._emit_result), so a hard kill loses nothing already fetched.
    state._RESULT_FILE = paths["jsonl"]
    try:
        state._RESULT_HANDLE = open(paths["jsonl"], "a", encoding="utf-8")
    except Exception:
        state._RESULT_HANDLE = None

    # Start incremental Excel: create workbook with headers on first record COLLAPSE_CHAINS needs the whole record set to merge chains, so it can't append row-by-row — disable the incremental workbook and rebuild Excel once at the end from the filtered records instead.
    _legacy_exports = state.PIPELINE != "raw"
    if state.OUTPUT_EXCEL and not state.COLLAPSE_CHAINS and _legacy_exports:
        state._EXCEL_APPEND_ENABLED = True
        try:
            _init_excel(paths["xlsx"])
        except Exception:
            state._EXCEL_APPEND_ENABLED = False
    else:
        state._EXCEL_APPEND_ENABLED = False

    ckpt       = load_checkpoint(ckpt_key) if state.RESUME_MODE else {"seen_urls": set(), "completed": set()}
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

    grid_index = build_grid_index(grid_points) if use_grid else {}
    dead_points: dict[tuple[float, float], bool] = {}

    def mark_progress(query: str) -> None:
        nonlocal progress_count
        with progress_lock:
            progress_count += 1
            pbar_pts.update(1)
            state._progress(progress_count, total_points, query)

    def run_query(query: str):
        state.info(f"  ─── Запрос «{query}»: начало поиска")
        query_records: list[dict] = []
        processed_keys: list[tuple] = []
        # Search-phase bookkeeping for the «всё уже спарсено ранее» verdict:
        api_hits = 0
        new_candidates_total = 0

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

        def _join_stop_aware(thread) -> bool:
            """Join a batch thread, polling stop/skip every 0.25s."""
            if thread is None:
                return True
            stop_observed = 0.0
            while thread.is_alive():
                if (state._STOP_EVENT and state._STOP_EVENT.is_set()) or state.is_skip_city():
                    if stop_observed == 0.0:
                        stop_observed = time.monotonic()
                    elif time.monotonic() - stop_observed > 2.0:
                        return False  # abandoned — records already on disk
                else:
                    stop_observed = 0.0
                thread.join(timeout=0.25)
            return True

        def drain_batch() -> None:
            """Wait for current enrichment batch and collect results."""
            nonlocal batch_key, batch_thread
            if batch_thread is not None:
                if _join_stop_aware(batch_thread):
                    recs = batch_results.pop(batch_key, [])
                    query_records.extend(recs)
                    processed_keys.append(batch_key)
                    mark_progress(query)
                batch_thread = None
                batch_key = None

        def join_prev_batch(prev_thread, prev_key) -> None:
            """Join a specific previous batch thread and collect its results."""
            if prev_thread is not None:
                if _join_stop_aware(prev_thread):
                    recs = batch_results.pop(prev_key, [])
                    query_records.extend(recs)
                    processed_keys.append(prev_key)
                    mark_progress(query)

        # Drain any leftover enrichment from previous city's last query
        drain_batch()

        # Track previous batch for pipelining
        prev_batch_thread: threading.Thread | None = None
        prev_batch_key: tuple | None = None

        for lat, lon in grid_points:
            if state._STOP_EVENT and state._STOP_EVENT.is_set():
                break
            if state.is_skip_city():
                break

            key = (query, lat, lon)
            if key in completed:
                continue

            point_num = progress_count + 1
            state.update_pause_info(query=query, point=point_num, points_total=total_points)

            nb = grid_index.get((lat, lon), {})
            known_nb = [n for n in (nb.get("up"), nb.get("left"), nb.get("up_left")) if n]
            if len(known_nb) >= 2 and all(dead_points.get(n) for n in known_nb):
                state.syslog(f"point {point_num}/{total_points} [{lat:.3f}, {lon:.3f}] skipped — neighbors dead")
                processed_keys.append(key)
                mark_progress(query)
                continue

            if use_grid:
                state.syslog(f"point {point_num}/{total_points} [{lat:.3f}, {lon:.3f}], query={query}")
            else:
                state.info(f"  🔍 Поиск: «{query}» в {state.CITY}…")

            pbar_search.set_description(f"«{query}»")

            candidates, found, new_candidates = collect_candidates(
                query, state.CITY, lat, lon, seen_urls,
                pbar_search, pbar_detail, seen_lock=seen_lock,
            )
            state.syslog(f"point result: api_found={found}, candidates={len(candidates)}, new={new_candidates}")
            try:
                api_hits = max(api_hits, int(found or 0))
                new_candidates_total += int(new_candidates or 0)
            except (TypeError, ValueError):
                pass

            dead_points[(lat, lon)] = bool(
                found is not None and (found == 0 or new_candidates == 0)
            )

            # Start enrichment for THIS point
            start_batch(key, candidates)

            # Now wait for the PREVIOUS point's enrichment while we go back to the top of the loop and search the next point.
            join_prev_batch(prev_batch_thread, prev_batch_key)
            prev_batch_thread = batch_thread
            prev_batch_key = batch_key

        # Wait for the final batch.
        drain_batch()

        state.info(f"  ✅ «{query}»: {len(query_records)} записей")
        state.syslog(f"query_done: query={query}, records={len(query_records)}")
        return processed_keys, query_records, (api_hits, new_candidates_total)

    pending_queries = [
        query for query in state.SEARCH_QUERIES
        if any((query, lat, lon) not in completed for lat, lon in grid_points)
    ]
    pbar_pts.update(len(completed))
    state._progress(len(completed), total_points, "")

    detail_pool = ThreadPoolExecutor(max_workers=state.MAX_WORKERS)
    _api_hits = 0           # organizations the API returned for this city
    _new_candidates = 0     # how many of them were not seen before
    state.CITY_ALL_SEEN = False

    try:
        if pending_queries:
            worker_count = min(state.SEARCH_WORKERS, len(pending_queries))
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = {pool.submit(run_query, query): query for query in pending_queries}
                for future in as_completed(futures):
                    query = futures[future]
                    try:
                        processed_keys, records, point_stats = future.result()
                    except Exception as exc:
                        state.warn(f"Ошибка в запросе «{query}»: {exc}")
                        continue

                    _api_hits = max(_api_hits, point_stats[0])
                    _new_candidates += point_stats[1]
                    all_results.extend(records)
                    completed.update(processed_keys)
                    if records and state.OUTPUT_CSV and _legacy_exports:
                        save_csv(records, paths["csv"], append=True)
                        state.syslog(f"csv_append: +{len(records)} records")

                    if processed_keys:
                        save_checkpoint(ckpt_key, seen_urls, completed)
                        save_global_seen(seen_urls)

                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        break

        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            pause_ev = getattr(state, "_PAUSE_EVENT", None)
            if pause_ev and pause_ev.is_set():
                state.ok("⏸ Поиск поставлен на паузу. Прогресс сохранён — нажмите «Продолжить», чтобы возобновить.")
            else:
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
        save_checkpoint(ckpt_key, seen_urls, completed)

    # Rebuild the full list from the crash-safe JSONL sidecar.
    jsonl_records = load_jsonl(paths["jsonl"])
    full_records  = dedupe_records(jsonl_records)
    full_records  = apply_output_filters(full_records)
    state.syslog(f"jsonl_records={len(jsonl_records)}, full_after_dedupe={len(full_records)}")

    # ── Stage 1 raw export (two-stage pipeline) ─────────────────
    state._RAW_FILES_LAST_RUN = []
    # Files of THIS run: run() is called per city, so the per-city list above is useless for stage 2 — a multi-city run kept only the last city's raw files and exported just that city. `_RAW_FILES_RUN` accumulates across the whole run (created by run_web) and is what stage 2 filters.
    if not isinstance(getattr(state, "_RAW_FILES_RUN", None), list):
        state._RAW_FILES_RUN = []
    if state.PIPELINE == "raw" and jsonl_records:
        try:
            from .processing import annotate_branch_counts, export_raw_records
            # «🎯 Тип компании»: branch_count считается по всему городу ДО разбивки на файлы (филиалы сети часто попадают в разные запросы), так что число попадает в raw и живёт до «Применить фильтры заново».
            annotate_branch_counts(jsonl_records)
            _by_qc: dict[tuple, list[dict]] = {}
            for _r in jsonl_records:
                _by_qc.setdefault((_r.get("query") or state.CITY, _r.get("city") or state.CITY), []).append(_r)
            for (_q, _c), _recs in _by_qc.items():
                # Resume: do not overwrite the slice collected before the pause.
                _rawp = export_raw_records(_recs, _q, _c,
                                           merge_existing=bool(state.RESUME_MODE))
                state._RAW_FILES_LAST_RUN.append(_rawp)
                if _rawp not in state._RAW_FILES_RUN:
                    state._RAW_FILES_RUN.append(_rawp)
                state.syslog(f"raw_export: {len(_recs)} records → {_rawp}")
            if state._RAW_FILES_LAST_RUN:
                # Полный путь: папка результатов может быть пользовательской.
                state.info(f"  📦 Raw: {len(jsonl_records)} организаций (без фильтров) → {state.RAW_DIR}")
        except Exception as exc:
            state.warn(f"Не удалось сохранить raw-данные: {exc}")
    if state.APPEND_MODE and os.path.exists(paths["json"]):
        try:
            with open(paths["json"], encoding="utf-8") as f:
                full_records = dedupe_records(json.load(f) + jsonl_records)
        except Exception:
            pass

    if state.OUTPUT_JSON and jsonl_records and _legacy_exports:
        try:
            save_json(full_records, paths["json"], append=False)
            state.syslog(f"json_save: {len(full_records)} records → {paths['json']}")
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
            state.syslog(f"excel_finalize: {len(full_records or all_results)} records...")
            _finalize_excel(full_records or all_results)
            state.syslog(f"excel_done: {paths['xlsx']}")
        except Exception as exc:
            state.warn(f"Ошибка финализации Excel: {exc}")
            # Fallback: rebuild from scratch
            try:
                if full_records:
                    save_excel(full_records, paths["xlsx"])
            except Exception:
                pass
    elif state.OUTPUT_EXCEL and full_records and _legacy_exports:
        # CLI fallback (shouldn't normally happen)
        try:
            save_excel(full_records, paths["xlsx"])
        except Exception:
            pass

    state._EXCEL_APPEND_ENABLED = False

    # Nothing found at all → never leave an empty output behind.
    if not all_results and not full_records:
        for _key in ("xlsx", "csv", "json", "map"):
            _p = paths.get(_key)
            try:
                if _p and os.path.exists(_p):
                    os.remove(_p)
                    state.syslog(f"empty_output_removed: {_p}")
            except Exception:
                pass

    if full_records and _legacy_exports:
        if state.OUTPUT_MAP:
            state.syslog(f"map_generate: {len(full_records)} records...")
            save_map(full_records, paths["map"], center_lat, center_lon)
            state.info(f"  💾 Карта: готово → {paths['map']}")

    print_stats(all_results)
    print_limit_stats()

    state.ok(f"{'═' * 58}")
    # Контекст для счётчика: «50 (из 43 запросов)» объясняет, откуда цифра.
    try:
        from .http_client import get_stats as _http_stats
        _api_requests = int(_http_stats().get("requests") or 0)
    except Exception:
        _api_requests = 0
    _found_ctx = f" (из {_api_requests} запросов)" if _api_requests else ""
    # «Найдено 0» при включённых фильтрах выглядит как сорвавшийся поиск, а не как работающий предфильтр: показываем, сколько записей сбор снял сам.
    _skipped_ctx = ""
    try:
        _skipped_total = state.crawl_skip_summary()["total"]
        if _skipped_total:
            _skipped_ctx = f" · предфильтр сбора отбросил {_skipped_total}"
    except Exception:
        pass
    state.ok(f"  Найдено записей: {len(all_results)}{_found_ctx}{_skipped_ctx}")
    if full_records:
        # Paths already announced as «📁 город: файл» are not repeated here — each output path shows up once per run. _shown_file_paths only exists in the web runner; the plain run() still prints everything.
        shown = globals().get("_shown_file_paths") or set()
        def _skip(rel_path: str) -> bool:
            import os as _os
            return _os.path.basename(rel_path) in shown
        if _legacy_exports:
            if state.OUTPUT_CSV and not _skip(paths["csv"]):   state.ok(f"  CSV   → {state.short_path(paths['csv'])}")
            if state.OUTPUT_JSON and not _skip(paths["json"]):  state.ok(f"  JSON  → {state.short_path(paths['json'])}")
            if state.OUTPUT_EXCEL and not _skip(paths["xlsx"]): state.ok(f"  Excel → {state.short_path(paths['xlsx'])}")
            if state.OUTPUT_MAP and not _skip(paths["map"]):   state.ok(f"  Карта → {state.short_path(paths['map'])}")

    if len(completed) == total_points:
        clear_checkpoint(ckpt_key)
        state.syslog("checkpoint_cleared: all points processed")

    state.ok(f"{'═' * 58}\n")

    # Verdict for «город уже парсился»: the API DID return organizations, but not a single one was new — everything is in the global seen store.
    state.CITY_ALL_SEEN = bool(
        not all_results and _api_hits > 0 and _new_candidates == 0
    )

    if not full_records:
        state.warn("Подходящих записей не найдено. Попробуйте изменить запросы или фильтры.")
        if getattr(state, "SEARCH_BLOCKED", ""):
            # Пустота из-за капчи — не повод менять запросы и фильтры: выдачи вообще не было, и это надо сказать отдельно от «ничего не нашлось».
            try:
                from .search import search_failure_hint
                state.warn("  ⚠ " + search_failure_hint())
            except Exception:
                pass
        if state.CITY_ALL_SEEN:
            state.warn(
                f"  ⚠ {state.CITY}: все найденные организации уже парсились ранее — "
                "новых нет. Файлы не создаются. Чтобы пройти город заново, "
                "очистите кэш: вкладка «История» → «🗑 Очистить кэш»."
            )


def _apply_params(params: dict) -> None:
    """Apply form parameters to the global state module."""
    state.SEARCH_QUERIES  = [q.strip() for q in params.get("queries", []) if q.strip()]
    state.OUTPUT_CSV      = bool(params.get("output_csv", False))
    state.OUTPUT_JSON     = bool(params.get("output_json", False))
    state.OUTPUT_EXCEL    = bool(params.get("output_excel", True))
    state.OUTPUT_MAP      = bool(params.get("output_map", False))
    state.OUTPUT_FILENAME = None
    state.APPEND_MODE     = False
    state.RESUME_MODE     = bool(params.get("resume", False))
    # Two-stage pipeline: "raw" — сбор применяет только те фильтры, которые известны по самой записи (чёрный список, «только без сайтов», соцсети: см. processing.crawl_skip_reason), а фильтры, которым нужен весь набор (объединение филиалов, «тип компании», оценка лида), ждут этапа 2. Unset → legacy behaviour.
    _pl = params.get("pipeline", "")
    state.PIPELINE = _pl if _pl in ("raw", "") else ""
    state.RAW_MODE = params.get("raw_mode", "keep") if state.PIPELINE == "raw" else "keep"
    if state.PIPELINE == "raw":
        state.COLLAPSE_CHAINS = False
    else:
        state.COLLAPSE_CHAINS = bool(params.get("collapse_chains", False))
    state.USE_GRID        = bool(params.get("use_grid", False))
    # Data source: только Яндекс (источник 2GIS удалён по требованию правообладателя).
    state.SOURCE = "yandex"
    state.GRID_RADIUS_KM  = int(params.get("grid_radius", 20))
    state.GRID_STEP_KM    = int(params.get("grid_step", 5))
    state.MAX_WORKERS     = max(1, int(params.get("max_workers", 20)))
    state.SEARCH_WORKERS  = max(1, min(5, int(params.get("query_workers", 2))))
    state.MAX_PAGES       = max(1, int(params.get("max_pages", 1)))
    state.FETCH_DETAIL    = bool(params.get("fetch_detail", True))
    state.SOCIAL_MODE      = params.get("social_mode", "all")
    # Required socials (stage-2 filter): the business must have ALL of them.
    try:
        from yandex_maps_parser.constants import KNOWN_PLATFORMS as _KP
        _rs = params.get("required_socials") or []
        state.REQUIRED_SOCIALS = {str(p) for p in _rs if str(p) in _KP}
    except Exception:
        state.REQUIRED_SOCIALS = set()
    state.MAX_CANDIDATES_PER_CITY = max(0, int(params.get("max_candidates", 200)))
    # Parse mode: "without_website" (only businesses without a website) | "all".
    _pm = params.get("parse_mode", "without_website")
    state.PARSE_MODE = _pm if _pm in ("without_website", "all") else "without_website"
    # Чёрный список нужен уже сбору: слово снимает запись ДО загрузки карточки.
    try:
        from .processing import parse_blacklist_words
        state.BLACKLIST_WORDS = parse_blacklist_words(params.get("blacklist_words") or [])
    except Exception:
        state.BLACKLIST_WORDS = []
    state.reset_crawl_skips()
    # Счётчики непрочитанных карточек — на прогон целиком (как и предфильтр):
    state.reset_read_failures()
    # Фильтры, которые сбор может решить по одной записи (см. processing.crawl_skip_reason): без них снятые этапом 2 записи появлялись бы в живой таблице и пропадали только в конце прогона.
    try:
        state.MIN_LEAD_SCORE = int(params.get("min_lead_score") or 0)
    except (TypeError, ValueError):
        state.MIN_LEAD_SCORE = 0
    state.ONLY_SINGLE_BRANCH = bool(params.get("only_single_branch", False))
    try:
        from .processing import normalize_only_new_months
        state.ONLY_NEW_MONTHS = normalize_only_new_months(params.get("only_new_months"))
    except Exception:
        state.ONLY_NEW_MONTHS = None
    state.VK_CHECK = bool(params.get("vk_check", False))
    # Excel export columns: list of field keys from the form; None = all columns
    _ec = params.get("excel_columns")
    if isinstance(_ec, list) and _ec:
        from yandex_maps_parser.constants import CSV_FIELDS
        _valid = set(CSV_FIELDS)
        state.EXCEL_COLUMNS = {str(f) for f in _ec if str(f) in _valid}
    else:
        state.EXCEL_COLUMNS = None
    # Страницы читает только настоящий браузер (Chrome/Chromium через CDP), поэтому выбор «способа парсинга» больше не нужен: HTTP-путь удалён.
    state.USE_BROWSER    = bool(params.get("use_browser", True))
    # Debug window: separate Chrome, visible, CDP only (no tab pool).
    state.DEBUG_CDP_WINDOW = bool(params.get("debug_cdp_window", False))
    # Socials are ALWAYS collected from business cards (the UI has no switch for it any more): without them neither the social filters nor the lead score can work. `fetch_detail=False` stays honored for API clients.
    if not params.get("fetch_detail", True):
        state.FETCH_DETAIL = False
    # Re-create semaphore to match the new MAX_WORKERS setting
    state._detail_semaphore = threading.Semaphore(state.MAX_WORKERS)


class _NoRawData(Exception):
    """Этап 2 не нужен: сырых файлов нет (не ошибка, а пустой сбор)."""


def _run_was_interrupted() -> bool:
    """True when the last run_web() was stopped by the user or crashed."""
    return bool(getattr(state, "_RUN_INTERRUPTED", False))


def _collect_run_files(started_at: float) -> list[str]:
    """Collect output files created after started_at."""
    result_files: list[str] = []
    _results = str(getattr(state, "RESULTS_DIR", None) or state.OUTPUT_DIR)
    if os.path.isdir(_results):
        for fname in sorted(os.listdir(_results)):
            fpath = os.path.join(_results, fname)
            if (
                os.path.isfile(fpath)
                and os.path.getmtime(fpath) >= started_at
                and not fname.startswith("_")
                and not fname.startswith(".")
                and not fname.startswith("~$")
                and not fname.endswith(".checkpoint.json")
                and not fname.endswith(".jsonl")
            ):
                result_files.append(fname)
    return result_files


def run_web(params: dict, log_fn, stop_event=None, skip_event=None, pause_event=None) -> list[str]:
    """Run the parser with settings from the web form."""
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
    _run_start_time = time.time()  # track overall run start for history
    _last_finished_city = ""       # последний город, доведённый до конца
    # Interrupted-run flag for the two-stage pipeline (edge case 3):
    state._RUN_INTERRUPTED = False
    _loop_ok = False   # True only when the city loop finished without an exception

    # Set up file logger for this run
    import uuid as _uuid
    run_id = _uuid.uuid4().hex[:8]
    try:
        from run_logger import RunLogger
        _file_logger = RunLogger(run_id, cities, state.SEARCH_QUERIES)
    except Exception:
        _file_logger = None

    # Combine browser + file logging
    def _combined_log(level: str, msg: str) -> None:
        if log_fn:
            log_fn(level, msg)
        if _file_logger:
            _file_logger.log(level, msg)

    # File-only system log: writes to log file but NOT to browser.
    def _syslog(msg: str) -> None:
        if _file_logger:
            _file_logger.log("sys", msg)

    # Web-only log: writes to browser but NOT to file.
    def _weblog(level: str, msg: str) -> None:
        if log_fn:
            log_fn(level, msg)

    # Browser-visible duplicate guard for human log lines only.
    _last_web_msg = [""]

    def _dedup_emit(level: str, msg: str, emit) -> None:
        if level in ("info", "ok", "warn", "error"):
            if msg == _last_web_msg[0]:
                return
            _last_web_msg[0] = msg
        emit(level, msg)

    def _dedup_log(level: str, msg: str) -> None:
        """_combined_log with consecutive-duplicate suppression (human levels)."""
        _dedup_emit(level, msg, _combined_log)

    def _dedup_weblog(level: str, msg: str) -> None:
        _dedup_emit(level, msg, _weblog)

    state._LOG_FN        = _dedup_log
    state._SYSLOG_FN     = _syslog
    state._TQDM_DISABLE  = True
    state._STOP_EVENT    = stop_event
    state._SKIP_CITY_EVENT = skip_event or threading.Event()
    # A pause maps onto the stop event: the run unwinds through the same graceful path (checkpoint + Excel finalize).
    if pause_event is None:
        pause_event = threading.Event()
    state._PAUSE_EVENT   = pause_event
    state._SKIPPED_CITIES = []
    # Raw xlsx files of THIS run (filled per city in run() and read by the stage-2 block below).
    state._RAW_FILES_RUN = []
    if state.RESUME_MODE and state.PIPELINE == "raw":
        try:
            from .processing import raw_files_for
            state._RAW_FILES_RUN = raw_files_for(state.SEARCH_QUERIES, cities)
            if state._RAW_FILES_RUN:
                state.info(f"  ⏪ Продолжение: к обработке добавлено {len(state._RAW_FILES_RUN)} "
                           f"сырых файлов прошлого запуска")
        except Exception:
            state._RAW_FILES_RUN = []
    # File paths already announced via «📁 город: файл» — the final summary («Excel → …», «JSON → …») skips them so each path prints once.
    _shown_file_paths: set[str] = set()
    _total_records = 0
    # One flag per city that actually ran: True when the city produced nothing because every organization found there was parsed in an earlier run.
    _seen_flags: list[bool] = []
    state._ALL_ALREADY_SEEN = False
    # Проверка «Вы не робот?» от Яндекса: сбрасывается на каждый прогон, чтобы прошлая капча не объясняла сегодняшнюю пустоту.
    state.SEARCH_BLOCKED = ""
    try:
        from . import browser_search
        browser_search.reset_blocked()
    except Exception:
        pass

    # Continuation mode: after the user's cities, keep parsing further cities from the catalog (population order), until continue_limit extra cities have run.
    continue_extra = int(params.get("continue_limit", 0) or 0)
    if params.get("continue_cities") and continue_extra > 0:
        try:
            from yandex_maps_parser.city_data import cities_after
            extra: list[str] = cities_after(cities[-1], continue_extra, exclude=cities)
        except Exception:
            extra = []
        if extra:
            last_before = cities[-1]
            cities = cities + extra
            state.info(
                f"  ♾ Режим продолжения: после «{last_before}» добавлено {len(extra)} "
                f"городов — {', '.join(extra[:5])}"
                + ("…" if len(extra) > 5 else "")
            )
    total_cities = len(cities)   # recount after expansion

    # Log configuration — system traces to file only
    _syslog(f"Запуск run_web: run_id={run_id}, города={cities}, запросы={state.SEARCH_QUERIES}")
    _syslog(f"Конфиг: worker={state.MAX_WORKERS}, search_workers={state.SEARCH_WORKERS}, max_pages={state.MAX_PAGES}")
    _syslog(f"Фильтры: social_mode={state.SOCIAL_MODE}, retry={state.RETRY_COUNT}")
    _syslog(f"Вывод: excel={state.OUTPUT_EXCEL}, json={state.OUTPUT_JSON}, csv={state.OUTPUT_CSV}, map={state.OUTPUT_MAP}")
    _syslog(f"GRID: enabled={state.USE_GRID}, radius={state.GRID_RADIUS_KM}km, step={state.GRID_STEP_KM}km")

    # Initialize the browser pool.
    if state.USE_BROWSER:
        # Выбор браузера: параметр запуска → settings.json → автоматически.
        _browser_path = str(params.get("browser_path") or "").strip()
        if not _browser_path:
            try:
                import paths as _paths_mod
                _browser_path = str(_paths_mod.load_settings().get("browser_path") or "").strip()
            except Exception:
                _browser_path = ""
        cdp_client.set_browser(_browser_path)
        cdp_ok = cdp_client.init_browser(pool_size=min(state.MAX_WORKERS, 20))
        if cdp_ok:
            _binfo = cdp_client.browser_info()
            _syslog(f"Browser pool: CDP initialized ({_binfo.get('name')} at {_binfo.get('path')})")
            _weblog("info", "  🌐 Режим: браузер ("
                             + (_binfo.get("name") or "Chrome/Chromium")
                             + " через CDP)")
        else:
            _syslog("Browser pool: CDP unavailable, no HTTP fallback (removed)")
            _weblog("warn", "  ⚠ Браузер не найден — установите Chrome/Chromium "
                            "(вкладка «🩺 Диагностика» подскажет, что делать)")
    # Debug window — separate visible Chrome (CDP only, no tab pool)
    if state.DEBUG_CDP_WINDOW:
        dp = cdp_client.open_debug_window()
        if dp is not None:
            _syslog(f"debug_cdp_window: opened, CDP port={dp}")
            _weblog("info", f"  🔬 Отладочный Chrome открыт: CDP порт {dp}")
        else:
            _syslog("debug_cdp_window: failed to open window")
            _weblog("warn", "  ⚠ Не удалось открыть отладочный Chrome")
    # Deduped: the same line was previously printed twice for single-city runs (once here, once via the city header path).
    _dedup_weblog("info", f"  Поиск: {len(cities)} город(ов) — {', '.join(cities)}; "
                         f"запросы: {', '.join(state.SEARCH_QUERIES)}")
    # Журнал источников: дата сбора и откуда взяты данные.
    _dedup_weblog("info", f"  📅 Данные собираются сейчас: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                         " · источник — публичная выдача Яндекс.Карт")
    # Лимиты: приложение не «долбит» сервис, а ждёт между запросами; при 429 пауза увеличивается сама (rate_limit).
    _dedup_weblog("info", "  🐢 Вежливый режим: пауза между запросами, "
                         "авто-замедление при 429 — сервис не получает шквал запросов")

    try:
        for city_idx, city in enumerate(cities):
            if stop_event and stop_event.is_set():
                break

            # Папку результатов могли поменять в интерфейсе уже во время поиска: новая настройка вступает в силу со СЛЕДУЮЩЕГО города, текущий дописывается туда, где начался.
            try:
                import paths as _paths_mod
                _paths_mod.refresh_output_dirs()
            except Exception:
                pass

            state.update_pause_info(city=city, city_idx=city_idx + 1, cities_total=total_cities)
            # Reset skip event and per-city record counter for each new city
            state.reset_skip_city()
            # Reset the adaptive backoff counter for the new city
            try:
                from yandex_maps_parser.rate_limit import _anti_bot_reset, _rps_reset
                _anti_bot_reset()
                _rps_reset()
            except Exception:
                pass
            _syslog(f"--- Город {city_idx + 1}/{total_cities}: {city} ---")

            if total_cities > 1:
                # Web: simple city header (deduped)
                _dedup_weblog("info", f"  🏙  Город {city_idx + 1}/{total_cities}: {city}")
                # File: detailed separator
                if _file_logger:
                    _file_logger.log_city_start(city_idx + 1, total_cities, city)
                # Signal city transition to frontend
                _combined_log("progress", f"city/{city_idx + 1}/{total_cities}/{city}")
                # Once per run: tell the frontend the full queue so it can prefill queued cities and show «Городов обработано: X из Y».
                if city_idx == 0:
                    _combined_log("progress", f"city_list|{'/'.join(cities)}")

            state.CITY = city
            started_at = time.time()
            _syslog(f"Вызов run(): city={city}, queries={state.SEARCH_QUERIES}, max_pages={state.MAX_PAGES}")
            run()
            _syslog(f"run() завершена за {time.time() - started_at:.1f}с")

            # Check if city was skipped
            was_skipped = state.is_skip_city()
            records_found = state._CITY_RECORDS_FOUND
            _total_records += records_found
            _seen_flags.append(bool(getattr(state, "CITY_ALL_SEEN", False)))
            if was_skipped:
                state._SKIPPED_CITIES.append({"name": city, "records_found": records_found})
                _dedup_weblog("ok", f"  ⏭ {city}: пропущен вручную ({records_found} записей сохранено)")
                if _file_logger:
                    _file_logger.log_city_done(city, records_found, skipped=True)
                if total_cities > 1:
                    _combined_log("progress", f"city_done|{city_idx + 1}|{total_cities}|{city}|skipped|{records_found}")
            else:
                _last_finished_city = city
                if _file_logger:
                    _file_logger.log_city_done(city, records_found)
                if total_cities > 1:
                    _combined_log("progress", f"city_done|{city_idx + 1}|{total_cities}|{city}|done|{records_found}")

            # Collect files from this city run
            city_files = _collect_run_files(started_at)
            all_files.extend(city_files)
            _syslog(f"Город {city}: файлы={city_files}, records={records_found}")

            # Refresh the merged frontend JSON after EVERY city, not just at the end — so the results table / stats stay populated even if the app is killed or the run is stopped before all cities.
            try:
                from .exporters import write_frontend_json
                write_frontend_json(all_files, str(getattr(state, "RESULTS_DIR", None) or state.OUTPUT_DIR), cities)
            except Exception:
                pass

            if city_files:
                _shown_file_paths.update(city_files)
                _weblog("ok", f"  📁 {city}: {', '.join(state.short_path(f) for f in city_files)}")
        _loop_ok = True
    finally:
        # «Города уже парсились ранее»: each city that ran returned zero new organizations while the API did return some.
        state._ALL_ALREADY_SEEN = bool(
            _seen_flags and all(_seen_flags) and _total_records == 0
        )
        if state._ALL_ALREADY_SEEN:
            _weblog("warn",
                    "  ⚠ Все найденные организации уже парсились ранее — новых нет, "
                    "файлы не создавались. Чтобы пройти города заново, очистите кэш "
                    "(вкладка «История» → «🗑 Очистить кэш»).")
        # Save search history
        try:
            from search_history import add_entry as _hist_add
            elapsed = time.time() - _run_start_time
            _hist_add(
                run_id=run_id,
                queries=state.SEARCH_QUERIES,
                cities=cities,
                social_mode=state.SOCIAL_MODE,
                results_count=_total_records,
                files=all_files,
                elapsed_sec=elapsed,
                # «paused» — не «stopped»: поиск ждёт «Продолжить», а не завершён.
                status=("paused" if (pause_event and pause_event.is_set())
                        else "stopped" if (stop_event and stop_event.is_set())
                        else "completed"),
            )
        except Exception:
            pass
        # Shut down browser pool (Playwright + CDP)
        try:
            cdp_client.close_browser()
        except Exception:
            pass
        # Write final summary to file log
        if _file_logger:
            try:
                stopped = bool(stop_event and stop_event.is_set())
                _file_logger.finish(_total_records, all_files, stopped,
                                    paused=bool(pause_event and pause_event.is_set()))
            except Exception:
                pass
        # Two-stage pipeline: stage 2 (filtering) runs only on complete crawls.
        if state.PIPELINE == "raw" and _loop_ok and not (stop_event and stop_event.is_set()):
            try:
                from .processing import process_all
                _filters = {
                    "collapse_chains": bool(params.get("collapse_chains", False)),
                    "chain_key":       params.get("chain_key", "name_city"),
                    "parse_mode":      params.get("parse_mode", "all"),
                    "social_mode":     state.SOCIAL_MODE,
                    "required_socials": sorted(state.REQUIRED_SOCIALS),
                    # Lead scoring + VK activity (accordion «Фильтрация результата»).
                    "vk_check":         bool(params.get("vk_check", False)),
                    "vk_mode":          params.get("vk_mode", "all"),
                    "vk_max_post_days": params.get("vk_max_post_days") or 0,
                    "vk_min_followers": params.get("vk_min_followers") or 0,
                    "min_lead_score":   params.get("min_lead_score") or 0,
                    "sort_by_score":    bool(params.get("sort_by_score", True)),
                    # Чёрный список («🚫 Исключить по словам»): слова приезжают из формы и снимают записи ДО остальных фильтров.
                    "blacklist_words":  params.get("blacklist_words") or [],
                    # «🎯 Тип компании»: только одиночки и/или только новые.
                    "only_single_branch": bool(params.get("only_single_branch", False)),
                    "only_new_months":   params.get("only_new_months"),
                }
                _formats = []
                if params.get("output_excel"): _formats.append("excel")
                if params.get("output_json"):  _formats.append("json")
                if params.get("output_csv"):   _formats.append("csv")
                if params.get("output_map"):   _formats.append("html")
                # Every raw file of this run — including the slice written before a pause (preloaded in run_web on resume).
                _raw_input = (list(getattr(state, "_RAW_FILES_RUN", []) or [])
                              or list(getattr(state, "_RAW_FILES_LAST_RUN", []) or []))
                if not _raw_input:
                    # Собирать было нечего (пустая выдача, капча, все записи сняты предфильтром) — фильтровать тоже нечего.
                    _weblog("info", "  🧪 Этап 2 пропущен: сырых данных нет — "
                                     "фильтровать нечего (причина выше)")
                    raise _NoRawData()
                _stage2 = process_all(
                    _raw_input,
                    _filters,
                    _formats,
                    log_fn=_weblog,
                    cleanup_mode=state.RAW_MODE,
                )
                for _pf in _stage2.get("files", []) or []:
                    _rel = os.path.relpath(_pf, str(getattr(state, "RESULTS_DIR", None) or state.OUTPUT_DIR))
                    if _rel not in all_files:
                        all_files.append(_rel)
            except _NoRawData:
                pass
            except Exception as exc:
                try:
                    _weblog("warn", f"  [!] Ошибка обработки: {exc}")
                except Exception:
                    pass
        elif state.PIPELINE == "raw" and not _loop_ok:
            state._RUN_INTERRUPTED = True
            try:
                _weblog("warn", "  ⚠ Поиск прерван — сырые данные сохранены в output/raw/, фильтрация не запускалась")
            except Exception:
                pass
        elif state.PIPELINE == "raw":
            state._RUN_INTERRUPTED = True
            # Пауза — это не обрыв: сырые данные те же, но фильтрация ждёт продолжения, и формулировка не должна пугать пользователя.
            _interrupted_msg = (
                "  ⏸ Поиск на паузе — сырые данные сохранены в output/raw/, "
                "фильтрация выполнится после «Продолжить»"
                if (pause_event and pause_event.is_set()) else
                "  ⏹ Поиск прерван — сырые данные сохранены в output/raw/, фильтрация не запускалась"
            )
            try:
                _weblog("warn", _interrupted_msg)
            except Exception:
                pass
        # «Собрано до города X»: при остановке/паузе/лимите пользователь должен видеть, какие данные уже на диске, а какие города остались.
        if not _loop_ok and _last_finished_city:
            try:
                _dedup_weblog("info", f"  📦 Собрано до города «{_last_finished_city}» включительно — "
                                      f"данные сохранены; остальные города можно пройти через «Продолжить»")
            except Exception:
                pass
        state._LOG_FN        = None
        state._SYSLOG_FN     = None
        state._TQDM_DISABLE  = False
        state._SKIP_CITY_EVENT = None
        # NOTE: _SKIPPED_CITIES intentionally NOT cleared here — callers (run_process / thread fallback) read it after run_web() returns to attach the skipped-city list to the "done" message.

    return all_files


# ── Multiprocessing entry point ─────────────────────────────

def _watch_pause_file(pause_file: str, pause_event, stop_event,
                      poll: float = 0.5, stop_grace: float = 2.0) -> None:
    """Poll `pause_file` and, when it appears, flag the run as paused."""
    import time as _t
    deadline = None
    while True:
        if os.path.exists(pause_file):
            pause_event.set()
            stop_event.set()
            return
        if stop_event.is_set():
            if deadline is None:
                deadline = _t.monotonic() + stop_grace
            elif _t.monotonic() >= deadline:
                return              # честный стоп: паузы так и не появилось
        _t.sleep(poll)


def run_process(params: dict, mp_queue, stop_file: str | None = None,
                skip_file: str | None = None, pause_file: str | None = None) -> None:
    """Entry point for a child process running a search."""
    import threading as _threading

    # Create a stop event for this child process
    stop_event = _threading.Event()
    # Create a skip-city event for this child process
    skip_event = _threading.Event()
    # Create a pause event for this child process
    pause_event = _threading.Event()

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

    # Watch the pause file in a background thread: a pause maps onto the stop event (graceful unwind + checkpoint) but stays distinguishable.
    if pause_file:
        _threading.Thread(
            target=_watch_pause_file,
            args=(pause_file, pause_event, stop_event),
            daemon=True,
        ).start()

    # Watch the skip file in a background thread
    if skip_file:
        def _watch_skip():
            while not skip_event.is_set():
                if os.path.exists(skip_file):
                    skip_event.set()
                    try:
                        os.remove(skip_file)
                    except OSError:
                        pass
                    return
                import time as _t
                _t.sleep(0.5)
        _threading.Thread(target=_watch_skip, daemon=True).start()

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
        # Стартовый прогресс для родителя: сколько городов всего.
        _total_cities = len(params.get("cities") or [])
        if _total_cities:
            mp_queue.put({"type": "progress", "cities_done": 0,
                          "cities_total": _total_cities})
        files = run_web(params, _q_log, stop_event, skip_event, pause_event)
        # Build the frontend-friendly merged JSON (english keys, all cities) so the results table and stats render correctly even when only Excel output was requested.
        try:
            from .exporters import write_frontend_json
            ff = write_frontend_json(files, str(getattr(state, "RESULTS_DIR", None) or state.OUTPUT_DIR), params.get("cities"))
            if ff and ff not in files:
                files.insert(0, ff)
        except Exception:
            pass
        count = 0
        for f in files:
            if f == "_results_for_frontend.json" or (f.endswith(".json") and not f.startswith("_")):
                try:
                    with open(os.path.join(str(getattr(state, "RESULTS_DIR", None) or state.OUTPUT_DIR), f), encoding="utf-8") as jf:
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
        skipped = getattr(state, '_SKIPPED_CITIES', [])
        # Enrich the resume payload with the pause position.
        try:
            _pos = state.pause_position()
        except Exception:
            _pos = {}
        # Финальный прогресс: прогон дошёл до конца — все города пройдены и записей столько же, сколько в итоге.
        if _total_cities and not stop_event.is_set() and not pause_event.is_set():
            mp_queue.put({"type": "progress", "cities_done": _total_cities,
                          "cities_total": _total_cities,
                          "records_so_far": count})
        mp_queue.put({"type": "done", "files": files, "count": count,
                      "stopped": stop_event.is_set() and not pause_event.is_set(),
                      "paused": pause_event.is_set(),
                      # True → nothing new: every organization was already parsed in an earlier run (the UI explains it instead of «0»).
                      "all_seen": bool(getattr(state, "_ALL_ALREADY_SEEN", False)),
                      "resume": {
                          "queries": params.get("queries") or [],
                          "all_cities": params.get("cities") or [],
                          "params": params,
                          "position": _pos,
                      },
                      "formats": fmts,
                      "skipped_cities": skipped})
    except Exception as exc:
        try:
            mp_queue.put({"type": "log",  "level": "warn", "msg": f"Ошибка: {exc}"})
            # Явная ошибка для родителя: мост пометит прогон failed, и /api/v1/status отличит «сломалось» от «ничего не найдено».
            mp_queue.put({"type": "error", "message": str(exc)})
            mp_queue.put({"type": "done", "files": [], "count": 0,
                          "stopped": stop_event.is_set() and not pause_event.is_set(),
                          "paused": pause_event.is_set(),
                          "error": str(exc),
                          "resume": None, "formats": []})
        except Exception:
            pass
    finally:
        # Send sentinel so bridge thread knows we're done
        try:
            mp_queue.put(None)
        except Exception:
            pass
        # Clean up stop + skip + pause files (a leftover pause file would immediately pause the NEXT run that reuses the same run_id path).
        for f in (stop_file, skip_file, pause_file):
            if f:
                try:
                    os.remove(f)
                except OSError:
                    pass


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


if __name__ == "__main__":
    run()
