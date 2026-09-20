"""Pause → Resume → Pause: the whole cycle, driven through the real routes.

Regression for «после возобновления пауза прекращает поиск, а не ставит его
на паузу». The cycle is forced through the thread-fallback child (the engine is
stubbed, so nothing touches the network) because that child shares the entry's
events with the parent, which makes the whole contract observable:

  /run → engine running → /stop?pause=1 → done(paused=True)
       → /run(resume) → engine running again → /stop?pause=1 → done(paused=True)

Anything that turns the SECOND pause into a plain stop (a stale `.pause` file,
a paused entry left active, a resume that queues instead of starting) makes one
of the assertions below fail.
"""
import queue as _queue
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import run_manager as rm
from run_manager import run_manager


@pytest.fixture(autouse=True)
def _isolated_runs():
    with run_manager._lock:
        saved = dict(run_manager._runs)
        run_manager._runs.clear()
    yield
    with run_manager._lock:
        run_manager._runs.clear()
        run_manager._runs.update(saved)


@pytest.fixture
def _fallback_child(monkeypatch, tmp_path):
    """Force the thread-fallback child and stub the engine inside it."""
    import multiprocessing

    monkeypatch.setattr(rm, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(rm, "_FINISH_DELAY", 0.05)

    class _NoProcess:
        def __init__(self, *a, **k):
            raise RuntimeError("processes disabled for this test")

    monkeypatch.setattr(multiprocessing, "Process", _NoProcess)

    starts = []
    stop_kinds = []

    def fake_run_web(params, log_fn, stop_event=None, skip_event=None,
                     pause_event=None):
        import yandex_maps_parser.state as st
        st._STOP_EVENT = stop_event
        st._PAUSE_EVENT = pause_event
        starts.append(params.get("resume", False))
        log_fn("info", "engine start")
        deadline = time.time() + 20
        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                kind = "pause" if (pause_event is not None
                                   and pause_event.is_set()) else "stop"
                stop_kinds.append(kind)
                log_fn("ok" if kind == "pause" else "warn", kind.upper())
                break
            time.sleep(0.02)
        else:
            stop_kinds.append("timeout")
        return []

    import yandex_maps_parser as pkg
    monkeypatch.setattr(pkg, "run_web", fake_run_web, raising=False)
    return {"starts": starts, "stop_kinds": stop_kinds}


def _client():
    from flask import Flask
    from routes import parser as parser_mod

    app = Flask(__name__)
    app.register_blueprint(parser_mod.bp)
    return app.test_client()


def _wait_for(pred, timeout=8.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _drain(entry) -> list[dict]:
    msgs = []
    while True:
        try:
            msgs.append(entry["log_queue"].get_nowait())
        except _queue.Empty:
            return msgs


def _done_msg(entry) -> dict | None:
    for m in _drain(entry):
        if isinstance(m, dict) and m.get("type") == "done":
            return m
    return None


def test_pause_resume_pause_cycle(_fallback_child):
    client = _client()
    params = {"queries": ["кафе"], "cities": ["Уфа", "Курск"]}

    # ── 1. fresh run ──────────────────────────────────────────
    data = client.post("/run", json=params).get_json()
    assert data["queued"] is False
    run_a = data["run_id"]
    entry_a = run_manager.get(run_a)
    assert _wait_for(lambda: _fallback_child["starts"]), "движок не стартовал"

    # ── 2. pause it ───────────────────────────────────────────
    stopped = client.post("/stop?pause=1").get_json()
    assert stopped["targets"] == [run_a], stopped
    assert _wait_for(lambda: entry_a.get("_done")), "done так и не пришёл"
    done_a = _done_msg(entry_a)
    assert done_a is not None, "нет done-сообщения"
    assert done_a["paused"] is True, f"первая пауза не распознана: {done_a}"
    assert done_a["resume"], "пауза без данных для продолжения"
    assert _fallback_child["stop_kinds"][-1] == "pause"

    # ── 3. resume ─────────────────────────────────────────────
    resumed = dict(params, resume=True)
    data2 = client.post("/run", json=resumed).get_json()
    assert data2["queued"] is False, "«Продолжить» встал в очередь"
    run_b = data2["run_id"]
    assert run_b != run_a
    entry_b = run_manager.get(run_b)
    assert _wait_for(lambda: len(_fallback_child["starts"]) >= 2), \
        "возобновлённый поиск не стартовал"
    assert _fallback_child["starts"][-1] is True, "resume потерялся"

    # ── 4. pause AGAIN — must still be a pause ────────────────
    stopped2 = client.post("/stop?pause=1").get_json()
    assert stopped2["targets"] == [run_b], \
        f"вторая пауза нацелилась не туда: {stopped2} (запуск A={run_a}, B={run_b})"
    assert _wait_for(lambda: entry_b.get("_done")), "второй done не пришёл"
    done_b = _done_msg(entry_b)
    assert done_b is not None
    assert done_b["paused"] is True, \
        f"вторая пауза превратилась в остановку: {done_b}"
    assert done_b["stopped"] is False, "stopped не должен быть True у паузы"
    assert done_b["resume"], "после второй паузы нельзя продолжить"
    assert _fallback_child["stop_kinds"] == ["pause", "pause"], \
        f"движок увидел не две паузы: {_fallback_child['stop_kinds']}"


def test_resume_after_second_pause_still_starts(_fallback_child):
    """Цикл из трёх пауз подряд — пауза не «выгорает» после возобновления."""
    client = _client()
    params = {"queries": ["кафе"], "cities": ["Уфа", "Курск"]}
    ids = []
    for cycle in range(3):
        body = dict(params)
        if cycle:
            body["resume"] = True
        d = client.post("/run", json=body).get_json()
        assert d["queued"] is False, f"цикл {cycle}: поиск встал в очередь"
        rid = d["run_id"]
        ids.append(rid)
        entry = run_manager.get(rid)
        assert _wait_for(lambda: len(_fallback_child["starts"]) >= cycle + 1)
        stop = client.post("/stop?pause=1").get_json()
        assert stop["targets"] == [rid], f"цикл {cycle}: {stop}"
        assert _wait_for(lambda: entry.get("_done"))
        done = _done_msg(entry)
        assert done and done["paused"] is True, f"цикл {cycle}: {done}"
        assert done["resume"], f"цикл {cycle}: нет данных для продолжения"
    assert _fallback_child["stop_kinds"] == ["pause"] * 3
    assert len(set(ids)) == 3, "каждое продолжение должно быть новым запуском"


def test_resume_while_the_paused_run_is_still_active(_fallback_child, monkeypatch):
    """«Продолжить» через полсекунды после паузы — старый запуск ещё active.

    finish_run() приходит только через _FINISH_DELAY секунд после done, так
    что реальный пользователь почти всегда попадает именно в это окно: старый
    приостановленный запуск ещё помечен active и перехватывает следующую
    паузу, если его не финализировать (clear_paused_run).
    """
    monkeypatch.setattr(rm, "_FINISH_DELAY", 30)   # старый запуск остаётся active
    client = _client()
    params = {"queries": ["кафе"], "cities": ["Уфа", "Курск"]}

    run_a = client.post("/run", json=params).get_json()["run_id"]
    entry_a = run_manager.get(run_a)
    assert _wait_for(lambda: _fallback_child["starts"])
    assert client.post("/stop?pause=1").get_json()["targets"] == [run_a]
    assert _wait_for(lambda: entry_a.get("_done"))

    run_b = client.post("/run", json=dict(params, resume=True)).get_json()["run_id"]
    assert run_b != run_a
    assert entry_a["active"] is False, "старый запуск остался active"
    assert _wait_for(lambda: len(_fallback_child["starts"]) >= 2)

    stop2 = client.post("/stop?pause=1").get_json()
    assert stop2["targets"] == [run_b], \
        f"пауза досталась и старому запуску: {stop2}"
    entry_b = run_manager.get(run_b)
    assert _wait_for(lambda: entry_b.get("_done"))
    assert _done_msg(entry_b)["paused"] is True
    assert entry_a.get("paused") is True       # уже не «активный», но пауза запомнена


def test_stale_pause_file_does_not_break_the_next_run(_fallback_child):
    """Мусорный .pause от прошлого запуска не должен «паузить» новый."""
    client = _client()
    params = {"queries": ["кафе"], "cities": ["Уфа"]}
    d = client.post("/run", json=params).get_json()
    entry = run_manager.get(d["run_id"])
    assert _wait_for(lambda: _fallback_child["starts"])
    # A leftover signal file that nobody cleaned up (a hard-killed child).
    Path(entry["pause_file"]).write_text("pause")
    assert client.post("/stop?pause=1").get_json()["targets"] == [d["run_id"]]
    assert _wait_for(lambda: entry.get("_done"))
    done = _done_msg(entry)
    assert done and done["paused"] is True
