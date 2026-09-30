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
API_PY = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
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
        assert 'id="bulk-persist-btn"' in TEMPLATE
        assert "Сохранить сейчас</button>" in TEMPLATE
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
        """Тёмная тема — графит и мягкий светлый текст, а не #000/#fff.

        Значения менялись (2026-09: фон стал ровнее, без синего уклона),
        но правило осталось: чистого чёрного и чистого белого в теме нет.
        """
        block = DARK_TOKEN_BLOCK[:DARK_TOKEN_BLOCK.index("\n}")]
        assert "--bg:#101216" in block
        assert "--txt:#E6E9EF" in block

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
        # «Вкл» остаётся зелёным, но не неоновым: эмеральд #10B981 из макета был
        # самым насыщенным пятном на нейтральном экране. Проверяем сам смысл:
        # зелёный канал ведёт, а разброс каналов умеренный.
        for block in (light, dark):
            hexv = re.search(r'--tgl-on:\s*(#[0-9a-fA-F]{6})', block).group(1)
            r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
            assert g > r and g > b, f'тумблер «вкл» должен быть зелёным: {hexv}'
            assert max(r, g, b) - min(r, g, b) < 140, f'«вкл» слишком насыщенный: {hexv}'

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
    сайдбора. Теперь это группы с подзаголовками, «Дополнительно»
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

    @staticmethod
    def _title(name: str) -> str:
        """Подзаголовок группы — без значков: эмодзи ушли из подписей."""
        return f'<div class="flt-group-title">{name}</div>'

    def test_groups_with_subtitles(self):
        sec = self._section()
        for name in ("Качество", "Тип компании", "Оценка лида", "Активность",
                     "Обработка", "Исключить по словам"):
            assert self._title(name) in sec, name
        assert sec.count('class="flt-group"') == 6
        # Порядок — от частого к редкому: оценка лида идёт ПЕРЕД активностью ВК.
        assert sec.index(self._title("Оценка лида")) < sec.index(self._title("Активность"))
        # «Тип компании» — про самого клиента, а не про качество данных:
        # стоит сразу после соцсетей и до оценки лида.
        assert sec.index(self._title("Тип компании")) < sec.index(self._title("Оценка лида"))

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
        next_group = sec.index(self._title("Оценка лида"))
        assert social < tiles < next_group < vk, "плитки обязательных соцсетей оторвались от режима"
        # Между режимом и плитками нет границы группы — это ОДИН блок.
        assert "flt-group-title" not in sec[social:tiles], "соцсети снова стали двумя пунктами"
        assert "Обязательные соцсети" in sec[tiles:next_group]
        # Плитки по-прежнему раскрываются классом .open из setSocialMode.
        assert 'class="tiles-reveal"' in sec[tiles:next_group]
        assert '<div class="tiles-grid" id="social-net-chk-grid"></div>' in sec[tiles:next_group]
        assert "netFilter.classList.toggle('open', mode === 'with_socials')" in APP_JS

    def test_company_type_group(self):
        """«🎯 Тип компании»: одиночки, новые с периодом и счётчик «подойдёт»."""
        sec = self._section()
        group = sec[sec.index(self._title("Тип компании")): sec.index(self._title("Оценка лида"))]
        for needle in ('id="f-only-single"', 'id="f-only-new"', 'id="f-new-months"',
                       'id="company-type-new-row"', 'id="company-type-count"'):
            assert needle in group, needle
        assert 'onchange="onCompanyTypeChange()"' in group
        # Чекбоксы стилизованы как везде в аккордеоне (класс .chk).
        assert group.count('<label class="chk">') == 2
        # Периоды — только из серверного реестра COMPANY_TYPE_MONTHS, дефолт 6.
        import re as _re
        values = _re.findall(r'<option value="(\d+)"', group)
        assert values == ["1", "3", "6", "12", "24"], values
        assert '<option value="6" selected>' in group
        assert 'role="status"' in group, "счётчик озвучивается скринридером"
        # Тексты объясняют, что именно фильтруется и что данные могут быть
        # неполными (даты добавления у Яндекса нет вовсе).
        assert "Компании с 1 филиалом" in group
        assert "базе 2ГИС" in group and "даты нет" in group

    def test_company_type_group_styles(self):
        """Период гаснет без своего чекбокса, счётчик читается в обеих темах."""
        row = self._rule(".ct-new-row{")
        assert "opacity:.4" in row and "pointer-events:none" in row
        assert "opacity:1" in self._rule(".ct-new-row.on{")
        count = self._rule(".ct-count{")
        assert "var(--bdr)" in count and "var(--row-alt)" in count
        assert ".ct-count.on{" in STYLE
        # Мобильная версия ≤860px: строка периода не сдвигается вправо и
        # растягивается на всю ширину сайдбора.
        assert ".ct-new-row{margin-left:0}" in STYLE
        assert ".ct-new-row select{flex:1 1 100%}" in STYLE

    def test_company_type_counter_is_wired(self):
        """Счётчик ленивый, а оба фильтра уезжают и в запуск, и в рефильтр."""
        for fn in ("onlySingleChecked", "newMonthsValue", "newMonthsPeriod",
                   "companyTypeOn", "syncCompanyTypeUi", "onCompanyTypeChange",
                   "scheduleCompanyTypePreview", "previewCompanyType",
                   "companyTypeCountHTML"):
            assert f"function {fn}(" in APP_JS, fn
        assert "'/preview-company-type'" in APP_JS
        # Два пути: обычный запуск (getParams) и «Применить фильтры заново».
        assert APP_JS.count("only_single_branch: onlySingleChecked()") == 2
        assert APP_JS.count("only_new_months:    newMonthsValue()") == 2
        # Как и чёрный список — только при открытии раздела.
        assert "scheduleCompanyTypePreview();" in APP_JS
        # Реестр периодов в браузере совпадает с серверным COMPANY_TYPE_MONTHS.
        import re as _re
        decl = _re.search(r"const COMPANY_TYPE_PERIODS = \{(.*?)\};\n", APP_JS, _re.S)
        assert decl, "нет реестра периодов в app.js"
        assert [int(n) for n in _re.findall(r"(\d+):", decl.group(1))] == [1, 3, 6, 12, 24]

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
        # Подпись без эмодзи: значки в подписях и кнопках — инлайновый SVG
        # (.ico), эмодзи рисовались цветными на Windows и монохромно на macOS.
        assert "Дополнительно</summary>" in sec
        assert "<summary><svg class=\"ico\"" in sec
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
        assert "Применить фильтры заново</button>" in sec[footer:]
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
        assert '<div class="flt-group-title">Исключить по словам</div>' in sec
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
        assert block > sec.index('<div class="flt-group-title">Обработка</div>')

    def test_copy_and_limits_live_in_the_markup(self):
        sec = self._section()
        assert 'Добавьте слова, которые исключат компанию' in sec
        assert 'Добавьте слово и нажмите Enter или +' in sec
        assert 'Слова ищутся в названии и категории. Регистр не важен.' in sec
        # Кнопки списка — с SVG-значками вместо эмодзи.
        assert 'Сохранить список</button>' in sec and 'Очистить список</button>' in sec
        assert 'Загрузить шаблон</button>' in sec
        assert sec.count('<svg class="ico"') >= 3, "у кнопок списка должны быть значки"
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
        # Ввод живёт в onTemplateTextInput: он и превью обновляет,
        # и автодополнение открывает.
        assert 'oninput="onTemplateTextInput()"' in TEMPLATE

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

    def test_bulk_delete_controls_in_markup_and_js(self):
        sec = self._panel()
        assert 'id="btn-tpl-del-selected"' in sec
        assert 'deleteSelectedTemplates()' in sec
        assert 'toggleSelectAllTemplates()' in sec
        for fn in ('deleteSelectedTemplates', 'toggleTemplateSelected',
                   'toggleSelectAllTemplates', 'pruneTemplateSelection'):
            assert f'function {fn}(' in APP_JS, fn
        assert "data-tpl-check" in APP_JS

    def test_autocomplete_in_markup_and_js(self):
        sec = self._panel()
        assert 'id="tpl-autocomplete"' in sec
        assert 'oninput="onTemplateTextInput()"' in TEMPLATE
        assert 'onkeydown="onTemplateTextKeydown(event)"' in TEMPLATE
        for fn in ('onTemplateTextInput', 'onTemplateTextKeydown',
                   'renderTemplateAutocomplete', 'applyTemplateAutocomplete',
                   'closeTemplateAutocomplete', 'allTemplateVars'):
            assert f'function {fn}(' in APP_JS, fn

    def test_custom_vars_subtab_and_modal(self):
        sec = self._panel()
        # Переключатель подвкладок и панель переменных.
        assert "showTplSubtab('vars')" in sec
        assert 'id="tpl-pane-vars"' in sec
        assert 'id="tpl-var-cards"' in sec
        assert 'openVarModal()' in sec
        # Модалка переменной: имя, источник (текст/столбец), описание.
        for needle in ('id="tpl-var-modal"', 'id="tpl-var-name"', 'id="tpl-var-source"',
                       'id="tpl-var-value"', 'id="tpl-var-column"', 'id="tpl-var-desc"'):
            assert needle in TEMPLATE, needle
        for fn in ('openVarModal', 'saveVarFromModal', 'closeVarModal',
                   'deleteCustomVar', 'onVarSourceChange'):
            assert f'function {fn}(' in APP_JS, fn

    def test_custom_vars_styled(self):
        for rule in ('.tpl-subtab{', '.tpl-var-card{', '.tpl-ac-box{',
                     '.tpl-card-chk{', '.tpl-var-name-row{'):
            assert rule in STYLE, rule
        assert '.tpl-ac-box[hidden]' in STYLE
        assert '[data-theme="dark"] .tpl-var-card' in STYLE

    def test_server_round_trips_custom_variables(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        assert 'custom_variables' in api
        mod = (ROOT / "yandex_maps_parser" / "message_templates.py").read_text(encoding="utf-8")
        assert 'def normalize_custom_variables(' in mod
        assert 'custom_variables' in mod

    def test_special_variables_in_both_mirrors(self):
        # Служебные переменные живут в Python и JS-зеркале синхронно.
        mod = (ROOT / "yandex_maps_parser" / "message_templates.py").read_text(encoding="utf-8")
        for needle in ('SPECIAL_VARIABLES = ("дата", "время", "приветствие")',
                       'def _special_value(', '_GREETING_PARTS'):
            assert needle in mod, needle
        for needle in ('const TEMPLATE_SPECIAL_VARS',
                       'function specialTemplateValue(',
                       'const TEMPLATE_GREETING_PARTS'):
            assert needle in APP_JS, needle

    def test_export_import_carry_custom_variables(self):
        assert 'custom_variables: customVariables' in APP_JS, "экспорт без переменных"
        assert 'function importCustomVariables(' in APP_JS
        assert 'function normalizeCustomVariablesClient(' in APP_JS
        assert 'parsed.custom_variables' in APP_JS

    def test_save_warns_about_unknown_variables(self):
        assert 'Неизвестные переменные' in APP_JS
        assert 'saveVarFromModal._varsWarned' in APP_JS


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


class TestDiagnosticsPanel:
    """«🩺 Диагностика»: кнопка в шапке, панель и защита от чужого сайта.

    Панель — ответ на «ничего не работает» для десктопной сборки, где нет
    консоли. Разметка тут проверяется целиком: кнопка, три вида проверок,
    предупреждение про квоту и то, что эндпоинт в JS совпадает с flask-роутом.
    """

    ROUTES = (ROOT / "routes" / "diagnostics.py").read_text(encoding="utf-8")

    def test_button_lives_between_logs_and_updates(self):
        logs = TEMPLATE.index('id="btn-logs"')
        diag = TEMPLATE.index('id="btn-diag"')
        updates = TEMPLATE.index('id="btn-updates"')
        assert logs < diag < updates
        assert 'onclick="showDiagnostics()"' in TEMPLATE

    def test_panel_offers_three_scopes(self):
        for needle in ("runDiagnostics(['keys','files','data','env'], this)",
                       "runDiagnostics(['keys'], this)",
                       "runDiagnostics(['files','data','env'], this)"):
            assert needle in APP_JS, needle

    def test_quota_warning_is_shown_before_the_click(self):
        assert "списывает 1–2 запроса" in APP_JS
        assert "onclick=\"closeDiagnostics()\"" in APP_JS

    def test_js_endpoint_matches_the_flask_route(self):
        assert "fetch('/diagnostics/run'" in APP_JS
        assert '@bp.route("/diagnostics/run", methods=["POST"])' in self.ROUTES

    def test_only_the_app_itself_can_run_it(self):
        """Проверка ключей тратит квоту 2ГИС: чужая страница нажать не может."""
        assert "def _only_from_our_ui(" in self.ROUTES
        assert '@bp.before_request' in self.ROUTES
        assert "request.is_json" in self.ROUTES

    def diagnostics_css(self) -> str:
        """Только блок правил панели — от первого .diag- до общей модалки."""
        block = STYLE[STYLE.index(".diag-modal{"):]
        return block[: block.index(".ui-modal p{")]

    def test_styles_cover_statuses_and_the_phone(self):
        css = self.diagnostics_css()
        for needle in (".diag-modal{", ".diag-summary-error{", ".diag-group-title{",
                       '.diag-row[data-status="error"]{'):
            assert needle in css, needle
        assert "@media(max-width:860px){" in css
        assert ".diag-actions .diag-run{flex:1 1 100%}" in css, "на телефоне кнопки в столбик"

    def test_no_hardcoded_colours_in_the_panel(self):
        css = self.diagnostics_css()
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css), "тёмная тема сломается"
        assert "rgba(" not in css, "тёмная тема сломается"


