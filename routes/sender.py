"""VK message sender routes."""
import os
import json
import queue
import threading

from flask import Blueprint, request, jsonify

OUTPUT_DIR = "output"
SENDER_CONFIG_FILE = "sender_config.json"

bp = Blueprint("sender", __name__)

# ── Sender state ──────────────────────────────────────────────
_send_state: dict = {
    "active":     False,
    "log_queue":  queue.Queue(),
    "stop_event": threading.Event(),
}
_send_lock = threading.Lock()

_ANSI_RE = None


def _strip_ansi(text: str) -> str:
    global _ANSI_RE
    if _ANSI_RE is None:
        import re
        _ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
    return _ANSI_RE.sub("", text)


def _load_sender_config() -> dict:
    if os.path.exists(SENDER_CONFIG_FILE):
        try:
            with open(SENDER_CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _safe_sender_config(data: dict) -> dict:
    allowed = {"message", "delayMin", "delayMax", "limitType", "limitN", "file"}
    return {key: data[key] for key in allowed if key in data}


def _save_sender_config(data: dict):
    data = _safe_sender_config(data)
    with open(SENDER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_excel_filename(filename: str) -> str | None:
    if not filename:
        return None
    basename = os.path.basename(filename)
    resolved = os.path.realpath(os.path.join(OUTPUT_DIR, basename))
    allowed  = os.path.realpath(OUTPUT_DIR)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        return None
    return basename


def _send_thread(params: dict):
    lq         = _send_state["log_queue"]
    stop_event = _send_state["stop_event"]

    def log_fn(level: str, msg: str):
        lq.put({"type": "log", "level": level, "msg": _strip_ansi(msg)})

    try:
        import vk_sender as _vk
        stats = _vk.run_send(params, log_fn, stop_event)
        lq.put({"type": "done", "stats": stats, "stopped": stop_event.is_set()})
    except Exception as exc:
        lq.put({"type": "log",  "level": "warn", "msg": f"Ошибка: {exc}"})
        lq.put({"type": "done", "stats": {}, "stopped": stop_event.is_set()})
    finally:
        with _send_lock:
            _send_state["active"] = False


# ── Routes ────────────────────────────────────────────────────

@bp.route("/send/files")
def send_files():
    from vk_sender.excel_manager import list_excel_files
    files = list_excel_files(OUTPUT_DIR)
    return jsonify({"files": files})


@bp.route("/send/config", methods=["GET"])
def send_config_get():
    return jsonify(_safe_sender_config(_load_sender_config()))


@bp.route("/send/config", methods=["POST"])
def send_config_post():
    data = request.get_json(force=True) or {}
    _save_sender_config(data)
    return jsonify({"ok": True})


@bp.route("/send/run", methods=["POST"])
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


@bp.route("/send/stop", methods=["POST"])
def send_stop():
    _send_state["stop_event"].set()
    return jsonify({"ok": True})


@bp.route("/send/logs")
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

    from flask import Response
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/send/status")
def send_status():
    return jsonify({"active": _send_state["active"]})
