"""
Tests for «🎯 Тип компании» («Только одиночки» / «Только новые»).

Covers: the branch-count annotation (incl. old raw files without the field),
the chain-merge maximum, both record predicates and their edge cases, the
normalisation of the period, the AND semantics inside apply_filters and the
counter breakdown the UI shows before «Применить фильтры заново».

Run with: python -m pytest tests/test_company_type.py -v
"""
import os
from datetime import datetime, timedelta

import pytest
from flask import Flask

from yandex_maps_parser import processing, state
from yandex_maps_parser.exporters import collapse_chains, collapse_chains_name_city, save_excel


# ── Helpers ───────────────────────────────────────────────────

def _days_ago(days: int) -> str:
    """Дата в формате записи branch/added_at (YYYY-MM-DD), N дней назад."""
    return (datetime.now().date() - timedelta(days=days)).strftime("%Y-%m-%d")


def _raw(tmp_path, records, name="raw_company_type.xlsx"):
    """Raw-файл этапа 2 с внутренними колонками «типа компании»."""
    path = str(tmp_path / name)
    save_excel(records, path,
               extra_fields=("website", "branch_count", "added_at"))
    return path


# ── branch_count: аннотация по собранным данным ───────────────

class TestAnnotateBranchCounts:
    def test_counts_branches_of_one_chain(self):
        recs = [
            {"name": "Кофейня А", "city": "Уфа"},
            {"name": "Кофейня А", "city": "Уфа"},
            {"name": "Кофейня А", "city": "Уфа"},
            {"name": "Одиночка", "city": "Уфа"},
        ]
        processing.annotate_branch_counts(recs)
        assert [r["branch_count"] for r in recs] == [3, 3, 3, 1]

    def test_same_name_in_another_city_is_not_a_branch(self):
        recs = [{"name": "Сеть Б", "city": "Уфа"}, {"name": "Сеть Б", "city": "Казань"}]
        processing.annotate_branch_counts(recs)
        assert [r["branch_count"] for r in recs] == [1, 1]

    def test_api_value_wins_when_it_is_larger(self):
        """items.org.branch_count знает про филиалы вне нашего сбора."""
        recs = [{"name": "Сеть В", "city": "Уфа", "branch_count": "7"},
                {"name": "Сеть В", "city": "Уфа"}]
        processing.annotate_branch_counts(recs)
        assert [r["branch_count"] for r in recs] == [7, 7]

    def test_our_count_wins_for_standalone_org(self):
        """API сказал 0 (филиалов нет) — но запись-то у нас одна, одиночка."""
        recs = [{"name": "Точка Г", "city": "Уфа", "branch_count": 0}]
        processing.annotate_branch_counts(recs)
        assert recs[0]["branch_count"] == 1

    def test_is_idempotent(self):
        recs = [{"name": "Сеть Д", "city": "Уфа"}, {"name": "Сеть Д", "city": "Уфа"}]
        processing.annotate_branch_counts(recs)
        first = [r["branch_count"] for r in recs]
        processing.annotate_branch_counts(recs)
        assert [r["branch_count"] for r in recs] == first == [2, 2]

    def test_records_without_a_name_stay_unknown(self):
        """Без названия филиалы не посчитать — поле остаётся пустым, и фильтр
        такую запись пропускает (неизвестное ≠ одиночка)."""
        recs = [{"name": "", "city": "Уфа"}, {"name": "Имя", "city": "Уфа"}]
        processing.annotate_branch_counts(recs)
        assert recs[0].get("branch_count", "") == ""
        assert recs[1]["branch_count"] == 1


# ── Объединение филиалов не должно «превращать» сеть в одиночку ──

class TestChainMergeKeepsBranchCount:
    def _chain(self):
        return [
            {"name": "Сеть Е", "city": "Уфа", "phone": "+7 111", "branch_count": 3},
            {"name": "Сеть Е", "city": "Уфа", "phone": "+7 222", "branch_count": 3},
            {"name": "Сеть Е", "city": "Уфа", "phone": "+7 333", "branch_count": 5},
        ]

    def test_name_city_merge_keeps_max(self):
        merged = collapse_chains_name_city(self._chain())
        assert len(merged) == 1
        assert merged[0]["branch_count"] == 5

    def test_contact_merge_keeps_max(self):
        # Стратегия «по названию»: ветки без общих контактов схлопываются тоже
        # (name_city режет группу по совпадению телефонов — там другое правило).
        merged = collapse_chains(self._chain(), "name")
        assert len(merged) == 1
        assert merged[0]["branch_count"] == 5

    def test_merge_does_not_invent_a_count_when_all_unknown(self):
        merged = collapse_chains_name_city([
            {"name": "Сеть Ж", "city": "Уфа", "phone": "+7 111"},
            {"name": "Сеть Ж", "city": "Уфа", "phone": "+7 222"},
        ])
        assert len(merged) == 1
        assert merged[0].get("branch_count", "") == ""