class TestDesignSystem:
    """Визуальная система: шрифт рядом с приложением, значки вместо эмодзи.

    Это не вкусовщина, а два измеримых свойства: (1) интерфейс обязан
    выглядеть одинаково на машине без доступа к Google Fonts, (2) в элементах
    управления не должно остаться эмодзи — на Windows они цветные и разной
    ширины, на macOS монохромные, из-за чего ряд кнопок разъезжался.
    """

    # Комментарии из разметки убираем: в них значки упоминаются словами.
    RENDERED = re.sub(r"<!--.*?-->", "", TEMPLATE, flags=re.S)
    HEADER = RENDERED[RENDERED.index("<header"):RENDERED.index("</header>")]
    # Верхняя панель лога — все кнопки журнала в одном месте.
    LOGBAR = RENDERED[RENDERED.index('class="term-top"'):RENDERED.index('class="log-empty"')]
    EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
    # Значок = ссылка на символ спрайта: одна форма на всю страницу.
    ICON = '<svg class="ico" aria-hidden="true"><use href="#i-'

    def test_font_ships_with_the_app(self):
        """Шрифт лежит рядом: без сети интерфейс не должен «уезжать»."""
        assert "fonts.googleapis" not in TEMPLATE
        assert "fonts.gstatic" not in TEMPLATE
        fonts = ROOT / "static" / "fonts"
        for name in ("manrope-cyrillic.woff2", "manrope-latin.woff2", "OFL.txt"):
            assert (fonts / name).is_file(), f"нет {name}"
        assert (fonts / "manrope-cyrillic.woff2").stat().st_size > 5000

    def test_font_faces_point_at_the_local_files(self):
        assert '@font-face{' in STYLE
        assert 'url("../fonts/manrope-cyrillic.woff2")' in STYLE
        assert 'url("../fonts/manrope-latin.woff2")' in STYLE
        assert STYLE.count('font-display:swap') >= 2, "текст не должен ждать шрифт"
        assert "font-family:var(--font-ui);" in STYLE

    def test_welcome_screen_does_not_inherit_the_monospace_log(self):
        """Первый экран живёт внутри #log-output, а тот моноширинный."""
        rule = STYLE[STYLE.index("#onboarding-screen,.onboarding,.flow-step{"):]
        assert "font-family:var(--font-ui)" in rule[:80]

    def test_icon_class_is_one_place(self):
        assert ".ico{" in STYLE
        rule = STYLE[STYLE.index(".ico{"):]
        rule = rule[: rule.index("}")]
        assert "stroke:currentColor" in rule, "значки должны наследовать цвет темы"
        assert "fill:none" in rule
        assert ".hdr-right .ico{" in STYLE

    def test_header_buttons_carry_svg_not_emoji(self):
        for bid in ("btn-logs", "btn-diag", "btn-updates"):
            start = self.HEADER.index(f'id="{bid}"')
            button = self.HEADER[start: self.HEADER.index("</button>", start)]
            assert self.ICON in button, f"{bid}: значок должен быть инлайновым SVG"
            assert not self.EMOJI.search(button), f"{bid}: вернулся эмодзи"

    def test_log_toolbar_carries_svg_not_emoji(self):
        for bid in ("btn-log-save", "btn-log-copy", "btn-clear-log"):
            assert self.ICON in self.LOGBAR, f"{bid}: нет значка"
        assert not self.EMOJI.search(self.LOGBAR), "в панели лога остались эмодзи"

    def test_eyebrow_labels_lost_their_emoji(self):
        for title in ("Сбор данных", "Вывод и фильтрация"):
            assert f'<div class="group-title">{title}</div>' in TEMPLATE
        # Ни один подзаголовок фильтров не начинается со значка.
        blocks = re.findall(r'<div class="(?:group-title|flt-group-title)">([^<]*)</div>',
                            self.RENDERED)
        assert blocks, "подзаголовки не найдены"
        for text in blocks:
            assert not self.EMOJI.search(text), f"эмодзи вернулся в подзаголовок: {text}"

    def test_js_built_chrome_uses_the_same_icon_map(self):
        assert "const UI_ICONS = {" in APP_JS
        for key in ("search", "pause", "bell", "sun", "moon"):
            assert f"{key}:" in APP_JS, key
        # Подписи, которые JS восстанавливает сам, тоже с иконкой.
        assert "const REFILTER_LABEL = UI_ICONS.refresh" in APP_JS
        assert "const UPDATE_BTN_IDLE = UI_ICONS.refresh" in APP_JS

    def test_narrow_phone_keeps_only_icons_in_the_header(self):
        """Шапка растягивала страницу вбок на телефоне (242px прокрутки).

        До 620px подписи второстепенных кнопок скрыты, но у каждой кнопки есть
        aria-label — иначе от кнопки остался бы безымянный значок.
        """
        for bid, label in (("btn-logs", "Логи"), ("btn-diag", "Диагностика"),
                           ("btn-updates", "Обновления")):
            start = self.HEADER.index(f'id="{bid}"')
            button = self.HEADER[start: self.HEADER.index("</button>", start)]
            assert f'<span class="hdr-lbl">{label}</span>' in button, bid
            assert f'aria-label="{label}"' in button, f"{bid}: подпись скрыта — нужен aria-label"
        assert "@media(max-width:620px){" in STYLE
        assert ".hdr-right > button .hdr-lbl{display:none}" in STYLE
        assert ".hdr-right > button .hdr-lbl{display:inline}" not in STYLE

    def test_js_labels_use_the_same_hidden_wrapper(self):
        """Кнопку «Обновления» рисует JS — обёртку .hdr-lbl он тоже обязан ставить."""
        assert '\'<span class="hdr-lbl">Обновления</span>\'' in APP_JS
        assert "'<span class=\"hdr-lbl\">Проверяю…</span>'" in APP_JS


