#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка целостности ассетов релиза и локальных сборок. python scripts/verify_release_assets.py --tag v2.3.4.1 python scripts/verify_release_assets.py --check-local dist/app.zip --version 2.3.4.1 Код возврата: 0 — всё цело, 1 — есть проблемы."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:  # requests есть в requirements.txt
    import requests
except ImportError:  # pragma: no cover
    requests = None

# Обязательные ассеты релиза — ровно то, что собирают build-exe.yml и build-macos.yml.
REQUIRED_ASSETS = (
    "YandexBusinessParser-windows-x64.zip",
    "YandexBusinessParser-macos-arm64.zip",
    "YandexBusinessParser-macos-x64.zip",
    "YandexBusinessParser-macos-arm64.dmg",
    "YandexBusinessParser-macos-x64.dmg",
    "CHANGELOG.md",
)

# Ожидаемые файлы внутри архива приложения.
APP_EXE = "YandexBusinessParser.exe"
APP_BINARY = "YandexBusinessParser.app/Contents/MacOS/YandexBusinessParser"
MIN_JS_MODULES = 5  # в бандле десятки модулей, а не единицы

# Трейлер UDIF: последние 512 байт, 'koly' и смещения data fork / XML-plist.
KOLY_SIZE = 512
KOLY_DATA_OFFSET = 0x18
KOLY_DATA_LENGTH = 0x20
KOLY_XML_OFFSET = 0xD8
KOLY_XML_LENGTH = 0xE0

# Файловые системы внутри образа: отличают установщик от «гигабайта нулей».
DMG_FILESYSTEMS = ("Apple_APFS", "Apple_HFS", "Apple_CoreStorage")

# Сколько байт хвоста смотреть в поисках plist разделов, если koly нечитаем.
DMG_TAIL_BYTES = 4 << 20

# Архитектуры из заголовков PE/Mach-O.
PE_MACHINES = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}
MACHO_CPUS = {
    0x00000007: "x86",
    0x01000007: "x64",
    0x0000000C: "arm",
    0x0100000C: "arm64",
}


def strip_tag(tag: str) -> str:
    """Убрать ведущую «v» из тега: `v2.3.4.1` → `2.3.4.1`."""
    tag = str(tag or "").strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag


def repo_slug() -> str:
    """owner/name репозитория из CI или значение по умолчанию."""
    return os.environ.get("GITHUB_REPOSITORY", "ScarFace11/Yandex-Buisnes-Parser")


def pe_arch(head: bytes) -> str | None:
    """Архитектура PE-файла (.exe) по заголовку или None."""
    if len(head) < 0x40 or not head.startswith(b"MZ"):
        return None
    offset = struct.unpack_from("<I", head, 0x3C)[0]
    if offset + 6 > len(head) or head[offset:offset + 4] != b"PE\0\0":
        return None
    machine = struct.unpack_from("<H", head, offset + 4)[0]
    return PE_MACHINES.get(machine, f"0x{machine:04x}")


def macho_arches(head: bytes) -> set:
    """Архитектуры Mach-O (тонкий или universal); пусто — это не Mach-O."""
    if len(head) < 8:
        return set()
    thin = struct.unpack_from("<I", head, 0)[0]
    if thin in (0xFEEDFACE, 0xFEEDFACF):  # MH_MAGIC / MH_MAGIC_64
        cpu = struct.unpack_from("<I", head, 4)[0]
        return {MACHO_CPUS.get(cpu, f"cpu=0x{cpu:x}")}
    fat = struct.unpack_from(">I", head, 0)[0]
    if fat in (0xCAFEBABE, 0xCAFEBABF, 0xBEBAFECA, 0xBFBAFECA):
        count = struct.unpack_from(">I", head, 4)[0]
        arches = set()
        for i in range(min(count, 32)):
            off = 8 + i * 20
            if off + 4 > len(head):
                break
            cpu = struct.unpack_from(">I", head, off)[0]
            arches.add(MACHO_CPUS.get(cpu, f"cpu=0x{cpu:x}"))
        return arches
    return set()


def api_get(url: str, token: str = "", timeout: int = 30):
    """GET к GitHub API."""
    if requests is None:
        raise RuntimeError("нужен пакет requests (pip install -r requirements.txt)")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API вернул {resp.status_code} на {url}: {resp.text[:200]}")
    return resp.json()


