"""Сборка для macOS: .app-бандл, папка данных, авто-обновление, CI.

Проверяем контракт macOS-версии:
  * данные не пишутся внутрь .app — они в ~/Library/Application Support;
  * данные dev- и публичной сборки не пересекаются;
  * шаблоны/статика находятся внутри бандла (Contents/Frameworks|Resources);
  * браузер открывается только на macOS-сборке (и отключается переменной);
  * авто-обновление изнутри .app не предлагается, но версия проверяется;
  * файлы сборки (spec, скрипт, workflow) и автоматизация GitHub на месте.
"""
import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parent.parent


# ── Папка данных ──────────────────────────────────────────────

class TestDataDir:
    def test_frozen_macos_uses_application_support(self, monkeypatch, tmp_path):
        import paths
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "_is_macos", lambda: True)
        monkeypatch.setattr(paths.sys, "executable",
                            str(tmp_path / "YandexBusinessParser.app" / "Contents"
                                / "MacOS" / "YandexBusinessParser"))
        expected = Path.home() / "Library" / "Application Support" / "YandexBusinessParser"
        assert paths.data_dir() == expected

    def test_dev_bundle_has_its_own_data_folder(self, monkeypatch, tmp_path):
        import paths
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "_is_macos", lambda: True)
        monkeypatch.setattr(paths.sys, "executable",
                            str(tmp_path / "YandexBusinessParserDev.app" / "Contents"
                                / "MacOS" / "YandexBusinessParserDev"))
        d = paths.data_dir()
        assert d.name == "YandexBusinessParserDev"
        assert d != Path.home() / "Library" / "Application Support" / "YandexBusinessParser"

    def test_frozen_elsewhere_stays_next_to_the_bundle(self, monkeypatch, tmp_path):
        """Windows-сборка не изменилась: данные лежат рядом с exe."""
        import paths
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "_is_macos", lambda: False)
        monkeypatch.setattr(paths.sys, "executable",
                            str(tmp_path / "YandexBusinessParser.exe"))
        assert paths.data_dir() == tmp_path

    def test_source_run_uses_the_project_root(self):
        import paths
        assert paths.data_dir() == Path(paths.__file__).resolve().parent

    def test_user_dir_is_created_on_first_launch(self, monkeypatch, tmp_path):
        """Первый запуск не должен падать из-за отсутствующей папки."""
        import paths
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "_is_macos", lambda: False)
        monkeypatch.setattr(paths.sys, "executable",
                            str(tmp_path / "fresh" / "App.exe"))
        d = paths.user_dir()
        assert d.is_dir() and d == tmp_path / "fresh"


# ── Ресурсы внутри бандла ─────────────────────────────────────

class TestResourceDir:
    @staticmethod
    def _bundle(tmp_path, *, in_frameworks, in_resources):
        base = tmp_path / "App.app" / "Contents"
        macos, fw, res = base / "MacOS", base / "Frameworks", base / "Resources"
        for d in (macos, fw, res):
            d.mkdir(parents=True)
        if in_frameworks:
            (fw / "templates").mkdir()
        if in_resources:
            (res / "templates").mkdir()
        return macos

    def test_templates_are_found_in_frameworks(self, monkeypatch, tmp_path):
        import paths
        macos = self._bundle(tmp_path, in_frameworks=True, in_resources=False)
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths.sys, "executable", str(macos / "YandexBusinessParser"))
        monkeypatch.setattr(paths.sys, "_MEIPASS",
                            str(macos.parent / "Frameworks"), raising=False)
        assert paths.resource_dir() == macos.parent / "Frameworks"
        assert (paths.resource_dir() / "templates").is_dir()

    def test_templates_are_found_in_resources(self, monkeypatch, tmp_path):
        """Если PyInstaller положил данные в Contents/Resources — берём их."""
        import paths
        macos = self._bundle(tmp_path, in_frameworks=False, in_resources=True)
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths.sys, "executable", str(macos / "YandexBusinessParser"))
        monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
        assert paths.resource_dir() == macos.parent / "Resources"

    def test_windows_onedir_internal_dir_still_works(self, monkeypatch, tmp_path):
        import paths
        exe_dir = tmp_path / "App"
        (exe_dir / "_internal" / "templates").mkdir(parents=True)
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths.sys, "executable", str(exe_dir / "App.exe"))
        monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)
        assert paths.resource_dir() == exe_dir / "_internal"

    def test_source_run_reads_the_checkout(self, monkeypatch):
        import paths
        monkeypatch.setattr(paths, "is_frozen", lambda: False)
        assert (paths.resource_dir() / "templates" / "index.html").is_file()


