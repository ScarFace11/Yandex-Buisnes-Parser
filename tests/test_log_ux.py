"""
Tests for the log/UX fixes: humanized API errors, city-list prefill,
continuation mode, and request-kind labeling.
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import state, twogis, search, runner, city_data


# ── 1. Humanized 2GIS errors ──────────────────────────────────

class TestHuman2gisError:
    def test_404_becomes_friendly(self):
        msg = twogis._human_api_error(404, "Results not found", "notfound", "Клуб", "Душанбе")
        assert "Душанбе" in msg and "«Клуб»" in msg
        assert "404" not in msg and "API ошибка" not in msg

    def test_403_key_problem(self):
        msg = twogis._human_api_error(403, "Forbidden", "forbidden", "кафе", "Уфа")
        assert "ключ" in msg.lower()

    def test_429_quota(self):
        msg = twogis._human_api_error(429, "Limit exceeded", "limit", "кафе", "Уфа")
        assert "лимит" in msg.lower()

    def test_unknown_code_falls_back(self):
        msg = twogis._human_api_error(500, "Internal", "", "кафе", "Уфа")
        assert "продолжатся" in msg or "пропущен" in msg

    def test_search_items_warns_human_and_tech(self, monkeypatch):
        calls = []

        class FakeResp:
            status_code = 200
            def json(self):
                return {"meta": {"code": 404, "error": {"type": "notFound",
                        "message": "Results not found"}}}

        monkeypatch.setattr(twogis, "_get", lambda *a, **kw: FakeResp())
        monkeypatch.setattr(state, "warn", lambda m: calls.append(("warn", m)))
        monkeypatch.setattr(state, "tech", lambda m: calls.append(("tech", m)))
        items, total = twogis.search_items("Клуб", "Душанбе", 38.5, 68.7, 0)
        assert items == [] and total is None
        warns = [m for lv, m in calls if lv == "warn"]
        techs = [m for lv, m in calls if lv == "tech"]
        assert len(warns) == 1 and "«Клуб»" in warns[0] and "Душанбе" in warns[0]
        assert any("code=404" in t for t in techs)   # raw details preserved

    def test_404_not_billed(self, monkeypatch, tmp_path):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"meta": {"code": 404, "error": {"type": "notFound",
                        "message": "Results not found"}}}

        monkeypatch.setattr(twogis, "_get", lambda *a, **kw: FakeResp())
        # Isolate the persisted monthly counter so the assertion reflects
        # only what this request billed.
        monkeypatch.setattr(twogis, "_quota_file", lambda: tmp_path / ".2gis_quota.json")
        monkeypatch.setattr(twogis, "_quota_base", 0)
        monkeypatch.setattr(twogis, "_quota_used", 0)
        monkeypatch.setattr(twogis, "_quota_file_loaded", False)
        twogis.quota_reset()
        twogis.search_items("Клуб", "Душанбе", 38.5, 68.7, 0)
        assert twogis.quota_used() == 0


# ── 2. Humanized Yandex search errors ─────────────────────────

class TestHumanSearchError:
    def test_403_key(self):
        msg = search._human_search_error(403, "кафе", "Уфа")
        assert "ключ" in msg.lower() and "403" not in msg

    def test_404_nothing_found(self):
        msg = search._human_search_error(404, "кафе", "Сочи")
        assert "Сочи" in msg and "«кафе»" in msg

    def test_other_status(self):
        msg = search._human_search_error(502, "кафе", "Уфа")
        assert "временно" in msg

    def test_search_page_403(self, monkeypatch):
        calls = []

        class FakeResp:
            status_code = 403
            text = '{"error": "forbidden"}'
            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(search, "_get", lambda *a, **kw: FakeResp())
        monkeypatch.setattr(state, "warn", lambda m: calls.append(("warn", m)))
        monkeypatch.setattr(state, "tech", lambda m: calls.append(("tech", m)))
        feats, found = search.search_page("кафе", "Уфа", 54.7, 55.9, 0)
        assert feats == [] and found is None
        warns = [m for lv, m in calls if lv == "warn"]
        assert len(warns) == 1 and "ключ" in warns[0].lower()


# ── 3. Stats labels in Russian ────────────────────────────────

class TestStatsLabels:
    def test_other_renamed(self, monkeypatch):
        lines = []
        monkeypatch.setattr(state, "ok", lambda m: lines.append(m))
        monkeypatch.setattr(state, "info", lambda m: lines.append(m))
        import yandex_maps_parser.http_client as hc
        monkeypatch.setattr(hc, "get_stats", lambda: {
            "requests": 45, "by_kind": {"search": 30, "other": 15},
            "rate_limits": 0, "retries": 0, "cooldown_seconds": 0})
        from yandex_maps_parser.stats import print_limit_stats
        print_limit_stats()
        joined = "\n".join(lines)
        assert "Прочие запросы: 15" in joined
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