def fetch_release(repo: str, tag: str = "", token: str = "", timeout: int = 30) -> dict:
    """Релиз по тегу или последний опубликованный."""
    base = f"https://api.github.com/repos/{repo.strip('/')}/releases"
    if tag:
        data = api_get(f"{base}/tags/{tag.strip()}", token, timeout)
    else:
        data = api_get(f"{base}/latest", token, timeout)
    data.setdefault("assets", [])
    return data


def download_asset(asset: dict, dest: Path, token: str = "", timeout: int = 60) -> int:
    """Скачать ассет на диск и вернуть число байт."""
    if requests is None:
        raise RuntimeError("нужен пакет requests (pip install -r requirements.txt)")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = asset.get("browser_download_url") or asset.get("url")
    if not asset.get("browser_download_url"):
        headers["Accept"] = "application/octet-stream"  # иначе API отдаёт JSON
    with requests.get(url, headers=headers, stream=True, timeout=timeout) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"скачивание {asset.get('name')} вернуло {resp.status_code}")
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
    return dest.stat().st_size


def sha256_file(path: Path) -> str:
    """sha256 файла."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_version_json(zf: zipfile.ZipFile, names: list) -> tuple:
    """Данные static/version.json и его имя в архиве."""
    candidates = [n for n in names if n.endswith("static/version.json")]
    if not candidates:
        return None, ""
    try:
        raw = zf.read(candidates[0]).decode("utf-8-sig")
        return json.loads(raw), candidates[0]
    except Exception:
        return None, candidates[0]


def check_version_json(data, version: str, problems: list) -> None:
    """Проверить версию внутри архива и непротиворечивость min_version."""
    if data is None:
        problems.append("внутри нет разбираемого static/version.json")
        return
    inner = str(data.get("version", ""))
    if version and inner != version:
        problems.append(f"внутри версия {inner or '—'}, а релиз {version}")
    minimum = str(data.get("min_version", ""))
    if minimum and _ver_tuple(minimum) > _ver_tuple(inner or version):
        problems.append(f"внутри min_version {minimum} выше версии {inner or version}")


def _ver_tuple(text: str) -> tuple:
    """Версия в виде кортежа чисел."""
    return tuple(int(x) for x in str(text).split(".") if x.isdigit())


def check_zip_crc(path: Path) -> list:
    """Пересчитать CRC всех записей — ловит порчу и обрезку архива."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
    except zipfile.BadZipFile as exc:
        return [f"файл не читается как zip: {exc}"]
    except Exception as exc:  # битый deflate роняет чтение с zlib.error
        return [f"архив повреждён: {type(exc).__name__}: {exc}"]
    return [f"битая запись в архиве: {bad}"] if bad else []


def _read_entry_head(zf: zipfile.ZipFile, name: str, size: int = 0x10000) -> bytes:
    """Прочитать начало записи; пусто — запись битая (CRC уже сообщил)."""
    try:
        with zf.open(name) as fh:
            return fh.read(size)
    except Exception:
        return b""


def check_zip_layout(path: Path, version: str, kind: str, arch: str = "") -> list:
    """Проверить состав архива, версию внутри и архитектуру бинарника."""
    problems: list = []
    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        return [f"файл не читается как zip: {exc}"]
    with zf:
        names = zf.namelist()
        data, _ = read_version_json(zf, names)
        check_version_json(data, version, problems)

        if not any(n.endswith("templates/index.html") for n in names):
            problems.append("внутри нет templates/index.html")

        js = [n for n in names if "/static/js/" in n and n.endswith(".js")]
        if len(js) < MIN_JS_MODULES:
            problems.append(f"внутри {len(js)} модулей static/js (ожидалось не меньше {MIN_JS_MODULES})")

        if any(n.endswith(".local-build") for n in names):
            problems.append("внутри осталась метка .local-build — сборка не подчиняется порогу версии")

        if kind == "windows" and APP_EXE in names:
            head = _read_entry_head(zf, APP_EXE)  # PE-заголовок — начало файла
            if head:
                machine = pe_arch(head)
                if not machine:
                    problems.append(f"{APP_EXE} не похож на PE-файл")
                elif machine != arch:
                    problems.append(f"внутри {APP_EXE} собран под {machine}, а архив называется {arch}")
        elif kind == "macos" and APP_BINARY in names:
            head = _read_entry_head(zf, APP_BINARY)
            if head:
                arches = macho_arches(head)
                if not arches:
                    problems.append(f"{APP_BINARY} не Mach-O — архитектуру проверить не удалось")
                elif arch not in arches:
                    problems.append(f"внутри {sorted(arches)}, а архив называется {arch}")
        elif kind == "windows":
            problems.append(f"внутри нет {APP_EXE}")
        elif kind == "macos":
            problems.append(f"внутри нет {APP_BINARY}")
    return problems