# ── Браузер и авто-обновление ─────────────────────────────────

class TestBrowserAutostart:
    def test_only_the_frozen_macos_build_opens_the_browser(self, monkeypatch):
        import app
        monkeypatch.delenv("YP_OPEN_BROWSER", raising=False)
        monkeypatch.setattr(app.sys, "platform", "darwin")
        monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
        assert app._should_open_browser() is True

    def test_windows_build_keeps_the_console_behaviour(self, monkeypatch):
        import app
        monkeypatch.delenv("YP_OPEN_BROWSER", raising=False)
        monkeypatch.setattr(app.sys, "platform", "win32")
        monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
        assert app._should_open_browser() is False

    def test_env_switch_disables_autostart(self, monkeypatch):
        """Нужно смоук-тестам сборки и тому, у кого открыта своя вкладка."""
        import app
        monkeypatch.setattr(app.sys, "platform", "darwin")
        monkeypatch.setattr(app.paths, "is_frozen", lambda: True)
        for value in ("0", "false", "NO"):
            monkeypatch.setenv("YP_OPEN_BROWSER", value)
            assert app._should_open_browser() is False

    def test_source_run_never_steals_the_browser(self, monkeypatch):
        import app
        monkeypatch.delenv("YP_OPEN_BROWSER", raising=False)
        monkeypatch.setattr(app.sys, "platform", "darwin")
        monkeypatch.setattr(app.paths, "is_frozen", lambda: False)
        assert app._should_open_browser() is False


class TestPortFallback:
    """Занятый порт (на macOS это 5000/AirPlay) не должен валить запуск."""

    def test_a_busy_port_is_detected(self):
        import socket
        import app
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            busy = srv.getsockname()[1]
            assert app._port_is_free(busy) is False
            assert app._available_port(busy) not in (busy, None)

    def test_a_free_port_is_kept_as_is(self):
        import socket
        import app
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", 0))
            free = srv.getsockname()[1]
        # порт освобождён
        assert app._port_is_free(free) is True
        assert app._available_port(free) == free


class TestWindowlessStdout:
    """.app запускается без консоли: stdout/stderr могут быть None."""

    def test_streams_are_restored_into_app_log(self, monkeypatch, tmp_path):
        import app
        monkeypatch.setattr(app.sys, "stdout", None)
        monkeypatch.setattr(app.sys, "stderr", None)
        monkeypatch.setattr(app.paths, "user_dir", lambda: tmp_path)
        app._ensure_streams()
        try:
            assert app.sys.stdout is not None
            assert app.sys.stderr is not None
            assert (tmp_path / "app.log").exists()
        finally:
            app.sys.stdout = None      # monkeypatch вернёт настоящее значение
            app.sys.stderr = None

    def test_app_log_is_truncated_when_it_grows(self, monkeypatch, tmp_path):
        import app
        log = tmp_path / "app.log"
        log.write_text("x" * 500, encoding="utf-8")
        monkeypatch.setattr(app.sys, "stdout", None)
        monkeypatch.setattr(app.sys, "stderr", None)
        monkeypatch.setattr(app.paths, "user_dir", lambda: tmp_path)
        app._ensure_streams(max_log_bytes=10)
        try:
            assert "xxxx" not in log.read_text(encoding="utf-8")
        finally:
            app.sys.stdout = None
            app.sys.stderr = None

    def test_real_streams_are_left_untouched(self, monkeypatch):
        import io
        import app
        out, err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(app.sys, "stdout", out)
        monkeypatch.setattr(app.sys, "stderr", err)
        app._ensure_streams()
        assert app.sys.stdout is out and app.sys.stderr is err


@pytest.fixture
def client():
    from routes import update as update_mod
    app = Flask(__name__)
    app.register_blueprint(update_mod.bp)
    return app.test_client()


