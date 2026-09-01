"""
Public REST API for programmatic access to the parser.

Endpoints:
  POST /api/v1/search    — Start a search job
  GET  /api/v1/status     — Get run status
  GET  /api/v1/results    — Get results as JSON
  GET  /api/v1/health     — Health check

Usage:
  curl -X POST http://localhost:5000/api/v1/search \
    -H "Content-Type: application/json" \
    -d '{"queries": ["кафе"], "cities": ["Москва"], "social_mode": "with_socials"}'

  curl http://localhost:5000/api/v1/results?run_id=abc123
"""

import json
import queue

from flask import Blueprint, request, jsonify

from run_manager import run_manager

bp = Blueprint("public_api", __name__, url_prefix="/api/v1")


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
        "social_mode": "with_socials",          // optional: all|with_socials|without_socials
        "max_pages": 15,                        // optional: 1-50
        "max_workers": 10,                      // optional: 1-20
        "output_formats": ["excel", "json"],    // optional
        "api_key": "your-api-key"               // optional: override config key
    }
    """
    data = request.get_json(force=True) or {}

    queries = [q.strip() for q in data.get("queries", []) if q.strip()]
    if not queries:
        return jsonify({"error": "queries is required (array of strings)"}), 400

    cities = [c.strip() for c in data.get("cities", []) if c.strip()]
    if not cities:
        return jsonify({"error": "cities is required (array of strings)"}), 400

    # Build params
    params = {
        "queries": queries,
        "cities": cities,
        "social_mode": data.get("social_mode", "with_socials"),
        "max_pages": max(1, min(50, int(data.get("max_pages", 15)))),
        "max_workers": max(1, min(20, int(data.get("max_workers", 10)))),
        "query_workers": 2,
        "min_rating": float(data.get("min_rating", 0)),
        "min_reviews": int(data.get("min_reviews", 0)),
        "use_grid": bool(data.get("use_grid", False)),
        "grid_radius": int(data.get("grid_radius", 20)),
        "grid_step": int(data.get("grid_step", 5)),
        "validate_socials": bool(data.get("validate_socials", False)),
        "use_browser": bool(data.get("use_browser", True)),
        "fetch_detail": bool(data.get("fetch_detail", True)),
        "api_key": data.get("api_key", ""),
        "required_socials": data.get("required_socials", []),
    }

    # Output formats
    formats = data.get("output_formats", ["excel", "json"])
    params["output_excel"] = "excel" in formats
    params["output_json"] = "json" in formats
    params["output_csv"] = "csv" in formats
    params["output_map"] = "map" in formats

    # Start run
    entry = run_manager.new_run()
    entry["params"] = params
    entry["cities"] = cities

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
            "message": f"Job queued at position {run_manager.queue_position(entry['id'])}",
        })

    run_manager.start_process(entry)
    return jsonify({
        "ok": True,
        "queued": False,
        "run_id": entry["id"],
        "message": "Search started",
    })


@bp.route("/status", methods=["GET"])
def status():
    """Get status of a run or all runs.

    Query params:
      run_id — optional, specific run to check
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
            "cities": entry.get("cities", []),
            "started_at": entry.get("started_at", 0),
        })
    return jsonify(run_manager.status())


@bp.route("/results", methods=["GET"])
def results():
    """Get results for a completed run.

    Query params:
      run_id  — optional, specific run
      format  — 'json' (default) or 'csv'
    """
    run_id = request.args.get("run_id", "")
    entry = run_manager.get(run_id)

    if not entry:
        with run_manager._lock:
            for r in sorted(run_manager._runs.values(),
                            key=lambda x: x.get("started_at", 0), reverse=True):
                if r.get("active") or r.get("queued"):
                    entry = r
                    break

    if not entry:
        return jsonify({"error": "No active or recent run found"}), 404

    # Get files from entry
    files = entry.get("files", [])
    json_files = [f for f in files if f.endswith(".json") and not f.startswith("_")]

    if not json_files:
        return jsonify({"results": [], "message": "No results yet"})

    # Load the first JSON file
    import os
    filepath = os.path.join("output", json_files[0])
    if not os.path.isfile(filepath):
        return jsonify({"error": "Results file not found"}), 404

    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({
            "run_id": entry["id"],
            "count": len(data),
            "results": data,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/stop", methods=["POST"])
def stop():
    """Stop a running search.

    Query params:
      run_id — optional, specific run to stop
    """
    run_id = request.args.get("run_id", "")
    run_manager.stop_run(run_id)
    return jsonify({"ok": True, "message": "Stop requested"})


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
