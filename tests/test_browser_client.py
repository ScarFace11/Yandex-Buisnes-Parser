"""Поведение browser_client вокруг автоустановки Playwright.

Главный сценарий: в сборке .exe (sys.frozen) автоустановка запрещена —
модуль bundлится в сборку (parser.spec), поиск не должен скачивать
pip-пакеты в системный Python пользователя «в консоли» во время первого
запуска. Сабпроцесс-тест Chromium в .exe запускает сам exe с
YP_BROWSER_PROBE=1 (см. app._maybe_run_browser_probe).

Плюс отладочное окно cdp_client (отдельный видимый Chrome с CDP):
сценарий «у пользователя нет Chrome» обязан деградировать без исключений.
"""
import os
import sys

import pytest

from yandex_maps_parser import browser_client, cdp_client, state


@pytest.fixture(autouse=True)
def _quiet_and_isolated(monkeypatch):
    """Не писать в общий syslog и не оставлять глобальный кэш статуса."""
    monkeypatch.setattr(state, "syslog", lambda *_: None)
    monkeypatch.setattr(state, "warn", lambda *_: None)
    monkeypatch.setattr(browser_client, "_playwright_mod", None)
    yield
    monkeypatch.setattr(browser_client, "_playwright_mod", None)


class TestAutoInstallGuard:
    def test_frozen_build_never_runs_pip(self, monkeypatch):
        """В .exe автоустановка сразу False и pip не запускается ни разу."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        def _boom(*_a, **_k):
            raise AssertionError("pip/subprocess install must not run in a frozen build")

        monkeypatch.setattr(browser_client.subprocess, "check_call", _boom)
        monkeypatch.setattr(browser_client.subprocess, "run", _boom)

        assert browser_client._auto_install_playwright() is False

    def test_sources_still_auto_install(self, monkeypatch):
        """Из исходников автоустановка остаётся рабочим путём."""
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        calls = []
        monkeypatch.setattr(browser_client.subprocess, "check_call",
                            lambda cmd, **k: calls.append(cmd) or 0)

        assert browser_client._auto_install_playwright() is True
        assert len(calls) == 2  # pip install + playwright install chromium
        assert any("pip" in c for c in calls)
        assert any("playwright" in c and "install" in calls[calls.index(c) + 1]
                   for c in calls)

    def test_init_browser_frozen_goes_straight_to_fallback(self, monkeypatch):
        """init_browser в .exe не пытается ставить playwright, а сразу
        сообщает о fallback — с предупреждением, как из исходников."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(browser_client, "_try_import_playwright", lambda: None)

        installed = {}
        monkeypatch.setattr(browser_client, "_auto_install_playwright",
                            lambda: installed.setdefault("ran", True) or True)

        warns = []
        monkeypatch.setattr(state, "warn", lambda m: warns.append(m))

        assert browser_client.init_browser() is False
        assert "ran" not in installed, "init_browser must not attempt install when frozen"
        assert any("pip install playwright" in m for m in warns), \
            "предупреждение про Chromium теперь и для .exe (модуль в сборке)"