# ── Предикаты ─────────────────────────────────────────────────

class TestPredicates:
    def test_single_branch(self):
        assert processing.is_single_branch({"branch_count": 1}) is True
        assert processing.is_single_branch({"branch_count": "1"}) is True
        assert processing.is_single_branch({"branch_count": 0}) is True   # 0 = филиалов нет
        assert processing.is_single_branch({"branch_count": 2}) is False
        assert processing.is_single_branch({"branch_count": 100}) is False

    def test_single_branch_without_data_passes(self):
        for rec in ({}, {"branch_count": ""}, {"branch_count": "не число"}):
            assert processing.is_single_branch(rec) is True

    def test_new_company_by_date(self):
        assert processing.is_new_company({"added_at": _days_ago(10)}, 6) is True
        assert processing.is_new_company({"added_at": _days_ago(200)}, 6) is False
        assert processing.is_new_company({"added_at": _days_ago(10)}, 1) is True
        assert processing.is_new_company({"added_at": _days_ago(40)}, 1) is False
        assert processing.is_new_company({"added_at": _days_ago(900)}, 24) is False

    def test_new_company_boundary_is_inclusive(self):
        """Ровно N месяцев назад ещё считается новой: 30 дней ≈ месяц."""
        assert processing.is_new_company({"added_at": _days_ago(30)}, 1) is True
        assert processing.is_new_company({"added_at": _days_ago(31)}, 1) is False

    def test_new_company_without_date_passes(self):
        for rec in ({}, {"added_at": ""}, {"added_at": "не дата"}, {"added_at": "01.02.2026"}):
            assert processing.is_new_company(rec, 6) is True

    def test_filter_off_passes_everything(self):
        assert processing.is_new_company({"added_at": _days_ago(9999)}, None) is True
        assert processing.is_new_company({"added_at": _days_ago(9999)}, 0) is True


class TestNormalizeMonths:
    def test_allowed_periods(self):
        for n in (1, 3, 6, 12, 24):
            assert processing.normalize_only_new_months(n) == n
            assert processing.normalize_only_new_months(str(n)) == n

    def test_unknown_period_falls_back_to_default(self):
        assert processing.normalize_only_new_months(7) == processing.NEW_COMPANY_DEFAULT_MONTHS
        assert processing.normalize_only_new_months("мусор") == processing.NEW_COMPANY_DEFAULT_MONTHS

    def test_off_values(self):
        for value in (None, "", 0, "0", False, -3):
            assert processing.normalize_only_new_months(value) is None


# ── Счётчик «будет найдено» ───────────────────────────────────

class TestBreakdown:
    def _recs(self):
        return [
            {"name": "Одиночка новая", "branch_count": 1, "added_at": _days_ago(5)},
            {"name": "Одиночка старая", "branch_count": 1, "added_at": _days_ago(900)},
            {"name": "Сеть новая", "branch_count": 4, "added_at": _days_ago(20)},
            {"name": "Сеть старая", "branch_count": 4, "added_at": _days_ago(900)},
            {"name": "Без данных", "branch_count": "", "added_at": ""},
        ]

    def test_counts_each_filter_and_their_intersection(self):
        info = processing.company_type_breakdown(self._recs(), 6)
        assert info["total"] == 5
        assert info["single"] == 3          # две одиночки + запись без данных
        assert info["new"] == 3             # две новые + запись без данных
        assert info["both"] == 2
        assert info["with_date"] == 4       # у «Без данных» даты нет
        assert info["months"] == 6

    def test_months_are_normalized_like_the_filter(self):
        assert processing.company_type_breakdown([], 7)["months"] == 6
        assert processing.company_type_breakdown([], None)["months"] is None

    def test_empty_input(self):
        assert processing.company_type_breakdown([], 6) == {
            "total": 0, "single": 0, "new": 0, "both": 0, "with_date": 0, "months": 6}


