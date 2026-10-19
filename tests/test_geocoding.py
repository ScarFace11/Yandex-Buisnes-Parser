# -*- coding: utf-8 -*-
"""Геокодинг: центр города и сетка точек покрытия.

Регрессия, из-за которой сетка не работала вовсе: `build_grid` обращался к
`state`, но модуль его не импортировал — «Настроить вручную» падало с
NameError на первом же городе. Тест держит вызов без импорта снаружи: ошибка
возвращается сразу, а не через полчаса прогона.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import geocoding, state


class TestBuildGrid:
    def test_grid_works_without_extra_imports(self, monkeypatch):
        """Тот самый NameError: state должен быть доступен внутри модуля."""
        monkeypatch.setattr(state, "GRID_RADIUS_KM", 10, raising=False)
        monkeypatch.setattr(state, "GRID_STEP_KM", 5, raising=False)
        points = geocoding.build_grid(54.5101, 36.2598, None)
        assert points, "сетка не должна быть пустой"

    def test_center_is_always_inside(self, monkeypatch):
        monkeypatch.setattr(state, "GRID_RADIUS_KM", 10, raising=False)
        monkeypatch.setattr(state, "GRID_STEP_KM", 4, raising=False)
        points = geocoding.build_grid(55.7505, 37.6175, None)
        assert (55.7505, 37.6175) in points

    def test_all_points_fit_the_radius(self, monkeypatch):
        monkeypatch.setattr(state, "GRID_RADIUS_KM", 12, raising=False)
        monkeypatch.setattr(state, "GRID_STEP_KM", 5, raising=False)
        clat, clon = 54.5101, 36.2598
        for lat, lon in geocoding.build_grid(clat, clon, None):
            dlat = (lat - clat) * 111.32
            dlon = (lon - clon) * 111.32 * 0.58  # cos(54.5°) ≈ 0.58
            assert dlat ** 2 + dlon ** 2 <= 12 ** 2 + 1

    def test_envelope_clips_the_circle(self, monkeypatch):
        """Рамка города только сужает круг: точки вне неё не строятся."""
        monkeypatch.setattr(state, "GRID_RADIUS_KM", 20, raising=False)
        monkeypatch.setattr(state, "GRID_STEP_KM", 5, raising=False)
        clat, clon = 54.5101, 36.2598
        full = geocoding.build_grid(clat, clon, None)
        clipped = geocoding.build_grid(clat, clon, (clat - 0.05, clat + 0.05,
                                                    clon - 0.05, clon + 0.05))
        assert len(clipped) < len(full)
        assert all(abs(lat - clat) <= 0.05 + 1e-9 and abs(lon - clon) <= 0.05 + 1e-9
                   for lat, lon in clipped)


class TestCiytCenter:
    def test_catalog_city_has_coordinates_and_no_browser_needed(self, monkeypatch):
        """Города каталога не ходят в браузер вовсе — координаты из таблицы."""
        from yandex_maps_parser import browser_search

        def boom(*_a, **_k):
            raise AssertionError("браузер для города каталога не нужен")

        monkeypatch.setattr(browser_search, "_center_from_browser", boom)
        monkeypatch.setattr(browser_search, "_city_cache", {})
        assert browser_search.city_center("Калуга") == (54.5101, 36.2598)

    def test_unknown_city_returns_none_only_after_browser(self, monkeypatch):
        """Незнакомый город — это None (поиск по тексту), а не «Москва»."""
        from yandex_maps_parser import browser_search

        monkeypatch.setattr(browser_search, "_city_cache", {})
        monkeypatch.setattr(browser_search, "_center_from_disk", lambda _key: None)
        monkeypatch.setattr(browser_search, "_center_from_browser", lambda _city: None)
        assert browser_search.city_center("Химки-тест-неизвестный") is None


class TestCityEnvelope:
    """Рамка города обрезает сетку: меньше запросов и никаких полей за городом."""

    def test_catalog_city_gets_envelope_from_the_table(self, monkeypatch):
        from yandex_maps_parser import geocoding

        monkeypatch.setattr(geocoding, "city_center", lambda city: (55.7946, 49.1115))
        geocoding._geocode_cache.clear()
        lat, lon, envelope = geocoding.geocode_city("Казань")
        assert envelope is not None, "город каталога обязан получить рамку без сети"
        south, north, west, east = envelope
        assert south < lat < north and west < lon < east

    def test_unknown_city_has_no_envelope(self, monkeypatch):
        from yandex_maps_parser import geocoding

        monkeypatch.setattr(geocoding, "city_center", lambda city: (55.89, 37.45))
        geocoding._geocode_cache.clear()
        assert geocoding.geocode_city("Химки-тест-неизвестный")[2] is None

    def test_grid_is_clipped_by_the_city_box(self, monkeypatch):
        from yandex_maps_parser import geocoding
        from yandex_maps_parser.city_coords import lookup_bbox

        monkeypatch.setattr(state, "GRID_RADIUS_KM", 60, raising=False)
        monkeypatch.setattr(state, "GRID_STEP_KM", 10, raising=False)
        lat, lon = 55.7946, 49.1115
        box = lookup_bbox("Казань")
        full = geocoding.build_grid(lat, lon, None)
        clipped = geocoding.build_grid(lat, lon, box)
        assert len(clipped) < len(full), "рамка должна отсекать точки за городом"
        south, north, west, east = box
        for plat, plon in clipped:
            assert south - 1e-9 <= plat <= north + 1e-9
            assert west - 1e-9 <= plon <= east + 1e-9
        assert (lat, lon) in clipped, "центр города обязан остаться в сетке"