def dmg_koly(path: Path) -> dict | None:
    """Разобрать трейлер koly; None — это не UDIF-образ."""
    size = path.stat().st_size
    if size < KOLY_SIZE:
        return None
    with open(path, "rb") as fh:
        fh.seek(-KOLY_SIZE, os.SEEK_END)
        tail = fh.read(KOLY_SIZE)
    if tail[:4] != b"koly":
        return None
    data_off, data_len = struct.unpack_from(">qq", tail, KOLY_DATA_OFFSET)
    xml_off, xml_len = struct.unpack_from(">qq", tail, KOLY_XML_OFFSET)
    return {
        "data_offset": data_off,
        "data_length": data_len,
        "xml_offset": xml_off,
        "xml_length": xml_len,
        "file_size": size,
    }


def _xml_candidates(path: Path) -> list:
    """Кандидаты (смещение, длина) XML-plist в хвосте образа."""
    size = path.stat().st_size
    window = min(size, DMG_TAIL_BYTES)
    with open(path, "rb") as fh:
        fh.seek(size - window)
        tail = fh.read()
    out: list = []
    pos = tail.find(b"<?xml")
    while pos != -1:
        end = tail.find(b"</plist>", pos)
        if end != -1:
            out.append((size - window + pos, end + len(b"</plist>") - (size - window + pos)))
        pos = tail.find(b"<?xml", pos + 1)
    return out


def dmg_plist(path: Path) -> dict | None:
    """Plist разделов образа: по указателю koly, затем перебор кандидатов."""
    koly = dmg_koly(path)
    candidates: list = []
    if koly:
        off, length = koly["xml_offset"], koly["xml_length"]
        if length > 0 and 0 <= off <= koly["file_size"] - length:
            candidates.append((off, length))
    candidates.extend(_xml_candidates(path))

    for off, length in candidates:
        try:
            with open(path, "rb") as fh:
                fh.seek(off)
                raw = fh.read(length)
            plist = plistlib.loads(raw)
        except Exception:
            continue
        if isinstance(plist, dict) and "resource-fork" in plist:
            return plist
    return None


