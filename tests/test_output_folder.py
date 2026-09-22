"""«Папка для сохранения результатов»: настройка, проверка и раздача модулям.

Что проверяем:
  * по умолчанию всё как было — output/ рядом с данными приложения;
  * пользовательская папка принимает raw/, processed/ и _archive/, а служебные
    файлы (кэш найденного, чекпоинты, история) остаются в папке приложения;
  * расширенный режим: своя папка на каждый этап, пустое поле = общая;
  * ошибки пути (файл вместо папки, несуществующий диск) видны в форме, а не
    всплывают при сохранении результатов;
  * смена папки доезжает до всех модулей, которые запомнили её при импорте;
  * системный диалог выбора папки закрыт заглушкой — тесты его не открывают.
"""
import importlib
import json
import os

import pytest
from flask import Flask

# Модули, которые держат папки результатов в собственных глобальных именах:
# paths.refresh_output_dirs() обязан обновить их все.
_REBIND = {
    "config": ("RESULTS_DIR", "RAW_DIR", "PROCESSED_DIR"),
    "yandex_maps_parser.state": ("RESULTS_DIR", "RAW_DIR", "PROCESSED_DIR"),
    "routes.api": ("RESULTS_DIR",),
    "run_manager": ("RESULTS_DIR",),
    "routes.sender": ("RESULTS_DIR",),
}


@pytest.fixture()
def out_env(tmp_path, monkeypatch):
    """data_dir → tmp: settings.json и папки уходят в песочницу, а после теста
    прежние значения возвращаются, чтобы не ломать соседние тесты."""
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    saved = {}
    for name, attrs in _REBIND.items():
        mod = importlib.import_module(name)
        saved[name] = {a: getattr(mod, a) for a in attrs if hasattr(mod, a)}
    yield tmp_path
    for name, values in saved.items():
        mod = importlib.import_module(name)
        for attr, value in values.items():
            setattr(mod, attr, value)


@pytest.fixture()
def client(out_env):
    from routes import api as api_mod

    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


def _paths():
    import paths
    return paths


# ── paths: папки ───────────────────────────────────────────────
class TestResultsRoot:
    def test_default_is_output_next_to_the_app_data(self, out_env):
        import paths

        assert paths.results_root() == out_env / "output"
        assert paths.default_results_root() == out_env / "output"

    def test_custom_folder_gets_the_three_subfolders(self, out_env):
        import paths

        custom = out_env / "MyData"
        paths.save_settings({"results_root": str(custom)})

        assert paths.results_root() == custom
        assert paths.raw_dir() == str(custom / "raw")
        assert paths.processed_dir() == str(custom / "processed")
        assert paths.archive_root() == str(custom / "_archive")
        assert os.path.isdir(custom / "raw") and os.path.isdir(custom / "processed")

    def test_service_files_stay_in_the_app_folder(self, out_env):
        """Кэш найденного и чекпоинты не переезжают вместе с результатами."""
        import paths

        paths.save_settings({"results_root": str(out_env / "MyData")})

        assert paths.output_dir() == str(out_env / "output")
        assert paths.env_path().parent == out_env

    def test_cyrillic_and_spaces_in_the_path(self, out_env):
        import paths

        custom = out_env / "Мои результаты" / "клиенты 2026"
        paths.save_settings({"results_root": str(custom)})
        os.makedirs(paths.raw_dir(), exist_ok=True)
        probe = os.path.join(paths.raw_dir(), "raw_тест.xlsx")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")

        assert os.path.isfile(probe)

    def test_home_expansion_is_supported(self, out_env, monkeypatch):
        import paths

        monkeypatch.setenv("HOME", str(out_env / "home"))
        monkeypatch.setenv("USERPROFILE", str(out_env / "home"))
        paths.save_settings({"results_root": "~/parsed"})

        assert paths.results_root() == out_env / "home" / "parsed"

    def test_advanced_mode_overrides_a_stage(self, out_env):
        import paths

        paths.save_settings({"results_root": str(out_env / "main"),
                             "raw_dir": str(out_env / "raws")})

        assert paths.raw_dir() == str(out_env / "raws")
        # Остальные этапы остаются внутри общей папки.
        assert paths.processed_dir() == str(out_env / "main" / "processed")
        assert paths.archive_root() == str(out_env / "main" / "_archive")

    def test_empty_setting_means_default(self, out_env):
        import paths

        paths.save_settings({"results_root": ""})
        assert paths.results_root() == out_env / "output"


