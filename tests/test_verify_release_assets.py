# -*- coding: utf-8 -*-
"""Проверка целостности ассетов релиза: «сборка зелёная, а архив битый».

Сценарий, ради которого всё затевалось: сборка отчиталась об успехе, но
пользователь скачивает обрезанный архив, архив прошлой версии или без
macOS-установщика. Ловить это вручную нельзя — ловит скрипт
scripts/verify_release_assets.py, который смотрит на опубликованный релиз
так же, как на него смотрит пользователь.

Сеть в этих тестах не нужна: собираем настоящие zip/dmg нужного вида и
проверяем, что скрипт их распознаёт — и что битые отличает от целых.
"""
import json
import plistlib
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_release_assets as vra  # noqa: E402

VERSION = "2.3.4.1"


# ── Заголовки бинарников ───────────────────────────────────────

def pe_bytes(machine: int = 0x8664) -> bytes:
    """Настоящий заголовок PE-файла: MZ + сигнатура + machine."""
    head = bytearray(b"MZ" + b"\0" * 0x3E)
    struct.pack_into("<I", head, 0x3C, 0x80)
    head += b"\0" * (0x80 - len(head))
    head += b"PE\0\0" + struct.pack("<H", machine)
    return bytes(head)


def macho_bytes(cpu: int = 0x0100000C) -> bytes:
    """Тонкий Mach-O (64-битный) с нужной архитектурой."""
    return struct.pack("<II", 0xFEEDFACF, cpu) + b"\0" * 64


def fat_macho_bytes(cpus=(0x0100000C, 0x01000007)) -> bytes:
    """Universal-бинарник: заголовок fat с двумя архитектурами."""
    out = struct.pack(">II", 0xCAFEBABE, len(cpus))
    for i, cpu in enumerate(cpus):
        out += struct.pack(">iiIII", cpu, 3, 4096 * (i + 1), 4096, 12)
    return out


# ── Сборка настоящих архивов ───────────────────────────────────

def make_app_zip(path: Path, *, kind="windows", version=VERSION, arch="x64",
                 marker=False, js_modules=8, templates=True,
                 compress=zipfile.ZIP_STORED) -> Path:
    """Архив приложения нужного вида (как собирает pyinstaller).

    По умолчанию записи без сжатия (так проще ломать в тестах осознанно);
    compress=ZIP_DEFLATED — как настоящий релизный архив.
    """
    with zipfile.ZipFile(path, "w", compression=compress) as zf:
        if kind == "windows":
            zf.writestr("YandexBusinessParser.exe", pe_bytes(0x8664))
            prefix = "_internal/"
        else:
            zf.writestr(vra.APP_BINARY,
                        macho_bytes(0x0100000C if arch == "arm64" else 0x01000007))
            prefix = "YandexBusinessParser.app/Contents/Resources/"
        zf.writestr(prefix + "static/version.json", json.dumps(
            {"version": version, "min_version": "2.3.4",
             "download_url": "https://example/x.zip"}))
        if templates:
            zf.writestr(prefix + "templates/index.html", "<html></html>")
        for i in range(js_modules):
            zf.writestr(prefix + f"static/js/0{i}-module.js", "// module")
        if marker:
            zf.writestr(prefix + ".local-build", "")
    return path


def make_dmg(path: Path, *, valid=True, fs="Apple_APFS", decoy=False) -> Path:
    """UDIF-образ: plist разделов + трейлер koly в последних 512 байтах.

    Устроен как настоящий .dmg: трейлер koly хранит смещение и длину
    XML-plist с разделами, а внутри сжатых данных лежит посторонний
    plist (decoy=True) — на настоящих образах он тоже есть.
    """
    plist = plistlib.dumps({"resource-fork": {"blkx": [
        {"Name": "Protective Master Boot Record (MBR : 0)"},
        {"Name": f"disk image ({fs} : 4)"},
    ]}})
    body = b"\0" * 1024
    if decoy:
        body += plistlib.dumps({"cdhashes": ["deadbeef"]})
    xml_offset = len(body)
    body += plist
    data = body + b"\0" * 512
    trailer = bytearray(b"koly" + b"\0" * 508)
    struct.pack_into(">qq", trailer, vra.KOLY_DATA_OFFSET, 0, len(body))
    struct.pack_into(">qq", trailer, vra.KOLY_XML_OFFSET, xml_offset, len(plist))
    data += bytes(trailer)
    if not valid:          # обрезанный образ: хвоста koly нет
        data = data[:len(data) - 600]
    path.write_bytes(data)
    return path


