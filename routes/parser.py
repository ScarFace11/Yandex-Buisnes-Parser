"""Parser search routes."""
import json
import queue

from flask import Blueprint, request, Response, jsonify

from run_manager import run_manager

bp = Blueprint("parser", __name__)


@bp.route("/run", methods=["POST"])
def run_parser():
    # Минимально допустимая версия: на устаревшей сборке поиск не стартует вовсе.
    try:
        from routes.update import minimum_state
        state = minimum_state()
    except Exception:
        state = {}
    if state.get("blocked"):
        return jsonify({
            "error": state.get("notice") or
                     "Эта версия приложения больше не поддерживается — обновитесь",
            "blocked": True,
            "current": state.get("current", ""),
            "minimum": state.get("minimum", ""),
            "download_url": state.get("download_url", ""),
        }), 409

    params = request.get_json(force=True) or {}

    queries = [q.strip() for q in params.get("queries", []) if q.strip()]
    if not queries:
        return jsonify({"error": "Введите хотя бы один запрос"}), 400
    cities = [c.strip() for c in params.get("cities", []) if c.strip()]
    if not cities:
        city = params.get("city", "").strip()
        if city:
            cities = [city]
    if not cities:
        return jsonify({"error": "Введите хотя бы один город"}), 400
    params["cities"] = cities

    entry = run_manager.new_run()
    entry["params"] = params
    entry["cities"] = cities

    active = run_manager.active_run_id()
    if active and active != entry["id"]:
        # «Продолжить» after a pause: the paused run already delivered its results and is being finalized — it must not block the resume, or the continuation would sit in the queue forever (see clear_paused_run).
        resumable = params.get("resume") and run_manager.clear_paused_run(active)
        if not resumable:
            with run_manager._lock:
                entry["queued"] = True
                entry["active"] = False
            return jsonify({"ok": True, "queued": True, "run_id": entry["id"],
                            "position": run_manager.queue_position(entry["id"])})

    run_manager.start_process(entry)
    return jsonify({"ok": True, "queued": False, "run_id": entry["id"]})


@bp.route("/stop", methods=["POST"])
def stop_parser():
    run_id = request.args.get("run_id", "")
    # ?pause=1 → graceful unwind that REMEMBERS the run: the frontend gets a done message with paused=true + resume payload and offers «Продолжить».
    pause = request.args.get("pause", "") in ("1", "true", "yes")
    affected = run_manager.stop_run(run_id, pause=pause)
    # `targets` says whether anything was actually stopped: a pause request that arrives after the run already finished used to answer «ok, paused» and the UI kept waiting for a done message that was never coming.
    return jsonify({"ok": True, "paused": pause, "targets": affected,
                    "target": affected[0] if affected else None})


@bp.route("/skip-city", methods=["POST"])
def skip_city_route():
    run_id = request.args.get("run_id", "")
    check = request.args.get("check", "")
    info = run_manager.skip_city_info(run_id)
    if check:
        # Just return info, don't skip
        return jsonify({"ok": True, "city": info["city"], "records": info["records_found"]})
    run_manager.skip_city(run_id)
    return jsonify({"ok": True, "city": info["city"], "records": info["records_found"]})


@bp.route("/logs")
def logs():
    run_id = request.args.get("run_id", "")
    entry = run_manager.get(run_id)

    if not entry:
        with run_manager._lock:
            for r in sorted(run_manager._runs.values(),
                            key=lambda x: x["started_at"], reverse=True):
                if r["active"] or r.get("queued"):
                    entry = r
                    break

    if not entry:
        return Response(
            iter(['data: {"type":"ping"}\n\n']),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    lq = entry["log_queue"]

    def generate():
        while True:
            try:
                msg = lq.get(timeout=25)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                if entry.get("_done"):
                    yield 'data: {"type":"done","files":[],"count":0,"stopped":true,"formats":[]}\n\n'
                    break
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/status")
def status():
    s = run_manager.status()
    # Браузер — единственный движок сбора; фронтенд по этому флагу показывает предупреждение «Chrome не найден», если он отсутствует.
    try:
        from yandex_maps_parser.cdp_client import is_installed as browser_installed
        s["browser_available"] = browser_installed()
    except Exception:
        s["browser_available"] = False
    return jsonify(s)


@bp.route("/runs")
def list_runs():
    return jsonify({"runs": run_manager.list_runs()})
