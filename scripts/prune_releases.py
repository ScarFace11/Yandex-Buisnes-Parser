#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Уборка архивов старых релизов GitHub — с отчётом вместо «сюрприза»."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "ScarFace11/Yandex-Buisnes-Parser"
DEFAULT_PATTERNS = ("*.zip", "*.dmg")
DEFAULT_VERSION_JSON = ROOT / "static" / "version.json"
API = "https://api.github.com"


# ── Версии ────────────────────────────────────────────────────

def strip_tag(tag: str) -> str:
    """`v2.3.4` → `2.3.4`."""
    tag = str(tag or "").strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag


def version_tuple(value: str) -> tuple:
    """Числовые части версии: «2.3.10» → (2, 3, 10)."""
    return tuple(int(x) for x in str(value or "").split(".") if x.isdigit())


def is_below(version: str, threshold: str) -> bool:
    """`version` строго ниже `threshold` с учётом разной длины (2.3 == 2.3.0)."""
    a, b = version_tuple(version), version_tuple(threshold)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) < b + (0,) * (n - len(b))


def release_version(release: dict) -> str:
    """Версия релиза — из тега (у нас теги всегда вида v2.3.4)."""
    return strip_tag((release or {}).get("tag_name") or "")


# ── Классификация ─────────────────────────────────────────────

def asset_selected(name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(str(name or "").lower(), p.lower())
               for p in patterns)


def build_plan(releases, threshold: str, patterns=DEFAULT_PATTERNS) -> list:
    """Список решений по каждому ассету — без единого удаления."""
    plan = []
    for rel in releases or []:
        tag = str((rel or {}).get("tag_name") or "")
        name = str((rel or {}).get("name") or "")
        version = release_version(rel)
        parsed = bool(version_tuple(version))
        below = parsed and is_below(version, threshold)
        for asset in (rel or {}).get("assets") or []:
            asset_name = str(asset.get("name") or "")
            chosen = below and asset_selected(asset_name, patterns)
            if not parsed:
                reason = "версия не разобрана — не трогаем"
            elif not below:
                reason = f"начиная с v{threshold} архивы храним"
            elif chosen:
                reason = f"версия старое порога v{threshold}"
            else:
                reason = "не архив (описание/CHANGELOG остаются)"
            plan.append({
                "tag": tag,
                "release_name": name,
                "version": version,
                "asset": asset_name,
                "asset_id": asset.get("id"),
                "size": int(asset.get("size") or 0),
                "delete": bool(chosen),
                "reason": reason,
            })
    return plan


def summarize(plan) -> dict:
    victims = [p for p in plan if p["delete"]]
    versions = sorted({p["version"] for p in victims}, key=version_tuple)
    return {
        "releases": len({p["tag"] for p in plan if p["tag"]}),
        "assets_total": len(plan),
        "assets_to_delete": len(victims),
        "bytes_to_free": sum(p["size"] for p in victims),
        "versions": versions,
        "kept": [p for p in plan if not p["delete"]],
    }


# ── Источник релизов ──────────────────────────────────────────

def load_releases_from_json(path) -> list:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("releases") or []
    return list(data)


# ── Источник без токена: HTML-фрагмент релиза ─────────────────

_DOWNLOAD_RE = re.compile(r'/releases/download/([^/"]+)/([^"?]+)')
_SIZE_RE = re.compile(r">\s*([\d.,]+)\s*(B|KB|MB|GB)\s*<", re.I)
_SIZE_MULT = {"b": 1, "kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3}


def _parse_size(text: str) -> int:
    m = _SIZE_RE.search(text or "")
    if not m:
        return 0
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return 0
    return int(value * _SIZE_MULT.get(m.group(2).lower(), 1))


def parse_expanded_assets(html_text: str) -> list:
    """Файлы релиза из HTML-фрагмента expanded_assets (с размерами)."""
    marks = list(_DOWNLOAD_RE.finditer(html_text or ""))
    assets, seen = [], set()
    for i, m in enumerate(marks):
        name = m.group(2)
        if name in seen:
            continue
        seen.add(name)
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html_text)
        assets.append({"id": None, "name": name,
                       "size": _parse_size(html_text[m.start():end])})
    return assets