class TestSettingsFile:
    def test_round_trip_and_merge(self, out_env):
        import paths

        paths.save_settings({"results_root": "D:/one"})
        paths.save_settings({"raw_dir": "D:/two"})

        data = json.loads(paths.settings_path().read_text(encoding="utf-8"))
        assert data == {"results_root": "D:/one", "raw_dir": "D:/two"}

    def test_broken_file_does_not_break_startup(self, out_env):
        import paths

        paths.settings_path().write_text("{не json", encoding="utf-8")
        assert paths.load_settings() == {}
        assert paths.results_root() == out_env / "output"


class TestCheckDir:
    def test_missing_folder_is_created(self, out_env):
        import paths

        target = out_env / "new" / "nested"
        assert paths.check_dir(str(target)) == ""
        assert target.is_dir()

    def test_a_file_instead_of_a_folder_is_an_error(self, out_env):
        import paths

        target = out_env / "file.txt"
        target.write_text("x", encoding="utf-8")
        assert paths.check_dir(str(target)) != ""


class TestRefreshOutputDirs:
    def test_every_module_follows_the_new_folder(self, out_env):
        import paths

        custom = out_env / "Shared"
        paths.save_settings({"results_root": str(custom)})
        dirs = paths.refresh_output_dirs()

        assert dirs["root"] == str(custom)
        for name, attrs in _REBIND.items():
            mod = importlib.import_module(name)
            for attr in attrs:
                if not hasattr(mod, attr):
                    continue          # модуль без этого имени — не беда
                expected = {"RESULTS_DIR": str(custom),
                            "RAW_DIR": str(custom / "raw"),
                            "PROCESSED_DIR": str(custom / "processed")}[attr]
                assert getattr(mod, attr) == expected, f"{name}.{attr}"

    def test_reset_moves_everything_back(self, out_env):
        import paths
        from yandex_maps_parser import state

        paths.save_settings({"results_root": str(out_env / "Shared")})
        paths.refresh_output_dirs()
        paths.save_settings({"results_root": "", "raw_dir": "",
                             "processed_dir": "", "archive_dir": ""})
        paths.refresh_output_dirs()

        assert state.RAW_DIR == str(out_env / "output" / "raw")


