# Changelog для разработчиков

Технические изменения проекта: что и где поменялось, какие инварианты держим.
Пользовательская (человеческая) версия тех же версий —
в [CHANGELOG.md](CHANGELOG.md).

Правило ведения: одна правка = две записи. Сначала раздел в `CHANGELOG.md`
(что это даёт пользователю), затем раздел здесь с тем же номером версии —
файлы, функции, шаги CI, тесты. Номер версии в обоих файлах обязан совпадать:
это проверяет `tests/test_changelogs.py`, и на этом же совпадении строится
сборка релиза — тело GitHub Release берётся из `CHANGELOG.md`, а технические
заметки уходят свёрнутым блоком «Для разработчиков» и прикладываются к релизу
как `CHANGELOG.md` + `CHANGES-DEV.md`.

Свежие разделы сверху. Нерелизнутое живёт под `[Unreleased]` и при выпуске
переименовывается в номер версии.

## [Unreleased]

**Звук уведомлений: пресеты, громкость, предпросмотр** (`static/js/app.js`,
`templates/index.html`, `static/css/style.css`)

- `SOUND_PRESETS` — единственное место с описанием тонов (`notes`, `gain`,
  `step`, `tail`, `type`); `SOUND_DEFAULTS` задаёт дефолт на тип события
  (город — `chime`, поиск — `fanfare`), `VOLUME_DEFAULT = 0.7`.
- `playNotifySound(kind, {draft})` — общая точка воспроизведения: пресет и
  громкость берутся из `notifySettings`, а с `draft: true` — из `notifyDraft`,
  то есть прослушивание звучит ровно так, как сохранится. `playCityDoneSound()`
  и `playDoneSound()` остались совместимыми обёртками над ним.
- `_chime()` множит `gain` на громкость; в `_tone()` нижняя граница
  `Math.max(0.0001, gain)` — `exponentialRampToValueAtTime` от нуля браузеры
  считают ошибкой, а громкость 0 — валидная настройка.
- Формат `notifications_settings` расширен ключами `volume`, `sound_city`,
  `sound_search`. Валидация: `_notifyVolume()` (доля 0…1, мусор → дефолт),
  `_notifySound()` (id проверяется по реестру, чтобы удалённый пресет не
  оставлял пользователя без звука). `notifyDraftDirty()` учитывает новые поля,
  поэтому кнопка «Сохранить» ведёт себя как раньше.
- Разметка: `#notify-sound-city`, `#notify-sound-search`, `#notify-play-city`,
  `#notify-play-search`, `#notify-volume`, `#notify-vol-val`. Опции списков
  строит `_fillSoundSelect()` из реестра — подписи не дублируются в HTML.
- Смена пресета (`notifySoundChanged`) и отпускание ползунка
  (`notifyVolumeCommit`) сразу играют звук: выбор без прослушивания —
  выбор наугад.

**«Массовый обход» открывает вкладки в порядке таблицы**
(`static/js/app.js`, `routes/api.py`)

- Клиент: `bulkSortSpec()` сводит состояние сортировки к паре
  `{col, asc}` (колонка заголовка ≥ 2 или чекбокс «Сначала горячие» →
  `col: 6, asc: false`) и передаёт её в `/bulk/urls` как `sort_col`/`sort_asc`;
  `bulkOrderLabel()` показывает порядок в панели (`#bulk-order-note`).
- Сервер: `_sort_like_table(recs, sort_col, sort_asc)` +
  `_lead_score_num()` + `_VIEW_SORT_KEYS` (2..5 — name/category/address/phone,
  6 — оценка лида). Сортировка применяется к записям ДО фильтрации в очередь,
  поэтому порядок очереди совпадает с порядком строк. Python-сортировка
  устойчивая, как `Array.sort` в браузере, — записи с равным ключом идут в
  порядке файла в обоих местах. Без `sort_col` поведение прежнее (порядок
  файла), старые вызовы API не ломаются.
- `filterTable()` теперь сбрасывает `sortCol`/`sortAsc`: список строк
  пересобирается с нуля, и прежняя сортировка по клику к нему не относится.
  Без сброса стрелка в шапке и фактический порядок расходились, а обход
  повторял бы порядок, которого на экране нет.

**Две истории изменений** (`CHANGELOG.md`, `CHANGES-DEV.md`,
`scripts/release_notes.py`, `.github/workflows/build-exe.yml`)