def list_release_tags(remote: str = "origin") -> list:
    """Теги из `git ls-remote` (только теги, без веток и peeled)."""
    res = subprocess.run(["git", "ls-remote", "--tags", "--refs", remote],
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"git ls-remote {remote}: {res.stderr.strip()}")
    out = []
    for line in res.stdout.splitlines():
        ref = line.split("\t")[-1].strip()
        if ref.startswith("refs/tags/"):
            out.append(ref[len("refs/tags/"):])
    return out


def load_releases_from_web(repo: str, remote: str = "origin") -> list:
    """Список релизов с их файлами — без токена и без API-лимита."""
    import requests
    releases = []
    for tag in list_release_tags(remote):
        r = requests.get(
            f"https://github.com/{repo}/releases/expanded_assets/{tag}",
            timeout=20,
            headers={"User-Agent": "YandexParser-ReleasePruner/1.0"})
        if r.status_code != 200:
            # 404 — релиза нет (тег есть, релиз удалён/не создан): пропускаем.
            continue
        releases.append({"tag_name": tag, "name": "",
                         "assets": parse_expanded_assets(r.text)})
    return releases


def load_releases(repo: str, token: str) -> list:
    """Все релизы репозитория через REST API (постранично)."""
    if not token:
        raise RuntimeError(
            "нет токена: задайте GITHUB_TOKEN (или GH_TOKEN). Без него GitHub "
            "отдаёт список по лимиту, а удалять ассеты нельзя вовсе")
    import requests
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "YandexParser-ReleasePruner/1.0",
               "Authorization": f"Bearer {token}"}
    out, page = [], 1
    while True:
        r = requests.get(f"{API}/repos/{repo}/releases",
                         params={"per_page": 100, "page": page},
                         headers=headers, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"GitHub ответил {r.status_code}: {r.text[:200]}")
        chunk = r.json() or []
        out.extend(chunk)
        if len(chunk) < 100:
            return out
        page += 1


def delete_asset(repo: str, token: str, asset_id) -> None:
    """Удалить ровно ОДИН файл релиза. Тег и описание не затрагиваются."""
    if not asset_id:
        raise RuntimeError("у ассета нет id — нечего удалять")
    import requests
    r = requests.delete(
        f"{API}/repos/{repo}/releases/assets/{asset_id}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "YandexParser-ReleasePruner/1.0",
                 "Authorization": f"Bearer {token}"},
        timeout=20)
    if r.status_code not in (204, 202, 200):
        raise RuntimeError(f"не удалось удалить ассет {asset_id}: "
                           f"HTTP {r.status_code} {r.text[:200]}")


# ── Отчёты ────────────────────────────────────────────────────

