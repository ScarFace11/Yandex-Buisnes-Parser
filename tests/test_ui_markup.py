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

    def test_sound_pickers_and_volume_slider_are_in_the_popover(self):
        for needle in ('id="notify-sound-city"', 'id="notify-sound-search"',
                       'id="notify-play-city"', 'id="notify-play-search"',
                       'id="notify-volume"', 'id="notify-vol-val"'):
            assert needle in TEMPLATE, needle
        assert 'type="range"' in TEMPLATE, 'нет ползунка громкости'
        # Кнопка «Прослушать» на каждый тип события.
        assert TEMPLATE.count('onclick="previewNotifySound(') == 2
        assert 'onchange="notifySoundChanged(\'city\')"' in TEMPLATE
        assert 'onchange="notifySoundChanged(\'search\')"' in TEMPLATE
        assert 'oninput="notifyVolumeInput()"' in TEMPLATE
        assert 'onchange="notifyVolumeCommit()"' in TEMPLATE

    def test_presets_live_in_one_registry_and_stay_pure_code(self):
        """Пресеты — только тоны Web Audio: ни .mp3, ни base64 в разметке."""
        assert 'const SOUND_PRESETS = {' in APP_JS
        assert 'const SOUND_DEFAULTS' in APP_JS
        assert 'const VOLUME_DEFAULT' in APP_JS
        for fn in ('_fillSoundSelect', 'previewNotifySound', 'notifySoundChanged',
                   'playNotifySound', 'notifyVolumeInput', 'notifyVolumeCommit'):
            assert 'function ' + fn + '(' in APP_JS, fn
        # Звук синтезируется кодом: ни файлов, ни base64-вложений.
        assert 'data:audio' not in APP_JS
        assert 'new Audio(' not in APP_JS
        # Пресетов несколько и подписи — в реестре, а не в разметке.
        assert APP_JS.count('label:') >= 4
        assert 'id="notify-sound-city" aria-label' in TEMPLATE

    def test_volume_and_preset_are_persisted_with_the_type_flags(self):
        for key in ('volume:', 'sound_city:', 'sound_search:'):
            assert key in APP_JS, key
        # Громкость 0 — валидная настройка: exponentialRamp от нуля уронил бы звук.
        assert 'Math.max(0.0001' in APP_JS
        assert 'function _notifyVolume(' in APP_JS
        assert 'function _notifySound(' in APP_JS

    def test_header_button_base_does_not_leak_into_the_popover(self):
        """Попап живёт ВНУТРИ .hdr-right, и базовый стиль кнопок шапки
        (прозрачный фон + белая рамка) перебивал его содержимое: тумблеры
        теряли фон, «Сохранить» становился белым на белом в светлой теме,
        «▶» — белой стрелкой на белой карточке. Селектор шапки теперь только
        по прямым детям.
        """
        assert '.hdr-right > button,' in STYLE
        assert '.hdr-right .notify-wrap > button' in STYLE, 'кнопка уведомлений потеряла вид'
        assert '.hdr-right button{' not in STYLE, 'базовое правило снова ловит попап'
        assert '.hdr-right button,' not in STYLE.replace('.hdr-right > button,', '')

    def test_popover_controls_declare_their_own_look(self):
        """Фон, рамка и цвет у тумблера, «Сохранить» и «▶» — свои."""
        for sel in ('.notify-save{', '.notify-play{', '.tgl{', '.notify-snd select{'):
            block = STYLE[STYLE.index(sel) + len(sel):]
            block = block[: block.index('}')]
            assert 'background' in block, sel
            assert 'font-family:inherit' in block or sel == '.tgl{', sel
        for sel in ('.notify-save{', '.notify-play{'):
            block = STYLE[STYLE.index(sel) + len(sel):]
            block = block[: block.index('}')]
            assert 'color:var' in block, sel

    def test_sound_row_styles_use_theme_tokens(self):
        assert '.notify-snd{' in STYLE and '.notify-play{' in STYLE
        assert '.notify-row-vol input[type="range"]' in STYLE
        assert '.notify-vol-val{' in STYLE
        assert 'accent-color:var(--c)' in STYLE