# ── Заголовки ──────────────────────────────────────────────────

class TestBinaryHeaders:
    def test_pe_architecture_is_read_from_the_header(self):
        assert vra.pe_arch(pe_bytes(0x8664)) == "x64"
        assert vra.pe_arch(pe_bytes(0x014C)) == "x86"
        assert vra.pe_arch(pe_bytes(0xAA64)) == "arm64"

    def test_a_non_pe_file_has_no_architecture(self):
        assert vra.pe_arch(b"#!/bin/sh\necho hi\n") is None
        assert vra.pe_arch(b"") is None

    def test_macho_architecture_is_read_from_the_header(self):
        assert vra.macho_arches(macho_bytes(0x0100000C)) == {"arm64"}
        assert vra.macho_arches(macho_bytes(0x01000007)) == {"x64"}

    def test_universal_binary_reports_both_architectures(self):
        assert vra.macho_arches(fat_macho_bytes()) == {"arm64", "x64"}

    def test_a_non_macho_file_has_no_architectures(self):
        assert vra.macho_arches(b"\x7fELF\x02\x01\x01" + b"\0" * 32) == set()


# ── Проверка zip ───────────────────────────────────────────────

class TestZipChecks:
    def test_a_whole_archive_has_no_problems(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        assert vra.check_zip_crc(path) == []
        assert vra.check_zip_layout(path, VERSION, "windows", arch="x64") == []

    def test_a_corrupted_archive_is_detected(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        # Портим байт ВНУТРИ данных записи: байт в заголовке CRC не защищает,
        # и такой «битый» файл проходит проверку (так и бывает с обрезкой).
        with zipfile.ZipFile(path) as zf:
            info = max((i for i in zf.infolist() if not i.is_dir()),
                       key=lambda i: i.file_size)
            offset = info.header_offset + 30 + len(info.filename) + len(info.extra)
        raw = bytearray(path.read_bytes())
        assert offset < len(raw)
        raw[offset] ^= 0xFF
        path.write_bytes(bytes(raw))
        problems = vra.check_zip_crc(path)
        assert problems, "битый архив должен ломаться на пересчёте CRC"
        assert any("битая запись" in p for p in problems), problems

    def test_a_truncated_archive_is_detected(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        raw = path.read_bytes()
        path.write_bytes(raw[:len(raw) // 2])
        assert vra.check_zip_crc(path), "обрезанный архив должен ломаться"

    def test_a_corrupted_deflated_archive_is_reported_not_crashed(self, tmp_path):
        """Регресс с реального релиза: в сжатом архиве порча байта роняет
        чтение с zlib.error (не BadZipFile) — проверка обязана вернуть
        проблему, а не уйти в traceback."""
        path = make_app_zip(tmp_path / "win.zip", kind="windows",
                            compress=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(path) as zf:
            info = max((i for i in zf.infolist() if not i.is_dir()),
                       key=lambda i: i.file_size)
            offset = info.header_offset + 30 + len(info.filename) + len(info.extra) + 64
        raw = bytearray(path.read_bytes())
        raw[offset] ^= 0xFF
        path.write_bytes(bytes(raw))
        problems = vra.check_zip_crc(path)
        assert problems, "сжатый битый архив должен ломаться на пересчёте CRC"

    def test_the_version_inside_must_match_the_release(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows", version="2.3.4")
        problems = vra.check_zip_layout(path, VERSION, "windows", arch="x64")
        assert any("2.3.4" in p for p in problems), problems

    def test_the_local_build_marker_is_a_problem(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows", marker=True)
        problems = vra.check_zip_layout(path, VERSION, "windows", arch="x64")
        assert any(".local-build" in p for p in problems), problems

    def test_missing_templates_are_a_problem(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows", templates=False)
        problems = vra.check_zip_layout(path, VERSION, "windows", arch="x64")
        assert any("templates/index.html" in p for p in problems), problems

    def test_a_stripped_bundle_is_a_problem(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows", js_modules=1)
        problems = vra.check_zip_layout(path, VERSION, "windows", arch="x64")
        assert any("static/js" in p for p in problems), problems

    def test_the_macos_binary_must_match_the_architecture_in_the_name(self, tmp_path):
        path = make_app_zip(tmp_path / "mac.zip", kind="macos", arch="x64")
        problems = vra.check_zip_layout(path, VERSION, "macos", arch="arm64")
        assert any("архив называется arm64" in p for p in problems), problems

    def test_the_macos_binary_of_the_right_architecture_passes(self, tmp_path):
        path = make_app_zip(tmp_path / "mac.zip", kind="macos", arch="arm64")
        assert vra.check_zip_layout(path, VERSION, "macos", arch="arm64") == []

    def test_a_universal_binary_satisfies_both_architectures(self, tmp_path):
        path = tmp_path / "mac.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(vra.APP_BINARY, fat_macho_bytes())
            prefix = "YandexBusinessParser.app/Contents/Resources/"
            zf.writestr(prefix + "static/version.json",
                        json.dumps({"version": VERSION}))
            zf.writestr(prefix + "templates/index.html", "<html></html>")
            for i in range(8):
                zf.writestr(prefix + f"static/js/0{i}-module.js", "// module")
        assert vra.check_zip_layout(path, VERSION, "macos", arch="arm64") == []
        assert vra.check_zip_layout(path, VERSION, "macos", arch="x64") == []


# ── Проверка dmg ───────────────────────────────────────────────

class TestDmgChecks:
    @pytest.fixture(autouse=True)
    def _no_platform_hdiutil(self, monkeypatch):
        """Синтетический образ проверяем без hdiutil.

        Тесты собирают крошечный UDIF из заголовка koly и plist, а не
        настоящий том. hdiutil на новых macOS отказывается его открывать
        («image not recognized»), хотя структура для нашей проверки целая.
        Сам вызов hdiutil остаётся в check_dmg и проверяется на реальных
        образах в релизном workflow.
        """
        monkeypatch.setattr(vra, "dmg_hdiutil", lambda path: [])

    def test_hdiutil_problems_reach_the_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vra, "dmg_hdiutil",
                            lambda path: ["hdiutil verify: image not recognized"])
        problems = vra.check_dmg(make_dmg(tmp_path / "a.dmg"))
        assert problems == ["hdiutil verify: image not recognized"]

    def test_a_whole_image_has_no_problems(self, tmp_path):
        assert vra.check_dmg(make_dmg(tmp_path / "a.dmg")) == []

    def test_a_truncated_image_is_detected(self, tmp_path):
        problems = vra.check_dmg(make_dmg(tmp_path / "a.dmg", valid=False))
        assert problems, "обрезанный образ должен ломаться"
        assert any("koly" in p for p in problems), problems

    def test_an_image_without_a_volume_is_detected(self, tmp_path):
        path = tmp_path / "a.dmg"
        plist = plistlib.dumps({"resource-fork": {"blkx": [
            {"Name": "Protective Master Boot Record (MBR : 0)"}]}})
        data = b"\0" * 1024 + plist + b"\0" * 512
        trailer = bytearray(b"koly" + b"\0" * 508)
        struct.pack_into(">qq", trailer, vra.KOLY_DATA_OFFSET, 0, len(data))
        struct.pack_into(">qq", trailer, vra.KOLY_XML_OFFSET, 1024, len(plist))
        path.write_bytes(data + bytes(trailer))
        problems = vra.check_dmg(path)
        assert any("файловой системой" in p for p in problems), problems

    def test_an_empty_file_is_a_problem(self, tmp_path):
        path = tmp_path / "a.dmg"
        path.write_bytes(b"")
        assert vra.check_dmg(path)

    def test_a_decoy_plist_inside_the_image_is_not_the_partition_list(self, tmp_path):
        """Регресс: первый «<?xml» в файле — это посторонний plist внутри
        сжатых данных образа, а не описание разделов. По нему здоровый образ
        объявлялся битым. Настоящий plist лежит по указателю в koly."""
        path = make_dmg(tmp_path / "a.dmg", decoy=True)
        plist = vra.dmg_plist(path)
        assert plist is not None
        assert "resource-fork" in plist, "взяли не тот plist"
        assert vra.check_dmg(path) == []

    def test_a_middle_cut_keeps_the_trailer_but_loses_the_data(self, tmp_path):
        """Файл, у которого хвост цел, а середина вырезана: трейлер на месте,
        но данных в файле меньше, чем он обещает."""
        path = make_dmg(tmp_path / "a.dmg")
        raw = path.read_bytes()
        # Обрезаем глубже, чем обещает koly (data fork кончается на
        # 1024 + len(plist)): файл короче описанного раздела.
        path.write_bytes(raw[:200] + raw[-1024:])
        problems = vra.check_dmg(path)
        assert problems, "образ с вырезанной серединой должен ломаться"
        assert any("обрезан" in p for p in problems), problems

    def test_the_image_must_contain_a_real_filesystem(self, tmp_path):
        path = make_dmg(tmp_path / "a.dmg", fs="Apple_Free")
        problems = vra.check_dmg(path)
        assert any("файловой системой" in p for p in problems), problems


class TestLocalCheck:
    """Режим --check-local: сборщик проверяет файл ДО загрузки на релиз."""

    def test_a_whole_archive_passes(self, tmp_path):
        path = make_app_zip(tmp_path / "YandexBusinessParser-windows-x64.zip",
                            kind="windows")
        assert vra.check_local(path, VERSION) == []

    def test_a_corrupted_archive_fails(self, tmp_path):
        path = make_app_zip(tmp_path / "YandexBusinessParser-windows-x64.zip",
                            kind="windows")
        with zipfile.ZipFile(path) as zf:
            info = max((i for i in zf.infolist() if not i.is_dir()),
                       key=lambda i: i.file_size)
            offset = info.header_offset + 30 + len(info.filename) + len(info.extra)
        raw = bytearray(path.read_bytes())
        raw[offset] ^= 0xFF
        path.write_bytes(bytes(raw))
        assert vra.check_local(path, VERSION)

    def test_the_cli_mode_reports_a_broken_file(self, tmp_path):
        path = tmp_path / "YandexBusinessParser-windows-x64.zip"
        path.write_bytes(b"not a zip at all")
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_release_assets.py"),
             "--check-local", str(path)],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "не прошёл проверку" in res.stdout
        # Причина не должна дублироваться: нечитаемый zip — это одна ошибка.
        assert res.stdout.count("не читается как zip") == 1, res.stdout

    def test_the_cli_mode_passes_a_whole_file(self, tmp_path):
        path = make_app_zip(tmp_path / "YandexBusinessParser-windows-x64.zip",
                            kind="windows")
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_release_assets.py"),
             "--check-local", str(path), "--version", VERSION],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "OK" in res.stdout


# ── CHANGELOG ──────────────────────────────────────────────────

class TestChangelogCheck:
    def test_a_section_of_the_release_version_passes(self, tmp_path):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(f"# Changelog\n\n## [{VERSION}] — Что-то\n\n- Пункт\n",
                        encoding="utf-8")
        assert vra.check_changelog(path, VERSION) == []

    def test_a_changelog_without_the_section_is_a_problem(self, tmp_path):
        path = tmp_path / "CHANGELOG.md"
        path.write_text("# Changelog\n\n## [2.0.0] — Старое\n", encoding="utf-8")
        problems = vra.check_changelog(path, VERSION)
        assert problems and VERSION in problems[0]


# ── Проверка ассета целиком ────────────────────────────────────

class TestVerifyAsset:
    def test_a_size_mismatch_is_reported(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        asset = {"name": "YandexBusinessParser-windows-x64.zip",
                 "size": path.stat().st_size + 100}
        note, problems = vra.verify_asset(path, asset, VERSION)
        assert problems, "размер, отличный от указанного GitHub, — это обрыв"
        assert any("обрезан" in p for p in problems), problems

    def test_a_matching_digest_is_noted(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        asset = {"name": "YandexBusinessParser-windows-x64.zip",
                 "size": path.stat().st_size,
                 "digest": "sha256:" + vra.sha256_file(path)}
        note, problems = vra.verify_asset(path, asset, VERSION)
        assert not problems, problems
        assert "sha256 совпал" in note

    def test_a_wrong_digest_is_reported(self, tmp_path):
        path = make_app_zip(tmp_path / "win.zip", kind="windows")
        asset = {"name": "YandexBusinessParser-windows-x64.zip",
                 "size": path.stat().st_size,
                 "digest": "sha256:" + "0" * 64}
        note, problems = vra.verify_asset(path, asset, VERSION)
        assert any("sha256" in p for p in problems), problems


class TestVerifyRelease:
    """Прогон целиком: сеть подменена, файлы лежат на диске."""

    def _patch(self, monkeypatch, assets):
        def fake_fetch(repo, tag="", token="", timeout=30):
            return {"tag_name": f"v{VERSION}", "draft": False,
                    "html_url": "https://example/rel", "assets": assets}
        monkeypatch.setattr(vra, "fetch_release", fake_fetch)

    def test_a_release_without_the_disk_images_fails(self, monkeypatch, tmp_path):
        """Регресс 2.3.4.1: релиз опубликовался без .dmg — на macOS ставить
        было нечем. Проверка обязана это ловить."""
        zip_path = make_app_zip(tmp_path / "YandexBusinessParser-windows-x64.zip",
                                kind="windows")
        asset = {"name": "YandexBusinessParser-windows-x64.zip",
                 "size": zip_path.stat().st_size}

        def fake_download(asset, dest, token="", timeout=60):
            dest.write_bytes(zip_path.read_bytes())
            return dest.stat().st_size
        monkeypatch.setattr(vra, "download_asset", fake_download)
        self._patch(monkeypatch, [asset])

        code = vra.verify_release("o/r", f"v{VERSION}", report_path=tmp_path / "r.md")
        assert code == 1, "релиз без .dmg не должен проходить проверку"
        report = (tmp_path / "r.md").read_text(encoding="utf-8")
        assert "YandexBusinessParser-macos-arm64.dmg" in report
        assert "YandexBusinessParser-macos-x64.dmg" in report

    def test_a_complete_release_passes(self, monkeypatch, tmp_path):
        names = list(vra.REQUIRED_ASSETS)
        assets = []
        for name in names:
            if name.endswith(".zip"):
                kind = "windows" if "windows" in name else "macos"
                arch = "x64"
                if "macos" in name:
                    arch = "arm64" if "arm64" in name else "x64"
                p = make_app_zip(tmp_path / name, kind=kind, arch=arch)
            elif name.endswith(".dmg"):
                p = make_dmg(tmp_path / name)
            else:
                p = tmp_path / name
                p.write_text(f"# Changelog\n\n## [{VERSION}] — Что-то\n",
                             encoding="utf-8")
            assets.append({"name": name, "size": p.stat().st_size})

        def fake_download(asset, dest, token="", timeout=60):
            src = tmp_path / asset["name"]
            dest.write_bytes(src.read_bytes())
            return dest.stat().st_size
        monkeypatch.setattr(vra, "download_asset", fake_download)
        self._patch(monkeypatch, assets)

        code = vra.verify_release("o/r", f"v{VERSION}", report_path=tmp_path / "r.md")
        assert code == 0, (tmp_path / "r.md").read_text(encoding="utf-8")


# ── Мелкие помощники ───────────────────────────────────────────

def test_strip_tag():
    assert vra.strip_tag("v2.3.4.1") == "2.3.4.1"
    assert vra.strip_tag("2.3.4.1") == "2.3.4.1"


def test_the_required_list_covers_everything_the_builds_produce():
    """Каждый файл, который собирают build-exe.yml и build-macos.yml,
    обязан быть в списке обязательных: иначе релиз опубликуется без него."""
    assert "YandexBusinessParser-windows-x64.zip" in vra.REQUIRED_ASSETS
    assert "YandexBusinessParser-macos-arm64.zip" in vra.REQUIRED_ASSETS
    assert "YandexBusinessParser-macos-x64.zip" in vra.REQUIRED_ASSETS
    assert "YandexBusinessParser-macos-arm64.dmg" in vra.REQUIRED_ASSETS
    assert "YandexBusinessParser-macos-x64.dmg" in vra.REQUIRED_ASSETS
    assert "CHANGELOG.md" in vra.REQUIRED_ASSETS


# ── Разводка workflow ──────────────────────────────────────────

WORKFLOWS = ROOT / ".github" / "workflows"


def read_workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class TestVerifyWorkflow:
    def test_the_workflow_exists(self):
        assert (WORKFLOWS / "verify-release-assets.yml").exists()

    def test_it_runs_after_the_release_is_published(self):
        yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")
        wf = yaml.safe_load(read_workflow("verify-release-assets.yml"))
        triggers = wf.get("on", wf.get(True))
        assert triggers["release"]["types"] == ["published"], (
            "проверка должна идти сразу после публикации — тогда битый архив "
            "не успеет разойтись по пользователям"
        )

    def test_it_also_runs_on_a_schedule(self):
        """Сборку могут перезалить и позже: ежедневная перепроверка ловит и это."""
        yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")
        wf = yaml.safe_load(read_workflow("verify-release-assets.yml"))
        triggers = wf.get("on", wf.get(True))
        assert triggers.get("schedule"), "нужен график перепроверки"

    def test_it_calls_the_script(self):
        text = read_workflow("verify-release-assets.yml")
        assert "scripts/verify_release_assets.py" in text

    def test_it_runs_on_macos_so_hdiutil_can_verify_the_image(self):
        """hdiutil есть только на macOS: без него .dmg проверяется лишь
        «на глаз», а пересчёт контрольных сумм — это и есть целостность."""
        yaml = pytest.importorskip("yaml", reason="workflow-файлы читает pyyaml")
        wf = yaml.safe_load(read_workflow("verify-release-assets.yml"))
        runs_on = wf["jobs"]["verify"]["runs-on"]
        assert "macos" in str(runs_on), runs_on

    def test_publishing_requires_the_macos_disk_images(self):
        """Регресс: релиз 2.3.4.1 опубликовался без .dmg — macOS-установщика
        не было, а публикация прошла. Значит, .dmg обязателен."""
        text = read_workflow("publish-release.yml")
        assert "YandexBusinessParser-macos-arm64.dmg" in text
        assert "YandexBusinessParser-macos-x64.dmg" in text


class TestBuildsVerifyBeforeUpload:
    """«Сборка зелёная, а архив битый» ловится ДО загрузки на релиз."""

    def test_the_windows_build_checks_the_archive(self):
        text = read_workflow("build-exe.yml")
        assert "--check-local" in text, (
            "windows-сборка должна проверять архив до загрузки на релиз"
        )

    def test_the_macos_build_verifies_the_disk_image(self):
        text = read_workflow("build-macos.yml")
        assert "hdiutil verify" in text, (
            "образ .dmg должен проверяться пересчётом контрольных сумм"
        )
        assert "--check-local" in text, "zip тоже проверяется до загрузки"

    def test_the_macos_build_mounts_the_image_and_looks_for_the_app(self):
        """Монтирование показывает, что установщик не пустой: внутри есть
        само приложение, а не только значок."""
        text = read_workflow("build-macos.yml")
        assert "hdiutil attach" in text
        assert "YandexBusinessParser.app/Contents/MacOS/YandexBusinessParser" in text


# ── Живой релиз (сеть; при сбое — пропуск) ─────────────────────

def test_the_published_release_passes_the_check():
    """Скрипт против настоящего опубликованного релиза.

    Сеть в CI бывает недоступна (лимит запросов у общих IP, прокси) — это
    пропуск, а не красный тест: инвариант проверяется, когда ответ пришёл.
    """
    import os

    data = json.loads((ROOT / "static" / "version.json").read_text(encoding="utf-8-sig"))
    version = data.get("version", "")
    if not version:
        pytest.skip("в version.json нет версии")
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_release_assets.py"),
         "--repo", "ScarFace11/Yandex-Buisnes-Parser",
         "--tag", f"v{version}", "--asset", "CHANGELOG.md"],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if res.returncode == 1 and "GitHub API" in (res.stdout + res.stderr):
        pytest.skip("GitHub API недоступен (лимит запросов или сеть)")
    assert res.returncode == 0, res.stdout + res.stderr