def dmg_hdiutil(path: Path) -> list:
    """hdiutil verify — эталонная проверка образа (только macOS)."""
    exe = shutil.which("hdiutil")
    if not exe:
        return []
    try:
        res = subprocess.run([exe, "verify", str(path)],
                             capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return [f"hdiutil verify не отработал: {exc}"]
    if res.returncode != 0:
        lines = (res.stderr or res.stdout or "").strip().splitlines()
        return [f"hdiutil verify: {lines[-1] if lines else 'образ не прошёл проверку'}"]
    return []


def check_dmg(path: Path) -> list:
    """Проверить целостность UDIF-образа и наличие раздела с файловой системой."""
    problems: list = []
    size = path.stat().st_size
    if size < KOLY_SIZE:
        return [f"образ пустой ({size} байт)"]

    koly = dmg_koly(path)
    if koly is None:
        return ["это не образ UDIF: нет трейлера koly (файл обрезан или не dmg)"]

    data_end = koly["data_offset"] + koly["data_length"]
    if koly["data_length"] <= 0 or data_end > size:
        problems.append(f"data fork образа обрезан (нужно {data_end} байт, есть {size})")
    xml_end = koly["xml_offset"] + koly["xml_length"]
    if koly["xml_length"] <= 0 or xml_end > size:
        problems.append(f"описание разделов обрезано (нужно {xml_end} байт, есть {size})")

    plist = dmg_plist(path)
    if plist is None:
        problems.append("в образе нет разбираемого plist-описания разделов")
        return problems
    blkx = (plist.get("resource-fork") or {}).get("blkx") or []
    if not blkx:
        problems.append("plist не содержит ни одного раздела")
        return problems
    if not any(fs in (b.get("Name") or "") for b in blkx for fs in DMG_FILESYSTEMS):
        names = ", ".join((b.get("Name") or "?") for b in blkx)
        problems.append(f"в образе нет раздела с файловой системой: {names}")
    problems.extend(dmg_hdiutil(path))
    return problems


def check_changelog(path: Path, version: str) -> list:
    """Проверить, что в CHANGELOG есть раздел текущей версии."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        return [f"не читается: {exc}"]
    if not re.search(rf"^##\s*\[{re.escape(version)}\]", text, re.M):
        return [f"в CHANGELOG нет раздела [{version}]"]
    return []


def verify_asset(path: Path, asset: dict, version: str) -> tuple:
    """Проверить один скачанный ассет: (описание, список проблем)."""
    name = asset.get("name", "")
    problems: list = []
    notes: list = []

    expected = asset.get("size")
    actual = path.stat().st_size
    if expected is not None and int(expected) != actual:
        problems.append(f"размер {actual} байт, а GitHub сообщает {expected} — файл обрезан")

    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        want = digest.split(":", 1)[1].strip().lower()
        got = sha256_file(path)
        if got != want:
            problems.append(f"sha256 не совпал: {got[:16]}… вместо {want[:16]}…")
        else:
            notes.append("sha256 совпал")
    else:
        notes.append("у ассета нет digest в API — сверка хеша пропущена")

    if name.endswith(".zip"):
        problems.extend(check_zip_crc(path))
        if not any(p.startswith("файл не читается как zip") for p in problems):
            if "windows" in name:
                problems.extend(check_zip_layout(path, version, "windows", arch="x64"))
            elif "macos" in name:
                arch = "arm64" if "arm64" in name else "x64"
                problems.extend(check_zip_layout(path, version, "macos", arch=arch))
        notes.append("zip разобран")
    elif name.endswith(".dmg"):
        problems.extend(check_dmg(path))
        notes.append("образ проверен")
    elif name.upper() == "CHANGELOG.MD":
        problems.extend(check_changelog(path, version))
        notes.append("раздел версии на месте")

    return ", ".join(notes), problems


def check_local(path: Path, version: str = "") -> list:
    """Проверить локальный файл сборки до загрузки на релиз."""
    name = path.name
    if name.endswith(".zip"):
        problems = check_zip_crc(path)
        if not any(p.startswith("файл не читается как zip") for p in problems):
            if "windows" in name:
                problems.extend(check_zip_layout(path, version, "windows", arch="x64"))
            elif "macos" in name:
                arch = "arm64" if "arm64" in name else "x64"
                problems.extend(check_zip_layout(path, version, "macos", arch=arch))
        return problems
    if name.endswith(".dmg"):
        return check_dmg(path)
    return [f"не знаю, как проверять «{name}»"]


def verify_release(repo: str, tag: str = "", token: str = "", only: str = "",
                   timeout: int = 30, keep: bool = False,
                   report_path: Path | None = None) -> int:
    """Проверить ассеты релиза; 0 — целы, 1 — есть проблемы."""
    release = fetch_release(repo, tag, token, timeout)
    release_tag = release.get("tag_name") or tag
    version = strip_tag(release_tag)
    assets = release.get("assets") or []

    if release.get("draft"):
        print(f"::error::релиз {release_tag} — черновик: его ещё не видят пользователи")
        return 1

    names = [a.get("name", "") for a in assets]
    missing = [n for n in REQUIRED_ASSETS if n not in names]
    if missing:
        print("::error::на релизе нет: " + ", ".join(missing))

    selected = [a for a in assets if not only or fnmatch.fnmatch(a.get("name", ""), only)]
    if only and not selected:
        print(f"::error::не нашлось ассетов по маске {only!r}")
        return 1

    lines = []
    broken = 0
    workdir = Path(tempfile.mkdtemp(prefix="release-check-"))
    try:
        for asset in selected:
            name = asset.get("name", "")
            dest = workdir / name
            try:
                download_asset(asset, dest, token, timeout=max(timeout, 120))
            except Exception as exc:
                broken += 1
                lines.append((name, False, f"НЕ ПРОВЕРЕН — скачивание не удалось: {exc}", []))
                print(f"::error::{name}: скачивание не удалось: {exc}")
                continue
            note, problems = verify_asset(dest, asset, version)
            if problems:
                broken += 1
                lines.append((name, False, note, problems))
                for p in problems:
                    print(f"::error::{name}: {p}")
            else:
                lines.append((name, True, note, []))
    finally:
        if keep:
            print(f"Скачанные файлы оставлены в {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    ok = broken == 0 and not missing
    _print_report(release, lines, missing, ok)
    if report_path:
        _write_report(report_path, release, lines, missing, ok)
    return 0 if ok else 1


def _print_report(release: dict, lines: list, missing: list, ok: bool) -> None:
    """Напечатать отчёт в консоль."""
    print()
    print(f"=== Проверка ассетов релиза {release.get('tag_name')} ===")
    print(f"Релиз: {release.get('html_url')}")
    for name, good, note, problems in lines:
        print(f"[{'OK  ' if good else 'FAIL'}] {name} — {note}")
        for p in problems:
            print(f"         · {p}")
    if missing:
        print(f"[FAIL] отсутствуют на релизе: {', '.join(missing)}")
    good = sum(1 for _, g, _, _ in lines if g)
    print(f"ИТОГ: {good} из {len(lines)} проверенных ассетов целы"
          + (f"; отсутствуют: {', '.join(missing)}" if missing else ""))
    print("РЕЗУЛЬТАТ: " + ("всё цело" if ok else "есть проблемы"))


def _write_report(path: Path, release: dict, lines: list, missing: list, ok: bool) -> None:
    """Записать markdown-отчёт."""
    out = [f"# Проверка ассетов {release.get('tag_name')}", "",
           f"Релиз: {release.get('html_url')}", ""]
    for name, good, note, problems in lines:
        out.append(f"- {'✅' if good else '❌'} **{name}** — {note}")
        for p in problems:
            out.append(f"  - {p}")
    if missing:
        out += ["", "**Отсутствуют на релизе:** " + ", ".join(missing)]
    out += ["", "Итог: " + ("все ассеты целы" if ok else "есть проблемы")]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    """Разобрать аргументы и выполнить проверку."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=repo_slug(), help="owner/name репозитория")
    ap.add_argument("--tag", default="", help="тег релиза (пусто — последний опубликованный)")
    ap.add_argument("--asset", default="", help="маска имени ассета, например '*.zip'")
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN", ""),
                    help="токен GitHub (для приватного репозитория)")
    ap.add_argument("--timeout", type=int, default=30, help="таймаут запросов, с")
    ap.add_argument("--keep", action="store_true", help="не удалять скачанные файлы")
    ap.add_argument("--report", default="", help="куда записать markdown-отчёт")
    ap.add_argument("--check-local", default="",
                    help="проверить локальный файл сборки (без сети) и выйти")
    ap.add_argument("--version", default="",
                    help="версия, которую ждём внутри архива (для --check-local)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):  # UTF-8 даже на cp1252-раннере
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    report = Path(args.report) if args.report else None

    if args.check_local:
        local = Path(args.check_local)
        if not local.exists():
            print(f"::error::файла нет: {local}")
            return 1
        try:
            problems = check_local(local, args.version)
        except Exception as exc:
            print(f"::error::{local.name}: проверка не выполнена: {exc}")
            return 1
        if problems:
            print(f"::error::{local.name}: архив не прошёл проверку целостности")
            for p in problems:
                print(f"::error::{local.name}: {p}")
            return 1
        print(f"OK: {local.name} цел (CRC, состав архива и версия внутри — в порядке)")
        return 0

    try:
        return verify_release(repo=args.repo, tag=args.tag, token=args.token,
                              only=args.asset, timeout=args.timeout,
                              keep=args.keep, report_path=report)
    except Exception as exc:
        print(f"::error::проверка не выполнена: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
