# -*- coding: utf-8 -*-
"""social_normalize в экспорте: канонические значения в CSV/Excel/JSON.

Модуль лежал мёртвым (0 импортов), теперь подключён ко всем точкам записи:
save_csv / save_json / save_excel / _append_excel и выгрузке выборки
/export-filtered. Здесь проверяется и то, и другое:

* сами функции — по примерам из их докстрингов;
* normalize_record — поля преобразуются, чужие не трогаются, идемпотентность;
* каждый писатель отдаёт нормализованные значения при чтении обратно.
"""
import csv
import io
import json

import pytest
from flask import Flask

from yandex_maps_parser.exporters import (
    _records_from_xlsx,
    save_csv,
    save_excel,
    save_json,
)
from yandex_maps_parser.social_normalize import (
    dedupe_phones,
    ensure_https,
    normalize_record,
    normalize_ru_phone,
    normalize_vk_url,
    normalize_whatsapp_url,
    split_phones,
)


# Грязная запись ровно в том виде, в каком она приходит из парсера:
# дубль телефона, vk.ru вместо vk.com, битый wa.me с «восьмой», http-сайт.
DIRTY = {
    "name": "Кафе «Пример»",
    "city": "Казань",
    "query": "кафе",
    "address": "ул. Баумана, 1",
    "phone": "+7 (843) 203-38-80, +7 (927) 674-35-03, 88432033880",
    "vk": "https://vk.ru/club42",
    "whatsapp": "https://wa.me/89376154245",
    "website": "http://taplink.cc/cafe",
}

CLEAN_PHONE = "+7 (843) 203-38-80, +7 (927) 674-35-03"
CLEAN_WA = "https://wa.me/79376154245"
CLEAN_VK = "https://vk.com/club42"


# ── Unit: сами функции (примеры из докстринга) ────────────────

class TestPhones:
    def test_ru_phone_national_format(self):
        assert normalize_ru_phone("8 937 615-42-45") == "79376154245"

    def test_ru_phone_plus7_format(self):
        assert normalize_ru_phone("+7 (987) 007-00-16") == "79870070016"

    def test_ru_phone_rejects_short_and_8800(self):
        assert normalize_ru_phone("12345") == ""
        assert normalize_ru_phone("8 800 100-10-10") == ""

    def test_split_phones(self):
        assert split_phones("+7 1, +7 2; +7 3") == ["+7 1", "+7 2", "+7 3"]
        assert split_phones("") == []

    def test_dedupe_keeps_first_spelling(self):
        # 88432033880 — тот же номер, что и «+7 (843) 203-38-80».
        got = dedupe_phones(
            "+7 (843) 203-38-80, +7 (927) 674-35-03, 88432033880")
        assert got == "+7 (843) 203-38-80, +7 (927) 674-35-03"

    def test_dedupe_is_idempotent(self):
        once = dedupe_phones(DIRTY["phone"])
        assert dedupe_phones(once) == once


class TestWhatsapp:
    def test_garbage_symbols(self):
        assert (normalize_whatsapp_url("https://wa.me/8+996+125-85-16")
                == "https://wa.me/9961258516")

    def test_russian_leading_8_gets_country_code(self):
        # Регрессия: до фикса код возвращал wa.me/9376154245 (битая ссылка).
        assert (normalize_whatsapp_url("https://wa.me/89376154245")
                == "https://wa.me/79376154245")

    def test_kyrgyz_8996_keeps_996(self):
        assert (normalize_whatsapp_url("https://wa.me/89961258516")
                == "https://wa.me/9961258516")

    def test_extra_plus_sign(self):
        assert (normalize_whatsapp_url("https://wa.me/+79870070016")
                == "https://wa.me/79870070016")

    def test_api_whatsapp_com_becomes_wa_me(self):
        got = normalize_whatsapp_url(
            "https://api.whatsapp.com/send?phone=79001234567")
        assert got == "https://wa.me/79001234567"

    def test_garbage_number_is_dropped(self):
        assert normalize_whatsapp_url("https://wa.me/12345") is None
        assert normalize_whatsapp_url("https://example.com/x") is None
        assert normalize_whatsapp_url("") is None


class TestVk:
    def test_vk_ru_canonicalized(self):
        assert normalize_vk_url("https://vk.ru/club42") == "https://vk.com/club42"

    def test_mobile_domain_canonicalized(self):
        assert (normalize_vk_url("https://m.vk.com/club42")
                == "https://vk.com/club42")

    def test_foreign_url_rejected(self):
        assert normalize_vk_url("https://example.com/x") is None
        assert normalize_vk_url("") is None


class TestEnsureHttps:
    def test_upgrades_http(self):
        assert ensure_https("http://taplink.cc/x") == "https://taplink.cc/x"

    def test_keeps_https_and_plain(self):
        assert ensure_https("https://a.ru") == "https://a.ru"
        assert ensure_https("") == ""


# ── normalize_record ──────────────────────────────────────────

