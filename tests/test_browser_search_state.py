"""
Поиск: выдача берётся из состояния страницы (JSON), вёрстка — запасной путь.

Run with: python -m pytest tests/test_browser_search_state.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import browser_search as bs


class TestStateHarvestJs:
    """Подстановки в шаблон JS: без необработанных плейсхолдеров."""

    def test_substitutes_want_and_pages(self):
        js = bs._state_harvest_js(50)
        assert "const want = 50;" in js
        # 50 организаций = две страницы выдачи по 25.
        assert "const maxPage = 2;" in js
        assert "$WANT$" not in js and "$MAXPAGE$" not in js and "$BUDGET$" not in js

    def test_single_page_for_small_request(self):
        assert "const maxPage = 1;" in bs._state_harvest_js(10)

    def test_page_count_capped(self):
        """Больше 250 организаций с точки не берём."""
        js = bs._state_harvest_js(10_000)
        assert "const want = 250;" in js
        assert "const maxPage = 10;" in js

    def test_reads_state_and_falls_back_silently(self):
        """Пустая строка = «состояния нет» — вызывающий уйдёт на вёрстку."""
        js = bs._state_harvest_js(50)
        assert "return '';" in js
        assert "root.stack[0].results" in js
        assert "st.items" in js
        # Следующие страницы берутся из самой страницы, с её cookie.
        assert "{credentials: 'include'}" in js

    def test_wait_expr_waits_for_state(self):
        expr = bs._state_wait_expr()
        assert "application/json" in expr
        assert str(bs._STATE_MIN_BYTES) in expr


class TestItemsToCards:
    def test_maps_state_item(self):
        cards = bs._items_to_cards([{
            "id": "1616376732",
            "name": "Monkey Grinder",
            "category": "Кофейня, кофе с собой",
            "address": "ул. Ленина, 66, Уфа",
            "coords": "55.958730,54.732742",     # выдаётся как «долгота,широта»
            "rating": "5.0",
            "reviews": "807",
        }])
        assert len(cards) == 1
        card = cards[0]
        assert card["_biz_id"] == "1616376732"
        assert card["name"] == "Monkey Grinder"
        assert card["category"] == "Кофейня, кофе с собой"
        assert card["address"] == "ул. Ленина, 66, Уфа"
        assert card["rating"] == "5.0"
        assert card["reviews_count"] == "807"
        assert (card["lat"], card["lon"]) == ("54.732742", "55.958730")

    def test_normalizes_dom_style_numbers(self):
        """Разбор вёрстки отдаёт «4,9» и «(1 490 оценок)» — чистим так же."""
        card = bs._items_to_cards([{
            "id": "1", "name": "Душа", "rating": "4,9", "reviews": "Рейтинг 4,9",
            "coords": "",
        }])[0]
        assert card["rating"] == "4.9"
        assert card["reviews_count"] == "4"
        assert (card["lat"], card["lon"]) == ("", "")

    def test_skips_items_without_id_or_name(self):
        cards = bs._items_to_cards([
            {"id": "", "name": "Без id"},
            {"id": "2", "name": ""},
            {"id": "3", "name": "Годная"},
        ])
        assert [c["name"] for c in cards] == ["Годная"]

    def test_deduplicates_by_id(self):
        cards = bs._items_to_cards([
            {"id": "5", "name": "Первая"},
            {"id": "5", "name": "Первая (копия)"},
        ])
        assert len(cards) == 1


class TestHarvestPaths:
    """harvest_cards: сначала состояние, при пустоте — вёрстка."""

    def _capture(self, monkeypatch, state_cards, dom_cards):
        """Подменяем оба пути и логируем, какой из них вызвали."""
        calls = []

        def state_path(url, want):
            calls.append("state")
            return state_cards

        def dom_path(url, want):
            calls.append("dom")
            return dom_cards

        monkeypatch.setattr(bs, "_harvest_from_state", state_path)
        monkeypatch.setattr(bs, "_harvest_from_dom", dom_path)
        monkeypatch.setattr(bs.state, "syslog", lambda *_a, **_k: None)
        return calls

    def test_state_result_wins(self, monkeypatch):
        calls = self._capture(monkeypatch, [{"_biz_id": "1", "name": "A"}],
                              [{"_biz_id": "2", "name": "B"}])
        assert [c["name"] for c in bs.harvest_cards("кофейня", "Уфа", 1.0, 2.0)] == ["A"]
        assert calls == ["state"]

    def test_falls_back_to_dom(self, monkeypatch):
        calls = self._capture(monkeypatch, [], [{"_biz_id": "2", "name": "B"}])
        assert [c["name"] for c in bs.harvest_cards("кофейня", "Уфа", 1.0, 2.0)] == ["B"]
        assert calls == ["state", "dom"]

    def test_both_empty_gives_empty_list(self, monkeypatch):
        self._capture(monkeypatch, [], [])
        assert bs.harvest_cards("кофейня", "Уфа", 1.0, 2.0) == []

    def test_state_path_parses_payload(self, monkeypatch):
        """Строка состояния разбирается в карточки (JSON как отдаёт страница)."""
        payload = json.dumps({"total": 71, "cards": [{
            "id": "42", "name": "Кофейня", "coords": "55.9,54.7",
            "rating": "4.5", "reviews": "12",
        }]}, ensure_ascii=False)
        monkeypatch.setattr(bs.cdp_client, "eval_in_page",
                            lambda *a, **kw: payload)
        monkeypatch.setattr(bs.state, "syslog", lambda *_a, **_k: None)
        cards = bs._harvest_from_state("https://example.invalid", 50)
        assert cards and cards[0]["_biz_id"] == "42"

    def test_state_path_tolerates_broken_json(self, monkeypatch):
        monkeypatch.setattr(bs.cdp_client, "eval_in_page", lambda *a, **kw: "<html>")
        monkeypatch.setattr(bs.state, "syslog", lambda *_a, **_k: None)
        assert bs._harvest_from_state("https://example.invalid", 50) == []