class TestResultsTableDesign:
    """Таблица результатов держится на ролих палитры, а не на своих цветах.

    Здесь ловится регресс, который уже случался: липкая шапка была отдельной
    чёрной плитой со своими правилами для тёмной темы, зебра была почти
    неотличима от белого, а просмотренная строка гасла через opacity —
    и вместе с текстом гасла зебра под ней.
    """

    def _rule(self, selector: str) -> str:
        assert selector in STYLE, f"нет правила {selector}"
        block = STYLE[STYLE.index(selector) + len(selector):]
        return block[: block.index("}")]

    def test_header_is_sticky_and_painted_with_roles(self):
        head = self._rule("#results-table th{")
        assert "position:sticky" in head and "top:0" in head
        assert "z-index:2" in head, "шапку перекрывают бейджи строк"
        # Непрозрачный --card, а не --panel/--row-alt: под шапку уезжают
        # строки, и полупрозрачный или совпадающий с зеброй тон её терял.
        assert "background:var(--card)" in head and "color:var(--muted)" in head
        # Чёрная плита со белым текстом: была отдельная тема для тёмной.
        assert "--hdr" not in head and "--on-accent" not in head

    def test_header_tone_differs_from_the_zebra(self):
        """Регресс, который уже случался: --panel и --row-alt были одним тоном
        (#f7f8fa), и липкая шапка сливалась с чётными строками."""
        for start in (":root{", DARK_MARKER + "{"):
            block = STYLE[STYLE.index(start):]
            block = block[: block.index("\n}")]
            vals = dict(re.findall(r"(--card|--row-alt|--panel)\s*:\s*([^;]+);", block))
            assert vals["--card"] != vals["--row-alt"], vals
            assert vals["--panel"] != vals["--row-alt"], vals

    def test_header_needs_no_dark_override(self):
        assert '#results-table th{' not in dark_rule_lines()

    def test_zebra_and_hover_live_on_their_own_tokens(self):
        assert "#results-table tr:nth-child(even) td{background:var(--row-alt)}" in STYLE
        assert "#results-table tr:nth-child(even):hover td{background:var(--row-hover)}" in STYLE
        # Полоса, подсветка и сама карточка — три разных тона в каждой теме:
        # иначе зебра и курсор сливаются с фоном (так уже было: #fafbfc на #fff).
        for start in (":root{", DARK_MARKER + "{"):
            block = STYLE[STYLE.index(start):]
            block = block[: block.index("\n}")]
            vals = dict(re.findall(r"(--row-alt|--row-hover|--card)\s*:\s*([^;]+);", block))
            assert len(vals) == 3, vals
            assert len(set(vals.values())) == 3, f"тона совпали: {vals}"

    def test_reviewed_row_dims_by_colour_not_opacity(self):
        # --sub, а не --muted: на зебре и под курсором тихий --muted уходит
        # ниже 4.5:1 (см. PAIRS в tests/test_theme_contrast.py).
        assert "#results-table tr.is-reviewed td{color:var(--sub)}" in STYLE
        assert "opacity" not in self._rule("#results-table tr.is-reviewed td{")

    def test_table_needs_no_dark_theme_rules_at_all(self):
        """Таблица читает роли — значит, в тёмной теме у неё нет своих правил."""
        assert "#results-table" not in dark_rule_lines()

    def test_row_text_uses_classes_not_inline_colours(self):
        assert 'class="tbl-link"' in APP_JS and 'class="tbl-cat"' in APP_JS
        assert "style=\"color:var(--g)" not in APP_JS
        assert ".tbl-link{color:var(--c);font-weight:600" in STYLE
        # Служебный текст строки — --sub: на тонированной поверхности зебры
        # и наведения --muted не добирает контраста.
        assert ".tbl-cat{color:var(--sub)}" in STYLE
        assert ".score-na{color:var(--sub)}" in STYLE

    def test_density_keeps_service_columns_readable(self):
        cell = self._rule("\n#results-table td{")
        assert "vertical-align:top" in cell and "border-bottom:1px solid var(--bdr-soft)" in cell
        # Бейджи строки выровнены по центру, а не по верхней кромке.
        assert "#results-table td:nth-child(7),#results-table td:nth-child(8)" in STYLE
        assert "#results-table td:nth-child(6){white-space:nowrap}" in STYLE

    def test_one_scrim_for_every_modal(self):
        """Четыре модалки — одно затемнение: раньше у каждой был свой rgba."""
        for overlay in (".skip-modal-overlay{", ".logs-modal-overlay{",
                        ".ui-modal-overlay{", ".tpl-modal-overlay{"):
            assert "background:var(--scrim)" in self._rule(overlay), overlay

    def test_popups_share_the_radius_and_shadow_ladder(self):
        for sel in (".tpl-modal{", ".city-dropdown{", "#col-dropdown{", ".tpl-ac-box{"):
            rule = self._rule(sel)
            assert "var(--r-" in rule, f"{sel}: радиус вне лестницы токенов"
        assert "box-shadow:var(--sh-lg)" in self._rule(".tpl-ac-box{")

    def test_dropdown_items_hover_on_the_same_surface(self):
        """Одна подсветка курсора на все меню, а не «где --cl, где --c-soft»."""
        assert ".city-option:hover{background:var(--row-hover)}" in STYLE
        assert ".col-item:hover{background:var(--row-hover)}" in STYLE
        assert ".tpl-ac-item:hover,.tpl-ac-item.active{background:var(--row-hover)}" in STYLE

    def test_cards_keep_the_same_radius_ladder(self):
        for sel in (".hist-card{", ".stat-city-card{", ".template-card{", ".file-card{"):
            assert "var(--r-" in self._rule(sel), f"{sel}: радиус вне лестницы токенов"


