document.addEventListener('keydown', _notifyEscape);
// Первый жест разблокирует звук (autoplay-политика).
['click', 'keydown', 'touchstart'].forEach(ev =>
  document.addEventListener(ev, unlockAudio, { once: true, passive: true }));

// ═══════════════════════════════════════════
//  Social network filter
// ═══════════════════════════════════════════
function toggleSocialFilter(key) {
  if (activeSocialFilters.has(key)) activeSocialFilters.delete(key);
  else activeSocialFilters.add(key);
  // Sync button states
  document.querySelectorAll('.sf-tag').forEach(btn => {
    btn.classList.toggle('active', activeSocialFilters.has(btn.dataset.key));
  });
  document.getElementById('sf-clear-btn')
    .classList.toggle('visible', activeSocialFilters.size > 0);
  filterTable();
}

function clearSocialFilters() {
  activeSocialFilters.clear();
  document.querySelectorAll('.sf-tag').forEach(b => b.classList.remove('active'));
  document.getElementById('sf-clear-btn').classList.remove('visible');
  filterTable();
}

// Кнопки «⊘ Дубли» больше нет: убирать дубли одним кликом без контроля было
// опасно, а объединение филиалов сетей живёт в аккордеоне «Фильтрация
// результата» («Объединять филиалы сетей» + правило объединения).

// ═══════════════════════════════════════════
//  Column visibility
// ═══════════════════════════════════════════
const COLS_KEY = 'yp_cols_v2';
const COLS_AUTO_KEY = 'yp_cols_auto_v1';   // столбцы, спрятанные «Скрыть пустые»
// `idx` — только для совместимости со старыми сохранёнными настройками;
// порядок столбцов задаёт COL_ORDER_DEFAULT/colOrder, а разметка находит
// колонку по data-col, а не по позиции.
const COLS = [
  { idx: 1, key: 'rev',      label: '✓ Просмотрено' },
  { idx: 2, key: 'num',      label: '# Номер' },
  { idx: 3, key: 'name',     label: 'Название' },
  { idx: 4, key: 'category', label: 'Категория' },
  { idx: 5, key: 'address',  label: 'Адрес' },
  { idx: 6, key: 'phone',    label: 'Телефон' },
  { idx: 7, key: 'score',    label: 'Оценка' },
  { idx: 8, key: 'socials',  label: 'Соцсети' },
  { idx: 9, key: 'rating',   label: 'Рейтинг' },
];
const COL_LABELS = Object.fromEntries(COLS.map(c => [c.key, c.label]));

// ── Порядок столбцов ──────────────────────────────────────────
// «Рейтинг» по умолчанию НЕ в самом конце: раньше он стоял за соцсетями,
// то есть за правой границей экрана — его приходилось искать прокруткой.
// Теперь качественные числа (оценка лида и рейтинг) стоят рядом, а самая
// широкая колонка (соцсети) — последней.
const COL_ORDER_KEY = 'yp_cols_order_v1';
const COL_ORDER_DEFAULT = ['rev', 'num', 'name', 'category', 'address', 'phone',
                           'score', 'rating', 'socials'];
let colOrder = COL_ORDER_DEFAULT.slice();

// Полный набор ключей в сохранённом порядке: чужие ключи (старая версия
// localStorage или переименованная колонка) выбрасываем, забытые добавляем
// в конец — набор столбцов от порядка не зависит.
function normalizeColOrder(saved) {
  const known = COLS.map(c => c.key);
  const out = [];
  (Array.isArray(saved) ? saved : []).forEach(k => {
    if (known.includes(k) && !out.includes(k)) out.push(k);
  });
  // Забытые/новые ключи — в стандартном порядке чтения, а не в порядке
  // объявления COLS: им задан «Рейтинг рядом с оценкой».
  COL_ORDER_DEFAULT.forEach(k => { if (!out.includes(k)) out.push(k); });
  known.forEach(k => { if (!out.includes(k)) out.push(k); });
  return out;
}

function loadColOrder() {
  try {
    colOrder = normalizeColOrder(JSON.parse(localStorage.getItem(COL_ORDER_KEY)));
  } catch (e) {
    colOrder = normalizeColOrder(null);
  }
  applyColOrder();
  renderColDropdown();
}

function saveColOrder() {
  localStorage.setItem(COL_ORDER_KEY, JSON.stringify(colOrder));
}

function resetColOrder() {
  colOrder = COL_ORDER_DEFAULT.slice();
  saveColOrder();
  renderColDropdown();
  applyColOrder();
}

// Порядок колонок в статической разметке — страховка для уже запущенного
// сервера со старым index.html в Jinja-кэше: ячейкам без data-col ключ
// проставляется по позиции. После перезапуска приложения разметка приходит
// с data-col и это не используется.
const COL_ID_BY_POS = ['rev', 'num', 'name', 'category', 'address', 'phone',
                       'score', 'socials', 'rating'];

function _stampMissingColIds(row) {
  const cells = Array.from(row.children || []);
  if (cells.length !== COL_ID_BY_POS.length) return;   // плейсхолдер / чужая таблица
  if (cells.some(c => c.dataset && c.dataset.col)) return;   // разметка уже с data-col
  cells.forEach((cell, i) => { if (cell.dataset) cell.dataset.col = COL_ID_BY_POS[i]; });
}

// Переставить ячейки по colOrder. Каждая ячейка (th и td) несёт data-col,
// поэтому порядок применяется к любой строке независимо от разметки:
// appendChild уже существующего узла = перемещение, а не копия.
function applyColOrder() {
  if (typeof document === 'undefined' || !document.querySelectorAll) return;
  document.querySelectorAll('#results-table tr').forEach(row => {
    _stampMissingColIds(row);
    const cells = {};
    let n = 0;
    Array.from(row.children || []).forEach(cell => {
      const key = cell.dataset && cell.dataset.col;
      if (key) { cells[key] = cell; n++; }
    });
    if (n < 2) return;                  // плейсхолдер «Ничего не найдено»
    colOrder.forEach(key => { if (cells[key]) row.appendChild(cells[key]); });
  });
  applyColClasses();
}

// Сдвиг стрелками (работает и без мыши с перетаскиванием).
function moveCol(key, delta) {
  const i = colOrder.indexOf(key), j = i + delta;
  if (i < 0 || j < 0 || j >= colOrder.length) return;
  [colOrder[i], colOrder[j]] = [colOrder[j], colOrder[i]];
  saveColOrder();
  renderColDropdown();
  applyColOrder();
}

// ── Перетаскивание в списке столбцов ──────────────────────────
let _colDragKey = null;

function onColDragStart(e, key) {
  _colDragKey = key;
  if (e && e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', key); } catch (err) {}
  }
  const items = document.getElementById('col-items');
  if (items) items.classList.add('dragging');
}

// Живой предпросмотр: пока тянем, список и таблица уже переставляются.
// Важно не перерисовывать список целиком — иначе браузер потеряет
// перетаскиваемый узел; поэтому двигаем сами элементы списка.
function onColDragOver(e, key) {
  if (!_colDragKey || _colDragKey === key) return;
  if (e && e.preventDefault) e.preventDefault();
  const items = document.getElementById('col-items');
  if (items && items.children) {
    const list = Array.from(items.children);
    const src = list.find(el => el.dataset && el.dataset.key === _colDragKey);
    const dst = list.find(el => el.dataset && el.dataset.key === key);
    if (src && dst && items.insertBefore) items.insertBefore(src, dst);
  }
  const from = colOrder.indexOf(_colDragKey), to = colOrder.indexOf(key);
  if (from < 0 || to < 0 || from === to) return;
  colOrder.splice(from, 1);
  colOrder.splice(to, 0, _colDragKey);
  applyColOrder();
}

function onColDragEnd() {
  const items = document.getElementById('col-items');
  if (items) items.classList.remove('dragging');
  if (!_colDragKey) return;
  _colDragKey = null;
  saveColOrder();
  renderColDropdown();      // обновить состояние стрелок
  applyColOrder();
}

// Поля записи, которые наполняют колонку. null/пустой список = колонка
// «служебная» и в «Скрыть пустые» не участвует.
const COL_DATA_FIELDS = {
  category: ['category'], address: ['address'], phone: ['phone'],
  score: ['lead_score'], socials: ['vk', 'instagram', 'telegram', 'whatsapp'],
  rating: ['rating', 'reviews_count'],
};

// Есть ли в колонке хоть одно непустое значение в наборе строк.
function colHasData(key, rows) {
  const fields = COL_DATA_FIELDS[key];
  if (!fields || !rows || !rows.length) return false;
  return rows.some(r => fields.some(f => {
    const v = r[f];
    return v !== undefined && v !== null && String(v).trim() !== '';
  }));
}

// «Скрыть пустые»: прячем колонки, где во ВСЕХ строках нет данных.
// Спрятанные так столбцы запоминаются отдельно (autoHiddenCols): когда новый
// поиск приносит по ним данные, их снова показывают автоматически, а
// вручную скрытые пользователем столбцы не трогают.
function hideEmptyColumns() {
  const rows = (typeof allResults !== 'undefined' && allResults) ? allResults : [];
  let hidden = 0;
  for (const c of COLS) {
    if (!COL_DATA_FIELDS[c.key] || !rows.length) continue;   // служебные не скрываем
    if (colHasData(c.key, rows)) continue;
    autoHiddenCols.add(c.key);
    if (!hiddenCols.has(c.key)) { hiddenCols.add(c.key); hidden++; }
  }
  saveColState();
  applyColClasses();
  renderColDropdown();
  if (typeof showToast === 'function') {
    showToast(hidden ? `Скрыто пустых столбцов: ${hidden}` : 'Пустых столбцов не нашлось', 'info');
  }
}
let hiddenCols = new Set();
// Столбцы, спрятанные кнопкой «Скрыть пустые» (а не вручную). Их можно
// вернуть сами, как только по ним появятся данные.
let autoHiddenCols = new Set();

// Новый набор результатов: автоскрытые столбцы, по которым теперь есть
// данные, показываем снова — иначе после нового поиска таблица оставалась
// без столбцов до нажатия «Показать все».
function syncAutoHiddenCols(rows) {
  if (!autoHiddenCols.size) return;
  const list = rows || ((typeof allResults !== 'undefined' && allResults) ? allResults : []);
  let shown = 0;
  for (const key of [...autoHiddenCols]) {
    if (!colHasData(key, list)) continue;
    autoHiddenCols.delete(key);
    if (hiddenCols.delete(key)) shown++;
  }
  if (shown) { saveColState(); applyColClasses(); renderColDropdown(); }
}

function loadColState() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLS_KEY));
    hiddenCols = new Set(Array.isArray(saved) ? saved : []);
  } catch { hiddenCols = new Set(); }
  try {
    const savedAuto = JSON.parse(localStorage.getItem(COLS_AUTO_KEY));
    autoHiddenCols = new Set(Array.isArray(savedAuto) ? savedAuto : []);
  } catch { autoHiddenCols = new Set(); }
  applyColClasses();
  renderColDropdown();
}

function saveColState() {
  localStorage.setItem(COLS_KEY, JSON.stringify([...hiddenCols]));
  localStorage.setItem(COLS_AUTO_KEY, JSON.stringify([...autoHiddenCols]));
}

// Скрытие — классом на КАЖДОЙ ячейке столбца, а не по позиции (nth-child):
// столбцы можно переставлять, и позиционные правила прятали бы не тот.
function applyColClasses() {
  const tbl = document.getElementById('results-table');
  if (!tbl) return;
  if (document.querySelectorAll) {
    document.querySelectorAll('#results-table [data-col]').forEach(cell => {
      const key = cell.dataset && cell.dataset.col;
      cell.classList.toggle('col-hidden', !!key && hiddenCols.has(key));
    });
  }
  // Строка фильтра «Сеть: …» управляет скрытой колонкой соцсетей: когда
  // колонка скрыта, фильтр остаётся без объекта и только путает — прячем.
  const sfRow = document.getElementById('social-filter-row');
  if (sfRow) sfRow.classList.toggle('col-hidden', hiddenCols.has('socials'));
  // Update button badge
  const btn = document.getElementById('btn-cols');
  if (btn) {
    const n = hiddenCols.size;
    btn.classList.toggle('active', n > 0);
    btn.innerHTML = n > 0 ? `${UI_ICONS.gear}Столбцы <span style="background:var(--c);color:var(--on-accent);border-radius:10px;padding:1px 6px;font-size:10px">${COLS.length - n}/${COLS.length}</span>` : UI_ICONS.gear + 'Столбцы';
  }
}

// Список столбцов: видимость (чекбокс) + порядок (перетаскивание за ручку).
// Порядок в списке = порядок колонок в таблице.
function renderColDropdown() {
  const box = document.getElementById('col-items');
  if (!box) return;
  box.innerHTML = colOrder.map((key, i) => `
    <div class="col-item" draggable="true" data-key="${key}"
         ondragstart="onColDragStart(event, '${key}')"
         ondragover="onColDragOver(event, '${key}')"
         ondrop="onColDragOver(event, '${key}'); onColDragEnd()"
         ondragend="onColDragEnd()">
      <span class="col-grip" title="Перетащите, чтобы изменить порядок столбцов">⠿</span>
      <label class="col-lbl">
        <input type="checkbox" ${hiddenCols.has(key) ? '' : 'checked'}
          onchange="toggleCol('${key}', this.checked)">
        <span class="col-lbl-txt">${COL_LABELS[key] || key}</span>
      </label>
    </div>`).join('');
}