# ── apply_filters: AND + счётчики ─────────────────────────────

class TestApplyFilters:
    def _raw(self, tmp_path):
        return _raw(tmp_path, [
            {"city": "Уфа", "name": "Одиночка", "query": "кафе", "branch_count": 1},
            {"city": "Уфа", "name": "Сеть", "query": "кафе", "branch_count": 4},
            {"city": "Уфа", "name": "Просто", "query": "кафе"},
        ])

    def test_only_single_keeps_ones_and_unknowns(self, tmp_path):
        res = processing.apply_filters([self._raw(tmp_path)], {"only_single_branch": True})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Одиночка", "Просто"}      # без данных — пропускаем
        assert res["single_excluded"] == 1
        assert res["company_type_excluded"] == 1

    def test_both_filters_are_an_and(self, tmp_path):
        raw = _raw(tmp_path, [
            {"city": "Уфа", "name": "Одиночка новая", "query": "кафе",
             "branch_count": 1, "added_at": _days_ago(3)},
            {"city": "Уфа", "name": "Одиночка старая", "query": "кафе",
             "branch_count": 1, "added_at": _days_ago(900)},
            {"city": "Уфа", "name": "Сеть новая", "query": "кафе",
             "branch_count": 5, "added_at": _days_ago(3)},
        ], name="raw_and.xlsx")
        res = processing.apply_filters(
            [raw], {"only_single_branch": True, "only_new_months": 6})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Одиночка новая"}
        assert res["single_excluded"] == 1
        assert res["new_excluded"] == 1
        assert res["company_type_excluded"] == 2

    def test_filters_off_change_nothing(self, tmp_path):
        res = processing.apply_filters([self._raw(tmp_path)], {})
        assert res["count"] == 3
        assert res["company_type_excluded"] == 0

    def test_unknown_period_falls_back_to_six_months(self, tmp_path):
        """Период 7 месяцев — не из списка: применяется дефолт (6), а не «выкл.»."""
        raw = _raw(tmp_path, [
            {"city": "Уфа", "name": "Новых", "query": "кафе", "added_at": _days_ago(20)},
            {"city": "Уфа", "name": "Старых", "query": "кафе", "added_at": _days_ago(200)},
        ], name="raw_period.xlsx")
        res = processing.apply_filters([raw], {"only_new_months": 7})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Новых"}
        # Дефолт тот же, что у явной шестёрки.
        res6 = processing.apply_filters([raw], {"only_new_months": 6})
        assert {r["name"] for r in res6["groups"]["кафе"]["Уфа"]} == names

    def test_old_raw_files_without_the_field_still_work(self, tmp_path):
        """Файл, собранный до этой версии: колонок нет вообще — сеть из двух
        строк должна распознаться счётом по «название + город»."""
        path = str(tmp_path / "raw_old.xlsx")
        save_excel([
            {"city": "Уфа", "name": "Сеть старая", "query": "кафе", "phone": "+7 111"},
            {"city": "Уфа", "name": "Сеть старая", "query": "кафе", "phone": "+7 222"},
            {"city": "Уфа", "name": "Один", "query": "кафе", "phone": "+7 333"},
        ], path)
        res = processing.apply_filters([str(path)], {"only_single_branch": True})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Один"}


# ── Raw-выгрузка несёт оба поля ───────────────────────────────

class TestRawRoundTrip:
    def test_export_raw_records_writes_the_new_columns(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state, "RAW_DIR", str(tmp_path / "raw"))
        os.makedirs(state.RAW_DIR, exist_ok=True)
        path = processing.export_raw_records(
            [{"name": "Филиал", "city": "Уфа", "query": "кафе",
              "branch_count": 3, "added_at": "2026-05-04"}],
            "кафе", "Уфа")
        assert "branch_count" in processing.load_raw_records(path)[0]
        back = processing.load_raw_records(path)[0]
        assert int(back["branch_count"]) == 3
        assert back["added_at"] == "2026-05-04"

    def test_raw_columns_do_not_leak_into_the_report(self):
        """Внутренние колонки, как website: состав отчёта не меняется."""
        from yandex_maps_parser.constants import CSV_FIELDS
        assert "branch_count" not in CSV_FIELDS
        assert "added_at" not in CSV_FIELDS


