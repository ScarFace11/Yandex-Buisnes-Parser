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
  dd.classList.toggle('open');
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
let themeAnimTimer = null;

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
  if (themeBtn) themeBtn.innerHTML = dark ? UI_ICONS.sun : UI_ICONS.moon;
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const next = !isDark;
  applyTheme(next, true);
  localStorage.setItem(THEME_KEY, next ? 'dark' : 'light');
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
  overlay.innerHTML = `<div class="logs-modal">
    <h3>${UI_ICONS.book}Логи запусков</h3>
    <div class="logs-empty">Загрузка…</div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  fetch('/logs/list')
    .then(r => r.json())
    .then(data => {
      const logs = data.logs || [];
      const modal = overlay.querySelector('.logs-modal');
      if (!logs.length) {
        modal.innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3><div class="logs-empty">Логов пока нет. Запустите поиск чтобы создать лог.</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
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
      modal.innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3>
        <ul class="logs-list">${listHtml}</ul>
        <div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
    })
    .catch(() => {
      overlay.querySelector('.logs-modal').innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3><div class="logs-empty">Ошибка загрузки</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
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
const DIAG_GROUP_TITLES = {
  keys:  UI_ICONS.key + 'Ключи API',
  files: UI_ICONS.folder + 'Файлы и папки',
  data:  UI_ICONS.box + 'Данные прошлых сборов',
  env:   UI_ICONS.info + 'Окружение',
};
const DIAG_STATUS = {
  ok:    { icon: UI_ICONS.check, label: 'в порядке' },
  warn:  { icon: UI_ICONS.warn,  label: 'предупреждение' },
  error: { icon: UI_ICONS.x,     label: 'ошибка' },
};
let _diagBusy = false;

function showDiagnostics() {
  const existing = document.getElementById('diag-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'diag-overlay';
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal diag-modal" role="dialog" aria-modal="true" aria-labelledby="diag-title">
      <h3 id="diag-title">${UI_ICONS.pulse}Диагностика</h3>
      <div class="diag-lead">Проверю браузер и токен ВК, права на папку результатов, окружение и данные
        прошлых сборов — это четыре причины, из-за которых чаще всего «ничего не работает». Читать логи не нужно.</div>
      <div class="diag-note">${UI_ICONS.key}«Только ключи» делает один живой запрос к ВКонтакте (проверка токена).
        «Проверить браузер» открывает настоящий Chrome и страницу выдачи: так видно, что браузер
        работает и что список организаций действительно загружается. Остальные проверки
        идут локально и выполняются мгновенно.</div>
      <div class="diag-actions">
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['keys','files','data','env'], this)">${UI_ICONS.checkSquare}Проверить всё</button>
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['keys'], this)">${UI_ICONS.key}Только ключи</button>
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['files','data','env'], this)">${UI_ICONS.folder}Без запросов к API</button>
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['engines'], this, true)">${UI_ICONS.pulse}Проверить браузер</button>
      </div>
      <div class="diag-summary" id="diag-summary" role="status" aria-live="polite">Нажмите «Проверить всё» — покажу, что работает, а что нет.</div>
      <div class="diag-results" id="diag-results"></div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel" onclick="closeDiagnostics()">Закрыть</button>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeDiagnostics(); });
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') closeDiagnostics(); });
  document.body.appendChild(overlay);
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
  const list = Array.isArray(groups) && groups.length ? groups : ['keys', 'files', 'data', 'env'];
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
        return;
      }
      renderDiagnostics(data.results || [], list);
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
  const plural = _pluralRu(results.length, 'проверка', 'проверки', 'проверок');
  let summary = `Проверок: ${results.length} (${plural}): `
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
          data.download_url || 'https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest');
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

function showUpdateBanner(newVer, changelog, url) {
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
        : `<a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer" title="Скачайте сборку для своей системы на странице релизов">Скачать v${newVer} ↗</a>`}
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
