"""
Regression tests for the 2GIS Places-quota counter (incl. monthly
persistence across app restarts), per-response billing rules in
twogis.search_items, and the grid step/radius guard in
runner._apply_params (offline — no network calls).

Run with: python -m pytest tests/test_quota_grid.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser import state
from yandex_maps_parser import twogis
from yandex_maps_parser.twogis import quota_used, quota_reset, _quota_count
from yandex_maps_parser.runner import _apply_params


@pytest.fixture(autouse=True)
def _twogis_clean(monkeypatch, tmp_path):
    """Isolate global counters/flags AND redirect the persistence file."""
    monkeypatch.setattr(twogis, "_quota_file", lambda: tmp_path / ".2gis_quota.json")
    monkeypatch.setattr(twogis, "_quota_base", 0)
    monkeypatch.setattr(twogis, "_quota_used", 0)
    monkeypatch.setattr(twogis, "_quota_file_loaded", False)
    monkeypatch.setattr(twogis, "_quota_soft_warned", False)
    monkeypatch.setattr(twogis, "_quota_hard_warned", False)
    twogis.reset_field_fallback()
    state.USE_GRID = False
    quota_reset()
    yield
    twogis.reset_field_fallback()
    quota_reset()


# ── quota counter: count, reset, warnings, persistence ────────

def test_quota_counts_within_run():
    assert quota_used() == 0
    _quota_count(1)
    _quota_count(3)
    assert quota_used() == 4


def test_quota_persists_across_restart(tmp_path, monkeypatch):
    """The counter must survive an app restart: a new 'process' (fresh module
    state) picks up the persisted month bucket and keeps accumulating."""
    _quota_count(120)
    # Simulate a restart: reload the module (fresh _quota_used = 0) while
    # keeping the persistence file pointed at the same tmp_path.
    import importlib
    monkeypatch.setattr(twogis, "_quota_file", lambda: tmp_path / ".2gis_quota.json")
    importlib.reload(twogis)
    monkeypatch.setattr(twogis, "_quota_file", lambda: tmp_path / ".2gis_quota.json")
    try:
        assert twogis.quota_used() == 120
        twogis._quota_count(5)
        assert twogis.quota_used() == 125
    finally:
        importlib.reload(twogis)   # restore for subsequent tests (fixture re-isolates)


def test_quota_bucket_resets_each_month(tmp_path):
    """A persisted bucket from a previous month must be discarded."""
    import json
    (tmp_path / ".2gis_quota.json").write_text(
        json.dumps({"month": "1999-01", "used": 999}), encoding="utf-8")
    assert quota_used() == 0


def test_quota_persisted_base_adds_to_run_counter(tmp_path, monkeypatch):
    """quota_reset() re-arms warnings but keeps the monthly total."""
    import json
    (tmp_path / ".2gis_quota.json").write_text(
        json.dumps({"month": twogis.time.strftime("%Y-%m"), "used": 500}), encoding="utf-8")
    monkeypatch.setattr(twogis, "_quota_file", lambda: tmp_path / ".2gis_quota.json")
    monkeypatch.setattr(twogis, "_quota_file_loaded", False)   # force re-read
    assert quota_used() == 500
    quota_reset()          # new run
    assert quota_used() == 500
    _quota_count(10)
    assert quota_used() == 510


def test_quota_warnings_fire_exactly_once_per_run(monkeypatch):
    msgs = []
    monkeypatch.setattr(twogis.state, "warn", lambda m: msgs.append(m))

    for _ in range(twogis._QUOTA_WARN_SOFT):        # → 850: soft warning
        _quota_count(1)
    soft = [m for m in msgs if "850" in m]
    assert len(soft) == 1, msgs

    for _ in range(twogis._QUOTA_WARN_HARD - twogis._QUOTA_WARN_SOFT):  # → 950
        _quota_count(1)
    hard = [m for m in msgs if "осталось менее" in m]
    assert len(hard) == 1, msgs

    for _ in range(50):                              # → 1000: cap reached →
        _quota_count(1)                              # ONE stop warning, no more
    assert len(msgs) == 3, msgs
    assert len([m for m in msgs if "остановлен" in m]) == 1

    # New run over an already-exhausted month: reset re-arms and immediately
    # warns that the monthly limit is spent (key is dead until next month).
    quota_reset()
    _quota_count(1)
    assert len([m for m in msgs if "лимит исчерпан" in m]) == 1


def test_quota_cap_reached_stops_run_once(monkeypatch):
    """Reaching the monthly cap fires ONE stop warning + requests a graceful
    stop; further billing attempts stay silent."""
    import threading
    msgs = []
    stops = threading.Event()
    monkeypatch.setattr(twogis.state, "warn", lambda m: msgs.append(m))
    monkeypatch.setattr(twogis.state, "request_stop", lambda: stops.set())

    for _ in range(twogis._QUOTA_DEMO_CAP):          # bill up to 1000
        _quota_count(1)

    stop_msgs = [m for m in msgs if "остановлен" in m]
    assert len(stop_msgs) == 1, msgs
    assert stops.is_set(), "graceful stop requested"

    # Over the cap: no additional stop warnings
    for _ in range(10):
        _quota_count(1)
    assert len([m for m in msgs if "остановлен" in m]) == 1


def test_quota_stop_resets_per_run(monkeypatch):
    """A fresh run re-arms the stop: an exhausted month stops immediately,
    exactly once per run."""
    import threading
    msgs = []
    stop_count = []
    monkeypatch.setattr(twogis.state, "warn", lambda m: msgs.append(m))
    monkeypatch.setattr(twogis.state, "request_stop", lambda: stop_count.append(1))

    for _ in range(twogis._QUOTA_DEMO_CAP + 5):
        _quota_count(1)
    assert len(stop_count) == 1

    # New run over an exhausted month: quota_reset re-arms everything.
    quota_reset()
    _quota_count(1)
    assert len(stop_count) == 2, "stop fires again in a new run"
    start_msgs = [m for m in msgs if "лимит исчерпан" in m]
    assert len(start_msgs) == 1                      # start-of-run warning (once)


def test_429_warns_once_then_silent_and_stops(monkeypatch):
    """The per-page 429/limit error is logged ONCE in plain language and
    stops the run; subsequent limit errors don't spam the browser log."""
    import threading
    msgs = []
    stops = threading.Event()
    monkeypatch.setattr(twogis.state, "warn", lambda m: msgs.append(m))
    monkeypatch.setattr(twogis.state, "tech", lambda m: None)
    monkeypatch.setattr(twogis.state, "request_stop", lambda: stops.set())

    resp = _FakeResp(_api_payload(429, error={"message": "limit exceeded", "type": "quota"}))
    monkeypatch.setattr(twogis, "_get", lambda url, params=None, session=None: resp)

    for _ in range(3):                               # 3 pages in a row
        items, total = twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
        assert (items, total) == ([], None)

    limit_msgs = [m for m in msgs if "лимит" in m.lower() or "лимит" in m]
    assert len(limit_msgs) == 1, msgs
    assert stops.is_set(), "run stop requested on the first 429"


