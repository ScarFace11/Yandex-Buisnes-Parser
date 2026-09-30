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

**«Динамика по дням»** (`routes/api.py`, `static/js/app.js`,
`templates/index.html`, `static/css/style.css`, `tests/test_stats_daily.py`,
`tests/ui/statsdaily.test.mjs`, `tests/test_ui_markup.py`,
`tests/test_results_files.py`, `tests/ui/sidebar.test.mjs`)

- `GET /stats/daily` → `_daily_series()`: период задаётся тремя способами,
  приоритет `from`/`to` → `month=YYYY-MM` → `days=N` (`_daily_window()`
  возвращает окно, признак обрезки и режим). Окно `days` — дефолт
  `DAILY_DEFAULT_DAYS=7`, кап `DAILY_MAX_DAYS=90`, 0/отрицательное/не-число →
  дефолт; месяц — целиком календарный (`_month_start()` терпит и `YYYY-M`,
  мусор уходит в режим days); явный диапазон — до года (`DAILY_MAX_SPAN=366`),
  длиннее — обрезается по правому краю с флагом `truncated`. Будущее срезано
  по `date.today()`, перепутанные поля упорядочиваются — валидатор на клиенте
  дублировать не нужно. Ответ: `mode`, `days`, `start`, `end`, `truncated`,
  `series[{date, found, files, reviewed}]` без пропусков (пустой день —
  нулями) + `totals`.
- Клиент запрашивает период строкой `_dailyQuery()` из состояния
  `_dailyRange{kind, days, month, from, to}`; `_reloadDaily()` рисует
  заголовок сразу и дозапрашивает данные, счётчик `_dailySeq` отбрасывает
  ответ на уже неактуальный период (было: флаг `_dailyBusy`, и быстрый
  клик 7→30 мог отрисовать прошлый ответ).
- «Найдено» — `_daily_found_in_window()`. Дата из имени raw-файла
  (`_DATE_IN_NAME` → `raw_YYYY-MM-DD_HH-MM_…`); имени без даты — mtime
  (`_file_parse_date()`): у processed даты в имени нет вообще
  (`кафе_казань_filtered.xlsx`). Файлы вне окна не открываются вовсе —
  `_count_records` читает xlsx, и обход всех файлов стоил бы секунд.
- raw и processed НЕ суммируются: processed — те же записи после фильтров,
  сумма давала бы ровно 2×. За день отвечают raw-файлы; processed идёт в дело
  только если raw за этот день нет (архив, ручная чистка); внутри
  processed/json vs processed/excel берётся большая подпапка, а не сумма —
  это два экспорта одних записей. `_is_raw_file()` различает их и внутри
  `_archive/**`, который тоже участвует: без него день обнулялся бы сразу
  после архивации.
- `_reviewed.json`: значение отметки — `{"reviewed_at": <unix>}` вместо
  `true` (`_mark()`, `_set_mark()`), повторная отметка дату НЕ сдвигает.
  Чтение (`_reviewed_ts()`) терпит легаси-`true` и ключи
  `updated_at`/`at`/`ts`; легаси даты не несёт и в график не попадает (все
  потребители проверяют значение на истинность — объект её сохраняет).
  `totals.undated` считает такие отметки, чтобы интерфейс мог объяснить
  «просмотрено 0» вместо того, чтобы выглядеть сломанным.
- UI: `#stats-daily` — первый блок `#p-stats`, перед `.stat-cards`;
  `dailySectionHTML()` / `renderDailyDynamics()` / `loadDailyDynamics()` /
  `setDailyRange()` / `setDailyMonth()` / `applyDailyCustom()` /
  `toggleDailyCustom()` (`DAILY_SEGMENTS` — Сегодня(1)/7/14/30). Нативный
  `input[type=month]` и два `input[type=date]` вместо списка месяцев:
  меньше кода и настоящий пикер, а `color-scheme` по теме чинит вид
  календаря в тёмной. Загрузка ленивая: при открытии вкладки
  (`showTab('stats')`) и из `renderStats` после прогона (во время прогона
  пропускается — `isRunActive()`: там renderStats зовётся каждые 1.5 с).
  Поля периода предзаполнены из последнего ответа (`_dailyPayload`), и он же
  даёт показ диапазона — клиент и сервер не могут разойтись в том, какой
  период показан; после рендера `.dyn-cols.scrollLeft = scrollWidth` —
  месяц и диапазон открываются на свежих днях.