- `scripts/release_notes.py` получил `--dev-changelog` (по умолчанию
  `CHANGES-DEV.md`): технический раздел той же версии добавляется к телу
  релиза свёрнутым блоком `<details>`, а в конце — ссылки на оба файла на
  теге релиза. Если раздела нет — релиз собирается как раньше (пользовательский
  текст + ссылка на `CHANGELOG.md`).
- `build-exe.yml` прикладывает к релизу оба файла вместе с `-windows-x64.zip`.
  Обновлятор ищет архив по имени `YandexBusinessParser-windows-x64.zip`
  (`ZIP_ASSET_NAME` в `routes/update.py`), поэтому лишние ассеты ему не мешают.
- `tests/test_changelogs.py` держит инвариант: набор версий в двух файлах
  совпадает, у каждой версии есть непустой раздел, текущая `config.APP_VERSION`
  описана в обоих файлах, в инструментах релиза есть включение dev-файла.

**Аккордеон «Фильтрация результата»: группы, «⚙️ Дополнительно», sticky-футер**
(`templates/index.html`, `static/css/style.css`, `static/js/app.js`,
`tests/test_ui_markup.py`, `tests/ui/filterspanel.test.mjs`)

- Разметка: одиннадцать блоков свёрнуты в четыре группы `.flt-group`
  (заголовок `.flt-group-title` + тело `.flt-group-body`) плюс
  `<details class="flt-extra" id="filters-extra">`. Все `id`, `name` и
  обработчики сохранены: `#lead-score-block` переехал на тело своей группы,
  `#vk-filter-block` — в «Активность», `#social-network-filter` вложен в блок
  соцсетей (плитки — уточнение к режиму «С соцсетями», а не отдельный пункт).
  Списки в «Дополнительно» читают `refilterNow()`/пресеты по `id` из DOM, так
  что свёрнутость на них не влияет — проверяет
  `TestFilterAccordionGroups::test_every_control_survived_the_regrouping`.
- CSS: `.flt-group{padding-top:16px}`, разделитель
  `.flt-group+.flt-group{border-top:1px solid var(--bdr);margin-top:16px}`,
  заголовок — 11px uppercase `var(--muted)` с рейкой `3px var(--c)`;
  `#acc-filters .acc-inner{gap:0;padding-bottom:0}` — ритм задают группы, а не
  flex-gap, иначе у разделителя было бы по 13px вместо 16/16.
- Sticky-футер: `.flt-footer{position:sticky;bottom:calc(var(--dock-h,0px) + 6px)}`
  — полоса во всю ширину аккордеона (`margin:16px -13px 0`) с кнопкой
  `#btn-refilter` на 100% и подсказкой (инлайновый `style` кнопки убран в CSS).
  Инвариант: у предка не должно быть скролл-порта, иначе `sticky` считается
  относительно него и не сдвигается вовсе — поэтому `#acc-filters` и
  `#acc-filters .acc-body>.acc-inner` используют `overflow:clip` (подрезает как
  `hidden`, но скролл-порта не создаёт). В браузере без поддержки `clip`
  объявление отбрасывается и остаётся прежний `hidden`: вид не меняется,
  пропадает только прилипание — мягкая деградация.
- `syncDockHeight()` (`app.js`): меряет `offsetHeight` у `#run-dock` и кладёт
  значение в `--dock-h` на `document.documentElement`; запасные значения —
  `:root{--dock-h:62px}` и `0px` в `@media(max-width:860px)` (там `#run-dock`
  статичный). Меряем, а не хардкодим: высота дока зависит от шрифта, зума и
  брейкпоинта, а две прилипающие панели на нижней кромке накладывались бы друг
  на друга. Вызов — при инициализации, на `resize` и через `ResizeObserver` на
  самом доке.
- Тесты: `TestFilterAccordionGroups` (группы и их порядок, разделители,
  свёрнутое по умолчанию «Дополнительно», состав футера, `overflow:clip` вместо
  `hidden`, замер дока), `tests/ui/filterspanel.test.mjs` — семь кейсов
  `syncDockHeight` (широкий экран, телефон, старый браузер без `matchMedia`,
  отсутствие дока, нулевая высота, пересчёт при смене высоты).

**Чёрный список слов («🚫 Исключить по словам»)**
(`yandex_maps_parser/processing.py`, `routes/api.py`, `yandex_maps_parser/runner.py`,
`static/js/app.js`, `templates/index.html`, `static/css/style.css`)

