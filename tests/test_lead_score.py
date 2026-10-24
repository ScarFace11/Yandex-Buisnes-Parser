"""
Unit tests for the Lead Score (offline — no network, no files).

Run with: python -m pytest tests/test_lead_score.py -v
"""
import sys
import os
import re
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import lead_score
from yandex_maps_parser.constants import EXPENSIVE_CATEGORY_KEYWORDS
from yandex_maps_parser.lead_score import (
    annotate_records, compute_score, MAX_SCORE, BASE_MAX,
)


def _rec(**over):
    base = {
        "name": "Кафе",
        "category": "Кафе",
        "phone": "",
        "vk": "",
        "telegram": "",
        "instagram": "",
        "whatsapp": "",
        "website": "",
        "aggregator_url": "",
        "rating": "",
        "reviews_count": "",
        "vk_activity": "",
        "added_at": "",
    }
    base.update(over)
    return base


def _recent() -> str:
    return (date.today() - timedelta(days=30)).isoformat()


class TestComputeScore:
    def test_maximum_is_one_hundred(self):
        # Семь базовых сигналов дают ровно 100 — максимум достижим и без
        # ключа ВК, поэтому «практический потолок 90» больше не нужен.
        assert BASE_MAX == 100
        assert MAX_SCORE == 100

    def test_hot_lead_scores_the_documented_breakdown(self):
        score, reasons = compute_score(_rec(
            phone="+7 900 000-00-00",
            vk="https://vk.com/club1",
            vk_activity="active",
            rating="4.8",
            reviews_count="120",
            category="Стоматология",
            added_at=_recent(),
        ))
        assert score == 100
        assert any("нет сайта" in r for r in reasons)
        assert any("есть соцсети" in r for r in reasons)
        assert any("недавно на Картах" in r for r in reasons)
        assert any("активный ВК" in r for r in reasons)
        assert any("дорогая категория" in r for r in reasons)

    def test_activity_bonus_never_breaks_the_scale(self):
        """База уже 100 — бонус ВК не делает 110."""
        score, _ = compute_score(_rec(
            phone="+7 1", rating="5", reviews_count="100",
            category="Стоматология", telegram="https://t.me/x",
            vk="https://vk.com/x", vk_activity="active", added_at=_recent(),
        ))
        assert score == MAX_SCORE

    def test_own_website_costs_the_thirty_points(self):
        with_site, _ = compute_score(_rec(website="https://kafe.ru"))
        without_site, _ = compute_score(_rec())
        assert without_site - with_site == lead_score.NO_WEBSITE

    def test_aggregator_link_counts_as_no_website(self):
        # taplink is a link page, not a website — same rule as the filters.
        score, reasons = compute_score(_rec(aggregator_url="https://taplink.cc/kafe"))
        assert score == lead_score.NO_WEBSITE
        assert any("нет сайта" in r for r in reasons)

    def test_missing_data_adds_nothing(self):
        score, reasons = compute_score(_rec(website="https://kafe.ru"))
        assert score == 0
        assert reasons == []

    def test_socials_without_website_add_ten(self):
        score, reasons = compute_score(_rec(telegram="https://t.me/kafe"))
        assert score == lead_score.NO_WEBSITE + lead_score.SOCIALS_PRESENT
        assert any("есть соцсети" in r for r in reasons)

    def test_vk_activity_is_not_invented_without_the_api(self):
        """Ссылка на ВК есть, активности нет (ключа не было) — только соцсети,
        и в разборе нет ни «активен», ни «не активен»."""
        score, reasons = compute_score(_rec(
            website="https://kafe.ru", vk="https://vk.com/kafe"))
        assert score == lead_score.SOCIALS_PRESENT
        assert not any("ВК" in r for r in reasons)

    def test_semi_active_vk_is_a_five_point_bonus(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", vk_activity="semi",
                                      vk="https://vk.com/club1"))
        assert score == lead_score.SOCIALS_PRESENT + lead_score.VK_SEMI

    def test_rating_below_threshold_adds_nothing(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="4.4"))
        assert score == 0

    def test_rating_on_a_ten_point_scale_is_normalised(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="47"))
        assert score == lead_score.RATING_GOOD

    def test_new_business_needs_a_recent_date(self):
        recent, _ = compute_score(_rec(website="https://kafe.ru", added_at=_recent()))
        assert recent == lead_score.NEW_BUSINESS
        old, _ = compute_score(_rec(website="https://kafe.ru", added_at="2020-01-01"))
        assert old == 0
        unknown, _ = compute_score(_rec(website="https://kafe.ru"))
        assert unknown == 0

    def test_broken_numbers_do_not_crash(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="н/д",
                                      reviews_count="много"))
        assert score == 0