- Панель статистики прокручивается целиком:
  `#p-stats.active{display:block;overflow-y:auto}` +
  `#p-stats .stats-body{flex:none;overflow:visible}`. Раньше скроллился только
  `#stats-body`, и блок над ним висел бы неподвижной полосой. `display`
  переопределяется только у `.active` — иначе перебивался бы
  `.tab-panel{display:none}` и скрытая вкладка была бы видна.
- График без библиотек: столбцы — flex-дети (`.dyn-col/.dyn-stack/.dyn-bar`),
  общая шкала на два ряда (на своей шкале короткая полоса «просмотрено»
  выглядела бы как длинная), ноль — насечка `.is-zero` БЕЗ inline-высоты
  (inline перебил бы правило класса), сегодня — `.is-today`. Иконка
  `#i-chart` в спрайте.
- Шкала (`dailyAxis()`): верхняя метка кратна шагу, шаг — лестница
  0.5/1/2/2.5/5/10 от порядка максимума, делений 2–4, поэтому на оси всегда
  круглые числа (50/100/150), а самый богатый день занимает бо́льшую часть
  высоты. Простой «максимум как верх» давал подписи 531 и 1062; для малых
  максимумов лестница без 2.5 — дробные деления (7.5 откликов) недопустимы.
  Формат чисел: `_fmtCount()` — разряды пробелом; `_fmtTick()` — «15к»
  для 10000+ (в гуттер оси 34px полное число не влезает).
- Вертикальная геометрия — три полосы: 18px под цифру над столбцом, 112px
  шкала, 30px подписи дней (`.dyn-cols/.dyn-col` height = 160, mobile — 134
  через медиазапрос вместе с `.dyn-stack{height:88px}`). Ось (`.dyn-yaxis`) и
  сетка (`.dyn-grid`) натянуты на те же `top/bottom`, что и шкала столбцов —
  иначе линии уезжают от высоты столбцов. Запас 18px, а не 16: подпись над
  100%-столбцом вылезала на пиксель за верх колонки, а у `.dyn-cols`
  overflow-x:auto (он же обрезал бы её сверху).
- Подсказка (`.dyn-tip`) — `position:fixed` и живёт в `<body>`
  (`_dailyTipNode()`), а не внутри графика: её резали и прокручиваемая панель
  статистики (`overflow-y:auto`), и `.dyn-cols` (`overflow-x:auto`) — у
  высокого столбца карточка уезжала за верх панели (баг из отчёта).
  `_placeDailyTip()` считает `left`/`top` из `getBoundingClientRect()` — это
  те же CSS-пиксели, что и у fixed-элемента, поэтому при масштабировании
  страницы подсказка остаётся над столбцом, а не уезжает от курсора; сдвиг
  через `transform` убран (его пришлось бы складывать с зажимом по краям).
  Нет места над столбцом (`_dailyTipBounds()` — верх панели, зажатый в окно) —
  карточка разворачивается под столбик (`is-below`). Позиция пересчитывается
  на каждом `mousemove`, а не только при смене дня: после прокрутки или смены
  зума курсор остаётся в той же колонке, и старая точка была бы неверной;
  `scroll` панели и `resize` окна подсказку прячут. Наведение —
  делегированное `mousemove` на `#stats-daily` (`_bindDailyHover()`, один
  раз), иначе подсказка терялась бы при каждой перерисовке. Данные дня —
  в `data-*` колонки, а не в HTML-атрибуте `title`.
- Цифра над столбцом — `.dyn-vlab` с inline `bottom:calc(<высота>% + 3px)`,
  то есть подпись едет вместе со столбцом. Ноль приглушён селектором
  `.dyn-series .dyn-vlab.is-zero`: без префикса .dyn-series цвет серии
  (0,3,0) перебивал этот (0,2,0) и ноль становился акцентным.
  Плотность (`_dailyDense()`) считается по реальной ширине блока — на
  телефоне и десктопе порог разный; в плотном режиме подписи скрывает класс
  `.dyn-chart.is-dense`.