- `processing.py`: `parse_blacklist_words()` — сплит по `[,;\n]`, trim,
  lowercase, пустые и дубликаты выброшены, слово длиннее `BLACKLIST_MAX_LEN=50`
  отброшено (это не слово, а вставленный абзац), список обрезан до
  `BLACKLIST_MAX_WORDS=100`; функция идемпотентна, поэтому результат можно
  сохранять как есть. `blacklist_matcher()` — одна скомпилированная
  alternation из `re.escape(w)`: спецсимволы (`C++`, `[акция]`) ищутся
  буквально, сравнение `re.IGNORECASE` в `BLACKLIST_FIELDS = name, category,
  description`; пустой список → `None` (в цикле фильтрации нулевая работа).
- Место в этапе 2: blacklist проверяется ПЕРВЫМ в цикле фильтрации — после
  `collapse_chains*`, до parse_mode / соцсетей / оценки / VK, поэтому
  «исключено» не зависит от остальных галочек (тест
  `test_blacklist_wins_over_the_other_filters`). Счётчик `blacklist_excluded`
  возвращается из `apply_filters` (в т.ч. в `empty`-ответе) и пишется в журнал
  строкой `🚫 Blacklist: исключено N компаний`.
- `routes/api.py`: `/process-filters` прокидывает `blacklist_words` в фильтры и
  отдаёт `blacklist_excluded` в ответе — у рефильтра нет потоковых логов, и без
  этого слово-исключение «работало бы молча». Новый `POST /preview-blacklist`
  (`{words}` → `{ok, words, total, excluded, remaining}`) считает исключения по
  сырым данным текущего поиска ТОЙ ЖЕ парой функций, что этап 2, — цифра в
  подсказке не может разойтись с результатом обработки.
- `runner.py`: `blacklist_words` из params обычного запуска уезжает в те же
  stage-2 фильтры.
- `app.js`: состояние `blacklistWords`; `normalizeBlacklist()` /
  `parseBlacklistInput()` (те же лимиты, что на сервере); `addBlacklistWords()`
  / `addBlacklistFromField()` / `onBlacklistKey()` (Enter добавляет, Backspace
  в пустом поле снимает последний чип); `removeBlacklistWord()`;
  `clearBlacklist()` (чипы гаснут классом `.bl-out` — как у городов);
  `applyBlacklistTemplate()` добавляет шаблон К текущему списку, опции строит
  `fillBlacklistTemplateSelect()` из реестра `BLACKLIST_TEMPLATES` (подписи не
  дублируются в разметке); `scheduleBlacklistSave()` / `saveBlacklistNow()` —
  ключ `blacklist_words`, формат `{words, version: 1, updated_at}`, debounce
  1 с; `loadBlacklistWords()` читает и старый формат (голый массив) и битый
  JSON; `scheduleBlacklistPreview()` / `previewBlacklist()` — debounce 600 мс и
  `_blPreviewSeq`, чтобы устаревший ответ не перетирал свежий счётчик.
- Пресеты и сброс: `getCurrentSettings().blacklist`, `applySettings()` →
  `setBlacklistWords()`, `FORM_DEFAULTS.blacklist = []` (сброс чистит и список).
  В payload идут `getParams().blacklist_words` и `refilterNow()` — иначе новый
  поиск и рефильтр давали бы разные срезы.
