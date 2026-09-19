"""
Unit tests for the VK activity helper (offline — the API is monkeypatched).

Run with: python -m pytest tests/test_vk_stats.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import vk_stats


class TestScreenName:
    def test_extracts_the_screen_name(self):
        assert vk_stats.screen_name("https://vk.com/pivmilya") == "pivmilya"
        assert vk_stats.screen_name("http://www.vk.com/club123") == "club123"

    def test_rejects_service_paths(self):
        assert vk_stats.screen_name("https://vk.com/wall-1_2") == ""
        assert vk_stats.screen_name("https://vk.com/away.php?to=x") == ""

    def test_rejects_foreign_and_empty_urls(self):
        assert vk_stats.screen_name("https://instagram.com/kafe") == ""
        assert vk_stats.screen_name("") == ""
        assert vk_stats.screen_name("https://vk.com") == ""

    def test_accepts_the_bare_screen_name_it_returned(self):
        # Regression: annotate_records feeds the extracted name back into
        # fetch_stats, which re-parsed it and silently found nothing.
        assert vk_stats.screen_name("pivmilya") == "pivmilya"
        assert vk_stats.screen_name("@pivmilya") == "pivmilya"
        assert vk_stats.screen_name(vk_stats.screen_name("https://vk.com/pivmilya")) == "pivmilya"

    def test_rejects_bare_service_words(self):
        assert vk_stats.screen_name("wall") == ""


class TestClassify:
    def test_thresholds(self):
        assert vk_stats.classify(0) == "active"
        assert vk_stats.classify(vk_stats.ACTIVE_MAX_DAYS) == "active"
        assert vk_stats.classify(vk_stats.ACTIVE_MAX_DAYS + 1) == "semi"
        assert vk_stats.classify(vk_stats.SEMI_MAX_DAYS) == "semi"
        assert vk_stats.classify(vk_stats.SEMI_MAX_DAYS + 1) == "inactive"

    def test_unknown_without_data(self):
        assert vk_stats.classify(None) == "unknown"


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(vk_stats, "_cache_get", lambda screen: None)
    monkeypatch.setattr(vk_stats, "_cache_put", lambda screen, stats: None)


class TestFetchStats:
    def test_group_activity_from_api(self, monkeypatch, no_cache):
        def fake_api(method, params, token):
            if method == "utils.resolveScreenName":
                return {"type": "group", "object_id": 12345}
            if method == "groups.getById":
                return {"groups": [{"members_count": 420}]}
            if method == "wall.get":
                return {"items": [{"date": vk_stats.time.time() - 2 * 86400}]}
            return None

        monkeypatch.setattr(vk_stats, "_api", fake_api)
        stats = vk_stats.fetch_stats("https://vk.com/kafe", token="t")
        assert stats["activity"] == "active"
        assert stats["followers"] == 420
        assert stats["last_post_days"] == 2

    def test_hidden_members_become_minus_one(self, monkeypatch, no_cache):
        def fake_api(method, params, token):
            if method == "utils.resolveScreenName":
                return {"type": "group", "object_id": 1}
            if method == "groups.getById":
                return {"groups": [{}]}          # is_closed, no count
            if method == "wall.get":
                return {"items": []}             # empty wall
            return None

        monkeypatch.setattr(vk_stats, "_api", fake_api)
        stats = vk_stats.fetch_stats("https://vk.com/kafe", token="t")
        assert stats["followers"] == -1
        assert stats["last_post_days"] == -1
        assert stats["activity"] == "unknown"

    def test_unresolvable_link_is_skipped(self, monkeypatch, no_cache):
        monkeypatch.setattr(vk_stats, "_api", lambda *a, **k: None)
        assert vk_stats.fetch_stats("https://vk.com/gone", token="t") == {}

    def test_no_token_means_no_request(self, monkeypatch):
        calls = []
        monkeypatch.setattr(vk_stats, "_api", lambda *a, **k: calls.append(a) or None)
        monkeypatch.setattr(vk_stats, "_token", lambda: "")
        assert vk_stats.fetch_stats("https://vk.com/kafe") == {}
        assert calls == []


class TestAnnotateRecords:
    def test_without_token_warns_and_changes_nothing(self, monkeypatch):
        monkeypatch.setattr(vk_stats, "_token", lambda: "")
        logs = []
        records = [{"vk": "https://vk.com/kafe"}]
        assert vk_stats.annotate_records(records, log_fn=lambda lvl, msg: logs.append((lvl, msg))) == 0
        assert "vk_activity" not in records[0]
        assert any(lvl == "warn" for lvl, _ in logs)

    def test_fills_only_measured_records(self, monkeypatch):
        monkeypatch.setattr(vk_stats, "_token", lambda: "t")
        monkeypatch.setattr(vk_stats, "fetch_stats", lambda screen, token="", cache=None: {
            "activity": "active", "followers": 100, "last_post_days": 3,
        })
        records = [{"vk": "https://vk.com/a"}, {"vk": ""}, {"name": "без ВК"}]
        assert vk_stats.annotate_records(records) == 1
        assert records[0]["vk_activity"] == "active"
        assert records[0]["vk_followers"] == 100
        assert "vk_activity" not in records[1]
        assert "vk_activity" not in records[2]

    def test_real_fetch_path_fills_the_record(self, monkeypatch):
        """End-to-end through the REAL fetch_stats (only the API is stubbed):
        catches the class of bug where the extracted screen name is fed back
        in and silently resolves to nothing."""
        monkeypatch.setattr(vk_stats, "_token", lambda: "t")
        monkeypatch.setattr(vk_stats, "_load_cache", lambda: {})
        monkeypatch.setattr(vk_stats, "_save_cache", lambda cache: None)

        def fake_api(method, params, token):
            if method == "utils.resolveScreenName":
                return {"type": "group", "object_id": 7}
            if method == "groups.getById":
                return {"groups": [{"members_count": 900}]}
            if method == "wall.get":
                return {"items": [{"date": vk_stats.time.time() - 5 * 86400}]}
            return None

        monkeypatch.setattr(vk_stats, "_api", fake_api)
        records = [{"vk": "https://vk.com/grandcafe"}]
        assert vk_stats.annotate_records(records) == 1
        assert records[0]["vk_activity"] == "active"
        assert records[0]["vk_followers"] == 900
        assert records[0]["vk_last_post_days"] == 5

    def test_the_cache_is_written_once_per_batch(self, monkeypatch):
        """Regression: the cache JSON used to be re-read and re-saved for
        every community, which is O(n²) disk I/O on a long list."""
        monkeypatch.setattr(vk_stats, "_token", lambda: "t")
        monkeypatch.setattr(vk_stats, "_load_cache", lambda: {})
        saves = []
        monkeypatch.setattr(vk_stats, "_save_cache", lambda cache: saves.append(dict(cache)))
        monkeypatch.setattr(vk_stats, "_api", lambda *a, **k: {"type": "group", "object_id": 1})

        records = [{"vk": "https://vk.com/a"}, {"vk": "https://vk.com/b"},
                   {"vk": "https://vk.com/c"}]
        assert vk_stats.annotate_records(records) == 3
        assert len(saves) == 1, "the cache must be flushed once per batch"
        assert {"a", "b", "c"} <= set(saves[0])

    def test_a_warm_batch_cache_skips_the_api(self, monkeypatch):
        monkeypatch.setattr(vk_stats, "_token", lambda: "t")
        warm = {"alive": {"activity": "active", "followers": 42,
                          "last_post_days": 1, "ts": vk_stats.time.time()}}
        monkeypatch.setattr(vk_stats, "_load_cache", lambda: warm)
        monkeypatch.setattr(vk_stats, "_save_cache", lambda cache: None)
        monkeypatch.setattr(vk_stats, "_api",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call for a cached community")))

        records = [{"vk": "https://vk.com/alive"}]
        vk_stats.annotate_records(records)
        assert records[0]["vk_followers"] == 42
        assert records[0]["vk_activity"] == "active"

    def test_negative_followers_are_left_empty(self, monkeypatch):
        monkeypatch.setattr(vk_stats, "_token", lambda: "t")
        monkeypatch.setattr(vk_stats, "fetch_stats", lambda screen, token="", cache=None: {
            "activity": "inactive", "followers": -1, "last_post_days": -1,
        })
        records = [{"vk": "https://vk.com/a"}]
        vk_stats.annotate_records(records)
        assert records[0]["vk_followers"] == ""
        assert records[0]["vk_last_post_days"] == ""
        assert records[0]["vk_activity"] == "inactive"