- Итоги периода — строка `.dyn-facts`: средний темп в день, лучший день
  (день + число) и доля разобранного от найденного; за один день первые два
  не показываются (среднее равно самому дню, «лучший» — тоже). Под легендой
  `.dyn-span` — человеческие даты периода, у месяца и диапазона сегменты
  не подсвечены, и без них непонятно, что показано. `.dyn-note` — о том,
  что график умалчивает: отметки без даты и обрезанный период.
  Колонка ограничена `max-width:72px` — один день («Сегодня») иначе
  растягивался в полосу на всю ширину.
- Тесты: `test_stats_daily.py` — окно/нули, дедуп raw↔processed, архив,
  mtime-фолбэк, битые файлы, даты отметок и клэмпы, месяц/диапазон/обрезка;
  `statsdaily.test.mjs` — разметка графика, состояния (загрузка/пусто/ошибка),
  запросы всех трёх режимов периода, геометрия подсказки (центр, зажим по
  краям, разворот под столбик, панель ниже экрана, пересчёт на каждом
  движении); `test_ui_markup.py::TestDailyDynamics` — контейнер, скролл
  панели, токены, иконка вместо эмодзи, отсутствие подсказки в разметке.

**Почасовой «Сегодня», растянутые колонки, таблица, разбивки** (`routes/api.py`,
`static/js/app.js`, `static/css/style.css`, `tests/test_stats_daily.py`,
`tests/ui/statsdaily.test.mjs`, `tests/ui/results.test.mjs`,
`tests/test_ui_markup.py`)

- `GET /stats/daily?…&hours=1` при окне в один день добавляет в ответ
  `hours`: 24 корзины `{hour, found, files}` или `None`, если файлов с
  часом нет. Час — из имени raw-файла (`_DATETIME_IN_NAME` →
  `raw_YYYY-MM-DD_HH-MM_…`, `_file_parse_hour()` валидирует дату-время и
  отвечает только для raw); у processed времени поиска в имени нет, а
  mtime — время фильтрации, поэтому processed в почасовой ряд не
  попадает. Сумма по часам сходится с дневным `totals.found` (тест).
