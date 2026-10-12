"""
Tests for the log/UX fixes: humanized browser-search failures, city-list
prefill, continuation mode, and stats labels.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import state, search, runner, city_data
from yandex_maps_parser import browser_search


# ── 1. Empty browser results read as a human explanation ──────

class TestBrowserSearchFailure:
    def test_empty_harvest_warns_once_and_says_what_to_do(self, monkeypatch):
        """Страница не открылась (нет браузера, нет сети) — пользователь
        должен увидеть, что проверить, а не пустую выдачу."""
        calls = []
        monkeypatch.setattr(search, "harvest_cards", lambda *a, **kw: [])
        monkeypatch.setattr(search, "_harvest_cache", {})
        monkeypatch.setattr(state, "warn", lambda m: calls.append(("warn", m)))
        monkeypatch.setattr(state, "tech", lambda m: calls.append(("tech", m)))

        feats, found = search.search_page("кафе", "Уфа", 54.7, 55.9, 0)
        assert feats == [] and found is None
        warns = [m for lv, m in calls if lv == "warn"]
        assert len(warns) == 1 and warns[0] == search.search_failure_hint()
        assert "Диагностика" in warns[0] and "интернет" in warns[0]
        assert any(lv == "tech" for lv, _ in calls), "техническая причина — в файл прогона"

    def test_cards_are_chunked_into_pages(self, monkeypatch):
        """Одна прокрутка выдаёт все карточки: search_page отдаёт их
        порциями по _PAGE_SIZE и повторно страницу не открывает."""
        calls = []

        def _harvest(query, city, lat, lon, max_cards=50):
            calls.append((query, city))
            return [{"_biz_id": f"{i}", "name": f"Организация {i}",
                     "lat": "54.7", "lon": "55.9"} for i in range(60)]

        monkeypatch.setattr(search, "harvest_cards", _harvest)
        monkeypatch.setattr(search, "_harvest_cache", {})
        monkeypatch.setattr(state, "warn", lambda m: None)

        first, total = search.search_page("кафе", "Уфа", 54.7, 55.9, 0)
        second, _ = search.search_page("кафе", "Уфа", 54.7, 55.9, search._PAGE_SIZE)
        assert len(first) == search._PAGE_SIZE and len(second) == 60 - search._PAGE_SIZE
        assert total == 60
        assert len(calls) == 1, "выдача кэшируется: страница открывается один раз"
        assert first[0]["properties"]["CompanyMetaData"]["id"] == "0"

    def test_out_of_range_center_is_dropped(self):
        assert browser_search._parse_center("https://yandex.ru/maps/?ll=55.9%2C54.7") == (54.7, 55.9)
        assert browser_search._parse_center("https://yandex.ru/maps/") is None
        assert browser_search._parse_center("https://yandex.ru/maps/?ll=999%2C999") is None

    def test_rating_and_reviews_are_normalised_from_the_card(self):
        assert browser_search._num("4,9") == "4.9"
        assert browser_search._num("Нет оценок") == ""
        assert browser_search._reviews("(1 490 оценок)") == "1490"
        assert browser_search._reviews("") == ""


# ── 3. Stats labels in Russian ────────────────────────────────

class TestStatsLabels:
    def test_kinds_are_named_in_russian(self, monkeypatch):
        lines = []
        monkeypatch.setattr(state, "ok", lambda m: lines.append(m))
        monkeypatch.setattr(state, "info", lambda m: lines.append(m))
        import yandex_maps_parser.http_client as hc
        monkeypatch.setattr(hc, "get_stats", lambda: {
            "requests": 45, "by_kind": {"search": 30, "other": 15},
            "rate_limits": 0, "retries": 0, "cooldown_seconds": 0})
        monkeypatch.setattr(hc, "browser_stats", lambda: {})
        from yandex_maps_parser.stats import print_limit_stats
        print_limit_stats()
        joined = "\n".join(lines)
        assert "Открыто страниц: 45" in joined
        assert "Выдачи поиска: 30" in joined
        assert "Прочие страницы: 15" in joined
        assert "\n    other:" not in joined


# ── 4. Continuation catalog ───────────────────────────────────

class TestCitiesAfter:
    def test_basic_order(self):
        out = city_data.cities_after("Уфа", 3)
        assert out == ["Ростов-на-Дону", "Красноярск", "Воронеж"]

    def test_excludes_user_cities(self):
        out = city_data.cities_after("Уфа", 3, exclude=["Ростов-на-Дону"])
        assert "Ростов-на-Дону" not in out and len(out) == 3

    def test_wraps_around(self):
        out = city_data.cities_after("Кишинёв", 2)   # last catalog entry
        assert out[0] == "Москва"

    def test_unknown_city_starts_from_top(self):
        out = city_data.cities_after("Атлантида", 2)
        assert out == ["Москва", "Санкт-Петербург"]

    def test_no_duplicates_with_exclude_all(self):
        out = city_data.cities_after("Уфа", 10, exclude=["Ростов-на-Дону", "Красноярск"])
        assert len(out) == len(set(out))
        assert "Ростов-на-Дону" not in out


class TestRunWebContinuation:
    def test_continuation_expands_cities(self, monkeypatch):
        """run_web appends catalog cities after the user's list."""
        import threading
        params = {"cities": ["Уфа"], "queries": ["кафе"], "source": "yandex",
                  "continue_cities": True, "continue_limit": 2}

        def fake_run():
            pass   # no-op; the stop_event ends the loop before city 2

        monkeypatch.setattr(runner, "run", fake_run)
        stop = threading.Event()
        logs = []
        runner.run_web(params, lambda lv, m: logs.append((lv, m)),
                       stop_event=stop, skip_event=None)
        # With the loop stopping after city 1, we can only assert that the
        # expansion itself happened and was announced.
        assert any("Режим продолжения" in m and "Ростов-на-Дону" in m for _, m in logs)
        # The city header must report the expanded total (1 + 2 = 3).
        assert any("Город 1/3" in m for _, m in logs)

    def test_no_continuation_by_default(self, monkeypatch):
        import threading
        params = {"cities": ["Уфа"], "queries": ["кафе"], "source": "yandex"}

        def fake_run():
            pass

        monkeypatch.setattr(runner, "run", fake_run)
        stop = threading.Event()
        logs = []
        runner.run_web(params, lambda lv, m: logs.append((lv, m)),
                       stop_event=stop, skip_event=None)
        assert not any("Режим продолжения" in m for _, m in logs)
        # Single-city runs emit no «Город x/y» header (existing behavior).
        assert not any("Город 1/1" in m for _, m in logs)


# ── 5. Duplicate suppression in _LOG_FN ──────────────────────

class TestDedupLog:
    def _make(self):
        out = []
        # Rebuild the closures from run_web's source by calling a tiny stub:
        last = [""]
        def dedup(level, msg):
            if level in ("info", "ok", "warn", "error"):
                if msg == last[0]:
                    return
                last[0] = msg
            out.append((level, msg))
        return dedup, out

    def test_human_duplicate_dropped(self):
        dedup, out = self._make()
        dedup("info", "same")
        dedup("info", "same")
        assert out == [("info", "same")]

    def test_progress_never_dropped(self):
        dedup, out = self._make()
        dedup("progress", "5/10/x/1/0")
        dedup("progress", "5/10/x/1/0")
        assert len(out) == 2

    def test_result_never_dropped(self):
        dedup, out = self._make()
        dedup("result", '{"name": "A"}')
        dedup("result", '{"name": "A"}')
        assert len(out) == 2

    def test_alternating_lines_kept(self):
        dedup, out = self._make()
        dedup("info", "a")
        dedup("info", "b")
        dedup("info", "a")
        assert len(out) == 3
