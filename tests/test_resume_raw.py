"""Пауза и продолжение: сырые данные, формулировки и состояние.

Регрессия на «после возобновления поиск не продолжается»: resumed-запуск
фильтровал только СВОЙ кусок raw-данных, а имена raw-файлов имеют точность
до минуты — поэтому ещё и перезаписывали кусок, собранный до паузы. Теперь
сырые файлы копятся за весь запуск, «Продолжить» подхватывает прошлый кусок,
а export_raw_records умеет досыпать записи в существующий файл.
"""
import os
import queue as _queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from yandex_maps_parser import processing, runner, state
from yandex_maps_parser.exporters import save_excel


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RAW_DIR", str(tmp_path / "raw"))
    os.makedirs(state.RAW_DIR, exist_ok=True)
    return state.RAW_DIR


def _rec(name, **extra):
    rec = {"city": "Уфа", "name": name, "query": "кафе", "yandex_maps_url": "https://y/" + name}
    rec.update(extra)
    return rec


# ── export_raw_records ────────────────────────────────────────

class TestExportRawRecords:
    def test_merges_instead_of_overwriting_on_resume(self, raw_dir):
        processing.export_raw_records([_rec("A")], "кафе", "Уфа")
        # Второй запуск в ту же минуту пишет в тот же файл.
        processing.export_raw_records([_rec("B")], "кафе", "Уфа", merge_existing=True)
        names = [r["name"] for r in processing.load_raw_records(
            processing.raw_path("кафе", "Уфа"))]
        assert names == ["A", "B"], "кусок до паузы потерялся"

    def test_same_name_is_not_duplicated_when_merging(self, raw_dir):
        processing.export_raw_records([_rec("A")], "кафе", "Уфа")
        processing.export_raw_records([_rec("A"), _rec("B")], "кафе", "Уфа",
                                      merge_existing=True)
        names = [r["name"] for r in processing.load_raw_records(
            processing.raw_path("кафе", "Уфа"))]
        assert sorted(names) == ["A", "B"]

    def test_fresh_run_still_overwrites(self, raw_dir):
        """Без продолжения поведение прежнее: файл минуты перезаписывается."""
        processing.export_raw_records([_rec("A")], "кафе", "Уфа")
        processing.export_raw_records([_rec("B")], "кафе", "Уфа")
        names = [r["name"] for r in processing.load_raw_records(
            processing.raw_path("кафе", "Уфа"))]
        assert names == ["B"]

    def test_carries_the_website_column(self, raw_dir):
        processing.export_raw_records([_rec("A", website="https://a.ru")], "кафе", "Уфа")
        rec = processing.load_raw_records(processing.raw_path("кафе", "Уфа"))[0]
        assert rec["website"] == "https://a.ru"


# ── raw_files_for ─────────────────────────────────────────────

class TestRawFilesFor:
    def _mk(self, raw_dir, name):
        with open(os.path.join(raw_dir, name), "w", encoding="utf-8") as fh:
            fh.write("x")

    def test_finds_the_slice_of_these_query_city_pairs(self, raw_dir):
        self._mk(raw_dir, "raw_2026-09-19_10-00_кафе_уфа.xlsx")
        self._mk(raw_dir, "raw_2026-09-19_10-05_кафе_казань.xlsx")
        self._mk(raw_dir, "raw_2026-09-19_10-07_бары_уфа.xlsx")
        found = [os.path.basename(p) for p in processing.raw_files_for(["кафе"], ["Уфа"])]
        assert found == ["raw_2026-09-19_10-00_кафе_уфа.xlsx"]

    def test_misses_nothing_for_a_multi_city_run(self, raw_dir):
        self._mk(raw_dir, "raw_2026-09-19_10-00_кафе_уфа.xlsx")
        self._mk(raw_dir, "raw_2026-09-19_10-05_кафе_казань.xlsx")
        found = processing.raw_files_for(["кафе"], ["Уфа", "Казань"])
        assert len(found) == 2

    def test_empty_without_matches(self, raw_dir):
        assert processing.raw_files_for(["кафе"], ["Сочи"]) == []
        assert processing.raw_files_for([], []) == []


# ── run_web wiring ────────────────────────────────────────────

