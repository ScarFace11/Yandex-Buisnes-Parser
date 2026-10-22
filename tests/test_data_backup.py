"""Экспорт/импорт данных и автокопия отметок «просмотрено».

Пользовательские данные (`_reviewed.json` — вся работа по разбору, плюс
настройки) переживают переезд между машинами через zip из /data/export.
Автокопия пишется в `output/_backup/` при каждой записи отметок, держит
последние 7 дней и не может отменить саму отметку при сбое.
"""
import io
import json
import zipfile

import pytest
from flask import Flask

from yandex_maps_parser.exporters import save_excel


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask client, направленный в временное дерево output/."""
    from routes import api as api_mod

    root = tmp_path / "output"
    raw = root / "raw"
    for d in (raw,):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(api_mod, "OUTPUT_DIR", str(root))
    monkeypatch.setattr(api_mod, "RESULTS_DIR", str(root))
    monkeypatch.setattr(api_mod, "REVIEWED_FILE", str(root / "_reviewed.json"))

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    c = app.test_client()
    c.dirs = {"root": root, "raw": raw}
    return c


def _rec(name):
    return {"name": name, "city": "Уфа", "query": "кафе",
            "yandex_maps_url": "https://ya.ru/" + name, "address": "ул. 1"}


# ── Автокопия отметок ─────────────────────────────────────────

class TestBackup:
    def test_save_creates_a_daily_copy(self, client, monkeypatch):
        from routes import api as api_mod
        monkeypatch.setattr(api_mod, "_backup_reviewed", api_mod._backup_reviewed)
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})
        bdir = client.dirs["root"] / "_backup"
        files = list(bdir.glob("_reviewed.*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text(encoding="utf-8")) == {
            "https://a": {"reviewed_at": 1.0}}

    def test_second_save_same_day_does_not_duplicate(self, client):
        from routes import api as api_mod
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0},
                                "https://b": {"reviewed_at": 2.0}})
        bdir = client.dirs["root"] / "_backup"
        assert len(list(bdir.glob("_reviewed.*.json"))) == 1

    def test_only_seven_copies_are_kept(self, client):
        from datetime import date, timedelta
        from routes import api as api_mod
        bdir = client.dirs["root"] / "_backup"
        bdir.mkdir(parents=True)
        today = date.today()
        for i in range(12):
            day = today - timedelta(days=i)
            (bdir / f"_reviewed.{day.isoformat()}.json").write_text("{}", encoding="utf-8")
        api_mod._save_reviewed({})
        names = sorted(f.name for f in bdir.glob("_reviewed.*.json"))
        assert len(names) == 7                      # новые 7 (включая сегодняшнюю)
        assert f"_reviewed.{today.isoformat()}.json" in names

    def test_backup_failure_never_breaks_the_mark(self, client, monkeypatch):
        from routes import api as api_mod
        def boom():
            raise OSError("disk full")
        monkeypatch.setattr(api_mod, "_backup_reviewed", boom)
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})
        # Основной файл записан, несмотря на сбой копии.
        assert json.loads(
            (client.dirs["root"] / "_reviewed.json").read_text(encoding="utf-8"))


class TestAtomicSave:
    """Отметки не теряются, если запись оборвалась на середине."""

    def test_failed_write_keeps_the_previous_file(self, client, monkeypatch):
        from routes import api as api_mod
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})

        def boom(obj, fp, **kw):
            fp.write('{"broken":')          # половина файла уже на диске
            raise OSError("disk full")

        monkeypatch.setattr(api_mod.json, "dump", boom)
        with pytest.raises(OSError):
            api_mod._save_reviewed({"https://b": {"reviewed_at": 2.0}})

        root = client.dirs["root"]
        assert json.loads((root / "_reviewed.json").read_text(encoding="utf-8")) == {
            "https://a": {"reviewed_at": 1.0}}
        assert not (root / "_reviewed.json.tmp").exists(), "временный файл убран"

    def test_corrupt_main_falls_back_to_the_previous_version(self, client):
        from routes import api as api_mod
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0},
                                "https://b": {"reviewed_at": 2.0}})
        (client.dirs["root"] / "_reviewed.json").write_text("{broken", encoding="utf-8")
        # Основной файл битый — отметки читаются из прошлой версии, а не как пусто.
        assert api_mod._load_reviewed() == {"https://a": {"reviewed_at": 1.0}}


# ── Экспорт / импорт ──────────────────────────────────────────

class TestDataTransfer:
    def test_export_returns_zip_with_reviewed(self, client):
        from routes import api as api_mod
        api_mod._save_reviewed({"https://a": {"reviewed_at": 1.0}})
        res = client.get("/data/export")
        assert res.status_code == 200
        assert res.headers["Content-Type"].startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(res.data))
        assert "_reviewed.json" in zf.namelist()

    def test_export_works_without_any_files(self, client):
        # settings.json на тестовой машине существует (paths.user_dir());
        # инвариант проще: без отметок в архиве нет _reviewed.json.
        res = client.get("/data/export")
        assert res.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(res.data))
        assert "_reviewed.json" not in zf.namelist()

    def test_import_merges_marks_without_overwriting(self, client):
        from routes import api as api_mod
        api_mod._save_reviewed({
            "https://kept": {"reviewed_at": 100.0},   # сделан ПОСЛЕ экспорта
            "https://same": {"reviewed_at": 300.0},
        })
        archive = {
            "https://same": {"reviewed_at": 1.0},     # старее — не затирает
            "https://new": {"reviewed_at": 2.0},
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("_reviewed.json", json.dumps(archive))
        buf.seek(0)
        res = client.post("/data/import", data={"file": (buf, "x.zip")},
                          content_type="multipart/form-data")
        data = res.get_json()
        assert data["ok"] is True and data["marks"] == 1
        rev = api_mod._load_reviewed()
        assert rev["https://kept"]["reviewed_at"] == 100.0
        assert rev["https://same"]["reviewed_at"] == 300.0, "импорт не сдвигает дату"
        assert rev["https://new"]["reviewed_at"] == 2.0

    def test_import_rejects_non_zip_and_empty(self, client):
        buf = io.BytesIO(b"not a zip")
        res = client.post("/data/import", data={"file": (buf, "x.zip")},
                          content_type="multipart/form-data")
        assert res.status_code == 400
        res = client.post("/data/import", data={},
                          content_type="multipart/form-data")
        assert res.status_code == 400

    def test_import_rejects_archive_without_known_files(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.txt", "hi")
        res = client.post("/data/import", data={"file": (buf, "x.zip")},
                          content_type="multipart/form-data")
        assert res.status_code == 400

    def test_import_rejects_corrupted_reviewed_json(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("_reviewed.json", "{broken")
        res = client.post("/data/import", data={"file": (buf, "x.zip")},
                          content_type="multipart/form-data")
        assert res.status_code == 400

    # ── browser.json: настройки вкладок из «Экспорта настроек» ──

    @staticmethod
    def _zip_with(**files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        buf.seek(0)
        return buf

    def test_import_returns_browser_settings_filtered(self, client):
        """browser.json принимается, но в ответ идут только свои ключи-строки.

        Архив — присланный файл: чужим ключам localStorage не верим даже,
        если их положили в архив руками.
        """
        payload = json.dumps({"yp_theme_v1": "dark", "yp_settings_v1": "{}",
                              "foreign": "нет", "yp_num": 5})
        res = client.post(
            "/data/import",
            data={"file": (self._zip_with(**{"browser.json": payload}), "x.zip")},
            content_type="multipart/form-data")
        data = res.get_json()
        assert data["ok"] is True
        assert data["browser"] == {"yp_theme_v1": "dark", "yp_settings_v1": "{}"}

    def test_import_accepts_archive_of_only_browser_settings(self, client):
        """Если настройки вкладок — единственное содержимое архива, это не мусор."""
        payload = json.dumps({"yp_results_scope": "all"})
        res = client.post(
            "/data/import",
            data={"file": (self._zip_with(**{"browser.json": payload}), "x.zip")},
            content_type="multipart/form-data")
        data = res.get_json()
        assert data["ok"] is True
        assert data["browser"] == {"yp_results_scope": "all"}
        assert data["marks"] == 0 and data["settings"] is False

    def test_import_rejects_corrupted_browser_json(self, client):
        res = client.post(
            "/data/import",
            data={"file": (self._zip_with(**{"browser.json": "{broken"}), "x.zip")},
            content_type="multipart/form-data")
        assert res.status_code == 400
        assert "browser.json" in res.get_json()["error"]

    def test_import_of_unknown_files_is_still_refused(self, client):
        """browser.json не делает архивом файлы без наших данных."""
        res = client.post(
            "/data/import",
            data={"file": (self._zip_with(**{"other.txt": "hi"}), "x.zip")},
            content_type="multipart/form-data")
        assert res.status_code == 400


# ── Короткие пути в логе ──────────────────────────────────────

class TestShortPath:
    def test_results_root_is_cut_with_output_prefix(self, monkeypatch, tmp_path):
        from yandex_maps_parser import state
        monkeypatch.setattr(state, "RESULTS_DIR", str(tmp_path / "output"))
        p = state.short_path(str(tmp_path / "output" / "москва_20261001.xlsx"))
        assert p == "output/москва_20261001.xlsx"

    def test_nested_subdir_uses_forward_slashes(self, monkeypatch, tmp_path):
        from yandex_maps_parser import state
        monkeypatch.setattr(state, "RESULTS_DIR", str(tmp_path / "output"))
        p = state.short_path(str(tmp_path / "output" / "raw" / "raw_file.xlsx"))
        assert p == "output/raw/raw_file.xlsx"

    def test_outside_path_falls_back_to_last_two_segments(self, monkeypatch, tmp_path):
        from yandex_maps_parser import state
        monkeypatch.setattr(state, "RESULTS_DIR", str(tmp_path / "output"))
        p = state.short_path(r"C:\some\other\place\file.xlsx")
        assert p == "place/file.xlsx"

    def test_short_input_returned_as_is(self, monkeypatch):
        from yandex_maps_parser import state
        monkeypatch.setattr(state, "RESULTS_DIR", str("\\\\nonexistent\\root"))
        assert state.short_path("plain.xlsx") == "plain.xlsx"