class TestUpdaterOnMac:
    def test_self_update_is_windows_only(self, monkeypatch):
        from routes import update as update_mod
        monkeypatch.setattr(sys, "platform", "darwin")
        assert update_mod._self_update_supported() is False
        monkeypatch.setattr(sys, "platform", "win32")
        assert update_mod._self_update_supported() is True

    def test_status_reports_auto_apply_false_and_the_platform(self, monkeypatch, client):
        from routes import update as update_mod
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(update_mod, "_is_frozen", lambda: True)
        monkeypatch.setattr(update_mod, "_is_dev", lambda: False)
        monkeypatch.setattr(update_mod, "_remote_meta",
                            lambda: {"version": "9.9.9", "download_url": "https://x/y.zip"})
        d = client.get("/update/status").get_json()
        # Версию проверяем, чтобы баннер «доступна новая версия» работал…
        assert d["newer"] is True
        # …но файлы приложение само не меняет: UI даёт ссылку на релиз.
        assert d["auto_apply"] is False
        assert d["platform"] == "darwin"

    def test_download_and_apply_refuse_instead_of_running_a_bat(
            self, monkeypatch, client, tmp_path):
        from routes import update as update_mod
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(update_mod, "_is_frozen", lambda: True)
        monkeypatch.setattr(update_mod, "_is_dev", lambda: False)
        monkeypatch.setattr(update_mod, "_user_dir", lambda: tmp_path)
        for url in ("/update/download", "/update/apply"):
            r = client.post(url)
            assert r.status_code == 400, url
            body = r.get_json()
            assert body["ok"] is False
            assert "Windows" in body["error"]

    def test_windows_status_still_offers_self_update(self, monkeypatch, client):
        from routes import update as update_mod
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(update_mod, "_is_frozen", lambda: True)
        monkeypatch.setattr(update_mod, "_is_dev", lambda: False)
        monkeypatch.setattr(update_mod, "_remote_meta",
                            lambda: {"version": "9.9.9", "download_url": "https://x/y.zip"})
        assert client.get("/update/status").get_json()["auto_apply"] is True


# ── Файлы сборки и автоматизация ──────────────────────────────

