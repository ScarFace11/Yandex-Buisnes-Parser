"""Parser search routes."""
import json
import queue

from flask import Blueprint, request, Response, jsonify

from run_manager import run_manager

bp = Blueprint("parser", __name__)


@bp.route("/run", methods=["POST"])
def run_parser():
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
    run_manager.stop_run(run_id)
    return jsonify({"ok": True})


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
    return jsonify(run_manager.status())


@bp.route("/runs")
def list_runs():
    return jsonify({"runs": run_manager.list_runs()})
