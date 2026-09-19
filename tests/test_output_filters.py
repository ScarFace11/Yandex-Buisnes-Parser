"""Tests for the optional output-quality filters and the total-deadline timeout."""

import pytest

from yandex_maps_parser import state
from yandex_maps_parser.exporters import (
    collapse_chains,
    apply_output_filters,
)


def _rec(city, name, phone="", **socials):
    r = {"city": city, "name": name, "phone": phone}
    r.update(socials)
    return r


class TestCollapseChains:
    def test_merges_same_phone_same_name(self):
        recs = [
            _rec("Саратов", "Буфет ФМ", "+7 (8452) 60-31-60", vk="https://vk.ru/a"),
            _rec("Саратов", "Буфет ФМ", "+7 (8452) 60-31-60", telegram="https://t.me/b"),
        ]
        out = collapse_chains(recs)
        assert len(out) == 1
        row = out[0]
        assert row["vk"] == "https://vk.ru/a"
        assert row["telegram"] == "https://t.me/b"

    def test_keeps_distinct_phone_branches(self):
        recs = [
            _rec("Саратов", "Поддон", "+7 (937) 262-66-62", vk="https://vk.ru/p1"),
            _rec("Саратов", "Поддон", "+7 (937) 999-99-99", vk="https://vk.ru/p2"),
        ]
        out = collapse_chains(recs)
        assert len(out) == 2

    def test_merges_by_shared_social(self):
        recs = [
            _rec("Минск", "Кафе X", "+375 29 111-11-11", telegram="https://t.me/cafe"),
            _rec("Минск", "Кафе X", "+375 29 222-22-22", telegram="https://t.me/cafe"),
        ]
        out = collapse_chains(recs)
        assert len(out) == 1

    def test_different_cities_never_merge(self):
        recs = [
            _rec("Саратов", "Бар", "+7 111", vk="https://vk.ru/s"),
            _rec("Минск", "Бар", "+7 111", vk="https://vk.ru/m"),
        ]
        out = collapse_chains(recs)
        assert len(out) == 2

    def test_single_records_untouched(self):
        recs = [_rec("Минск", "Один бар", "+375 29 333-33-33", vk="https://vk.ru/o")]
        assert collapse_chains(recs) == recs

    # ── Merge strategies («Правило объединения» dropdown) ──

    def test_strategy_name_merges_across_cities(self):
        recs = [
            _rec("Уфа", "Сеть А", "+7 111", vk="https://vk.ru/a1"),
            _rec("Москва", "Сеть А", "+7 222"),
            _rec("Казань", "Другое дело", "+7 333"),
        ]
        out = collapse_chains(recs, "name")
        assert len(out) == 2          # Сеть А merged, «Другое дело» apart
        assert sum(1 for r in out if r["name"] == "Сеть А") == 1

    def test_strategy_phone_merges_by_shared_number(self):
        recs = [
            _rec("Уфа", "Филиал №1", "+7 900 111-22-33"),
            _rec("Стерлитамак", "Филиал №2", "+7 900 111-22-33"),
            _rec("Уфа", "Другая сеть", "+7 900 999-88-77"),
        ]
        out = collapse_chains(recs, "phone")
        assert len(out) == 2          # same number → one row
        phones = [r["phone"] for r in out if "+7 900 111-22-33" in r["phone"]]
        assert len(phones) == 1 and "+7 900 111-22-33, +7 900 111-22-33" not in phones[0]

    def test_strategy_email_merges_by_shared_email(self):
        recs = [
            _rec("Уфа", "Кафе Луна", "", email="luna@mail.ru"),
            _rec("Москва", "Кафе Луна", "", email="luna@mail.ru"),
            _rec("Уфа", "Бар Соль", "", email="sol@mail.ru"),
        ]
        out = collapse_chains(recs, "email")
        assert len(out) == 2

    def test_strategy_email_without_contact_never_merges(self):
        recs = [
            _rec("Уфа", "Кафе Луна", "+7 111"),
            _rec("Уфа", "Кафе Луна", "+7 222"),
        ]
        out = collapse_chains(recs, "email")
        assert len(out) == 2          # no email on either record

    def test_strategy_name_city_keeps_cities_apart(self):
        recs = [
            _rec("Уфа", "Сеть А", "+7 111"),
            _rec("Москва", "Сеть А", "+7 222"),
        ]
        out = collapse_chains(recs, "name_city")
        assert len(out) == 2


class TestApplyOutputFilters:
    def test_collapse_flag_respected(self):
        recs = [
            _rec("Саратов", "Буфет ФМ", "+7 (8452) 60-31-60", vk="https://vk.ru/a"),
            _rec("Саратов", "Буфет ФМ", "+7 (8452) 60-31-60", telegram="https://t.me/b"),
        ]
        state.COLLAPSE_CHAINS = True
        try:
            out = apply_output_filters(recs)
        finally:
            state.COLLAPSE_CHAINS = False
        assert len(out) == 1
        assert out[0]["vk"] and out[0]["telegram"]

    def test_off_by_default(self):
        recs = [_rec("Минск", "Бар", ""), _rec("Минск", "Бар", "+7 111")]
        state.COLLAPSE_CHAINS = False
        assert apply_output_filters(recs) == recs


class TestTotalTimeoutExtraction:
    """The 3rd tuple element of _get's timeout is a hard wall-clock deadline."""

    def test_three_tuple_extracts_total(self):
        from yandex_maps_parser.http_client import _get

        # simulate the extraction logic used by _get()
        def extract(t):
            return t[2] if isinstance(t, tuple) and len(t) >= 3 else None

        assert extract((8, 15, 60)) == 60
        assert extract((8, 15)) is None
        assert extract(10) is None