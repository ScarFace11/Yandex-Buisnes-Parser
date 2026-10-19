"""
Public REST API for programmatic access to the parser.

Сервер слушает ТОЛЬКО 127.0.0.1 (см. app.run(host="127.0.0.1") в app.py),
поэтому API доступно с этого же компьютера и ключа не требует: со стороны
сети наружу ничего не выходит.

Endpoints:
  GET  /api/v1/health        — health check
  POST /api/v1/search        — start a search job (asynchronous)
  POST /api/v1/batch         — запустить ПАЧКУ прогонов списком записей
  GET  /api/v1/batch/<id>    — сводка и прогресс пачки
  GET  /api/v1/batch/<id>/results — организации всей пачки одним списком
  GET  /api/v1/runs          — runs of this session (id, статус, файлы)
  GET  /api/v1/status        — status of one run or the whole queue
  GET  /api/v1/results       — records as JSON; ?wait=120 дождаться конца,
                               ?limit=50&offset=0 — страница больших ответов
  POST /api/v1/stop          — stop a running search (?run_id=…&pause=1)
  POST /api/v1/skip-city     — skip the current city of a run
  GET  /api/v1/openapi.json  — OpenAPI-спецификация (для Postman, n8n, кодогенерации)

Статус прогона (`status`): queued | running | paused | done | failed.
`failed` приходит вместе с полем `error` — «сломалось» и «ничего не нашлось»
это разные вещи, и автоматизация должна их различать. У идущих прогонов есть
`progress` {cities_done, cities_total, records_so_far}.

Интеграция с n8n / без опроса: в /search (и в каждой записи /batch) можно
передать "callback_url" — URL (обычно Webhook-нода n8n). Когда прогон
завершится, приложение отправит туда POST {event:"run.finished", run_id,
status, count, files, error, progress}. Опрос /status и /results при этом
работает как раньше — callback это заменяет, но не обязателен.

Записи вместо консоли: /batch принимает массив записей-заданий (как строки
таблицы), первый прогон стартует сразу, остальные встают в очередь, а прогресс
и результаты пачки забираются двумя адресами — так n8n/Sheets/CRM отдают
список задач одним запросом, а не набором текста руками.

Typical automation flow (curl):
  # 1. Запустить поиск — вернётся run_id, поиск идёт в фоне
  curl -X POST http://127.0.0.1:5000/api/v1/search \\
       -H "Content-Type: application/json" \\
       -d '{"queries": ["кафе"], "cities": ["Москва"], "social_mode": "with_socials"}'
  → {"ok": true, "queued": false, "run_id": "…", "warnings": []}

  # 2. Дождаться конца и забрать организации (wait — секунды ожидания)
  curl "http://127.0.0.1:5000/api/v1/results?run_id=…&wait=120"
  → {"status": "done", "count": 137, "files": [...], "results": [...]}

  # 3. Пачка записей одним запросом (вместо набора задач по одной)
  curl -X POST http://127.0.0.1:5000/api/v1/batch \\
       -H "Content-Type: application/json" \\
       -d '{"records": [{"query": "кафе", "city": "Москва"},
                        {"query": "автосервис", "city": "Казань"}]}'
  → {"ok": true, "batch_id": "…", "count": 2, "runs": [...]}
  curl "http://127.0.0.1:5000/api/v1/batch/…/results?wait=300"

  # И то же самое из Python
  import requests
  BASE = "http://127.0.0.1:5000/api/v1"
  r = requests.post(f"{BASE}/search", json={"queries": ["кафе"],
                                            "cities": ["Москва"]}, timeout=30).json()
  data = requests.get(f"{BASE}/results", params={"run_id": r["run_id"],
                                                 "wait": 180}, timeout=200).json()
  for org in data["results"]:
      print(org["name"], org.get("phone"), org.get("vk"))

Ответ /results — все организации прогона: JSON-файлы разных городов
склеиваются в один список, дубли по одной организации (сырые и
обработанные записи) схлопываются, более поздний файл побеждает.
"""

import json
import os
import time
import uuid
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify
from flask_cors import CORS

from run_manager import run_manager, RESULTS_DIR

bp = Blueprint("public_api", __name__, url_prefix="/api/v1")