class TestFrozenSubprocessProbe:
    """В .exe `python -c` невозможен: сабпроцесс-тест запускает сам exe
    с YP_BROWSER_PROBE=1 (см. app._maybe_run_browser_probe)."""

    def test_frozen_probe_runs_exe_with_env(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        calls = {}

        class _R:
            returncode = 0
            stderr = b""

        def _run(cmd, capture_output, timeout, **kw):
            calls["cmd"] = cmd
            calls["env"] = kw.get("env", {})
            return _R()

        monkeypatch.setattr(browser_client.subprocess, "run", _run)
        assert browser_client._test_playwright_in_subprocess() is True
        assert calls["cmd"] == [sys.executable], "в .exe запускается сам exe"
        assert calls["env"].get("YP_BROWSER_PROBE") == "1"
        assert calls["env"].get("YP_OPEN_BROWSER") == "0", "probe не должен открывать браузер"

    def test_sources_probe_uses_python_dash_c(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        calls = {}

        class _R:
            returncode = 0
            stderr = b""

        def _run(cmd, capture_output, timeout, **kw):
            calls["cmd"] = cmd
            calls["env"] = kw.get("env")
            return _R()

        monkeypatch.setattr(browser_client.subprocess, "run", _run)
        assert browser_client._test_playwright_in_subprocess() is True
        assert "-c" in calls["cmd"], "из исходников — прежний python -c"
        assert "env" not in calls or not calls["env"], "из исходников env не нужен"

    def test_frozen_probe_crash_reports_exit_code(self, monkeypatch):
        """Крэш 0xC0000005 (3221225477) в probe-режиме — понятное
        предупреждение с кодом, без пустой причины."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)

        class _R:
            returncode = 3221225477
            stderr = b""

        monkeypatch.setattr(browser_client.subprocess, "run",
                            lambda *a, **k: _R())
        warns = []
        monkeypatch.setattr(state, "warn", lambda m: warns.append(m))
        monkeypatch.setattr(state, "syslog", lambda m: None)

        assert browser_client._test_playwright_in_subprocess() is False
        assert any("3221225477" in m for m in warns), \
            "в предупреждении должен быть код крэша"


class _FakeProc:
    """Подмена subprocess.Popen: живой процесс без реального Chrome."""

    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class TestDebugWindow:
    """Отладочное окно Chrome: свой профиль, CDP-порт, деградация без Chrome."""

    def test_no_chrome_returns_none_without_crash(self, monkeypatch):
        """Нет Chrome/Chromium/Edge вообще → None, без исключения и процесса."""
        monkeypatch.setattr(cdp_client, "_find_chrome", lambda: None)

        assert cdp_client.open_debug_window() is None
        assert cdp_client._debug_proc is None
        assert cdp_client.is_installed() is False

    def test_close_without_open_is_noop(self, monkeypatch):
        """close_debug_window() безопасен, если окно не открывалось."""
        monkeypatch.setattr(cdp_client, "_find_chrome", lambda: None)
        cdp_client.close_debug_window()
        cdp_client.close_debug_window()
        assert cdp_client._debug_proc is None

    def test_open_isolated_profile_visible_and_cdp_ready(self, monkeypatch):
        """Окно: свой --user-data-dir (не привязка к запущенному Chrome),
        без --headless, в первом окне start_url, порт CDP отвечает,
        закрытие чистит процесс и профиль."""
        fake = _FakeProc()
        captured: dict = {}

        def _popen(cmd, **_kw):
            captured["cmd"] = list(cmd)
            return fake

        monkeypatch.setattr(cdp_client.subprocess, "Popen", _popen)
        monkeypatch.setattr(cdp_client, "_find_chrome", lambda: "C:/fake/chrome.exe")
        monkeypatch.setattr(cdp_client, "_cdp_get",
                            lambda _port, _path: {"Browser": "Chrome/151"})
        monkeypatch.setattr(cdp_client.time, "sleep", lambda *_: None)

        port = cdp_client.open_debug_window(start_url="http://127.0.0.1:5000/")
        assert port and port > 0
        cmd = captured["cmd"]
        assert any(a.startswith("--user-data-dir=") for a in cmd), \
            "свой временный профиль обязателен"
        assert any(a.startswith(f"--remote-debugging-port={port}") for a in cmd)
        assert "--headless=new" not in cmd, "окно должно быть видимым"
        assert cmd[-1] == "http://127.0.0.1:5000/", \
            "в окне должен открыться интерфейс, а не about:blank"
        profile = cdp_client._debug_profile_dir
        assert profile and os.path.isdir(profile)

        cdp_client.close_debug_window()
        assert cdp_client._debug_proc is None
        assert fake.terminated, "процесс Chrome должен быть закрыт"
        assert not os.path.isdir(profile), "временный профиль должен удалиться"

    def test_init_browser_visible_flag_controls_headless(self, monkeypatch):
        """init_browser(visible=True) не ставит --headless; по умолчанию ставит."""
        captured: list = []

        def _popen(cmd, **_kw):
            captured.append(list(cmd))
            return _FakeProc()

        monkeypatch.setattr(cdp_client.subprocess, "Popen", _popen)
        monkeypatch.setattr(cdp_client, "_find_chrome", lambda: "C:/fake/chrome.exe")
        monkeypatch.setattr(cdp_client, "_cdp_get",
                            lambda _port, _path: {"Browser": "Chrome/151"})
        monkeypatch.setattr(cdp_client, "_create_tab", lambda: None)  # фейк-CDP
        monkeypatch.setattr(cdp_client.time, "sleep", lambda *_: None)

        # Вкладки создаться не могут (CDP фейковый) → False, но флаги уже сняты.
        cdp_client.init_browser(pool_size=2, visible=True)
        assert "--headless=new" not in captured[-1]

        cdp_client.init_browser(pool_size=2)  # headless по умолчанию
        assert "--headless=new" in captured[-1]


class TestBrowserPriority:
    """CDP пробуется первым, Playwright — только запасной вариант.

    Раньше приоритет был обратный: на Python 3.14 / в .exe Playwright
    заведомо падал, и каждый поиск тратил 2-5 с на обрывающуюся попытку.
    """

    @staticmethod
    def _run_web(monkeypatch, cdp_result, pw_result, order):
        import threading
        from yandex_maps_parser import runner

        monkeypatch.setattr(runner, "run", lambda *a, **k: None)
        monkeypatch.setattr(runner, "_init_browser",
                            lambda **_k: order.append("playwright") or pw_result)
        monkeypatch.setattr(cdp_client, "init_browser",
                            lambda **_k: order.append("cdp") or cdp_result)
        params = {"cities": ["Уфа"], "queries": ["кафе"], "source": "yandex"}
        runner.run_web(params, lambda _lv, _m: None,
                       stop_event=threading.Event(), skip_event=None)

    def test_cdp_first_playwright_not_tried(self, monkeypatch):
        """CDP запустился — Playwright даже не пробуем."""
        order = []
        self._run_web(monkeypatch, cdp_result=True, pw_result=False, order=order)
        assert order == ["cdp"], "при работающем CDP Playwright не должен запускаться"

    def test_playwright_fallback_when_cdp_fails(self, monkeypatch):
        """CDP не встал — тогда пробуем Playwright, и только потом httpx."""
        order = []
        self._run_web(monkeypatch, cdp_result=False, pw_result=True, order=order)
        assert order == ["cdp", "playwright"], \
            "без CDP должна следовать попытка Playwright"
