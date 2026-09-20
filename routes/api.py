"""Utility routes: reviewed, export, results, download, API key test."""
import os
import io
import csv
import json
import shutil

from flask import Blueprint, request, Response, send_from_directory, jsonify

# Writable dir: next to the .exe when frozen, project root from source
try:
    import paths as _paths
    OUTPUT_DIR = _paths.output_dir()
except Exception:
    OUTPUT_DIR = "output"
REVIEWED_FILE = os.path.join(OUTPUT_DIR, "_reviewed.json")

bp = Blueprint("api", __name__)


def _json_body() -> dict:
    """JSON body of a request — including the beacon form.

    `navigator.sendBeacon` (used when the tab closes, so the reviewed marks
    are not lost) may arrive as text/plain; Flask then leaves get_json()
    empty, and the request would silently fall back to the default view.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = request.get_data(as_text=True) or ""
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _load_reviewed() -> dict:
    if os.path.exists(REVIEWED_FILE):
        try:
            with open(REVIEWED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_reviewed(data: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(REVIEWED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


GITHUB_REPO = "ScarFace11/Yandex-Buisnes-Parser"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/static/version.json"


@bp.route("/")
def index():
    return __import__("flask").render_template("index.html")


@bp.route("/check-version")
def check_version():
    """Check if a newer version is available on GitHub."""
    import requests as req_lib
    from config import APP_VERSION
    # DEV-сборка не обновляется публичными релизами — баннер не показываем.
    try:
        from config import is_dev_build
        if is_dev_build():
            return jsonify({"current": APP_VERSION, "newer": False, "dev": True})
    except Exception:
        pass
    try:
        r = req_lib.get(GITHUB_RAW_URL, timeout=8,
                        headers={"User-Agent": "YandexParser/2.0"})
        if r.status_code == 200:
            remote = r.json()
            remote_ver = remote.get("version", "0.0.0")
            current = APP_VERSION
            # Simple version compare: "2.2.0" > "2.1.0"
            def _ver_tuple(v):
                return tuple(int(x) for x in v.split(".") if x.isdigit())
            newer = _ver_tuple(remote_ver) > _ver_tuple(current)
            return jsonify({
                "current": current,
                "remote": remote_ver,
                "newer": newer,
                "changelog": remote.get("changelog", ""),
                "download_url": "https://github.com/ScarFace11/Yandex-Buisnes-Parser/archive/refs/heads/main.zip",
            })
        return jsonify({"current": APP_VERSION, "newer": False, "error": f"HTTP {r.status_code}"})
    except Exception as exc:
        return jsonify({"current": APP_VERSION, "newer": False, "error": str(exc)})


@bp.route("/reviewed", methods=["GET"])
def get_reviewed():
    return jsonify(_load_reviewed())


@bp.route("/reviewed", methods=["POST"])
def set_reviewed():
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    state_val = bool(data.get("reviewed", False))
    if not url:
        return jsonify({"error": "url required"}), 400
    reviewed = _load_reviewed()
    if state_val:
        reviewed[url] = True
    else:
        reviewed.pop(url, None)
    _save_reviewed(reviewed)
    return jsonify({"ok": True})


@bp.route("/results/<path:filename>")
def results(filename):
    allowed = os.path.realpath(OUTPUT_DIR)
    filepath = os.path.realpath(os.path.join(allowed, filename))
    if not filepath.startswith(allowed + os.sep) or not os.path.isfile(filepath):
        return jsonify({"error": "not found"}), 404
    try:
        with open(filepath, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@bp.route("/download-zip")
def download_zip():
    """Bundle several output files into one ZIP archive on the fly.
    Usage: /download-zip?files=name1.xlsx|name2.json (| separated)."""
    import zipfile
    from flask import send_file
    raw = request.args.get("files", "")
    names = [n.strip() for n in raw.split("|") if n.strip()]
    if not names:
        return jsonify({"error": "no files requested"}), 400
    # Only files that actually exist in OUTPUT_DIR; reject path traversal
    allowed = os.path.realpath(OUTPUT_DIR)
    safe_names = []
    for n in names:
        p = os.path.realpath(os.path.join(allowed, n))
        if p.startswith(allowed + os.sep) and os.path.isfile(p):
            safe_names.append((p, os.path.basename(n)))
    if not safe_names:
        return jsonify({"error": "no valid files"}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, base in safe_names:
            zf.write(path, arcname=base)
    buf.seek(0)
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"parser_results_{stamp}.zip")


@bp.route("/save-api-key", methods=["POST"])
def save_api_key():
    """Save YANDEX_API_KEY to .env file and reload it (legacy single-key form)."""
    data = request.get_json(force=True) or {}
    return _write_env_keys({"YANDEX_API_KEY": data.get("api_key", "")})


@bp.route("/save-api-keys", methods=["POST"])
def save_api_keys():
    """Save YANDEX_API_KEY and/or TWOGIS_API_KEY to .env and hot-reload them.

    One button for both key fields: each non-empty field overwrites its key,
    empty fields are left untouched (the .env value keeps working).
    """
    data = request.get_json(force=True) or {}
    return _write_env_keys({
        "YANDEX_API_KEY": data.get("yandex_api_key", ""),
        "TWOGIS_API_KEY": data.get("twogis_api_key", ""),
        "VK_TOKEN": data.get("vk_token", ""),
    })


def _write_env_keys(keys: dict):
    """Write the given non-empty KEY=value pairs into .env (create/replace
    per key), reload them into config so a restart isn't needed.
    Returns a Flask response."""
    from pathlib import Path

    # Sanitize: strip quotes/whitespace, forbid characters that would corrupt
    # the 'KEY = "value"' line format (quotes, #, newlines).
    import re as _re_sanitize
    clean = {}
    for env_name, raw in keys.items():
        val = (raw or "").strip().strip("\"'").strip()
        if not val:
            continue
        if _re_sanitize.search(r'[\r\n#"]', val):
            return jsonify({"ok": False,
                            "error": f"{env_name}: ключ содержит недопустимые символы (кавычки, # или переводы строк)"}), 400
        clean[env_name] = val
    if not clean:
        return jsonify({"ok": False, "error": "Введите хотя бы один ключ"}), 400

    # Прежний ключ 2GIS — чтобы отличить «ввели новый» от «пересохранили тот же».
    try:
        import config as _cfg
        old_twogis_key = (_cfg.TWOGIS_API_KEY or "").strip()
    except Exception:
        old_twogis_key = os.environ.get("TWOGIS_API_KEY", "").strip()

    # .env location: next to the .exe when frozen, project root from source
    try:
        import paths as _paths
        env_path = _paths.env_path()
    except Exception:
        project_root = Path(__file__).resolve().parent.parent
        env_path = project_root / ".env"
    if not env_path.exists():
        alt = env_path.parent / "yandex_maps_parser" / ".env"
        if alt.exists():
            env_path = alt

    try:
        # Read existing .env or create new
        lines = []
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # Replace existing lines or append at the end
        remaining = dict(clean)
        for i, line in enumerate(lines):
            stripped = line.strip()
            for env_name in list(remaining):
                if stripped.startswith(env_name) and "=" in stripped:
                    lines[i] = f'{env_name} = "{remaining.pop(env_name)}"\n'
                    break
        for env_name, val in remaining.items():
            lines.append(f'\n{env_name} = "{val}"\n')

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Hot-reload into the running process (no restart needed)
        for env_name, val in clean.items():
            os.environ[env_name] = val
        try:
            import config
            if "YANDEX_API_KEY" in clean:
                config.YANDEX_API_KEY = clean["YANDEX_API_KEY"]
            if "TWOGIS_API_KEY" in clean:
                config.TWOGIS_API_KEY = clean["TWOGIS_API_KEY"]
            if "VK_TOKEN" in clean:
                config.VK_TOKEN = clean["VK_TOKEN"]
        except Exception:
            pass
        try:
            from yandex_maps_parser import state as pstate
            if "TWOGIS_API_KEY" in clean:
                pstate.TWOGIS_API_KEY = clean["TWOGIS_API_KEY"]
        except Exception:
            pass

        # Новый ключ 2GIS = новая месячная квота: счётчик потраченных токенов
        # относится к СТАРОМУ ключу и без сброса показывал бы новый как
        # исчерпанный. Один и тот же ключ счётчик не трогает.
        quota_reset = False
        if "TWOGIS_API_KEY" in clean and clean["TWOGIS_API_KEY"] != old_twogis_key:
            try:
                from yandex_maps_parser import twogis as _tg
                _tg.quota_reset_for_new_key()
                quota_reset = True
            except Exception:
                pass

        saved = ", ".join(sorted(clean))
        return jsonify({"ok": True, "message": f"Сохранено в {env_path.name}: {saved}",
                        "path": str(env_path), "quota_reset": quota_reset})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/export-filtered", methods=["POST"])
def export_filtered():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    fmt  = data.get("format", "csv")

    HEADERS = ["#", "✓ Просмотрено", "Название", "Категория", "Адрес", "Телефон",
               "VK", "Instagram", "Telegram", "WhatsApp",
               "Агрегатор", "Ссылка", "Запрос"]
    FIELDS = ["_idx", "_reviewed", "name", "category", "address", "phone",
              "vk", "instagram", "telegram", "whatsapp",
              "aggregator_url", "yandex_maps_url", "query"]

    # Marks live in _reviewed.json — merge them into the export so the
    # «Просмотрено» column is never empty (mirrors the table checkboxes).
    _rev = _load_reviewed()

    def _val(row, f):
        if f == "_reviewed":
            key = _review_key(row)
            return bool(key and _rev.get(key))
        if f == "yandex_maps_url":
            # «Ссылка» в выгрузке выборки: карточка Яндекса, а для 2GIS-записей
            # — карточка 2ГИС (раньше столбец был пустым на 2GIS-запусках).
            return row.get("yandex_maps_url") or row.get("twogis_url") or ""
        return row.get(f, "")

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        for i, row in enumerate(rows, 1):
            writer.writerow([i if f == "_idx" else _val(row, f) for f in FIELDS])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=filtered_export.csv"}
        )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Результаты"

    header_fill = PatternFill("solid", fgColor="1A6B3C")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    for col, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for i, row in enumerate(rows, 2):
        for col, f in enumerate(FIELDS, 1):
            val = i - 1 if f == "_idx" else _val(row, f)
            ws.cell(row=i, column=col, value=val)

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 8), 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=filtered_export.xlsx"}
    )


# ── Logs ────────────────────────────────────────────────────

@bp.route("/logs/list")
def list_log_files():
    """List all log files with metadata."""
    from run_logger import list_logs
    return jsonify({"logs": list_logs()})


@bp.route("/logs/view/<path:filename>")
def view_log(filename):
    """View a log file as plain text."""
    from run_logger import LOGS_DIR
    safe = os.path.basename(filename)
    fpath = os.path.join(LOGS_DIR, safe)
    if not os.path.isfile(fpath):
        return jsonify({"error": "Log not found"}), 404
    with open(fpath, encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"inline; filename={safe}"})


@bp.route("/logs/download/<path:filename>")
def download_log(filename):
    """Download a log file."""
    from run_logger import LOGS_DIR
    safe = os.path.basename(filename)
    if not safe.endswith(".log"):
        return jsonify({"error": "Invalid file"}), 400
    fpath = os.path.join(LOGS_DIR, safe)
    if not os.path.isfile(fpath):
        return jsonify({"error": "Log not found"}), 404
    return send_from_directory(LOGS_DIR, safe, as_attachment=True)


@bp.route("/twogis/key-status")
def twogis_key_status():
    """Whether a 2GIS API key is configured (.env / config or state)."""
    key = ""
    try:
        from yandex_maps_parser import state as pstate
        key = pstate.TWOGIS_API_KEY or ""
    except Exception:
        pass
    if not key:
        try:
            from config import TWOGIS_API_KEY
            key = TWOGIS_API_KEY or ""
        except Exception:
            pass
    return jsonify({"present": bool(key.strip())})


@bp.route("/api-keys/status")
def api_keys_status():
    """Which API keys are configured (.env / config) — for the sidebar badge.

    Returns booleans only, never the keys themselves.
    """
    from config import YANDEX_API_KEY, TWOGIS_API_KEY
    from config import VK_TOKEN
    yk = (YANDEX_API_KEY or "").strip()
    gk = (TWOGIS_API_KEY or "").strip()
    vk = (VK_TOKEN or "").strip()
    # Runtime overrides (state) may carry keys the UI typed for this run.
    try:
        from yandex_maps_parser import state as pstate
        yk = yk or (pstate.YANDEX_API_KEY or "").strip()
        gk = gk or (pstate.TWOGIS_API_KEY or "").strip()
    except Exception:
        pass
    return jsonify({"yandex": bool(yk), "twogis": bool(gk), "vk": bool(vk)})


@bp.route("/cache/stats")
def cache_stats_route():
    """Return cache statistics."""
    try:
        from yandex_maps_parser.cache import cache_stats
        return jsonify(cache_stats())
    except Exception:
        return jsonify({"total": 0, "valid": 0, "expired": 0})


@bp.route("/analytics")
def analytics_route():
    """Return real-time analytics."""
    try:
        from yandex_maps_parser.http_client import get_analytics
        return jsonify(get_analytics())
    except Exception:
        return jsonify({})


# ── Search History ──────────────────────────────────────────

@bp.route("/history")
def history_list():
    """List search history."""
    from search_history import get_history, get_stats
    limit = request.args.get("limit", 50, type=int)
    return jsonify({
        "history": get_history(limit),
        "stats": get_stats(),
    })


@bp.route("/history/<run_id>")
def history_entry(run_id):
    """Get a specific history entry."""
    from search_history import get_entry
    entry = get_entry(run_id)
    if not entry:
        return jsonify({"error": "Entry not found"}), 404
    return jsonify(entry)


@bp.route("/history/<run_id>", methods=["DELETE"])
def history_delete(run_id):
    """Delete a history entry."""
    from search_history import delete_entry
    if delete_entry(run_id):
        return jsonify({"ok": True})
    return jsonify({"error": "Entry not found"}), 404


@bp.route("/history/clear", methods=["POST"])
def history_clear():
    """Clear all history."""
    from search_history import clear_history
    clear_history()
    return jsonify({"ok": True})


@bp.route("/seen/clear", methods=["POST"])
def seen_clear():
    """Clear global _seen.json so previously processed businesses are re-scanned."""
    seen_path = os.path.join(OUTPUT_DIR, "_seen.json")
    if os.path.exists(seen_path):
        try:
            with open(seen_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = len(data.get("seen_urls", []))
        except Exception:
            count = 0
        os.remove(seen_path)
        return jsonify({"ok": True, "cleared": count})
    return jsonify({"ok": True, "cleared": 0})


@bp.route("/seen/status")
def seen_status():
    """Show how many businesses are in the global seen store."""
    seen_path = os.path.join(OUTPUT_DIR, "_seen.json")
    if os.path.exists(seen_path):
        try:
            with open(seen_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = len(data.get("seen_urls", []))
            saved_at = data.get("saved_at", "unknown")
            return jsonify({"count": count, "saved_at": saved_at})
        except Exception:
            pass
    return jsonify({"count": 0, "saved_at": None})


# ═══════════════════════════════════════════════════════════════
#  Two-stage pipeline: raw / processed views + re-filtering
# ═══════════════════════════════════════════════════════════════

def _raw_dir() -> str:
    try:
        import paths as _p
        return _p.raw_dir()
    except Exception:
        return os.path.join(OUTPUT_DIR, "raw")


def _processed_dir() -> str:
    try:
        import paths as _p
        return _p.processed_dir()
    except Exception:
        return os.path.join(OUTPUT_DIR, "processed")


def _run_state():
    from yandex_maps_parser import state as _state
    return _state


def _archive_root() -> str:
    """output/_archive/ — root of every dated archive folder (may not exist)."""
    return os.path.join(OUTPUT_DIR, "_archive")


def _archive_today() -> str:
    """output/_archive/YYYY-MM-DD/ — created on demand (same as paths.archive_dir)."""
    try:
        import paths as _p
        return _p.archive_dir()
    except Exception:
        d = os.path.join(_archive_root(), __import__("datetime").date.today().isoformat())
        os.makedirs(d, exist_ok=True)
        return d


def _archive_index_path() -> str:
    return os.path.join(_archive_root(), "_index.json")


def _load_archive_index() -> dict:
    """{archived rel path → original rel path} so files can be restored."""
    try:
        with open(_archive_index_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_archive_index(data: dict) -> None:
    try:
        os.makedirs(_archive_root(), exist_ok=True)
        with open(_archive_index_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _unique_path(path: str) -> str:
    """path, path_1, path_2 … — never overwrite an existing file."""
    if not os.path.exists(path):
        return path
    directory, base = os.path.split(path)
    stem, dot, ext = base.rpartition(".")
    stem = stem or base
    i = 1
    while True:
        cand = os.path.join(directory, f"{stem}_{i}{dot}{ext}")
        if not os.path.exists(cand):
            return cand
        i += 1


# Only these top-level folders under output/ may be read, archived or deleted
# through the file browser / results routes.
_PUBLIC_DIRS = ("raw", "processed", "_archive")

SOCIAL_KEYS = ("vk", "telegram", "whatsapp", "instagram")

VIEWS = ("raw", "processed", "all")

# records-count cache: (abspath, mtime_ns, size) → int | None (unreadable)
_REC_CACHE: dict = {}
_REC_CACHE_MAX = 512


def _safe_output_file(rel: str) -> str | None:
    """Resolve a client-given relative path to a real file inside output/{raw,
    processed,_archive}. Returns None for anything else (traversal, absolute
    paths, internal files like _seen.json, other top-level folders)."""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    root = os.path.realpath(OUTPUT_DIR)
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    top = os.path.relpath(full, root).split(os.sep)[0]
    if top not in _PUBLIC_DIRS:
        return None
    return full


def _rel_output(path: str) -> str:
    """Posix-style path relative to output/ (for the API + UI)."""
    return os.path.relpath(path, OUTPUT_DIR).replace(os.sep, "/")


def _review_key(rec: dict) -> str:
    """Stable identity of a record for the «просмотрено» mark.

    Card URL first (yandex → 2gis), then a name|city|address composite for
    rows without a card. Mirrored by reviewKey() in app.js — keep in sync.
    """
    for field in ("yandex_maps_url", "twogis_url"):
        val = str(rec.get(field) or "").strip()
        if val:
            return val
    name = str(rec.get("name") or "").strip()
    addr = str(rec.get("address") or "").strip()
    if not (name or addr):
        return ""
    city = str(rec.get("city") or "").strip()
    return "n:" + "|".join((name, city, addr))


def _safe_http_url(url: str) -> str:
    """Only http(s) links ever reach the UI / clipboard."""
    url = str(url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def _read_records_file(path: str) -> list:
    """Read one results file (xlsx/json) tolerantly; [] when unreadable."""
    try:
        if path.lower().endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        from yandex_maps_parser.exporters import _records_from_xlsx
        return _records_from_xlsx(path)
    except Exception:
        return []


def _count_records(path: str) -> int | None:
    """Row count of a results file, cached by (path, mtime, size)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    ck = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    if ck in _REC_CACHE:
        return _REC_CACHE[ck]
    try:
        low = path.lower()
        if low.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            n: int | None = len(data) if isinstance(data, list) else 0
        elif low.endswith(".xlsx"):
            # Validate the workbook first: _records_from_xlsx swallows read
            # errors, so a corrupt/partial file would otherwise look like an
            # empty table instead of a problem the user should see.
            with open(path, "rb") as fh:
                if fh.read(2) != b"PK":
                    raise ValueError("не похоже на xlsx")
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                next(wb.active.iter_rows(values_only=True))
            finally:
                wb.close()
            n = len(_read_records_file(path))
        else:  # csv — header + data lines
            with open(path, encoding="utf-8", errors="ignore") as fh:
                n = max(0, sum(1 for _ in fh) - 1)
    except Exception:
        n = None
    if len(_REC_CACHE) >= _REC_CACHE_MAX:
        _REC_CACHE.clear()
    _REC_CACHE[ck] = n
    return n