class TestFilterAccordionGroups:
    """«Фильтрация результата»: группы вместо одиннадцати блоков подряд.

    Аккордеон читался как один длинный список, редкие настройки тонули в
    середине, а кнопка «Применить фильтры заново» уезжала за нижнюю кромку
    сайдбора. Теперь это группы с подзаголовками, «⚙️ Дополнительно»
    свёрнуто по умолчанию, а действие — в sticky-футере.
    """

    def _section(self) -> str:
        """Разметка одного аккордеона «03. Фильтрация результата»."""
        body = TEMPLATE[TEMPLATE.index('id="acc-filters"'):]
        return body[: body.index("</section>")]

    def _rule(self, selector: str) -> str:
        assert selector in STYLE, f"нет правила {selector}"
        block = STYLE[STYLE.index(selector) + len(selector):]
        return block[: block.index("}")]

    def test_groups_with_subtitles(self):
        sec = self._section()
        for title in ("🎯 Качество", "📊 Оценка лида", "🔍 Активность", "🔧 Обработка",
                      "🚫 Исключить по словам"):
            assert f'<div class="flt-group-title">{title}</div>' in sec, title
        assert sec.count('class="flt-group"') == 5
        # Порядок — от частого к редкому: оценка лида идёт ПЕРЕД активностью ВК.
        assert sec.index("📊 Оценка лида") < sec.index("🔍 Активность")

    def test_every_control_survived_the_regrouping(self):
        sec = self._section()
        for needle in ('id="parse-mode-hint"', 'id="social-mode-hint"',
                       'id="social-network-filter"', 'id="social-net-chk-grid"',
                       'id="social-net-hint"', 'id="f-vk-check"', 'id="vk-check-hint"',
                       'id="vk-filter-block"', 'id="f-vk-max-days"', 'id="f-vk-min-followers"',
                       'id="f-sort-score"', 'id="f-min-score"', 'id="score-presets"',
                       'id="score-hint"', 'id="f-collapse-chains"', 'id="f-chain-key"',
                       'id="f-raw-mode"', 'id="btn-refilter"'):
            assert needle in sec, f"{needle} потерялся при перегруппировке"
        for needle in ('name="parse_mode"', 'name="social_mode"', 'name="vk_mode"'):
            assert needle in sec, needle
        # Режимы свёрнутых блоков обрабатывает тот же appendLog/JS — id плиток
        # и грид соцсетей читает initSocialNetCheckboxes.
        assert 'class="parse-mode-opt active"' in sec
        assert 'class="score-preset active"' in sec

    def test_socials_are_one_block_with_nested_tiles(self):
        """«Соцсети в результате» + «Обязательные соцсети» — один блок."""
        sec = self._section()
        social = sec.index("Соцсети в результате")
        vk = sec.index("Проверять активность ВКонтакте")
        tiles = sec.index('id="social-network-filter"')
        next_group = sec.index("📊 Оценка лида")
        assert social < tiles < next_group < vk, "плитки обязательных соцсетей оторвались от режима"
        # Между режимом и плитками нет границы группы — это ОДИН блок.
        assert "flt-group-title" not in sec[social:tiles], "соцсети снова стали двумя пунктами"
        assert "Обязательные соцсети" in sec[tiles:next_group]
        # Плитки по-прежнему раскрываются классом .open из setSocialMode.
        assert 'class="tiles-reveal"' in sec[tiles:next_group]
        assert '<div class="tiles-grid" id="social-net-chk-grid"></div>' in sec[tiles:next_group]
        assert "netFilter.classList.toggle('open', mode === 'with_socials')" in APP_JS

    def test_group_title_looks_like_the_sidebar_group_title(self):
        rule = self._rule(".flt-group-title{")
        assert "font-size:11px" in rule
        assert "text-transform:uppercase" in rule
        assert "color:var(--muted)" in rule
        assert "border-left:3px solid var(--c)" in rule
        assert "padding:0 0 8px 9px" in rule, "16/8 из макета: сверху группу отбивает .flt-group"
        body = self._rule(".flt-group-body{")
        assert "gap:12px" in body
        assert ".flt-group{padding-top:16px}" in STYLE
        assert ".flt-group+.flt-group{border-top:1px solid var(--bdr);margin-top:16px}" in STYLE

    def test_rare_settings_are_collapsed_by_default(self):
        sec = self._section()
        assert '<details class="flt-extra" id="filters-extra">' in sec
        assert "<summary>⚙️ Дополнительно</summary>" in sec
        # Свёрнуто: атрибута open у <details> нет (разметка, а не CSS).
        at = sec.index('id="filters-extra"')
        tag = sec[sec.rindex("<details", 0, at): sec.index(">", at) + 1]
        assert "open" not in tag, f"«Дополнительно» должно быть свёрнуто: {tag}"
        assert sec.count('id="filters-extra"') == 1
        box = sec[sec.index('id="filters-extra"'):]
        box = box[: box.index("</details>")]
        for needle in ('id="f-chain-key"', 'id="f-raw-mode"'):
            assert needle in box, f"{needle} должен жить в «⚙️ Дополнительно»"
        # Значения селектов — контракт для refilterNow/preset-ов.
        assert '<option value="name_city" selected>' in box
        assert '<option value="keep" selected>' in box
        rule = self._rule(".flt-extra-body{")
        assert "padding:11px" in rule

    def test_footer_is_the_last_block_and_carries_the_action(self):
        sec = self._section()
        footer = sec.index('class="flt-footer"')
        assert sec.index('</details>') < footer, "футер должен идти после «Дополнительно»"
        assert 'id="btn-refilter"' in sec[footer:]
        assert 'onclick="refilterNow()"' in sec[footer:]
        assert "🔄 Применить фильтры заново</button>" in sec[footer:]
        assert "refilterNow()" in sec[footer:]
        # Футер — последний блок аккордеона: после него ни групп, ни настроек.
        assert "flt-group-title" not in sec[footer:]
        assert sec.count('class="flt-footer"') == 1

    def test_sticky_footer_parks_above_the_dock(self):
        rule = self._rule(".flt-footer{")
        assert "position:sticky" in rule
        assert "bottom:calc(var(--dock-h" in rule
        assert "z-index:5" in rule
        assert "background:var(--card)" in rule
        assert "box-shadow:0 -4px 12px" in rule
        assert "margin:16px -13px 0" in rule, "футер должен быть во всю ширину аккордеона"
        assert "width:100%" in self._rule(".flt-footer #btn-refilter{")
        # Запасное значение токена + ноль на телефоне (там док статичный).
        assert ":root{--dock-h:62px}" in STYLE
        assert "@media(max-width:860px){:root{--dock-h:0px}}" in STYLE
        assert "@media(max-width:860px){#run-dock{position:static}}" in STYLE

    def test_sticky_needs_clip_where_hidden_would_kill_it(self):
        """overflow:hidden у предка делает его скролл-портом: футер «прилипал» бы
        к самому аккордеону и не сдвинулся бы ни на пиксель."""
        assert "#acc-filters{overflow:clip}" in STYLE
        assert "#acc-filters .acc-body>.acc-inner{overflow:clip}" in STYLE
        assert "#acc-filters{overflow:hidden}" not in STYLE
        assert "#acc-filters .acc-body>.acc-inner{overflow:hidden}" not in STYLE
        # Ритм групп задаёт сам аккордеон, а не flex-gap (иначе разделитель
        # получал бы 13px сверху и 13px снизу вместо 16/16).
        assert "#acc-filters .acc-inner{gap:0;padding-bottom:0}" in STYLE

    def test_js_measures_the_dock_instead_of_hard_coding_it(self):
        assert "function syncDockHeight()" in APP_JS
        assert "root.style.setProperty('--dock-h'" in APP_JS
        assert "dock.offsetHeight" in APP_JS
        assert "syncDockHeight();" in APP_JS
        assert "addEventListener('resize', syncDockHeight)" in APP_JS
        assert "new ResizeObserver(syncDockHeight).observe(_dockEl)" in APP_JS