def human_size(n: int) -> str:
    step = float(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if step < 1024 or unit == "ГБ":
            return f"{step:.0f} {unit}" if unit == "Б" else f"{step:.1f} {unit}"
        step /= 1024
    return f"{step:.1f} ГБ"


def render_text(head: dict, plan, applied: bool) -> str:
    s = summarize(plan)
    lines = []
    mode = "УДАЛЕНИЕ" if applied else "РЕЖИМ ОТЧЁТА (ничего не удалено)"
    lines.append(f"=== Уборка архивов релизов — {mode} ===")
    lines.append(f"Релизов просмотрено: {s['releases']}, ассетов: {s['assets_total']}")
    lines.append(f"Под удаление: {s['assets_to_delete']} файл(ов) "
                 f"на {human_size(s['bytes_to_free'])}")
    if s["versions"]:
        lines.append("Версии: " + ", ".join(s["versions"]))
    lines.append("")
    if s["assets_to_delete"]:
        lines.append("tag            файл                                    размер   причина")
        for p in plan:
            if p["delete"]:
                lines.append(f"{p['tag']:<14} {p['asset']:<38} "
                             f"{human_size(p['size']):>8}   {p['reason']}")
    else:
        lines.append("Нечего удалять: у всех релизов версии не ниже порога.")
    kept = [p for p in plan if not p["delete"]]
    if kept:
        lines.append("")
        lines.append(f"Остаются нетронутыми: {len(kept)} ассет(ов) "
                     "(описания, теги и CHANGELOG сохраняются)")
    return "\n".join(lines)


def render_markdown(head: dict, plan, applied: bool) -> str:
    s = summarize(plan)
    mode = "удаление" if applied else "режим отчёта (dry-run)"
    lines = [f"## Уборка архивов релизов — {mode}", "",
             f"- релизов: **{s['releases']}**, ассетов: **{s['assets_total']}**",
             f"- к удалению: **{s['assets_to_delete']}** файл(ов) "
             f"на **{human_size(s['bytes_to_free'])}**"]
    if s["versions"]:
        lines.append(f"- версии: {', '.join('v' + v for v in s['versions'])}")
    if s["assets_to_delete"]:
        lines += ["", "| тег | файл | размер |", "|---|---|---|"]
        lines += [f"| {p['tag']} | {p['asset']} | {human_size(p['size'])} |"
                  for p in plan if p["delete"]]
    lines.append("")
    lines.append("Теги, названия и описания релизов не изменяются — удаляются "
                 "только архивы сборок.")
    return "\n".join(lines)


def main() -> int:
    try:                       # UTF-8 в лог, где это возможно
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--below", help="удалять архивы релизов НИЖЕ этой версии")
    src.add_argument("--below-min", action="store_true",
                     help="порог = min_version из version.json")
    ap.add_argument("--version-json", default=str(DEFAULT_VERSION_JSON))
    ap.add_argument("--pattern", action="append", dest="patterns",
                    help=f"шаблон файлов для удаления (по умолчанию: "
                         f"{', '.join(DEFAULT_PATTERNS)}); можно несколько раз")
    ap.add_argument("--apply", action="store_true",
                    help="РЕАЛЬНО удалить выбранные архивы (иначе только отчёт)")
    ap.add_argument("--from-json", dest="from_json", default="",
                    help="взять список релизов из файла вместо API (офлайн)")
    ap.add_argument("--from-web", action="store_true",
                    help="инвентаризация без токена: теги из git ls-remote, файлы "
                         "из HTML-страницы релиза (только отчёт, без удаления)")
    ap.add_argument("--remote", default="origin",
                    help="git-remote для --from-web (по умолчанию origin)")
    ap.add_argument("--json", dest="json_out", default="",
                    help="куда сохранить отчёт в JSON")
    ap.add_argument("--summary", default="",
                    help="куда дописать отчёт в markdown (для $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN")
                    or os.environ.get("GH_TOKEN") or "")
    args = ap.parse_args()

    threshold = ""
    if args.below_min:
        try:
            data = json.loads(Path(args.version_json).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            print(f"::error::не прочитать {args.version_json}: {exc}")
            return 1
        threshold = strip_tag(data.get("min_version") or "")
        if not version_tuple(threshold):
            print("::error::в version.json не задан min_version — порог неизвестен, "
                  "укажите --below вручную")
            return 1
    else:
        threshold = strip_tag(args.below)
        if not version_tuple(threshold):
            print(f"::error::непонятный порог версии: {args.below!r}")
            return 1

    patterns = tuple(args.patterns) if args.patterns else DEFAULT_PATTERNS

    if args.from_web and args.apply:
        # У файла из HTML нет id, а API-удаление требует именно id: не даём сделать вид, что удаление прошло.
        print("::error::--from-web только для отчёта: удаление требует API и токена")
        return 1

    try:
        if args.from_json:
            releases = load_releases_from_json(args.from_json)
        elif args.from_web:
            releases = load_releases_from_web(args.repo, args.remote)
        else:
            releases = load_releases(args.repo, args.token)
    except Exception as exc:
        print(f"::error::не удалось получить релизы: {exc}")
        return 1

    plan = build_plan(releases, threshold, patterns)
    head = {"repo": args.repo, "threshold": threshold,
            "patterns": list(patterns), "applied": bool(args.apply)}

    applied = bool(args.apply)
    deleted, failures = 0, []
    if applied:
        for p in plan:
            if not p["delete"]:
                continue
            try:
                delete_asset(args.repo, args.token, p["asset_id"])
                p["deleted"] = True
                deleted += 1
                print(f"  удалён {p['tag']}/{p['asset']}")
            except Exception as exc:
                p["deleted"] = False
                failures.append(f"{p['tag']}/{p['asset']}: {exc}")
                print(f"::warning::{p['tag']}/{p['asset']}: {exc}")

    print(render_text(head, plan, applied))

    report = dict(head)
    report.update(summarize(plan))
    report["deleted"] = deleted
    report["failures"] = failures
    report["plan"] = plan

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nОтчёт записан: {args.json_out}")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(render_markdown(head, plan, applied) + "\n")

    if failures:
        print(f"::error::не удалось удалить {len(failures)} ассет(ов)")
        return 1
    if applied:
        print(f"Готово: удалено {deleted} архив(ов).")
    else:
        print("Это отчёт. Повторите с --apply, чтобы удалить перечисленное.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