def _is_result_file(name: str) -> bool:
    """Real results file: xlsx/json, not an internal (`_`) or Excel lock (`~$`)."""
    return (name.lower().endswith((".xlsx", ".json"))
            and name[:1] not in ("_", "~") and not name.startswith("~$"))


# Marker written by RunManager.start_process for every search that starts.
_CURRENT_SEARCH_FILE = ".current_search.json"


def _current_search() -> dict:
    """{run_id, started_at, cities, queries} of the current (last) search.

    Empty dict when this installation never ran a search (first launch of the
    .exe, files copied into output/ by hand). Callers then fall back to the
    whole folder so nothing disappears from the UI.
    """
    try:
        with open(os.path.join(OUTPUT_DIR, _CURRENT_SEARCH_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and float(data.get("started_at") or 0) > 0:
            return data
    except Exception:
        pass
    return {}


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _view_files(view: str, scope: str = "current") -> list[str]:
    """Absolute paths of every file backing a results view (raw / processed).

    scope="current" (default) keeps only the files of the current search —
    everything written after it started, so a later «Применить фильтры заново»
    is included too. Older searches stay reachable through «История файлов»
    (open a single file) or `scope=all`.
    """
    out: list[str] = []
    if view in ("raw", "all"):
        raw_d = _raw_dir()
        if os.path.isdir(raw_d):
            out.extend(os.path.join(raw_d, f) for f in sorted(os.listdir(raw_d))
                       if _is_result_file(f))
    if view in ("processed", "all"):
        proc_d = _processed_dir()
        if os.path.isdir(proc_d):
            for sub in ("json", "excel"):
                sd = os.path.join(proc_d, sub)
                if os.path.isdir(sd):
                    out.extend(os.path.join(sd, f) for f in sorted(os.listdir(sd))
                               if _is_result_file(f))
    if scope == "all":
        return out
    since = float(_current_search().get("started_at") or 0)
    if not since:
        return out
    return [f for f in out if _file_mtime(f) >= since]


def _fill_lead_scores(recs: list) -> list:
    """Give every record a lead score, even when its file carries none.

    The score is derived from fields the record already has (нет сайта,
    рейтинг, отзывы, телефон, категория), so a file written before scoring
    existed — or by stage 1 — still scores correctly in the table. A score
    already stored in the file always wins: stage 2 raises it further with
    the VK activity check.
    """
    missing = [r for r in recs
               if isinstance(r, dict) and r.get("lead_score") in (None, "")]
    if missing:
        try:
            from yandex_maps_parser.lead_score import annotate_records
            annotate_records(missing)
        except Exception:
            pass
    return recs


def _collect_records(view: str, rel_file: str | None = None,
                     scope: str = "current") -> list:
    """Records of a view — or of one explicitly requested file."""
    if rel_file:
        full = _safe_output_file(rel_file)
        return _fill_lead_scores(_read_records_file(full)) if full else []
    recs: list = []
    for f in _view_files(view, scope):
        recs.extend(_read_records_file(f))
    if view == "all":
        try:
            from yandex_maps_parser.exporters import dedupe_records
            recs = dedupe_records(recs)
        except Exception:
            pass
    return _fill_lead_scores(recs)


def _cities_of(recs: list) -> list[dict]:
    """[{city, count}] sorted by count desc (records without a city grouped)."""
    counts: dict = {}
    for r in recs:
        c = str(r.get("city") or "").strip() or "Без города"
        counts[c] = counts.get(c, 0) + 1
    return [{"city": c, "count": n}
            for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _unviewed_stats(recs: list) -> dict:
    """How many records are still unmarked, and how many of those per social."""
    rev = _load_reviewed()
    by_social = {k: 0 for k in SOCIAL_KEYS}
    total = 0
    for r in recs:
        key = _review_key(r)
        if key and rev.get(key):
            continue
        total += 1
        for s in SOCIAL_KEYS:
            if _safe_http_url(r.get(s)):
                by_social[s] += 1
    return {"total": total, "by_social": by_social}


@bp.route("/results-view")
def results_view():
    """Merged records for the «Текущий результат» sub-tab.

    view=raw       → records from output/raw/ (unfiltered)
    view=processed → records from output/processed/{json,excel}/ (filtered)
    view=all       → both, raw first (the live-streamed table equivalent)
    file=<rel>     → only that file (used by the «История файлов» browser)
    scope=current  → only files of the current search (default) — the tab is
                     a view of the *last* search, not of the whole folder
    scope=all      → every file in the folder («Все поиски» toggle)

    `cities` drives the city tabs, `unviewed` the bulk-outreach counters.
    """
    view = (request.args.get("view") or "raw").lower()
    if view not in VIEWS:
        view = "raw"
    scope = (request.args.get("scope") or "current").lower()
    if scope not in ("current", "all"):
        scope = "current"
    rel_file = (request.args.get("file") or "").strip() or None
    if rel_file and not _safe_output_file(rel_file):
        return jsonify({"error": "file not found"}), 404
    recs = _collect_records(view, rel_file, scope)
    return jsonify({
        "view": view,
        "scope": scope,
        "file": rel_file,
        "current_search": _current_search() or None,
        "count": len(recs),
        "records": recs,
        "cities": _cities_of(recs),
        "unviewed": _unviewed_stats(recs),
    })


@bp.route("/process-filters", methods=["POST"])
def process_filters():
    """Stage 2 on demand: re-filter existing raw files without a new crawl."""
    data = request.get_json(silent=True) or {}
    formats = data.get("formats") or ["excel"]
    filters = {
        "collapse_chains": bool(data.get("collapse_chains", False)),
        "chain_key":       str(data.get("chain_key") or "name_city"),
        "parse_mode":      data.get("parse_mode", "all"),
        "social_mode":     data.get("social_mode", "all"),
        "required_socials": data.get("required_socials") or [],
        # Stage-2 lead scoring / VK activity (see processing.apply_filters).
        "vk_check":         bool(data.get("vk_check", False)),
        "vk_mode":          data.get("vk_mode", "all"),
        "vk_max_post_days": data.get("vk_max_post_days") or 0,
        "vk_min_followers": data.get("vk_min_followers") or 0,
        "min_lead_score":   data.get("min_lead_score") or 0,
        "sort_by_score":    bool(data.get("sort_by_score", True)),
    }
    cleanup_mode = data.get("raw_mode", "keep")
    try:
        from yandex_maps_parser.processing import list_raw_files, process_all
        raw_paths = [os.path.join(_raw_dir(), f) for f in list_raw_files()]
        if not raw_paths:
            return jsonify({"ok": False, "error": "Нет сырых данных в output/raw/ — сначала запустите сбор."}), 400
        res = process_all(raw_paths, filters, formats, cleanup_mode=cleanup_mode)
        return jsonify({
            "ok": True,
            "count": res.get("count", 0),
            "empty": res.get("empty", False),
            "files": [os.path.relpath(f, OUTPUT_DIR) for f in res.get("files", [])],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ═══════════════════════════════════════════════════════════════
#  Bulk social outreach (manual) — «Массовый обход»
#  The server decides *what* to open (view + city + social + unviewed),
#  the client never sends file paths.
# ═══════════════════════════════════════════════════════════════

@bp.route("/bulk/urls", methods=["POST"])
def bulk_urls():
    """Next batch of social profile URLs to open manually.

    Body: {view, city?, social, count, skip_viewed}
    Reply: {urls:[{url,key,name}], returned, total, remaining}
    """
    data = request.get_json(silent=True) or {}
    view = str(data.get("view") or "raw").lower()
    if view not in VIEWS:
        return jsonify({"error": "invalid view"}), 400
    social = str(data.get("social") or "").lower()
    if social not in SOCIAL_KEYS:
        return jsonify({"error": "invalid social"}), 400
    try:
        count = int(data.get("count", 5))
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(50, count))
    city = str(data.get("city") or "").strip()[:100]
    skip_viewed = bool(data.get("skip_viewed", True))
    skip_keys = {str(k) for k in (data.get("exclude_keys") or []) if k}
    # Обход идёт по тому же срезу, что и таблица: файл из «Истории файлов»
    # либо текущий поиск (scope=all — вся папка).
    scope = str(data.get("scope") or "current").lower()
    if scope not in ("current", "all"):
        scope = "current"
    # The bulk panel follows the file opened from «История файлов».
    rel_file = str(data.get("file") or "").strip() or None
    if rel_file and not _safe_output_file(rel_file):
        return jsonify({"error": "file not found"}), 404

    recs = _collect_records(view, rel_file, scope)
    rev = _load_reviewed()
    pool: list[dict] = []
    for r in recs:
        if city and (str(r.get("city") or "").strip() or "Без города") != city:
            continue
        url = _safe_http_url(r.get(social))
        if not url:
            continue
        key = _review_key(r)
        if skip_viewed and key and rev.get(key):
            continue
        if key and key in skip_keys:
            continue
        pool.append({"url": url, "key": key, "name": str(r.get("name") or "")})
    urls = pool[:count]
    return jsonify({
        "urls": urls,
        "returned": len(urls),
        "total": len(pool),
        "remaining": max(0, len(pool) - len(urls)),
    })


@bp.route("/reviewed/batch", methods=["POST"])
def reviewed_batch():
    """Mark up to 500 records at once (one disk write)."""
    data = request.get_json(silent=True) or {}
    raw_keys = data.get("keys")
    if not isinstance(raw_keys, list):
        return jsonify({"error": "keys must be a list"}), 400
    if len(raw_keys) > 500:
        return jsonify({"error": "too many keys (max 500)"}), 400
    state_val = bool(data.get("reviewed", True))
    reviewed = _load_reviewed()
    changed = 0
    for k in raw_keys:
        k = str(k or "").strip()
        if not k:
            continue
        if state_val:
            if not reviewed.get(k):
                changed += 1
            reviewed[k] = True
        else:
            if reviewed.pop(k, None):
                changed += 1
    if changed:
        _save_reviewed(reviewed)
    return jsonify({"ok": True, "changed": changed})


def _persist_reviewed_column(path: str, rev: dict) -> int | None:
    """Write the «✓ Просмотрено» column of one xlsx from the marks store.

    Returns the number of changed rows, or None when the file has no such
    column (e.g. the column is switched off in «Форматы вывода»).
    A running file is replaced atomically, so a crash can't leave a half
    written workbook behind.
    """
    import openpyxl
    from yandex_maps_parser.constants import HEADER_LABELS

    wb = openpyxl.load_workbook(path)
    try:
        ws = wb.active
        header = [str(c.value or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1))]
        label = HEADER_LABELS.get("reviewed", "✓ Просмотрено")
        if label not in header:
            return None
        cols = {}
        for field in ("name", "city", "address", "yandex_maps_url", "twogis_url"):
            lab = HEADER_LABELS.get(field)
            if lab in header:
                cols[field] = header.index(lab) + 1
        rev_col = header.index(label) + 1
        changed = 0
        for row in range(2, ws.max_row + 1):
            rec = {}
            for field, ci in cols.items():
                rec[field] = ws.cell(row=row, column=ci).value
            key = _review_key(rec)
            val = bool(key and rev.get(key))
            cell = ws.cell(row=row, column=rev_col)
            if bool(cell.value) != val:
                changed += 1
            cell.value = val
        tmp = path + ".tmp"
        wb.save(tmp)
    finally:
        wb.close()
    os.replace(path + ".tmp", path)
    return changed


@bp.route("/reviewed/persist", methods=["POST"])
def reviewed_persist():
    """Write the marks of one view into its xlsx files.

    Called automatically by the UI (debounced after a click, on leaving the
    page, before exporting) and by the «Сохранить сейчас» button.
    """
    data = _json_body()
    view = str(data.get("view") or "raw").lower()
    if view not in VIEWS:
        view = "raw"
    scope = str(data.get("scope") or "current").lower()
    if scope not in ("current", "all"):
        scope = "current"
    rev = _load_reviewed()
    files = [f for f in _view_files(view, scope) if f.lower().endswith(".xlsx")]
    updated = 0
    skipped = 0
    errors: list[dict] = []
    for f in files:
        try:
            changed = _persist_reviewed_column(f, rev)
        except Exception as exc:  # never fail the whole batch on one file
            errors.append({"file": os.path.basename(f), "error": str(exc)})
            continue
        if changed is None:
            skipped += 1
        else:
            updated += changed
    _REC_CACHE.clear()
    return jsonify({"ok": True, "files": len(files), "updated": updated,
                    "skipped": skipped, "errors": errors})


# ═══════════════════════════════════════════════════════════════
#  File browser — «История файлов» (RAW / PROCESSED / ARCHIVE)
# ═══════════════════════════════════════════════════════════════

@bp.route("/files/list")
def files_list():
    """Every results file with size/date/record count (newest first)."""
    from datetime import datetime

    def _section(root: str, recursive: bool) -> list[dict]:
        items: list[dict] = []
        if not os.path.isdir(root):
            return items
        walker = os.walk(root) if recursive else [(root, [], os.listdir(root))]
        for dirpath, _dirs, files in walker:
            for name in files:
                low = name.lower()
                # `_`-prefixed files are internal (e.g. _archive/_index.json),
                # `~$…` are Excel lock files left by Excel itself.
                if not low.endswith((".xlsx", ".json", ".csv")) or name[:1] in ("_", "~") or name.startswith("~$"):
                    continue
                full = os.path.join(dirpath, name)
                if not os.path.isfile(full):
                    continue
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                item = {
                    "name": name,
                    "path": _rel_output(full),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M"),
                    "ext": low.rsplit(".", 1)[-1],
                }
                n = _count_records(full)
                if n is None:
                    item["error"] = "не удалось прочитать файл"
                else:
                    item["records"] = n
                items.append(item)
        items.sort(key=lambda i: i.get("mtime", 0), reverse=True)
        return items

    return jsonify({
        "raw": _section(_raw_dir(), False),
        "processed": _section(_processed_dir(), True),
        "archive": _section(_archive_root(), True),
    })


@bp.route("/files/action", methods=["POST"])
def files_action():
    """Move results files to the dated archive, or delete them for good.

    Body: {path | paths: [..], action: "archive"|"delete"|"restore",
    confirm?} — `delete` needs confirm:true (the UI asks first). The batch
    form (`paths`) powers «Удалить выбранные» in «История файлов»; every
    path is processed independently so one bad file never blocks the rest.
    Only files under output/{raw, processed,_archive} are accepted.
    """
    import shutil

    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").lower()
    if action not in ("archive", "restore", "delete"):
        return jsonify({"error": "invalid action"}), 400

    # Batch form: collect paths, fall back to the single-path form.
    rels: list[str] = [str(p) for p in (data.get("paths") or []) if str(p or "").strip()]
    if not rels:
        single = str(data.get("path") or "")
        if single:
            rels = [single]
    if not rels:
        return jsonify({"error": "no files specified"}), 400

    if len(rels) > 1:
        return _files_action_batch(rels, action, bool(data.get("confirm", False)))

    rel = rels[0]
    full = _safe_output_file(rel)
    if not full:
        return jsonify({"error": "file not found"}), 404

    root = os.path.realpath(OUTPUT_DIR)
    top_dir = os.path.relpath(full, root).split(os.sep)[0]

    if action == "archive":
        if top_dir == "_archive":
            return jsonify({"error": "файл уже в архиве"}), 400
        original_rel = _rel_output(full)
        target = _unique_path(os.path.join(_archive_today(), os.path.basename(full)))
        try:
            shutil.move(full, target)
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500
        index = _load_archive_index()
        index[_rel_output(target)] = original_rel
        _save_archive_index(index)
        _REC_CACHE.clear()
        return jsonify({"ok": True, "moved_to": _rel_output(target)})

    if action == "restore":
        if top_dir != "_archive":
            return jsonify({"error": "файл не в архиве"}), 400
        archived_rel = _rel_output(full)
        index = _load_archive_index()
        target_rel = index.get(archived_rel) or ""
        if not target_rel:
            # Fall back to the naming convention: raw_* → raw/, остальное — в processed/excel/
            base = os.path.basename(full)
            target_rel = ("raw/" if base.lower().startswith("raw_") else "processed/excel/") + base
        target_rel = target_rel.replace("\\", "/").lstrip("/")
        dest = os.path.realpath(os.path.join(root, target_rel))
        if (not dest.startswith(root + os.sep)
                or os.path.relpath(dest, root).split(os.sep)[0] not in ("raw", "processed")):
            return jsonify({"error": "недопустимый путь восстановления"}), 400
        dest = _unique_path(dest)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(full, dest)
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500
        index.pop(archived_rel, None)
        _save_archive_index(index)
        _REC_CACHE.clear()
        return jsonify({"ok": True, "restored_to": _rel_output(dest)})

    if not bool(data.get("confirm", False)):
        return jsonify({"error": "confirmation required"}), 400
    try:
        os.remove(full)
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500
    _REC_CACHE.clear()
    return jsonify({"ok": True, "deleted": _rel_output(full)})


def _files_action_batch(rels: list, action: str, confirm: bool):
    """Run /files/action over several paths, reporting per-file results.

    A missing file counts as already gone (the list may be stale) rather
    than an error; real failures (OSError, unsafe path) land in `errors`.
    """
    moved: list[str] = []
    deleted: list[str] = []
    errors: list[dict] = []
    index: dict = {}

    for rel in rels:
        full = _safe_output_file(rel)
        if not full:
            if action == "delete" and not os.path.exists(os.path.join(OUTPUT_DIR, rel)):
                continue          # already gone — nothing to do
            errors.append({"path": rel, "error": "file not found"})
            continue
        root = os.path.realpath(OUTPUT_DIR)
        top_dir = os.path.relpath(full, root).split(os.sep)[0]
        try:
            if action == "archive":
                if top_dir == "_archive":
                    errors.append({"path": rel, "error": "файл уже в архиве"})
                    continue
                original_rel = _rel_output(full)
                target = _unique_path(os.path.join(_archive_today(), os.path.basename(full)))
                shutil.move(full, target)
                index[_rel_output(target)] = original_rel
                moved.append(_rel_output(target))
            elif action == "delete":
                if not confirm:
                    return jsonify({"error": "confirmation required"}), 400
                os.remove(full)
                deleted.append(_rel_output(full))
            else:  # restore
                if top_dir != "_archive":
                    errors.append({"path": rel, "error": "файл не в архиве"})
                    continue
                archived_rel = _rel_output(full)
                if not index:
                    index = _load_archive_index()
                target_rel = index.get(archived_rel) or ""
                if not target_rel:
                    base = os.path.basename(full)
                    target_rel = ("raw/" if base.lower().startswith("raw_")
                                  else "processed/excel/") + base
                target_rel = target_rel.replace("\\", "/").lstrip("/")
                dest = os.path.realpath(os.path.join(root, target_rel))
                if (not dest.startswith(root + os.sep)
                        or os.path.relpath(dest, root).split(os.sep)[0] not in ("raw", "processed")):
                    errors.append({"path": rel, "error": "недопустимый путь восстановления"})
                    continue
                dest = _unique_path(dest)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(full, dest)
                moved.append(_rel_output(dest))
        except OSError as exc:
            errors.append({"path": rel, "error": str(exc)})

    if index:
        _save_archive_index(index)
    if moved or deleted:
        _REC_CACHE.clear()
    return jsonify({
        "ok": not errors or bool(moved or deleted),
        "moved": moved,
        "deleted": deleted,
        "errors": errors,
    })
