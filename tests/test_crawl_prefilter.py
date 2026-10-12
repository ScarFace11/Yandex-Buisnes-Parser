"""Предфильтр сбора (processing.crawl_skip_reason).

Главное утверждение: сбор отбрасывает ровно те записи, которые снял бы
этап 2 по тем же фильтрам. Иначе живая таблица показывала бы записи,
которых нет в результате, а «Применить фильтры заново» — другие числа.

Паритет проверяется на одном и том же наборе записей: набор имён,
оставшихся после `crawl_skip_reason`, сравнивается с тем, что вернул
`processing.apply_filters` из raw-файла.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import processing
from yandex_maps_parser.exporters import save_excel


# ── Набор записей: по одной на каждое правило ─────────────────

RECORDS = [
    {"name": "Кофейня Франшиза", "category": "Кофейня", "city": "Уфа", "query": "кафе"},
    {"name": "Салон VIP", "category": "Салон красоты", "city": "Уфа", "query": "кафе"},
    {"name": "Только ВК", "city": "Уфа", "query": "кафе", "vk": "https://vk.com/a"},
    {"name": "ВК и ТГ", "city": "Уфа", "query": "кафе",
     "vk": "https://vk.com/b", "telegram": "https://t.me/b"},
    {"name": "Без соцсетей", "city": "Уфа", "query": "кафе"},
    {"name": "С сайтом", "city": "Уфа", "query": "кафе", "website": "https://cafe.ru"},
    {"name": "Таплинк", "city": "Уфа", "query": "кафе", "website": "https://taplink.cc/x"},
    {"name": "Витрина vk.cc", "city": "Уфа", "query": "кафе",
     "aggregator_url": "https://vk.cc/abc"},
    {"name": "Витрина bio.link", "city": "Уфа", "query": "кафе",
     "aggregator_url": "https://bio.link/coffee"},
]

# Фильтры этапа 2, которые решает уже сбор. Остальные (объединение
# филиалов, «тип компании», оценка лида, ВК) требуют всего набора записей
# и в паритете не участвуют.
COMBOS = [
    {"parse_mode": "all", "social_mode": "all"},
    {"parse_mode": "without_website", "social_mode": "all"},
    {"parse_mode": "all", "social_mode": "with_socials"},
    {"parse_mode": "all", "social_mode": "without_socials"},
    {"parse_mode": "without_website", "social_mode": "with_socials"},
    {"parse_mode": "all", "social_mode": "all", "required_socials": ["vk"]},
    {"parse_mode": "all", "social_mode": "with_socials",
     "required_socials": ["vk", "telegram"]},
    {"parse_mode": "without_website", "social_mode": "with_socials",
     "blacklist_words": ["франшиза", "vip"]},
    {"parse_mode": "all", "social_mode": "all", "blacklist_words": ["франшиза"]},
]


def _crawl_kept(records, filters):
    """Имена записей, которые сбор оставит (не отбросит предфильтром)."""
    return {
        rec["name"] for rec in records
        if not processing.crawl_skip_reason(
            rec,
            words=filters.get("blacklist_words") or [],
            parse_mode=filters.get("parse_mode", "all"),
            social_mode=filters.get("social_mode", "all"),
            required_socials=filters.get("required_socials") or (),
        )
    }


def _stage2_kept(tmp_path, records, filters):
    """Имена записей, которые остались после apply_filters (этап 2)."""
    raw = tmp_path / "raw_prefilter.xlsx"
    save_excel([dict(r) for r in records], str(raw),
               extra_fields=("website", "branch_count", "added_at"))
    res = processing.apply_filters([str(raw)], dict(filters))
    kept = set()
    for cities in res["groups"].values():
        for recs in cities.values():
            kept.update(r["name"] for r in recs)
    return kept


@pytest.mark.parametrize("filters", COMBOS, ids=lambda f: "_".join(f"{k}={v}" for k, v in f.items()))
def test_crawl_and_stage2_agree(tmp_path, filters):
    """Что сбор выкинул, того и этап 2 не оставил бы (и наоборот)."""
    assert _crawl_kept(RECORDS, filters) == _stage2_kept(tmp_path, RECORDS, filters)


@pytest.mark.parametrize("filters", COMBOS, ids=lambda f: "_".join(f"{k}={v}" for k, v in f.items()))
def test_prefilter_never_keeps_more_than_stage2(tmp_path, filters):
    """Сбор не может оставить запись, которую этап 2 снял бы: иначе запись
    появилась бы в живой таблице и исчезла после сборки — это и был баг."""
    extra = _crawl_kept(RECORDS, filters) - _stage2_kept(tmp_path, RECORDS, filters)
    assert extra == set()


# ── Отдельные правила ─────────────────────────────────────────

class TestSkipReason:
    def test_empty_record_passes(self):
        assert processing.crawl_skip_reason({}) == ""

    def test_blacklist_wins_over_other_reasons(self):
        """Слово из чёрного списка побеждает: запись не должна тянуть
        загрузку карточки ради проверки соцсетей."""
        rec = {"name": "Кофейня Франшиза", "vk": "https://vk.com/a"}
        assert processing.crawl_skip_reason(
            rec, words=["франшиза"], social_mode="all") == "blacklist"

    def test_blacklist_is_case_and_substring_based(self):
        assert processing.crawl_skip_reason(
            {"category": "САЛОН VIP"}, words=["vip"]) == "blacklist"
        assert processing.crawl_skip_reason(
            {"name": "Кофейня Ромашка"}, words=["vip"]) == ""

    def test_blacklist_words_are_normalized(self):
        """Слова приезжают из формы как есть — регистр не важен."""
        assert processing.crawl_skip_reason(
            {"name": "Кофейня Франшиза"}, words=["  ФРАНШИЗА "]) == "blacklist"

    def test_website_reason(self):
        assert processing.crawl_skip_reason(
            {"website": "https://cafe.ru"}, parse_mode="without_website") == "website"
        assert processing.crawl_skip_reason(
            {"website": "https://cafe.ru"}, parse_mode="all") == ""

    @pytest.mark.parametrize("site", ["https://taplink.cc/x", "https://linktr.ee/x",
                                      "https://vk.cc/abc", "https://bio.link/x",
                                      "https://beacons.ai/x"])
    def test_link_aggregators_are_not_websites(self, site):
        """Витрина ссылок — не сайт: и сбор, и этап 2 держат такую запись."""
        assert processing.crawl_skip_reason(
            {"website": site}, parse_mode="without_website") == ""
        assert processing.crawl_skip_reason(
            {"aggregator_url": site}, parse_mode="without_website") == ""

    def test_social_reasons(self):
        bare = {"name": "Без соцсетей"}
        with_vk = {"name": "С ВК", "vk": "https://vk.com/a"}
        assert processing.crawl_skip_reason(bare, social_mode="with_socials") == "no_socials"
        assert processing.crawl_skip_reason(with_vk, social_mode="with_socials") == ""
        assert processing.crawl_skip_reason(with_vk, social_mode="without_socials") == "has_socials"
        assert processing.crawl_skip_reason(bare, social_mode="without_socials") == ""

    def test_required_socials_are_an_and_filter(self):
        rec = {"name": "Только ВК", "vk": "https://vk.com/a"}
        assert processing.crawl_skip_reason(
            rec, required_socials=["vk"]) == ""
        assert processing.crawl_skip_reason(
            rec, required_socials=["vk", "telegram"]) == "missing_socials"

    def test_required_socials_ignored_in_without_socials_mode(self):
        """«Без соцсетей» и плитки вместе несовместимы: запись с сетями
        снимается как «с соцсетями», а не как «нет нужных сетей»."""
        rec = {"name": "С ВК", "vk": "https://vk.com/a"}
        assert processing.crawl_skip_reason(
            rec, social_mode="without_socials", required_socials=["vk"]) == "has_socials"

    def test_prefilter_applies_to_an_empty_required_list(self):
        assert processing.crawl_skip_reason(
            {"name": "Без соцсетей"}, social_mode="with_socials",
            required_socials=[]) == "no_socials"


# ── Фильтры, решаемые по одной записи ─────────────────────────
# Раньше они жили только на этапе 2, поэтому запись показывалась в живой
# таблице и исчезала после «Применения фильтров». Теперь сбор снимает её сам.

class TestRecordLevelFilters:
    COLD = {"name": "Холодный", "website": "https://cold.ru"}          # 0 баллов
    HOT = {"name": "Горячий", "category": "стоматология", "phone": "+7 999"}  # 40

    def test_min_score_drops_a_cold_lead(self):
        assert processing.crawl_skip_reason(
            self.COLD, min_lead_score=40) == "score"
        assert processing.crawl_skip_reason(
            self.HOT, min_lead_score=40) == ""

    def test_score_filter_fills_lead_score_on_keep(self):
        rec = dict(self.HOT)
        assert processing.crawl_skip_reason(rec, min_lead_score=40) == ""
        assert rec["lead_score"] == 40, "оценка заполнена сразу для живой таблицы"

    def test_min_score_is_skipped_when_vk_check_adds_points(self):
        """Этап 2 с проверкой ВК добавит баллы — сбор не должен снимать."""
        assert processing.crawl_skip_reason(
            self.COLD, min_lead_score=40, vk_check=True) == ""

    def test_only_new_drops_old_cards_and_keeps_undated(self):
        old = {"name": "Старая", "added_at": "2020-01-01"}
        assert processing.crawl_skip_reason(
            old, only_new_months=6) == "new"
        assert processing.crawl_skip_reason(
            {"name": "Без даты"}, only_new_months=6) == ""

    def test_only_single_drops_branches_reported_by_the_source(self):
        assert processing.crawl_skip_reason(
            {"name": "Сеть", "branch_count": 3}, only_single_branch=True) == "single"
        # Нет данных — не снимаем: этап 2 может досчитать филиалы по набору.
        assert processing.crawl_skip_reason(
            {"name": "Одиночка", "branch_count": 1}, only_single_branch=True) == ""
        assert processing.crawl_skip_reason(
            {"name": "Без данных"}, only_single_branch=True) == ""
