# -*- coding: utf-8 -*-
"""Самопроверка без запуска интерфейса: `app.py --check`."""
import argparse
import json
import sys
import time

# Значки статусов: в UTF-8-консоли читаются, в логе не ломаются.
_MARKS = {"ok": "✔", "warn": "▲", "error": "✖"}
_TITLES = {
    "keys": "Ключи API",
    "files": "Файлы и папки",
    "data": "Данные прошлых сборов",
    "runs": "Прогоны и кэш",
    "env": "Окружение",
    "engines": "Браузер и выдача",
}


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу: 1 проверка / 2 проверки / 5 проверок."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def counts(results: list[dict]) -> dict:
    """Сколько строк каждого статуса — по нему считается итог и код возврата."""
    got = {"ok": 0, "warn": 0, "error": 0}
    for row in results or []:
        status = row.get("status") if isinstance(row, dict) else None
        if status in got:
            got[status] += 1
    return got


def format_report(results: list[dict], *, title: str = "Самопроверка",
                  groups: list[str] | None = None) -> str:
    """Текст отчёта для консоли: группы, строки, «что делать», итог."""
    results = results or []
    got = counts(results)
    # Строку без группы или не-словарь печатать некуда: отчёт обязан выжить даже на мусорном входе (сторонняя проверка тоже когда-нибудь сломается).
    rows_in = [r for r in results if isinstance(r, dict) and r.get("group")]
    order = [g for g in (groups or []) if any(r.get("group") == g for r in rows_in)]
    if not order:
        order = list(dict.fromkeys(r.get("group") for r in rows_in))
    head = [
        "═" * 62,
        f"  {title} — {time.strftime('%d.%m.%Y %H:%M')}",
        "═" * 62,
    ]
    lines: list[str] = list(head)

    for group in order:
        rows = [r for r in rows_in if r.get("group") == group]
        if not rows:
            continue
        lines.append("")
        lines.append(_TITLES.get(group, str(group)))
        for row in rows:
            mark = _MARKS.get(row.get("status"), "•")
            lines.append(f"  {mark} {row.get('title') or ''}")
            detail = (row.get("detail") or "").strip()
            if detail:
                lines.append(f"     {detail}")
            hint = (row.get("hint") or "").strip()
            if hint:
                lines.append(f"     → {hint}")

    lines.append("")
    lines.append("─" * 62)
    total = len(results)
    summary = (f"Итог: {total} {_plural(total, 'проверка', 'проверки', 'проверок')}: "
               f"{got['ok']} в порядке")
    if got["warn"]:
        summary += f", {got['warn']} с предупреждениями"
    if got["error"]:
        summary += f", {got['error']} с ошибками"
    lines.append(summary + ".")
    if got["error"]:
        lines.append("Есть ошибки: с ними сбор не пойдёт — начните с красных строк.")
    elif got["warn"]:
        lines.append("Ошибок нет. Предупреждения — места, где результат будет хуже обычного.")
    else:
        lines.append("Всё готово к работе.")
    lines.append("Подробнее: «Диагностика» в окне приложения или --json.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Запуск проверок из консоли. Возвращает код выхода процесса."""
    parser = argparse.ArgumentParser(
        prog="app.py --check",
        description="Самопроверка приложения без запуска интерфейса.",
    )
    parser.add_argument("--check", action="store_true",
                        help="выполнить проверки и выйти (флаг для app.py)")
    parser.add_argument("--groups", default="",
                        help="группы через запятую: keys,files,data,runs,env,engines")
    parser.add_argument("--deep", action="store_true",
                        help="живая проба браузера: открыть страницу выдачи")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="машинный отчёт вместо текста")
    args, unknown = parser.parse_known_args(argv or [])
    if unknown:
        # Неизвестный флаг — не повод молча сделать не то; но и падать из-за лишнего аргумента оболочки не хочется: предупреждаем в stderr.
        print(f"  (пропущены незнакомые аргументы: {' '.join(unknown)})", file=sys.stderr)

    try:
        from routes import diagnostics
    except Exception as exc:          # битая установка — говорим прямо
        print(f"Самопроверка не запустилась: {type(exc).__name__}", file=sys.stderr)
        return 2

    valid = list(diagnostics.GROUPS)
    wanted = [g.strip() for g in args.groups.split(",") if g.strip()]
    bad = [g for g in wanted if g not in valid]
    if bad:
        print(f"Неизвестные группы: {', '.join(bad)}. Доступны: {', '.join(valid)}",
              file=sys.stderr)
        return 2
    # Без --deep группа «engines» только ищет бинарник (мгновенно); живая проба выдачи включается флагом, потому что открывает окно браузера.
    groups = wanted or valid

    try:
        results = diagnostics.run_checks(groups, deep=bool(args.deep))
    except Exception as exc:
        print(f"Проверки не выполнились: {type(exc).__name__}", file=sys.stderr)
        return 2

    got = counts(results)
    if args.as_json:
        print(json.dumps({"ok": not got["error"], "counts": got,
                          "results": results, "ts": int(time.time())},
                         ensure_ascii=False, indent=2))
    else:
        print(format_report(results, title="Самопроверка Yandex Business Parser",
                            groups=groups))
    return 1 if got["error"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