class TestFrontendMirror:
    """The table tooltip explains a score with its own copy of the rules.

    static/js/04-results-table.js carries a JS mirror of this table; if the two
    drift, the number in the column and the tooltip disagree — so the tables are
    compared here instead of in a comment.
    """

    @staticmethod
    def _app_js() -> str:
        from tests._appjs import read_app_js
        return read_app_js()

    def test_maximum_matches(self):
        js = self._app_js()
        assert f"const SCORE_MAX = {MAX_SCORE};" in js
        assert f"const SCORE_NEW_MONTHS = {lead_score.NEW_BUSINESS_MONTHS};" in js

    def test_every_point_value_is_present_once(self):
        js = self._app_js()
        table = js[js.index("const SCORE_RULES"):js.index("function scoreBreakdown")]
        pts = [int(p) for p in re.findall(r"pts: (\d+)", table)]
        assert sorted(pts) == sorted([
            lead_score.NO_WEBSITE, lead_score.RATING_GOOD, lead_score.REVIEWS_MANY,
            lead_score.HAS_PHONE, lead_score.EXPENSIVE_CATEGORY,
            lead_score.SOCIALS_PRESENT, lead_score.NEW_BUSINESS,
            lead_score.VK_ACTIVE, lead_score.VK_SEMI,
        ])

    def test_thresholds_match(self):
        table = self._app_js()
        table = table[table.index("const SCORE_RULES"):table.index("function scoreBreakdown")]
        assert "scoreRating(r) >= 4.5" in table
        assert "scoreNum(r.reviews_count) >= 50" in table

    def test_expensive_categories_match(self):
        js = self._app_js()
        block = js[js.index("const SCORE_EXPENSIVE"):js.index("function scoreNum")]
        words = re.findall(r"'([^']+)'", block)
        assert words == list(EXPENSIVE_CATEGORY_KEYWORDS)

    def test_aggregator_list_matches(self):
        assert "linktree" in self._app_js()[self._app_js().index("SCORE_AGGREGATORS"):].split("\n")[0]

    def test_vk_is_scored_only_when_checked(self):
        js = self._app_js()
        assert "function scoreVkChecked(r)" in js
        body = js[js.index("function scoreBreakdown"):js.index("function scoreWhyText")]
        assert "if (scoreVkChecked(r))" in body
        assert "ВК не проверялся" in body


class TestAnnotateRecords:
    def test_writes_score_and_reason(self):
        records = [_rec(category="Стоматология"), _rec(website="https://x.ru")]
        annotate_records(records)
        assert records[0]["lead_score"] == lead_score.NO_WEBSITE + lead_score.EXPENSIVE_CATEGORY
        assert "нет сайта" in records[0]["lead_score_why"]
        assert records[1]["lead_score"] == 0

    def test_a_poisoned_record_does_not_stop_the_batch(self):
        class Boom(dict):
            def get(self, *a, **k):
                raise RuntimeError("bad row")

        records = [Boom(), _rec(website="https://x.ru")]
        annotate_records(records)          # must not raise
        assert records[0]["lead_score"] == 0
        assert records[1]["lead_score"] == 0
