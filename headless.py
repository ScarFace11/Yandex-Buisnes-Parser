# -*- coding: utf-8 -*-
"""Сбор из консоли по сохранённому пресету: `app.py --run`.

Зачем это нужно. Обычный запуск — это окно приложения и нажатие кнопки:
на сервере без графики, по SSH, по расписанию или просто «оставить на ночь»
это лишний шаг. Здесь тот же движок (`runner.run_web`) и те же параметры
формы, но без Flask: сервер не поднимается, окно не открывается, порт не
занимается. Логи идут в stdout, выгрузки — в ту же папку результатов.

    python app.py --run --preset "Уфа стоматология"
    python app.py --run --preset ufa.json --pages 2 --dry-run
    python app.py --run --queries "кафе, кофейня" --cities "Уфа, Казань"
    python app.py --run --list-presets

Пресеты берутся из settings.json (туда их дублирует интерфейс) или из
JSON-файла: консоль не видит localStorage браузера, и это единственный
честный способ запустить «тот самый» сохранённый набор.

Браузер для сбора всё равно нужен и запускается: страницы Яндекс.Карт
читаются только через Chromium (Chrome DevTools Protocol). «Без интерфейса»
означает «без окна приложения», а не «без браузера».
"""
import argparse
import re
import sys
import time

import presets_store

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Уровни, которые в консоли не нужны: sys/tech — отладка, progress — пинги
# квоты (их десятки на город). С --verbose показываем всё.
_QUIET_LEVELS = {"sys", "tech", "progress"}


def _strip(text: str) -> str:
    return _ANSI_RE.sub("", str(text or ""))


def make_logger(verbose: bool = False):
    """log_fn для run_web: строки с понятным префиксом, без ANSI и мусора."""
    prefixes = {"ok": "✔ ", "warn": "▲ ", "error": "✖ ", "result": "• "}

    def log(level: str, msg: str) -> None:
        if not verbose and level in _QUIET_LEVELS:
            return
        line = _strip(msg).replace("\r", " ").strip()
        if not line:
            return
        try:
            print(prefixes.get(level, "  ") + line, flush=True)
        except (OSError, ValueError):
            pass          # закрытая консоль не должна убивать прогон

    return log


def describe(params: dict) -> str:
    """Человеческая сводка того, что будет запущено (для --dry-run и шапки)."""
    formats = [name for name, key in (("Excel", "output_excel"), ("JSON", "output_json"),
                                      ("CSV", "output_csv"), ("HTML-карта", "output_map"))
               if params.get(key)]
    cities = params.get("cities") or []
    queries = params.get("queries") or []
    lines = [
        f"Запросы ({len(queries)}): {', '.join(queries) or '—'}",
        f"Города ({len(cities)}): {', '.join(cities) or '—'}",
        f"Форматы: {', '.join(formats) or '—'}",
        f"Страниц на точку: {params.get('max_pages')} · потоков: {params.get('max_workers')}"
        f" · лимит организаций: {params.get('max_candidates')}",
        f"Режим: {'только без сайтов' if params.get('parse_mode') == 'without_website' else 'все организации'}"
        f" · соцсети: {params.get('social_mode')}"
        + (" · сетка точек" if params.get("use_grid") else ""),
    ]
    if params.get("blacklist_words"):
        lines.append(f"Исключить слова: {', '.join(params['blacklist_words'])}")
    if params.get("continue_cities"):
        lines.append("Непрерывный режим: после выбранных городов — следующие по каталогу")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py --run",
        description="Сбор по сохранённому пресету без запуска интерфейса.",
    )
    parser.add_argument("--run", action="store_true",
                        help="выполнить сбор и выйти (флаг для app.py)")
    parser.add_argument("--preset", default="",
                        help="имя сохранённого пресета или путь к JSON-файлу")
    parser.add_argument("--list-presets", action="store_true",
                        help="показать сохранённые пресеты и выйти")
    parser.add_argument("--queries", default="",
                        help="запросы через запятую (без пресета)")
    parser.add_argument("--cities", default="",
                        help="города через запятую (без пресета)")
    parser.add_argument("--pages", type=int, default=None, help="страниц на точку")
    parser.add_argument("--workers", type=int, default=None, help="потоков на карточки")
    parser.add_argument("--max", dest="max_candidates", type=int, default=None,
                        help="максимум организаций на город")
    parser.add_argument("--formats", default="",
                        help="форматы выгрузки через запятую: excel,json,csv,map")
    parser.add_argument("--no-continue", action="store_true",
                        help="выключить непрерывный режим, даже если он в пресете")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать, что будет запущено")
    parser.add_argument("--verbose", action="store_true",
                        help="печатать технические строки лога")
    return parser


def main(argv: list[str] | None = None) -> int:
    args, unknown = _parser().parse_known_args(argv or [])
    if unknown:
        print(f"Незнакомые аргументы: {' '.join(unknown)}", file=sys.stderr)
        return 2

    if args.list_presets:
        presets = presets_store.load_presets()
        if not presets:
            print("Сохранённых пресетов нет. Сохраните пресет в интерфейсе "
                  "(кнопка «+ Новый») или передайте JSON-файл через --preset.")
            return 0
        print("Сохранённые пресеты:")
        for preset in presets:
            settings = preset.get("settings") or {}
            queries = presets_store._as_list(settings.get("queries"))
            cities = presets_store._as_list(settings.get("cities"))
            print(f"  • {preset['name']}: {len(queries)} запросов, "
                  f"{len(cities)} городов" + (f" ({', '.join(cities[:3])}…)" if len(cities) > 3 else ""))
        return 0

    overrides = {
        "pages": args.pages,
        "workers": args.workers,
        "max_candidates": args.max_candidates,
        "formats": [f for f in args.formats.replace(";", ",").split(",") if f.strip()],
        "no_continue": args.no_continue,
    }
    if args.queries:
        overrides["queries"] = args.queries
    if args.cities:
        overrides["cities"] = args.cities

    if not args.preset and not args.queries:
        print("Нужен пресет (--preset «Имя» или файл.json) либо --queries с городами. "
              "Список пресетов: --list-presets.", file=sys.stderr)
        return 2

    try:
        if args.preset:
            preset = presets_store.load_preset_source(args.preset)
            settings = preset["settings"]
            source = preset["name"]
        else:
            settings = {}
            source = "параметры командной строки"
    except (KeyError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    params = presets_store.preset_to_params(settings, overrides)
    if not params["queries"]:
        print("В пресете нет запросов — добавьте их в интерфейсе или флагом --queries.",
              file=sys.stderr)
        return 2
    if not params["cities"]:
        print("В пресете нет городов — добавьте их в интерфейсе или флагом --cities.",
              file=sys.stderr)
        return 2

    print("═" * 62)
    print(f"  Сбор без интерфейса — {source}")
    print("═" * 62)
    print(describe(params))
    print("─" * 62)

    if args.dry_run:
        print("Проверка параметров: сбор не запускался (--dry-run).")
        return 0

    started = time.time()
    try:
        from yandex_maps_parser import runner
        files = runner.run_web(params, make_logger(args.verbose))
    except KeyboardInterrupt:
        print("\nОстановлено пользователем — собранное сохранено, "
              "продолжить можно тем же пресетом.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nСбор не выполнился: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    elapsed = time.time() - started
    print("─" * 62)
    print(f"Готово за {int(elapsed // 60)} мин {int(elapsed % 60):02d} с · файлов: {len(files or [])}")
    for name in (files or []):
        print(f"  • {name}")
    try:
        from paths import results_root
        print(f"Папка результатов: {results_root()}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
