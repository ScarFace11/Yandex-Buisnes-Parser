# -*- coding: utf-8 -*-
"""Сторож аудита интерфейса: что он проверяет, за чем следит и как отчитывается.

Сам аудит проверяется в tests/test_a11y_browser.py и tests/test_a11y_keyboard.py
(настоящий браузер). Здесь проверяется обвязка, из-за которой аудит попадает на
автосохранение: набор файлов интерфейса, выбор режима, разбор отчёта и код
возврата — то, по чему хук на сохранение решает, показать «чисто» или «сломано».

Run with: python -m pytest tests/test_a11y_watch.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import a11y_watch  # noqa: E402


# ── Что под наблюдением ─────────────────────────────────────────
def test_watched_files_cover_everything_that_draws_the_interface():
    """Вёрстка, стили, фронтенд-скрипты и сам сценарий аудита — под наблюдением."""
    names = {p.name for p in a11y_watch.watched_files()}
    assert "index.html" in names, "правка вёрстки не запускает аудит"
    assert "style.css" in names, "правка стилей не запускает аудит"
    assert any(n.endswith(".js") and n[0].isdigit() for n in names), \
        "правка фронтенд-скриптов не запускает аудит"
    assert "a11y_audit.js" in names, "правка самих проверок не запускает аудит"


def test_watched_files_are_real_files_without_duplicates():
    files = a11y_watch.watched_files()
    assert len(files) == len(set(files)), "один файл попал в наблюдение дважды"
    assert all(p.is_file() for p in files)
    assert all(p.is_relative_to(ROOT) for p in files)


# ── Режимы ──────────────────────────────────────────────────────
def test_quick_mode_runs_a_subset_and_full_mode_adds_keyboard():
    """Быстрый режим — секунды на сохранение, полный — как в CI."""
    quick = a11y_watch.build_command(full=False)
    full = a11y_watch.build_command(full=True)
    assert "-k" in quick, "быстрый режим обязан сузить матрицу состояний"
    quick_k = quick[quick.index("-k") + 1]
    for state in ("collapsed-sidebar", "open-sidebar", "table-with-rows", "theme_switch"):
        assert state in quick_k, f"быстрый режим потерял состояние {state}"
    assert "detects_broken_markup" in quick_k, (
        "без теста-канарейки «чисто» ничего не доказывает"
    )
    assert "-k" not in full, "полный режим проверяет всю матрицу"
    assert "tests/test_a11y_keyboard.py" in full, "полный режим теряет клавиатуру"
    assert "tests/test_a11y_keyboard.py" not in quick


def test_quick_mode_still_checks_both_browser_test_specs():
    quick = a11y_watch.build_command(full=False)
    assert "tests/test_a11y_browser.py" in quick


def test_commands_are_quiet_and_do_not_pollute_pytest_cache():
    """Отчёт нужен короткий: -q и короткая сводка падений вместо простыни."""
    for cmd in (a11y_watch.build_command(full=False), a11y_watch.build_command(full=True)):
        assert "-q" in cmd
        assert "-rf" in cmd
        assert "no:cacheprovider" in cmd


def test_node_suite_lists_test_files_without_a_shell_glob():
    """Оболочку не зовём: имена node-тестов подставляются списком."""
    cmd = a11y_watch.build_node_command()
    assert cmd[:2] == ["node", "--test"]
    assert all(f.endswith(".test.mjs") for f in cmd[2:])
    assert len(cmd) > 2, "node-тесты интерфейса не найдены"


# ── Разбор отчёта ───────────────────────────────────────────────
CLEAN_REPORT = "...\n8 passed, 1 skipped in 12.34s\n"

BROKEN_REPORT = (
    "F...\n"
    "=========================== short test summary info ===========================\n"
    "FAILED tests/test_a11y_browser.py::test_interface_passes_audit[table-with-rows-dark] - \n"
    "AssertionError: dark тема, состояние «table-with-rows»: 2 нарушений\n"
    "  [contrast] td#score.cell: 3.1:1 ниже порога 4.5:1\n"
    "  [name] button.sf-tag: нет доступного имени\n"
    "1 failed, 7 passed in 20.00s\n"
)


def test_clean_report_says_clean_and_shows_the_count():
    text = a11y_watch.format_report(CLEAN_REPORT)
    assert "чисто" in text
    assert "8 passed" in text


def test_full_report_counts_pytest_not_node_footer():
    """В полном режиме за pytest идёт сводка node-тестов — берём счёт pytest."""
    report = CLEAN_REPORT + "\n\u2139 tests 486\n\u2139 pass 486\n\u2139 skipped 0\n"
    text = a11y_watch.format_report(report, full=True)
    assert "8 passed" in text
    assert "skipped 0" not in text


def test_failed_node_tests_are_reported_too():
    """Провал node-тестов интерфейса — тоже не «чисто»."""
    report = CLEAN_REPORT + "\n\u2716 failing tests:\n\u2716 tests\\ui (64ms)\n"
    text = a11y_watch.format_report(report, full=True)
    assert "\u2716" in text


def test_broken_report_lists_each_finding_with_its_element():
    """В отчёте видно, ЧТО сломалось и где — иначе правку не найти."""
    text = a11y_watch.format_report(BROKEN_REPORT)
    assert "[contrast] td#score.cell: 3.1:1" in text
    assert "[name] button.sf-tag" in text
    assert "FAILED tests/test_a11y_browser.py" in text


def test_findings_ignore_service_brackets_of_pytest():
    """Служебные скобки pytest («[100%]», id теста) за находки не считаются."""
    noise = "[100%]\nFAILED tests/x.py::test_y[table-with-rows-dark] - AssertionError\n"
    assert a11y_watch.findings(noise) == []
    assert a11y_watch.findings("  [contrast] span.x: 2.0:1 ниже порога\n")


def test_findings_are_read_out_of_the_pytest_error_block():
    """В отчёте pytest находка живёт в блоке «E   [contrast] …» — читается и он."""
    report = (
        "E       AssertionError: dark тема, состояние «table-with-rows»: 1 нарушений\n"
        "E           [contrast] span#tbl-count.tbl-count: 1.00:1 < 4.5:1\n"
        "E       assert [{'check': 'c...'}] == []\n"
    )
    assert a11y_watch.findings(report) == [
        "[contrast] span#tbl-count.tbl-count: 1.00:1 < 4.5:1"
    ]
    assert "[contrast]" in a11y_watch.format_report(report)


def test_audit_violations_are_shown_without_the_error_tail(monkeypatch, capsys):
    """Найдено нарушение — виден только список находок, без «прогон не состоялся»."""
    report = BROKEN_REPORT + "INFO werkzeug: GET /status HTTP/1.1\n"
    monkeypatch.setattr(a11y_watch, "run_audit", lambda full=False: (1, report))
    assert a11y_watch.run_once() == 1
    out = capsys.readouterr().out
    assert "[contrast]" in out
    assert "прогон не состоялся" not in out, "находки выданы за поломку прогона"
    assert "werkzeug" not in out, "в отчёт попал служебный шум приложения"


def test_meaningful_tail_drops_application_noise():
    report = (
        "INFO werkzeug:_internal.py:97 127.0.0.1 - - [16/Oct/2026] \"GET /status\" 200 -\n"
        "no browser on Chromium\n"
        "1 error in 0.20s\n"
    )
    tail = a11y_watch.meaningful_tail(report)
    assert "no browser on Chromium" in tail
    assert "werkzeug" not in tail


# ── Слепок файлов ───────────────────────────────────────────────
def test_snapshot_notices_a_touched_file(tmp_path):
    path = tmp_path / "style.css"
    path.write_text("a{}", encoding="utf-8")
    before = a11y_watch.snapshot([path])
    path.write_text("a{color:red}", encoding="utf-8")
    after = a11y_watch.snapshot([path])
    changed, removed = a11y_watch.changed_paths(before, after)
    assert changed == [str(path)]
    assert removed == []


def test_snapshot_notices_removed_files(tmp_path):
    path = tmp_path / "style.css"
    path.write_text("a{}", encoding="utf-8")
    before = a11y_watch.snapshot([path])
    path.unlink()
    changed, removed = a11y_watch.changed_paths(before, a11y_watch.snapshot([path]))
    assert changed == []
    assert removed == [str(path)]


def test_snapshot_skips_vanished_files_instead_of_failing(tmp_path):
    """Файл исчез между обходом и stat — это не повод падать."""
    assert a11y_watch.snapshot([tmp_path / "нет-такого.css"]) == {}


# ── Режим хука: --once отдаёт код возврата проверки ─────────────
def test_once_returns_failure_code_when_audit_found_violations(monkeypatch, capsys):
    monkeypatch.setattr(a11y_watch, "run_audit", lambda full=False: (1, BROKEN_REPORT))
    assert a11y_watch.run_once() == 1
    out = capsys.readouterr().out
    assert "[contrast] td#score.cell: 3.1:1" in out


def test_once_returns_zero_when_audit_is_clean(monkeypatch, capsys):
    monkeypatch.setattr(a11y_watch, "run_audit", lambda full=False: (0, CLEAN_REPORT))
    assert a11y_watch.run_once() == 0
    assert "чисто" in capsys.readouterr().out


def test_once_shows_the_tail_when_the_run_broke(monkeypatch, capsys):
    """Нет браузера — это не «нарушений нет»: в отчёте видно, что прогон не состоялся."""
    broken = "no browser\n1 error in 0.20s\n"
    monkeypatch.setattr(a11y_watch, "run_audit", lambda full=False: (2, broken))
    assert a11y_watch.run_once() == 1
    out = capsys.readouterr().out
    assert "прогон не состоялся" in out
    assert "no browser" in out


def test_once_passes_the_mode_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(a11y_watch, "run_audit",
                        lambda full=False: (seen.update(full=full), (0, CLEAN_REPORT))[1])
    a11y_watch.run_once(full=True)
    assert seen["full"] is True


def test_cli_once_returns_the_audit_code(monkeypatch):
    """Так сторож и вешается на сохранение: код возврата = вердикт аудита."""
    monkeypatch.setattr(a11y_watch, "run_audit", lambda full=False: (1, BROKEN_REPORT))
    assert a11y_watch.main(["--once"]) == 1


def test_cli_full_once_asks_for_the_full_matrix(monkeypatch):
    seen = {}
    monkeypatch.setattr(a11y_watch, "run_audit",
                        lambda full=False: (seen.update(full=full), (0, CLEAN_REPORT))[1])
    assert a11y_watch.main(["--once", "--full"]) == 0
    assert seen["full"] is True


def test_watch_reports_only_after_a_change(monkeypatch, tmp_path):
    """Наблюдение: первая проверка сразу, дальше — только после правки файла.

    Правка делается из подменённого sleep — после первого слепка и через
    паузу тишины, как при настоящем сохранении в редакторе.
    """
    watched = tmp_path / "style.css"
    watched.write_text("a{}", encoding="utf-8")
    monkeypatch.setattr(a11y_watch, "watched_files", lambda root=None: [watched])
    calls = []
    monkeypatch.setattr(a11y_watch, "run_once",
                        lambda full=False, label="": (calls.append(label), 0)[1])

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 2:
            watched.write_text("a{color:red}", encoding="utf-8")
        if sleeps["n"] > 40:
            raise KeyboardInterrupt

    monkeypatch.setattr(a11y_watch.time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        a11y_watch.watch(interval=0.01, debounce=0.01)

    assert calls[0] == "первый прогон", "первая проверка должна идти сразу"
    assert len(calls) == 2, f"аудит не отреагировал на правку ровно один раз: {calls}"
    assert "style.css" in calls[1], f"в отчёте не видно, что изменилось: {calls[1]}"


def test_watch_waits_through_a_burst_of_saves(monkeypatch, tmp_path):
    """Пачка быстрых сохранений даёт один прогон, а не по одному на букву."""
    watched = tmp_path / "style.css"
    watched.write_text("a{}", encoding="utf-8")
    monkeypatch.setattr(a11y_watch, "watched_files", lambda root=None: [watched])
    calls = []
    monkeypatch.setattr(a11y_watch, "run_once",
                        lambda full=False, label="": (calls.append(label), 0)[1])

    sleeps = {"n": 0}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] <= 8:
            watched.write_text(f"a{{color:red;padding:{sleeps['n']}px}}", encoding="utf-8")
        if sleeps["n"] > 40:
            raise KeyboardInterrupt

    monkeypatch.setattr(a11y_watch.time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        a11y_watch.watch(interval=0.01, debounce=0.01)

    # Восемь сохранений подряд — далеко не восемь прогонов. Верхняя граница не 2:
    # отметка времени файла на Windows обновляется с задержкой, и уже сделанная
    # правка может выглядеть как ещё одна — лишний прогон безвреден, а вот
    # прогон на каждое сохранение нет.
    assert 2 <= len(calls) <= 4, f"на пачку из 8 сохранений пришлось {len(calls)} прогонов"


def test_watch_without_interface_files_says_so(monkeypatch, capsys):
    """Пустой набор — это ошибка настройки, а не «чисто»."""
    monkeypatch.setattr(a11y_watch, "watched_files", lambda root=None: [])
    assert a11y_watch.watch() == 1
    assert "нечего проверять" in capsys.readouterr().out


def test_python_interpreter_prefers_repository_venv():
    """pytest и websocket-client живут в venv: сторож обязан взять его."""
    interpreter = a11y_watch._python()
    assert interpreter, "интерпретатор не найден"
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.exists():
        assert Path(interpreter) == venv


def test_output_encoding_is_switched_to_utf8(monkeypatch):
    """Отчёт на Windows-консоли в cp1251 раньше падал на «✓» и находках."""
    class Stream:
        def __init__(self):
            self.kwargs = None

        def reconfigure(self, **kwargs):
            self.kwargs = kwargs

    stdout, stderr = Stream(), Stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    a11y_watch.configure_output()
    expected = {"encoding": "utf-8", "errors": "replace"}
    assert stdout.kwargs == expected
    assert stderr.kwargs == expected


def test_output_encoding_setup_survives_streams_without_reconfigure(monkeypatch):
    """В тестах и пайпах поток без reconfigure — это не повод падать."""
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    monkeypatch.setattr(sys, "stderr", None, raising=False)
    a11y_watch.configure_output()  # не должно бросить исключение


def test_paths_outside_the_repository_do_not_break_the_report(tmp_path):
    """Путь вне репозитория печатается как есть, а не роняет отчёт."""
    assert a11y_watch._rel(tmp_path / "style.css") == str(tmp_path / "style.css")
    assert a11y_watch._rel(ROOT / "static" / "css" / "style.css") == \
        str(Path("static") / "css" / "style.css")