# Браузерные клиенты (дашборд на другом порту, расширение, страница на
# localhost) без CORS получают заблокированный запрос ещё до нашего ответа.
# Разрешаем только loopback-источники: сервер и так слушает 127.0.0.1 и
# наружу не смотрит, чужие сайты этому API не нужны.
CORS(bp, origins=[r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$"],
     methods=["GET", "POST", "OPTIONS"])

# Ожидание результата ограничено: длинный опрос не должен висеть вечно.
_WAIT_MAX_S = 300
_WAIT_POLL_S = 0.5

# Сколько записей-заданий принимает одна пачка. Больше — не «жадность»:
# прогоны встают в очередь и ищут по одному, а мегабайтный список задач
# в одном запросе только маскирует, что его надо резать на страницы.
_BATCH_MAX_RECORDS = 200

# Кэш разбора результатов: /results опрашивают каждые несколько секунд, и
# без кэша каждый запрос заново читал бы десятки мегабайт JSON (50 городов ×
# 15 страниц). Ключ — прогон/пачка, список файлов и их mtime+размер: файлы
# не менялись → отдаём разобранное из памяти.
_RESULTS_CACHE: dict[tuple, tuple[float, list[dict]]] = {}
_RESULTS_CACHE_TTL_S = 60
_RESULTS_CACHE_MAX = 8


def _int_arg(raw, default: int = 0, lo: int = 0, hi: int | None = None,
             warnings: list | None = None, name: str = "") -> int:
    """Целое из query-параметра; мусор и выход за границы → значение по умолчанию.

    Если передан список warnings, туда попадает предупреждение: клиент
    должен видеть, что max_pages=999 приехал как 50, а не молча получить
    совсем другой прогон.
    """
    if raw is None or str(raw).strip() == "":
        return default
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        if warnings is not None:
            warnings.append(f"{name or 'value'}={raw!r} is not a number — "
                            f"default {default} used")
        return default
    if val < lo:
        if warnings is not None:
            warnings.append(f"{name or 'value'}={val} raised to minimum {lo}")
        return lo
    if hi is not None and val > hi:
        if warnings is not None:
            warnings.append(f"{name or 'value'}={val} clamped to {hi}")
        return hi
    return val


def _as_str_list(value) -> list[str]:
    """Список непустых строк из поля запроса.

    Строка считается ОДНИМ элементом: `"queries": "кафе"` (так часто шлют
    n8n и обычный curl) раньше разбиралось по буквам — получался список из
    четырёх «запросов» по одной букве.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _pick_entry(run_id: str) -> dict | None:
    """Прогон по id; без id — активный или стоящий в очереди."""
    if run_id:
        return run_manager.get(run_id)
    with run_manager._lock:
        runs = sorted(run_manager._runs.values(),
                      key=lambda x: x.get("started_at", 0), reverse=True)
    for r in runs:
        if r.get("active") or r.get("queued"):
            return r
    return None


def _entry_status(entry: dict) -> str:
    """queued | running | paused | done | failed — статус для автоматизации.

    Порядок проверок важен: entry["active"] снимается только через
    _FINISH_DELAY (6 с) после сообщения «done», а мост выставляет _done
    сразу — по одному active клиент видел «running» уже закончившегося
    прогона, и n8n с wait получал пустой список результатов.
    """
    if entry.get("error"):
        return "failed"
    if entry.get("queued"):
        return "queued"
    if entry.get("_done") or not entry.get("active"):
        return "paused" if entry.get("paused") else "done"
    if entry.get("paused"):
        return "paused"        # пауза: прогон ещё активен, но не работает
    return "running"


def _progress_payload(entry: dict) -> dict:
    """Прогресс прогона: сколько городов пройдено и сколько записей уже есть.

    cities_total по умолчанию берётся из списка городов прогона: счётчик
    моста появляется только когда движок дошёл до первого города.
    """
    total = int(entry.get("cities_total") or 0) or len(entry.get("cities") or [])
    return {
        "cities_done":    int(entry.get("cities_done") or 0),
        "cities_total":   total,
        "records_so_far": int(entry.get("records_so_far") or 0),
    }


def _canon_url(url: str) -> str:
    """Канонический вид ссылки: без query/fragment, без хвостового «/», хост в нижнем регистре.

    Дубли одной организации приходят и с `?utm_source=…`, и без него: без
    нормализации они не схлопывались и в ответе появлялись двумя карточками.
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "//" + raw)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/")
    if not host:
        return path.lower()
    return f"{(parsed.scheme or 'https').lower()}://{host}{path}"


def _record_key(rec: dict) -> str | None:
    """Ключ организации для схлопывания дублей (совместим с routes/api._review_key)."""
    y = _canon_url(rec.get("yandex_maps_url"))
    if y:
        return y
    name = " ".join(str(rec.get("name") or "").split()).lower()
    addr = " ".join(str(rec.get("address") or "").split()).lower()
    if not name and not addr:
        return None
    city = " ".join(str(rec.get("city") or "").split()).lower()
    return "n:" + "|".join([name, city, addr])


def _files_fingerprint(files: list[str]) -> tuple:
    """Отпечаток файлов результатов: имя, mtime и размер.

    По нему кэш понимает, что файлы не менялись, и не перечитывает их.
    """
    fp = []
    for rel in files:
        path = os.path.join(RESULTS_DIR, rel)
        try:
            st = os.stat(path)
            fp.append((rel, st.st_mtime_ns, st.st_size))
        except OSError:
            fp.append((rel, None, None))
    return tuple(fp)