function toggleCol(key, visible) {
  // Ручное действие: столбец больше не считается «автоскрытым пустым»,
  // поэтому новый поиск не покажет его вопреки выбору пользователя.
  autoHiddenCols.delete(key);
  if (visible) hiddenCols.delete(key);
  else hiddenCols.add(key);
  saveColState();
  applyColClasses();
}

function setAllCols(visible) {
  autoHiddenCols.clear();
  if (visible) hiddenCols.clear();
  else COLS.forEach(c => hiddenCols.add(c.key));
  saveColState();
  applyColClasses();
  renderColDropdown();
}

function toggleColDropdown(e) {
  e.stopPropagation();
  const dd = document.getElementById('col-dropdown');
  const willOpen = !dd.classList.contains('open');
  dd.classList.toggle('open', willOpen);
  if (willOpen) {
    fitColDropdown(dd);
    // Второй проход на следующем кадре: если в момент открытия панель ещё
    // докручивалась/дописывалась (подгрузка таблицы, анимация вкладки),
    // список мог измерить устаревшую геометрию и открыться не туда.
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => {
      if (dd.classList.contains('open')) fitColDropdown(dd);
    });
  }
}

// Список «Столбцы» всплывает ВНУТРИ панели результатов, а не в корне окна:
// выше прокрутки панели (и шапки) его всё равно обрезает ближайший
// контейнер с overflow, а слева список срезает колонка настроек — визуально
// это выглядело как «перекрыт другими слоями». Поэтому место меряем по
// клип-контейнеру, а не по окну, и по горизонтали список прижимается так,
// чтобы не вылезать за колонку.
function _colClipBox(dd) {
  let el = dd.parentElement;
  while (el && el !== document.documentElement) {
    const cs = getComputedStyle(el);
    if (cs.overflow !== 'visible' || cs.overflowX !== 'visible' || cs.overflowY !== 'visible') return el;
    el = el.parentElement;
  }
  return null;
}

function fitColDropdown(dd) {
  if (!dd) return;
  const btn = document.getElementById('btn-cols');
  dd.classList.remove('drop-up');
  dd.style.maxHeight = '';
  dd.style.right = '';
  const win = (typeof window !== 'undefined')
    ? {top: 0, bottom: window.innerHeight, left: 0, right: window.innerWidth}
    : {top: 0, bottom: 0, left: 0, right: 0};
  const clip = _colClipBox(dd);
  const box = clip ? clip.getBoundingClientRect() : win;
  // 1. Горизонталь: левый край списка — внутри колонки (с запасом 4px).
  let r = dd.getBoundingClientRect();
  const overLeft = (box.left + 4) - r.left;
  if (overLeft > 0) dd.style.right = (-Math.ceil(overLeft)) + 'px';
  // 2. Вертикаль: снизу — если список там целиком помещается; вверх — только
  //    если снизу не влезает, но вверх влезает (или там просто больше места).
  //    Раньше «влезает снизу» мерилось по остатку ПОД открытым списком
  //    (box.bottom - r.bottom), из-за чего вместо свободных 484px под
  //    списком виделись 35px и список зря поднимался в 58-пиксельную щель.
  r = dd.getBoundingClientRect();
  const b = btn && btn.getBoundingClientRect ? btn.getBoundingClientRect() : null;
  const spaceBelow = box.bottom - r.top - 8;
  const spaceAbove = b ? b.top - box.top - 8 : 0;
  const fitsBelow = r.height <= spaceBelow;
  const fitsAbove = r.height <= spaceAbove;
  const dropUp = !fitsBelow && (fitsAbove || spaceAbove > spaceBelow);
  if (dropUp) dd.classList.add('drop-up');
  const room = Math.max(dropUp ? spaceAbove : spaceBelow, 0);
  if (room > 0) {
    dd.style.maxHeight = Math.floor(room) + 'px';
    dd.style.overflowY = 'auto';
  }
}

// Пока список открыт, он должен переживать и скролл панели, и изменение
// окна — иначе после прокрутки снова оказывался не у кнопки.
if (typeof window !== 'undefined') {
  const _refitCols = () => {
    const dd = document.getElementById('col-dropdown');
    if (dd && dd.classList.contains('open')) fitColDropdown(dd);
  };
  window.addEventListener('resize', _refitCols);
  window.addEventListener('scroll', _refitCols, true);
}

// ═══════════════════════════════════════════
//  Что парсить: поля → столбцы отчёта (аккордеон 02)
//  EXCEL_COLUMN_DEFS mirrors constants.CSV_FIELDS / HEADER_LABELS (used by
//  the template column-variable picker). The user-facing selection lives in
//  the «Что парсить» accordion and is sent with every run
//  (params.excel_columns).
// ═══════════════════════════════════════════
const PARSE_FIELDS_KEY = 'yp_parse_fields_v1';
const EXCEL_COLUMN_DEFS = [
  { f: 'reviewed',       l: '✓ Просмотрено' },
  { f: 'lead_score',     l: 'Оценка лида' },
  { f: 'name',           l: 'Название' },
  { f: 'category',       l: 'Категория' },
  { f: 'address',        l: 'Адрес' },
  { f: 'phone',          l: 'Телефон' },
  { f: 'rating',         l: 'Рейтинг' },
  { f: 'reviews_count',  l: 'Отзывов' },
  { f: 'vk',             l: 'ВКонтакте' },
  { f: 'vk_activity',    l: 'Активность ВК' },
  { f: 'vk_followers',   l: 'Подписчики ВК' },
  { f: 'vk_last_post_days', l: 'Последний пост (дней)' },
  { f: 'instagram',      l: 'Instagram' },
  { f: 'telegram',       l: 'Telegram' },
  { f: 'whatsapp',       l: 'WhatsApp' },
  { f: 'aggregator_url', l: 'Сайт / Таплинк' },
  // Ссылка на карточку организации — единственный источник данных, Яндекс.Карты.
  { f: 'yandex_maps_url',l: 'Яндекс.Карты' },
  { f: 'query',          l: 'Запрос' },
  { f: 'parsed_at',      l: 'Дата сбора' },
  { f: 'city',           l: 'Город' },
];
function loadParseFields() {
  try {
    const saved = JSON.parse(localStorage.getItem(PARSE_FIELDS_KEY));
    parseFields = Array.isArray(saved) ? new Set(saved) : null;
  } catch { parseFields = null; }
  renderParseFields();
}

function saveParseFields() {
  localStorage.setItem(PARSE_FIELDS_KEY,
    JSON.stringify(parseFields === null ? null : [...parseFields]));
}

// Строим список столбцов отчёта из отмеченных полей (+ служебные поля).
// Соцсетевые и VK-столбцы вырезаются целиком, когда мастер «Соцсети» выключен.
function getExcelCols() {
  const enabled = parseFieldsEnabled();
  const socOn = enabled.has('socials');
  const cols = new Set(PARSE_SERVICE_COLS);
  for (const f of PARSE_REGULAR.concat(PARSE_PERSONAL)) {
    if (!enabled.has(f.k)) continue;
    if (!socOn && (f.k === 'socials' || f.k === 'vk_activity')) continue;
    (PARSE_FIELD_COLS[f.k] || []).forEach(c => cols.add(c));
  }
  return [...cols];
}

function renderParseFieldGrid(list, gridId) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  const enabled = parseFieldsEnabled();
  const socOn = enabled.has('socials');
  grid.innerHTML = list.map(f => {
    const on = enabled.has(f.k);
    const locked = !!f.locked;
    // VK-активность требует и мастер «Соцсети», и сохранённый ключ ВК.
    const gated = (f.needsKey && (!vkTokenReady || !socOn)) || (f.k === 'vk_activity' && !socOn);
    const dis = locked || gated;
    return `<label class="chk ${on ? 'on' : ''}${dis ? ' disabled' : ''}">
      <input type="checkbox" ${on ? 'checked' : ''} ${dis ? 'disabled' : ''}
        onchange="toggleParseField('${f.k}', this.checked)"> ${f.l}</label>`;
  }).join('');
}

function renderParseFields() {
  renderParseFieldGrid(PARSE_REGULAR, 'parse-regular-grid');
  renderParseFieldGrid(PARSE_PERSONAL, 'parse-personal-grid');
  updateSocialUI();
}

// «Только данные компании»: одной кнопкой снимаем персональные поля.
// Раньше их приходилось выключать по одному, и легко было забыть телефон —
// а именно он превращает отчёт в обработку персональных данных.
function disablePersonalFields() {
  if (parseFields === null) parseFields = parseFieldsEnabled();
  PARSE_PERSONAL.forEach(f => parseFields.delete(f.k));
  saveParseFields();
  renderParseFields();
  if (allResults.length) filterTable();
  if (typeof updateBasicSummary === 'function') updateBasicSummary();
  if (typeof showToast === 'function') {
    showToast('В отчёт попадут только сведения о компании — персональные поля сняты', 'ok');
  }
}

function toggleParseField(k, on) {
  if (parseFields === null) parseFields = parseFieldsEnabled();  // разворачиваем значения по умолчанию
  if (on) parseFields.add(k); else parseFields.delete(k);
  // Выключили соцсети — VK-активность не может остаться (нет ссылки на профиль).
  if (k === 'socials' && !on) parseFields.delete('vk_activity');
  saveParseFields();
  renderParseFields();
  if (allResults.length) filterTable();
}

// ═══════════════════════════════════════════
//  Гейтинг UI от выбора полей: соцсети / VK без ключа
// ═══════════════════════════════════════════
// Соцсети выключены → прячем фильтр по соцсетям, массовый обход; сбрасываем
// режим соцсетей и обязательные сети, чтобы скрытый фильтр не оставался активным.
function updateSocialUI() {
  const socOn = socialsEnabled();
  const smb = document.getElementById('social-mode-block');
  if (smb) smb.hidden = !socOn;
  // Массовый обход решает сам, виден ли он (соцсети выбраны И есть ссылки
  // в таблице) — здесь лишь сбрасываем состояние, когда соцсети выключили.
  const bulk = document.getElementById('bulk-panel');
  if (bulk && !socOn) bulk.hidden = true;
  if (socOn && typeof updateBulkStats === 'function') updateBulkStats();
  // Строка фильтра по соцсетям над таблицей тоже бессмысленна без соцсетей.
  const sfRow = document.getElementById('social-filter-row');
  if (sfRow) sfRow.classList.toggle('socials-off', !socOn);
  if (!socOn) {
    if (typeof socialMode !== 'undefined' && socialMode !== 'all') setSocialMode('all');
    if (typeof requiredSocials !== 'undefined' && requiredSocials.size) {
      requiredSocials.clear();
      document.querySelectorAll('#social-net-chk-grid .soc-tile.on').forEach(t => {
        t.classList.remove('on');
        const cb = t.querySelector('input[type=checkbox]');
        if (cb) cb.checked = false;
      });
      updateSocialFilterHint();
    }
  }
  updateVkGate();
}

// VK-функции (проверка активности) — только при наличии ключа И собранных соцсетей.
function updateVkGate() {
  const allowed = socialsEnabled() && vkTokenReady;
  const group = document.getElementById('vk-activity-group');
  if (group) group.classList.toggle('vk-gated', !allowed);
  const cb = document.getElementById('f-vk-check');
  if (cb) {
    cb.disabled = !allowed;
    if (!allowed) cb.checked = false;
  }
  if (!allowed) {
    const blk = document.getElementById('vk-filter-block');
    if (blk) blk.classList.remove('open');
  }
  updateVkCheckHint();
}

// ═══════════════════════════════════════════
//  Хранение результатов: автоудаление через N дней (7/14/30/своё, макс. 30)
// ═══════════════════════════════════════════
let retentionDays = 30;

function initRetention() {
  const sel = document.getElementById('f-retention-days');
  const custom = document.getElementById('f-retention-custom');
  if (!sel) return;
  fetch('/retention/status')
    .then(r => r.json())
    .then(j => {
      const d = parseInt(j.days, 10);
      retentionDays = (d >= 1 && d <= 30) ? d : 30;
      const isPreset = [7, 14, 30].includes(retentionDays);
      sel.value = isPreset ? String(retentionDays) : 'custom';
      if (custom) custom.value = retentionDays;
      onRetentionChange(true);
    })
    .catch(() => onRetentionChange(true));
}

function onRetentionChange(skipSave) {
  const sel = document.getElementById('f-retention-days');
  const customWrap = document.getElementById('retention-custom-wrap');
  const custom = document.getElementById('f-retention-custom');
  if (!sel) return;
  const isCustom = sel.value === 'custom';
  if (customWrap) customWrap.hidden = !isCustom;
  let days;
  if (isCustom) {
    days = parseInt((custom || {}).value, 10);
    if (isNaN(days) || days < 1) days = 1;
    if (days > 30) days = 30;
    if (custom) custom.value = days;
  } else {
    days = parseInt(sel.value, 10) || 30;
  }
  retentionDays = days;
  if (!skipSave) saveRetention(days);
}

