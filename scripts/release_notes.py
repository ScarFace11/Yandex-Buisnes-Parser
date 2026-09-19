#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тело черновика GitHub Release из CHANGELOG.md.

Используется job'ом `release-draft` в .github/workflows/build-exe.yml при пуше
тега v*:

    title=$(python3 scripts/release_notes.py --tag v2.3.0 \
            --changelog CHANGELOG.md --out release_notes.md)
    gh release create "$TAG" --draft --title "$title" \
        --notes-file release_notes.md

Поведение:
  * находит секцию «## [VERSION] — Подзаголовок» (VERSION — тег без «v»),
    берёт всё до следующего «## » как тело; подзаголовок идёт в заголовок
    релиза («v2.3.0 — Подзаголовок»);
  * секции нет → фолбэк: ссылка на CHANGELOG + список коммитов с предыдущего
    тега (best-effort, требует fetch-depth: 0 в checkout);
  * печатает заголовок релиза одной строкой в stdout (когда --out — файл).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def extract_section(text: str, version: str):
    """(подзаголовок, тело) секции «## [version] …» или None."""
    # [ \t]* а не \s*: пробелы только до конца строки заголовка, иначе жадный
    # \s* перепрыгивает переводы строк и съедает тело секции.
    heading = re.search(rf"^##\s*\[{re.escape(version)}\][ \t]*(.*)$", text, re.M)
    if not heading:
        return None
    start = heading.end()
    nxt = re.search(r"^##\s", text[start:], re.M)
    # nxt.start() — индекс ВНУТРИ text[start:], резать нужно text[start:start+nxt.start()].
    section = text[start:start + nxt.start()] if nxt else text[start:]
    subtitle = ""
    sub = re.match(r"\s*[—–-]+\s*(.+)", heading.group(1))
    if sub:
        subtitle = sub.group(1).strip().strip("#").strip()
    return subtitle, section.strip().strip("`").strip()


def git_log_since_previous_tag(tag: str) -> str:
    """Список коммитов с прошлого тега; пустая строка, если не вышло."""
    try:
        prev = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", tag + "^"],
            capture_output=True, text=True, timeout=20,
        )
        rng = (prev.stdout.strip() + ".." + tag
               if prev.returncode == 0 and prev.stdout.strip() else tag)
        log = subprocess.run(
            ["git", "log", "--oneline", "--no-decorate", rng],
            capture_output=True, text=True, timeout=20,
        )
        return log.stdout.strip() if log.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True, help="тег релиза, например v2.3.0")
    ap.add_argument("--changelog", default="CHANGELOG.md")
    ap.add_argument("--out", default="-",
                    help="файл для тела релиза; «-» — печатать тело в stdout")
    args = ap.parse_args()

    tag = args.tag.strip()
    version = tag[1:] if tag.startswith("v") else tag

    cl_path = Path(args.changelog)
    text = cl_path.read_text(encoding="utf-8-sig") if cl_path.exists() else ""
    found = extract_section(text, version) if text else None

    if found:
        subtitle, body = found
    else:
        # Секции для этой версии нет — собираем тело вручную (edge case ТЗ:
        # «если описаний не было — собрать из коммитов»).
        subtitle = ""
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        repo = os.environ.get("GITHUB_REPOSITORY",
                              "ScarFace11/Yandex-Buisnes-Parser")
        body = (f"Полное описание — в [CHANGELOG.md]({server}/{repo}/"
                f"blob/main/CHANGELOG.md).")
        commits = git_log_since_previous_tag(tag)
        if commits:
            body += "\n\n### Коммиты\n\n" + commits

    title = f"v{version} — {subtitle}" if subtitle else tag

    if args.out == "-":
        sys.stdout.write(body + "\n")
    else:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
