"""Tests for the two-stage pipeline (Raw → Processed).

Covers: raw naming/paths, filter ordering (merge BEFORE filters), the
«Название + Город» chain key, save_processed layout, cleanup_raw modes,
run_web raw-mode filter neutralization and the interrupted-run rule.
"""
import os

from yandex_maps_parser import processing, runner, state


# ── Naming ────────────────────────────────────────────────────

class TestNaming:
    def test_raw_filename_format(self):
        import re
        name = processing.raw_filename("Клубы", "Уфа")
        assert re.match(r"raw_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_клубы_уфа\.xlsx$", name)

    def test_raw_path_in_raw_dir(self):
        p = processing.raw_path("кафе", "Сочи")
        assert os.path.dirname(p).replace("\\", "/").endswith("output/raw")

    def test_processed_filename(self):
        assert processing.processed_filename("excel", "Клубы", "Уфа") == "клубы_уфа_filtered.xlsx"
        assert processing.processed_filename("json", "Кафе", "Уфа") == "кафе_уфа_filtered.json"
        assert processing.processed_filename("csv", "Кафе", "Уфа") == "кафе_уфа_filtered.csv"
        assert processing.processed_filename("html", "Кафе", "Уфа") == "кафе_уфа_filtered_map.html"


# ── apply_filters ─────────────────────────────────────────────

