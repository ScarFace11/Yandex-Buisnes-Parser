# -*- coding: utf-8 -*-
"""Аудит доступности на автосохранение: правка CSS или вёрстки — сразу отчёт."""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Что считается «файлами интерфейса»: вёрстка, стили, фронтенд-скрипты и сам сценарий аудита (правка проверок тоже должна перезапускать проверку).
WATCH_GLOBS = (
    "templates/*.html",
    "static/css/*.css",
    "static/js/*.js",
    "tests/a11y_audit.js",
)

# Быстрый набор: обе темы × три состояния + канарейка + переключение темы.
QUICK_K = (
    "detects_broken_markup or collapsed-sidebar or open-sidebar "
    "or table-with-rows or theme_switch"
)

BROWSER_TESTS = ("tests/test_a11y_browser.py",)
KEYBOARD_TESTS = ("tests/test_a11y_keyboard.py",)
UI_TESTS = "tests/ui/*.test.mjs"


def watched_files(root: Path = ROOT) -> list:
    """Файлы интерфейса, за которыми следит сторож (существующие, без дублей)."""
    found = []
    for pattern in WATCH_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in found:
                found.append(path)
    return found


def snapshot(paths) -> dict:
    """Слепок «путь → время и размер»: по нему видно правку без чтения файла."""
    state = {}
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        state[str(path)] = (st.st_mtime_ns, st.st_size)
    return state


def changed_paths(before: dict, after: dict):
    """Что изменилось между слепками: правленые, появившиеся и исчезнувшие."""
    changed = [p for p, v in after.items() if before.get(p) != v]
    removed = [p for p in before if p not in after]
    return changed, removed


# Отчёт печатается «✓/✗» и русскими находками, а консоль на Windows бывает в cp1251 — без этого печать падала с UnicodeEncodeError ещё до проверки.
def configure_output() -> None:
    """Своя печать — в UTF-8 с заменой непереводимых знаков (не падать на них)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _rel(path) -> str:
    """Путь для отчёта: относительно репозитория, а если он вне — как есть."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def _python() -> str:
    """Интерпретатор с зависимостями проекта: сначала venv в репозитории."""
    for candidate in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def build_command(full: bool = False) -> list:
    """Команда проверки: аудит в браузере, в полном режиме — ещё и остальное."""
    cmd = [_python(), "-m", "pytest", *BROWSER_TESTS]
    if full:
        cmd += list(KEYBOARD_TESTS)
    cmd += ["-q", "--no-header", "-rf", "-p", "no:cacheprovider"]
    if not full:
        cmd += ["-k", QUICK_K]
    return cmd


def build_node_command() -> list:
    """node-тесты интерфейса: файлы перечисляются здесь, а не оболочкой."""
    files = sorted(str(p.relative_to(ROOT)) for p in ROOT.glob(UI_TESTS))
    return ["node", "--test", *files]