def test_pages_cap_warns_once_when_max_pages_exceeds_5(monkeypatch):
    """MAX_PAGES > 5 with 2GIS: one plain-language warning per run about the
    5-page API cap; silent when the cap is respected."""
    msgs = []
    monkeypatch.setattr(twogis.state, "warn", lambda m: msgs.append(m))
    monkeypatch.setattr(twogis.state, "syslog", lambda m: None)

    class _S:
        MAX_PAGES = 15
        _STOP_EVENT = None
    monkeypatch.setattr(twogis.state, "MAX_PAGES", 15, raising=False)

    pages_requested = []

    def _fake_search(query, city, lat, lon, page, session=None):
        pages_requested.append(page)
        return ([{"fake": f"{page}-{i}"} for i in range(10)], 100)   # full page

    monkeypatch.setattr(twogis, "search_items", _fake_search)
    monkeypatch.setattr(twogis, "parse_item", lambda it, q: {"_biz_id": it["fake"], "name": "x"})

    from yandex_maps_parser import twogis as t
    t.collect_candidates_2gis("кафе", "Уфа", 54.7, 55.9,
                              seen_urls=set(), pbar_search=None, pbar_detail=None,
                              search_session=None)
    cap_msgs = [m for m in msgs if "5 страниц" in m]
    assert len(cap_msgs) == 1, msgs
    assert len(pages_requested) == 5, "pages clamped to the API cap"

