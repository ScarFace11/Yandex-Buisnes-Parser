#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Версия в static/version.json — одна реализация для сборки и анонса."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_notes import extract_section  # noqa: E402

ZIP_ASSET = "YandexBusinessParser-windows-x64.zip"
BULLET_RE = re.compile(r"^[-*•]\s+")
HISTORY_LIMIT = 8
SUMMARY_LIMIT = 400


def strip_tag(tag: str) -> str:
    """`v2.3.1` → `2.3.1` (тег без ведущей «v»)."""
    tag = str(tag or "").strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag


def versioned_download_url(repo: str, version: str, asset: str = ZIP_ASSET) -> str:
    """Ссылка на архив КОНКРЕТНОГО тега."""
    repo = str(repo or "").strip().strip("/")
    if not repo or not version:
        return ""
    return f"https://github.com/{repo}/releases/download/v{version}/{asset}"


def summarize(body: str, limit: int = SUMMARY_LIMIT) -> str:
    """Первый абзац секции CHANGELOG, схлопнутый в одну строку."""
    para = []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line:
            if para:
                break
            continue
        if not para and (line.startswith("#") or line.startswith("```")):
            continue
        if para and BULLET_RE.match(line):
            break
        para.append(BULLET_RE.sub("", line, count=1))
    text = re.sub(r"[*_`\[\]]", "", " ".join(para)).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def apply_version(path, version: str, *, changelog_file=None,
                  download_url: str = "", repo: str = "", asset: str = ZIP_ASSET,
                  bump_history: bool = True, min_version: str = "") -> dict:
    """Проставить версию в version.json и вернуть получившийся словарь. `min_version` — порог «ниже этой версии работать нельзя»."""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig") if p.exists() else "{}"
    data = json.loads(text or "{}")
    version = strip_tag(version)
    data["version"] = version

    if str(min_version or "").strip():
        data["min_version"] = strip_tag(min_version)

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
    """Вывод, который не может уронить шаг сборки."""
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
    ap.add_argument("--min-version", default="",
                    help="минимально допустимая версия («ниже — не работаем»); "
                         "не задана — значение в файле не меняется")
    args = ap.parse_args()

    data = apply_version(
        args.path,
        args.tag or args.version,
        changelog_file=args.changelog,
        download_url=args.download_url,
        repo=args.repo,
        asset=args.asset,
        bump_history=not args.no_history,
        min_version=args.min_version,
    )
    say(f"version.json -> version {data.get('version')}, "
        f"min_version {data.get('min_version') or '—'}, "
        f"download_url {data.get('download_url')}, "
        f"history {len(data.get('history') or [])}")
    say(f"changelog: {data.get('changelog', '')[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
