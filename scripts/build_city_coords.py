# -*- coding: utf-8 -*-
"""Собрать yandex_maps_parser/city_coords.py из выгрузки scripts/gen_city_coords.py."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "yandex_maps_parser" / "city_coords.py"

HEAD = '''# -*- coding: utf-8 -*-
"""Координаты центров городов — офлайн-справочник для геокодинга.

Геокодер-API Яндекса платный (а бесплатная версия запрещает сохранять
данные), поэтому раньше центр города брался из карты: страница поиска по
названию города сама проставляет центр в адресе (ll/sll). Способ рабочий, но
у него две беды, из-за которых поиск уезжал не в тот город:

* если Яндекс НЕ узнал название, он оставляет центр по умолчанию (Москву) —
  и прогон молча шёл по Москве, а сетка точек строилась вокруг неё;
* на каждый город тратилась навигация браузера (это же и лишний повод для
  антибота), а при медленной странице координат не было вовсе.

Теперь для городов из каталога приложения координаты берутся отсюда: быстро,
без сети и без браузера. Браузер остаётся запасным вариантом для названий вне
каталога — с проверкой, что найденный центр не «Москва по умолчанию».

Источник данных: OpenStreetMap через Nominatim. Название спрашивается как
есть (без «, Россия» — иначе для Минска, Алматы и Ташкента находилась деревня
с тем же названием в России), из выдачи берётся объект типа city/town.
Данные (c) участники OpenStreetMap, лицензия ODbL 1.0
(https://www.openstreetmap.org/copyright). Таблица генерируется скриптами
scripts/gen_city_coords.py и scripts/build_city_coords.py.

Кроме центра здесь лежит рамка города (boundingbox OSM): сетка точек поиска
обрезается по ней, иначе круг радиусом 20 км захватывает пригороды и соседние
районы — запросы уходят в поля и тратят квоту впустую.
"""

# Название города → (широта, долгота) центра.
CITY_COORDS: dict[str, tuple[float, float]] = {
'''

TAIL = '''}

# Название города → рамка (юг, север, запад, восток) — порядок Nominatim.
# Город без рамки остаётся с одним центром: сетка тогда строится по кругу,
# как раньше. Путать эти два случая нельзя — «рамки нет» не значит «город
# размером с точку».
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
__BBOX_ROWS__
}

# Как город пишут руками: сокращения и разговорные варианты. Ключи — уже
# нормализованные (см. _normalize): нижний регистр, без точек, «ё» → «е»,
# дефисы заменены пробелами.
ALIASES: dict[str, str] = {
    "мск": "Москва",
    "спб": "Санкт-Петербург",
    "питер": "Санкт-Петербург",
    "петербург": "Санкт-Петербург",
    "ленинград": "Санкт-Петербург",
    "екб": "Екатеринбург",
    "нск": "Новосибирск",
    "нн": "Нижний Новгород",
    "н новгород": "Нижний Новгород",
    "нижний": "Нижний Новгород",
    "ростов": "Ростов-на-Дону",
    "ростов дону": "Ростов-на-Дону",
    "челны": "Набережные Челны",
    "наб челны": "Набережные Челны",
    "улан удэ": "Улан-Удэ",
    "комсомольск": "Комсомольск-на-Амуре",
    "орел": "Орёл",
    "белгород": "Белгород",
    "петропавловск камчатский": "Петропавловск-Камчатский",
    # Столицы СНГ пишут и латиницей — координаты у них в таблице есть.
    "minsk": "Минск",
    "almaty": "Алматы",
    "astana": "Астана",
    "nur sultan": "Астана",
    "tashkent": "Ташкент",
    "baku": "Баку",
    "bishkek": "Бишкек",
    "tbilisi": "Тбилиси",
    "yerevan": "Ереван",
    "dushanbe": "Душанбе",
    "ashgabat": "Ашхабад",
    "chisinau": "Кишинёв",
    "кишинев": "Кишинёв",
}


def _normalize(name: str) -> str:
    """Название города к виду, в котором оно ищется в таблице.

    Убираем регистр, точки (пишут «г. Казань»), «ё», лишние пробелы и
    разницу между дефисом и пробелом («Санкт-Петербург» / «Санкт Петербург»).
    """
    text = str(name or "").lower().replace("ё", "е")
    text = text.replace("г.", " ").replace(".", " ")
    text = text.replace("-", " ").replace("\\u00a0", " ")
    return " ".join(text.split())


# Нормализованное имя → координаты и рамка: готовится один раз при импорте.
_BY_NORMALIZED: dict[str, tuple[float, float]] = {
    _normalize(name): coords for name, coords in CITY_COORDS.items()
}
_BBOX_BY_NORMALIZED: dict[str, tuple[float, float, float, float]] = {
    _normalize(name): box for name, box in CITY_BBOX.items()
}


def _canonical(city: str) -> str | None:
    """Нормализованное имя, под которым город лежит в таблицах.

    Одно место для сокращений и «Казань, Татарстан»: и центр, и рамка
    находятся по одному и тому же ключу, иначе у «СПб» был бы центр, а
    рамки не было бы вовсе.
    """
    key = _normalize(city)
    if not key:
        return None
    if key in _BY_NORMALIZED or key in _BBOX_BY_NORMALIZED:
        return key
    alias = ALIASES.get(key)
    if alias:
        return _normalize(alias)
    # «Казань, Татарстан» — город в начале строки.
    return key.split(",")[0].strip() or None


def lookup(city: str) -> tuple[float, float] | None:
    """Координаты центра города из таблицы либо None (города там нет).

    Таблица покрывает города каталога приложения — те, что предлагаются в
    интерфейсе. Для остальных названий координаты ищет браузер.
    """
    key = _canonical(city)
    return _BY_NORMALIZED.get(key) if key else None


def lookup_bbox(city: str) -> tuple[float, float, float, float] | None:
    """Рамка города (юг, север, запад, восток) либо None.

    None — «рамки в таблице нет»: для города вне каталога её и неоткуда
    взять, а для каталожного она могла не приехать с Nominatim. В обоих
    случаях сетка строится по кругу: тихо подменять рамку центром нельзя.
    """
    key = _canonical(city)
    return _BBOX_BY_NORMALIZED.get(key) if key else None
'''


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_coords_raw.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = "\n".join(
        f'    {json.dumps(name, ensure_ascii=False)}: ({item["lat"]}, {item["lon"]}),'
        for name, item in sorted(data.items())
    )
    boxes = "\n".join(
        f'    {json.dumps(name, ensure_ascii=False)}: '
        f'({box["s"]}, {box["n"]}, {box["w"]}, {box["e"]}),'
        for name, item in sorted(data.items())
        for box in [item.get("bbox")]
        if isinstance(box, dict)
    )
    OUT.write_text(HEAD + rows + "\n" + TAIL.replace("__BBOX_ROWS__", boxes),
                   encoding="utf-8", newline="\r\n")
    count_boxes = len([1 for item in data.values() if isinstance(item.get("bbox"), dict)])
    print(f"записано {OUT}: городов {len(data)}, с рамкой {count_boxes}")
    if count_boxes < len(data):
        print("Города без рамки: сетка для них строится по кругу (см. gen_city_coords).",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
