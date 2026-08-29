"""Utility routes: reviewed, export, results, download, API key test."""
import os
import io
import csv
import json

from flask import Blueprint, request, Response, send_from_directory, jsonify

OUTPUT_DIR = "output"
REVIEWED_FILE = os.path.join(OUTPUT_DIR, "_reviewed.json")

bp = Blueprint("api", __name__)


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


@bp.route("/")
def index():
    return __import__("flask").render_template("index.html")


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


@bp.route("/test-api-key", methods=["POST"])
def test_api_key():
    import requests as req_lib
    data = request.get_json(force=True) or {}
    api_key = data.get("api_key", "").strip()
    if not api_key:
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


@bp.route("/export-filtered", methods=["POST"])
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