class TestNormalizeRecord:
    def test_all_target_fields_fixed(self):
        out = normalize_record(DIRTY)
        assert out["phone"] == CLEAN_PHONE
        assert out["whatsapp"] == CLEAN_WA
        assert out["vk"] == CLEAN_VK
        assert out["website"] == "https://taplink.cc/cafe"

    def test_untouched_fields_are_preserved(self):
        out = normalize_record(DIRTY)
        for key in ("name", "city", "query", "address"):
            assert out[key] == DIRTY[key]

    def test_idempotent(self):
        once = normalize_record(DIRTY)
        assert normalize_record(once) == once

    def test_broken_wa_is_dropped_but_non_wa_vk_is_kept(self):
        out = normalize_record({"whatsapp": "https://wa.me/12345",
                                "vk": "club42"})
        assert out["whatsapp"] == ""
        assert out["vk"] == "club42"     # легаси-значение не трогаем

    def test_empty_and_missing_fields(self):
        assert normalize_record({}) == {}
        out = normalize_record({"phone": "", "vk": "", "whatsapp": ""})
        assert out == {"phone": "", "vk": "", "whatsapp": ""}

    def test_does_not_mutate_input(self):
        src = dict(DIRTY)
        normalize_record(src)
        assert src == DIRTY

    # Отдельного столбца website в отчёте нет (CSV_FIELDS): обычный сайт
    # организации уезжает в единую колонку «Сайт / Таплинк» — ключ
    # aggregator_url. Сам website остаётся в записи: по нему этап 2 ищет
    # контакты и считает «без сайта».
    def test_website_fills_the_single_site_column(self):
        out = normalize_record({"website": "http://taplink.cc/cafe"})
        assert out["aggregator_url"] == "https://taplink.cc/cafe"
        assert out["website"] == "https://taplink.cc/cafe"

    def test_existing_aggregator_url_wins_over_the_website(self):
        out = normalize_record({"website": "http://firma.ru",
                                "aggregator_url": "https://taplink.cc/x"})
        assert out["aggregator_url"] == "https://taplink.cc/x"
        assert out["website"] == "https://firma.ru"

    def test_blank_website_creates_no_site_column(self):
        out = normalize_record({"website": ""})
        assert "aggregator_url" not in out
        assert normalize_record({}).get("aggregator_url") is None


# ── Интеграция: писатели файлов ───────────────────────────────

def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


class TestSaveCsvNormalizes:
    def test_csv_row_is_canonical(self, tmp_path):
        path = tmp_path / "out.csv"
        save_csv([DIRTY], str(path), append=False)
        rows = _read_csv(path)
        assert len(rows) == 1
        assert rows[0]["phone"] == CLEAN_PHONE
        assert rows[0]["vk"] == CLEAN_VK
        assert rows[0]["whatsapp"] == CLEAN_WA

    def test_append_normalizes_new_rows(self, tmp_path):
        path = tmp_path / "out.csv"
        save_csv([DIRTY], str(path), append=False)
        save_csv([dict(DIRTY, name="Второе")], str(path), append=True)
        rows = _read_csv(path)
        assert len(rows) == 2
        assert all(r["vk"] == CLEAN_VK for r in rows)


class TestSaveJsonNormalizes:
    def test_json_is_canonical(self, tmp_path):
        path = tmp_path / "out.json"
        save_json([DIRTY], str(path), append=False)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["phone"] == CLEAN_PHONE
        assert data[0]["whatsapp"] == CLEAN_WA

    def test_append_normalizes_both_batches(self, tmp_path):
        path = tmp_path / "out.json"
        save_json([DIRTY], str(path), append=False)
        save_json([dict(DIRTY, name="Второе")], str(path), append=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert all(r["vk"] == CLEAN_VK for r in data)


class TestSaveExcelNormalizes:
    def test_xlsx_is_canonical(self, tmp_path):
        path = tmp_path / "out.xlsx"
        save_excel([DIRTY], str(path))
        rows = _records_from_xlsx(str(path))
        assert len(rows) == 1
        assert rows[0]["phone"] == CLEAN_PHONE
        assert rows[0]["vk"] == CLEAN_VK
        assert rows[0]["whatsapp"] == CLEAN_WA


class TestAppendExcelNormalizes:
    def test_incremental_row_is_canonical(self, tmp_path):
        """Пятая точка записи: построчная дозапись во время поиска.

        _excel — модульный синглтон, поэтому в finally сбрасываем его
        состояние, чтобы не протекло в другие тесты.
        """
        from yandex_maps_parser import exporters as ex

        path = tmp_path / "inc.xlsx"
        state = ex._excel
        try:
            state.open, state.wb, state._dirty = False, None, 0
            ex._init_excel(str(path))
            ex._append_excel(dict(DIRTY))
            ex._finalize_excel([dict(DIRTY)])     # финальный save на диск
            rows = ex._records_from_xlsx(str(path))
            assert len(rows) == 1
            assert rows[0]["phone"] == CLEAN_PHONE
            assert rows[0]["vk"] == CLEAN_VK
            assert rows[0]["whatsapp"] == CLEAN_WA
        finally:
            state.open, state.wb, state._dirty = False, None, 0


# ── Интеграция: выгрузка выборки /export-filtered ─────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from routes import api as api_mod

    monkeypatch.setattr(api_mod, "REVIEWED_FILE",
                        str(tmp_path / "_reviewed.json"))
    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


class TestExportFilteredNormalizes:
    def _export_csv(self, client, rows):
        resp = client.post("/export-filtered",
                           json={"rows": rows, "format": "csv"})
        assert resp.status_code == 200
        text = resp.data.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def test_selection_csv_is_canonical(self, client):
        rows = self._export_csv(client, [DIRTY])
        assert len(rows) == 1
        assert rows[0]["Телефон"] == CLEAN_PHONE
        assert rows[0]["VK"] == CLEAN_VK
        assert rows[0]["WhatsApp"] == CLEAN_WA

    def test_foreign_fields_survive(self, client):
        rows = self._export_csv(client, [DIRTY])
        assert rows[0]["Название"] == DIRTY["name"]