class TestApplyFilters:
    def test_merge_first_then_filters(self, tmp_path):
        """Edge case 1: merge chains first, filter after — merged contacts
        survive even when the base record would be filtered out."""
        raw = tmp_path / "raw.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([
            {"city": "Уфа", "name": "Кофейня А", "query": "кафе", "phone": "+7 111"},
            {"city": "Уфа", "name": "Кофейня А", "query": "кафе", "phone": "+7 111",
             "vk": "https://vk.ru/a"},
        ], str(raw))
        res = processing.apply_filters(
            [str(raw)],
            {"collapse_chains": True, "parse_mode": "without_website"},
        )
        assert res["count"] == 1          # merged, vk contact survived the merge
        rec = next(iter(res["groups"]["кафе"]["Уфа"]))
        assert rec["vk"] == "https://vk.ru/a"

    def test_name_city_key_merges_same_named(self, tmp_path):
        """Acceptance criterion: merge by «Название + Город» — two same-named
        businesses in one city merge even with different contacts."""
        raw = tmp_path / "raw.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([
            {"city": "Уфа", "name": "Сеть Б", "query": "кафе", "phone": "+7 111"},
            {"city": "Уфа", "name": "Сеть Б", "query": "кафе", "phone": "+7 222",
             "telegram": "https://t.me/b"},
            {"city": "Казань", "name": "Сеть Б", "query": "кафе", "phone": "+7 333"},
        ], str(raw))
        res = processing.apply_filters([str(raw)], {"collapse_chains": True})
        ufa = res["groups"]["кафе"]["Уфа"]
        kazan = res["groups"]["кафе"]["Казань"]
        assert len(ufa) == 1
        assert "+7 111" in ufa[0]["phone"] and "+7 222" in ufa[0]["phone"]
        assert ufa[0]["telegram"] == "https://t.me/b"
        assert len(kazan) == 1            # different city never merges

    def test_without_website_filter(self, tmp_path):
        raw = tmp_path / "raw.xlsx"
        from yandex_maps_parser.exporters import save_excel
        # Raw files always carry the website column (mirrors
        # processing.export_raw_records → save_excel(extra_fields=...)),
        # even though it is no longer a report column.
        save_excel([
            {"city": "Уфа", "name": "С сайтом", "query": "кафе", "website": "https://cafe.ru"},
            {"city": "Уфа", "name": "Без сайта", "query": "кафе"},
            {"city": "Уфа", "name": "Таплинк", "query": "кафе",
             "website": "https://taplink.cc/x"},   # aggregator ≠ website
        ], str(raw), extra_fields=("website",))
        res = processing.apply_filters([str(raw)], {"parse_mode": "without_website"})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Без сайта", "Таплинк"}

    # ── Socials: a STAGE-2 filter (the crawl keeps every record) ──

    @staticmethod
    def _raw_with_socials(tmp_path):
        raw = tmp_path / "raw_socials.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([
            {"city": "Уфа", "name": "Только ВК", "query": "кафе",
             "vk": "https://vk.com/a"},
            {"city": "Уфа", "name": "ВК и ТГ", "query": "кафе",
             "vk": "https://vk.com/b", "telegram": "https://t.me/b"},
            {"city": "Уфа", "name": "Без соцсетей", "query": "кафе"},
        ], str(raw))
        return str(raw)

    def test_with_socials_drops_records_without_any_social(self, tmp_path):
        res = processing.apply_filters(
            [self._raw_with_socials(tmp_path)], {"social_mode": "with_socials"})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Только ВК", "ВК и ТГ"}

    def test_without_socials_keeps_only_bare_records(self, tmp_path):
        res = processing.apply_filters(
            [self._raw_with_socials(tmp_path)], {"social_mode": "without_socials"})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Без соцсетей"}

    def test_required_socials_is_an_and_filter(self, tmp_path):
        """Two checked tiles → the business must have BOTH networks."""
        res = processing.apply_filters(
            [self._raw_with_socials(tmp_path)],
            {"social_mode": "all", "required_socials": ["vk", "telegram"]})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"ВК и ТГ"}

    def test_required_socials_work_in_every_mode(self, tmp_path):
        """Regression: the tiles used to be honored only in «С соцсетями»,
        so a selection silently did nothing while «Все» stayed active."""
        raw = self._raw_with_socials(tmp_path)
        for mode in ("all", "with_socials"):
            res = processing.apply_filters(
                [raw], {"social_mode": mode, "required_socials": ["telegram"]})
            names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
            assert names == {"ВК и ТГ"}, f"tiles ignored in mode {mode}"

    def test_required_socials_ignored_for_without_socials(self, tmp_path):
        """Contradictory combination must not wipe the result set."""
        res = processing.apply_filters(
            [self._raw_with_socials(tmp_path)],
            {"social_mode": "without_socials", "required_socials": ["vk"]})
        names = {r["name"] for r in res["groups"]["кафе"]["Уфа"]}
        assert names == {"Без соцсетей"}

    def test_no_social_filters_keeps_everything(self, tmp_path):
        res = processing.apply_filters([self._raw_with_socials(tmp_path)], {})
        assert res["count"] == 3

    # ── Lead score + VK activity (stage-2 prioritisation) ──

    @staticmethod
    def _raw_for_scoring(tmp_path):
        raw = tmp_path / "raw_score.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([
            # hot: no site, active VK, good rating, many reviews, phone
            {"city": "Уфа", "name": "Горячий", "query": "кафе", "phone": "+7 111",
             "vk": "https://vk.com/hot", "rating": 4.8, "reviews_count": 120},
            # luke-warm: has a site, no VK data
            {"city": "Уфа", "name": "Тёплый", "query": "кафе", "website": "https://t.ru",
             "phone": "+7 222", "rating": 3.0},
        ], str(raw), extra_fields=("website",))
        return str(raw)

    def test_lead_score_is_computed_before_the_filters(self, tmp_path):
        res = processing.apply_filters([self._raw_for_scoring(tmp_path)], {})
        by_name = {r["name"]: r for r in res["groups"]["кафе"]["Уфа"]}
        # 30 (нет сайта) + 15 (рейтинг 4.8) + 15 (120 отзывов) + 5 (телефон).
        # The VK bonus is absent because activity was never checked.
        assert by_name["Горячий"]["lead_score"] == 65
        assert by_name["Тёплый"]["lead_score"] == 5     # phone only

    def test_min_lead_score_drops_cold_leads(self, tmp_path):
        res = processing.apply_filters(
            [self._raw_for_scoring(tmp_path)], {"min_lead_score": 40})
        assert {r["name"] for r in res["groups"]["кафе"]["Уфа"]} == {"Горячий"}

    def test_min_lead_score_of_zero_keeps_everything(self, tmp_path):
        res = processing.apply_filters(
            [self._raw_for_scoring(tmp_path)], {"min_lead_score": 0})
        assert res["count"] == 2

    def test_sort_by_score_puts_the_hot_lead_first(self, tmp_path):
        res = processing.apply_filters(
            [self._raw_for_scoring(tmp_path)], {"sort_by_score": True})
        names = [r["name"] for r in res["groups"]["кафе"]["Уфа"]]
        assert names == ["Горячий", "Тёплый"]

    @staticmethod
    def _raw_with_vk(tmp_path):
        raw = tmp_path / "raw_vk.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([
            {"city": "Уфа", "name": "Живой", "query": "кафе", "vk": "https://vk.com/alive"},
            {"city": "Уфа", "name": "Полуживой", "query": "кафе", "vk": "https://vk.com/semi"},
            {"city": "Уфа", "name": "Заброшенный", "query": "кафе", "vk": "https://vk.com/dead"},
            {"city": "Уфа", "name": "Без ВК", "query": "кафе"},
        ], str(raw))
        return str(raw)

    @staticmethod
    def _fake_vk(monkeypatch):
        from yandex_maps_parser import vk_stats

        def fake(records, log_fn=None):
            for r in records:
                r["vk_activity"], r["vk_followers"], r["vk_last_post_days"] = "", "", ""
                link = r.get("vk") or ""
                if link.endswith("/alive"):
                    r.update(vk_activity="active", vk_followers=500, vk_last_post_days=3)
                elif link.endswith("/semi"):
                    r.update(vk_activity="semi", vk_followers=80, vk_last_post_days=60)
                elif link.endswith("/dead"):
                    r.update(vk_activity="inactive", vk_followers=5, vk_last_post_days=900)
            return 3

        monkeypatch.setattr(vk_stats, "annotate_records", fake)

    def test_vk_mode_active_keeps_only_live_communities(self, tmp_path, monkeypatch):
        self._fake_vk(monkeypatch)
        res = processing.apply_filters([self._raw_with_vk(tmp_path)],
                                       {"vk_check": True, "vk_mode": "active"})
        assert {r["name"] for r in res["groups"]["кафе"]["Уфа"]} == {"Живой", "Без ВК"}

    def test_records_without_vk_data_are_never_treated_as_inactive(self, tmp_path, monkeypatch):
        """A missing VK link must not be a reason to drop the lead."""
        self._fake_vk(monkeypatch)
        res = processing.apply_filters([self._raw_with_vk(tmp_path)],
                                       {"vk_check": True, "vk_mode": "active_semi"})
        assert {r["name"] for r in res["groups"]["кафе"]["Уфа"]} == \
            {"Живой", "Полуживой", "Без ВК"}

    def test_vk_post_age_and_followers_limits(self, tmp_path, monkeypatch):
        self._fake_vk(monkeypatch)
        res = processing.apply_filters(
            [self._raw_with_vk(tmp_path)],
            {"vk_check": True, "vk_mode": "all", "vk_max_post_days": 30,
             "vk_min_followers": 100})
        assert {r["name"] for r in res["groups"]["кафе"]["Уфа"]} == {"Живой", "Без ВК"}

    def test_vk_check_off_ignores_activity_filters(self, tmp_path, monkeypatch):
        """Without the checkbox the activity data is not even fetched."""
        from yandex_maps_parser import vk_stats
        monkeypatch.setattr(vk_stats, "annotate_records",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
        res = processing.apply_filters([self._raw_with_vk(tmp_path)],
                                       {"vk_mode": "active"})
        assert res["count"] == 4

    def test_empty_result_flag(self, tmp_path):
        """Edge case 2: nothing survives → empty flag for the UI message."""
        raw = tmp_path / "raw.xlsx"
        from yandex_maps_parser.exporters import save_excel
        save_excel([{"city": "Уфа", "name": "A", "query": "кафе", "website": "https://a.ru"}],
                   str(raw), extra_fields=("website",))
        res = processing.apply_filters([str(raw)], {"parse_mode": "without_website"})
        assert res["empty"] is True and res["count"] == 0

    def test_missing_files_tolerated(self):
        res = processing.apply_filters(["Z:/no/such/file.xlsx"], {})
        assert res["empty"] is True


# ── save_processed / cleanup_raw ──────────────────────────────

class TestSaveProcessed:
    def test_json_and_csv_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state, "PROCESSED_DIR", str(tmp_path))
        recs = [{"city": "Уфа", "name": "A", "query": "кафе", "lat": "54.7", "lon": "55.9"}]
        pj = processing.save_processed(recs, "json", "кафе", "Уфа")
        pc = processing.save_processed(recs, "csv", "кафе", "Уфа")
        assert os.path.isfile(pj) and os.path.basename(pj) == "кафе_уфа_filtered.json"
        assert os.path.dirname(pj).replace("\\", "/").endswith("/json")
        assert os.path.isfile(pc) and os.path.basename(pc) == "кафе_уфа_filtered.csv"
        assert os.path.dirname(pc).replace("\\", "/").endswith("/csv")

    def test_excel_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(state, "PROCESSED_DIR", str(tmp_path))
        recs = [{"city": "Уфа", "name": "A", "query": "кафе"}]
        p = processing.save_processed(recs, "excel", "кафе", "Уфа")
        assert os.path.isfile(p) and p.endswith("кафе_уфа_filtered.xlsx")


