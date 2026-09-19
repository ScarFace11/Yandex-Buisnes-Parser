"""Журнал «Ход поиска»: фильтры, метки времени, иерархия, кнопки.

Логику фильтрации и свёртки городов ловят node-тесты (tests/ui/logpanel),
но часть требований живёт только в разметке, стилях и текстах бэкенда —
их проверяем здесь: кнопки на месте, CSS фильтров существует, счётчики
объясняют, откуда взялась цифра.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
RUNNER = (ROOT / "yandex_maps_parser" / "runner.py").read_text(encoding="utf-8")
STATS = (ROOT / "yandex_maps_parser" / "stats.py").read_text(encoding="utf-8")


class TestLogFilters:
    """[Все] [Важные] [Ошибки] [Технические] — четыре режима чтения."""

    def test_four_filter_buttons_are_wired(self):
        for name in ("all", "important", "errors", "tech"):
            assert f'data-lfilter="{name}"' in TEMPLATE, name
        assert TEMPLATE.count('onclick="setLogFilter(') == 4

    def test_errors_filter_carries_a_counter_badge(self):
        assert 'id="log-err-count"' in TEMPLATE

    def test_empty_verdict_strip_exists(self):
        assert 'id="log-filter-empty"' in TEMPLATE

    def test_js_maps_every_filter_to_a_container_class(self):
        # «Все» — это отсутствие скрывающего правила, остальные три — правила.
        for name in ("important", "errors", "tech"):
            assert f"#log-output.f-{name}" in STYLE, name
        assert "logEl.classList.add('f-' + S.filter)" in APP_JS
        assert "function setLogFilter(" in APP_JS
        assert "function _refreshLogFilter(" in APP_JS
        assert "✅ Ошибок нет" in APP_JS
        assert "'Важных сообщений нет — включите «Все»'" in APP_JS \
            or "Важных сообщений нет" in APP_JS

    def test_filters_hide_lines_with_css_only(self):
        """Смена фильтра не перерисовывает журнал — строки не теряются."""
        assert "#log-output.f-important .ll.noise{display:none}" in STYLE
        assert "#log-output.f-errors .ll:not(.warn):not(.error)" in STYLE
        assert "#log-output.f-tech .ll:not(.tech){display:none}" in STYLE


class TestTimestamps:
    def test_the_stamp_column_is_kept_but_repeats_are_dimmed(self):
        assert "#log-output .ll-time{display:inline-block;min-width:64px}" in STYLE
        assert "#log-output .ll-time.same{visibility:hidden}" in STYLE
        assert "S.lastSec" in APP_JS


class TestHierarchyAndFolds:
    def test_city_headers_are_foldable(self):
        assert "function toggleLogBlock(" in APP_JS
        assert "#log-output .ll.city" in STYLE
        assert "#log-output .ll.city.collapsed" in STYLE
        assert "ll-caret" in APP_JS and "ll-caret" in STYLE

    def test_sub_lines_are_indented(self):
        assert "#log-output .ll.ind-1{padding-left:26px" in STYLE
        assert "LOG_SUBLINE_RE" in APP_JS


class TestLevelColours:
    """✅/📡/⚠/[!] — вес и цвет, а не один серый поток."""

    def test_levels_are_decided_by_level_then_text(self):
        assert "function _logLevel(" in APP_JS
        assert "function _logIsNoise(" in APP_JS

    def test_success_and_error_are_bold(self):
        assert "#log-output .ll.ok{font-weight:700}" in STYLE
        assert "#log-output .ll.error{font-weight:700}" in STYLE
        assert "#log-output .ll.info{font-weight:600}" in STYLE


class TestLogHeaderButtons:
    def test_save_and_copy_exist_and_are_wired(self):
        assert 'id="btn-log-save"' in TEMPLATE and "saveLogFile()" in TEMPLATE
        assert 'id="btn-log-copy"' in TEMPLATE and "copyLogText()" in TEMPLATE
        assert "function saveLogFile(" in APP_JS
        assert "async function copyLogText(" in APP_JS
        # Копирование переиспользует общий хелпер, а не второй execCommand.
        assert "await copyText(text)" in APP_JS

    def test_the_saved_file_carries_absolute_stamps(self):
        assert "function _logPlainText(" in APP_JS
        assert "[${el._stamp}] ${txt}" in APP_JS


class TestJumpToBottom:
    def test_floating_button_and_js_are_wired(self):
        assert 'id="log-jump"' in TEMPLATE and "logJumpToBottom()" in TEMPLATE
        assert 'id="log-jump-n"' in TEMPLATE
        assert "function logJumpToBottom(" in APP_JS
        assert "function _onLogScroll(" in APP_JS
        assert ".log-jump" in STYLE


class TestProgressStrip:
    def test_current_city_eta_and_mini_bars_are_rendered(self):
        for needle in ('id="tp-city"', 'id="tp-eta"', 'id="tp-cities"'):
            assert needle in TEMPLATE, needle
        assert "tp-chip" in APP_JS and ".tp-chip" in STYLE
        assert "set('tp-city'" in APP_JS
        assert ".term-progress-info .tp-city{font-size:13px" in STYLE


class TestCountersCarryContext:
    """«43» без контекста ничего не объясняет — цифры получают подпись."""

    def test_requests_are_named(self):
        assert "Запросов к API:" in STATS

    def test_found_count_explains_its_source(self):
        assert "_found_ctx" in RUNNER
        assert "(из {_api_requests} запросов)" in RUNNER


class TestLogCapAndEmptyState:
    def test_log_is_capped_and_has_a_placeholder(self):
        assert "const MAX_LOG_LINES = 1200;" in APP_JS
        assert "Лог очищен — новые записи появятся здесь" in APP_JS
        assert ".log-empty{" in STYLE

    def test_pragma_cleared_log_forgets_its_counters(self):
        body = APP_JS[APP_JS.index("function clearLog("):]
        body = body[: body.index("\n}")]
        assert "S.stats = {total: 0, noise: 0, err: 0, tech: 0}" in body
        assert "S.meta = []" in body
        assert re.search(r"_refreshLogFilter\(\);", body)