function saveRetention(days) {
  const st = document.getElementById('retention-status');
  fetch('/retention/set', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ days: days })
  })
    .then(r => r.json())
    .then(j => {
      if (j.ok && st) {
        st.textContent = `Срок хранения сохранён: ${days} дн.`
          + (j.removed != null ? ` · удалено устаревших файлов: ${j.removed}` : '');
      } else if (st && j.error) {
        st.textContent = 'Не удалось сохранить: ' + j.error;
      }
    })
    .catch(() => { if (st) st.textContent = 'Не удалось сохранить срок — сервер недоступен.'; });
}

document.addEventListener('click', e => {
  const wrap = document.querySelector('.col-toggle-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('col-dropdown')?.classList.remove('open');
  }
  // Дропдаун шаблонов исключений закрывается кликом мимо.
  const dd = document.getElementById('blacklist-dd');
  if (dd && !dd.contains(e.target)) closeBlacklistDropdown();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('blacklist-dd-panel')?.hidden === false) {
    closeBlacklistDropdown();
  }
});

// ═════════════════════════════════════════
//  API keys → .env (VK token, one button)
// ═════════════════════════════════════════

// ── API-keys block (static section at the top of the sidebar) ──
// Expand/collapse the key form; the status badge lives in the header so the
// user sees at a glance whether keys are configured without expanding.
function toggleApiKeys() {
  const body = document.getElementById('api-keys-body');
  const hdr  = document.getElementById('api-keys-toggle');
  if (!body || !hdr) return;
  body.hidden = !body.hidden;
  hdr.setAttribute('aria-expanded', body.hidden ? 'false' : 'true');
  hdr.classList.toggle('open', !body.hidden);
}

// Badge states: токен ВК нужен только для проверки активности сообществ и
// оценки лида (+20). Ключей Яндекса в приложении нет — поиск и карточки
// читает браузер.
function updateApiKeysStatus(vk) {
  const badge = document.getElementById('api-status-badge');
  if (!badge) return;
  const total = 1;
  const have = [vk].filter(Boolean).length;
  let cls, txt, title;
  if (have === total) {
    cls = 'ok'; txt = UI_ICONS.check + `Готово ${have}/${total}`;
    title = 'Токен ВКонтакте настроен';
  } else {
    cls = 'warn'; txt = UI_ICONS.warn + `${have}/${total}`;
    title = 'Токена ВКонтакте нет — проверка активности ВК будет пропущена';
  }
  badge.className = 'api-badge ' + cls;
  badge.innerHTML = txt;
  badge.title = title;
  // Per-key dots next to each field label (green = key is set).
  const dots = { 'key-dot-vk': vk };
  for (const [id, present] of Object.entries(dots)) {
    const dot = document.getElementById(id);
    if (dot) {
      dot.classList.toggle('on', !!present);
      dot.title = present ? 'Ключ указан (в .env)' : 'Ключ не указан';
    }
  }
}

// True when a VK token is stored — used by the «Проверять активность ВК»
// hint so the user learns about the missing token before the run, not after.
let vkTokenReady = false;

function updateVkCheckHint() {
  const hint = document.getElementById('vk-check-hint');
  if (!hint) return;
  if (!socialsEnabled()) {
    hint.textContent = 'Соцсети не собираются — проверка активности недоступна. Включите «Соцсети» в разделе «Что парсить».';
  } else if (!vkTokenReady) {
    hint.textContent = 'Нужен VK-ключ в блоке «API-ключи» — без него проверка активности ВК отключена.';
  } else {
    hint.textContent = 'Проверяет подписчиков и дату последнего поста через VK API. Результат кэшируется на 7 дней.';
  }
}

// ═══════════════════════════════════════════
//  VK activity + lead score (accordion 04)
// ═══════════════════════════════════════════
function setVkMode(mode) {
  vkMode = mode;
  document.querySelectorAll('.vk-mode-opt').forEach(el => {
    const radio = el.querySelector('input[type=radio]');
    const on = !!radio && radio.value === mode;
    el.classList.toggle('active', on);
    if (radio) radio.checked = on;
  });
}

// The activity controls only matter when the check is on — showing them
// always made the block look like it filtered something by itself.
function onVkCheckChange() {
  const cb = document.getElementById('f-vk-check');
  const block = document.getElementById('vk-filter-block');
  if (block) block.classList.toggle('open', !!(cb && cb.checked));
  updateVkCheckHint();
}

function onMinScoreInput() {
  const el = document.getElementById('f-min-score');
  if (!el) return;
  const v = +el.value || 0;
  // Preset buttons mirror the stored threshold; «Все» (0) is the default.
  document.querySelectorAll('.score-preset').forEach(b =>
    b.classList.toggle('active', +b.dataset.score === v));
  const hint = document.getElementById('score-hint');
  if (!hint) return;
  const base = v === 0
    ? 'Порог 0: показывать все записи'
    : `Порог ${v}: останутся лиды с оценкой ${v} и выше`;
  const scored = allResults.filter(r => r.lead_score != null && r.lead_score !== '');
  hint.textContent = scored.length
    ? `${base} · подходят ${scored.filter(r => (+r.lead_score || 0) >= v).length} из ${scored.length}.`
    : `${base}. Формула — в «ℹ️ Как считается оценка» ниже.`;
}

// Preset click → store the threshold in the same hidden field (presets,
// filterTable and min_lead_score read it) and refresh the feedback line.
function setMinScore(v) {
  const el = document.getElementById('f-min-score');
  if (el) el.value = +v || 0;
  onMinScoreInput();
  applyFiltersAndRender();
}

function applyFiltersAndRender() {
  curPage = 1;
  renderPage();
}

// Ask the backend which keys are present in .env and paint the badge.
function refreshApiKeysStatus() {
  fetch('/api-keys/status')
    .then(r => r.json())
    .then(j => {
      vkTokenReady = !!j.vk;
      updateApiKeysStatus(!!j.vk);
      updateVkCheckHint();
      // Ключ ВК влияет на доступность VK-поля в «Что парсить» и на гейтинг
      // блока «Активность» — перерисовываем после загрузки статуса.
      if (typeof renderParseFields === 'function') renderParseFields();
      else updateVkGate();
    })
    .catch(() => {});
}

function saveApiKeys() {
  const btn = document.getElementById('btn-save-key');
  const vkToken = (document.getElementById('f-vk-token') || {}).value?.trim() || '';
  const status = document.getElementById('apikey-status');

  if (!vkToken) {
    showToast('Введите токен ВКонтакте', 'error');
    return;
  }

  btn.disabled = true;
  const orig = btn.textContent;
  btn.innerHTML = UI_ICONS.busy + 'Сохраняю…';

  const show = (ok, msg) => {
    if (!status) return;
    status.style.display = 'block';
    status.className = ok ? 'ok' : 'err';
    status.innerHTML = (ok ? UI_ICONS.check : UI_ICONS.x) + escapeHtml(msg);
  };

  fetch('/save-api-keys', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({vk_token: vkToken})
  })
  .then(r => r.json().then(d => ({ok: r.ok, data: d})))
  .then(({ok, data}) => {
    if (ok && data.ok) {
      showToast(data.message || 'Токен сохранён в .env', 'success');
      show(true, data.message || 'Токен сохранён в .env');
      // Пустое поле = «использовать сохранённое в .env» — отражаем это.
      if (vkToken) document.getElementById('f-vk-token').value = '';
      refreshApiKeysStatus();
    } else {
      showToast(data.error || 'Ошибка сохранения', 'error');
      show(false, data.error || 'Ошибка сохранения');
    }
  })
  .catch(e => {
    showToast('Ошибка соединения: ' + e.message, 'error');
    show(false, 'Ошибка соединения: ' + e.message);
  })
  .finally(() => {
    btn.disabled = false;
    btn.textContent = orig;
  });
}

// Toast notifications are implemented once, near the top of this file
// (stacked in #toast-container, top-right). The legacy centered version
// was removed in the UI redesign.

// ═══════════════════════════════════════════
//  Dark theme
// ═══════════════════════════════════════════
const THEME_KEY = 'yp_theme_v1';
const THEME_ORDER = ['light', 'dark', 'system'];   // цикл кнопки «Сменить тему»
const THEME_RU = { light: 'светлая', dark: 'тёмная', system: 'как в системе' };
let themeAnimTimer = null;

// Выбранный режим: 'light' | 'dark' | 'system'. 'system' — по умолчанию:
// цвета берутся из настройки ОС и следуют за ней, как «Авто» в системных
// настройках macOS/Windows.
function themePref() {
  let v = null;
  try { v = localStorage.getItem(THEME_KEY); } catch (e) { /* приватный режим */ }
  return THEME_ORDER.indexOf(v) >= 0 ? v : 'system';
}

function systemPrefersDark() {
  return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

// animate=true только при ручном переключении: короткая плавная смена цветов
// вместо резкого «щелчка». Первую отрисовку анимировать нельзя — тему ставит
// мини-скрипт в <head> шаблона ещё до загрузки стилей.
function applyTheme(dark, animate) {
  const root = document.documentElement;
  if (animate) {
    root.classList.add('theme-anim');
    if (themeAnimTimer) clearTimeout(themeAnimTimer);
    themeAnimTimer = setTimeout(() => root.classList.remove('theme-anim'), 260);
  }
  root.setAttribute('data-theme', dark ? 'dark' : 'light');
  const themeBtn = document.getElementById('btn-theme');
  if (themeBtn) {
    const pref = themePref();
    themeBtn.innerHTML = pref === 'system' ? UI_ICONS.auto
      : (dark ? UI_ICONS.sun : UI_ICONS.moon);
    themeBtn.title = 'Тема: ' + THEME_RU[pref] + ' — нажмите для следующей';
    themeBtn.setAttribute('aria-label', themeBtn.title);
  }
}

// Применить сохранённый режим с учётом системной темы для 'system'.
function applyThemePref(animate) {
  const pref = themePref();
  applyTheme(pref === 'system' ? systemPrefersDark() : pref === 'dark', animate);
}

function toggleTheme() {
  const next = THEME_ORDER[(THEME_ORDER.indexOf(themePref()) + 1) % THEME_ORDER.length];
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* приватный режим */ }
  applyThemePref(true);
}

// В режиме «system» тема меняется вместе с ОС уже после загрузки страницы.
if (window.matchMedia) {
  const mqTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const onSystemTheme = () => { if (themePref() === 'system') applyTheme(mqTheme.matches, false); };
  if (mqTheme.addEventListener) mqTheme.addEventListener('change', onSystemTheme);
  else if (mqTheme.addListener) mqTheme.addListener(onSystemTheme);   // старый Safari
}

// City data is defined above as CITIES_DATA with population info.
// City combobox UI is implemented via initCitySelect/addCity/removeCity functions.

