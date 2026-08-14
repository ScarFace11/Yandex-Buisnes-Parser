"""
File output: CSV, JSON, Excel (.xlsx), and HTML map.
"""
import csv
import json
import os
import re
from collections import Counter
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .constants import (
    CSV_FIELDS,
    HEADER_LABELS,
    COL_WIDTHS,
    SOCIAL_COLORS,
    SOCIAL_BADGE_COLORS,
    SOCIAL_LABELS,
    KNOWN_PLATFORMS,
    QUERY_COLORS,
)
from . import state


# ── Path resolution ───────────────────────────────────────────

def _resolve(base: str) -> dict[str, str]:
    os.makedirs(state.OUTPUT_DIR, exist_ok=True)
    return {
        "csv":  os.path.join(state.OUTPUT_DIR, f"{base}.csv"),
        "json": os.path.join(state.OUTPUT_DIR, f"{base}.json"),
        "jsonl": os.path.join(state.OUTPUT_DIR, f"{base}.jsonl"),
        "xlsx": os.path.join(state.OUTPUT_DIR, f"{base}.xlsx"),
        "map":  os.path.join(state.OUTPUT_DIR, f"{base}_map.html"),
    }


def load_jsonl(path: str) -> list[dict]:
    """Read records from the crash-safe JSONL sidecar (one JSON object per line)."""
    records: list[dict] = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception:
        pass
    return records


def record_key(rec: dict) -> str:
    """
    Stable dedup key for a business record.
    Priority: yandex_maps_url → phone digits → normalized name+address.
    The name+address fallback is normalized so small formatting differences
    ("ул. Ленина, 1" vs "Ленина 1") don't create duplicates.
    """
    url = str(rec.get("yandex_maps_url") or "").strip()
    if url:
        return "u|" + url
    digits = re.sub(r"\D", "", str(rec.get("phone") or ""))
    if digits:  # normalize 8-XXX and +7-XXX to the same key
        if len(digits) == 11 and digits[0] == "8":
            digits = "7" + digits[1:]
        return "p|" + digits
    norm = lambda s: re.sub(r"\W+", "", (s or "").lower())
    return f"n|{norm(rec.get('name'))}|{norm(rec.get('address'))}"