# ── POST /preview-company-type ────────────────────────────────

_ROWS = [
    {"name": "Одиночка новая", "branch_count": 1, "added_at": _days_ago(5)},
    {"name": "Одиночка старая", "branch_count": 1, "added_at": _days_ago(900)},
    {"name": "Сеть новая", "branch_count": 4, "added_at": _days_ago(20)},
    {"name": "Без данных"},
]


@pytest.fixture()
def client(monkeypatch):
    from routes import api as api_mod

    monkeypatch.setattr(api_mod, "_collect_records",
                        lambda view, rel_file=None, scope="current":
                        [dict(r) for r in _ROWS])
    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


class TestPreviewCompanyType:
    def test_counts_single_new_and_their_intersection(self, client):
        data = client.post("/preview-company-type",
                           json={"only_single_branch": True, "only_new_months": 6}).get_json()
        assert data["ok"] is True
        assert data["total"] == 4
        assert data["single"] == 3          # две одиночки + запись без данных
        assert data["new"] == 3             # две новые + запись без данных
        assert data["both"] == 2
        assert data["with_date"] == 3
        assert data["months"] == 6

    def test_thin_body_is_safe(self, client):
        data = client.post("/preview-company-type", json={}).get_json()
        assert data["ok"] is True
        assert data["months"] is None, "без фильтра период не выдумывается"
        assert data["single"] == 3

    def test_period_is_normalized_like_the_filter(self, client):
        assert client.post("/preview-company-type",
                           json={"only_new_months": 7}).get_json()["months"] == 6
        assert client.post("/preview-company-type",
                           json={"only_new_months": 0}).get_json()["months"] is None

    def test_counter_matches_the_stage_2_result(self, client, tmp_path):
        """Цифра в подсказке и результат «Применить фильтры заново» — одно и то же."""
        data = client.post("/preview-company-type",
                           json={"only_single_branch": True, "only_new_months": 6}).get_json()
        raw = _raw(tmp_path, [dict(r, city="Уфа", query="кафе") for r in _ROWS],
                   name="raw_preview.xlsx")
        res = processing.apply_filters([raw], {"only_single_branch": True,
                                               "only_new_months": 6})
        assert res["count"] == data["both"]

    def test_old_records_get_their_branch_count_annotated(self, client, monkeypatch):
        """Файл без поля branch_count: превью считает филиалы само."""
        from routes import api as api_mod
        monkeypatch.setattr(api_mod, "_collect_records", lambda *a, **kw: [
            {"name": "Сеть", "city": "Уфа"},
            {"name": "Сеть", "city": "Уфа"},
            {"name": "Один", "city": "Уфа"},
        ])
        data = client.post("/preview-company-type",
                           json={"only_single_branch": True}).get_json()
        assert data["single"] == 1, "сеть из двух строк не должна считаться одиночкой"

    def test_records_are_not_mutated_between_calls(self, client):
        first = client.post("/preview-company-type", json={"only_new_months": 6}).get_json()
        second = client.post("/preview-company-type", json={"only_new_months": 6}).get_json()
        assert first == second

    def test_client_and_server_agree_on_periods(self):
        """Реестр месяцев и дефолт в браузере — те же, что на сервере."""
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        app_js = open(os.path.join(root, "static", "js", "app.js"),
                      encoding="utf-8").read()
        decl = re.search(r"const COMPANY_TYPE_PERIODS = \{(.*?)\};\n", app_js, re.S)
        assert decl, "нет COMPANY_TYPE_PERIODS в app.js"
        assert [int(n) for n in re.findall(r"(\d+):", decl.group(1))] == \
            list(processing.COMPANY_TYPE_MONTHS)
        default = re.search(r"const COMPANY_TYPE_DEFAULT_MONTHS = (\d+);", app_js)
        assert default and int(default.group(1)) == processing.NEW_COMPANY_DEFAULT_MONTHS

    def test_broken_source_reports_instead_of_failing(self, monkeypatch):
        from routes import api as api_mod

        def _boom(*a, **kw):
            raise OSError("сырые файлы недоступны")

        monkeypatch.setattr(api_mod, "_collect_records", _boom)
        app = Flask(__name__)
        app.register_blueprint(api_mod.bp)
        resp = app.test_client().post("/preview-company-type", json={})
        assert resp.status_code == 500
        assert resp.get_json()["ok"] is False