# ── /output-dir ────────────────────────────────────────────────
class TestOutputDirRoute:
    def test_get_reports_the_current_folders(self, client, out_env):
        d = client.get("/output-dir").get_json()
        assert d["root"] == str(out_env / "output")
        assert d["custom"] is False and d["advanced"] is False
        assert d["default_root"] == str(out_env / "output")

    def test_post_saves_and_creates_subfolders(self, client, out_env):
        custom = out_env / "Клиенты"
        d = client.post("/output-dir", json={"root": str(custom)}).get_json()

        assert d["ok"] is True
        assert d["root"] == str(custom)
        assert (custom / "raw").is_dir()
        assert (custom / "processed").is_dir()
        assert d["pending"] is False

    def test_post_switches_the_api_to_the_new_folder(self, client, out_env):
        from routes import api as api_mod

        custom = out_env / "Клиенты"
        client.post("/output-dir", json={"root": str(custom)})

        assert api_mod.RESULTS_DIR == str(custom)
        assert api_mod._raw_dir() == str(custom / "raw")

    def test_bad_path_is_rejected_with_a_message(self, client, out_env):
        bad = out_env / "not-a-folder.txt"
        bad.write_text("x", encoding="utf-8")

        resp = client.post("/output-dir", json={"root": str(bad)})
        d = resp.get_json()

        assert resp.status_code == 400
        assert d["ok"] is False
        assert "root" in d["errors"]
        # Настройка не сохранилась — прежний путь остался.
        assert client.get("/output-dir").get_json()["root"] == str(out_env / "output")

    def test_advanced_mode_keeps_per_stage_folders(self, client, out_env):
        d = client.post("/output-dir", json={
            "root": str(out_env / "main"),
            "advanced": True,
            "raw": str(out_env / "raws"),
            "processed": "",
            "archive": "",
        }).get_json()

        assert d["ok"] is True and d["advanced"] is True
        assert d["raw"] == str(out_env / "raws")
        assert d["processed"] == str(out_env / "main" / "processed")

    def test_plain_mode_clears_stage_overrides(self, client, out_env):
        client.post("/output-dir", json={"root": str(out_env / "a"), "advanced": True,
                                         "raw": str(out_env / "raws")})
        d = client.post("/output-dir", json={"root": str(out_env / "b"),
                                             "advanced": False}).get_json()

        assert d["advanced"] is False
        assert d["raw"] == str(out_env / "b" / "raw")

    def test_reset_returns_to_the_default_folder(self, client, out_env):
        client.post("/output-dir", json={"root": str(out_env / "Клиенты")})
        d = client.post("/output-dir", json={"reset": True}).get_json()

        assert d["ok"] is True and d["reset"] is True
        assert d["root"] == str(out_env / "output")

    def test_active_run_is_reported_as_pending(self, client, out_env, monkeypatch):
        from routes import api as api_mod

        monkeypatch.setattr(api_mod, "_run_active", lambda: True)
        d = client.post("/output-dir", json={"root": str(out_env / "Клиенты")}).get_json()

        assert d["pending"] is True, "форма обязана предупредить про следующий город"
        assert d["running"] is True


# ── /folder-picker ─────────────────────────────────────────────
class TestFolderPicker:
    def test_command_is_built_per_platform(self):
        from routes import api as api_mod

        win = api_mod.picker_command("win32")
        assert win[0] == "powershell" and "FolderBrowserDialog" in win[-1]
        mac = api_mod.picker_command("darwin")
        assert mac[0] == "osascript" and "choose folder" in mac[-1]
        assert api_mod.picker_command("linux") is None

    def test_returns_the_chosen_path(self, client, monkeypatch):
        from routes import api as api_mod

        monkeypatch.setattr(api_mod, "picker_command", lambda *_: ["true"])
        monkeypatch.setattr(api_mod, "_run_picker", lambda cmd: "/tmp/chosen")
        d = client.post("/folder-picker").get_json()

        assert d == {"ok": True, "path": "/tmp/chosen"}

    def test_cancelled_dialog_is_not_an_error(self, client, monkeypatch):
        from routes import api as api_mod

        monkeypatch.setattr(api_mod, "picker_command", lambda *_: ["true"])
        monkeypatch.setattr(api_mod, "_run_picker", lambda cmd: "")
        d = client.post("/folder-picker").get_json()

        assert d["ok"] is False and d["cancelled"] is True

    def test_dialog_failure_is_reported(self, client, monkeypatch):
        from routes import api as api_mod

        monkeypatch.setattr(api_mod, "picker_command", lambda *_: ["true"])

        def boom(cmd):
            raise RuntimeError("нет дисплея")

        monkeypatch.setattr(api_mod, "_run_picker", boom)
        resp = client.post("/folder-picker")

        assert resp.status_code == 500
        assert "нет дисплея" in resp.get_json()["error"]

    def test_platform_without_a_dialog_says_so(self, client, monkeypatch):
        from routes import api as api_mod

        monkeypatch.setattr(api_mod, "picker_command", lambda *_: None)
        resp = client.post("/folder-picker")

        assert resp.status_code == 501
        assert "вручную" in resp.get_json()["error"]