class TestBlacklistChips:
    """«🚫 Исключить по словам»: чипы, шаблоны и счётчик в аккордеоне 03.

    Логику (валидация, storage, debounce, шаблоны) ловят node-тесты в
    tests/ui/blacklist.test.mjs, а здесь — то, что живёт только в разметке
    и стилях: id-контракты обработчиков, отсутствие обрезки на поле и
    токены темы.
    """

    def _section(self) -> str:
        body = TEMPLATE[TEMPLATE.index('id="acc-filters"'):]
        return body[: body.index("</section>")]

    def _rule(self, selector: str) -> str:
        assert selector in STYLE, f"нет правила {selector}"
        block = STYLE[STYLE.index(selector) + len(selector):]
        return block[: block.index("}")]

    def test_block_has_its_own_group_and_every_control(self):
        sec = self._section()
        assert '<div class="flt-group-title">🚫 Исключить по словам</div>' in sec
        for needle in ('id="blacklist-chips"', 'id="f-blacklist-input"',
                       'id="btn-blacklist-add"', 'id="btn-blacklist-save"',
                       'id="btn-blacklist-clear"', 'id="blacklist-template"',
                       'id="blacklist-count"', 'id="blacklist-err"'):
            assert needle in sec, needle
        for handler in ('onclick="addBlacklistFromField()"', 'onkeydown="onBlacklistKey(event)"',
                        'onclick="openBlacklistSaveModal()"', 'onclick="clearBlacklist()"',
                        'onclick="toggleBlacklistDropdown(event)"'):
            assert handler in sec, handler

    def test_block_sits_before_the_advanced_box_and_the_footer(self):
        """Список — обычная группа: редкое живёт в «Дополнительно», а действие — в
        футере, поэтому исключения не должны оказаться после них."""
        sec = self._section()
        block = sec.index('id="blacklist-chips"')
        assert block < sec.index('id="filters-extra"')
        assert block < sec.index('class="flt-footer"')
        # и после групп качества/оценки/активности/обработки
        assert block > sec.index("🔧 Обработка")

    def test_copy_and_limits_live_in_the_markup(self):
        sec = self._section()
        assert 'Добавьте слова, которые исключат компанию' in sec
        assert 'Добавьте слово и нажмите Enter или +' in sec
        assert 'Слова ищутся в названии и категории. Регистр не важен.' in sec
        assert '💾 Сохранить список' in sec and '🗑 Очистить список' in sec
        assert '📂 Загрузить шаблон' in sec
        # Поле НЕ ограничивает длину: maxlength обрезал бы вставленный список
        # слов до 50 символов. Лимит на одно слово проверяет JS
        # (BLACKLIST_MAX_LEN), а не атрибут поля.
        assert 'maxlength=' not in sec
        assert 'Таблица и файлы обновятся после «Применить фильтры заново».' in sec

    def test_template_options_are_built_from_the_registry(self):
        """Дропдаун — кастомный (у select не бывает кнопок в опциях): в разметке
        только кнопка и пустая панель, содержимое строит JS из реестра."""
        sec = self._section()
        dd = sec[sec.index('id="blacklist-dd"'):]
        dd = dd[: dd.index('id="blacklist-tpl-hint"')]
        assert 'id="blacklist-dd-panel" hidden' in dd
        assert '<option' not in dd, "опции рисует JS — в разметке их нет"
        assert "const BLACKLIST_TEMPLATES = {" in APP_JS
        assert "function fillBlacklistTemplateSelect(" in APP_JS
        assert "function toggleBlacklistDropdown(" in APP_JS
        assert "function closeBlacklistDropdown(" in APP_JS
        assert "function renderBlacklistListManage(" in APP_JS
        assert 'data-act="edit"' in APP_JS and 'data-act="del"' in APP_JS

    def test_chips_follow_the_design_and_the_theme_tokens(self):
        chips = self._rule(".bl-chips{")
        assert "flex-wrap:wrap" in chips
        assert "max-height:150px" in chips
        assert "overflow-y:auto" in chips
        chip = self._rule(".bl-chip{")
        assert "border-radius:6px" in chip
        assert "background:var(--chip-bg)" in chip
        assert "color:var(--chip-txt)" in chip
        # Анимация — только у свежедобавленных чипов (.bl-new): базовый чип
        # сам не анимируется, иначе перерисовка списка прыгала бы целиком.
        assert "animation:" not in chip, "базовый .bl-chip не анимируется сам"
        assert "animation:bl-chip-in .15s" in self._rule(".bl-chip.bl-new{"), \
            "появление нового чипа — scale + fade (0.15s)"
        assert "@keyframes bl-chip-in{" in STYLE
        assert "scale(.9)" in STYLE
        assert ".bl-chip .bl-chip-x:hover{color:var(--err-strong)}" in STYLE
        assert ".bl-chip.bl-out{opacity:0;transform:translateX(-6px)}" in STYLE
        # Ни одного hex-литерала в правилах — цвет переключается токенами темы.
        for rule in (".bl-chips{", ".bl-chip{", ".bl-chip .bl-chip-x{"):
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", self._rule(rule)), rule

    def test_chip_tokens_are_declared_for_both_themes(self):
        light = STYLE[STYLE.index(":root{"):]
        light = light[: light.index("\n}")]
        dark = DARK_TOKEN_BLOCK[: DARK_TOKEN_BLOCK.index("\n}")]
        for token in ("--chip-bg:", "--chip-txt:"):
            assert token in light, f"{token} не объявлен в светлой теме"
            assert token in dark, f"{token} не объявлен в тёмной теме"
        # Плашка из макета (#F3F4F6 / #374151) — светлая тема; в тёмной
        # нейтральный Gray-700 выбивался бы из графитовой палитры.
        assert "--chip-bg:#F3F4F6" in light and "--chip-txt:#374151" in light

    def test_storage_key_and_handlers_are_wired(self):
        assert "const BLACKLIST_KEY = 'blacklist_words'" in APP_JS
        assert "version: BLACKLIST_VERSION" in APP_JS
        assert "updated_at: new Date().toISOString()" in APP_JS
        for fn in ("normalizeBlacklist", "parseBlacklistInput", "addBlacklistWords",
                   "removeBlacklistWord", "clearBlacklist", "applyBlacklistTemplate",
                   "loadBlacklistWords", "setBlacklistWords", "previewBlacklist",
                   "saveBlacklistNow"):
            assert f"function {fn}(" in APP_JS, fn
        assert "'/preview-blacklist'" in APP_JS
        assert "function onBlacklistChipKey(" in APP_JS, "крестик доступен с клавиатуры"
        assert 'onkeydown="onBlacklistChipKey(event,' in APP_JS
        # Живой счётчик исключений ленивый: на загрузке — только число слов,
        # запрос уходит при открытии раздела (acc-filters).
        assert "scheduleBlacklistPreview" in APP_JS
        assert "loadBlacklistWords();" in APP_JS
        assert "renderBlacklistChips({preview: false})" in APP_JS
        assert "sec.id === 'acc-filters'" in APP_JS
        assert "_blAnimateWords" in APP_JS


