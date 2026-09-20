"""Tests for the pause feature: position tracking + enriched resume payload."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import run_manager as rm
from run_manager import _pause_resume_payload, _bridge_reader, run_manager
import yandex_maps_parser.state as state


@pytest.fixture(autouse=True)
def _isolated_runs():
    """The RunManager singleton is module state — keep tests independent.

    active_run_id() returns the OLDEST active entry, so a leftover run from a
    previous test would decide which run «продолжить» sees.
    """
    with run_manager._lock:
        saved = dict(run_manager._runs)
        run_manager._runs.clear()
    yield
    with run_manager._lock:
        run_manager._runs.clear()
        run_manager._runs.update(saved)


@pytest.fixture(autouse=True)
def _clean_pause_state():
    """PAUSE_INFO is global module state — reset it around every test."""
    state.update_pause_info(city="", city_idx=0, cities_total=0,
                            query="", point=0, points_total=0)
    yield
    state.update_pause_info(city="", city_idx=0, cities_total=0,
                            query="", point=0, points_total=0)


def test_pause_position_defaults():
    pos = state.pause_position()
    assert pos["city"] == ""
    assert pos["city_idx"] == 0
    assert "records" in pos


def test_pause_position_update_and_snapshot():
    state.update_pause_info(city="Уфа", city_idx=2, cities_total=5,
                            query="кафе", point=7, points_total=12)
    pos = state.pause_position()
    assert pos == {"city": "Уфа", "city_idx": 2, "cities_total": 5,
                   "query": "кафе", "point": 7, "points_total": 12,
                   "records": pos["records"]}
    # snapshot is a copy, not a live reference
    state.update_pause_info(city="Москва")
    assert pos["city"] == "Уфа"


def test_resume_payload_contains_position_and_quota():
    state.update_pause_info(city="Казань", city_idx=1, cities_total=3,
                            query="отель", point=3, points_total=9)
    entry = {
        "id": "deadbeef",
        "params": {"queries": ["отель"], "cities": ["Казань", "Уфа"],
                   "source": "twogis"},
    }
    payload = _pause_resume_payload(entry)
    assert payload["run_id"] == "deadbeef"
    assert payload["queries"] == ["отель"]
    assert payload["all_cities"] == ["Казань", "Уфа"]
    assert payload["position"]["city"] == "Казань"
    assert payload["quota"] is not None
    assert payload["quota"]["cap"] > 0
    assert payload["quota"]["used"] <= payload["quota"]["cap"]


def test_resume_payload_yandex_has_no_quota():
    entry = {"id": "x", "params": {"queries": ["a"], "cities": ["Барнаул"],
                                   "source": "yandex"}}
    payload = _pause_resume_payload(entry)
    assert payload["quota"] is None
    assert payload["position"]["city"] == ""  # not set for this fake run


def test_resume_payload_tolerates_broken_state(monkeypatch):
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(state, "pause_position", boom, raising=False)
    entry = {"id": "x", "params": {"queries": [], "cities": []}}
    payload = _pause_resume_payload(entry)
    assert payload["position"] == {}
    assert payload["quota"] is None


# ── Pause really stops the run ───────────────────────────────
# Regression: «Пауза» used to only flip entry["paused"] — in thread-fallback
# mode nothing set the event, so the search kept running.

def _entry_with_stop_files(tmp_path):
    entry = run_manager.new_run()
    stop_dir = tmp_path / ".run_stop"
    stop_dir.mkdir()
    entry["stop_file"] = str(stop_dir / f"{entry['id']}.stop")
    entry["skip_file"] = str(stop_dir / f"{entry['id']}.skip")
    entry["pause_file"] = str(stop_dir / f"{entry['id']}.pause")
    entry["params"] = {"queries": ["кафе"], "cities": ["Уфа"]}
    entry["cities"] = ["Уфа"]
    return entry


def test_pause_sets_both_signals(tmp_path):
    entry = _entry_with_stop_files(tmp_path)
    targets = run_manager.stop_run(entry["id"], pause=True)
    assert targets == [entry["id"]], "роут должен знать, кого именно он остановил"
    assert entry["paused"] is True
    assert entry["pause_event"].is_set(), "thread fallback wakes up too"
    assert entry["stop_event"].is_set(), "engine unwinds through the stop path"
    assert os.path.isfile(entry["pause_file"]), "child process sees the pause"
    # Regression: the stop file used to be written for a pause too. The child
    # watches both files and whichever fired first won — when `.stop` won, the
    # pause flag was never set and the run ended as a plain stop (no
    # «Продолжить»). A pause must therefore leave the stop file alone.
    assert not os.path.exists(entry["stop_file"]), "пауза не пишет стоп-файл"


def test_stop_is_not_a_pause(tmp_path):
    entry = _entry_with_stop_files(tmp_path)
    targets = run_manager.stop_run(entry["id"], pause=False)
    assert targets == [entry["id"]]
    assert not entry.get("paused")
    assert not entry["pause_event"].is_set()
    assert entry["stop_event"].is_set()
    assert not os.path.exists(entry["pause_file"])
    assert os.path.isfile(entry["stop_file"]), "честный стоп пишет стоп-файл"


def test_stop_run_without_targets_reports_nothing(tmp_path):
    """Пауза после уже завершённого поиска не должна считаться успешной."""
    assert run_manager.stop_run("нет-такого", pause=True) == []


# ── Файловый наблюдатель паузы (дочерний процесс) ─────────────

def test_pause_watcher_flags_both_events(tmp_path):
    import threading
    from yandex_maps_parser.runner import _watch_pause_file

    pf = tmp_path / "r.pause"
    pf.write_text("pause")
    pause_ev, stop_ev = threading.Event(), threading.Event()
    _watch_pause_file(str(pf), pause_ev, stop_ev, poll=0.01, stop_grace=0.05)
    assert pause_ev.is_set() and stop_ev.is_set()


def test_pause_watcher_catches_a_pause_that_lost_the_race(tmp_path):
    """Стоп обогнал паузу — пауза всё равно должна быть распознана.

    Именно этот случай терялся: стоп-файл приходил первым, наблюдатель паузы
    выходил сразу, и поиск завершался как обычная остановка.
    """
    import threading
    import time as _t
    from yandex_maps_parser.runner import _watch_pause_file

    pf = tmp_path / "r.pause"
    pause_ev, stop_ev = threading.Event(), threading.Event()
    stop_ev.set()                       # стоп пришёл первым
    th = threading.Thread(target=_watch_pause_file,
                          args=(str(pf), pause_ev, stop_ev),
                          kwargs={"poll": 0.02, "stop_grace": 2.0}, daemon=True)
    th.start()
    _t.sleep(0.15)
    pf.write_text("pause")              # пауза догоняет
    th.join(timeout=2.0)
    assert pause_ev.is_set(), "пауза не потерялась"


def test_pause_watcher_gives_up_on_a_plain_stop(tmp_path):
    import threading
    from yandex_maps_parser.runner import _watch_pause_file

    pause_ev, stop_ev = threading.Event(), threading.Event()
    stop_ev.set()
    done = threading.Event()

    def run():
        _watch_pause_file(str(tmp_path / "never.pause"), pause_ev, stop_ev,
                          poll=0.01, stop_grace=0.05)
        done.set()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    assert done.wait(timeout=2.0), "наблюдатель обязан завершиться"
    assert not pause_ev.is_set()


def test_pause_grace_is_longer_than_stop(monkeypatch):
    """A pause must be given time to flush the checkpoint + Excel."""
    assert rm._PAUSE_GRACE_SEC > rm._STOP_GRACE_SEC


def test_bridge_crash_done_keeps_pause(tmp_path, monkeypatch):
    """A hard-killed paused child still yields a resumable «done»."""
    import queue as _queue
    monkeypatch.setattr(rm, "_FINISH_DELAY", 0.01)
    entry = _entry_with_stop_files(tmp_path)
    entry["paused"] = True
    reg = _queue.Queue()
    mp = _queue.Queue()
    mp.put(None)                      # sentinel: the child stopped talking
    _bridge_reader(mp, reg, entry)
    msg = reg.get_nowait()
    assert msg["type"] == "done"
    assert msg["paused"] is True
    assert msg["resume"]["run_id"] == entry["id"]


# ── Resume must actually start (not queue behind the paused run) ─────
# Regression: right after a pause the run is still marked active for
# _FINISH_DELAY seconds. «Продолжить» then landed in the queue behind a run
# that is never started again, and /logs kept streaming the dead run — the
# search appeared not to resume at all.

def test_clear_paused_run_finalizes_it(tmp_path):
    entry = _entry_with_stop_files(tmp_path)
    entry["paused"] = True
    assert run_manager.is_paused(entry["id"])
    assert run_manager.active_run_id() == entry["id"]

    assert run_manager.clear_paused_run(entry["id"]) == entry["id"]
    assert entry["active"] is False
    assert run_manager.active_run_id() != entry["id"]


def test_clear_paused_run_ignores_unpaused_and_unknown():
    running = run_manager.new_run()            # active, not paused
    try:
        assert run_manager.clear_paused_run(running["id"]) is None
        assert running["active"] is True
        assert run_manager.clear_paused_run("no-such-run") is None
    finally:
        run_manager.finish_run(running["id"])


def test_resume_request_starts_instead_of_queueing(tmp_path, monkeypatch):
    """A resume POST while a PAUSED run is still active starts the run."""
    from flask import Flask
    from routes import parser as parser_mod

    app = Flask(__name__)
    app.register_blueprint(parser_mod.bp)
    client = app.test_client()

    paused = _entry_with_stop_files(tmp_path)
    paused["paused"] = True

    started = []
    monkeypatch.setattr(run_manager, "start_process", lambda e: started.append(e["id"]))
    body = {"queries": ["кафе"], "cities": ["Уфа"], "resume": True}
    data = client.post("/run", json=body).get_json()
    assert data["queued"] is False, "resume must not wait in the queue"
    assert started == [data["run_id"]]


def test_plain_request_still_queues_behind_a_live_run(tmp_path, monkeypatch):
    from flask import Flask
    from routes import parser as parser_mod

    app = Flask(__name__)
    app.register_blueprint(parser_mod.bp)
    client = app.test_client()

    _entry_with_stop_files(tmp_path)          # active, NOT paused
    monkeypatch.setattr(run_manager, "start_process", lambda e: None)
    data = client.post("/run", json={"queries": ["кафе"], "cities": ["Уфа"]}).get_json()
    assert data["queued"] is True


def test_bridge_crash_done_without_pause(tmp_path, monkeypatch):
    import queue as _queue
    monkeypatch.setattr(rm, "_FINISH_DELAY", 0.01)
    entry = _entry_with_stop_files(tmp_path)
    reg = _queue.Queue()
    mp = _queue.Queue()
    mp.put(None)
    _bridge_reader(mp, reg, entry)
    msg = reg.get_nowait()
    assert msg["paused"] is False
    assert msg["resume"] is None
