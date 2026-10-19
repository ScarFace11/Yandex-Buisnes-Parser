# -*- coding: utf-8 -*-
"""Сферы бизнеса: каталог запросов и история по сферам.

Каталог — единственное место, где живут «правильные» слова для поиска.
Ошибка здесь тихая: выдача придёт, просто по другому слову и заметно беднее.
Поэтому проверяем не только наличие сфер, но и склейку с историей: по ней
пользователь решает, парсить ли город снова.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import spheres


class TestCatalog:
    def test_catalog_is_not_empty_and_serializable(self):
        items = spheres.catalog()
        assert len(items) >= 20
        for item in items:
            assert set(item) == {"id", "name", "icon", "queries"}
            assert item["id"] and item["name"]
            assert item["queries"], f"{item['id']}: набор запросов пуст"
            assert all(isinstance(q, str) and q.strip() for q in item["queries"])

    def test_ids_are_unique(self):
        ids = [s["id"] for s in spheres.catalog()]
        assert len(ids) == len(set(ids))

    def test_every_query_is_lowercase_and_trimmed(self):
        """«Тренажёрный» пишется через «ё» — это нормально: сравнение
        нормализует «ё» с обеих сторон, а лишние пробелы ломали бы запрос."""
        for item in spheres.catalog():
            for q in item["queries"]:
                assert q == q.lower(), q
                assert q == q.strip(), q
                assert "  " not in q, q


class TestMatching:
    def test_one_word_of_a_sphere_is_enough(self):
        assert spheres.sphere_for_queries(["кафе"])["id"] == "cafe"
        assert spheres.sphere_for_queries(["кофейня"])["id"] == "cafe"

    def test_second_word_is_found_too(self):
        assert spheres.sphere_for_queries(["барбершоп"])["id"] == "hair"
        assert spheres.sphere_for_queries(["зубной врач"])["id"] == "dental"

    def test_case_and_yo_are_ignored(self):
        assert spheres.sphere_for_queries(["САЛОН КРАСОТЫ"])["id"] == "beauty"
        assert spheres.sphere_for_queries(["тренажёрный зал"])["id"] == "fitness"
        assert spheres.sphere_for_queries(["тренажерный зал"])["id"] == "fitness"

    def test_unknown_query_is_not_a_sphere(self):
        assert spheres.sphere_for_queries(["атомный реактор"]) is None
        assert spheres.sphere_for_queries([]) is None
        assert spheres.match_text(["атомный реактор"]) == ""


class TestHistory:
    def test_last_run_and_cities_are_aggregated(self):
        entries = [
            {"timestamp": 300.0, "queries": ["кафе"], "cities": ["Москва"], "results_count": 10},
            {"timestamp": 200.0, "queries": ["кафе", "кофейня"], "cities": ["Казань", "Москва"], "results_count": 5},
            {"timestamp": 100.0, "queries": ["стоматология"], "cities": ["Уфа"], "results_count": 7},
        ]
        summary = {s["id"]: s for s in spheres.history_summary(entries)}
        cafe = summary["cafe"]
        assert cafe["last_ts"] == 300.0, "история отсортирована — первый вход и есть последний запуск"
        assert cafe["runs"] == 2
        assert cafe["results"] == 15
        assert cafe["cities"] == ["Москва", "Казань"], "города объединяются без повторов"
        assert cafe["cities_total"] == 2
        assert summary["dental"]["runs"] == 1
        assert "hair" not in summary

    def test_entries_without_spheres_are_skipped(self):
        summary = spheres.history_summary([
            {"timestamp": 1.0, "queries": ["атомный реактор"], "cities": ["Москва"]},
        ])
        assert summary == []

    def test_cities_are_capped_so_the_dropdown_stays_readable(self):
        entries = [{"timestamp": 1.0, "queries": ["кафе"],
                    "cities": ["А", "Б", "В", "Г", "Д", "Е", "Ж"]}]
        summary = spheres.history_summary(entries)[0]
        assert len(summary["cities"]) == 5
        assert summary["cities_total"] == 7, "+2 в подписи не должно теряться"