def test_quota_thresholds_match_demo_cap():
    assert twogis._QUOTA_DEMO_CAP == 1000
    assert twogis._QUOTA_WARN_SOFT < twogis._QUOTA_WARN_HARD < twogis._QUOTA_DEMO_CAP


# ── search_items: only successful responses are billed ────────

class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _api_payload(meta_code, items=None, error=None):
    meta = {"code": meta_code}
    if error:
        meta["error"] = error
    return {"meta": meta, "result": {"total": len(items or []), "items": items or []}}


def test_search_items_success_bills_one_token(monkeypatch):
    monkeypatch.setattr(
        twogis, "_get",
        lambda url, params=None, session=None: _FakeResp(
            _api_payload(200, items=[{"id": "1"}])))
    items, total = twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
    assert items == [{"id": "1"}]
    assert quota_used() == 1


def test_search_items_meta_error_still_billed_returns_empty(monkeypatch):
    # 2GIS signals errors inside an HTTP-200 body: still billed by 2GIS,
    # but the parser must return no items (meta.code 200 → billed).
    monkeypatch.setattr(
        twogis, "_get",
        lambda url, params=None, session=None: _FakeResp(
            _api_payload(200, error={"message": "ключ недействителен", "type": "auth"})))
    items, total = twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
    assert items == [] and total is None
    assert quota_used() == 1


def test_search_items_failed_meta_code_not_billed(monkeypatch):
    monkeypatch.setattr(
        twogis, "_get",
        lambda url, params=None, session=None: _FakeResp(
            _api_payload(403, error={"message": "ключ заблокирован", "type": "auth"}),
            status_code=403))
    items, total = twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
    assert items == [] and total is None
    assert quota_used() == 0


def test_search_items_no_response_not_billed(monkeypatch):
    monkeypatch.setattr(twogis, "_get", lambda url, params=None, session=None: None)
    monkeypatch.setattr(twogis.state, "warn", lambda m: None)
    items, total = twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
    assert (items, total) == ([], None)
    assert quota_used() == 0


def test_search_items_meta_204_counts_as_billed(monkeypatch):
    monkeypatch.setattr(
        twogis, "_get",
        lambda url, params=None, session=None: _FakeResp(_api_payload(204)))
    twogis.search_items("кафе", "Уфа", 54.7, 55.9, 0)
    assert quota_used() == 1


# ── _apply_params: grid step/radius guard ─────────────────────

def test_apply_params_clamps_step_over_radius_for_2gis():
    _apply_params({"queries": ["кафе"], "source": "2gis", "use_grid": True,
                   "grid_radius": 10, "grid_step": 15})
    assert state.GRID_STEP_KM == 10
    assert state.GRID_RADIUS_KM == 10


def test_apply_params_keeps_sane_pair_for_2gis():
    _apply_params({"queries": ["кафе"], "source": "2gis", "use_grid": True,
                   "grid_radius": 20, "grid_step": 5})
    assert state.GRID_RADIUS_KM == 20
    assert state.GRID_STEP_KM == 5


def test_apply_params_equal_step_radius_allowed():
    _apply_params({"queries": ["кафе"], "source": "2gis", "use_grid": True,
                   "grid_radius": 8, "grid_step": 8})
    assert state.GRID_RADIUS_KM == 8
    assert state.GRID_STEP_KM == 8


def test_apply_params_yandex_pair_not_touched():
    _apply_params({"queries": ["кафе"], "source": "yandex", "use_grid": True,
                   "grid_radius": 10, "grid_step": 15})
    assert state.GRID_STEP_KM == 15
    assert state.GRID_RADIUS_KM == 10


def test_apply_params_grid_off_not_clamped():
    _apply_params({"queries": ["кафе"], "source": "2gis", "use_grid": False,
                   "grid_radius": 10, "grid_step": 15})
    assert state.GRID_STEP_KM == 15


def test_apply_params_source_validation():
    _apply_params({"queries": ["кафе"], "source": "bogus"})
    assert state.SOURCE == "yandex"          # unknown source falls back
    _apply_params({"queries": ["кафе"], "source": "2gis"})
    assert state.SOURCE == "2gis"
