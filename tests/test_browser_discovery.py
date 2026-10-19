# -*- coding: utf-8 -*-
"""Поиск браузера для сбора: подходит любой Chromium, включая Яндекс Браузер.

Приложение открывает страницы по Chrome DevTools Protocol, поэтому «браузер
найден» не может означать «найден любой браузер»: Firefox и Safari CDP не
умеют вовсе. Здесь фиксируется контракт поиска:

* кандидаты собираются по системе: macOS (бандлы /Applications), Windows
  (Яндекс Браузер, Chrome, Edge, Brave, Vivaldi, Opera), Linux (/usr/bin);
* сборки Chromium из кеша Playwright ищутся динамически, самая свежая версия
  первой (раньше путь был захардкожен как `chromium-1234`, которого нет ни у
  кого — отсюда «браузер не найден» у тех, у кого он был);
* в PATH ищутся только Chromium-имена — Firefox/Safari туда не попадают;
* режимы запуска перебираются: новый headless → старый → видимое окно.

Run with: python -m pytest tests/test_browser_discovery.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from yandex_maps_parser import cdp_client as cdp


@pytest.fixture(autouse=True)
def _restore_platform(monkeypatch):
    """Каждый тест выбирает систему сам, остальные настройки возвращаются."""
    yield
    monkeypatch.setattr(cdp, "_PLATFORM", sys.platform, raising=False)


def _paths_for(platform: str, monkeypatch) -> list[tuple[str, str]]:
    """Кандидаты для системы — пути в POSIX-виде, чтобы сравнения читались."""
    monkeypatch.setattr(cdp, "_PLATFORM", platform)
    monkeypatch.setattr(cdp, "_playwright_cache_dirs", lambda: [])
    return [(label, str(path).replace("\\", "/"))
            for label, path in cdp._browser_candidates()]


class TestCandidateDetection:
    def test_macos_offers_yandex_and_other_chromium_browsers(self, monkeypatch):
        """На маке только Safari и Яндекс Браузер — второй обязан находиться."""
        pairs = _paths_for("darwin", monkeypatch)
        joined = " ".join(p for _l, p in pairs)
        assert "/Applications/Yandex.app/Contents/MacOS/Yandex" in joined
        assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in joined
        assert "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" in joined
        assert "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" in joined
        # Ни Safari, ни Firefox через CDP не управляются — их в кандидатах нет.
        assert "Safari.app" not in joined
        assert "Firefox.app" not in joined

    def test_home_applications_is_searched_too(self, monkeypatch):
        pairs = _paths_for("darwin", monkeypatch)
        assert any("Applications/Yandex.app" in p.replace("\\", "/") for _l, p in pairs)

    def test_windows_offers_yandex_browser(self, monkeypatch):
        pairs = _paths_for("win32", monkeypatch)
        joined = " ".join(p.replace("\\", "/") for _l, p in pairs)
        assert "Yandex/YandexBrowser/Application/browser.exe" in joined
        assert "Google/Chrome/Application/chrome.exe" in joined
        assert "Microsoft/Edge/Application/msedge.exe" in joined
        assert "BraveSoftware/Brave-Browser/Application/brave.exe" in joined

    def test_linux_offers_binary_paths(self, monkeypatch):
        joined = " ".join(p for _l, p in _paths_for("linux", monkeypatch))
        assert "/usr/bin/chromium" in joined or "/usr/bin/chromium-browser" in joined

    def test_only_the_current_platform_paths_are_offered(self, monkeypatch):
        """Пути чужих систем не попадают в список (иначе мусор в логе и UI)."""
        assert not [p for _l, p in _paths_for("win32", monkeypatch)
                    if p.startswith("/Applications")]
        assert not [p for _l, p in _paths_for("darwin", monkeypatch)
                    if "YandexBrowser" in p]

    def test_path_names_are_chromium_only(self):
        joined = " ".join(cdp._PATH_BROWSERS)
        assert "firefox" not in joined and "safari" not in joined
        assert "yandex-browser" in joined and "chromium" in joined


class TestPlaywrightCache:
    """Сборки Chromium из кеша Playwright — динамически и по свежести."""

    def _fake_cache(self, tmp_path) -> str:
        for ver, rel in (("1100", "chromium-1100/chrome-linux/chrome"),
                         ("1200", "chromium-1200/chrome-linux/chrome"),
                         ("1300", "chromium_headless_shell-1300/chrome-linux/chrome-headless-shell")):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\n", encoding="utf-8")
        return str(tmp_path)

    def test_newest_version_comes_first(self, tmp_path, monkeypatch):
        self._fake_cache(tmp_path)
        monkeypatch.setattr(cdp, "_playwright_cache_dirs", lambda: [tmp_path])
        found = cdp._playwright_browsers()
        rels = [str(p).replace("\\", "/") for _l, p in found]
        assert len(rels) == 3
        assert "-1300" in rels[0], "самая свежая сборка должна быть первой"
        assert "chromium-1100" in rels[-1]
        assert all(label == "Playwright Chromium" for label, _p in found)

    def test_missing_cache_dir_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cdp, "_playwright_cache_dirs",
                            lambda: [tmp_path / "nope", tmp_path / "also-nope"])
        assert cdp._playwright_browsers() == []


class TestFindBrowser:
    def test_returns_the_first_existing_candidate(self, tmp_path, monkeypatch):
        real = tmp_path / "browser.exe"
        real.write_text("x", encoding="utf-8")
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [
            ("First", tmp_path / "missing.exe"),
            ("Second", real),
        ])
        assert cdp._find_chrome() == str(real)

    def test_falls_back_to_path_lookup(self, monkeypatch):
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [])
        monkeypatch.setattr(cdp.shutil, "which",
                            lambda name: "/usr/bin/yandex-browser" if name == "yandex-browser" else None)
        assert cdp._find_chrome() == "/usr/bin/yandex-browser"

    def test_nothing_found_is_none(self, monkeypatch):
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [])
        monkeypatch.setattr(cdp.shutil, "which", lambda name: None)
        monkeypatch.setattr(cdp, "_non_chromium_browsers", lambda: ["Safari"])
        assert cdp._find_chrome() is None
        info = cdp.browser_info()
        assert info["path"] == "" and info["name"] == ""
        assert info["chromium"] is False
        assert info["unsupported"] == ["Safari"]
        # Список для выбора и ручной выбор пусты — форма не покажет селект.
        assert info["browsers"] == []
        assert info["selected"] == ""

    def test_manually_selected_browser_wins(self, tmp_path, monkeypatch):
        """Выбранный в настройках браузер важнее «первого найденного»."""
        first = tmp_path / "chrome.exe"
        wanted = tmp_path / "yandex.exe"
        first.write_text("x", encoding="utf-8")
        wanted.write_text("x", encoding="utf-8")
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [
            ("Google Chrome", first), ("Яндекс Браузер", wanted),
        ])
        monkeypatch.setattr(cdp, "_configured_browser", str(wanted))
        assert cdp._find_chrome() == str(wanted)
        assert cdp.selected_browser() == str(wanted)

    def test_missing_selected_browser_falls_back(self, tmp_path, monkeypatch):
        """Браузер удалили — сбор не падает, берётся первый существующий."""
        real = tmp_path / "chrome.exe"
        real.write_text("x", encoding="utf-8")
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [("Google Chrome", real)])
        monkeypatch.setattr(cdp, "_configured_browser", str(tmp_path / "gone.exe"))
        assert cdp._find_chrome() == str(real)
        assert cdp.selected_browser() == ""

    def test_available_browsers_lists_only_existing_files(self, tmp_path, monkeypatch):
        real = tmp_path / "YandexBrowser" / "browser.exe"
        real.parent.mkdir(parents=True)
        real.write_text("x", encoding="utf-8")
        missing = tmp_path / "chrome.exe"
        monkeypatch.setattr(cdp, "_browser_candidates", lambda: [
            ("Google Chrome", missing),
            ("Яндекс Браузер", real),
            ("Яндекс Браузер", real),          # дубль пути из другого каталога
        ])
        monkeypatch.setattr(cdp.shutil, "which", lambda name: None)
        listed = cdp.available_browsers()
        assert [b["path"] for b in listed] == [str(real)]
        assert listed[0]["name"] == "Яндекс Браузер"

    def test_browser_name_is_human_readable(self):
        assert cdp._browser_label("/Applications/Yandex.app/Contents/MacOS/Yandex") == "Яндекс Браузер"
        assert cdp._browser_label(r"C:\Users\x\Yandex\YandexBrowser\browser.exe") == "Яндекс Браузер"
        assert cdp._browser_label("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") == "Google Chrome"
        assert cdp._browser_label("/usr/bin/microsoft-edge") == "Microsoft Edge"
        assert cdp._browser_label("/usr/bin/chromium-browser") == "Chromium"
        assert cdp._browser_label("/x/chromium_headless_shell-1200/chrome-headless-shell") == "Chromium (headless)"

    def test_unsupported_browsers_are_reported_only_on_mac(self, monkeypatch):
        monkeypatch.setattr(cdp, "_PLATFORM", "win32")
        assert cdp._non_chromium_browsers() == []
        monkeypatch.setattr(cdp, "_PLATFORM", "darwin")
        monkeypatch.setattr(cdp.Path, "exists", lambda self: "Safari.app" in str(self))
        assert cdp._non_chromium_browsers() == ["Safari"]


class TestHeadlessLadder:
    def test_all_three_modes_are_tried(self):
        """Старые сборки Яндекс Браузера не знают --headless=new: нужен запас."""
        assert cdp._HEADLESS_VARIANTS == ("--headless=new", "--headless", "")

    def test_init_browser_explains_what_to_install(self, monkeypatch):
        """Нет Chromium — говорим, что подойдёт Яндекс Браузер и что не подходит."""
        warned: list[str] = []
        monkeypatch.setattr(cdp, "_find_chrome", lambda: None)
        monkeypatch.setattr(cdp, "browser_info", lambda: {
            "path": "", "name": "", "chromium": False,
            "unsupported": ["Firefox", "Safari"]})
        monkeypatch.setattr(cdp.state, "warn", lambda msg: warned.append(msg))

        assert cdp.init_browser(pool_size=1) is False
        text = " ".join(warned)
        assert "Chromium" in text and "Яндекс Браузер" in text
        assert "Firefox" in text and "Chrome DevTools Protocol" in text