class TestCleanupRaw:
    def _mk(self, tmp_path, monkeypatch, n=2):
        monkeypatch.setattr(state, "RAW_DIR", str(tmp_path / "raw"))
        os.makedirs(str(tmp_path / "raw"), exist_ok=True)
        files = []
        for i in range(n):
            f = tmp_path / "raw" / f"raw_2026-09-13_10-0{i}_q_c.xlsx"
            f.write_text("dummy", encoding="utf-8")
            files.append(str(f))
        return files

    def test_keep_mode(self, tmp_path, monkeypatch):
        files = self._mk(tmp_path, monkeypatch)
        processing.cleanup_raw(files, "keep")
        assert all(os.path.isfile(f) for f in files)

    def test_delete_mode(self, tmp_path, monkeypatch):
        files = self._mk(tmp_path, monkeypatch)
        processing.cleanup_raw(files, "delete")
        assert not any(os.path.isfile(f) for f in files)

    def test_archive_mode_moves_to_dated_dir(self, tmp_path, monkeypatch):
        files = self._mk(tmp_path, monkeypatch)
        monkeypatch.setattr(state, "OUTPUT_DIR", str(tmp_path))
        import paths as paths_mod
        monkeypatch.setattr(paths_mod, "user_dir", lambda: tmp_path)
        processing.cleanup_raw(files, "archive")
        assert not any(os.path.isfile(f) for f in files)
        import datetime
        day = datetime.date.today().isoformat()
        archived = list((tmp_path / "output" / "_archive" / day).glob("*.xlsx"))
        assert len(archived) == len(files)