class TestIconSprite:
    """Один спрайт на все значки: разметка и app.js ссылаются на <symbol>.

    Эмодзи в кнопках убраны не из эстетики: на Windows они рисовались цветными
    и разной ширины, на macOS — монохромными, а часть (⏸ ⏹ 🔤) подменялась
    чужим глифом или пропадала совсем, и ряд кнопок разъезжался. Спрайт —
    один набор форм на страницу, поэтому кнопка из шаблона и кнопка, которую
    собирает JS, выглядят одинаково.
    """

    # Пиктограммы (эмодзи и символьные значки). Стрелки и дефисы в прозе
    # (→ ← ·) намеренно не входят: это типографика, а не иконки — они
    # наследуют цвет текста и есть в любом шрифте.
    EMOJI = re.compile(
        "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u23F0-\u23FF"
        "\u21BA]"
    )

    def _slug(self, name: str) -> str:
        assert name in APP_JS, f"нет UI_ICONS.{name}"
        return name

    def test_every_referenced_symbol_is_defined(self):
        defined = set(re.findall(r'<symbol id="(i-[a-z0-9-]+)"', TEMPLATE))
        used = set(re.findall(r'href="#(i-[a-z0-9-]+)"', TEMPLATE + APP_JS))
        assert defined, "спрайт #icon-sprite пуст"
        assert not (used - defined), f"ссылки на несуществующие значки: {sorted(used - defined)}"
        assert not (defined - used), f"значки без ссылок (мёртвые): {sorted(defined - used)}"

    def test_ui_icons_point_at_the_sprite(self):
        block = APP_JS[APP_JS.index("const UI_ICONS = {"):]
        block = block[: block.index("\n};")]
        keys = re.findall(
            r"^  ([A-Za-z]+): +'<svg class=\"ico\" aria-hidden=\"true\">"
            r"<use href=\"#(i-[a-z0-9-]+)\"/></svg>',$",
            block, re.M,
        )
        assert len(keys) >= 30, f"UI_ICONS читается не полностью: {len(keys)}"
        assert "UI_ICONS.busy" in APP_JS and "UI_ICONS.gear" in APP_JS

    def test_no_emoji_in_rendered_markup(self):
        rendered = re.sub(r"<!--.*?-->", "", TEMPLATE, flags=re.S)
        left = sorted(set(self.EMOJI.findall(rendered)))
        assert not left, f"в разметке остались эмодзи: {left}"

    def test_controls_carry_icons_not_emoji(self):
        """В текстах журнала и тостах эмодзи — содержание (их пишет и Python),
        а подписи кнопок и заголовки модалок обязаны быть значками."""
        for bad in ("'🗑 Удалить", "'💾 Сохранить", "'🔄 Сбросить", "'📁 Обзор…'",
                    "'⏳ Открываем…'", "'✅ Все просмотрены'", "'🚀 Открыть",
                    "'✏️ Редактировать", "'➕ Новая переменная'", "'📊 Выбрано: ",
                    "'📂 Импорт'", "'⚙️ Настроить выбор'", "'👁 Превью",
                    "'📋 Скопировать все'", "'📖 Доступные переменные", "'🔤 Переменные",
                    "'🎲 Случайный выбор", "(on ? '☑' : '☐')",
                    "'⚠ ' + msg", "'⚠ ' + escape", "'✓ ' : '✕ ", "'💾 Сохранить как есть'",
                    "'🏪 Франшизы", "'🛵 Доставка", "'🛵 Доставка и тёмные",
                    "txt = `✅ Готово", "txt = `⚠️", "txt = `❌ 0/", '">✎<', '">✕<'):
            assert bad not in APP_JS, f"эмодзи в подписи управления: {bad}"
        # И то, чем они заменены — тоже часть контракта.
        for good in ("UI_ICONS.trash + 'Удалить выбранные",
                     "const REFILTER_LABEL = UI_ICONS.refresh + 'Применить фильтры заново'",
                     "UI_ICONS.checkSquare : UI_ICONS.square",
                     "UI_ICONS.check + 'Все просмотрены'",
                     "UI_ICONS.gear + 'Столбцы'",
                     "+ UI_ICONS.pencil + '</button>'",
                     "badge.innerHTML = txt"):
            assert good in APP_JS, good

    def test_icon_gap_lives_in_the_rule_not_in_markup(self):
        """Пробел в разметке терялся у кнопок, которые собирает JS: значок
        слипался с подписью. Зазор — в правиле .ico, поэтому он есть везде."""
        rule = STYLE[STYLE.index("\n.ico{"):]
        rule = rule[: rule.index("}")]
        assert "margin-right" in rule
        # Кнопки-иконки без подписи: зазор сдвинул бы значок от центра.
        assert ".file-btn .ico,.ub-close .ico,.bulk-reset .ico" in STYLE
        assert "</svg> " not in TEMPLATE, "пробел в разметке ломает единый зазор"

    def test_status_badge_uses_an_icon_not_a_glyph_in_the_text(self):
        """Пилюля состояния рисует значок по классу состояния, а подпись
        приходит без эмодзи — иначе один и тот же смысл оформлялся тремя
        разными наборами глифов (⏳ эмодзи, ⏹ и ✔ — символы)."""
        assert 'id="status-badge" role="status"' in TEMPLATE
        assert '<use href="#i-check"/>' in TEMPLATE.split('id="status-badge"')[1][:160]
        assert "const STATUS_ICONS = {" in APP_JS
        for state in ("running", "queued", "paused", "stopped", "error", "done"):
            assert re.search(rf"^  {state}: +UI_ICONS\.", APP_JS, re.M), state
        for bad in ("'⏸ Пауза'", "'⏳ Выполняется'", "'⏳ В очереди'", "'⏹ Остановлено'",
                    "'✔ Готово'", "'✖ Ошибка'", "'✖ Соединение прервано'"):
            assert bad not in APP_JS, f"эмодзи в подписи состояния: {bad}"
        assert "STATUS_ICONS[cls]" in APP_JS


