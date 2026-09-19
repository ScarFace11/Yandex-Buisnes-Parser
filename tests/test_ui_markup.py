"""Разметка и CSS: проверки по тексту шаблона и стилей.

Дешёвые, но злые тесты. Логику ловят node-тесты в tests/ui, а здесь —
то, что живёт только в разметке: исчезнувшие кнопки, вернувшаяся
сортировка по «#», «ядовитые» цвета тёмной темы и автосохранение
отметок «Просмотрено».
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

DARK_MARKER = '[data-theme="dark"]'
DARK_TOKEN_BLOCK = STYLE[STYLE.index(DARK_MARKER + "{"):]


def dark_rule_lines() -> str:
    """Только строки правил `[data-theme="dark"] …{…}` (без комментариев).

    Так палитра проверяется именно там, где она работает: светлая тема
    трогать не должна, а комментарии — тем более.
    """
    keep, inside, depth = [], False, 0
    for line in STYLE.split("\n"):
        if not inside and line.startswith(DARK_MARKER):
            inside, depth = True, 0
        if inside:
            if not line.strip().startswith("/*"):
                keep.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                inside = False
    return "\n".join(keep)


class TestDedupButtonRemoved:
    """«⊘ Дубли» дублировала «Объединять филиалы сетей» — кнопки больше нет."""

    def test_button_is_gone_from_the_toolbar(self):
        assert "btn-dedup" not in TEMPLATE
        assert "⊘ Дубли" not in TEMPLATE

    def test_handler_and_styles_are_gone_too(self):
        assert "function deduplicateResults" not in APP_JS
        assert "btn-dedup" not in APP_JS
        assert "btn-dedup" not in STYLE

    def test_chain_merging_stays_in_the_filter_accordion(self):
        assert 'id="f-collapse-chains"' in TEMPLATE
        assert 'id="f-chain-key"' in TEMPLATE


class TestNumberColumnNotSortable:
    """«#» — порядковый номер строки, а не поле данных."""

    def test_header_has_no_sort_handler(self):
        assert 'onclick="sortTable(1)"' not in TEMPLATE
        assert re.search(r'<th class="nosort"[^>]*>#</th>', TEMPLATE)

    def test_style_kills_cursor_and_arrows(self):
        assert "#results-table th.nosort{cursor:default}" in STYLE
        assert '#results-table th.nosort::after{content:""}' in STYLE

    def test_js_ignores_the_number_column(self):
        assert "const NOSORT_COLS = new Set([0, 1]);" in APP_JS
        assert "if (NOSORT_COLS.has(col)) return;" in APP_JS
        # сортировка по «#» тянула индекс строки в компараторе
        assert "filteredRows.indexOf(a)" not in APP_JS


class TestReviewedAutosave:
    """Отметки «Просмотрено» не должны теряться без ручной кнопки."""

    def test_status_indicator_exists(self):
        assert 'id="reviewed-save-status"' in TEMPLATE

    def test_manual_button_is_renamed(self):
        assert "💾 Сохранить сейчас" in TEMPLATE
        assert "💾 Отметки в файлы" not in TEMPLATE

    def test_js_wires_every_autosave_trigger(self):
        for needle in ("REVIEWED_AUTOSAVE_MS", "markReviewedDirty",
                       "autoPersistReviewed", "persistReviewedOnLeave"):
            assert needle in APP_JS, needle
        assert "window.addEventListener('pagehide'" in APP_JS
        assert "visibilitychange" in APP_JS
        assert "navigator.sendBeacon" in APP_JS or "nav.sendBeacon" in APP_JS

    def test_debounce_is_five_seconds(self):
        assert "const REVIEWED_AUTOSAVE_MS = 5000;" in APP_JS


class TestThemeInit:
    """Тёмная тема ставится до первой отрисовки и не мигает."""

    def test_theme_is_applied_in_the_head_before_the_stylesheet(self):
        head = TEMPLATE[:TEMPLATE.index("</head>")]
        assert "yp_theme_v1" in head, "тема должна ставиться до загрузки CSS"
        assert "document.documentElement.setAttribute('data-theme'" in head
        assert head.index("yp_theme_v1") < head.index("css/style.css")

    def test_switch_is_animated_for_a_quarter_second(self):
        assert "theme-anim" in STYLE

    def test_dark_section_is_parsed_at_all(self):
        assert dark_rule_lines().count("[data-theme=") > 100


class TestDarkPalette:
    def test_token_block_defines_the_soft_palette(self):
        block = DARK_TOKEN_BLOCK[:DARK_TOKEN_BLOCK.index("\n}")]
        for token in ("--bg:", "--card:", "--panel:", "--field:", "--term:",
                      "--bdr:", "--bdr-h:", "--txt:", "--sub:", "--muted:",
                      "--hdr:", "--c:", "--row-alt:", "--row-hover:"):
            assert token in block, token

    def test_background_is_not_black_and_text_is_not_white(self):
        block = DARK_TOKEN_BLOCK[:DARK_TOKEN_BLOCK.index("\n}")]
        assert "--bg:#191C22" in block
        assert "--txt:#E3E7EE" in block

    def test_no_acid_colours_left_in_the_dark_rules(self):
        rules = dark_rule_lines()
        for bad in ("#14B8A6", "#14b8a6", "#0F1419", "#0f1419", "#11161b",
                    "#1A1F24", "#1F2937", "#F3F4F6", "#9CA3AF", "#007E8C",
                    "#374151", "#4B5563", "#EF4444", "#F59E0B", "#10B981"):
            assert bad not in rules, f"{bad} вернулся в тёмную тему — нужен var(--…)"

    def test_dark_rules_pull_from_tokens(self):
        rules = dark_rule_lines()
        assert rules.count("var(--") > 200, "тёмная тема должна жить на токенах"

    def test_stylesheet_braces_balance(self):
        css = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
        assert css.count("{") == css.count("}"), "CSS сломан: фигурные скобки не сходятся"