- `_dailyQuery()`: `days=1` и диапазон `from==to` добавляют `&hours=1`.
  `dailySectionHTML()` при `payload.hours` с ненулевыми корзинами рисует
  `dailyHoursChartHTML()` — тот же plot (шкала/сетка/ось из общих
  helpers), колонки от первого до последнего часа с данными (+1 час
  запаса), подпись колонки — «14» (`data-dm="14:00"`, `data-wd="Час» для
  подсказки). «Просмотрено» по часам НЕ раскладывается: времени отметки в
  данных нет, выдумывать нельзя — оно остаётся в легенде. Факты «в
  среднем в день»/«лучший день» к часам не относятся и не показываются.
- Колонки растянуты на всю ширину: `max-width:72px` у `.dyn-col` снят,
  `flex:1 1 0` делит ширину между колонками; `min-width:26px` сохраняет
  прокрутку для месяца/диапазона. Один дневной столбец без почасовых
  данных ограничен отдельно — `.dyn-cols.is-single .dyn-col{max-width:
  120px}`. Парные ряды в широкой колонке прижаты к центру:
  `.dyn-col .dyn-series{max-width:16px}` + `gap:4px` у `.dyn-stack`.
- Таблица результатов: `phoneHTML()` разбивает comma-joined телефоны на
  строки (`.tbl-phone`, `max-height:3.2em` + прокрутка внутри ячейки,
  полный список в `title`); `td:nth-child(6){max-width:230px}` гасит
  распирание таблицы (в Excel/CSV телефоны попадают без изменений).
  Соцсетям наоборот минимум: `th/td:nth-child(8){min-width:120px}`.
- Статистика: `donutHTML()` — SVG-кольцо (r=70, обод 16, rotate(-90°),
  доли через stroke-dasharray, минимальная дуга 0.5%, одиночная соцсеть —
  полная окружность) с центром «всего» и легендой «N · %». Разбивки
  сведены в `.stat-split`: слева «Топ категорий» (полосы `barRows`),
  справа кольцо соцсетей; на узком экране — колонкой.
- Панель статистики получила общий внутренний отступ:
  `#p-stats.active{…;padding:20px}` (был только у `#stats-body`),
  `#p-stats .stats-body` обнулён (`padding:0`), чтобы не удваивать.
- Тесты: `test_stats_daily.py::TestHours` — 24 корзины, час из имени
  (14-01 и 14-50 → «14»), сходимость сумм, processed без часов, hours
  только при одиночном дне; `statsdaily.test.mjs` — запрос `&hours=1`,
  разметка почасового графика, фолбэк на дневной столбец;
  `test_ui_markup.py::TestDailyDynamics` — отсутствие `max-width:72px`,
  `phoneHTML`, ширины колонок 6/8 таблицы, `donutHTML`/`.stat-split`;
  `results.test.mjs` — в набор grab добавлен `phoneHTML`.

**Статус-пилюля без эмодзи** (`templates/index.html`, `static/js/app.js`,
`static/css/style.css`, `tests/test_ui_markup.py`, `tests/ui/sidebar.test.mjs`)

- `setStatus()` больше не принимает эмодзи в тексте: значок рисует сама
  пилюля по классу состояния (`STATUS_ICONS` → `#status-badge .ico`, размер
  11px и штрих 2.2 — в 11px-пилюлю 15px-глиф не влезал). Так `⏳`, `⏹`, `✔`
  и `✖` из подписей ушли: один и тот же смысл оформлялся тремя разными
  наборами глифов, а на Windows часть из них цветная.

## [2.3.2]

**Свои переменные шаблонов** (`yandex_maps_parser/message_templates.py`,
`routes/api.py`, `vk_sender/runner.py`, `static/js/app.js`, `templates/index.html`,
`static/css/style.css`, `tests/test_message_templates.py`, `tests/ui/templates.test.mjs`,
`tests/test_ui_markup.py`)

- Схема `message_templates` в settings.json: версия 1 → 2, новое поле
  `custom_variables: [{name, value, column, description, created_at}]`.
  Миграция `_MIGRATIONS[1]` добавляет пустой список старым хранилищам
  (механизм был зарезервирован под будущие шаги — задействован).
- `normalize_custom_variables()`: имя по `^[A-Za-z0-9_а-яА-ЯёЁ]+$` (тот же
  алфавит, что у подстановки), без коллизий со встроенными и алиасами
  (`RESERVED_VAR_NAMES = VARIABLES ∪ VARIABLE_ALIASES`), дедуп без учёта
  регистра; `column` задан → `value` не нужен (значение берётся из записи),
  иначе обязателен непустой `value`. Лимиты: MAX_VAR_NAME 60,
  MAX_VAR_VALUE 1000, MAX_VAR_DESC 200, MAX_VAR_COLUMN 60, кап
  MAX_CUSTOM_VARS 100.
- `substitute(text, record, show_missing_as_var, custom_variables=None)`:
  свои переменные проверяются первыми и перекрывают встроенные; `column` →
  `record[column]`, иначе статичный `value`; пустые — по общим правилам
  («—» / `{var}` при show_missing_as_var). `custom_variables=None` — старый
  контракт не меняется.
- Интеграции на сервере: `POST/GET /templates` прокидывают
  `custom_variables` в составе состояния; `/bulk/urls` подставляет их и в
  одиночный `template`, и в random-выбор (`_make_random_picker`);
  `vk_sender/runner.py` — при обычной отправке
  (`custom_variables=load_templates().get("custom_variables")`), random-ветка
  получает их через общий `substitute`.
- Клиент: состояние `customVariables` в `applyTemplatesState`/
  `postTemplatesState` (полный round-trip с сервером); зеркало
  `substituteTemplate` учитывает свои переменные с теми же приоритетами
  (клик по соцсети, превью в модалке).
- UI: подвкладки внутри `p-templates` — `showTplSubtab('templates'|'vars')`,
  панели `#tpl-pane-templates` / `#tpl-pane-vars`, переключатель
  `.tpl-subtab`. Подвкладка «Переменные»: карточки `renderVarCards()`
  (встроенные — просмотр, свои — ✎/🗑 через `TEMPLATE_ICONS`), модалка
  `#tpl-var-modal` (имя между визуальными скобками, источник
  «статичный текст / столбец», селект столбцов из зеркала EXCEL_COLUMN_DEFS —
  `varColumnOptions()` без служебных `reviewed`/`parsed_at`, описание).
  CRUD: `saveVarFromModal` (валидация имени/дублей/капа клиентом, сервер
  перепроверяет), `deleteCustomVar` с `uiConfirm`. Блок «📖 Доступные
  переменные», селект «Вставить переменную» и автодополнение пополнены
  своими (`allTemplateVars()`).
- CSS: `.tpl-subtab(s)`, `.tpl-var-card/kind/actions/desc/val`,
  `.tpl-var-name-row`, `.tpl-vars-manage`, `.tpl-var-count`; тёмная тема —
  `[data-theme="dark"] .tpl-var-card`.

**Массовое удаление шаблонов** (те же файлы)

- Выделение — `_tplSelectedIds` (Set id), чекбоксы на карточках
  (`data-tpl-check`, `toggleTemplateSelected`), «Выделить все» работает по
  видимому списку (`_visibleTemplates()` = фильтр категории + поиск).
- `deleteSelectedTemplates()`: одно `uiConfirm` на весь выбор (первые 3
  названия + «и ещё N»), затем один проход — `pruneTemplatePicks()`, одна
  перерисовка, один `saveTemplatesState()`. Кнопка
  `#btn-tpl-del-selected` появляется при N ≥ 1 и показывает количество
  (`updateTplSelectionUi`); `pruneTemplateSelection()` чистит выделение от
  удалённых/отфильтрованных id; `deleteTemplate` (по одному) тоже снимает id
  с выделения.

**Автодополнение переменных в редакторе шаблона** (те же файлы)

- `onTemplateTextInput()` (oninput `#tpl-text`): незакрытая `{` до каретки →
  `renderTemplateAutocomplete(fragment)` — панель `#tpl-autocomplete` под
  textarea, фильтр по началу имени, метка «своя» у своих переменных;
  закрытая `{…}` или отсутствие `{` — панель скрыта.
- Вставка: клик (`mousedown` + preventDefault, чтобы textarea не теряла
  фокус), `Enter`/`Tab` (выбор стрелками, `_tplAcIndex`), Esc — закрыть;
  `applyTemplateAutocomplete(key)` заменяет незакрытую `{…` до каретки на
  полный токен и возвращает превью. `onblur` textarea закрывает панель с
  задержкой 150 мс — клик по пункту успевает отработать.
- Ограничение наивного слайсера функций в tests/ui (`grab()`): внутри новых
  функций нет символов `{`/`}` вне кода — комментарии переформулированы.

**Важно для обратной совместимости**: старый settings.json (version 1)
мигрирует автоматически и без потерь; `substitute()` без
`custom_variables` и все существующие контракты API не изменились.
- Тесты: `tests/test_message_templates.py` (новые классы
  `TestCustomVariables`, `TestSubstituteCustom`, round-trip API своих
  переменных, миграция v1→v2), `tests/ui/templates.test.mjs` (выделение и
  пакетное удаление, CRUD переменных, автодополнение, подстановка своих —
  63 кейса), `TestMessageTemplates` в `tests/test_ui_markup.py`
  (разметка подвкладок/модалки переменных/автодополнения, CSS-контракты,
  серверный round-trip).

**Случайный выбор шаблонов** (`yandex_maps_parser/message_templates.py`,
`routes/api.py`, `vk_sender/runner.py`, `static/js/app.js`, `templates/index.html`,
`static/css/style.css`, `tests/test_message_templates.py`, `tests/ui/templates.test.mjs`,
`tests/ui/results.test.mjs`)

- Хранение в `message_templates` (settings.json): `template_modes`
  (`single`/`random` per-категория), `random_template_ids` (наборы per-категория),
  `avoid_repeats` (глобально). Новые поля аддитивные — старый settings.json
  получает дефолты через `normalize_state` без смены версии схемы.
- `normalize_modes()` — мусор → `single`; `normalize_random_ids(raw, templates)` —
  только существующие id СВОЕЙ категории (удаление/переезд шаблона автоматически
  чистит наборы при следующей нормализации), дедуп, кап MAX_TEMPLATES.
- `pick_random_text(texts, last, avoid)` — чистая функция выбора: с
  `avoid_repeats` исключает последний, пусто → выбор из полного набора (1 шаблон
  всегда даёт тот же текст — корректно). `resolve_pick_state(social, state)` —
  `(texts, names, mode, avoid)` для категории.
- API: `POST /templates` принимает `template_modes`/`random_template_ids`/
  `avoid_repeats` (GET отдаёт автоматически); `POST /bulk/urls` — `template_ids`
  + `tpl_avoid_repeats`: сервер резолвит id по своему хранилищу и выбирает
  per-record (`pick_random_text` + `substitute`), каждый item получает
  `tpl_name`; без id — прежний контракт (`template` текстом). `/send/run`
  прокидывает `message_tpl_ids`/`tpl_avoid_repeats` как есть (params не фильтруются).
- `vk_sender/runner.py`: ids резолвятся через `load_templates()` по категории
  `social`; набор пуст/невалиден — fallback на `message_tpl`. Выбор на КАЖДОЕ
  сообщение с `last` внутри прогона; финальный лог «Использовано шаблонов: N из M».
- Клиент: состояние `templateModes`/`randomTemplateIds`/`avoidRepeats` в
  `applyTemplatesState`/`postTemplatesState`; `pickRandomTemplate(social)` —
  зеркало `pick_random_text` с сессионным `_lastPickedTpl`; `getTemplateFor(social)`
  — random → случайный из набора, иначе активный (fallback при пустом наборе).
  `onSocialBadgeClick` берёт `getTemplateFor` и показывает имя шаблона в тосте.
  `bulkOpenBatch` в random-режиме шлёт `template_ids` вместо текста; очередь
  (`renderBulkQueue`) рисует «📋 (Имя шаблона)» из `tpl_name`. `startSend` при
  `#s-random-tpl` шлёт `message_tpl_ids` и не требует непустого текста;
  `saveSenderConfig`/`restoreSenderConfig` хранят галочку в localStorage.
  `pruneTemplatePicks()` чистит наборы при удалении/смене категории шаблона
  (не дожидаясь серверной нормализации).
- UI: блок «🎲 Выбор шаблона» в `p-templates` (селект категории `#tpl-pick-cat`,
  радио режимов, для single — селект шаблона, для random — чекбоксы + счётчик
  «Выбрано: X из Y» + ghost «⚙️ Настроить выбор»); модалка `#tpl-pick-modal` на
  `.tpl-modal`/`.ui-modal-btns`: чекбоксы, «Избегать повторов», счётчик,
  подсказки (0 выбранных — Save off, 1 — предупреждение «Выберите 2+»);
  чекбокс «🎲 Случайный из выбранных шаблонов» в `fw-send-tpl`. Все цвета на
  токенах (hex-литералов нет); ≤860px — стек, модалка на всю ширину.
- Тесты: `tests/test_message_templates.py` +11 (нормализация режимов/наборов,
  prune, дефолты старых файлов, контракт `pick_random_text`, API roundtrip,
  отбрасывание битых id, `/bulk/urls` random с per-record текстом/именем и
  avoid-чередованием, fallback без набора, раннер с ids);
  `tests/ui/templates.test.mjs` +11 (чтение состояния, `getTemplateFor` —
  random/avoid/fallback, тост с именем, prune, переключение режима с сохранением,
  валидация модалки, `savePickModal`, отмена, очередь с `tpl_name`);
  `tests/ui/results.test.mjs` — заглушки новых глобалов для `bulkOpenBatch`.
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

**Пресеты списков исключений и UX вкладки «📝 Шаблоны»** (`static/js/app.js`,
`templates/index.html`, `static/css/style.css`, `tests/ui/blacklist.test.mjs`,
`tests/ui/templates.test.mjs`, `tests/test_ui_markup.py`)

- Сохранённые списки исключений: ключ `blacklist_lists` (отдельно от текущего
  списка `blacklist_words` — очистка списка не сносит сохранённые), структура
  `{version, lists:[{name, words, updated_at}]}`, лимиты `BLACKLIST_MAX_LISTS`
  и `BLACKLIST_LIST_NAME_MAX`, нормализация в `getBlacklistLists()`.
- «💾 Сохранить список» открывает модалку `openBlacklistSaveModal()` вместо
  `prompt()`: имя + Esc/Enter/клик по подложке; дубликат имени не блокирует —
  `uiConfirm` предлагает перезаписать, при отказе модалка переоткрывается через
  `setTimeout(…, 0)` с прежним именем в поле.
- «📂 Загрузить шаблон» — кастомный дропдаун вместо `<select>` (у нативного
  не бывает кнопок в опциях): `#blacklist-dd` → `.bl-dd-btn` + `.bl-dd-panel`;
  `fillBlacklistTemplateSelect()` строит панель из реестра `BLACKLIST_TEMPLATES`
  + сохранённых списков (группы «Встроенные шаблоны» / «Мои списки», значения
  `builtin:<key>` / `saved:<имя>`, пустое состояние с подсказкой, футер-примечание
  «добавляется к списку, а не заменяет»). `renderBlacklistListManage()` вешает
  применение на `.bl-dd-item[data-value]` и перезапись/удаление (с `uiConfirm`)
  на кнопки ✎/🗑 в строке `.bl-dd-row` (hover-reveal); встроенные шаблоны
  неизменяемы. `toggleBlacklistDropdown()`/`closeBlacklistDropdown()` держат
  `aria-expanded` в синхроне, пересобирают панель на каждое открытие; закрытие —
  клик мимо (делегированный `document.click`) и Escape.
  `applyBlacklistTemplate()` принимает оба префикса, закрывает дропдаун и
  добавляет слова К списку.
- Шаблоны сообщений: прокрутка вкладки (`.tpl-scroll` с `flex:1;min-height:0;
  overflow-y:auto`), подсказка-порядок работы `.tpl-intro-hint`, поиск
  `#tpl-search` (`onTemplateSearch()` фильтрует по названию и тексту, счётчик
  «N из M» в `#tpl-search-count`), пустое состояние `#tpl-empty-box` с кнопками
  «+ Добавить шаблон» и «🔄 Сброс к стандартным».
- Превью без данных таблицы: `TEMPLATE_DEMO_COMPANY` — вымышленная компания,
  заголовок «👁 Превью (пример):», пояснение в `#tpl-preview-note`; при живых
  данных — реальная первая компания из `filteredRows`/`allResults`. Превью
  обновляется oninput (debounce не нужен — подстановка дешёвая).
- Категория в модалке — `<select id="tpl-category">` (4 категории) со
  стрелкой в CSS; чекбокс «показывать {переменную}» перенесён влево от текста;
  «Сброс к стандартным» — ghost-кнопка с подтверждением через `uiConfirm`
  (текст «Ваши изменения будут потеряны»).
- Карточки: 3 основные кнопки (редактировать / копировать текст / удалить) +
  меню «⋮» (`.tpl-menu`) с «Дублировать»; действия видны на hover и
  focus-within; дата «Обновлено: ДД.ММ ЧЧ:ММ» (`_fmtTemplateDate()`); тост
  «Шаблон сохранён» после записи.
- Селекты выбора шаблона (`fillTemplateSelect()`): опция — только название,
  группировка по категориям через `<optgroup>` (в таблице категория и так
  видна по активной соцсети).
- Тесты: `tests/ui/blacklist.test.mjs` +8 кейсов (дропдаун из реестра и списков
  с кнопками в строках, `saved:`-применение, модалка сохранения/дубликат/пустой
  список, управление, toggle/aria); `tests/ui/templates.test.mjs` +8 кейсов
  (прокрутка-обёртка не тестируется изолированно — проверяется разметкой; поиск,
  пустое состояние, пример-превью, optgroup-селекты, дата, меню),
  `TestBlacklistChips` обновлён на `openBlacklistSaveModal()` и кастомный
  дропдаун.

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