// ═══════════════════════════════════════════
//  Logs modal
// ═══════════════════════════════════════════
function showLogsModal() {
  const existing = document.querySelector('.logs-modal-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.className = 'logs-modal-overlay';
  // Заголовок живёт ВНЕ перерисовываемого тела: список логов подъезжает
  // запросом и заменяет внутренности, а имя диалога (aria-labelledby) держится
  // именно за заголовком — иначе окно теряло бы своё имя ровно в тот момент,
  // когда лог загрузился.
  overlay.innerHTML = `<div class="logs-modal">
    <h3>${UI_ICONS.book}Логи запусков</h3>
    <div class="logs-body"><div class="logs-empty">Загрузка…</div></div>
  </div>`;
  document.body.appendChild(overlay);
  modalA11y(overlay);
  const body = overlay.querySelector('.logs-body');
  const closeBtn = '<div style="text-align:right;margin-top:12px">' +
    '<button class="skip-cancel" onclick="this.closest(\'.logs-modal-overlay\').remove()">Закрыть</button></div>';
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  fetch('/logs/list')
    .then(r => r.json())
    .then(data => {
      const logs = data.logs || [];
      if (!logs.length) {
        body.innerHTML = '<div class="logs-empty">Логов пока нет. Запустите поиск чтобы создать лог.</div>' + closeBtn;
        return;
      }
      const listHtml = logs.map(l => {
        const sizeKB = (l.size / 1024).toFixed(1);
        return `<li>
          <span class="log-name">${escapeHtml(l.name)}</span>
          <span class="log-meta">${l.modified} · ${sizeKB} КБ</span>
          <span class="log-actions">
            <a class="log-view" href="/logs/view/${encodeURIComponent(l.name)}" target="_blank">👁 Смотреть</a>
            <a class="log-dl" href="/logs/download/${encodeURIComponent(l.name)}" download>💾 Скачать</a>
          </span>
        </li>`;
      }).join('');
      body.innerHTML = `<ul class="logs-list">${listHtml}</ul>` + closeBtn;
    })
    .catch(() => {
      body.innerHTML = '<div class="logs-empty">Ошибка загрузки</div>' + closeBtn;
    });
}

// ═══════════════════════════════════════════
//  🩺 Диагностика: самопроверка по кнопке
// ═══════════════════════════════════════════
// Отвечает на «ничего не работает» без чтения логов: живые ли ключи, куда
// пишем, готово ли окружение и понимает ли текущая версия старые сборы.
// Живая проверка одна — токен ВКонтакте, поэтому запускается ТОЛЬКО по
// нажатию и отделена от локальных проверок: «только ключи» / «без запросов к
// API». Тексты приходят с сервера, поэтому каждый из них пропускается через
// escapeHtml.
// Заголовки групп и значки статусов — из того же спрайта, что и кнопки: в
// отчёте рядом стоят три состояния, и разнобой между ними читался как шум.
// Названия без значков — для текстового отчёта: в буфер обмена SVG класть нельзя.
const DIAG_GROUP_NAMES = {
  keys: 'Ключи API',
  files: 'Файлы и папки',
  data: 'Данные прошлых сборов',
  runs: 'Прогоны и кэш',
  env: 'Окружение',
  engines: 'Браузер и выдача',
};
const DIAG_GROUP_TITLES = {
  keys:  UI_ICONS.key + DIAG_GROUP_NAMES.keys,
  files: UI_ICONS.folder + DIAG_GROUP_NAMES.files,
  data:  UI_ICONS.box + DIAG_GROUP_NAMES.data,
  runs:  UI_ICONS.pulse + DIAG_GROUP_NAMES.runs,
  env:   UI_ICONS.info + DIAG_GROUP_NAMES.env,
  engines: UI_ICONS.search + DIAG_GROUP_NAMES.engines,
};
const DIAG_STATUS = {
  ok:    { icon: UI_ICONS.check, label: 'в порядке' },
  warn:  { icon: UI_ICONS.warn,  label: 'предупреждение' },
  error: { icon: UI_ICONS.x,     label: 'ошибка' },
};
let _diagBusy = false;
// Последний отчёт — для кнопки «Скопировать»: пересказывать его руками
// в переписке с поддержкой приходилось построчно.
let _diagLast = [];

function showDiagnostics() {
  const existing = document.getElementById('diag-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'diag-overlay';
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal diag-modal" role="dialog" aria-modal="true" aria-labelledby="diag-title">
      <h3 id="diag-title">${UI_ICONS.pulse}Диагностика</h3>
      <div class="diag-lead">Проверю браузер и токен ВК, права на папку результатов, окружение,
        данные прошлых сборов и историю прогонов — то, из-за чего чаще всего «ничего не работает».
        Читать логи не нужно.</div>
      <div class="diag-note">${UI_ICONS.key}«Только ключи» делает один живой запрос к ВКонтакте (проверка токена).
        «Проверить браузер» открывает настоящий Chrome и страницу выдачи: так видно, что браузер
        работает и что список организаций действительно загружается. Остальные проверки
        идут локально и выполняются мгновенно. Ту же самую проверку можно запустить
        без окна приложения: <code>YandexBusinessParser.exe --check</code> (в консоли или в фоне).</div>
      <div class="diag-actions">
        <button type="button" class="btn-sm diag-run" title="Все локальные проверки и токен ВК — без открытия браузера"
          onclick="runDiagnostics(['keys','files','data','runs','env'], this)">${UI_ICONS.checkSquare}Проверить всё</button>
        <button type="button" class="btn-sm diag-run" title="Один живой запрос к ВКонтакте: действителен ли токен"
          onclick="runDiagnostics(['keys'], this)">${UI_ICONS.key}Только ключи</button>
        <button type="button" class="btn-sm diag-run" title="Папки, диск, настройки, данные и история прогонов — ничего не тратит и не запрашивает"
          onclick="runDiagnostics(['files','data','runs','env'], this)">${UI_ICONS.folder}Без запросов к API</button>
        <button type="button" class="btn-sm diag-run" title="Откроет браузер и страницу выдачи: занимает до минуты"
          onclick="runDiagnostics(['engines'], this, true)">${UI_ICONS.pulse}Проверить браузер</button>
      </div>
      <div class="diag-summary" id="diag-summary" role="status" aria-live="polite">Нажмите «Проверить всё» — покажу, что работает, а что нет.</div>
      <div class="diag-legend">
        <span class="diag-legend-item" data-status="ok">${UI_ICONS.check}в порядке</span>
        <span class="diag-legend-item" data-status="warn">${UI_ICONS.warn}будет хуже обычного</span>
        <span class="diag-legend-item" data-status="error">${UI_ICONS.x}сбор не пойдёт</span>
        <span class="diag-legend-tip">Цвет полосы слева и есть статус — читать пояснения построчно не обязательно.</span>
      </div>
      <div class="diag-results" id="diag-results"></div>
      <div class="diag-copy-row">
        <button type="button" class="btn-sm" id="btn-diag-copy" onclick="copyDiagReport(this)"
          title="Скопировать отчёт текстом — удобно переслать или приложить к обращению" disabled>${UI_ICONS.copy}Скопировать отчёт</button>
        <span class="diag-copy-hint">Отчёт без секретов: только статусы и объяснения.</span>
      </div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel" onclick="closeDiagnostics()">Закрыть</button>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeDiagnostics(); });
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') closeDiagnostics(); });
  document.body.appendChild(overlay);
  // Фокус внутрь, Tab и Escape по окну, возврат фокуса на кнопку «Диагностика».
  modalA11y(overlay);
  // Клавиатура: Esc должен работать и без клика внутри модалки.
  document.addEventListener('keydown', _diagEscape);
}

function _diagEscape(e) {
  if (e && e.key === 'Escape') closeDiagnostics();
}

function closeDiagnostics() {
  document.removeEventListener('keydown', _diagEscape);
  const overlay = document.getElementById('diag-overlay');
  if (overlay) overlay.remove();
}

// Группы проверок: ['keys'] — единственный сетевой запрос, остальные локальные.
// deep=true — живая проба браузера: открывает Chrome и грузит страницу
// выдачи, поэтому отдельная кнопка, а не часть «Проверить всё».
function runDiagnostics(groups, btn, deep) {
  if (_diagBusy) return Promise.resolve();
  const list = Array.isArray(groups) && groups.length
    ? groups : ['keys', 'files', 'data', 'runs', 'env'];
  const probe = !!deep;
  _diagBusy = true;
  const buttons = [...document.querySelectorAll('.diag-run')];
  // innerHTML, а не textContent: подписи несут значок из спрайта, и возврат
  // через textContent вставил бы <svg …> в кнопку как обычный текст.
  const labels = buttons.map(b => b.innerHTML);
  const pressed = btn || buttons[0];
  const pressedLabel = pressed ? pressed.innerHTML : '';
  buttons.forEach(b => { b.disabled = true; });
  if (pressed) pressed.innerHTML = UI_ICONS.busy + 'Проверяю…';
  setDiagSummary('⏳ Идут проверки…'
    + (probe ? ' Открываю настоящий браузер и страницу выдачи — это занимает до минуты.' : '')
    + (!probe && list.includes('keys') ? ' Ключи проверяются живыми запросами.' : ''));
  return fetch('/diagnostics/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({groups: list, deep: probe}),
  })
    .then(r => r.json())
    .then(data => {
      if (!data || data.ok === false) {
        setDiagSummary('⛔ Проверки не выполнились: '
          + escapeHtml((data && data.error) || 'сервер не ответил'), 'error');
        _diagLast = [];
        _syncDiagCopyBtn();
        return;
      }
      _diagLast = data.results || [];
      renderDiagnostics(_diagLast, list);
      _syncDiagCopyBtn();
    })
    .catch(() => setDiagSummary('⛔ Не удалось выполнить проверки — сервер недоступен.', 'error'))
    .then(() => {
      _diagBusy = false;
      buttons.forEach((b, i) => { b.disabled = false; b.innerHTML = labels[i]; });
      if (pressed) pressed.innerHTML = pressedLabel;
    });
}

function setDiagSummary(html, status) {
  const el = document.getElementById('diag-summary');
  if (!el) return;
  el.innerHTML = html;
  el.className = 'diag-summary' + (status ? ' diag-summary-' + status : '');
}

function renderDiagnostics(results, groups) {
  const box = document.getElementById('diag-results');
  if (!box) return;
  const errors = results.filter(r => r.status === 'error').length;
  const warns = results.filter(r => r.status === 'warn').length;
  const ok = results.filter(r => r.status === 'ok').length;
  let summary = `Проверок: ${results.length} — `
    + `<b>${ok}</b> в порядке`
    + (warns ? `, <b>${warns}</b> с предупреждениями` : '')
    + (errors ? `, <b>${errors}</b> с ошибками` : '') + '.';
  if (errors) summary += ' Сначала разберитесь с ошибками — с ними работа не пойдёт.';
  else if (warns) summary += ' Ошибок нет; предупреждения — это места, где результат будет хуже обычного.';
  else summary += ' Всё готово к работе.';
  setDiagSummary(summary, errors ? 'error' : (warns ? 'warn' : 'ok'));

  const order = Array.isArray(groups) && groups.length ? groups : Object.keys(DIAG_GROUP_TITLES);
  box.innerHTML = order.map(group => {
    const rows = results.filter(r => r.group === group);
    if (!rows.length) return '';
    return `<div class="diag-group">
      <div class="diag-group-title">${DIAG_GROUP_TITLES[group] || escapeHtml(group)}</div>
      ${rows.map(diagRowHTML).join('')}
    </div>`;
  }).join('') || '<div class="diag-empty">Проверки ничего не вернули.</div>';
}

// ── Копирование отчёта ───────────────────────────────────────
// Смысл: когда что-то не работает, отчёт пересылают автору или кладут в
// обращение. Пересказывать двадцать строк руками — та ещё работа, поэтому
// кнопка отдаёт ровно то же, что видно в окне, без разметки и без секретов.
const DIAG_STATUS_WORDS = { ok: 'OK', warn: 'ВНИМАНИЕ', error: 'ОШИБКА' };

function diagReportText() {
  const lines = ['Диагностика Yandex Business Parser — '
    + new Date().toLocaleString('ru-RU')];
  const counts = { ok: 0, warn: 0, error: 0 };
  for (const group of Object.keys(DIAG_GROUP_NAMES)) {
    const rows = _diagLast.filter(r => r && r.group === group);
    if (!rows.length) continue;
    lines.push('', DIAG_GROUP_NAMES[group]);
    for (const row of rows) {
      const word = DIAG_STATUS_WORDS[row.status] || 'ПРОВЕРКА';
      if (row.status in counts) counts[row.status]++;  // только известные статусы
      lines.push(`  [${word}] ${row.title || ''}`.trimEnd());
      if (row.detail) lines.push(`         ${row.detail}`);
      if (row.hint) lines.push(`         → ${row.hint}`);
    }
  }
  lines.push('', `Итог: ${_diagLast.length} проверок: ${counts.ok} в порядке`
    + (counts.warn ? `, ${counts.warn} с предупреждениями` : '')
    + (counts.error ? `, ${counts.error} с ошибками` : '') + '.');
  return lines.join('\n');
}

function _syncDiagCopyBtn() {
  const btn = document.getElementById('btn-diag-copy');
  if (btn) btn.disabled = !_diagLast.length;
}

function copyDiagReport(btn) {
  if (!_diagLast.length) return Promise.resolve(false);
  const label = btn ? btn.innerHTML : '';
  if (btn) btn.disabled = true;
  return Promise.resolve(copyText(diagReportText()))
    .then(ok => {
      if (typeof showToast === 'function') {
        showToast(ok ? 'Отчёт диагностики скопирован — можно переслать'
                     : 'Не удалось скопировать отчёт — выделите текст в окне',
                 ok ? 'ok' : 'error');
      }
      return ok;
    })
    .finally(() => { if (btn) btn.innerHTML = label; });
}

// Одна строка отчёта: значок по статусу, заголовок, объяснение и что делать.
function diagRowHTML(row) {
  const meta = DIAG_STATUS[row.status] || DIAG_STATUS.warn;
  const detail = row.detail ? `<div class="diag-detail">${escapeHtml(row.detail)}</div>` : '';
  const hint = row.hint ? `<div class="diag-hint">${UI_ICONS.info}${escapeHtml(row.hint)}</div>` : '';
  return `<div class="diag-row" data-status="${escapeHtml(row.status || 'warn')}">
    <div class="diag-row-head">
      <span class="diag-ico" aria-hidden="true">${meta.icon}</span>
      <span class="diag-title">${escapeHtml(row.title || '')}</span>
      <span class="diag-sr">${meta.label}</span>
    </div>
    ${detail}${hint}
  </div>`;
}

// ═══════════════════════════════════════════
//  Version check from GitHub
// ═══════════════════════════════════════════
// Poll GitHub every 30 minutes while the page stays open; the header button
// re-uses the same check on demand.
const UPDATE_CHECK_INTERVAL = 30 * 60 * 1000;

// DEV-сборка (config.is_dev_build) не обновляется публичными релизами:
// сервер отвечает dev:true, баннер и точка обновления не показываются.
let _devBuild = false;

function checkForUpdates(silent) {
  // Frozen build: /update/status also reports latest version + whether the
  // in-app updater is available. Source runs fall back to /check-version.
  return fetch('/update/status')
    .then(r => r.json())
    .then(data => {
      if (data.dev) {
        _devBuild = true;
        setUpdateIndicator(false);
        return { newer: false, dev: true, version: data.current };
      }
      if (data.newer) {
        showUpdateBanner(data.latest, data.changelog || '',
          data.download_url || 'https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest',
          data.asset_name || '');
        setUpdateIndicator(true, data.latest);
        return { newer: true, version: data.latest };
      }
      setUpdateIndicator(false);
      // Сервер может объяснить, почему объявленную версию пока нельзя
      // поставить (релиз ещё не опубликован) — это не ошибка связи.
      return { newer: false, version: data.latest || data.current, notice: data.notice || '' };
    })
    .catch(() => {
      // /update/status unavailable — legacy /check-version fallback
      return fetch('/check-version')
        .then(r => r.json())
        .then(data => {
          if (data.dev) {
            _devBuild = true;
            setUpdateIndicator(false);
            return { newer: false, dev: true, version: data.current };
          }
          if (data.newer) {
            showUpdateBanner(data.remote, data.changelog || '', data.download_url || '');
            setUpdateIndicator(true, data.remote);
            return { newer: true, version: data.remote };
          }
          setUpdateIndicator(false);
          return { newer: false, version: data.current };
        })
        .catch(() => ({ newer: false, error: true }));
    })
    .then(res => {
      if (silent) return res;
      if (res.dev) showToast('DEV-сборка — авто-обновление отключено (только для разработки)', 'info');
      else if (res.error) showToast('Не удалось связаться с GitHub — проверьте интернет', 'error');
      else if (res.newer) showToast(`Новая версия v${res.version} — обновите через баннер сверху`, 'success');
      else if (res.notice) showToast(res.notice, 'info');
      else showToast('Вы на последней версии ✓', 'success');
      return res;
    });
}

// Header button: manual re-check with visual feedback
function manualUpdateCheck(btn) {
  if (!btn || btn.dataset.busy) return;
  btn.dataset.busy = '1';
  btn.classList.remove('has-update');
  btn.innerHTML = '<span class="spin" style="width:11px;height:11px;border-width:1.5px"></span>'
    + '<span class="hdr-lbl">Проверяю…</span>';
  checkForUpdates(false)
    .catch(() => {})
    .finally(() => {
      delete btn.dataset.busy;
      // Надпись восстанавливает индикатор: он заново решит, «🔄 Обновления»
      // или «⬆ Обновить до vX» — исходный innerHTML больше не запоминаем,
      // иначе он затирал бы свежий статус проверки.
      renderUpdateIndicator();
    });
}

// Periodic background check (silent — banner only, no toasts).
// DEV-сборку не проверяем вовсе: узнав про dev:true, выходим из цикла.
setInterval(() => { if (!_devBuild) checkForUpdates(true); }, UPDATE_CHECK_INTERVAL);

// ── Индикация обновления в шапке ──
// Кнопка «Обновления» живёт в приклеенной шапке, поэтому её видно при любой
// прокрутке: она и есть главный индикатор (надпись «⬆ Обновить до vX» +
// пульсация), а тонкая точка — только дополнение к ней.
// Подпись — в обёртке .hdr-lbl: на узком экране она скрывается, и в шапке
// остаются только значки (иначе кнопка снова растягивала страницу вбок).
const UPDATE_BTN_IDLE = UI_ICONS.refresh + '<span class="hdr-lbl">Обновления</span>';
let _availableVersion = '';

function renderUpdateIndicator() {
  const btn = document.getElementById('btn-updates');
  if (!btn) return;
  const on = !!_availableVersion;
  if (!btn.dataset.busy) {
    btn.classList.toggle('has-update', on);
    btn.innerHTML = on
      ? (UI_ICONS.upload + '<span class="hdr-lbl">' + `Обновить до v${_availableVersion}` + '</span>')
      : UPDATE_BTN_IDLE;
    btn.setAttribute('aria-label', on ? `Обновить до v${_availableVersion}` : 'Обновления');
  }
  let dot = document.getElementById('update-dot');
  if (!dot) {
    dot = document.createElement('span');
    dot.id = 'update-dot';
    dot.title = 'Доступно обновление';
    btn.appendChild(dot);
  }
  if (on) {
    dot.dataset.version = _availableVersion;
    dot.classList.add('on');
  } else {
    dot.classList.remove('on');
  }
}

function setUpdateIndicator(on, version) {
  _availableVersion = on ? String(version || '') : '';
  renderUpdateIndicator();
}

// Высоту баннера нельзя зашить в CSS: на узком экране кнопки переносятся на
// вторую строку, и страницу нужно сдвинуть ровно на его высоту.
function _syncBannerOffset() {
  const banner = document.getElementById('update-banner');
  document.body.classList.toggle('has-update-banner', !!banner);
  document.body.style.paddingTop = banner ? banner.offsetHeight + 'px' : '';
}
window.addEventListener('resize', _syncBannerOffset);

// Закрытый баннер не возвращаем для ТОЙ ЖЕ версии (кнопка в шапке всё равно
// продолжает сообщать об обновлении), но новую версию показываем снова.
let _dismissedBannerVersion = '';

function dismissUpdateBanner() {
  const banner = document.getElementById('update-banner');
  _dismissedBannerVersion = banner ? (banner.dataset.version || '') : '';
  if (banner) banner.remove();
  _syncBannerOffset();
}

// `assetName` — файл релиза под текущую систему (windows zip или macos .dmg):
// сервер отдаёт его вместе со ссылкой, чтобы кнопка не обещала .exe сборке на
// macOS. Формат пишем в подписи: «Скачать v2.3.4 (macOS, .dmg) ↗».
function _assetLabel(assetName) {
  const name = String(assetName || '');
  const ext = (name.match(/\.[a-z0-9]+$/i) || [''])[0].toLowerCase();
  const os = /macos/i.test(name) ? 'macOS' : (/windows/i.test(name) ? 'Windows' : '');
  const parts = [os, ext].filter(Boolean);
  return parts.length ? ` (${parts.join(', ')})` : '';
}

function showUpdateBanner(newVer, changelog, url, assetName) {
  // Remove existing banner if any
  const existing = document.getElementById('update-banner');
  if (existing) existing.remove();
  // Пользователь закрыл баннер этой версии — уважаем выбор: индикация
  // остаётся в шапке («⬆ Обновить до vX»), но окно больше не перекрываем.
  if (_dismissedBannerVersion && _dismissedBannerVersion === String(newVer)) {
    _syncBannerOffset();
    return;
  }

  // Frozen build: «Обновить сейчас» is the PRIMARY action — it downloads,
  // installs and restarts inside the app (no GitHub visit needed).
  // Source run: no in-app updater, so GitHub becomes the primary action.
  fetch('/update/status').then(r => r.json()).then(st => {
    // Сам обновляет файлы только Windows-сборка; macOS-бандл и исходники
    // получают ссылку на релиз (auto_apply=false приходит с сервера).
    const frozen = !!st.frozen && st.auto_apply !== false;
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.dataset.version = String(newVer);
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <button class="ub-btn" id="ub-changelog" onclick="showChangelog()" title="Подробнее об изменениях в новой версии">${UI_ICONS.file}Что нового</button>
      ${frozen
        ? `<button class="ub-btn ub-primary" id="ub-self-update" onclick="selfUpdate()" title="Скачать и установить прямо из приложения — после установки просто обновите страницу">${UI_ICONS.upload}Обновить сейчас</button>
           <a class="ub-btn" href="${url}" target="_blank" rel="noopener noreferrer" title="Страница релизов на GitHub">GitHub ↗</a>`
        : `<a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer" title="Скачайте сборку для своей системы${assetName ? ': ' + escapeHtml(assetName) : ''}">Скачать v${newVer}${_assetLabel(assetName)} ↗</a>`}
      <button class="ub-close" onclick="dismissUpdateBanner()" title="Скрыть (индикация останется в шапке)">${UI_ICONS.x}</button>
    `;
    document.body.prepend(banner);
    _syncBannerOffset();
  }).catch(() => {
    // /update/status is dead — render the source-mode banner (GitHub primary)
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.dataset.version = String(newVer);
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
      <button class="ub-close" onclick="dismissUpdateBanner()" title="Скрыть (индикация останется в шапке)">${UI_ICONS.x}</button>
    `;
    document.body.prepend(banner);
    _syncBannerOffset();
  });
}

// ── Changelog viewer: full version.json (whats-new) in a modal ──
let _changelogCache = null;

function showChangelog() {
  const close = () => document.getElementById('changelog-overlay')?.remove();
  const render = (meta, err) => {
    const cur = (document.getElementById('app-version') || {}).textContent || '';
    const rows = (meta && meta.history ? meta.history : [])
      .map(h => `
        <div class="cl-entry ${h.version === (meta.version || '') ? 'cl-latest' : ''}">
          <div class="cl-ver">v${escapeHtml(h.version || '?')}${h.version === (meta.version || '') ? '<span class="cl-tag">новейшая</span>' : ''}${cur.includes(h.version) ? '<span class="cl-tag cl-yours">у вас</span>' : ''}</div>
          <div class="cl-text">${escapeHtml(h.changelog || '—')}</div>
        </div>`).join('')
      || `<div class="cl-entry"><div class="cl-text">${err ? 'Не удалось загрузить список изменений — проверьте интернет.' : escapeHtml((meta && meta.changelog) || '—')}</div></div>`;
    const overlay = document.createElement('div');
    overlay.id = 'changelog-overlay';
    overlay.className = 'ui-modal-overlay';
    overlay.innerHTML = `
      <div class="ui-modal changelog-modal">
        <h3>${UI_ICONS.file}Что нового</h3>
        <div class="cl-list">${rows}</div>
        <div class="ui-modal-btns">
          <button type="button" class="m-cancel" onclick="document.getElementById('changelog-overlay').remove()">Закрыть</button>
        </div>
      </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    document.body.appendChild(overlay);
    modalA11y(overlay);
  };
  if (_changelogCache) { render(_changelogCache); return; }
  fetch('/update/changelog')
    .then(r => r.json())
    .then(meta => { _changelogCache = meta; render(meta); })
    .catch(() => render(null, true));
}

// ── Self-update: download → apply → the app restarts itself ──
let _selfUpdating = false;

async function selfUpdate() {
  if (_selfUpdating) return;
  const btn = document.getElementById('ub-self-update');
  const txt = el => { if (btn) btn.textContent = el; };
  _selfUpdating = true;
  try {
    txt('⏳ Скачиваю…');
    const dl = await fetch('/update/download', { method: 'POST' })
      .then(r => r.json());
    if (!dl.ok) throw new Error(dl.error || 'Ошибка скачивания');

    txt('⏳ Устанавливаю…');
    const ap = await fetch('/update/apply', { method: 'POST' })
      .then(r => r.json());
    if (!ap.ok) throw new Error(ap.error || 'Ошибка установки');

    if (typeof showToast === 'function') showToast(ap.message || 'Обновление установлено, перезапускаюсь…', 'success');
    txt('✓ Перезапуск…');
    // The backend stops itself and the updater .bat restarts the exe.
    // Poll /update/status — as soon as the server answers again with a
    // fresh version, reload the page.
    const deadline = Date.now() + 60000;
    const poll = setInterval(async () => {
      try {
        const s = await fetch('/update/status', { cache: 'no-store' }).then(r => r.json());
        clearInterval(poll);
        location.reload();
      } catch (e) { if (Date.now() > deadline) { clearInterval(poll); location.reload(); } }
    }, 1500);
  } catch (e) {
    _selfUpdating = false;
    txt('⬆ Обновить сейчас');
    if (typeof showToast === 'function') showToast('Не удалось обновиться: ' + e.message, 'error');
  }
}
// ═══════════════════════════════════════════════════════════════
//  Шаблоны сообщений («📝 Шаблоны»)

// ═══════════════════════════════════════════
//  Шаги «Как это работает» — не картинка, а действие
//
//  Три шага на пустом экране объясняли, что делать, но были обычными блоками:
//  тень при наведении обещала клик, которого не было. Теперь каждый шаг
//  делает то, о чём говорит: ведёт к полю, запускает поиск, открывает
//  результаты — и объясняет, чего не хватает, если запустить пока нельзя.
// ═══════════════════════════════════════════
function _onboardingFocus(id) {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  // Фокус ставится ПОСЛЕ клика: браузер переводит фокус на нажатую кнопку-шаг
  // уже после обработчика, и он «съедал» поле, к которому шаг ведёт.
  setTimeout(() => {
    if (typeof el.focus === 'function') el.focus({ preventScroll: true });
  }, 0);
  return true;
}

function onboardingStep(n) {
  if (n === 1) {
    // «Напишите запрос и город»: открываем раздел и ставим курсор в то поле,
    // которое ещё пустое — сначала запрос, потом город.
    const sec = document.getElementById('acc-basic');
    if (sec && !sec.classList.contains('open')) {
      const hdr = sec.querySelector('.acc-hdr');
      if (hdr) toggleAccordion(hdr);
    }
    const queries = (document.getElementById('f-queries')?.value || '').trim();
    _onboardingFocus(queries ? 'f-city-input' : 'f-queries');
    return;
  }

  if (n === 2) {
    // «Найти компании»: если данных не хватает — не молчим и не жмём впустую,
    // а говорим, чего именно не хватает, и ведём к нужному полю.
    if (isRunActive()) { showToast('Поиск уже идёт', 'info'); return; }
    const queries = (document.getElementById('f-queries')?.value || '').trim();
    if (!queries) {
      showToast('Сначала напишите, кого искать — например «кафе»', 'error');
      _onboardingFocus('f-queries');
      return;
    }
    if (!selectedCities.length) {
      showToast('Выберите хотя бы один город в разделе «Где ищем?»', 'error');
      _onboardingFocus('f-city-input');
      return;
    }
    document.getElementById('btn-run')?.click();
    return;
  }

  if (n === 3) {
    // «Просмотрите результаты»: пока показывать нечего, говорим об этом.
    const hasRows = (typeof allResults !== 'undefined' && allResults.length > 0);
    showTab('table');
    if (!hasRows) {
      showToast('Пока пусто — запустите поиск, и результаты появятся здесь', 'info');
    }
  }
}

// ═══════════════════════════════════════════
//  Сообщить о проблеме: issue на GitHub
// ═══════════════════════════════════════════
// Кнопка в шапке открывает окно: пользователь пишет письмо, выбирает
// метки и куски контекста, а кнопка открывает форму GitHub с
// предзаполненным телом (URL-параметры new issue). Загружать файлы на
// GitHub приложение не умеет и не должно (для этого нужен ключ и токен
// пользователя), поэтому скриншот перекладывается штатным путём: вставка
// из буфера обмена — туда же, куда его кладёт Win+Shift+S.
const REPORT_REPO = 'ScarFace11/Yandex-Buisnes-Parser';
// Метки — стандартный набор репозитория (проверено по GitHub API).
// Цвета — как у меток на самом GitHub (примечательно: у каждой метки свой,
// поэтому они читаются как привычные пилюли, а не как однообразные галочки).
const REPORT_LABELS = [
  { id: 'bug',           lbl: 'Баг — что-то не работает',         color: '#d73a49', on: true },
  { id: 'enhancement',   lbl: 'Улучшение — новая возможность',    color: '#a2eeef' },
  { id: 'question',      lbl: 'Вопрос — нужен совет',              color: '#d876e3' },
  { id: 'documentation', lbl: 'Документация — инструкции, README', color: '#0075ca' },
  { id: 'accessibility', lbl: 'Доступность — сложность использования', color: '#8250df' },
];
// Куски контекста: сервер даёт env/runs/лог, вкладка — свои фильтры.
const REPORT_CTX_PARTS = [
  { id: 'env',    lbl: 'Версия, система и браузер' },
  { id: 'runs',   lbl: 'Последний прогон и кэш' },
  { id: 'log',    lbl: 'Последние строки лога' },
  { id: 'client', lbl: 'Фильтры и настройки этой вкладки' },
];
let _reportServerCtx = '';   // текст с сервера (env/runs/лог), по запросу
let _reportShot = '';        // dataURL последнего скриншота (только превью)
let _reportShotInClipboard = false;  // лежит ли картинка в буфере обмена
let _reportInitial = '';     // снимок формы при открытии — для «Отменить»
let _ghDeviceTimer = null;   // поллинг device flow (setInterval)
// Выбор меток и кусков контекста запоминается между открытиями окна:
// второй раз описывать баг одной и той же рубрикой не нужно.
const REPORT_CHOICES_KEY = 'yp_report_choices_v1';

// Тело issue собирается из кусков — чистая функция, её же гоняет node-тест.
function composeReportBody(desc, sections) {
  const head = (desc || '').trim() || '(описание не заполнено)';
  const rest = (sections || []).filter(Boolean).join('\n\n');
  return rest ? head + '\n\n---\n\n' + rest : head;
}

// Раздел контекста с сервера по заголовку («## Версия…» — до пустой строки).
function _serverSection(ctx, titlePart) {
  const parts = String(ctx || '').split(/\n\n(?=## )/);
  const hit = parts.find(p => p.indexOf('## ' + titlePart) === 0);
  return hit || '';
}

// Настройки вкладки — из localStorage: сервер их не видит, а для
// «почему у меня так, а не иначе» это самое первое, что нужно.
function _clientSettingsSection() {
  const lines = ['## Фильтры и настройки этой вкладки'];
  const read = (key) => {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  };
  const form = read('yp_settings_v1');
  if (form) {
    try {
      const s = JSON.parse(form);
      const interesting = ['query', 'queries', 'cities', 'parse_mode', 'social_mode',
                           'required_socials', 'min_lead_score', 'formats', 'max_pages'];
      interesting.forEach(k => {
        if (s[k] !== undefined && s[k] !== null && s[k] !== '') {
          lines.push('- ' + k + ': ' + JSON.stringify(s[k]));
        }
      });
    } catch (e) { lines.push('- сохранённые фильтры не разобрать: ' + e.name); }
  }
  const fields = read('yp_parse_fields_v1');
  if (fields) lines.push('- выбранные поля отчёта: ' + (fields.length > 160 ? fields.slice(0, 160) + '…' : fields));
  lines.push('- тема: ' + (THEME_RU[read('yp_theme_v1')] || 'по умолчанию'));
  lines.push('- таблица: «все поиски» = ' + (read('yp_results_scope') || 'нет')
             + ', режим = ' + (read('yp_results_subtab') || 'сырые'));
  return lines.length > 1 ? lines.join('\n') : '';
}

// URL формы GitHub. Длина ограничена: длинный адрес браузеры и GitHub
// обрезают молча, поэтому при нехватке места последние разделы контекста
// отбрасываются с явной пометкой в конце тела.
function buildIssueUrl(opts) {
  const title = String((opts && opts.title) || '').trim() || 'Сообщение из приложения';
  const labels = (opts && opts.labels || []).filter(Boolean).join(',');
  const limit = 7000;   // запас до жёстких лимитов URI
  let body = String((opts && opts.body) || '');
  let url = _issueUrl(title, labels, body);
  let dropped = false;
  while (url.length > limit && /\n\n## /.test(body)) {
    // Последний раздел контекста — за борт (описание пользователя важнее).
    // URL пересчитывается на каждой итерации: без этого условие смотрит на
    // первый замер и сносит все разделы разом, хотя хватило бы одного.
    const idx = body.lastIndexOf('\n\n## ');
    body = body.slice(0, idx);
    url = _issueUrl(title, labels, body);
    dropped = true;
  }
  if (dropped) {
    body += '\n\n_(некоторые разделы контекста опущены из-за длины сообщения — '
          + 'полная версия остаётся в описании формы, скопируйте её при необходимости)_';
  }
  url = _issueUrl(title, labels, body);
  // truncated — «тело пришлось обрезать»: интерфейс предупреждает, что часть
  // контекста не доехала. Не «снова не влезло» — после обрезки URL обычно
  // укладывается в лимит, но пользователю это знать всё равно нужно.
  return { url: url, body: body, truncated: dropped };
}

function _issueUrl(title, labels, body) {
  const qs = 'title=' + encodeURIComponent(title)
    + (labels ? '&labels=' + encodeURIComponent(labels) : '')
    + '&body=' + encodeURIComponent(body);
  return 'https://github.com/' + REPORT_REPO + '/issues/new?' + qs;
}

function openReportModal() {
  const existing = document.getElementById('report-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'report-overlay';
  overlay.className = 'ui-modal-overlay';
  // Метки — не список галочек, а поле-дропдаун: внутри выпадает список с
  // цветными пилюлями, как на самом GitHub. Чекбоксы .rep-label остаются
  // прежними — сбор выбранных меток (openGitHubIssue/sendReportIssue) не меняется.
  const labelOpts = REPORT_LABELS.map(l => `
    <label class="rep-label-opt">
      <input type="checkbox" class="rep-label" value="${l.id}" ${l.on ? 'checked' : ''}>
      <span class="gh-pill" style="${_ghPillCss(l.color)}">${escapeHtml(l.id)}</span>
      <span class="rep-label-desc">${escapeHtml(l.lbl)}</span>
    </label>`).join('');
  const ctxRows = REPORT_CTX_PARTS.map(p => `
    <label class="chk"><input type="checkbox" class="rep-ctx" value="${p.id}" checked>
      <span>${escapeHtml(p.lbl)}</span></label>`).join('');
  overlay.innerHTML = `
    <div class="ui-modal report-modal" role="dialog" aria-modal="true" aria-labelledby="report-title">
      <button type="button" class="rep-x" onclick="cancelReportModal()"
              title="Закрыть окно" aria-label="Закрыть окно">${UI_ICONS.x}</button>
      <h3 id="report-title">${UI_ICONS.warn}Сообщить о проблеме</h3>
      <!-- GitHub не создаёт issue анонимно. Поле токена убрано: вместо него —
           вход по коду (device flow, client_id зашит в приложение); кнопка
           входа показывается только при can_device, а без токена сообщение
           уходит заполненной формой (кнопка внизу слева). -->
      <div class="rep-gh-login" id="rep-gh-login" role="status" hidden>
        <span class="rep-gh-txt" id="rep-gh-txt">GitHub не подключён — войдите по коду,
          и «Создать issue» будет работать напрямую: без открытия формы.</span>
        <span class="rep-gh-actions">
          <button type="button" class="btn-sm" id="rep-gh-login-btn"
                  onclick="startGitHubDeviceLogin()"
                  title="Войти в GitHub по коду — токен придёт сам, вводить его нигде не нужно">
            ${UI_ICONS.key}Войти в GitHub</button>
          <a class="rep-gh-link" href="https://github.com/login/device" target="_blank" rel="noopener">Страница авторизации</a>
        </span>
        <span class="rep-gh-code" id="rep-gh-code" hidden></span>
      </div>
      <div class="diag-lead">Опишите, что случилось, — и отправьте. Метки, контекст
        (версия, система, браузер, последний прогон, логи) и заголовок собираются
        сами; скриншот вставляется в окно и перекладывается в форму GitHub.</div>
      <div class="rep-sec-lbl" id="rep-labels-lbl">Метки GitHub</div>
      <div class="rep-label-select" id="rep-label-select">
        <button type="button" class="rep-label-field" id="rep-label-field"
                aria-haspopup="listbox" aria-expanded="false"
                aria-labelledby="rep-labels-lbl">
          <span class="rep-label-pills" id="rep-label-pills"></span>
          <span class="rep-label-caret" aria-hidden="true">▾</span>
        </button>
        <div class="rep-label-menu" id="rep-label-menu" role="listbox"
             aria-multiselectable="true" aria-labelledby="rep-labels-lbl" hidden>
          ${labelOpts}
        </div>
      </div>
      <div class="rep-sec-lbl"><label for="rep-title-inp">Заголовок</label></div>
      <input type="text" id="rep-title-inp" placeholder="Коротко: что не работает"
             aria-label="Заголовок сообщения">
      <div class="rep-sec-lbl"><label for="rep-desc">Описание</label></div>
      <textarea id="rep-desc" rows="5"
        placeholder="Что делали, что ожидалось, что получилось. Шаги воспроизведения — если они есть."></textarea>
      <div class="rep-sec-lbl">Что приложить к сообщению</div>
      <div class="rep-checks">${ctxRows}</div>
      <details class="rep-preview-wrap">
        <summary>Показать прилагаемый контекст</summary>
        <pre class="rep-preview" id="rep-preview">Загружаю контекст…</pre>
      </details>
      <div class="rep-sec-lbl">Скриншот</div>
      <div class="rep-shot" id="rep-shot" tabindex="0" role="button"
           aria-label="Область для вставки скриншота">
        Нажмите сюда и вставьте скриншот из буфера: <b>Ctrl+V</b>
        (снимок экрана кладётся туда же — Win+Shift+S на Windows).
        На GitHub он вставляется туда же — после открытия формы.
      </div>
      <!-- Кнопка вне rep-shot: тот имеет роль button, и кнопка внутри была бы
           вложенным элементом управления — клик дошёл бы и до выбора файла. -->
      <div class="rep-shot-actions" id="rep-shot-actions" hidden>
        <button type="button" class="btn-sm" onclick="copyReportShot(this)"
                title="Положить показанный скриншот в буфер обмена — затем Ctrl+V в форме GitHub">
          ${UI_ICONS.copy}Скопировать скриншот в буфер</button>
      </div>
      <div class="ui-modal-btns">
        <button type="button" class="btn-sm rep-form-btn" onclick="openGitHubIssue()"
                title="Открыть заполненную форму issue — работает и без токена">${UI_ICONS.external}Открыть форму на GitHub</button>
        <button type="button" class="m-cancel rep-cancel" onclick="cancelReportModal()"
                title="Отменить создание сообщения">Отменить</button>
        <button type="button" class="m-ok" id="rep-issue"
                onclick="sendReportIssue()"
                title="Создать issue на GitHub через API — без открытия сайта">${UI_ICONS.send}Создать issue</button>
      </div>
    </div>`;
  // Клик вне окна и Escape ведут себя как «Отменить»: если пользователь что-то
  // ввёл или выбрал — сначала подтверждение, а не мгновенная потеря данных.
  overlay.addEventListener('click', e => { if (e.target === overlay) cancelReportModal(); });
  document.body.appendChild(overlay);
  modalA11y(overlay);
  // Контекст с сервера — одним запросом; форма показывает его сразу.
  _reportServerCtx = '';
  fetch('/report/context')
    .then(r => r.json())
    .then(d => {
      _reportServerCtx = (d && d.ok && d.context) || '';
      _repSyncGithubLogin(!!(d && d.has_token), !!(d && d.can_device));
      _renderReportPreview();
    })
    .catch(() => {
      _reportServerCtx = '(контекст с сервера не получен — сервер недоступен)';
      _repSyncGithubLogin(null, false);
      _renderReportPreview();
    });
  // Обновление предпросмотра при любом изменении набора кусков контекста;
  // выбор запоминаем — при следующем открытии окно откроется с ним.
  overlay.querySelectorAll('.rep-ctx').forEach(cb => cb.addEventListener('change', () => {
    _renderReportPreview();
    _reportSaveChoices();
  }));
  // Дропдаун меток: открытие/закрытие и перерисовка выбранных пилюль в поле.
  _reportRestoreChoices();
  _repRenderPills();
  document.getElementById('rep-label-field').addEventListener('click', () => {
    const menu = document.getElementById('rep-label-menu');
    _repToggleLabelMenu(menu.hidden);
  });
  overlay.querySelectorAll('.rep-label').forEach(cb =>
    cb.addEventListener('change', () => {
      _repRenderPills();
      _renderReportPreview();
      _reportSaveChoices();
    }));
  // Клик мимо списка (и клавиши) закрывают дропдаун, но не модалку.
  overlay.addEventListener('click', e => {
    if (!e.target.closest('#rep-label-select')) _repToggleLabelMenu(false);
  });
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') _repToggleLabelMenu(false); });
  // Исходное состояние — чтобы «Отменить» понял, есть ли что терять.
  _reportInitial = _reportSnapshot();
  // Скриншот: вставка из буфера и выбор файла — оба пути дают превью.
  const shot = document.getElementById('rep-shot');
  shot.addEventListener('paste', _reportShotPasted);
  shot.addEventListener('click', () => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = 'image/*';
    inp.onchange = () => { if (inp.files && inp.files[0]) _reportShotFile(inp.files[0], true); };
    inp.click();
  });
  _renderReportPreview();
}

function _reportShotPasted(e) {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  for (const it of items) {
    if (it.type && it.type.indexOf('image/') === 0) {
      const file = it.getAsFile();
      if (file) { e.preventDefault(); _reportShotFile(file); }
      return;
    }
  }
}

function _reportShotFile(file, fromFile) {
  const reader = new FileReader();
  reader.onload = () => {
    _reportShot = String(reader.result || '');
    _reportShotInClipboard = !fromFile;   // вставка пришла из буфера — файл оттуда не брался
    const box = document.getElementById('rep-shot');
    if (!box) return;
    // Выбранный файл в буфере НЕ лежит — раньше такое превью обещало
    // вставку «он всё ещё в буфере», и вставка не работала.
    const note = fromFile
      ? 'Картинка выбрана файлом — сама по себе в буфере она не лежит. '
        + 'Нажмите «Скопировать скриншот в буфер», затем Ctrl+V в форме GitHub.'
      : 'Скриншот показан здесь, но на GitHub он попадает только вставкой: '
        + 'в форме GitHub нажмите в тело сообщения и <b>Ctrl+V</b> — он всё ещё в буфере обмена.';
    box.innerHTML = '<img src="' + _reportShot + '" alt="Выбранный скриншот">'
      + '<div class="rep-shot-note">' + note + '</div>';
    const actions = document.getElementById('rep-shot-actions');
    if (actions) actions.hidden = false;
  };
  reader.readAsDataURL(file);
}

// Подключение GitHub: сервер отдаёт два булевых признака — has_token (токен
// уже есть) и can_device (в сборке зашит client_id, вход по коду возможен).
// Поля ввода токена в окне больше нет — вместо него вход по коду (device
// flow): приложение показывает код, ведёт на github.com/login/device и
// само меняет подтверждённый код на токен. Без client_id кнопки входа нет
// вовсе: обычному пользователю не предлагают создавать OAuth-приложение —
// остаётся заполненная форма.
function _repSyncGithubLogin(has, canDevice) {
  const el = document.getElementById('rep-gh-login');
  if (!el) return;
  el.hidden = has === true;
  // Идущий вход по коду не сбрасываем: контекст с сервера приезжает
  // асинхронно и мог бы своим ответом убить уже начатый поллинг.
  if (has !== true && !_ghDeviceTimer) {
    _ghDeviceReset();   // кнопку возвращает в исходное состояние — ниже своё
    const login = canDevice === true;
    const btn = document.getElementById('rep-gh-login-btn');
    if (btn) btn.hidden = !login;
    const actions = el.querySelector('.rep-gh-actions');
    if (actions) actions.hidden = !login;
    const txt = el.querySelector('.rep-gh-txt');
    if (txt) {
      txt.textContent = has === null
        ? 'Сервер недоступен — вход по коду не работает, но сообщение всё равно уйдёт заполненной формой.'
        : (login
          ? 'GitHub не подключён — войдите по коду, и «Создать issue» будет работать напрямую: без открытия формы.'
          : 'GitHub не подключён — сообщение уйдёт заполненной формой на GitHub: войдите туда обычным способом, форма уже заполнена.');
    }
  }
}

// ── Вход в GitHub по коду (device flow) ──────────────────
function _ghDeviceReset() {
  if (_ghDeviceTimer) { clearInterval(_ghDeviceTimer); _ghDeviceTimer = null; }
  const box = document.getElementById('rep-gh-code');
  if (box) { box.hidden = true; box.innerHTML = ''; }
  const btn = document.getElementById('rep-gh-login-btn');
  if (btn) { btn.hidden = false; btn.disabled = false; btn.innerHTML = UI_ICONS.key + 'Войти в GitHub'; }
}

function _ghDeviceStatus(text) {
  const txt = document.getElementById('rep-gh-txt');
  if (txt) txt.textContent = text;
}

// Кнопка «Войти в GitHub»: сервер выдаёт код, окно показывает его, открывается
// страница авторизации, и дальше приложение само ждёт подтверждения.
function startGitHubDeviceLogin() {
  const btn = document.getElementById('rep-gh-login-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = 'Запрашиваю код…'; }
  return fetch('/report/github/device/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
    .then(r => r.json())
    .then(d => {
      if (!d || !d.ok) {
        _ghDeviceStatus((d && d.error) || 'GitHub не выдал код входа — попробуйте позже.');
        if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.key + 'Войти в GitHub'; }
        return false;
      }
      const codeBox = document.getElementById('rep-gh-code');
      if (codeBox) {
        codeBox.hidden = false;
        codeBox.innerHTML = 'Код: <b class="rep-gh-usercode">' + escapeHtml(d.user_code)
          + '</b> — введите его на <a href="' + escapeHtml(d.verification_uri)
          + '" target="_blank" rel="noopener">странице авторизации</a> и подтвердите доступ. '
          + 'Жду подтверждения…';
      }
      if (btn) btn.hidden = true;
      try { window.open(d.verification_uri, '_blank'); } catch (e) { /* вкладку блокируем сами, ссылка есть в тексте */ }
      _ghDevicePoll(d.device_code, d.interval || 5);
      return true;
    })
    .catch(() => {
      _ghDeviceStatus('Сервер не ответил — попробуйте ещё раз или откройте страницу авторизации по ссылке.');
      if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.key + 'Войти в GitHub'; }
      return false;
    });
}

// Опрос сервера каждые interval секунд (GitHub сам присылает slow_down —
// тогда удлиняем паузу). Сбой одного опроса поллинг не бросает.
function _ghDevicePoll(deviceCode, interval) {
  _ghDeviceTimer = setInterval(() => {
    fetch('/report/github/device/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_code: deviceCode }),
    })
      .then(r => r.json())
      .then(d => {
        if (d && d.ok) {
          _ghDeviceReset();
          const el = document.getElementById('rep-gh-login');
          if (el) el.hidden = true;
          showToast('GitHub подключён — «Создать issue» работает напрямую', 'ok');
          if (d.save_warning) appendLog('warn', 'Токен не сохранён: ' + d.save_warning);
          return;
        }
        if (d && d.pending) { if (d.slow_down) interval += 5; return; }
        _ghDeviceReset();
        _ghDeviceStatus((d && d.error) || 'Вход не завершён — попробуйте ещё раз.');
      })
      .catch(() => { /* один сбой опроса — не повод бросать ожидание */ });
  }, Math.max(1, interval) * 1000);
}

// ── Память выбора: метки и куски контекста ───────────────────────
function _reportSaveChoices() {
  const overlay = document.getElementById('report-overlay');
  if (!overlay) return;
  const ids = sel => [...overlay.querySelectorAll(sel)]
    .filter(cb => cb.checked).map(cb => cb.value);
  try {
    localStorage.setItem(REPORT_CHOICES_KEY, JSON.stringify({
      labels: ids('.rep-label'),
      ctx: ids('.rep-ctx'),
    }));
  } catch (e) { /* приватный режим — просто не запоминаем */ }
}

function _reportRestoreChoices() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(REPORT_CHOICES_KEY) || 'null'); }
  catch (e) { saved = null; }
  if (!saved) return;   // первый запуск — значения по умолчанию из разметки
  const overlay = document.getElementById('report-overlay');
  if (!overlay) return;
  const apply = (sel, wanted) => {
    if (!Array.isArray(wanted)) return;
    const set = new Set(wanted.map(String));
    overlay.querySelectorAll(sel).forEach(cb => { cb.checked = set.has(cb.value); });
  };
  apply('.rep-label', saved.labels);
  apply('.rep-ctx', saved.ctx);
}

// Двухступенчатая картинка → PNG-блоб для клипборда.
// Клипборду нужен именно image/png: файл мог быть JPEG, а вставка из буфера
// в форму GitHub ждёт PNG.
function _shotPngBlob(dataUrl) {
  return new Promise(resolve => {
    if (!dataUrl || dataUrl.indexOf('data:image/png') !== 0) {
      if (!dataUrl) { resolve(null); return; }
      const img = new Image();
      img.onload = () => {
        try {
          const c = document.createElement('canvas');
          c.width = img.naturalWidth; c.height = img.naturalHeight;
          c.getContext('2d').drawImage(img, 0, 0);
          c.toBlob(b => resolve(b), 'image/png');
        } catch (e) { resolve(null); }
      };
      img.onerror = () => resolve(null);
      img.src = dataUrl;
      return;
    }
    try {
      const bin = atob(dataUrl.slice(dataUrl.indexOf(',') + 1));
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      resolve(new Blob([bytes], { type: 'image/png' }));
    } catch (e) { resolve(null); }
  });
}

// Кнопка «Скопировать скриншот в буфер»: после неё Ctrl+V в форме GitHub
// (или в комментарии к созданному issue) вставляет именно эту картинку.
function copyReportShot(btn) {
  if (!_reportShot) {
    showToast('Скриншот не выбран', 'warn');
    return Promise.resolve(false);
  }
  const label = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = 'Копирую…'; }
  return _shotPngBlob(_reportShot)
    .then(blob => {
      if (!blob || !window.ClipboardItem
          || !navigator.clipboard || !navigator.clipboard.write) {
        throw new Error('clipboard unsupported');
      }
      return navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    })
    .then(() => {
      _reportShotInClipboard = true;
      showToast('Скриншот в буфере — Ctrl+V в форме GitHub', 'ok');
      return true;
    })
    .catch(() => {
      showToast('Браузер не дал скопировать картинку — скопируйте её из превью (Ctrl+C)', 'error');
      return false;
    })
    .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = label; } });
}

function _renderReportPreview() {
  const pre = document.getElementById('rep-preview');
  if (!pre) return;
  const parts = [];
  const ctx = _reportServerCtx;
  if (_ctxChecked('env')) parts.push(_serverSection(ctx, 'Версия, система и браузер'));
  if (_ctxChecked('runs')) parts.push(_serverSection(ctx, 'Прогоны и кэш'));
  if (_ctxChecked('log')) parts.push(_serverSection(ctx, 'Последние строки лога'));
  if (_ctxChecked('client')) parts.push(_clientSettingsSection());
  const body = composeReportBody('', parts);
  pre.textContent = body || '(пусто — отметьте хотя бы один пункт)';
}

function _ctxChecked(id) {
  const cb = document.querySelector('#report-overlay .rep-ctx[value="' + id + '"]');
  return !cb || cb.checked;
}

function _reportBodyNow() {
  const overlay = document.getElementById('report-overlay');
  const desc = overlay ? (document.getElementById('rep-desc') || {}).value : '';
  const parts = [];
  const ctx = _reportServerCtx;
  if (_ctxChecked('env')) parts.push(_serverSection(ctx, 'Версия, система и браузер'));
  if (_ctxChecked('runs')) parts.push(_serverSection(ctx, 'Прогоны и кэш'));
  if (_ctxChecked('log')) parts.push(_serverSection(ctx, 'Последние строки лога'));
  if (_ctxChecked('client')) parts.push(_clientSettingsSection());
  if (_reportShot) {
    parts.push(_reportShotInClipboard
      ? '> [!NOTE]\n> Скриншот был вставлен в окно приложения; вставьте его сюда: '
        + 'нажмите в тело сообщения и Ctrl+V — снимок всё ещё в буфере обмена.'
      : '> [!NOTE]\n> Скриншот показан в окно приложения, но в буфере его нет '
        + '(кнопка «Скопировать скриншот в буфер» в окне сообщения); '
        + 'вставьте его сюда через Ctrl+V, если оно нужно.');
  }
  return composeReportBody(desc, parts);
}

function openGitHubIssue() {
  const overlay = document.getElementById('report-overlay');
  if (!overlay) return;
  const title = (document.getElementById('rep-title-inp') || {}).value || '';
  const labels = [...overlay.querySelectorAll('.rep-label')]
    .filter(cb => cb.checked).map(cb => cb.value);
  const made = buildIssueUrl({ title: title, labels: labels, body: _reportBodyNow() });
  const win = window.open(made.url, '_blank');
  if (!win) {
    // Браузер заблокировал окно — текст в буфере, ссылку показываем в логе.
    copyText(made.body);
    showToast('Браузер заблокировал открытие — текст скопирован, ссылка в журнале', 'warn');
    appendLog('warn', 'Открыть форму вручную: ' + made.url.slice(0, 160) + '…');
    return;
  }
  if (made.truncated) {
    showToast('Контекст не поместился в ссылку — часть разделов опущена', 'warn');
  }
  closeReportModal();
}

// «Создать issue» — отправка тем же набором, что и в форму, но через
// GitHub API: без открытия сайта. Без токена (или с протухшим) сервер
// отвечает code=no_token/401 — тогда, не оставляя пользователя ни с чем,
// открываем заполненную форму, как раньше.
function sendReportIssue() {
  const overlay = document.getElementById('report-overlay');
  if (!overlay) return Promise.resolve(false);
  const btn = document.getElementById('rep-issue');
  const title = (document.getElementById('rep-title-inp') || {}).value || '';
  const labels = [...overlay.querySelectorAll('.rep-label')]
    .filter(cb => cb.checked).map(cb => cb.value);
  // Токен в окне не вводится: его роль принял сервер (.env, GITHUB_TOKEN),
  // а без него — тот же запасной путь, что и раньше, заполненная форма.
  const payload = {
    title: title,
    labels: labels,
    body: _reportBodyNow(),
  };
  const btnHtml = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = 'Отправляю…'; }
  return fetch('/report/issue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(r => r.json())
    .then(d => {
      if (btn) { btn.disabled = false; btn.innerHTML = btnHtml; }
      if (d && d.ok) {
        appendLog('ok', 'Issue #' + d.number + ' создан: ' + d.url);
        if (d.save_warning) appendLog('warn', 'Токен не сохранён: ' + d.save_warning);
        let opened = null;
        try { opened = window.open(d.url, '_blank'); } catch (e) { opened = null; }
        showToast(opened
          ? 'Issue #' + d.number + ' создан — вставьте скриншот, если он нужен'
          : 'Issue #' + d.number + ' создан — ссылка в журнале', 'ok');
        closeReportModal();
        return true;
      }
      const code = d && d.code;
      if (code === 'no_token' || (d && d.status === 401)) {
        showToast(((d && d.error) || 'Токена нет') + ' — открываю форму', 'warn');
        appendLog('warn', 'Issue через API не создан: ' + ((d && d.error) || 'нет токена'));
        openGitHubIssue();          // запасной путь — форма с тем же содержимым
        return false;
      }
      showToast('Не удалось создать issue: ' + ((d && d.error) || 'GitHub не ответил'), 'error');
      appendLog('error', 'GitHub API: ' + ((d && d.error) || 'нет ответа'));
      return false;
    })
    .catch(() => {
      if (btn) { btn.disabled = false; btn.innerHTML = btnHtml; }
      showToast('Сервер не ответил — попробуйте «Открыть форму на GitHub»', 'error');
      return false;
    });
}

// ══ Дропдаун меток ══════════════════════════
// Цвет пилюли — цвет метки на GitHub: в тёмной теме полупрозрачная подложка
// и светлый текст (как на самом GitHub в тёмной теме), в светлой — сплошная
// заливка с автоматически тёмным/светлым текстом по яркости цвета.
function _ghPillCss(color) {
  const c = String(color || '').replace('#', '');
  if (c.length !== 6) return '';
  const v = i => parseInt(c.slice(i, i + 2), 16);
  const r = v(0), g = v(1), b = v(2);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  const dark = document.documentElement.getAttribute('data-theme') === 'dark';
  const to2 = n => n.toString(16).padStart(2, '0');
  if (dark) {
    // Светлее к белому — на тёмном фоне иначе метка сливается с карточкой.
    const mix = n => to2(Math.round(n + (255 - n) * 0.4));
    return 'background:color-mix(in srgb, #' + c + ' 22%, transparent);color:#'
      + mix(r) + mix(g) + mix(b);
  }
  // Светлая тема GitHub: метка своим цветом, текст — контрастный.
  return 'background:#' + c + ';color:' + (lum > 0.55 ? '#24292f' : '#ffffff');
}

function _repToggleLabelMenu(show) {
  const menu = document.getElementById('rep-label-menu');
  const field = document.getElementById('rep-label-field');
  if (!menu || !field) return;
  menu.hidden = !show;
  field.setAttribute('aria-expanded', show ? 'true' : 'false');
}

// Выбранные метки в самом поле — цветные пилюли, чтобы список можно было
// закрыть и всё равно видеть выбор. Без выбора — призрачная подпись.
function _repRenderPills() {
  const box = document.getElementById('rep-label-pills');
  if (!box) return;
  const overlay = document.getElementById('report-overlay');
  const picked = [...overlay.querySelectorAll('.rep-label')]
    .filter(cb => cb.checked).map(cb => cb.value);
  if (!picked.length) {
    box.innerHTML = '<span class="rep-label-ph">Выберите метки…</span>';
    return;
  }
  const colors = {};
  REPORT_LABELS.forEach(l => { colors[l.id] = l.color; });
  box.innerHTML = picked.map(id =>
    '<span class="gh-pill" style="' + _ghPillCss(colors[id]) + '">' + escapeHtml(id) + '</span>'
  ).join('');
}

// ══ Отмена с подтверждением ══════════════════
// Снимок формы: если пользователь ничего не трогал — закрываем молча,
// если трогал (ввёл текст, поменял метки/контекст, вставил скриншот) —
// спрашиваем подтверждение, чтобы не потерять набранное случайным кликом.
function _reportSnapshot() {
  const overlay = document.getElementById('report-overlay');
  if (!overlay) return '';
  const marks = sel => [...overlay.querySelectorAll(sel)]
    .map(cb => (cb.checked ? '1' : '0')).join('');
  return JSON.stringify({
    title: (document.getElementById('rep-title-inp') || {}).value || '',
    desc: (document.getElementById('rep-desc') || {}).value || '',
    labels: marks('.rep-label'),
    ctx: marks('.rep-ctx'),
    shot: _reportShot ? '1' : '',
  });
}

function _reportDirty() {
  return _reportSnapshot() !== _reportInitial;
}

// Кнопка «Отменить», Escape и клик по фону — все через этот путь.
// Открытый дропдаун меток закрывается первым: Escape при открытом списке
// должен закрывать список, а не терять всю форму.
function cancelReportModal() {
  const menu = document.getElementById('rep-label-menu');
  if (menu && !menu.hidden) { _repToggleLabelMenu(false); return; }
  if (!_reportDirty()) { closeReportModal(); return; }
  uiConfirm('Закрыть окно? Набранное сообщение не будет отправлено.',
            'Отменить сообщение?', 'Закрыть без отправки', true)
    .then(ok => { if (ok) closeReportModal(); });
}

function closeReportModal() {
  const overlay = document.getElementById('report-overlay');
  if (overlay) overlay.remove();
  _reportShot = '';
  _reportShotInClipboard = false;
  _reportInitial = '';
  _ghDeviceReset();   // поллинг входа живёт не дольше окна
}

// ═══════════════════════════════════════════
//  Сброс настроек до стандартных
// ═══════════════════════════════════════════
// Сервер возвращает к стандартным папкам, браузеру и хранению, сохраняя
// пресеты, шаблоны писем, соглашение и ключи (routes/diagnostics.py).
// Настройки вкладки живут в localStorage — их чистит интерфейс.
const RESET_KEPT_NOTE = 'Пресеты, шаблоны писем, ключи API, история и сами файлы результатов НЕ трогаются.';

function openResetSettingsModal() {
  const existing = document.getElementById('reset-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'reset-overlay';
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-title">
      <h3 id="reset-title">${UI_ICONS.warn}Сбросить настройки до стандартных?</h3>
      <div class="diag-lead">Вернутся к стандартным: папки результатов (стандартная папка приложения),
        выбор браузера, срок хранения файлов, а также фильтры, столбцы и прочие настройки вкладок этого окна.</div>
      <div class="diag-note">${escapeHtml(RESET_KEPT_NOTE)}</div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel" onclick="closeResetSettingsModal()">Отмена</button>
        <button type="button" class="m-ok danger" id="reset-confirm" onclick="confirmResetSettings()">Сбросить</button>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeResetSettingsModal(); });
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') closeResetSettingsModal(); });
  document.body.appendChild(overlay);
  modalA11y(overlay);
}

function closeResetSettingsModal() {
  const overlay = document.getElementById('reset-overlay');
  if (overlay) overlay.remove();
}

function confirmResetSettings() {
  const btn = document.getElementById('reset-confirm');
  if (btn) { btn.disabled = true; btn.textContent = 'Сбрасываю…'; }
  return fetch('/settings/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
    .then(r => r.json())
    .then(d => {
      if (!d || !d.ok) {
        showToast('Сброс не выполнился: ' + ((d && d.error) || 'сервер не ответил'), 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Сбросить'; }
        return;
      }
      // Настройки вкладки — в мусор, кроме темы: тёмная тема — личное
      // предпочтение, сбрасывать его вместе с папками было бы неожиданно.
      const keep = ['yp_theme_v1'];
      const gone = [];
      try {
        for (let i = localStorage.length - 1; i >= 0; i--) {
          const k = localStorage.key(i);
          if (k && k.indexOf('yp_') === 0 && keep.indexOf(k) === -1) {
            localStorage.removeItem(k); gone.push(k);
          }
        }
      } catch (e) { /* приватный режим — нечего чистить */ }
      closeResetSettingsModal();
      showToast('Настройки сброшены (' + (d.reset || []).length + ' на сервере, '
              + gone.length + ' в браузере) — перезагружаю страницу', 'ok');
      setTimeout(() => location.reload(), 900);
    })
    .catch(() => {
      showToast('Сброс не выполнился — сервер недоступен', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Сбросить'; }
    });
}

// ═══════════════════════════════════════════
//  Экспорт настроек (перенос на другую машину)
// ═══════════════════════════════════════════
// Зеркало «Экспорт данных», но только настройки — и обязательно ДО сброса:
// сервер отдаёт settings.json, интерфейс добавляет свой снимок localStorage
// (фильтры, столбцы, тема), и обратно всё это возвращается той же кнопкой
// «Импорт данных» (/data/import принимает browser.json из архива).

// Снимок настроек вкладок. store — ради тестов: в браузере это localStorage.
function collectBrowserSettings(store) {
  const out = {};
  const s = store || (typeof localStorage !== 'undefined' ? localStorage : null);
  if (!s) return out;
  try {
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k && k.indexOf('yp_') === 0) {
        const v = s.getItem(k);
        if (typeof v === 'string') out[k] = v;
      }
    }
  } catch (e) { /* приватный режим — отдавать нечего */ }
  return out;
}

// Применение настроек вкладок из импортированного архива. Пишется только
// своё (yp_*) и только строками: содержимое архива — присланные данные.
function applyImportedBrowserSettings(raw, store) {
  if (!raw || typeof raw !== 'object') return 0;
  const s = store || (typeof localStorage !== 'undefined' ? localStorage : null);
  if (!s) return 0;
  let n = 0;
  try {
    Object.keys(raw).forEach(k => {
      const v = raw[k];
      if (k.indexOf('yp_') === 0 && typeof v === 'string') {
        s.setItem(k, v);
        n++;
      }
    });
  } catch (e) { /* приватный режим — нечего применять */ }
  return n;
}

function exportAppSettings() {
  const browser = collectBrowserSettings();
  return fetch('/settings/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ browser: browser }),
  })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
    .then(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'parser-settings-export.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      showToast('Настройки выгружены — на другой машине импортируйте архив кнопкой «Импорт данных»', 'ok');
      return true;
    })
    .catch(() => {
      showToast('Экспорт настроек не удался — сервер недоступен', 'error');
      return false;
    });
}
