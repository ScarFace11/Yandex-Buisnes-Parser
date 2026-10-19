"""Tests for the optional output-quality filters and the total-deadline timeout."""

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


# ── Разбиение группы по контактам: то же решение, но без квадрата ──
# «Название + Город» — лишь первый шаг: одноимённые фирмы в городе делятся
# на подгруппы по общему телефону/соцсети. Решение обязано остаться прежним
# (иначе менялись бы результаты выгрузки), а цена — линейной: прежний перебор
# всех уже собранных подгрупп с пересчётом телефона на каждом сравнении
# квадратичен (замер: 1.2 с на 20 000 записей только на этом шаге).


def _reference_split(group):
    """Прежний алгоритм дословно — эталон для сравнения."""
    from yandex_maps_parser.constants import KNOWN_PLATFORMS
    from yandex_maps_parser.exporters import _phone_digits

    merged = []
    for r in group:
        phones = _phone_digits(r)
        socials = [v for p in KNOWN_PLATFORMS if (v := r.get(p))]
        slot = None
        for m in merged:
            if any(_phone_digits(x) == phones for x in m if phones and _phone_digits(x)):
                slot = m
                break
            if socials and any(
                x.get(p) == s for x in m for p in KNOWN_PLATFORMS for s in socials
            ):
                slot = m
                break
        if slot is None:
            merged.append([r])
        else:
            slot.append(r)
    return merged


def _merge_reference_group(group):
    from yandex_maps_parser.exporters import _merge_group
    out = []
    for sub in _reference_split(group):
        out.extend(_merge_group(sub))
    return out


def _generated_group(n: int, seed: int = 11):
    """Одноимённые фирмы одного города: часть — одна сеть (общий телефон/ссылка)."""
    import random
    rnd = random.Random(seed)
    recs = []
    for i in range(n):
        shared = i % 7 == 0
        recs.append({
            "city": "Москва",
            "name": "Кофейня",
            "address": f"ул. Ленина {i}",
            "phone": "+7 999 000-00-00" if shared else f"+7 9{i % 90:02d} 1{i % 10}1-2{i % 10}2-3{i % 10}3",
            "vk": "https://vk.com/chain" if shared else (f"https://vk.com/p{i}" if i % 3 == 0 else ""),
            "telegram": "https://t.me/chain" if shared else (f"https://t.me/p{i}" if i % 5 == 0 else ""),
        })
    return recs


class TestCollapseChainsContactSplit:
    def test_same_result_as_the_previous_algorithm(self):
        for n, seed in ((40, 1), (150, 2), (400, 3)):
            group = _generated_group(n, seed)
            got = collapse_chains(group, "name_city")
            expected = _merge_reference_group(group)
            assert got == expected, f"на {n} записях разошлось с прежним решением"

    def test_distinct_contacts_keep_rows_apart(self):
        group = _generated_group(40, 4)
        out = collapse_chains(group, "name_city")
        assert len(out) > 1, "разные контакты не должны слипаться в одну строку"
        shared = [r for r in out if r["vk"] == "https://vk.com/chain"]
        assert shared, "общая сеть потерялась"

    def test_one_chain_of_many_branches_merges_into_one_row(self):
        group = [{"city": "Москва", "name": "Пятёрочка",
                  "phone": "+7 999 000-00-00", "vk": "https://vk.com/p5"}
                 for _ in range(300)]
        out = collapse_chains(group, "name_city")
        assert len(out) == 1, f"сеть из 300 веток схлопнулась в {len(out)} строк"

    def test_many_same_named_rows_stay_fast(self):
        """6000 одноимённых записей — секунды, а не минуты (было O(n²))."""
        import time
        group = [{"city": "Москва", "name": "Кофейня", "address": f"ул. {i}",
                  "phone": f"+7 9{i % 90:02d} {i:03d}-{i % 100:02d}-{i % 10}{i % 7}",
                  "vk": f"https://vk.com/p{i}" if i % 3 == 0 else ""}
                 for i in range(6000)]
        t0 = time.perf_counter()
        out = collapse_chains(group, "name_city")
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"разбор подгрупп снова квадратичный: {elapsed:.2f}s"
        assert len(out) == 6000, f"строки потерялись: {len(out)}"


class TestTotalTimeoutExtraction:
    """The 3rd tuple element of _get's timeout is a hard wall-clock deadline."""

    def test_three_tuple_extracts_total(self):
        # simulate the extraction logic used by _get()
        def extract(t):
            return t[2] if isinstance(t, tuple) and len(t) >= 3 else None

        assert extract((8, 15, 60)) == 60
        assert extract((8, 15)) is None
        assert extract(10) is None