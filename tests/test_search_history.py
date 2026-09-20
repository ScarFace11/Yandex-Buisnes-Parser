# -*- coding: utf-8 -*-
"""Search history: every mutation must be persisted to disk.

Regression: add/delete/clear assigned the module cache to a LOCAL variable
(missing `global _cache`), so `_save()` kept dumping the stale global —
deletions and «clear» came back after a restart and the file grew without
the MAX_HISTORY_ENTRIES trim ever applying.
"""
import json

import pytest

import search_history as sh


@pytest.fixture()
def hist(tmp_path, monkeypatch):
    """Fresh history module state backed by a temp file."""
    monkeypatch.setattr(sh, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(sh, "HISTORY_FILE", str(tmp_path / ".search_history.json"))
    monkeypatch.setattr(sh, "_cache", None)
    return sh


def _read_file(hist) -> list:
    with open(hist.HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


class TestPersistence:
    def test_add_entry_is_persisted(self, hist):
        hist.add_entry("run-1", ["кафе"], ["Ярославль"], results_count=5)
        data = _read_file(hist)
        assert [e["run_id"] for e in data] == ["run-1"]

    def test_update_entry_is_persisted(self, hist):
        hist.add_entry("run-1", ["кафе"], ["Ярославль"])
        hist.update_entry("run-1", status="stopped", results_count=9)
        data = _read_file(hist)
        assert data[0]["status"] == "stopped"
        assert data[0]["results_count"] == 9

    def test_delete_entry_is_persisted(self, hist):
        hist.add_entry("run-1", ["кафе"], ["Ярославль"])
        hist.add_entry("run-2", ["кафе"], ["Тутаев"])
        assert hist.delete_entry("run-1") is True
        data = _read_file(hist)
        assert [e["run_id"] for e in data] == ["run-2"]

    def test_clear_history_is_persisted(self, hist):
        hist.add_entry("run-1", ["кафе"], ["Ярославль"])
        hist.clear_history()
        assert _read_file(hist) == []
        assert hist.get_history() == []


class TestTrim:
    def test_history_is_trimmed_to_max_entries(self, hist, monkeypatch):
        monkeypatch.setattr(hist, "MAX_HISTORY_ENTRIES", 3)
        for i in range(5):
            hist.add_entry(f"run-{i}", ["кафе"], ["Ярославль"])
        data = _read_file(hist)
        assert [e["run_id"] for e in data] == ["run-4", "run-3", "run-2"]