class TestDailyDynamics:
    """«Динамика по дням» — дашборд вкладки «Статистика».

    Блок считается по файлам на диске (а не по записям текущей сессии),
    поэтому он живёт в своём контейнере и рисуется до KPI-карточек.
    """

    def test_container_is_the_first_block_of_the_stats_panel(self):
        stats = TEMPLATE.index('id="p-stats"')
        body = TEMPLATE.index('id="stats-body"', stats)
        daily = TEMPLATE.index('id="stats-daily"', stats)
        assert stats < daily < body, "динамика должна стоять перед KPI-карточками"
        assert 'id="stats-daily"' not in TEMPLATE[body:], "контейнер только один"

    def test_panel_scrolls_as_a_whole(self):
        """Прокручивался только #stats-body — блок над ним висел бы полосой.
        display меняется ТОЛЬКО у .active: иначе перебился бы
        `.tab-panel{display:none}` и скрытая вкладка была бы видна."""
        assert "#p-stats.active{display:block;overflow-y:auto;padding:20px}" in STYLE
        assert "#p-stats .stats-body{flex:none;overflow:visible;padding:0}" in STYLE
        assert "#p-stats{display:block}" not in STYLE

    def test_data_comes_from_the_server_by_day(self):
        assert "fetch('/stats/daily?' + _dailyQuery())" in APP_JS
        assert "function _dailyQuery()" in APP_JS
        assert "@bp.route(\"/stats/daily\")" in (
            ROOT / "routes" / "api.py").read_text(encoding="utf-8")

    def test_period_is_not_limited_to_the_quick_segments(self):
        """7/14/30 дней мало: период задаётся ещё календарным месяцем и
        диапазоном «с … по …», и каждый режим уходит своим параметром."""
        assert "DAILY_SEGMENTS" in APP_JS
        assert "{days: 1, label: 'Сегодня'}" in APP_JS, "статистика за сутки — окно в один день"
        assert "month=" in APP_JS and "'from=' +" in APP_JS and "&to=" in APP_JS
        assert 'type="month"' in APP_JS, "месяц — нативный пикер, а не список из 12 пунктов"
        assert 'type="date"' in APP_JS
        assert "setDailyMonth" in APP_JS and "applyDailyCustom" in APP_JS
        # Даты полей приходят из ответа сервера: клиент и сервер не могут
        # разойтись в том, какой период показан.
        assert "_dailyPayload = payload" in APP_JS

    def test_native_period_fields_follow_the_theme(self):
        """Пикер даты рисует браузер, поэтому тему ему сообщает color-scheme,
        а не токены цвета."""
        assert ".dyn-month,.dyn-date{" in STYLE
        assert "color-scheme:light" in STYLE
        assert '[data-theme="dark"] .dyn-month,[data-theme="dark"] .dyn-date{color-scheme:dark}' in STYLE

    def test_unanswered_marks_are_explained_on_the_chart(self):
        """Отметки старого формата — просто `true`, без даты. В график они не
        попадают, но «просмотрено 0» при сотне отмеченных строк выглядит как
        поломка счётчика, поэтому о них пишут прямо под графиком."""
        assert '"undated": undated' in (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        assert "_dailyNoteHTML" in APP_JS
        assert "в динамике по дням они не участвуют" in APP_JS
        assert ".dyn-note{" in STYLE

    def test_heading_uses_a_sprite_icon_not_an_emoji(self):
        assert "${UI_ICONS.chart}Динамика по дням" in APP_JS
        assert "'📊 Динамика" not in APP_JS
        assert '<symbol id="i-chart"' in TEMPLATE

    def test_chart_styles_read_theme_tokens(self):
        """Столбцы, шкала и легенда — на токенах: хекс в правиле не
        переключился бы вместе с темой (см. test_theme_contrast)."""
        block = STYLE[STYLE.index(".dyn-head{"):STYLE.index("@media(max-width:620px){", STYLE.index(".dyn-head{"))]
        assert "var(--c)" in block and "var(--grn)" in block
        assert "--brand" in block, "активный период — плотная плашка под белый текст"
        assert re.search(r"\.dyn-bar\.is-zero\{[^}]*height:2px", block), "ноль — насечка, не пропуск"

    def test_plot_geometry_leaves_room_for_the_numbers(self):
        """Три полосы по вертикали: запас под цифру над столбцом (16),
        шкала (112) и подписи дней (30). Если колонка станет ниже суммы,
        подпись самого высокого столбца срежется ее краем."""
        stack = int(re.search(r"\.dyn-stack\{[^}]*height:(\d+)px", STYLE).group(1))
        cols = int(re.search(r"\.dyn-cols\{[^}]*height:(\d+)px", STYLE).group(1))
        day = int(re.search(r"\.dyn-day\{height:(\d+)px", STYLE).group(1))
        margin = int(re.search(r"\.dyn-stack\{[^}]*margin-top:(\d+)px", STYLE).group(1))
        assert cols == margin + stack + day, "высота колонки = запас + шкала + подписи"
        assert margin >= 14, "под число над столбцом нужно ~12px"
        # Ось и сетка натянуты на ту же шкалу, что и столбцы: top — запас,
        # bottom — полоса подписей, иначе линии уедут от высоты столбцов.
        for sel in (".dyn-grid", ".dyn-yaxis"):
            rule = STYLE[STYLE.index(sel + "{"):]
            rule = rule[:rule.index("}")]
            assert f"top:{margin}px" in rule and f"bottom:{day}px" in rule, sel

    def test_numbers_are_on_the_chart_not_only_in_the_tooltip(self):
        """Просьба «пусть хотя бы цифры показывает» — про сам график: подписи
        над столбцами, подписанная ось и сетка по тем же делениям."""
        assert ".dyn-vlab{" in STYLE and ".dyn-tick{" in STYLE
        assert ".dyn-grid i{" in STYLE
        # Плотный ряд прячет подписи (числа остаются в подсказке и на оси).
        assert ".dyn-chart.is-dense .dyn-vlab{display:none}" in STYLE
        assert "dyn-vlab" in APP_JS and "dyn-tick" in APP_JS
        assert "class=\"dyn-vlab" in APP_JS

    def test_tooltip_is_not_clipped_by_the_scrolling_row(self):
        """Подсказку резали и .dyn-cols (overflow-x:auto), и сама панель
        статистики: у высокого столбца карточка над ним уезжала за верх
        панели. Поэтому она живёт в <body> и позиционируется position:fixed."""
        tip_pos = STYLE.index(".dyn-tip{")
        rule = STYLE[tip_pos:STYLE.index("}", tip_pos)]
        assert "position:fixed" in rule
        assert "transform:" not in rule, "сдвиг через transform не складывается с краями окна"
        assert "_dailyTip.className = 'dyn-tip'" in APP_JS
        assert "document.body.appendChild(_dailyTip)" in APP_JS
        assert 'class="dyn-tip"' not in APP_JS, "в разметке графика подсказки больше нет"
        # Позиция — из геометрии колонки в CSS-пикселях окна (те же единицы,
        # что и у fixed): при масштабировании страницы она не уезжает.
        assert "col.getBoundingClientRect()" in APP_JS
        assert "window.innerWidth" in APP_JS and "window.innerHeight" in APP_JS
        assert "chart.getBoundingClientRect()" not in APP_JS, "расчёт от родителя больше не нужен"

    def test_tooltip_hides_when_the_boxes_move_without_the_cursor(self):
        """Прокрутка и смена масштаба двигают столбцы без mousemove: подсказку
        надо спрятать, а не оставить висеть в устаревшей точке."""
        assert "addEventListener('scroll', _hideDailyTip" in APP_JS
        assert "addEventListener('resize', _hideDailyTip)" in APP_JS
        # Позиция пересчитывается на каждом mousemove, а не только при смене дня.
        assert "if (col) _showDailyTip(col); else _hideDailyTip();" in APP_JS

    def test_tooltip_goes_below_when_there_is_no_room_above(self):
        assert "function _dailyTipBounds(" in APP_JS
        assert "function _placeDailyTip(" in APP_JS
        assert "tip.classList.toggle('is-below', below)" in APP_JS
        assert "const below = top < minTop;" in APP_JS
        assert "const maxTop = Math.max(minTop, b.bottom - size.height - pad);" in APP_JS, \
            "нижняя граница не должна перебивать верхнюю"

    def test_today_is_a_hourly_chart(self):
        """«Сегодня» — график по часам: время поиска пишется в имя raw-файла
        (`raw_2026-09-30_14-01_…`), поэтому 14:01 и 14:50 попадают в колонку
        «14». Без файлов с часом дневной столбец честнее пустых суток."""
        assert "function dailyHoursChartHTML(" in APP_JS
        assert "payload.hours && payload.hours.some(h => h.found)" in APP_JS
        assert "def _file_parse_hour(" in API_PY
        assert "_DATETIME_IN_NAME" in API_PY
        assert "'&hours=1'" in APP_JS, "запрос просит почасовой разворот"
        assert "a.get(\"hours\", type=int) == 1" in API_PY

    def test_columns_fill_the_chart_width(self):
        """7 дней растягиваются на всю ширину графика, а не занимают узкую
        ленту слева. Единственный дневной столбец («Сегодня» без почасовых
        данных) ограничивается отдельно."""
        assert "max-width:72px" not in STYLE, "лента колонок + пустое место справа"
        assert re.search(r"\.dyn-col\{[^}]*flex:1 1 0", STYLE)
        assert ".dyn-cols.is-single .dyn-col{max-width:120px}" in STYLE

    def test_results_table_phones_and_socials_columns(self):
        """Телефоны: десяток номеров через запятую растягивал таблицу за
        горизонт. Соцсети наоборот — колонке задаём минимум."""
        assert "function phoneHTML(" in APP_JS
        assert 'class="tbl-phone"' in APP_JS
        assert re.search(r"#results-table td:nth-child\(6\)\{max-width:\d+px\}", STYLE)
        assert re.search(r"#results-table th:nth-child\(8\),#results-table td:nth-child\(8\)\{min-width:\d+px", STYLE)
        assert ".tbl-phone{" in STYLE and ".tbl-phone span{display:block" in STYLE

    def test_stats_breakdowns_use_donut_and_split(self):
        """Соцсети — кольцо с долями, категории — полосы рядом: два ряда
        полос на всю ширину читались как два одинаковых списка."""
        assert "function donutHTML(" in APP_JS
        assert "donutHTML(socialCounts" in APP_JS
        assert ".stat-split{" in STYLE and ".donut{" in STYLE
        assert ".donut-legend-row{" in STYLE

    def test_dashboard_facts_are_readable(self):
        """Итоги периода — не сноска: средний темп крупнее, лучший день
        подсвечен зелёным, доля разобранного — жирным значением."""
        assert 'class="dyn-fact dyn-fact-avg"' in APP_JS
        assert 'class="dyn-fact dyn-fact-best"' in APP_JS
        assert 'class="dyn-fact dyn-fact-share"' in APP_JS
        assert ".dyn-fact-avg{font-size:13px}" in STYLE
        assert ".dyn-fact-best b{color:var(--grn)}" in STYLE
        assert ".dyn-fact-share b{font-weight:800}" in STYLE

    def test_done_status_is_neutral_not_green(self):
        """«Готово» — приглушённая пилюля в тоне шапки: поиск закончен,
        и самое яркое пятно на экране не должно молчать про это."""
        start = STYLE.index("#status-badge.done{")
        rule = STYLE[start:STYLE.index("}", start)]
        assert "var(--grn)" not in rule and "var(--ok-bg)" not in rule, rule
        for dark in ("[data-theme=\"dark\"] #status-badge.done{",):
            rule_d = STYLE[STYLE.index(dark) + len(dark):]
            rule_d = rule_d[:rule_d.index("}")]
            assert "var(--grn)" not in rule_d, rule_d

    def test_quota_card_is_compact_with_manual_input(self):
        """Карточка 2GIS: цифры крупно, пояснение — в tooltip «ⓘ», ручной
        ввод расхода — малозаметное поле у значения."""
        assert 'class="quota-info"' in APP_JS and "ⓘ" in APP_JS
        assert ".quota-sub" not in STYLE, "пояснение уехало в tooltip"
        assert "quota-manual" in APP_JS and "setTwogisQuotaManual" in APP_JS
        assert "/twogis/quota" in APP_JS and "twogis_quota_manual" in API_PY
        assert ".quota-num{font-size:24px" in STYLE
        assert ".quota-manual{" in STYLE

    def test_social_badges_have_full_names(self):
        """VK/TG/WA в таблице расшифровываются при наведении."""
        assert 'SNAMES[p] || SLABELS[p]' in APP_JS

    def test_donut_sectors_carry_percentages_when_wide(self):
        """Проценты внутри секторов: дуга < 8% не подписывается — там не
        помещается, значение остаётся в легенде."""
        assert "donut-pct" in APP_JS and "pct < 0.08" in APP_JS
        assert ".donut-pct{" in STYLE

    def test_columns_button_is_visible_and_dropdown_aligned(self):
        """«Столбцы» заметнее соседей; список — ровные колонки
        чекбокс|подпись; фильтр соцсетей прячется вместе с колонкой."""
        assert "#btn-cols{\n  /* Кнопка заметнее" in STYLE
        assert ".col-item{\n  display:grid;grid-template-columns:14px 1fr" in STYLE
        assert "col-hidden" in APP_JS and ".tbl-social-row.col-hidden{display:none}" in STYLE

    def test_data_export_import_is_in_ui(self):
        """Экспорт/импорт отметок и настроек — во вкладке «Форматы вывода»."""
        assert 'id="data-import-file"' in TEMPLATE
        assert "exportAppData" in APP_JS and "importAppData" in APP_JS
        assert '@bp.route("/data/export")' in API_PY
        assert '@bp.route("/data/import", methods=["POST"])' in API_PY
        assert "_backup_reviewed" in API_PY

    def test_every_day_carries_its_own_numbers(self):
        """Колонка несёт данные для подсказки: иначе карточка при наведении
        показывала бы не тот день, на который наведён курсор."""
        for attr in ("data-wd", "data-dm", "data-found", "data-review", "data-files", "data-pct"):
            assert attr in APP_JS, attr
        assert "const axis = dailyAxis(maxFound)" in APP_JS
        assert "function dailyAxis(" in APP_JS
