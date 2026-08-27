import os
import re
import io
import csv
import json
import queue
import threading
import time

from flask import Flask, render_template, request, Response, send_from_directory, jsonify

import yandex_maps_parser as parser
import vk_sender

app = Flask(__name__)
OUTPUT_DIR    = "output"
REVIEWED_FILE = os.path.join(OUTPUT_DIR, "_reviewed.json")

# ── Global run state ──────────────────────────────────────────
_state: dict = {
    "active":     False,
    "log_queue":  queue.Queue(),
    "stop_event": threading.Event(),
}
_lock    = threading.Lock()
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ── Reviewed helpers ──────────────────────────────────────────

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


# ── Background run thread ─────────────────────────────────────

def _run_thread(params: dict):
    lq         = _state["log_queue"]
    stop_event = _state["stop_event"]
    files: list[str] = []
    count = 0

    def log_fn(level: str, msg: str):
        if level == "result":
            try:
                lq.put({"type": "result", "data": json.loads(msg)})
            except Exception:
                pass
        else:
            lq.put({"type": "log", "level": level, "msg": _strip_ansi(msg)})

    try:
        files = parser.run_web(params, log_fn, stop_event)
        # Count results from the JSON output file
        for f in files:
            if f.endswith(".json"):
                try:
                    with open(os.path.join(OUTPUT_DIR, f), encoding="utf-8") as jf:
                        count = len(json.load(jf))
                    break
                except Exception:
                    pass
        lq.put({"type": "done", "files": files, "count": count,
                "stopped": stop_event.is_set()})
    except Exception as exc:
        lq.put({"type": "log",  "level": "warn", "msg": f"Ошибка: {exc}"})
        lq.put({"type": "done", "files": files,  "count": 0,
                "stopped": stop_event.is_set()})
    finally:
        with _lock:
            _state["active"] = False


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_parser():
    with _lock:
        if _state["active"]:
            return jsonify({"error": "Уже выполняется"}), 409
        _state["active"] = True
        _state["log_queue"] = queue.Queue()
        _state["stop_event"].clear()

    params = request.get_json(force=True) or {}
    threading.Thread(target=_run_thread, args=(params,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/stop", methods=["POST"])
def stop_parser():
    _state["stop_event"].set()
    return jsonify({"ok": True})


@app.route("/logs")
def logs():
    lq = _state["log_queue"]

    def generate():
        while True:
            try:
                msg = lq.get(timeout=25)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/status")
def status():
    return jsonify({"active": _state["active"]})


@app.route("/results/<path:filename>")
def results(filename):
    # Resolve and constrain the path before reading.  Unlike
    # send_from_directory(), a manual os.path.join would otherwise allow
    # traversal with ../ on deployments that preserve the path component.
    allowed = os.path.realpath(OUTPUT_DIR)
    filepath = os.path.realpath(os.path.join(allowed, filename))
    if not filepath.startswith(allowed + os.sep) or not os.path.isfile(filepath):
        return jsonify({"error": "not found"}), 404
    try:
        with open(filepath, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


# ── Test API key ──────────────────────────────────────────────

@app.route("/test-api-key", methods=["POST"])
def test_api_key():
    import requests as req_lib
    data = request.get_json(force=True) or {}
    api_key = data.get("api_key", "").strip()
    if not api_key:
        # Use built-in key from config
        try:
            from config import YANDEX_API_KEY
            api_key = YANDEX_API_KEY
        except Exception:
            return jsonify({"ok": False, "error": "Ключ не задан"}), 400

    try:
        r = req_lib.get(
            "https://geocode-maps.yandex.ru/1.x/",
            params={"apikey": api_key, "format": "json", "geocode": "Москва"},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            try:
                geo = r.json()
                found = geo.get("response", {}).get("GeoObjectCollection", {}) \
                           .get("metaDataProperty", {}).get("GeocoderResponseMetaData", {}) \
                           .get("found", "?")
                return jsonify({"ok": True, "status": 200,
                                "message": f"Ключ рабочий. Геокодер нашёл {found} объект(ов) для «Москва»."})
            except Exception:
                return jsonify({"ok": True, "status": 200, "message": "Ключ рабочий (ответ получен)."})
        elif r.status_code == 403:
            return jsonify({"ok": False, "status": 403, "message": "Ключ недействителен или превышен лимит (403)."})
        elif r.status_code == 429:
            return jsonify({"ok": False, "status": 429, "message": "Превышен лимит запросов (429). Попробуйте позже."})
        else:
            return jsonify({"ok": False, "status": r.status_code,
                            "message": f"Неожиданный ответ: HTTP {r.status_code}."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Reviewed state ────────────────────────────────────────────

@app.route("/reviewed", methods=["GET"])
def get_reviewed():
    return jsonify(_load_reviewed())


@app.route("/reviewed", methods=["POST"])
def set_reviewed():
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    state = bool(data.get("reviewed", False))
    if not url:
        return jsonify({"error": "url required"}), 400
    reviewed = _load_reviewed()
    if state:
        reviewed[url] = True
    else:
        reviewed.pop(url, None)
    _save_reviewed(reviewed)
    return jsonify({"ok": True})


# ── Export filtered rows ──────────────────────────────────────

@app.route("/export-filtered", methods=["POST"])
def export_filtered():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    data = request.get_json(force=True) or {}
    rows = data.get("rows", [])
    fmt  = data.get("format", "csv")

    HEADERS = ["#", "Название", "Категория", "Адрес", "Телефон",
               "Рейтинг", "Отзывов", "VK", "Instagram", "Facebook",
               "Telegram", "YouTube", "TikTok", "OK", "Twitter", "WhatsApp",
               "Другие соцсети", "Агрегатор", "Ссылка", "Запрос"]
    FIELDS = ["_idx", "name", "category", "address", "phone",
              "rating", "reviews", "vk", "instagram", "facebook",
              "telegram", "youtube", "tiktok", "ok", "twitter", "whatsapp",
              "other_socials", "aggregator_url", "yandex_maps_url", "query"]

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        for i, row in enumerate(rows, 1):
            writer.writerow([i if f == "_idx" else row.get(f, "") for f in FIELDS])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=filtered_export.csv"}
        )

    # Excel
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
            val = i - 1 if f == "_idx" else row.get(f, "")
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


# ── Sender state ──────────────────────────────────────────────

_send_state: dict = {
    "active":     False,
    "log_queue":  queue.Queue(),
    "stop_event": threading.Event(),
}
_send_lock = threading.Lock()

SENDER_CONFIG_FILE = "sender_config.json"


def _load_sender_config() -> dict:
    if os.path.exists(SENDER_CONFIG_FILE):
        try:
            with open(SENDER_CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _safe_sender_config(data: dict) -> dict:
    """Keep only non-secret sender preferences.

    Access tokens are credentials, not UI preferences.  Older versions of the
    app could have written them to sender_config.json, so strip those keys
    when reading and when saving.
    """
    allowed = {
        "message", "delayMin", "delayMax", "limitType", "limitN", "file",
    }
    return {key: data[key] for key in allowed if key in data}


def _save_sender_config(data: dict):
    data = _safe_sender_config(data)
    with open(SENDER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _send_thread(params: dict):
    lq         = _send_state["log_queue"]
    stop_event = _send_state["stop_event"]

    def log_fn(level: str, msg: str):
        lq.put({"type": "log", "level": level, "msg": _strip_ansi(msg)})

    try:
        stats = vk_sender.run_send(params, log_fn, stop_event)
        lq.put({"type": "done", "stats": stats, "stopped": stop_event.is_set()})
    except Exception as exc:
        lq.put({"type": "log",  "level": "warn", "msg": f"Ошибка: {exc}"})
        lq.put({"type": "done", "stats": {}, "stopped": stop_event.is_set()})
    finally:
        with _send_lock:
            _send_state["active"] = False


# ── Sender routes ─────────────────────────────────────────────

@app.route("/send/files")
def send_files():
    from vk_sender.excel_manager import list_excel_files
    files = list_excel_files(OUTPUT_DIR)
    return jsonify({"files": files})


@app.route("/send/config", methods=["GET"])
def send_config_get():
    # Never return a legacy token that may exist in an old config file.
    return jsonify(_safe_sender_config(_load_sender_config()))


@app.route("/send/config", methods=["POST"])
def send_config_post():
    data = request.get_json(force=True) or {}
    _save_sender_config(data)
    return jsonify({"ok": True})


def _safe_excel_filename(filename: str) -> str | None:
    """
    Return the safe basename if the filename resolves inside OUTPUT_DIR,
    or None if it looks like a path traversal attempt.
    """
    if not filename:
        return None
    basename = os.path.basename(filename)
    resolved = os.path.realpath(os.path.join(OUTPUT_DIR, basename))
    allowed  = os.path.realpath(OUTPUT_DIR)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return None
    return basename


@app.route("/send/run", methods=["POST"])
def send_run():
    params = request.get_json(force=True) or {}

    safe_file = _safe_excel_filename(params.get("excel_file", ""))
    if not safe_file:
        return jsonify({"error": "Недопустимое имя файла"}), 400

    with _send_lock:
        if _send_state["active"]:
            return jsonify({"error": "Рассылка уже выполняется"}), 409
        _send_state["active"] = True
        _send_state["log_queue"] = queue.Queue()
        _send_state["stop_event"].clear()

    params["excel_file"] = safe_file
    params["output_dir"] = OUTPUT_DIR
    threading.Thread(target=_send_thread, args=(params,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/send/stop", methods=["POST"])
def send_stop():
    _send_state["stop_event"].set()
    return jsonify({"ok": True})


@app.route("/send/logs")
def send_logs():
    lq = _send_state["log_queue"]

    def generate():
        while True:
            try:
                msg = lq.get(timeout=25)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/send/status")
def send_status():
    return jsonify({"active": _send_state["active"]})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
