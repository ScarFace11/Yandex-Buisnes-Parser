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


class TestFileHistoryBulkActions:
    """История файлов: массовое удаление, массовый архив и снятие выбора.

    Все три кнопки появляются вместе с первым отмеченным файлом. Иконки в
    карточках — инлайновые SVG (эмодзи 🗑 рисовалось монохромно и пропадало
    на тёмном фоне), а «Удалить выбранные» в тёмной теме не должно сливаться
    с панелью."""
    IDS = ("btn-files-bulk-delete", "btn-files-bulk-archive", "btn-files-bulk-cancel")

    def test_three_bulk_buttons_exist_and_are_wired(self):
        for bid in self.IDES if hasattr(self, "IDES") else self.IDS:
            assert f'id="{bid}"' in TEMPLATE, bid
        for handler in ("bulkDeleteSelected()", "bulkArchiveSelected()", "clearFileSelection()"):
            assert f'onclick="{handler}"' in TEMPLATE, handler

    def test_js_exposes_the_archive_and_clear_handlers(self):
        for fn in ("function bulkArchiveSelected(", "function clearFileSelection(",
                   "function onFileSelect("):
            assert fn in APP_JS, fn
        assert "action: 'archive'" in APP_JS, "массовый архив идёт батчем через /files/action"

    def test_card_actions_are_theme_aware_svg_not_emoji(self):
        assert "const FILE_ACT_ICONS = {" in APP_JS
        assert "stroke=\"currentColor\"" in APP_JS
        assert '>🗑</button>' not in APP_JS, "эмодзи-мусорка не наследует цвет темы"
        assert "📥</button>" not in APP_JS

    def test_danger_icon_has_a_colour_in_both_themes(self):
        assert ".file-btn.danger{color:var(--err-strong)}" in STYLE
        assert '[data-theme="dark"] .file-btn.danger{color:var(--err-txt)}' in STYLE
        assert '[data-theme="dark"] .file-btn.danger:hover' in STYLE

    def test_bulk_delete_is_red_in_the_dark_theme_too(self):
        dark = dark_rule_lines()
        assert '[data-theme="dark"] .btn-sm.danger,[data-theme="dark"] .files-bulk-btn{' in dark
        rule = dark[dark.index('[data-theme="dark"] .btn-sm.danger,[data-theme="dark"] .files-bulk-btn{'):]
        rule = rule[: rule.index("}")]
        assert "border-color:var(--red)" in rule
        assert "color:var(--err-txt)" in rule
        # Полупрозрачный --err-bdr (*.45) делал кнопку серой — его тут быть не должно.
        assert "--err-bdr" not in rule


