# -*- coding: utf-8 -*-
"""Разовая генерация координат городов каталога (не поставляется с app).

Берём города из yandex_maps_parser/city_data.py и спрашиваем у Nominatim
(OpenStreetMap) и центр, и рамку города. Результат — выгрузка
_coords_raw.json, из которой таблицу собирает scripts/build_city_coords.py.

Рамка (bbox) нужна сетке точек: без неё круг радиусом 20 км захватывает
пригороды и соседние районы, и запросы уходят в поля. Nominatim отдаёт
boundingbox как [юг, север, запад, восток] — это ровно тот порядок, который
ждёт build_grid.

Повторный запуск не дёргает сеть для городов, у которых в выгрузке уже есть
и координаты, и рамка: скрипт дописывает недостающее. Так обновление таблицы
не зависит от того, ответил ли Nominatim на все 149 запросов подряд.

Почему без «, Россия»: раньше страна дописывалась всем городам подряд, и для
Минска, Алматы или Ташкента Nominatim честно находил в России деревню с тем
же названием (Минск в Красноярском крае, Обь — реку). Такие координаты
уводили поиск в другую часть страны. Теперь название спрашивается как есть,
а страна уточняется только там, где это действительно нужно (HINTS).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from yandex_maps_parser.city_data import CITIES_CATALOG  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_coords_raw.json")

UA = "YandexBusinessParser-dev (local table generation; contact: repo owner)"
URL = "https://nominatim.openstreetmap.org/search?format=json&limit=10&q="

# Названия, которые без уточнения приводят не туда: «Обь» — это река, а не
# город, «Ростов» без области — то Ростов-на-Дону, то Ростов Великий.
HINTS = {
    "Обь": "Обь, Новосибирская область",
    "Заречный": "Заречный, Свердловская область",
    "Ростов": "Ростов-на-Дону",
}

# Тип объекта в OSM, который считаем самим городом (в порядке предпочтения).
_CITY_TYPES = ("city", "town", "municipality")


def ask(name: str) -> dict | None:
    """Лучший результат для названия: сам город, а не область и не река.

    Первый результат для «Москва» — административная область (центроид
    Новой Москвы, ~14 км южнее), и с ним поиск по сетке уходил бы мимо
    города. Поэтому предпочитаем addresstype=city, а всё остальное берём
    только если города в выдаче нет вовсе.
    """
    query = HINTS.get(name, name)
    url = URL + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        return None
    for wanted in _CITY_TYPES:
        for item in data:
            if (item.get("addresstype") or item.get("type")) == wanted:
                return item
    return data[0]


def _bbox_of(item: dict) -> dict | None:
    """Рамка города из ответа Nominatim либо None.

    boundingbox — четыре строки в порядке south, north, west, east. Мусор и
    перевёрнутые значения отбрасываем: пусть у города останется центр без
    рамки, чем сетка, обрезанная по отрицательной площади.
    """
    raw = item.get("boundingbox")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        south, north, west, east = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not (south < north and west < east):
        return None
    return {"s": round(south, 4), "n": round(north, 4),
            "w": round(west, 4), "e": round(east, 4)}


def main() -> int:
    out: dict[str, dict] = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as f:
                out = json.load(f)
        except Exception as exc:
            print(f"! старая выгрузка не читается ({type(exc).__name__}) — начнём заново",
                  file=sys.stderr)
            out = {}
    report: list[str] = []
    misses: list[str] = []
    asked = 0
    for city in CITIES_CATALOG:
        name = city["name"]
        have = out.get(name) or {}
        if have.get("lat") is not None and have.get("bbox"):
            report.append(f"{name}|{have.get('type', '?')}|{have['lat']}|{have['lon']}|"
                          f"{have.get('display', '')}|bbox cached")
            continue
        try:
            item = ask(name)
            asked += 1
        except Exception as exc:
            print(f"! {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            item = None
        if not item:
            misses.append(name)
            continue
        kind = item.get("addresstype") or item.get("type") or "?"
        out[name] = {
            "lat": round(float(item["lat"]), 4),
            "lon": round(float(item["lon"]), 4),
            "display": item.get("display_name", ""),
            "type": kind,
            "bbox": _bbox_of(item),
        }
        # Отчёт для глаз: тип объекта и что именно нашлось (в display_name
        # видно страну — так ловится «деревня с тем же названием»).
        bbox = out[name]["bbox"]
        report.append(f"{name}|{kind}|{out[name]['lat']}|{out[name]['lon']}|"
                      f"{out[name]['display']}|{'bbox ok' if bbox else 'bbox нет'}")
        time.sleep(1.1)      # политика Nominatim: не чаще 1 запроса в секунду

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    report_path = os.path.join(ROOT, "_coords_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")

    print(f"записано {OUT}: городов {len(out)} (запрошено в этот раз: {asked})")
    without_bbox = [name for name, item in out.items() if not item.get("bbox")]
    if without_bbox:
        print(f"без рамки: {', '.join(sorted(without_bbox))}", file=sys.stderr)
    print(f"отчёт {report_path}")
    if misses:
        print("не найдены:", ", ".join(misses), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
