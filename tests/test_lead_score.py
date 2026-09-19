"""
Unit tests for the Lead Score (offline — no network, no files).

Run with: python -m pytest tests/test_lead_score.py -v
"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import lead_score
from yandex_maps_parser.constants import EXPENSIVE_CATEGORY_KEYWORDS
from yandex_maps_parser.lead_score import annotate_records, compute_score, MAX_SCORE


def _rec(**over):
    base = {
        "name": "Кафе",
        "category": "Кафе",
        "phone": "",
        "vk": "",
        "website": "",
        "aggregator_url": "",
        "rating": "",
        "reviews_count": "",
        "vk_activity": "",
    }
    base.update(over)
    return base


class TestComputeScore:
    def test_maximum_is_ninety(self):
        # «Новый бизнес (< 6 мес)» is not in the table: no source exposes a
        # registration date, so the practical maximum is 90.
        assert MAX_SCORE == 90

    def test_hot_lead_scores_the_documented_breakdown(self):
        score, reasons = compute_score(_rec(
            phone="+7 900 000-00-00",
            vk="https://vk.com/club1",
            vk_activity="active",
            rating="4.8",
            reviews_count="120",
            category="Стоматология",
        ))
        assert score == 90
        assert any("нет сайта" in r for r in reasons)
        assert any("активный ВК" in r for r in reasons)
        assert any("дорогая категория" in r for r in reasons)

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

    def test_semi_active_vk_is_worth_ten(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", vk_activity="semi",
                                      vk="https://vk.com/club1"))
        assert score == lead_score.VK_SEMI

    def test_rating_below_threshold_adds_nothing(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="4.4"))
        assert score == 0

    def test_rating_on_a_ten_point_scale_is_normalised(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="47"))
        assert score == lead_score.RATING_GOOD

    def test_broken_numbers_do_not_crash(self):
        score, _ = compute_score(_rec(website="https://kafe.ru", rating="н/д",
                                      reviews_count="много"))
        assert score == 0


class TestFrontendMirror:
    """The table tooltip explains a score with its own copy of the rules.

    static/js/app.js carries a JS mirror of this table (scoreBreakdown); if
    the two drift, the number in the column and the tooltip disagree — so the
    tables are compared here instead of in a comment.
    """

    @staticmethod
    def _app_js() -> str:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "static", "js", "app.js"), encoding="utf-8") as f:
            return f.read()

    def test_maximum_matches(self):
        assert f"const SCORE_MAX = {MAX_SCORE};" in self._app_js()

    def test_every_bonus_is_present_once(self):
        js = self._app_js()
        table = js[js.index("const SCORE_RULES"):js.index("function scoreBreakdown")]
        pts = [int(p) for p in re.findall(r"pts: (\d+)", table)]
        assert sorted(pts) == sorted([
            lead_score.NO_WEBSITE, lead_score.VK_ACTIVE, lead_score.VK_SEMI,
            lead_score.RATING_GOOD, lead_score.REVIEWS_MANY, lead_score.HAS_PHONE,
            lead_score.EXPENSIVE_CATEGORY,
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