class TestFocusIsVisibleInBothThemes:
    """Рамка фокуса: раньше кольцо брали из --c-soft (8%) — на тёмном поле
    его не видно, а часть правил использовала светлый литерал."""

    def test_focus_ring_token_is_defined_in_both_themes(self):
        light = STYLE[STYLE.index(":root{"):]
        light = light[: light.index("\n}")]
        dark = DARK_TOKEN_BLOCK[: DARK_TOKEN_BLOCK.index("\n}")]

        def alpha(block):
            m = re.search(r"--focus-ring:rgba\([^)]*,\s*([0-9.]+)\)", block)
            assert m, "--focus-ring объявлен не через rgba"
            return float(m.group(1))

        assert alpha(light) >= 0.1, "в светлой теме кольцо не должно исчезнуть"
        # В светлой теме плотность оставляем прежней (как до появления токена):
        # заметность там даёт бирюзовая обводка поля, а плотное свечение
        # читалось как лишнее выделение.
        assert alpha(light) <= 0.2, "в светлой теме кольцо не должно бросаться в глаза"
        assert alpha(dark) > alpha(light) * 3, "на тёмном поле кольцо обязано быть плотнее"

    def test_focus_rules_use_the_token(self):
        """Правила, которые РИСУЮТ рамку фокуса, обязаны брать её из токена."""
        css = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
        for rule in re.finditer(r"([^{}]*(?:focus|focus-within|focus-visible)[^{}]*)\{([^}]*)\}", css):
            selector, body = rule.group(1), rule.group(2)
            where = selector.strip()[-60:]
            assert "rgba(26,122,138" not in body, f"светлый литерал в правиле фокуса: {where}"
            # Строка вида `.stepper input:focus{outline:none;box-shadow:none}`
            # НЕ рисует фокус — рамку рисует .stepper:focus-within, поэтому
            # такие правила пропускаем.
            visible = [d for d in body.split(";")
                       if d.split(":")[0].strip() in ("box-shadow", "outline", "border-color")
                       and d.split(":", 1)[1].strip() not in ("none", "0", "0px")]
            if not visible or "var(--" in body:
                continue
            raise AssertionError(f"фокус без токена: {where} → {body.strip()}")

    def test_range_and_tiles_get_a_focus_state(self):
        assert "input[type=range]:focus-visible" in STYLE
        tiles = (".soc-tile", ".parse-mode-opt", ".social-mode-opt",
                 ".vk-mode-opt", ".source-mode-opt", ".grid-mode-opt")
        for tile in tiles:
            assert f"{tile}:has(input:focus-visible)" in STYLE, tile
        # Регресс: `:focus-within` обводил плитку по клику мышью (фокус уходил
        # в скрытое радио) — подсветка, которой пользователь не просил.
        for tile in tiles:
            assert f"{tile}:focus-within" not in STYLE, tile

    def test_checkboxes_and_radios_get_a_keyboard_focus_ring(self):
        """На коробке 14px свечение токена не различить, а в светлой теме
        у сфокусированного чекбокса не было видимого состояния вообще."""
        # Чекбокс — обычное видимое поле (рамка и по клику мышью).
        assert "input[type=checkbox]:focus{" in STYLE
        # Радио спрятаны в плитках: рамка только для клавиатуры, иначе она
        # светилась бы у всей плитки при клике — то самое лишнее выделение.
        assert "input[type=radio]:focus-visible{" in STYLE
        assert "input[type=radio]:focus{" not in STYLE

    def test_closed_reveal_does_not_leak_a_strip(self):
        """Закрытая секция (grid-template-rows:0fr) не показывает полоску
        контента: верхний отступ живёт только у открытого блока."""
        for rule in re.finditer(r"([^{}]*\.tiles-inner[^{}]*)\{([^}]*)\}", STYLE):
            selector, body = rule.group(1), rule.group(2)
            if "padding-top" in body:
                assert ".open" in selector, f"отступ у закрытого блока: {selector.strip()}"
        rule = re.search(r"#output-advanced \.tiles-inner\{([^}]*)\}", STYLE)
        assert rule, "нет правила #output-advanced .tiles-inner"
        assert "padding-top" not in rule.group(1), "padding даёт утечку в закрытом виде"
        assert "#output-advanced.open .tiles-inner{padding-top:8px}" in STYLE