- Тема: токены `--chip-bg` / `--chip-txt` в обоих блоках. Светлый — из макета
  (#F3F4F6 / #374151), тёмный — #333A47 / #E3E7EE: нейтральный Gray-700 из
  макета выбивался из графитовой палитры, а hex-литерал в тёмном правиле
  запрещён `test_ui_markup`. Пара добавлена в `PAIRS`
  `tests/test_theme_contrast.py` — контраст чипа ≥ 4.5:1 в обеих темах.
- Тесты: `tests/test_blacklist.py` (17 кейсов — парсинг, лимиты, спецсимволы,
  приоритет над соцсетями, «после объединения филиалов», строка журнала,
  `/preview-blacklist`), `tests/ui/blacklist.test.mjs` (25 кейсов — чипы,
  валидация, storage с debounce, шаблоны, счётчик без «гонки» ответов),
  `TestBlacklistChips` в `tests/test_ui_markup.py`, а также поля в
  `tests/test_refilter_filters.py` и round-trip в `tests/ui/presets.test.mjs`.

**Чёрный список слов: пять правок по итогам аудита** (`static/js/app.js`,
`templates/index.html`, `static/css/style.css`, тесты)

- `scheduleBlacklistPreview()`: `_blPreviewSeq++` выполняется ДО ветки пустого
  списка — иначе ответ на старый список воскрешал «🚫 Исключит N…» поверх
  «Список пуст» после очистки (гонка счётчика).
- `renderBlacklistChips(opts)` пересобирает список через `innerHTML`, поэтому
  `animation:bl-chip-in` снята с базового `.bl-chip` и повешена на
  `.bl-chip.bl-new`; какие слова новые, знает `_blAnimateWords` (заполняют
  `addBlacklistWords()` и `setBlacklistWords()`), а после рендера набор
  сбрасывается — анимируются только свежие чипы, а не весь список при каждой
  правке.
- Поле `#f-blacklist-input` больше без `maxlength="50"`: атрибут резал вставку
  списка слов до 50 символов целиком; лимит на ОДНО слово остался в JS
  (`BLACKLIST_MAX_LEN`, `parseBlacklistInput`).
- Ленивый счётчик: `loadBlacklistWords()` рисует чипы через
  `renderBlacklistChips({preview: false})` и показывает только «Слов в
  списке: N» — запрос `/preview-blacklist` больше не уходит на каждой загрузке
  страницы. Счётчик запускается при открытии раздела (`toggleAccordion`,
  `sec.id === 'acc-filters'`) и на каждое изменение списка; в разметке под
  счётчиком добавлена подсказка про «Применить фильтры заново».
- Крестик чипа получил `onkeydown="onBlacklistChipKey(event, i)"` —
  `onBlacklistChipKey()` снимает слово по Enter и пробелу (роль кнопки была, а
  клавиатура не работала).
- Тесты: `tests/ui/blacklist.test.mjs` +5 кейсов (гонка после очистки,
  анимация только новых чипов, отсутствие запроса на загрузке, счёт при
  открытии раздела, снятие чипа с клавиатуры); `tests/test_ui_markup.py` —
  нет `maxlength`, анимация на `.bl-chip.bl-new`, `onBlacklistChipKey`,
  ленивый рендер и подсказка.

**Шаблоны сообщений («📝 Шаблоны»)** (`yandex_maps_parser/message_templates.py`,
`routes/api.py`, `vk_sender/`, `static/js/app.js`, `templates/index.html`,
`static/css/style.css`, `tests/test_message_templates.py`,
`tests/ui/templates.test.mjs`)

- `message_templates.py`: `VARIABLES` (10 переменных) + `VARIABLE_ALIASES`
  (`название_бизнеса → name`, `reviews_count → reviews`), `DEFAULT_TEMPLATES`
  (5 пресетов), `normalize_templates()`, `normalize_active_ids()`,
  `migrate_templates()` (версия в settings.json; файл новее сборки не разрушаем —
  сохраняем и предупреждаем), `substitute()` — regex `\{(\w+)\}`, известная
  пустая переменная → «—» (или `{var}` при `show_missing_as_var`), неизвестная
  остаётся как есть. Хранение — ключ `message_templates` в settings.json (общее
  для команды), `active_template_ids` — по каждой категории.
- `routes/api.py`: `GET/POST /templates`, `POST /templates/reset`;
  `/bulk/urls` принимает `template` + `show_missing_as_var` и отдаёт `text` на
  каждую запись (та же подстановка, что в рассылке).
- `vk_sender/runner.py` использует `substitute()` вместо `.replace()` — работают
  и `{name}`, и `{название_бизнеса}`, и остальные переменные;
  `excel_manager.iter_recipients()` кладёт в запись `record` (все колонки по
  `HEADER_LABELS`), иначе в рассылке был бы только название.
- `app.js`: состояние `messageTemplates`/`activeTemplateIds`/`showMissingAsVar`;
  `substituteTemplate()` — зеркало Python-подстановки (regex с `А-Яа-я`: `\w`
  в JS не покрывает кириллицу и `{название_бизнеса}` иначе не заменится),
  `usedVariables()`, карточки CRUD, модалка с вставкой переменной и живым
  превью, `uiChoose()` — модалка на N вариантов (у `uiConfirm` их два) для
  конфликтов импорта («Заменить / Дублировать / Пропустить» + «применить ко
  всем»), экспорт/импорт JSON, сброс. Клик по бейджу соцсети
  (`onSocialBadgeClick`) копирует подставленный текст и открывает профиль;
  обход кладёт тексты в `bulkState.texts` и рисует очередь `#bulk-queue`
  с «Скопировать следующее»; `fillSenderFromTemplate()` заполняет поле рассылки.
  Иконки карточек — SVG на `currentColor` (эмодзи-мусорка запрещена
  `test_ui_markup`).
- Разметка/CSS: вкладка `t-templates` между «История» и «Форматы вывода»,
  панель `p-templates`, модалка `#tpl-modal`, селекты `#tbl-template`/
  `#bulk-template`/`#s-template`. `.template-card`, `.template-actions`
  (hover/focus-within), `.tpl-modal`, `.bulk-queue`; тёмная тема на токенах
  (hex-литералов нет).
- Тесты: `tests/test_message_templates.py` (24 кейса — хранение, нормализация,
  миграции, подстановка, API, `/bulk/urls`, рассылка VK),
  `tests/ui/templates.test.mjs` (31 кейс — подстановка, карточки, модалка,
  интеграции с таблицей и обходом, конфликты импорта), `TestMessageTemplates`
  в `tests/test_ui_markup.py`.

## [2.3.1]

- `routes/update.py`: батник установщика писался с `\r\r\n` (текстовый режим
  поверх уже готовых переводов строк) — `cmd.exe` обрывал файл, ни одна замена
  не выполнялась. Пишем побайтово, перед запуском проверяем содержимое;
  ссылка на архив берётся на конкретный тег, а не `releases/latest`
  (алиас отдаёт предыдущий релиз, пока новый — черновик); версия внутри
  скачанного архива сверяется с ожидаемой, иначе архив удаляется.
- `scripts/stamp_version.py`: `version.json` обновляется только после
  публикации релиза (`announce-release.yml` ждёт не-черновик с windows-архивом).
  `say()` печатает с `errors="replace"` — на windows-раннере stdout в cp1252,
  и русский вывод ронял шаг сборки.
- `search_history.py`: мутации не писались на диск (в `add`/`delete`/`clear`
  не хватало `global _cache`) — удаления и очистка возвращались после
  перезапуска, а обрезка до `MAX_HISTORY_ENTRIES` не срабатывала.
- `routes/sender.py`, история файлов: пропавший импорт `shutil` ронял
  архивацию/восстановление.
- Журнал/файлы: иконки карточек на токенах темы, плотные цвета кнопок
  «Удалить выбранные» в тёмной теме, добавлены «✕ Отменить выбор» и
  «📦 В архив (N)».
- Тесты: swap-сценарии апдейтера (`tests/test_updater_swap.py`), конвейер
  версии (`tests/test_release_version_flow.py`), сетевой `git log` в
  диагностике не роняет шаг; зависимости запинены, `pyflakes` чист.

## [2.3.0]

- `static/js/app.js`: вкладки массового обхода открываются синхронно, до
  первого `await` — иначе попап-блокировщик съедал всё, кроме первой.
  «Открыто X из N» и «📋 Скопировать ссылки» как честный фолбэк.
- Журнал «Ход поиска»: `LOG_NOISE_RE`/`LOG_KEEP_RE` и фильтры
  [Все · Важные · Ошибки · Технические], сворачиваемые блоки городов, выгрузка
  в `.log`. В шаблон регулярки попал реальный символ backspace вместо `\b` —
  шаблон молча не совпадал, добавлен регресс-тест на управляющие символы.
- Темы: палитра переведена на токены, контраст ≥ 4.5:1 проверяется
  `tests/test_theme_contrast.py`, тема выставляется до первой отрисовки.
- Оценка лида: `yandex_maps_parser/lead_score.py` и зеркало в app.js
  (`annotate_records` → `_fillLeadScores`), шесть бонусов, разбор в подсказке.
- Сборки: `.github/workflows/build-macos.yml` (`.app`/`.dmg`, подпись Developer
  ID + нотаризация, порт 5050), гейт `ci.yml` на трёх ОС, Dependabot для pip и
  Actions. Данные на macOS — в `~/Library/Application Support`.
- Апдейтер: баннер обновления закреплён под шапкой, кнопка в шапке
  превращается в «⬆ Обновить до vX»; сброс счётчика токенов 2GIS при смене
  ключа; автосохранение отметок «Просмотрено»; пауза с продолжением со
  следующего города.