class TestResumeWiring:
    def _run(self, params, monkeypatch, seen, run_stub=None):
        import yandex_maps_parser.processing as proc

        def fake_process_all(raw_files, filters, formats, log_fn=None, cleanup_mode="keep"):
            seen.append(list(raw_files))
            return {"groups": {}, "count": 0, "empty": True}

        monkeypatch.setattr(proc, "process_all", fake_process_all)
        # The crawl itself is out of scope here: только проводка этапа 2.
        monkeypatch.setattr(runner, "run", run_stub or (lambda *a, **k: None))
        monkeypatch.setattr(state, "_LOG_FN", None, raising=False)
        monkeypatch.setattr(state, "_SYSLOG_FN", None, raising=False)
        runner._apply_params(params)
        try:
            runner.run_web(params, None)
        except Exception:
            pass

    def _base(self, **extra):
        params = {"queries": ["кафе"], "cities": ["Уфа"], "pipeline": "raw",
                  "output_excel": True, "parse_mode": "all"}
        params.update(extra)
        return params

    def test_resume_feeds_the_pre_pause_slice_into_stage2(self, raw_dir, monkeypatch):
        with open(os.path.join(raw_dir, "raw_2026-09-19_10-00_кафе_уфа.xlsx"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        seen = []
        self._run(self._base(resume=True), monkeypatch, seen)
        assert seen, "этап 2 не запускался"
        assert any("кафе_уфа" in f for f in seen[0]), \
            f"кусок до паузы не попал в обработку: {seen[0]}"

    def test_fresh_run_does_not_pick_up_old_raw_files(self, raw_dir, monkeypatch):
        with open(os.path.join(raw_dir, "raw_2026-09-19_10-00_кафе_уфа.xlsx"),
                  "w", encoding="utf-8") as fh:
            fh.write("x")
        seen = []
        self._run(self._base(), monkeypatch, seen)
        assert seen
        assert seen[0] == [], "новый поиск не должен тащить прошлые raw-файлы"

    def test_multi_city_slices_are_not_lost(self, raw_dir, monkeypatch):
        """Раньше этап 2 видел только файлы ПОСЛЕДНЕГО города.

        run() вызывается на каждый город и пишет свои raw-файлы — список
        `_RAW_FILES_LAST_RUN` перезаписывался, а этап 2 читал его. Теперь
        файлы копятся в `_RAW_FILES_RUN` за весь запуск.
        """
        seen = []
        written = ["уфа.xlsx", "казань.xlsx"]

        def fake_run():
            state._RAW_FILES_LAST_RUN = [written.pop(0)] if written else []
            state._RAW_FILES_RUN = getattr(state, "_RAW_FILES_RUN", []) + list(state._RAW_FILES_LAST_RUN)

        self._run(self._base(cities=["Уфа", "Казань"]), monkeypatch, seen, run_stub=fake_run)
        assert seen, "этап 2 не запускался"
        assert seen[0] == ["уфа.xlsx", "казань.xlsx"], \
            f"этап 2 потерял часть городов: {seen[0]}"


# ── Слова «пауза» и «остановлено» ─────────────────────────────

class TestPauseWording:
    def test_file_log_summary_says_paused_not_stopped(self, tmp_path, monkeypatch):
        import run_logger as rl

        monkeypatch.setattr(rl, "LOGS_DIR", str(tmp_path))
        log = rl.RunLogger("abcd1234", ["Уфа"], ["кафе"])
        log.finish(3, ["a.xlsx"], stopped=True, paused=True)
        text = Path(log.path).read_text(encoding="utf-8")
        assert "⏸ Поставлен на паузу" in text
        assert "Остановлено пользователем" not in text

    def test_a_real_stop_still_reads_as_stopped(self, tmp_path, monkeypatch):
        import run_logger as rl

        monkeypatch.setattr(rl, "LOGS_DIR", str(tmp_path))
        log = rl.RunLogger("abcd1234", ["Уфа"], ["кафе"])
        log.finish(0, [], stopped=True, paused=False)
        text = Path(log.path).read_text(encoding="utf-8")
        assert "⏹ Остановлено пользователем" in text


# ── /status: пауза переживает перезагрузку страницы ───────────

class TestStatusReportsPaused:
    @pytest.fixture(autouse=True)
    def _isolated_runs(self):
        from run_manager import run_manager
        with run_manager._lock:
            saved = dict(run_manager._runs)
            run_manager._runs.clear()
        yield
        with run_manager._lock:
            run_manager._runs.clear()
            run_manager._runs.update(saved)

    def test_paused_run_travels_with_the_status(self):
        from run_manager import run_manager

        assert run_manager.status()["paused"] is None
        entry = run_manager.new_run()
        entry["params"] = {"queries": ["кафе"], "cities": ["Уфа"]}
        entry["cities"] = ["Уфа"]
        entry["paused"] = True
        entry["active"] = False
        st = run_manager.status()
        assert st["paused"] and st["paused"]["run_id"] == entry["id"]
        assert st["paused"]["resume"]["queries"] == ["кафе"]
        assert st["paused"]["resume"]["all_cities"] == ["Уфа"]

    def test_unpaused_run_is_not_reported_as_paused(self):
        from run_manager import run_manager

        entry = run_manager.new_run()
        entry["params"] = {"queries": ["кафе"], "cities": ["Уфа"]}
        assert run_manager.status()["paused"] is None

    def test_broken_paused_entry_does_not_break_the_status(self, monkeypatch):
        from run_manager import run_manager
        import run_manager as rm

        entry = run_manager.new_run()
        entry["paused"] = True

        def boom(_entry):
            raise RuntimeError("boom")

        monkeypatch.setattr(rm, "_pause_resume_payload", boom)
        st = run_manager.status()
        assert st["paused"] == {"run_id": entry["id"], "resume": None}