class TestOutputFolderSettings:
    """«Куда сохранять»: одна папка (или своя на каждый этап) вместо output/."""

    def test_form_has_the_folder_field_and_buttons(self):
        for needle in ('id="f-output-dir"', 'id="btn-output-browse"', 'id="btn-output-save"',
                       'id="btn-output-default"', 'id="f-output-advanced"',
                       'id="f-output-raw"', 'id="f-output-processed"', 'id="f-output-archive"',
                       'id="output-dir-hint"', 'id="output-dir-err"'):
            assert needle in TEMPLATE, needle

    def test_handlers_exist(self):
        for fn in ("function loadOutputDir(", "function saveOutputDir(", "function resetOutputDir(",
                   "function pickOutputDir(", "function onOutputAdvancedToggle(",
                   "function applyOutputDirState("):
            assert fn in APP_JS, fn
        assert "'/output-dir'" in APP_JS and "'/folder-picker'" in APP_JS

    def test_hint_explains_that_service_files_stay_put(self):
        assert "Ключи, кэш найденного и история остаются" in APP_JS

    def test_server_side_routes_exist(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        assert '@bp.route("/output-dir", methods=["GET"])' in api
        assert '@bp.route("/output-dir", methods=["POST"])' in api
        assert '@bp.route("/folder-picker", methods=["POST"])' in api


class TestNotificationSettings:
    """Попап настроек уведомлений: главный тумблер + два типа, два разных звука.

    Логику (черновик, откат, гейт по типам) проверяют node-тесты в
    tests/ui/notifications.test.mjs — здесь только разметка, стили и то,
    что звук перестал зависеть от разрешения браузера.
    """

    def test_header_button_keeps_ids_and_opens_the_popover(self):
        # id кнопки/иконки/подписи — контракт: их читает updateNotifyBtn.
        for needle in ('id="btn-notify"', 'id="notify-icon"', 'id="notify-txt"'):
            assert needle in TEMPLATE, needle
        assert 'onclick="toggleNotifyPopover(event)"' in TEMPLATE
        assert 'aria-haspopup="dialog"' in TEMPLATE

    def test_popover_has_master_and_two_type_switches(self):
        for needle in ('id="notify-pop"', 'id="notify-master"', 'id="notify-city"',
                       'id="notify-search"', 'id="notify-save"', 'id="notify-perm-hint"'):
            assert needle in TEMPLATE, needle
        assert TEMPLATE.count('role="switch"') == 3
        assert TEMPLATE.count('aria-checked=') == 3
        assert 'role="dialog"' in TEMPLATE

    def test_save_button_starts_disabled(self):
        """Пока ничего не изменено — сохранять нечего."""
        assert re.search(r'id="notify-save"[^>]*\bdisabled', TEMPLATE)

    def test_ios_switch_styles(self):
        start = STYLE.index('.tgl{')
        block = STYLE[start:start + 400]
        assert 'width:44px' in block and 'height:24px' in block
        assert '.tgl.on{' in STYLE, 'нет включённого состояния'
        assert '.tgl::after' in STYLE, 'нет ползунка'
        assert '.tgl:disabled' in STYLE, 'подтумблеры должны гаснуть с мастером'

    def test_switch_colours_live_in_tokens_for_both_themes(self):
        light = STYLE[STYLE.index(':root{'):]
        light = light[: light.index('\n}')]
        dark = DARK_TOKEN_BLOCK[: DARK_TOKEN_BLOCK.index('\n}')]
        for token in ('--tgl-off', '--tgl-on', '--knob'):
            assert token + ':' in light, f'{token} не объявлен в светлой теме'
            assert token + ':' in dark, f'{token} не объявлен в тёмной теме'
        assert '#10B981' in light, 'зелёный из макета потерялся'

    def test_popover_has_fixed_width_and_mobile_layout(self):
        assert 'width:320px' in STYLE
        assert '.notify-pop{position:fixed' in STYLE, 'нет раскладки на узком экране'
        # Кнопка остаётся доступной на узком экране — иначе попап не открыть.
        assert '#btn-notify{display:none}' not in STYLE
        assert '#notify-txt{display:none}' in STYLE

    def test_sounds_are_distinct_and_not_gated_by_notification_permission(self):
        for fn in ('function playCityDoneSound(', 'function playDoneSound('):
            assert fn in APP_JS, fn
        for fn in ('playCityDoneSound', 'playDoneSound'):
            body = APP_JS[APP_JS.index('function ' + fn + '('):]
            body = body[: body.index('\n}')]
            assert 'Notification' not in body, f'{fn} всё ещё зависит от разрешения'
        # Один общий контекст вместо нового на каждый сигнал.
        assert 'function audioCtx(' in APP_JS
        assert APP_JS.count('new (window.AudioContext') == 0
        assert "[[880, 1760]]" in APP_JS, 'звук города'
        assert '[523, 659, 784, [1047, 2093]]' in APP_JS, 'финальная мелодия'

    def test_settings_key_and_per_type_gate(self):
        assert "const NOTIFY_KEY = 'notifications_settings'" in APP_JS
        assert 'function notifyAllowed(' in APP_JS
        assert 'function notifyCityComplete(' in APP_JS
        assert 'function notifySearchComplete(' in APP_JS
        # Триггеры больше не смотрят на общий флаг напрямую.
        assert 'notifyCityComplete({ name, idx, total, status, records })' in APP_JS
        assert 'notifySearchComplete({' in APP_JS
        assert APP_JS.count("notificationsEnabled && Notification") == 0