class TestPackagingFiles:
    def test_mac_spec_builds_an_app_bundle(self):
        spec = (ROOT / "parser-mac.spec").read_text(encoding="utf-8")
        assert "BUNDLE(" in spec
        assert "console=False" in spec            # .app без окна терминала
        assert 'os.environ.get("YP_DEV"' in spec
        assert '"YandexBusinessParserDev" if DEV_BUILD else "YandexBusinessParser"' in spec
        assert "YP_ARCH" in spec
        assert "collect_submodules('yandex_maps_parser')" in spec
        assert "'playwright'" in spec             # по-прежнему исключён
        assert "bundle_identifier" in spec

    def test_mac_spec_parses(self):
        import ast
        ast.parse((ROOT / "parser-mac.spec").read_text(encoding="utf-8"))

    def test_local_build_script(self):
        sh = (ROOT / "build-mac.sh").read_text(encoding="utf-8")
        assert "parser-mac.spec" in sh
        assert "--distpath dist-mac" in sh
        assert "codesign" in sh
        assert "xattr -dr com.apple.quarantine" in sh   # подсказка про Gatekeeper
        assert 'YP_DEV=1' in sh

    def test_gitignore_keeps_the_mac_spec_tracked(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "!parser-mac.spec" in gi
        assert "dist-mac/" in gi
        assert "*.dmg" in gi


class TestGithubAutomation:
    def _wf(self, name):
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_pr_gate_runs_tests_on_three_platforms(self):
        wf = self._wf("ci.yml")
        assert "pull_request:" in wf
        for os_name in ("ubuntu-latest", "windows-latest", "macos-latest"):
            assert os_name in wf, os_name
        assert 'node --test "tests/ui/*.test.mjs"' in wf
        assert "parser-mac.spec" in wf          # спеки парсятся в CI

    def test_mac_workflow_builds_both_architectures(self):
        wf = self._wf("build-macos.yml")
        # macos-13 снят с поддержки в декабре 2025: x86_64 только macos-15-intel.
        assert "runner: macos-15" in wf and "runner: macos-15-intel" in wf
        assert "runner: macos-13" not in wf      # образ снят с поддержки
        assert "arm64" in wf and "x86_64" in wf
        assert "MACOSX_DEPLOYMENT_TARGET" in wf     # macOS 11+
        assert "parser-mac.spec" in wf
        assert "codesign --force --deep --sign -" in wf   # ad-hoc остаётся фолбэком
        assert "hdiutil create" in wf            # .dmg
        assert "ditto -c -k" in wf               # .zip с сохранением симлинков
        assert "YP_OPEN_BROWSER=0" in wf         # смоук-тест без браузера
        assert "templates/index.html" in wf or "templates*" in wf

    def test_mac_workflow_signs_and_notarizes_when_secrets_present(self):
        """Полная цепочка Developer ID + нотаризация; без секретов — ad-hoc."""
        wf = self._wf("build-macos.yml")
        # Режим подписи выбирается по наличию секрета с сертификатом.
        assert "secrets.MACOS_CERTIFICATE_P12" in wf
        assert "developer-id" in wf and "adhoc" in wf
        # Подпись: hardened runtime обязателен для нотаризации, entitlements —
        # для загрузчика PyInstaller, timestamp — для доверенной цепочки.
        assert '--options runtime' in wf
        assert '--entitlements entitlements.plist' in wf
        assert '--timestamp' in wf
        # Нотаризация notarytool + пришивание тикета stapler'ом.
        assert "notarytool store-credentials" in wf
        assert "notarytool submit" in wf
        assert "--wait" in wf
        assert "stapler staple" in wf
        assert "stapler validate" in wf
        # Секреты нотаризации пробрасываются в шаг.
        for secret in ("APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID"):
            assert f"secrets.{secret}" in wf, secret
        # Без сертификата сборка не падает: предупреждение в лог CI.
        assert "::warning::" in wf
        # Ветер ad-hoc и Developer ID взаимоисключающие.
        assert wf.count("if: steps.signing.outputs.mode == 'developer-id'") == 1
        assert wf.count("if: steps.signing.outputs.mode == 'adhoc'") == 1

    def test_mac_spec_reads_signing_from_env(self):
        """spec нейтрален: identity/entitlements приходят из окружения."""
        spec = (ROOT / "parser-mac.spec").read_text(encoding="utf-8")
        assert 'YP_CODESIGN_IDENTITY' in spec
        assert 'YP_ENTITLEMENTS' in spec
        assert "codesign_identity=CODESIGN_IDENTITY" in spec
        assert "entitlements_file=ENTITLEMENTS" in spec

    def test_entitlements_plist_covers_pyi_loader(self):
        """Без этих entitlements подписанный PyInstaller-бандл падает при старте."""
        pl = (ROOT / "entitlements.plist").read_text(encoding="utf-8")
        for key in (
            "com.apple.security.cs.allow-jit",
            "com.apple.security.cs.allow-unsigned-executable-memory",
            "com.apple.security.cs.allow-dyld-environment-variables",
            "com.apple.security.cs.disable-library-validation",
        ):
            assert key in pl, key
        # XML валиден.
        import xml.etree.ElementTree as ET
        ET.parse(ROOT / "entitlements.plist")

    def test_build_mac_script_supports_developer_id(self):
        sh = (ROOT / "build-mac.sh").read_text(encoding="utf-8")
        assert "YP_CODESIGN_IDENTITY" in sh
        assert "--options runtime" in sh
        assert "notarytool submit" in sh
        assert "stapler staple" in sh
        # Ad-hoc фолбэк остался.
        assert "codesign --force --deep --sign -" in sh

    def test_mac_workflow_does_not_race_for_the_release(self):
        """Релиз создаёт Windows-workflow; macOS только доливает файлы."""
        wf = self._wf("build-macos.yml")
        assert "gh release upload" in wf
        assert "gh-release" not in wf            # не создаём второй релиз
        assert "gh release view" in wf           # и ждём появления релиза

    def test_mac_workflow_builds_a_dev_bundle_too(self):
        wf = self._wf("build-macos.yml")
        assert "refs/heads/dev" in wf
        assert "inputs.dev" in wf
        assert "5010" in wf                      # dev-порт в смоук-тесте

    def test_dependabot_covers_pip_and_actions(self):
        cfg = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        assert "package-ecosystem: pip" in cfg
        assert "package-ecosystem: github-actions" in cfg
        assert "groups:" in cfg                  # мелкие обновления одним PR

    def test_existing_release_pipeline_still_guards_dev_versions(self):
        wf = self._wf("build-exe.yml")
        assert "config.is_dev_build()" in wf
        assert "YandexBusinessParser-windows-x64.zip" in wf
