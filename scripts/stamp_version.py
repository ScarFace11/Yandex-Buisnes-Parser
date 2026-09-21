#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Версия в static/version.json — одна реализация для сборки и анонса.

Два вызова, один код:

  * build-exe.yml (шаг перед pyinstaller) — штампует копию, которая попадёт
    ВНУТРЬ .exe: version = версия тега, download_url — ссылка на конкретный
    тег. Файл не коммитится: он нужен только сборке (проверка версии внутри
    скачанного архива и офлайн-режим «Что нового»).
  * announce-release.yml (событие release: published) — та же операция, но с
    коммитом в main: именно ЭТОТ файл читают установленные приложения, когда
    проверяют наличие обновления.

Инвариант проекта: `version` в файле на main — всегда ОПУБЛИКОВАННЫЙ релиз,
архив которого реально можно скачать. Реклама версии без релиза (или пока
релиз — черновик) превращает баннер обновления в обещание, которое нельзя
выполнить: пользователь скачивает обновление и остаётся на прежней версии.

Использование:
    python scripts/stamp_version.py --tag v2.3.1 --repo owner/name
    python scripts/stamp_version.py --version 2.3.1 --download-url https://…/x.zip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_notes import extract_section  # noqa: E402

ZIP_ASSET = "YandexBusinessParser-windows-x64.zip"
HISTORY_LIMIT = 8
SUMMARY_LIMIT = 400


def strip_tag(tag: str) -> str:
    """`v2.3.1` → `2.3.1` (тег без ведущей «v»)."""
    tag = str(tag or "").strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag


def versioned_download_url(repo: str, version: str, asset: str = ZIP_ASSET) -> str:
    """Ссылка на архив КОНКРЕТНОГО тега.

    Никогда не `releases/latest/download/...`: этот алиас отдаёт предыдущий
    опубликованный релиз, пока новый — черновик, и обновление превращается в
    установку той же версии, что уже стоит.
    """
    repo = str(repo or "").strip().strip("/")
    if not repo or not version:
        return ""
    return f"https://github.com/{repo}/releases/download/v{version}/{asset}"


def summarize(body: str, limit: int = SUMMARY_LIMIT) -> str:
    """Первый абзац секции CHANGELOG, схлопнутый в одну строку.

    Именно абзац, а не первая строка: в CHANGELOG абзац часто начинается
    коротким жирным лидом («**Кнопка обновления работает.**») — без него
    в «Что нового» попадал обрывок фразы.
    """
    para = []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line:
            if para:
                break
            continue
        if not para and (line.startswith("#") or line.startswith("```")):
            continue
        para.append(line)
    text = re.sub(r"[*_`\[\]]", "", " ".join(para)).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def apply_version(path, version: str, *, changelog_file=None,
                  download_url: str = "", repo: str = "", asset: str = ZIP_ASSET,
                  bump_history: bool = True) -> dict:
    """Проставить версию в version.json и вернуть получившийся словарь."""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig") if p.exists() else "{}"
    data = json.loads(text or "{}")
    version = strip_tag(version)
    data["version"] = version

    summary = ""
    if changelog_file:
        cl = Path(changelog_file)
        if cl.exists():
            found = extract_section(cl.read_text(encoding="utf-8-sig"), version)
            if found:
                summary = summarize(found[1])
    if summary:
        data["changelog"] = summary

    url = download_url or versioned_download_url(repo, version, asset)
    if url:
        data["download_url"] = url

    if bump_history:
        entry = {"version": version, "changelog": summary or data.get("changelog", "")}
        history = [h for h in (data.get("history") or [])
                   if str((h or {}).get("version")) != version]
        data["history"] = [entry] + history
        data["history"] = data["history"][:HISTORY_LIMIT]

    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return data


def say(text: str) -> None:
    """Вывод, который не может уронить шаг сборки.

    На windows-раннере GitHub stdout внешне — cp1252, и обычный print() с
    русскими словами падал с UnicodeEncodeError: скрипт отрабатывал верно, а
    шаг сборки краснел. Сначала просим UTF-8, а если не вышло — печатаем
    ASCII-версию строки.
    """
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(enc, "replace").decode(enc, "replace") + "\n")


def main() -> int:
    try:                       # UTF-8 в лог, где это возможно
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tag", help="тег релиза, например v2.3.1")
    src.add_argument("--version", help="версия без «v», например 2.3.1")
    ap.add_argument("--path", default="static/version.json")
    ap.add_argument("--changelog", default="CHANGELOG.md")
    ap.add_argument("--repo", default="", help="owner/name — для ссылки на тег")
    ap.add_argument("--download-url", default="")
    ap.add_argument("--asset", default=ZIP_ASSET)
    ap.add_argument("--no-history", action="store_true",
                    help="не трогать список history (только version/changelog/URL)")
    args = ap.parse_args()

    data = apply_version(
        args.path,
        args.tag or args.version,
        changelog_file=args.changelog,
        download_url=args.download_url,
        repo=args.repo,
        asset=args.asset,
        bump_history=not args.no_history,
    )
    say(f"version.json -> version {data.get('version')}, "
        f"download_url {data.get('download_url')}, "
        f"history {len(data.get('history') or [])}")
    say(f"changelog: {data.get('changelog', '')[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