def _read_results(files: list[str]) -> list[dict]:
    """Прочитать JSON-файлы прогона: склейка городов + схлопывание дублей."""
    out: list[dict] = []
    seen: dict[str, int] = {}
    for rel in files:
        if not rel.endswith(".json") or os.path.basename(rel).startswith("_"):
            continue
        path = os.path.join(RESULTS_DIR, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        for rec in data:
            if not isinstance(rec, dict):
                continue
            key = _record_key(rec)
            if key and key in seen:
                out[seen[key]] = rec      # более поздний файл побеждает
            else:
                if key:
                    seen[key] = len(out)
                out.append(rec)
    return out


def _load_results(files: list[str], cache_key: str = "") -> list[dict]:
    """Организации прогона с кэшем по отпечатку файлов (см. _RESULTS_CACHE)."""
    key = (cache_key, _files_fingerprint(files))
    now = time.monotonic()
    hit = _RESULTS_CACHE.get(key)
    if hit and now - hit[0] < _RESULTS_CACHE_TTL_S:
        return list(hit[1])
    records = _read_results(files)
    if len(_RESULTS_CACHE) >= _RESULTS_CACHE_MAX:
        # Кэш крошечный: сбросить дешевле, чем считать попадания.
        _RESULTS_CACHE.clear()
    _RESULTS_CACHE[key] = (now, records)
    return list(records)


def _build_params(data: dict, warnings: list) -> tuple[dict, list[str]]:
    """Параметры прогона из тела запроса — общее для /search и /batch.

    Возвращает (params, errors): непустые errors → ответ 400 с прежними
    текстами ошибок (обратная совместимость для готовых интеграций).
    """
    errors: list[str] = []
    queries = _as_str_list(data.get("queries"))
    if not queries:
        errors.append("queries is required (array of strings)")

    cities = _as_str_list(data.get("cities"))
    if not cities:
        errors.append("cities is required (array of strings)")

    # callback_url — куда стучаться по завершении прогона (Webhook n8n и т.п.).
    # Принимаем только http(s)-адрес: это не «локальная опечатка», а защита
    # от случайной записи файла по мусорной строке внутри приложения.
    callback_url = str(data.get("callback_url") or "").strip()
    if callback_url:
        parsed = urlparse(callback_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append("callback_url must be an http(s) URL")

    if errors:
        return {}, errors

    params = {
        "queries": queries,
        "cities": cities,
        "social_mode": str(data.get("social_mode") or "with_socials"),
        "max_pages": _int_arg(data.get("max_pages"), 15, 1, 50, warnings, "max_pages"),
        "max_workers": _int_arg(data.get("max_workers"), 10, 1, 20, warnings, "max_workers"),
        "query_workers": 2,
        # min_rating нормализуется ниже (мусор в запросе не должен ронять 500)
        "min_rating": 0.0,
        "min_reviews": _int_arg(data.get("min_reviews"), 0, 0, None, warnings, "min_reviews"),
        "use_grid": bool(data.get("use_grid", False)),
        "grid_radius": _int_arg(data.get("grid_radius"), 20, 1, 500, warnings, "grid_radius"),
        "grid_step": _int_arg(data.get("grid_step"), 5, 1, 100, warnings, "grid_step"),
        "use_browser": bool(data.get("use_browser", True)),
        "fetch_detail": bool(data.get("fetch_detail", True)),
        "api_key": data.get("api_key", ""),
        "required_socials": _as_str_list(data.get("required_socials")),
        # Не в params-боевом ключе конфига — свой параметр API; runner его
        # игнорирует, а _fire_api_callback читает именно отсюда (см. run_manager).
        "callback_url": callback_url,
    }

    # Output formats: явный пустой список означает «файлов не надо», поэтому
    # подменяем значение по умолчанию только когда поля в запросе нет.
    if data.get("output_formats") is None:
        formats = ["excel", "json"]
    else:
        formats = [f.lower() for f in _as_str_list(data.get("output_formats"))]
    unknown = [f for f in formats if f not in ("excel", "json", "csv", "map")]
    if unknown:
        warnings.append("unknown output_formats ignored: " + ", ".join(unknown))
    params["output_excel"] = "excel" in formats
    params["output_json"] = "json" in formats
    params["output_csv"] = "csv" in formats
    params["output_map"] = "map" in formats

    raw_rating = data.get("min_rating", 0)
    try:
        params["min_rating"] = float(raw_rating)
    except (TypeError, ValueError):
        params["min_rating"] = 0.0
        warnings.append(f"min_rating={raw_rating!r} is not a number — default 0 used")

    return params, []


def _wait_for_run(entry: dict, wait: int) -> None:
    """Дождаться конца прогона (не дольше wait секунд).

    Проверяем _done, а не только active: active снимается лишь через
    _FINISH_DELAY (6 с) после конца прогона — иначе запрос «догонял» бы
    «running» у уже закончившегося поиска и отдавал пустой список.
    """
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if entry.get("_done") or _entry_status(entry) not in ("queued", "running"):
            break
        time.sleep(_WAIT_POLL_S)


def _wait_for_runs(entries: list[dict], wait: int) -> None:
    """Дождаться конца всех прогонов пачки (не дольше wait секунд)."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if all(e.get("_done") or _entry_status(e) not in ("queued", "running")
               for e in entries):
            return
        time.sleep(_WAIT_POLL_S)


def _batch_entries(batch_id: str) -> list[dict]:
    """Прогоны пачки в порядке записей (batch_index из params)."""
    with run_manager._lock:
        entries = [e for e in run_manager._runs.values()
                   if str((e.get("params") or {}).get("batch_id") or "") == batch_id]
    return sorted(entries, key=lambda e: (e.get("params") or {}).get("batch_index", 0))


def _batch_status(statuses: list[str]) -> str:
    """Сводный статус пачки по статусам её прогонов."""
    if "running" in statuses:
        return "running"
    if "queued" in statuses:
        return "queued"
    if "paused" in statuses:
        return "paused"
    if "failed" in statuses:
        # Часть записей отработала, часть упала — это не «всё сломалось».
        return "partial" if "done" in statuses else "failed"
    return "done"


def _run_summary(entry: dict) -> dict:
    """Краткая сводка прогона для /batch/<id>."""
    return {
        "index":       (entry.get("params") or {}).get("batch_index"),
        "run_id":      entry.get("id", ""),
        "status":      _entry_status(entry),
        "count":       entry.get("count", 0),
        "cities":      entry.get("cities", []),
        "files":       entry.get("files", []),
        "error":       entry.get("error"),
        "progress":    _progress_payload(entry),
        "started_at":  entry.get("started_at", 0),
        "finished_at": entry.get("finished_at", 0),
    }


def _batch_files(entries: list[dict]) -> list[str]:
    """JSON-файлы всех прогонов пачки (служебные не отдаём)."""
    files: list[str] = []
    for e in entries:
        for f in e.get("files", []):
            if f.endswith(".json") and not os.path.basename(f).startswith("_"):
                files.append(f)
    return files


@bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "version": "1.0",
        "active_runs": len([r for r in run_manager._runs.values() if r.get("active")]),
    })


@bp.route("/search", methods=["POST"])
def search():
    """Start a search job.

    Request body:
    {
        "queries": ["кафе", "ресторан"],      // required
        "cities": ["Москва", "Санкт-Петербург"], // required
        "social_mode": "with_socials",          // optional STAGE-2 filter:
        //   all|with_socials|without_socials — applied to the raw records,
        //   so a different slice needs no re-crawl (collection keeps all)
        "required_socials": ["vk"],             // optional: business must have ALL of them
        "fetch_detail": true,                   // optional: collect socials from cards
        "max_pages": 15,                        // optional: 1-50
        "max_workers": 10,                      // optional: 1-20
        "output_formats": ["excel", "json"],    // optional
        "callback_url": "https://n8n.host/webhook/…", // optional: POST по завершении
        "api_key": "your-api-key"               // optional: override config key
    }

    Ответ: {"ok", "queued", "run_id", "position"?, "warnings": [...]}.
    warnings — то, что пришлось поправить в запросе (например
    "max_pages=999 clamped to 50"): клиент не должен узнать об этом по
    результатам другого прогона.
    """
    data = request.get_json(force=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    warnings: list[str] = []
    params, errors = _build_params(data, warnings)
    if errors:
        return jsonify({"error": "; ".join(errors), "errors": errors,
                        "warnings": warnings}), 400

    # Start run
    entry = run_manager.new_run()
    entry["params"] = params
    entry["cities"] = params["cities"]

    active = run_manager.active_run_id()
    if active and active != entry["id"]:
        with run_manager._lock:
            entry["queued"] = True
            entry["active"] = False
        return jsonify({
            "ok": True,
            "queued": True,
            "run_id": entry["id"],
            "position": run_manager.queue_position(entry["id"]),
            "warnings": warnings,
            "message": f"Job queued at position {run_manager.queue_position(entry['id'])}",
        })

    run_manager.start_process(entry)
    return jsonify({
        "ok": True,
        "queued": False,
        "run_id": entry["id"],
        "warnings": warnings,
        "message": "Search started",
    })


@bp.route("/batch", methods=["POST"])
def batch():
    """Запустить пачку прогонов списком записей — «воркфлоу с записями».

    Вместо набора задач по одной (в консоли или руками в конструкторе)
    автоматизация присылает СПИСОК записей — как строки таблицы: одна
    запись = один прогон. Первый стартует сразу, остальные встают в
    очередь (движок ищет по одному прогону за раз), поэтому ответ приходит
    сразу, а прогресс и результаты пачки забираются по batch_id.

    Тело:
    {
      "records": [                                   // required, ≤ 200 записей
        {"queries": ["кафе"], "cities": ["Москва"]},  // полная форма
        {"query": "автосервис", "city": "Казань"},    // короткая форма
        {"queries": ["стоматология"], "cities": ["Казань", "Самара"]}
      ],
      "defaults": {"max_pages": 5, "social_mode": "all"},   // общее для всех
      "callback_url": "https://n8n.host/webhook/…"          // событие на каждый прогон
    }

    Валидация — «всё или ничего»: если хоть одна запись неверна, ни один
    прогон не запускается, а в ответе перечислены все проблемные адреса.
    """
    data = request.get_json(force=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    raw = data.get("records")
    if raw is None:
        return jsonify({"error": "records is required (array of objects)"}), 400
    if not isinstance(raw, list) or not raw:
        return jsonify({"error": "records must be a non-empty array of objects"}), 400
    if len(raw) > _BATCH_MAX_RECORDS:
        return jsonify({
            "error": f"records must contain at most {_BATCH_MAX_RECORDS} jobs "
                     f"(got {len(raw)}) — разбейте пачку на части",
        }), 400

    defaults = data.get("defaults")
    if defaults is not None and not isinstance(defaults, dict):
        return jsonify({"error": "defaults must be an object"}), 400
    defaults = dict(defaults or {})
    batch_callback = str(data.get("callback_url")
                         or defaults.get("callback_url") or "").strip()

    # Сначала собираем и проверяем ВСЕ записи, и только потом запускаем:
    # ошибка в пятой записи не должна запускать первые четыре.
    prepared: list[tuple[int, dict, list]] = []
    all_warnings: list[str] = []
    all_errors: list[str] = []
    for idx, record in enumerate(raw):
        if not isinstance(record, dict):
            all_errors.append(f"records[{idx}]: must be an object")
            continue
        rec = dict(record)
        # Короткая форма: одна строка таблицы часто даёт один запрос и город.
        if not rec.get("queries") and rec.get("query"):
            rec["queries"] = [rec["query"]]
        if not rec.get("cities") and rec.get("city"):
            rec["cities"] = [rec["city"]]
        merged = {**defaults, **rec}
        if batch_callback and not merged.get("callback_url"):
            merged["callback_url"] = batch_callback
        rec_warnings: list[str] = []
        params, errors = _build_params(merged, rec_warnings)
        if errors:
            all_errors.extend(f"records[{idx}]: {e}" for e in errors)
            continue
        # Предупреждения нумеруем: в пачке важно, к какой записи относится
        # «max_pages=999 clamped to 50».
        all_warnings.extend(f"records[{idx}]: {w}" for w in rec_warnings)
        prepared.append((idx, params, rec_warnings))

    if all_errors:
        return jsonify({"error": "; ".join(all_errors), "errors": all_errors,
                        "warnings": all_warnings}), 400

    batch_id = uuid.uuid4().hex[:8]
    runs: list[dict] = []
    for idx, params, rec_warnings in prepared:
        params["batch_id"] = batch_id
        params["batch_index"] = idx
        # Свободен ли движок — смотрим ДО создания записи: new_run() помечает
        # новую запись активной, и она заняла бы сама себя (первая запись
        # пачки тогда встала бы в очередь к самой себе и никогда не стартовала).
        busy = run_manager.active_run_id()
        entry = run_manager.new_run()
        entry["params"] = params
        entry["cities"] = params["cities"]
        if busy:
            with run_manager._lock:
                entry["queued"] = True
                entry["active"] = False
            position = run_manager.queue_position(entry["id"])
        else:
            run_manager.start_process(entry)
            position = 0
        runs.append({
            "index":    idx,
            "run_id":   entry["id"],
            "queued":   bool(entry.get("queued")),
            "position": position,
            "queries":  params["queries"],
            "cities":   params["cities"],
            "warnings": rec_warnings,
        })

    return jsonify({
        "ok": True,
        "batch_id": batch_id,
        "count": len(runs),
        "queued": sum(1 for r in runs if r["queued"]),
        "warnings": all_warnings,
        "runs": runs,
        "message": f"Batch of {len(runs)} runs accepted",
    })


@bp.route("/batch/<batch_id>", methods=["GET"])
def batch_status(batch_id):
    """Сводка по пачке: статус и прогресс каждого прогона + общий прогресс.

    Query params:
      wait — сколько секунд ждать конца всей пачки (0…300)
    """
    wait = _int_arg(request.args.get("wait"), 0, 0, _WAIT_MAX_S)
    entries = _batch_entries(batch_id)
    if not entries:
        return jsonify({"error": "Batch not found"}), 404
    if wait:
        _wait_for_runs(entries, wait)

    statuses = [_entry_status(e) for e in entries]
    progress = {"cities_done": 0, "cities_total": 0, "records_so_far": 0}
    for e in entries:
        p = _progress_payload(e)
        for key in progress:
            progress[key] += p[key]
    return jsonify({
        "batch_id": batch_id,
        "status":   _batch_status(statuses),
        "count":    len(entries),
        "queued":   statuses.count("queued"),
        "running":  statuses.count("running"),
        "paused":   statuses.count("paused"),
        "done":     statuses.count("done"),
        "failed":   statuses.count("failed"),
        "progress": progress,
        # Ошибки отдельным списком: по ним сразу видно, какие записи упали
        # и почему, не разбирая runs.
        "errors": [{"index": (e.get("params") or {}).get("batch_index"),
                    "run_id": e.get("id", ""),
                    "error": e.get("error")} for e in entries if e.get("error")],
        "runs": [_run_summary(e) for e in entries],
    })


@bp.route("/batch/<batch_id>/results", methods=["GET"])
def batch_results(batch_id):
    """Организации всей пачки одним списком (склейка городов, без дублей).

    Query params:
      wait   — дождаться конца всех прогонов пачки (0…300)
      limit  — максимум записей в ответе (0 = все)
      offset — сколько записей пропустить
    """
    wait = _int_arg(request.args.get("wait"), 0, 0, _WAIT_MAX_S)
    limit = _int_arg(request.args.get("limit"), 0, 0)      # 0 = без лимита
    offset = _int_arg(request.args.get("offset"), 0, 0)

    entries = _batch_entries(batch_id)
    if not entries:
        return jsonify({"error": "Batch not found"}), 404
    if wait:
        _wait_for_runs(entries, wait)

    files = _batch_files(entries)
    records = _load_results(files, cache_key=batch_id)
    total = len(records)
    page = records[offset:offset + limit] if limit else records[offset:]
    return jsonify({
        "batch_id": batch_id,
        "status":   _batch_status([_entry_status(e) for e in entries]),
        "count":    len(page),
        "total":    total,
        "offset":   offset,
        "limit":    limit,
        "files":    files,
        "errors": [{"index": (e.get("params") or {}).get("batch_index"),
                    "run_id": e.get("id", ""),
                    "error": e.get("error")} for e in entries if e.get("error")],
        "results":  page,
    })


@bp.route("/runs", methods=["GET"])
def runs():
    """Runs of this session: id, статус, города и файлы.

    По run_id из ответа дальше спрашивается /status и /results.
    """
    return jsonify({"runs": run_manager.list_runs()})


@bp.route("/status", methods=["GET"])
def status():
    """Get status of a run or all runs.

    Query params:
      run_id — optional, specific run to check

    Ответ по прогону: run_id, active, queued, status, cities, files,
    started_at + count, error, progress, finished_at. `error` заполнен у
    status="failed", progress — у идущих прогонов.
    """
    run_id = request.args.get("run_id", "")
    if run_id:
        entry = run_manager.get(run_id)
        if not entry:
            return jsonify({"error": "Run not found"}), 404
        return jsonify({
            "run_id": entry["id"],
            "active": entry.get("active", False),
            "queued": entry.get("queued", False),
            "status": _entry_status(entry),
            "cities": entry.get("cities", []),
            "files": entry.get("files", []),
            "started_at": entry.get("started_at", 0),
            "count": entry.get("count", 0),
            "error": entry.get("error"),
            "progress": _progress_payload(entry),
            "finished_at": entry.get("finished_at", 0),
        })
    return jsonify(run_manager.status())


@bp.route("/results", methods=["GET"])
def results():
    """Get the organisations of a run as JSON.

    Query params:
      run_id — optional; без него берётся активный/стоящий в очереди прогон
      wait   — сколько секунд ждать конца прогона (0…300, по умолчанию 0):
               запрос «висит», пока поиск идёт, и отдаёт готовые записи
      limit  — максимум записей в ответе (0 = все, по умолчанию)
      offset — сколько записей пропустить (для страниц больших ответов)

    Ответ: {run_id, status, count, total, offset, limit, files, error,
    progress, results}.
    status — queued | running | paused | done | failed; count — записей в
    ЭТОМ ответе, total — всего после склейки и схлопывания дублей;
    results — страница организаций всех JSON-файлов прогона. У failed в
    error лежит причина, а results пуст: это не «ничего не найдено».
    """
    run_id = request.args.get("run_id", "")
    wait = _int_arg(request.args.get("wait"), 0, 0, _WAIT_MAX_S)
    limit = _int_arg(request.args.get("limit"), 0, 0)      # 0 = без лимита
    offset = _int_arg(request.args.get("offset"), 0, 0)

    entry = _pick_entry(run_id)
    if run_id and not entry:
        return jsonify({"error": "Run not found"}), 404
    if not entry:
        return jsonify({"error": "No active or recent run found"}), 404

    if wait:
        _wait_for_run(entry, wait)

    files = [f for f in entry.get("files", [])
             if f.endswith(".json") and not os.path.basename(f).startswith("_")]
    records = _load_results(files, cache_key=entry.get("id", ""))
    total = len(records)
    page = records[offset:offset + limit] if limit else records[offset:]
    return jsonify({
        "run_id": entry.get("id", ""),
        "status": _entry_status(entry),
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "files": files,
        "error": entry.get("error"),
        "progress": _progress_payload(entry),
        "results": page,
    })


@bp.route("/stop", methods=["POST"])
def stop():
    """Stop a running search.

    Query params:
      run_id — optional, specific run to stop
      pause  — 1: не стоп, а пауза (прогон можно будет продолжить)
    """
    run_id = request.args.get("run_id", "")
    pause = bool(_int_arg(request.args.get("pause"), 0, 0, 1))
    run_manager.stop_run(run_id, pause=pause)
    return jsonify({"ok": True, "paused": pause, "message": "Stop requested"})


@bp.route("/skip-city", methods=["POST"])
def skip_city():
    """Skip the current city in a multi-city run.

    Query params:
      run_id — optional
    """
    run_id = request.args.get("run_id", "")
    info = run_manager.skip_city_info(run_id)
    run_manager.skip_city(run_id)
    return jsonify({
        "ok": True,
        "city": info["city"],
        "records": info["records_found"],
        "message": f"Skipped city '{info['city']}' ({info['records_found']} records saved)",
    })


# ── OpenAPI ────────────────────────────────────────────────────────
# Спецификация отдаётся самим приложением, чтобы сторонние инструменты
# (Postman, n8n «Import from OpenAPI», генераторы клиентов) могли подключиться
# без ручного описания. Порт может отличаться (5000/5010/5050) — в servers
# указан дефолт, а в описании сказано смотреть консоль при старте.

def _openapi_spec() -> dict:
    """OpenAPI 3.0-описание /api/v1 — держится рядом с кодом эндпоинтов."""
    org_props = {
        "name": {"type": "string"},
        "city": {"type": "string"},
        "address": {"type": "string"},
        "category": {"type": "string"},
        "phone": {"type": "string", "description": "Номера через запятую"},
        "rating": {"type": ["number", "null"]},
        "reviews_count": {"type": ["number", "null"]},
        "vk": {"type": "string"},
        "telegram": {"type": "string"},
        "instagram": {"type": "string"},
        "whatsapp": {"type": "string"},
        "site": {"type": "string"},
        "yandex_maps_url": {"type": "string"},
        "lead_score": {"type": "number", "description": "Оценка лида 0–90"},
    }
    run_status = {
        "type": "string", "enum": ["queued", "running", "paused", "done", "failed"],
    }
    progress = {
        "type": "object",
        "description": "Сколько городов пройдено и сколько записей уже найдено",
        "properties": {
            "cities_done": {"type": "integer"},
            "cities_total": {"type": "integer"},
            "records_so_far": {"type": "integer"},
        },
    }
    job_props = {
        "queries": {"type": "array", "items": {"type": "string"}},
        "cities": {"type": "array", "items": {"type": "string"}},
        "query": {"type": "string", "description": "Короткая форма: один запрос"},
        "city": {"type": "string", "description": "Короткая форма: один город"},
        "social_mode": {
            "type": "string", "enum": ["all", "with_socials", "without_socials"],
        },
        "required_socials": {
            "type": "array",
            "items": {"type": "string", "enum": ["vk", "instagram", "telegram", "whatsapp"]},
        },
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 50},
        "max_workers": {"type": "integer", "minimum": 1, "maximum": 20},
        "min_rating": {"type": "number"},
        "min_reviews": {"type": "integer"},
        "use_grid": {"type": "boolean"},
        "fetch_detail": {"type": "boolean"},
        "output_formats": {
            "type": "array",
            "items": {"type": "string", "enum": ["excel", "json", "csv", "map"]},
        },
        "callback_url": {
            "type": "string", "format": "uri",
            "description": (
                "POST {event,run_id,status,count,files,error,progress} по "
                "завершении прогона — вместо опроса (n8n Webhook)"
            ),
        },
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Yandex-Parser API",
            "version": "1.0",
            "description": (
                "Локальный API парсера Яндекс.Карт: запуск поиска (по одному "
                "запросу или пачкой записей) и получение организаций. Сервер "
                "слушает только 127.0.0.1 — доступен с этого же компьютера, "
                "ключ не нужен. Порт смотрите в консоли при старте "
                "(5000/5010/5050)."
            ),
        },
        "servers": [{"url": "http://127.0.0.1:5000"}],
        "paths": {
            "/api/v1/health": {
                "get": {
                    "summary": "Проверка, что сервис жив",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                    },
                },
            },
            "/api/v1/search": {
                "post": {
                    "summary": "Запустить поиск (асинхронно — вернётся run_id)",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["queries", "cities"],
                            "properties": job_props,
                        }}},
                    },
                    "responses": {
                        "200": {"description": "{ok, queued, run_id, position?, warnings}"},
                        "400": {"description": "Неверный запрос"},
                    },
                },
            },
            "/api/v1/batch": {
                "post": {
                    "summary": "Запустить пачку прогонов списком записей",
                    "description": (
                        "Одна запись = один прогон. Первый стартует сразу, "
                        "остальные встают в очередь. Валидация «всё или "
                        "ничего»: при ошибке в любой записи ничего не "
                        "запускается."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["records"],
                            "properties": {
                                "records": {
                                    "type": "array", "maxItems": _BATCH_MAX_RECORDS,
                                    "items": {"type": "object", "properties": job_props},
                                },
                                "defaults": {
                                    "type": "object",
                                    "description": "Общие поля для всех записей",
                                    "properties": job_props,
                                },
                                "callback_url": {
                                    "type": "string", "format": "uri",
                                    "description": "Подставляется записям без своего callback_url",
                                },
                            },
                        }}},
                    },
                    "responses": {
                        "200": {"description": "{ok, batch_id, count, queued, runs, warnings}"},
                        "400": {"description": "Неверный запрос (в errors — все проблемные записи)"},
                    },
                },
            },
            "/api/v1/batch/{batch_id}": {
                "get": {
                    "summary": "Сводка и прогресс пачки",
                    "parameters": [
                        {"name": "batch_id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "wait", "in": "query",
                         "schema": {"type": "integer", "minimum": 0, "maximum": 300}},
                    ],
                    "responses": {
                        "200": {"description": "{batch_id, status, count, done, failed, errors, progress, runs}"},
                        "404": {"description": "Пачка не найдена"},
                    },
                },
            },
            "/api/v1/batch/{batch_id}/results": {
                "get": {
                    "summary": "Организации всей пачки одним списком",
                    "parameters": [
                        {"name": "batch_id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "wait", "in": "query",
                         "schema": {"type": "integer", "minimum": 0, "maximum": 300}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                    ],
                    "responses": {
                        "200": {"description": "Записи всех прогонов пачки без дублей"},
                        "404": {"description": "Пачка не найдена"},
                    },
                },
            },
            "/api/v1/runs": {
                "get": {
                    "summary": "Прогоны текущей сессии",
                    "responses": {"200": {"description": "{runs: [...] }"}},
                },
            },
            "/api/v1/status": {
                "get": {
                    "summary": "Статус прогона или всей очереди",
                    "parameters": [{
                        "name": "run_id", "in": "query",
                        "schema": {"type": "string"},
                    }],
                    "responses": {
                        "200": {"description": "Статус (см. описание полей results)"},
                        "404": {"description": "Прогон не найден"},
                    },
                },
            },
            "/api/v1/results": {
                "get": {
                    "summary": "Организации прогона (JSON)",
                    "description": (
                        "JSON-файлы городов склеиваются, дубли одной организации "
                        "схлопываются. wait дожидается конца, limit/offset "
                        "постраничивают большой ответ."
                    ),
                    "parameters": [
                        {"name": "run_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "wait", "in": "query", "schema": {"type": "integer", "minimum": 0, "maximum": 300}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Организации прогона",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "run_id": {"type": "string"},
                                    "status": run_status,
                                    "count": {"type": "integer", "description": "Записей в ответе"},
                                    "total": {"type": "integer", "description": "Всего записей"},
                                    "offset": {"type": "integer"},
                                    "limit": {"type": "integer"},
                                    "files": {"type": "array", "items": {"type": "string"}},
                                    "error": {
                                        "type": ["string", "null"],
                                        "description": "Причина падения при status=failed",
                                    },
                                    "progress": progress,
                                    "results": {
                                        "type": "array",
                                        "items": {"type": "object", "properties": org_props},
                                    },
                                },
                            }}},
                        },
                        "404": {"description": "Прогон не найден"},
                    },
                },
            },
            "/api/v1/stop": {
                "post": {
                    "summary": "Остановить поиск",
                    "parameters": [
                        {"name": "run_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "pause", "in": "query",
                         "description": "1 — пауза вместо стопа (можно продолжить)",
                         "schema": {"type": "integer", "enum": [0, 1]}},
                    ],
                    "responses": {"200": {"description": "{ok, paused}"}},
                },
            },
            "/api/v1/skip-city": {
                "post": {
                    "summary": "Пропустить текущий город",
                    "parameters": [
                        {"name": "run_id", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "{ok, city, records}"}},
                },
            },
        },
    }


@bp.route("/openapi.json", methods=["GET"])
def openapi_json():
    """OpenAPI-спецификация этого API (для Postman/n8n/генераторов клиентов)."""
    return jsonify(_openapi_spec())
