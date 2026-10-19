# -*- coding: utf-8 -*-
"""Таблица координат городов: покрытие каталога и отсутствие чужих городов.

Таблица — офлайн-геокодер приложения, и ошибка в ней тихая: поиск честно
уходит по координатам, просто не в тот город. Так уже случилось, когда имя
запрашивалось с «, Россия»: для Минска нашлась деревня Минск в Красноярском
крае, для Алматы — посёлок в Ульяновской области, для Бишкека, Тбилиси,
Душанбе и Ашхабада — Подмосковье, а для Оби — река. Тесты держат точки
привязки и требуют, чтобы города вне России были на своих местах.

Run with: python -m pytest tests/test_city_coords.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import city_coords as cc
from yandex_maps_parser.city_data import CITIES_CATALOG

# Города-привязки: (имя, широта, долгота, допуск в градусах).
# Допуск ~0.3° (30 км) — центр города у OSM может быть центроидом границы,
# но другая страна или другой город такую проверку не пройдут.
ANCHORS = [
    ("Москва", 55.7505, 37.6175, 0.05),
    ("Санкт-Петербург", 59.94, 30.32, 0.1),
    ("Казань", 55.79, 49.11, 0.1),
    ("Екатеринбург", 56.84, 60.60, 0.1),
    ("Новосибирск", 54.97, 82.95, 0.1),
    ("Владивосток", 43.12, 131.89, 0.1),
    ("Сочи", 43.59, 39.72, 0.1),
    ("Мурманск", 68.97, 33.08, 0.1),
    # Города вне России: именно они попадали в чужие края.
    ("Минск", 53.90, 27.56, 0.1),
    ("Алматы", 43.24, 76.89, 0.15),
    ("Астана", 51.13, 71.43, 0.15),
    ("Ташкент", 41.31, 69.28, 0.15),
    ("Баку", 40.41, 49.87, 0.2),
    ("Бишкек", 42.88, 74.60, 0.15),
    ("Тбилиси", 41.70, 44.80, 0.2),
    ("Ереван", 40.18, 44.51, 0.15),
    ("Душанбе", 38.56, 68.79, 0.15),
    ("Ашхабад", 37.95, 58.33, 0.15),
    ("Кишинёв", 47.01, 28.86, 0.15),
    # «Обь» — река, а не только город: река в Ханты-Мансийском округе
    # (60.99, 75.51) уводила поиск на 700 км от Новосибирска.
    ("Обь", 55.00, 82.70, 0.15),
]

# Точка, которую Яндекс.Карты ставят по умолчанию — она же «Москва».
MOSCOW = (55.7505, 37.6175)


class TestCatalogCoverage:
    def test_every_catalog_city_has_coordinates(self):
        """Город предлагается в интерфейсе — значит, координаты обязаны быть."""
        missing = [c["name"] for c in CITIES_CATALOG if cc.lookup(c["name"]) is None]
        assert missing == []

    def test_lookup_returns_floats(self):
        for c in CITIES_CATALOG:
            lat, lon = cc.lookup(c["name"])
            assert isinstance(lat, float) and isinstance(lon, float)

    def test_coordinates_are_in_the_region_of_the_catalog(self):
        """Каталог — Россия и СНГ: 35…70° с. ш., 19…180° в. д."""
        bad = [(n, p) for n, p in cc.CITY_COORDS.items()
               if not (35.0 <= p[0] <= 70.0 and 19.0 <= p[1] <= 180.0)]
        assert bad == []

    def test_only_known_doublet_shares_coordinates(self):
        """Один и тот же центр у двух городов — признак подстановки не того."""
        by_point: dict[tuple, list[str]] = {}
        for name, point in cc.CITY_COORDS.items():
            by_point.setdefault(point, []).append(name)
        doubles = sorted(v for v in by_point.values() if len(v) > 1)
        assert doubles == [["Ростов", "Ростов-на-Дону"]]


class TestAnchors:
    def test_city_is_where_it_says(self):
        for name, lat, lon, tol in ANCHORS:
            got = cc.lookup(name)
            assert got is not None, f"{name}: нет в таблице"
            assert abs(got[0] - lat) <= tol and abs(got[1] - lon) <= tol, (
                f"{name}: в таблице {got}, ожидалось около ({lat}, {lon})")

    def test_no_city_sits_on_the_default_moscow_point(self):
        """Тот же баг, вид сбоку: чужой город с координатами Москвы."""
        for name, point in cc.CITY_COORDS.items():
            if name.startswith("Москв"):
                continue
            near = abs(point[0] - MOSCOW[0]) < 0.05 and abs(point[1] - MOSCOW[1]) < 0.05
            assert not near, f"{name}: координаты Москвы — город не опознан"


class TestBoundingBoxes:
    """Рамка города: по ней сетка обрезается, чтобы не тратить запросы на пригороды."""

    def test_every_catalog_city_has_a_box(self):
        missing = [c["name"] for c in CITIES_CATALOG if cc.lookup_bbox(c["name"]) is None]
        assert missing == [], f"без рамки: {missing}"

    def test_box_contains_the_center(self):
        for name, (lat, lon) in cc.CITY_COORDS.items():
            box = cc.lookup_bbox(name)
            assert box is not None, name
            south, north, west, east = box
            assert south < lat < north and west < lon < east, f"{name}: центр вне рамки {box}"

    def test_box_is_a_city_not_a_region(self):
        """Рамка области или края (больше ~150 км) увела бы сетку в поля."""
        for name, (south, north, west, east) in cc.CITY_BBOX.items():
            assert 0 < north - south < 1.5, f"{name}: широта {north - south:.2f}°"
            assert 0 < east - west < 1.5, f"{name}: долгота {east - west:.2f}°"

    def test_aliases_share_the_box(self):
        assert cc.lookup_bbox("СПб") == cc.CITY_BBOX["Санкт-Петербург"]
        assert cc.lookup_bbox("мск") == cc.CITY_BBOX["Москва"]
        assert cc.lookup_bbox("Казань, Татарстан") == cc.CITY_BBOX["Казань"]

    def test_unknown_city_has_no_box(self):
        """None — «рамки нет»: для города вне каталога её неоткуда взять."""
        assert cc.lookup_bbox("Атлантида") is None
        assert cc.lookup_bbox("") is None
        assert cc.lookup_bbox(None) is None


class TestLookupAliases:
    def test_aliases_resolve_to_the_real_city(self):
        assert cc.lookup("СПб") == cc.CITY_COORDS["Санкт-Петербург"]
        assert cc.lookup("питер") == cc.CITY_COORDS["Санкт-Петербург"]
        assert cc.lookup("мск") == cc.CITY_COORDS["Москва"]
        assert cc.lookup("ЕКБ") == cc.CITY_COORDS["Екатеринбург"]
        assert cc.lookup("ростов") == cc.CITY_COORDS["Ростов-на-Дону"]

    def test_latin_names_resolve(self):
        assert cc.lookup("Minsk") == cc.CITY_COORDS["Минск"]
        assert cc.lookup("Almaty") == cc.CITY_COORDS["Алматы"]
        assert cc.lookup("Chisinau") == cc.CITY_COORDS["Кишинёв"]

    def test_normalization_ignores_case_dots_and_hyphens(self):
        kazan = cc.CITY_COORDS["Казань"]
        assert cc.lookup("г. Казань") == kazan
        assert cc.lookup("КАЗАНЬ") == kazan
        spb = cc.CITY_COORDS["Санкт-Петербург"]
        assert cc.lookup("Санкт Петербург") == spb
        assert cc.lookup("Санкт-Петербург") == spb

    def test_city_with_region_in_one_string(self):
        assert cc.lookup("Казань, Татарстан") == cc.CITY_COORDS["Казань"]
        assert cc.lookup("Сочи, Краснодарский край") == cc.CITY_COORDS["Сочи"]

    def test_unknown_city_is_none(self):
        """None означает «геокодируй браузером», а не «ищи в Москве»."""
        assert cc.lookup("Атлантида") is None
        assert cc.lookup("") is None
        assert cc.lookup("   ") is None
        assert cc.lookup(None) is None

    def test_unlisted_city_is_not_silently_mapped_to_moscow(self):
        assert cc.lookup("Химки") is None