def dedupe_records(records: list[dict]) -> list[dict]:
    """Deduplicate records using record_key()."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in records:
        key = record_key(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def load_existing_urls(csv_path: str) -> set[str]:
    ids: set[str] = set()
    if not os.path.exists(csv_path):
        return ids
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if u := row.get("yandex_maps_url", ""):
                    ids.add(u)
    except Exception:
        pass
    return ids


# ── CSV ───────────────────────────────────────────────────────

def save_csv(records: list[dict], path: str, append: bool) -> None:
    mode = "a" if append and os.path.exists(path) else "w"
    with open(path, mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        w.writerows(records)


# ── JSON ──────────────────────────────────────────────────────

def save_json(records: list[dict], path: str, append: bool) -> None:
    existing: list[dict] = []
    if append and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing + records, f, ensure_ascii=False, indent=2)


# ── Excel ─────────────────────────────────────────────────────

def save_excel(all_records: list[dict], path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Бизнесы"

    THIN        = Side(style="thin",   color="CCCCCC")
    THICK       = Side(style="medium", color="AAAAAA")
    CELL_BORDER = Border(left=THIN, right=THIN, top=THIN,  bottom=THIN)
    HEAD_BORDER = Border(left=THIN, right=THIN, top=THICK, bottom=THICK)
    HDR_FILL    = PatternFill("solid", fgColor="1A6B3C")
    HDR_FONT    = Font(bold=True, color="FFFFFF", size=10)
    REV_FILL    = PatternFill("solid", fgColor="E8F5E9")
    ALT_FILL    = PatternFill("solid", fgColor="F8F8F8")
    LINK_FONT   = Font(color="1155CC", underline="single", size=10)
    URL_RE      = re.compile(r"https?://", re.I)

    for ci, field in enumerate(CSV_FIELDS, 1):
        c = ws.cell(row=1, column=ci, value=HEADER_LABELS.get(field, field))
        c.font      = HDR_FONT
        c.fill      = HDR_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border    = HEAD_BORDER
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"

    for ri, record in enumerate(all_records, 2):
        alt = ri % 2 == 0
        for ci, field in enumerate(CSV_FIELDS, 1):
            val  = record.get(field, "")
            cell = ws.cell(row=ri, column=ci)

            if field == "reviewed":
                cell.fill  = REV_FILL
                cell.value = val
            elif field in SOCIAL_COLORS and isinstance(val, str) and URL_RE.match(val):
                cell.fill      = PatternFill("solid", fgColor=SOCIAL_COLORS[field])
                cell.hyperlink = val
                cell.value     = val
                cell.font      = Font(color="1155CC", underline="single", size=10)
            elif field in SOCIAL_COLORS and not val:
                cell.value = ""
            elif field == "email" and isinstance(val, str) and val:
                cell.hyperlink = f"mailto:{val}"
                cell.value     = val
                cell.font      = LINK_FONT
                if alt:
                    cell.fill = ALT_FILL
            elif field in ("aggregator_url", "yandex_maps_url") and isinstance(val, str) and URL_RE.match(val):
                cell.hyperlink = val
                cell.value     = val
                cell.font      = LINK_FONT
                if alt:
                    cell.fill = ALT_FILL
            else:
                cell.value = val
                if alt and field not in SOCIAL_COLORS:
                    cell.fill = ALT_FILL

            cell.alignment = Alignment(vertical="top", wrap_text=(field == "description"))
            cell.border    = CELL_BORDER

    for ci, field in enumerate(CSV_FIELDS, 1):
        ws.column_dimensions[get_column_letter(ci)].width = COL_WIDTHS.get(field, 16)
    ws.auto_filter.ref = ws.dimensions

    _fill_legend_sheet(wb.create_sheet("Легенда цветов"))
    _fill_stats_sheet(wb.create_sheet("Статистика"), all_records, HDR_FILL, HDR_FONT, CELL_BORDER, ALT_FILL)
    wb.save(path)


def _fill_legend_sheet(ws) -> None:
    THIN = Side(style="thin", color="CCCCCC")
    brd  = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    hf   = PatternFill("solid", fgColor="1A6B3C")
    hfnt = Font(bold=True, color="FFFFFF", size=10)

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 14

    for ci, label in enumerate(["Платформа", "Цвет ячейки при наличии ссылки", "Hex-код"], 1):
        c = ws.cell(row=1, column=ci, value=label)
        c.font      = hfnt
        c.fill      = hf
        c.border    = brd
        c.alignment = Alignment(horizontal="center")

    labels = {
        "vk": "ВКонтакте", "instagram": "Instagram", "facebook": "Facebook",
        "telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok",
        "ok": "Одноклассники", "twitter": "Twitter / X", "whatsapp": "WhatsApp",
        "other_socials": "Другие соцсети",
    }
    for ri, (platform, hex_color) in enumerate(SOCIAL_COLORS.items(), 2):
        ws.cell(row=ri, column=1, value=labels.get(platform, platform)).border = brd
        c = ws.cell(row=ri, column=2, value="Найдена ссылка")
        c.fill   = PatternFill("solid", fgColor=hex_color)
        c.border = brd
        ws.cell(row=ri, column=3, value=f"#{hex_color}").border = brd

    r = len(SOCIAL_COLORS) + 2
    ws.cell(r, 1, "(пусто)").border          = brd
    ws.cell(r, 2, "Ссылка не найдена").border = brd


def _fill_stats_sheet(ws, records, hfill, hfont, border, alt_fill) -> None:
    THIN = Side(style="thin", color="CCCCCC")
    brd  = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    def hdr(row, col, val):
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
        c           = ws.cell(row=row, column=col, value=val)
        c.font      = hfont
        c.fill      = hfill
        c.border    = brd
        c.alignment = Alignment(horizontal="center")

    def cell(row, col, val, alt=False):
        c = ws.cell(row=row, column=col, value=val)
        if alt:
            c.fill = alt_fill
        c.border = brd
        return c

    row = 1
    hdr(row, 1, "📊 Общая статистика")
    row += 1
    for label, val in [
        ("Всего найдено",            len(records)),
        ("С описанием",              sum(1 for r in records if r.get("description"))),
        ("С рейтингом",              sum(1 for r in records if r.get("rating"))),
        ("Через taplink/linktree",   sum(1 for r in records if r.get("aggregator_url"))),
        ("С проверкой соцсетей",     sum(1 for r in records if r.get("socials_valid"))),
    ]:
        cell(row, 1, label, row % 2 == 0)
        cell(row, 2, val,   row % 2 == 0)
        row += 1

    row += 1
    hdr(row, 1, "🔍 По запросам")
    row += 1
    for q, cnt in Counter(r.get("query", "") for r in records).most_common():
        cell(row, 1, q,   row % 2 == 0)
        cell(row, 2, cnt, row % 2 == 0)
        row += 1

    row += 1
    hdr(row, 1, "📱 По соцсетям")
    row += 1
    labels = {
        "vk": "ВКонтакте", "instagram": "Instagram", "facebook": "Facebook",
        "telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok",
        "ok": "Одноклассники", "twitter": "Twitter/X", "whatsapp": "WhatsApp",
    }
    for p in KNOWN_PLATFORMS:
        cnt = sum(1 for r in records if r.get(p))
        if cnt:
            c1 = cell(row, 1, labels.get(p, p), row % 2 == 0)
            c1.fill = PatternFill("solid", fgColor=SOCIAL_COLORS.get(p, "FFFFFF"))
            cell(row, 2, cnt, row % 2 == 0)
            row += 1

    row += 1
    hdr(row, 1, "🏪 Топ категорий")
    row += 1
    cats: Counter = Counter()
    for r in records:
        for cat in r.get("category", "").split(","):
            if c2 := cat.strip():
                cats[c2] += 1
    for cat, cnt in cats.most_common(15):
        cell(row, 1, cat, row % 2 == 0)
        cell(row, 2, cnt, row % 2 == 0)
        row += 1

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 12


# ── HTML map ──────────────────────────────────────────────────

def _popup_html(r: dict, idx: int) -> str:
    name     = r.get("name", "")
    category = r.get("category", "")
    address  = r.get("address", "")
    phone    = r.get("phone", "")
    rating   = r.get("rating", "")
    reviews  = r.get("reviews", "")
    maps_url = r.get("yandex_maps_url", "")
    agg_url  = r.get("aggregator_url", "")
    hours    = r.get("hours", "")

    badges = ""
    for p in KNOWN_PLATFORMS:
        url = r.get(p, "")
        if url:
            color = SOCIAL_BADGE_COLORS.get(p, "#888")
            label = SOCIAL_LABELS.get(p, p.upper())
            badges += (
                f'<a href="{url}" target="_blank" style="'
                f'display:inline-block;margin:2px 3px 2px 0;padding:2px 7px;'
                f'background:{color};color:#fff;border-radius:4px;'
                f'font-size:11px;font-weight:bold;text-decoration:none">'
                f'{label}</a>'
            )
    other = r.get("other_socials", "")
    if other:
        for u in other.split(", "):
            u = u.strip()
            if u:
                badges += (
                    f'<a href="{u}" target="_blank" style="'
                    f'display:inline-block;margin:2px 3px 2px 0;padding:2px 7px;'
                    f'background:#9C27B0;color:#fff;border-radius:4px;'
                    f'font-size:11px;font-weight:bold;text-decoration:none">…</a>'
                )

    rating_str = ""
    if rating:
        stars = "★" * round(float(rating)) + "☆" * (5 - round(float(rating)))
        rating_str = (
            f'<div style="margin:4px 0;color:#f5a623;font-size:13px">'
            f'{stars} <span style="color:#555;font-size:12px">'
            f'{rating}{(" · " + reviews + " отз.") if reviews else ""}</span></div>'
        )

    rows = ""
    if category:  rows += f'<div style="color:#888;font-size:11px;margin-bottom:3px">{category}</div>'
    if rating_str: rows += rating_str
    if address:   rows += f'<div style="margin:3px 0;font-size:12px">📍 {address}</div>'
    if phone:     rows += f'<div style="margin:3px 0;font-size:12px">📞 <a href="tel:{phone}">{phone}</a></div>'
    if hours:     rows += f'<div style="margin:3px 0;font-size:12px;color:#555">🕐 {hours}</div>'
    if agg_url:
        rows += (
            f'<div style="margin:4px 0;font-size:12px">'
            f'🔗 <a href="{agg_url}" target="_blank" style="color:#FF6B35">Taplink / Linktree</a></div>'
        )
    if badges:    rows += f'<div style="margin:6px 0">{badges}</div>'
    if maps_url:
        rows += (
            f'<div style="margin:6px 0">'
            f'<a href="{maps_url}" target="_blank" style="'
            f'display:inline-block;padding:4px 10px;background:#FF0000;'
            f'color:#fff;border-radius:4px;font-size:12px;text-decoration:none">'
            f'Открыть на Яндекс.Картах ↗</a></div>'
        )

    return (
        f'<div style="font-family:Arial,sans-serif;min-width:220px;max-width:280px">'
        f'<b style="font-size:14px">{name}</b>'
        f'{rows}</div>'
    )


def _folium_color_to_hex(name: str) -> str:
    mapping = {
        "blue":      "#4285F4", "red":       "#EA4335", "green":     "#34A853",
        "purple":    "#9C27B0", "orange":    "#FF9800", "darkblue":  "#1A237E",
        "darkred":   "#B71C1C", "darkgreen": "#1B5E20", "cadetblue": "#006064",
        "lightred":  "#EF9A9A",
    }
    return mapping.get(name, "#4285F4")


def save_map(records: list[dict], path: str, center_lat: float, center_lon: float) -> None:
    import folium
    from folium.plugins import HeatMap, MarkerCluster

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=12,
        tiles="OpenStreetMap",
        prefer_canvas=True,
    )

    queries  = list(dict.fromkeys(r.get("query", "") for r in records))
    q_color  = {q: QUERY_COLORS[i % len(QUERY_COLORS)] for i, q in enumerate(queries)}
    q_clusters = {}
    for q in queries:
        fg = folium.FeatureGroup(name=f"🔍 {q}", show=True)
        q_clusters[q] = (fg, MarkerCluster().add_to(fg))
        fg.add_to(m)

    heat_fg = folium.FeatureGroup(name="🌡 Тепловая карта", show=False)
    heat_fg.add_to(m)

    heat_points = []
    for idx, r in enumerate(records):
        lat = r.get("lat")
        lon = r.get("lon")
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue

        heat_points.append([lat, lon])
        q     = r.get("query", "")
        color = q_color.get(q, "blue")

        icon_color = "orange" if r.get("aggregator_url") else color
        icon_name  = "star"   if r.get("aggregator_url") else "info-sign"

        popup_html = _popup_html(r, idx)
        marker = folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=r.get("name", ""),
            icon=folium.Icon(color=icon_color, icon=icon_name, prefix="glyphicon"),
        )
        _, cluster = q_clusters.get(q, (None, None))
        if cluster is not None:
            marker.add_to(cluster)

    if heat_points:
        HeatMap(heat_points, radius=18, blur=15, min_opacity=0.35).add_to(heat_fg)

    legend_items = "".join(
        f'<div style="margin:3px 0">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{_folium_color_to_hex(q_color.get(q, "blue"))};margin-right:6px"></span>'
        f'{q} ({sum(1 for r in records if r.get("query") == q)})</div>'
        for q in queries
    )
    legend_html = f"""
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:12px 16px;border-radius:8px;
                box-shadow:0 2px 10px rgba(0,0,0,.25);font-family:Arial,sans-serif;
                font-size:13px;max-width:200px">
      <b style="font-size:14px">📍 Запросы</b><br>
      {legend_items}
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #eee;font-size:11px;color:#888">
        ★ — через taplink/linktree
      </div>
    </div>"""

    info_panel = f"""
    <div style="position:fixed;top:10px;right:10px;z-index:9999;
                background:white;padding:10px 14px;border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,.2);font-family:Arial,sans-serif;font-size:13px">
      <b>🗺 Яндекс.Карты — парсер</b><br>
      Всего: <b>{len(records)}</b> бизнесов<br>
      Город: {state.CITY}<br>
      <span style="color:#888;font-size:11px">Обновлено: {datetime.now().strftime("%d.%m.%Y %H:%M")}</span>
    </div>"""

    m.get_root().html.add_child(folium.Element(legend_html))
    m.get_root().html.add_child(folium.Element(info_panel))
    folium.LayerControl(collapsed=False).add_to(m)
    m.save(path)
