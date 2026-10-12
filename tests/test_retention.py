"""Retention: автоудаление сохранённых результатов через N дней (7/14/30/своё)."""
import os
import time


def _root(tmp_path, monkeypatch):
    import paths
    root = tmp_path / "output"
    root.mkdir()
    monkeypatch.setattr(paths, "results_root", lambda: root)
    return root


def test_clamp_bounds():
    import retention
    assert retention._clamp(5) == 5
    assert retention._clamp(0) == retention.MIN_DAYS
    assert retention._clamp(-3) == retention.MIN_DAYS
    assert retention._clamp(100) == retention.MAX_DAYS
    assert retention._clamp("abc") == retention.DEFAULT_DAYS
    assert retention._clamp(None) == retention.DEFAULT_DAYS


def test_cleanup_deletes_old_keeps_recent_and_service(tmp_path, monkeypatch):
    import retention
    root = _root(tmp_path, monkeypatch)

    old = root / "old.xlsx"
    new = root / "new.xlsx"
    old.write_text("x")
    new.write_text("x")
    stamp = time.time() - 40 * 86400
    os.utime(old, (stamp, stamp))

    # Служебные файлы (кэш, история, чекпоинты) начинаются с «.»/«_» или
    # имеют служебный суффикс — очистка их не трогает.
    (root / "_seen.json").write_text("{}")
    (root / ".search_history.json").write_text("[]")
    (root / "run.checkpoint.json").write_text("{}")
    (root / "log.jsonl").write_text("")

    removed = retention.cleanup_old_results(30)
    assert removed == 1
    assert not old.exists()
    assert new.exists()
    assert (root / "_seen.json").exists()
    assert (root / ".search_history.json").exists()
    assert (root / "run.checkpoint.json").exists()
    assert (root / "log.jsonl").exists()


def test_cleanup_walks_nested_result_dirs(tmp_path, monkeypatch):
    import retention
    root = _root(tmp_path, monkeypatch)
    sub = root / "processed" / "excel"
    sub.mkdir(parents=True)
    f = sub / "report.xlsx"
    f.write_text("x")
    stamp = time.time() - 10 * 86400
    os.utime(f, (stamp, stamp))
    assert retention.cleanup_old_results(7) == 1
    assert not f.exists()


def test_retention_setting_roundtrip(tmp_path, monkeypatch):
    import paths
    import retention
    _root(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "load_settings", lambda: {})
    saved = {}
    monkeypatch.setattr(paths, "save_settings", lambda v: saved.update(v))
    assert retention.set_retention_days(100) == 30   # ограничение максимума
    assert saved[retention.RETENTION_KEY] == 30
    assert retention.set_retention_days(7) == 7
    assert saved[retention.RETENTION_KEY] == 7
