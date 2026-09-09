"""Tests for the configurable Excel export columns (web form «Выгрузка Excel»)."""
import os
import tempfile

import openpyxl

from yandex_maps_parser import state
from yandex_maps_parser.constants import CSV_FIELDS
from yandex_maps_parser.exporters import _enabled_fields, save_excel

RECORDS = [
    {
        "reviewed": "",
        "name": "Тест",
        "category": "Бар",
        "phone": "+7 999 123-45-67",
        "rating": "4.5",
        "reviews": 10,
        "vk": "https://vk.com/test",
        "query": "бар",
        "parsed_at": "2026-09-07",
    }
]


def _xlsx_headers(records, columns):
    state.EXCEL_COLUMNS = columns
    try:
        path = os.path.join(tempfile.mkdtemp(), "t.xlsx")
        save_excel(records, path)
        wb = openpyxl.load_workbook(path)
        try:
            ws = wb.active
            return [c.value for c in ws[1]], list(ws.iter_rows(values_only=True))[1]
        finally:
            wb.close()
    finally:
        state.EXCEL_COLUMNS = None


def test_enabled_fields_all_by_default():
    assert _enabled_fields() == CSV_FIELDS


def test_enabled_fields_subset_keeps_csv_order():
    state.EXCEL_COLUMNS = {"vk", "name", "phone"}
    try:
        assert _enabled_fields() == ["name", "phone", "vk"]
    finally:
        state.EXCEL_COLUMNS = None


def test_excel_writes_only_selected_columns():
    headers, row = _xlsx_headers(RECORDS, {"name", "phone", "vk"})
    assert headers == ["Название", "Телефон", "ВКонтакте"]
    assert row == ("Тест", "+7 999 123-45-67", "https://vk.com/test")


def test_excel_includes_all_columns_when_none_selected():
    headers, row = _xlsx_headers(RECORDS, None)
    assert len(headers) == len(CSV_FIELDS)
    assert "Название" in headers and "ВКонтакте" in headers
    assert row[headers.index("Название")] == "Тест"
    assert row[headers.index("ВКонтакте")] == "https://vk.com/test"