class TestMessageTemplates:
    """«📝 Шаблоны»: вкладка, панель, модалка и интеграции в разметке.

    Логику (подстановка, карточки, очередь, импорт) ловят node-тесты в
    tests/ui/templates.test.mjs, а здесь — id-контракты обработчиков,
    порядок вкладки и стили/тема.
    """

    def _panel(self) -> str:
        body = TEMPLATE[TEMPLATE.index('id="p-templates"'):]
        return body[: body.index('id="p-excel"')]

    def test_tab_sits_between_history_and_export(self):
        assert 'id="t-templates"' in TEMPLATE
        assert 'onclick="showTab(\'templates\')"' in TEMPLATE
        assert TEMPLATE.index('id="t-history"') < TEMPLATE.index('id="t-templates"') \
            < TEMPLATE.index('id="t-excel"')
        assert 'id="p-templates"' in TEMPLATE

    def test_panel_has_every_control(self):
        sec = self._panel()
        for needle in ('id="tpl-list"', 'id="tpl-var-list"', 'id="tpl-show-missing"',
                       'id="btn-tpl-import"', 'id="btn-tpl-export"', 'id="btn-tpl-reset"',
                       'id="btn-tpl-add"', 'id="tpl-import-file"'):
            assert needle in sec, needle
        for handler in ('filterTemplatesByCategory(', 'importTemplates(', 'exportTemplates()',
                        'resetTemplates()', 'openTemplateModal()', 'onShowMissingChange()'):
            assert handler in sec, handler

    def test_edit_modal_has_fields_and_variable_insert(self):
        for needle in ('id="tpl-modal"', 'id="tpl-name"', 'id="tpl-category"',
                       'id="tpl-text"', 'id="tpl-var-insert"', 'id="tpl-preview-body"',
                       'id="tpl-modal-err"'):
            assert needle in TEMPLATE, needle
        assert 'onclick="saveTemplateFromModal()"' in TEMPLATE
        assert 'onclick="closeTemplateModal()"' in TEMPLATE
        assert 'oninput="updateTemplatePreview()"' in TEMPLATE

    def test_category_filter_covers_four_networks(self):
        sec = self._panel()
        for cat in ('all', 'vk', 'telegram', 'whatsapp', 'instagram'):
            assert 'data-cat="' + cat + '"' in sec, cat

    def test_table_bulk_and_sender_pickers_exist(self):
        assert 'id="tbl-template"' in TEMPLATE
        assert 'id="bulk-template"' in TEMPLATE
        assert 'id="s-template"' in TEMPLATE
        assert 'id="bulk-queue"' in TEMPLATE
        assert 'onclick="fillSenderFromTemplate()"' in TEMPLATE

    def test_client_wires_handlers_and_endpoints(self):
        for fn in ('loadTemplates', 'renderTemplates', 'openTemplateModal', 'saveTemplateFromModal',
                   'substituteTemplate', 'usedVariables', 'importTemplates', 'exportTemplates',
                   'resetTemplates', 'uiChoose', 'onSocialBadgeClick', 'renderBulkQueue',
                   'bulkCopyNext', 'getActiveTemplateFor', 'setActiveTemplate', 'onShowMissingChange'):
            assert f'function {fn}(' in APP_JS, fn
        assert "'/templates'" in APP_JS
        assert "'/templates/reset'" in APP_JS
        assert 'data-act="edit"' in APP_JS

    def test_substitution_supports_cyrillic_alias(self):
        # \w в JS не покрывает кириллицу — {название_бизнеса} иначе не заменится.
        assert 'А-Яа-я' in APP_JS
        assert "'название_бизнеса': 'name'" in APP_JS

    def test_cards_and_queue_are_styled(self):
        for rule in ('.template-card{', '.template-actions{', '.bulk-queue{', '.tpl-modal{'):
            assert rule in STYLE, rule
        assert '.template-card:hover .template-actions' in STYLE
        assert 'white-space:pre-wrap' in STYLE
        assert '[data-theme="dark"] .template-card' in STYLE
        assert '[data-theme="dark"] .bulk-queue' in STYLE

    def test_server_endpoints_and_module_exist(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        assert '@bp.route("/templates", methods=["GET"])' in api
        assert '@bp.route("/templates", methods=["POST"])' in api
        assert '@bp.route("/templates/reset", methods=["POST"])' in api
        mod = (ROOT / "yandex_maps_parser" / "message_templates.py").read_text(encoding="utf-8")
        for fn in ('def substitute(', 'def normalize_templates(', 'def normalize_active_ids(',
                   'def migrate_templates(', 'def load_templates(', 'def save_templates('):
            assert fn in mod, fn
        assert 'active_template_ids' in mod


class TestBulkCrawlOrder:
    """«Массовый обход» открывает профили в том же порядке, что и таблица.

    Регрессия: сервер отдавал записи в порядке файла, поэтому очередь
    начиналась не с самых горячих, хотя таблица отсортирована по оценке.
    """

    def test_panel_tells_the_user_the_order(self):
        assert 'id="bulk-order-note"' in TEMPLATE
        assert 'function bulkOrderLabel(' in APP_JS
        assert 'function bulkSortSpec(' in APP_JS
        assert '.bulk-order{' in STYLE

    def test_client_sends_the_table_sort_to_the_server(self):
        assert 'sort_col: sort.col,' in APP_JS
        assert 'sort_asc: sort.asc,' in APP_JS
        assert 'sort_col: p.sort_col, sort_asc: p.sort_asc' in APP_JS

    def test_server_sorts_records_the_way_the_table_shows_them(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        for fn in ('def _sort_like_table(', 'def _lead_score_num('):
            assert fn in api, fn
        assert '_sort_like_table(_collect_records(' in api
        assert 'sort_col' in api and 'sort_asc' in api
        # 6 — оценка лида, 2..5 — название/категория/адрес/телефон (sortTable).
        assert '_VIEW_SORT_KEYS = {2: "name", 3: "category", 4: "address", 5: "phone"}' in api

    def test_refiltering_drops_a_stale_column_sort(self):
        body = APP_JS[APP_JS.index('function filterTable('):]
        body = body[: body.index('function minScoreThreshold(')]
        assert 'sortCol = -1;' in body, 'стрелка в шапке разошлась бы с порядком строк'
        assert 'sortAsc = true;' in body