# ── run_web raw-mode wiring ───────────────────────────────────

class TestRawPipelineMode:
    def test_filters_neutralized_in_raw_mode(self):
        params = {
            "queries": ["кафе"], "cities": ["Уфа"], "source": "yandex",
            "pipeline": "raw", "parse_mode": "without_website",
            "collapse_chains": True,
        }
        runner._apply_params(params)
        try:
            assert state.PIPELINE == "raw"
            assert state.PARSE_MODE == "all"      # collection sees everything
            assert state.COLLAPSE_CHAINS is False
        finally:
            state.PIPELINE = ""
            state.PARSE_MODE = "without_website"

    def test_legacy_mode_untouched(self):
        params = {
            "queries": ["кафе"], "cities": ["Уфа"], "source": "yandex",
            "parse_mode": "without_website",
        }
        runner._apply_params(params)
        try:
            assert state.PIPELINE == ""            # legacy pipeline
            assert state.PARSE_MODE == "without_website"
        finally:
            state.PIPELINE = ""

    def test_required_socials_kept_regardless_of_social_mode(self):
        """The tiles are a stage-2 filter — they must survive any social_mode
        so the crawl can still fetch the detail page that proves the network."""
        from yandex_maps_parser import runner as _runner

        for mode in ("all", "with_socials", "without_socials"):
            _runner._apply_params({"social_mode": mode, "required_socials": ["vk", "nope"]})
            try:
                assert state.REQUIRED_SOCIALS == {"vk"}, f"tiles lost in mode {mode}"
            finally:
                state.REQUIRED_SOCIALS = set()

    def test_without_socials_mode_no_longer_disables_detail_fetch(self):
        """Filtering happens in stage 2, so «без соцсетей» must NOT skip the
        detail fetch — otherwise there would be nothing to filter on."""
        from yandex_maps_parser import runner as _runner

        _runner._apply_params({"social_mode": "without_socials", "fetch_detail": True})
        assert state.FETCH_DETAIL is True
        _runner._apply_params({"social_mode": "all", "fetch_detail": False})
        assert state.FETCH_DETAIL is False, "the explicit «не собирать соцсети» switch still works"
        state.FETCH_DETAIL = True

    def test_interrupted_run_skips_stage2(self, monkeypatch):
        """Edge case 3: stop_event set → stage 2 must not run."""
        import threading as _th

        calls = {"n": 0}
        monkeypatch.setattr(state, "PIPELINE", "raw", raising=False)
        monkeypatch.setattr(state, "_RAW_FILES_LAST_RUN", ["r.xlsx"], raising=False)
        monkeypatch.setattr(state, "SEARCH_QUERIES", ["кафе"])
        monkeypatch.setattr(state, "CITY", "Уфа")
        monkeypatch.setattr(state, "_LOG_FN", None, raising=False)
        monkeypatch.setattr(state, "_SYSLOG_FN", None, raising=False)

        import yandex_maps_parser.processing as proc
        monkeypatch.setattr(proc, "process_all", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})

        # Minimal run_web scaffolding: stop the loop before it starts.
        stop = _th.Event(); stop.set()

        # run_web needs a couple of attrs; give it no cities so it bails
        # right after _apply_params… but we need to reach the finally block.
        # Simpler: call the finally logic indirectly via a real run_web with
        # an empty city list and no output dirs written.
        params = {"queries": [], "cities": [], "pipeline": "raw"}
        runner._apply_params(params)   # keep state consistent
        try:
            runner.run_web(params, None, stop_event=stop)
        except Exception:
            pass
        assert calls["n"] == 0, "stage 2 must not run when the crawl was stopped"

    def test_complete_run_starts_stage2(self, monkeypatch):
        """The happy path: loop finishes → stage 2 runs once."""
        calls = {"n": 0}

        monkeypatch.setattr(state, "PIPELINE", "raw", raising=False)
        monkeypatch.setattr(state, "RAW_MODE", "keep", raising=False)
        monkeypatch.setattr(state, "SEARCH_QUERIES", ["кафе"])
        monkeypatch.setattr(state, "CITY", "Уфа")

        import yandex_maps_parser.processing as proc
        monkeypatch.setattr(proc, "process_all", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})

        # Simulate: raw files exist from run(), city loop completed.
        monkeypatch.setattr(state, "_RAW_FILES_LAST_RUN", ["Z:/raw/x.xlsx"], raising=False)

        # run_web with an empty city list: the loop body never runs but
        # _loop_ok becomes True → the finally block performs stage 2.
        params = {"queries": [], "cities": [], "pipeline": "raw",
                  "output_excel": True, "output_json": False,
                  "output_csv": False, "output_map": False,
                  "parse_mode": "all", "min_rating": 0, "min_reviews": 0}
        runner._apply_params(params)
        try:
            runner.run_web(params, None)
        except Exception:
            pass
        assert calls["n"] == 1, "stage 2 must run exactly once on a complete crawl"