def run_audit(full: bool = False):
    """Прогон проверок: (код возврата, текст отчёта)."""
    env = dict(os.environ)
    # Отчёт должен быть машиночитаемым даже в консоли Windows: русские находки и «✓/✗» иначе превращаются в кракозябры.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        build_command(full), cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    text = proc.stdout or ""
    if full:
        node = subprocess.run(
            build_node_command(), cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        code = proc.returncode or node.returncode
        text = text + "\n" + (node.stdout or "")
        return code, text
    return proc.returncode, text


def failed_tests(report: str) -> list:
    """Что именно не прошло: сводка pytest (FAILED/ERROR) и провалы node-тестов."""
    return [line.strip() for line in report.splitlines()
            if line.strip().startswith(("FAILED", "ERROR", "\u2716"))]


# Строка находки: «[проверка] путь-к-элементу: чем именно нарушено».
FINDING_RE = re.compile(r"^\[[\w][\w \-]*\]\s+\S.*:")


def _unmark(line: str) -> str:
    """Снять маркер pytest с строки: находка лежит в блоке «E   [contrast] …»."""
    stripped = line.strip()
    if stripped == "E":
        return ""
    if stripped.startswith("E "):
        return stripped[1:].strip()
    return stripped


def findings(report: str) -> list:
    """Находки аудита: строки вида «[contrast] селектор: подробность»."""
    found = []
    for line in report.splitlines():
        stripped = _unmark(line)
        if FINDING_RE.match(stripped):
            found.append(stripped)
    return found


# Служебный шум живого приложения (запросы, логи Flask) в отчёт не тащим:
NOISE_MARKERS = (" - - [", "INFO ", "Captured log", "DEBUG ")


def meaningful_tail(report: str, limit: int = 12) -> str:
    """Хвост отчёта без служебного шума — на случай, когда прогон сломался."""
    lines = [ln.rstrip() for ln in report.splitlines()
             if ln.strip() and not any(m in ln for m in NOISE_MARKERS)]
    return "\n".join(lines[-limit:])


def format_report(report: str, full: bool = False) -> str:
    """Короткая сводка вместо простыни pytest: находки, иначе — счёт проверок."""
    bad = failed_tests(report)
    hits = findings(report)
    if hits or bad:
        lines = []
        for item in hits[:20]:
            lines.append(f"  ✗ {item}")
        if len(hits) > 20:
            lines.append(f"  … ещё {len(hits) - 20}")
        for item in bad[:10]:
            lines.append(f"  ! {item}")
        return "\n".join(lines)
    # Счёт проверок — именно строка pytest («8 passed, 20 deselected»), а не сводка node-тестов: в полном режиме они идут следом и тоже «skipped».
    counts = [line.strip() for line in report.splitlines()
              if re.search(r"\d+ passed|\d+ error", line)]
    mode = "полный" if full else "быстрый"
    return f"  ✓ чисто ({mode} аудит: {counts[0] if counts else 'без отчёта'})"


def run_once(full: bool = False, label: str = "") -> int:
    """Один прогон с печатью отчёта. Возвращает код возврата проверки."""
    started = time.time()
    head = f"── аудит интерфейса: {label}" if label else "── аудит интерфейса"
    print(f"{head} …", flush=True)
    code, report = run_audit(full=full)
    took = time.time() - started
    if code == 0:
        print(f"{format_report(report, full=full)}  [{took:.1f} с]", flush=True)
        return 0
    print(format_report(report, full=full), flush=True)
    if not findings(report) and not failed_tests(report):
        # Не находки и не упавшие тесты, а поломка самого прогона (нет браузера, ошибка коллекции): врать «нарушений нет» нельзя — печатаем хвост.
        tail = meaningful_tail(report)
        if tail:
            print(f"  (прогон не состоялся, хвост отчёта)\n{tail}", flush=True)
    print(f"  [{took:.1f} с]", flush=True)
    return 1


def watch(interval: float = 1.0, debounce: float = 1.5, full: bool = False) -> int:
    """Наблюдение за файлами интерфейса: правка → аудит. Возврат — код последнего."""
    configure_output()
    paths = watched_files()
    if not paths:
        print("нечего проверять: файлы интерфейса не найдены", flush=True)
        return 1
    print(f"── слежу за {len(paths)} файлами интерфейса "
          f"(Ctrl+C — стоп)\n   {', '.join(_rel(p) for p in paths)}",
          flush=True)
    code = run_once(full=full, label="первый прогон")
    state = snapshot(paths)
    while True:
        time.sleep(interval)
        current = snapshot(paths)
        changed, removed = changed_paths(state, current)
        if not changed and not removed:
            continue
        # Пачка быстрых сохранений (редактор пишет по нажатию) ждёт тишины:
        while True:
            time.sleep(debounce)
            again = snapshot(paths)
            more, _ = changed_paths(current, again)
            if not more:
                break
            changed = sorted(set(changed) | set(more))
            current = again
        state = current
        label = ", ".join(_rel(p) for p in changed[:4])
        if len(changed) > 4:
            label += f" и ещё {len(changed) - 4}"
        if removed:
            label += f" (удалено: {len(removed)})"
        code = run_once(full=full, label=label)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Сквозной аудит доступности на автосохранение интерфейса",
    )
    parser.add_argument("--once", action="store_true",
                        help="один прогон и выход (для хука на сохранение)")
    parser.add_argument("--full", action="store_true",
                        help="вся матрица состояний, клавиатура и node-тесты")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="как часто смотреть за файлами, секунд")
    parser.add_argument("--debounce", type=float, default=1.5,
                        help="сколько тишины ждать после правки, секунд")
    args = parser.parse_args(argv)
    configure_output()

    if args.once:
        return run_once(full=args.full)
    try:
        return watch(interval=args.interval, debounce=args.debounce, full=args.full)
    except KeyboardInterrupt:
        print("\n── остановлено", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
