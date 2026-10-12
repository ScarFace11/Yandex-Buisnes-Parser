// ═══════════════════════════════════════════
let reviewedState = {};

// ── Отдельно «открытые» соцсети ──────────────────────────────────────────
// Клик по бейджу сети гасит именно этот бейдж, а не всю строку: у одной
// организации может быть несколько сетей, и каждая просматривается отдельно.
// Состояние живёт в localStorage (в таблицу идёт только визуальная метка).
const SOCIAL_VIEWED_KEY = 'yp_social_viewed_v1';
let socialViewedState = {};

function loadSocialViewed() {
  try {
    const saved = JSON.parse(localStorage.getItem(SOCIAL_VIEWED_KEY));
    socialViewedState = (saved && typeof saved === 'object') ? saved : {};
  } catch (e) { socialViewedState = {}; }
}

function socialViewedKey(row, platform) {
  const k = reviewKey(row);
  return k ? k + '|' + platform : '';
}

function isSocialViewed(row, platform) {
  const k = socialViewedKey(row, platform);
  return !!(k && socialViewedState[k]);
}

function markSocialViewed(row, platform) {
  const k = socialViewedKey(row, platform);
  if (!k || socialViewedState[k]) return false;
  socialViewedState[k] = true;
  try { localStorage.setItem(SOCIAL_VIEWED_KEY, JSON.stringify(socialViewedState)); } catch (e) {}
  return true;
}

function loadReviewed() {
  fetch('/reviewed').then(r => r.json()).then(data => {
    reviewedState = data || {};
    if (filteredRows.length) renderPage();
    updateBulkStats();          // «Осталось непросмотренных» зависит от отметок
  }).catch(() => {});
}

function toggleReviewed(url, cb) {
  if (!url) return;
  const checked = cb.checked;
  if (checked) reviewedState[url] = true; else delete reviewedState[url];
  const row = cb.closest('tr');
  if (row) row.classList.toggle('is-reviewed', checked);
  fetch('/reviewed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, reviewed: checked})
  }).catch(() => {});
  markReviewedDirty();
  updateBulkStats();
}

// ══════════════════════════════════════════════════════════════
//  Results tab: sub-tabs, city tabs, bulk outreach, file browser
// ══════════════════════════════════════════════════════════════
const SUBTAB_KEY    = 'yp_results_subtab';   // current | history
const CITY_TAB_KEY  = 'yp_results_city_tab';  // '' = все города
const BULK_OPEN_KEY = 'yp_bulk_open';         // 1 | 0 — панель развёрнута
const SCOPE_KEY     = 'yp_results_scope';     // current | all (текущий поиск | вся папка)
const BULK_MAX_TABS = 50;                     // предел вкладок за один клик

const BULK_SOCIALS = ['vk', 'telegram', 'whatsapp', 'instagram'];

let activeCity = '';            // выбранная вкладка города ('' = все)
let _lastCities = [];           // города текущего вида (от /results-view)
let unviewedOnly = false;       // фильтр «только непросмотренные»
let currentFileNote = '';       // «· файл: …» когда таблица показывает один файл
let currentFile = '';           // rel-путь файла, открытого из «Истории файлов»
let bulkBusy = false;
let bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
let filesLoaded = false;
let filesData = { raw: [], processed: [], archive: [] };
let filesFilter = '';
let filesSearchTimer = null;

// Mirrors the backend _review_key() — keep both in sync.
function reviewKey(r) {
  if (!r) return '';
  const y = String(r.yandex_maps_url || '').trim();
  if (y) return y;
  const name = String(r.name || '').trim();
  const addr = String(r.address || '').trim();
  if (!name && !addr) return '';
  return 'n:' + [name, String(r.city || '').trim(), addr].join('|');
}

function isReviewed(r) {
  const k = reviewKey(r);
  return !!(k && reviewedState[k]);
}

// Перерисовать таблицу и счётчики после изменения отметок
// (нужно и когда включён фильтр «только непросмотренные» —
//  помеченные строки должны из него исчезнуть).
// Пометить/снять «просмотрено» по ключу записи (тот же, что у чекбокса строки).
// Используется кликом по соцсети в таблице.
function toggleViewed(key, checked) {
  if (!key) return;
  if (checked) reviewedState[key] = true; else delete reviewedState[key];
  fetch('/reviewed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url: key, reviewed: checked})
  }).catch(() => {});
  markReviewedDirty();
}

function refreshReviewedUI() {
  updateBulkStats();
  if (unviewedOnly) { curPage = 1; filterTable(); }
  else if (filteredRows.length) renderPage();
}

function safeSocialUrl(u) {
  const s = String(u || '').trim();
  return /^https?:\/\//i.test(s) ? s : '';
}

// ── Массовое открытие вкладок ────────────────────────────────
// window.open ПОСЛЕ await теряет user-activation, поэтому браузер отдавал
// только первую вкладку из пяти. Схема, которая работает: пустые вкладки
// открываются СИНХРОННО прямо в обработчике клика, а URL-ы из ответа сервера
// подставляются в них уже потом.
function openBlankTabs(n) {
  const wins = [];
  for (let i = 0; i < n; i++) {
    let w = null;
    try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    wins.push(w || null);          // null = вкладку заблокировал браузер
  }
  return wins;
}

// Направить уже открытую вкладку на URL профиля. false = вкладка потеряна
// (заблокирована или закрыта), тогда показываем fallback «Скопировать ссылки».
function fillTab(win, url) {
  if (!win) return false;
  try {
    win.location.href = url;
    try { win.opener = null; } catch (e) { /* cross-origin после навигации */ }
    return true;
  } catch (e) {
    return false;
  }
}

function closeTab(win) {
  if (!win) return;
  try { win.close(); } catch (e) { /* уже закрыта */ }
}

function clampInt(v, lo, hi) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

function pluralNum(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

function pluralRecords(n) { return pluralNum(n, 'запись', 'записи', 'записей'); }
function pluralProfiles(n) { return pluralNum(n, 'профиль', 'профиля', 'профилей'); }
function pluralFiles(n) { return pluralNum(n, 'файл', 'файла', 'файлов'); }

function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' Б';
  if (n < 1024 * 1024) return (n / 1024).toFixed(n / 1024 < 10 ? 1 : 0) + ' КБ';
  return (n / 1048576).toFixed(1) + ' МБ';
}

function basenameOf(p) { return String(p || '').split('/').pop(); }

function postJSON(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(async r => {
    let data = {};
    try { data = await r.json(); } catch (e) { data = {}; }
    if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
    return data;
  });
}

// ── Sub-tabs: «Текущий результат» / «История файлов» ─────────
function setResultsSubTab(name) {
  const showCurrent = name !== 'history';
  document.querySelectorAll('#results-subtabs .subt-tab').forEach(b =>
    b.classList.toggle('active', (b.dataset.sub === 'history') === !showCurrent));
  const rc = document.getElementById('rs-current');
  const rh = document.getElementById('rs-history');
  if (rc) rc.hidden = !showCurrent;
  if (rh) rh.hidden = showCurrent;
  try { localStorage.setItem(SUBTAB_KEY, showCurrent ? 'current' : 'history'); } catch (e) {}
  if (!showCurrent) {
    // Уходим из таблицы — самый удобный момент дописать отметки в файлы.
    autoPersistReviewed();
    if (!filesLoaded) loadFilesPanel();
    else renderFiles();
  }
}

// ── City tabs ───────────────────────────────────────────────
function cityOf(r) { return String((r && r.city) || '').trim() || 'Без города'; }

function bulkScopeRows() {
  if (!activeCity) return allResults;
  return allResults.filter(r => cityOf(r) === activeCity);
}

function renderCityTabs(cities) {
  const box = document.getElementById('city-tabs');
  if (!box) return;
  const list = Array.isArray(cities) ? cities : [];
  if (list.length < 2) {            // один город — вкладки не нужны
    box.innerHTML = '';
    box.hidden = true;
    activeCity = '';
    return;
  }
  if (activeCity && !list.some(c => c.city === activeCity)) activeCity = '';
  box.hidden = false;
  const total = list.reduce((s, c) => s + (Number(c.count) || 0), 0);
  const tabs = [
    `<button class="city-tab${activeCity ? '' : ' active'}" data-city="" onclick="setCityTab('')">Все <span class="city-count">(${total})</span></button>`,
  ].concat(list.map(c =>
    `<button class="city-tab${c.city === activeCity ? ' active' : ''}" data-city="${escapeHtml(c.city)}" onclick="setCityTab(this.dataset.city)">${escapeHtml(c.city)} <span class="city-count">(${c.count})</span></button>`
  ));
  box.innerHTML = tabs.join('');
}

function setCityTab(city) {
  activeCity = String(city || '');
  try { localStorage.setItem(CITY_TAB_KEY, activeCity); } catch (e) {}
  document.querySelectorAll('#city-tabs .city-tab').forEach(b =>
    b.classList.toggle('active', (b.dataset.city || '') === activeCity));
  curPage = 1;
  filterTable();
  updateBulkStats();
}

// ── «Только непросмотренные» ─────────────────────────────────
function toggleUnviewedOnly() {
  unviewedOnly = !unviewedOnly;
  const b = document.getElementById('btn-unviewed');
  if (b) {
    b.classList.toggle('active', unviewedOnly);
    b.innerHTML = (unviewedOnly ? UI_ICONS.checkSquare : UI_ICONS.square) + 'Непросмотренные';
  }
  curPage = 1;
  filterTable();
}

// ── Bulk outreach panel ─────────────────────────────────────
function toggleBulkPanel() {
  const body = document.getElementById('bulk-body');
  const arrow = document.getElementById('bulk-collapse');
  if (!body) return;
  const open = body.hidden;
  body.hidden = !open;
  if (arrow) arrow.textContent = open ? '▾' : '▸';
  try { localStorage.setItem(BULK_OPEN_KEY, open ? '1' : '0'); } catch (e) {}
}

function setBulkCount(n) {
  const inp = document.getElementById('bulk-count');
  if (inp) inp.value = clampInt(n, 1, BULK_MAX_TABS);
  updateBulkStats();
}

// Сколько всего непросмотренных в текущем городе и сколько из них
// доступны по каждой соцсети (skip_viewed учитывается в by_social).
function bulkScopeStats() {
  const rows = bulkScopeRows();
  const skip = !!(document.getElementById('bulk-skip-viewed') || {}).checked;
  const stats = { unviewed: 0, with_social: {}, by_social: {} };
  BULK_SOCIALS.forEach(s => { stats.with_social[s] = 0; stats.by_social[s] = 0; });
  for (const r of rows) {
    const rev = isReviewed(r);
    if (!rev) stats.unviewed++;
    for (const s of BULK_SOCIALS) {
      if (!safeSocialUrl(r[s])) continue;
      stats.with_social[s]++;
      if (!(skip && rev)) stats.by_social[s]++;
    }
  }
  return stats;
}

// Сколько профилей выбранной соцсети ещё не просмотрено — ровно это число
// ограничивает следующий клик. Кнопка активна, пока оно больше нуля.
function bulkOpenable() {
  const sel = document.getElementById('bulk-social');
  const stats = bulkScopeStats();
  return stats.by_social[(sel && sel.value) || 'vk'] || 0;
}

// Сколько вкладок откроет клик: сколько запросили, но не больше остатка
// непросмотренных и жёсткого лимита BULK_MAX_TABS.
function bulkWillOpen(requested) {
  return Math.max(0, Math.min(clampInt(requested, 1, BULK_MAX_TABS), bulkOpenable()));
}

function updateBulkStats() {
  const panel = document.getElementById('bulk-panel');
  if (!panel) return;
  // Обходить нечего — соцсети выключены в «Что парсить» или в текущей
  // выборке нет ни одной ссылки на профиль. Панель видна только когда
  // в таблице реально есть соцсети (единый писатель panel.hidden).
  const socOn = (typeof socialsEnabled === 'function') ? socialsEnabled() : true;
  panel.hidden = !socOn || !bulkScopeRows().some(
    r => BULK_SOCIALS.some(s => safeSocialUrl(r[s])));
  const stats = bulkScopeStats();
  const sel = document.getElementById('bulk-social');
  const social = (sel && sel.value) || 'vk';

  const cnt = document.getElementById('unviewed-count');
  if (cnt) cnt.textContent = String(stats.unviewed);
  const note = document.getElementById('bulk-stats-note');
  if (note) note.textContent = ` · с ${SNAMES[social] || social}: ${stats.by_social[social] || 0}`;

  const order = document.getElementById('bulk-order-note');
  if (order) order.textContent = bulkOrderLabel();

  if (sel) {
    let firstAvailable = null;
    [...sel.options].forEach(o => {
      const base = o.dataset.base || o.textContent.replace(/\s*—\s*\d+\s*$/, '');
      o.dataset.base = base;
      const n = stats.by_social[o.value] || 0;
      o.textContent = `${base} — ${n}`;
      // Сеть без непросмотренных профилей не предложим — обходить нечего.
      o.disabled = n <= 0;
      if (n > 0 && firstAvailable === null) firstAvailable = o.value;
    });
    const cur = sel.selectedOptions && sel.selectedOptions[0];
    if (cur && cur.disabled && firstAvailable) {
      sel.value = firstAvailable;
    }
  }

  const inp = document.getElementById('bulk-count');
  const count = clampInt(inp ? inp.value : 5, 1, BULK_MAX_TABS);
  document.querySelectorAll('#bulk-panel .bulk-preset').forEach(b =>
    b.classList.toggle('active', Number(b.dataset.count) === count));

  // Выбор шаблона следует за выбранной соцсетью.
  syncTemplateSelects();

  const btn = document.getElementById('bulk-open-btn');
  if (btn) {
    const openable = stats.by_social[social] || 0;
    const willOpen = Math.min(count, openable, BULK_MAX_TABS);
    if (bulkBusy) {
      btn.disabled = true;
      btn.innerHTML = UI_ICONS.busy + 'Открываем…';
    } else if (!openable) {
      // Обход закончен: непросмотренных с этой соцсетью больше нет.
      btn.disabled = true;
      btn.innerHTML = UI_ICONS.check + 'Все просмотрены';
    } else {
      // Кнопка обещает ровно то, что откроется этим кликом.
      btn.disabled = false;
      btn.innerHTML = UI_ICONS.external + `Открыть ${willOpen} ${pluralProfiles(willOpen)}`;
    }
  }
  renderBulkProgress();
}

function renderBulkProgress() {
  const box = document.getElementById('bulk-progress');
  if (!box) return;
  if (!bulkState.opened && !bulkState.blocked) { box.hidden = true; return; }
  box.hidden = false;
  // Знаменатель — сколько всего оставалось непросмотренным с этой соцсетью
  // плюс уже открытое за сессию: процент не зависит от размера пачки.
  const total = bulkState.opened + bulkState.blocked + bulkOpenable();
  const pct = total ? Math.min(100, Math.round((bulkState.opened / total) * 100)) : 0;
  const fill = document.getElementById('bulk-progress-fill');
  if (fill) fill.style.width = pct + '%';
  const txt = document.getElementById('bulk-progress-txt');
  if (txt) {
    txt.textContent = `Открыто ${bulkState.opened} из ${total}`
      + (bulkState.blocked ? ` · заблокировано ${bulkState.blocked}` : '');
  }
}

function resetBulkProgress() {
  bulkState = { social: bulkState.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
  hideBulkWarn();
  updateBulkStats();
}

function showBulkWarn(msg) {
  const box = document.getElementById('bulk-warn');
  if (!box) return;
  box.hidden = false;
  box.innerHTML = msg;
}

function hideBulkWarn() {
  const box = document.getElementById('bulk-warn');
  if (box) { box.hidden = true; box.innerHTML = ''; }
}

// Порядок обхода = порядок строк в таблице. По умолчанию таблица отсортирована
// по оценке лида («Сначала горячие»), а клик по заголовку сортирует по своей
// колонке: раньше обход шёл в порядке файла и вкладки открывались вразброс
// относительно того, что видит пользователь.
function bulkSortSpec() {
  if (sortCol >= 2) return {col: sortCol, asc: !!sortAsc};
  const cb = document.getElementById('f-sort-score');
  return (cb && cb.checked) ? {col: 6, asc: false} : {col: null, asc: true};
}

function bulkOrderLabel() {
  const spec = bulkSortSpec();
  if (spec.col === 6) return 'Порядок: сначала горячие (по оценке)';
  if (spec.col) return 'Порядок: как в таблице (по колонке)';
  return 'Порядок: как в файле';
}

function bulkParams() {
  const sel = document.getElementById('bulk-social');
  const sort = bulkSortSpec();
  return {
    view: _resultsView,
    scope: _resultsScope,       // обход идёт по тому же срезу, что и таблица
    file: currentFile,          // обход идёт по открытому файлу, если он открыт
    city: activeCity,
    social: (sel && sel.value) || 'vk',
    skip_viewed: !!(document.getElementById('bulk-skip-viewed') || {}).checked,
    mark_viewed: !!(document.getElementById('bulk-mark-viewed') || {}).checked,
    sort_col: sort.col,
    sort_asc: sort.asc,
  };
}

async function bulkOpenBatch() {
  if (bulkBusy) return;
  const p = bulkParams();
  const inp = document.getElementById('bulk-count');
  const requested = clampInt(inp ? inp.value : 5, 1, BULK_MAX_TABS);

  // Другая соцсеть — начинаем сессию обхода заново.
  if (bulkState.social !== p.social) {
    bulkState = { social: p.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
    hideBulkWarn();
  }

  // Пустые вкладки открываются СИНХРОННО, до запроса к серверу: после await
  // браузер уже не считает их частью клика и блокирует всё, кроме первой.
  const wanted = Math.min(requested, BULK_MAX_TABS);
  const tabs = openBlankTabs(wanted);

  bulkBusy = true;
  updateBulkStats();
  try {
    // Шаблон для этой соцсети — сервер вернёт готовый текст на каждую запись.
    // В random-режиме шлём id набора: сервер сам выбирает per-record.
    // Набор случайного выбора пуст — fallback на ВСЕ шаблоны категории,
    // а не на один активный (иначе «случайный режим» копирует один текст).
    let randomIds = [];
    if (templateModes[p.social] === 'random') {
      randomIds = (randomTemplateIds[p.social] || []).slice();
      if (!randomIds.length) {
        randomIds = messageTemplates.filter(t => t.category === p.social).map(t => t.id);
      }
    }
    const randomMode = randomIds.length > 0;
    // Шаблон не выбран (или random) — текст не подставляем.
    const bulkTpl = randomMode ? null : getBulkTemplateFor(p.social);
    const data = await postJSON('/bulk/urls', {
      view: p.view, scope: p.scope, file: p.file, city: p.city, social: p.social,
      count: wanted, skip_viewed: p.skip_viewed, exclude_keys: [...bulkState.keys],
      // Порядок вкладок — как порядок строк в таблице.
      sort_col: p.sort_col, sort_asc: p.sort_asc,
      template: bulkTpl ? bulkTpl.text : '',
      // Составной шаблон (variant_ids): сервер раскрывает per-record по id —
      // без id клиентский текст был бы один и тот же для всех записей.
      template_id: bulkTpl ? bulkTpl.id : '',
      show_missing_as_var: showMissingAsVar,
      template_ids: randomIds,
      tpl_avoid_repeats: avoidRepeats,
    });
    const list = (data.urls || []).filter(i => i && i.url);
    if (!list.length) {
      // Очередь пуста — предварительно открытые вкладки закрываем, чтобы
      // у пользователя не остались пустые.
      tabs.forEach(closeTab);
      showToast('Нет непросмотренных компаний с этой соцсетью', 'warning');
      return;
    }

    // Заполняем уже открытые вкладки и закрываем лишние (сервер мог отдать
    // меньше, чем мы запросили, если очередь закончилась).
    const openedItems = [];
    let blocked = 0;
    for (let i = 0; i < tabs.length; i++) {
      const item = list[i];
      if (!item) { closeTab(tabs[i]); continue; }
      if (fillTab(tabs[i], item.url)) openedItems.push(item); else blocked++;
    }

    if (openedItems.length) {
      bulkState.opened += openedItems.length;
      openedItems.forEach(i => { if (i.key) bulkState.keys.add(i.key); });
      // Готовые тексты кладём в очередь: браузер не даёт копировать при
      // переключении внешней вкладки, поэтому копируем по кнопке.
      if (bulkTpl || randomMode) {
        if (!(bulkState.texts instanceof Map)) bulkState.texts = new Map();
        openedItems.forEach(i => {
          if (i.key) bulkState.texts.set(i.key, {name: i.name || '', text: i.text || '', url: i.url, tpl_name: i.tpl_name || ''});
        });
        renderBulkQueue();
      }
      if (p.mark_viewed) await markReviewedBatch(openedItems.map(i => i.key), true);
    }
    bulkState.blocked += blocked;
    if (blocked) {
      showBulkWarn(`⚠ Открыто ${openedItems.length} из ${list.length}: браузер заблокировал ${blocked} ${pluralProfiles(blocked)}. Разрешите всплывающие окна для этого сайта — или нажмите «📋 Скопировать ссылки» и откройте их вручную.`);
      showToast(`Открыто ${openedItems.length} из ${list.length}. Разрешите всплывающие окна`, 'warning');
    } else {
      hideBulkWarn();
      showToast(`Открыто ${openedItems.length} ${pluralProfiles(openedItems.length)}`, 'success');
    }
  } catch (e) {
    // Запрос упал — открытые пустые вкладки не должны висеть у пользователя.
    tabs.forEach(closeTab);
    showToast('Ошибка обхода: ' + e.message, 'error');
  } finally {
    bulkBusy = false;
    updateBulkStats();
    if (allResults.length) refreshReviewedUI();
  }
}

async function markReviewedBatch(keys, val) {
  const clean = [...new Set((keys || []).filter(Boolean))];
  if (!clean.length) return;
  const before = {};
  clean.forEach(k => {
    before[k] = !!reviewedState[k];
    // снятая отметка = ключа нет (не false), чтобы состояние совпадало с _reviewed.json
    if (val) reviewedState[k] = true; else delete reviewedState[k];
  });
  try {
    await postJSON('/reviewed/batch', { keys: clean, reviewed: val });
  } catch (e) {
    clean.forEach(k => { if (before[k]) reviewedState[k] = true; else delete reviewedState[k]; });
    showToast('Не удалось сохранить отметки: ' + e.message, 'error');
    refreshReviewedUI();
    return;
  }
  // Сервер отметки принял — теперь их надо дописать в xlsx.
  markReviewedDirty();
  refreshReviewedUI();
}

// ══════════════════════════════════════════════════════════════
//  Автосохранение отметок «Просмотрено»
// ══════════════════════════════════════════════════════════════
// Отметки сразу уходят в _reviewed.json (таблица и обход их видят), но в
// xlsx их надо переписать отдельным запросом. Раньше это делала только
// кнопка, о которой все забывали — и отметки не доживали до следующей
// сессии. Теперь пишем сами: через 5 с после последнего клика, при уходе со
// страницы, при переключении на «Историю файлов» и перед экспортом.
const REVIEWED_AUTOSAVE_MS = 5000;
let reviewedDirty = false;      // есть отметки, ещё не записанные в xlsx
let reviewedSaveError = false;  // последняя запись не удалась
let reviewedSaveTimer = null;
let reviewedPersistBusy = false;

function markReviewedDirty() {
  reviewedDirty = true;
  reviewedSaveError = false;
  updateReviewedSaveStatus();
  if (reviewedSaveTimer) clearTimeout(reviewedSaveTimer);
  reviewedSaveTimer = setTimeout(() => {
    reviewedSaveTimer = null;
    autoPersistReviewed();
  }, REVIEWED_AUTOSAVE_MS);
}

function updateReviewedSaveStatus() {
  const el = document.getElementById('reviewed-save-status');
  if (!el) return;
  let cls, txt;
  if (reviewedPersistBusy) {
    cls = 'busy'; txt = '⏳ Записываю отметки в файлы…';
  } else if (reviewedSaveError) {
    cls = 'err'; txt = '⚠ Отметки не записаны — нажмите «Сохранить сейчас»';
  } else if (reviewedDirty) {
    cls = 'dirty'; txt = '⏳ Есть несохранённые отметки — запишутся сами через пару секунд';
  } else {
    cls = 'ok'; txt = '✅ Все отметки сохранены';
  }
  el.textContent = txt;
  el.className = 'rev-save-status ' + cls;
}

// force = сохранить даже без изменений (ручная кнопка). Возвращает ответ
// сервера или null, если запись не удалась.
async function autoPersistReviewed(force) {
  if (!force && !reviewedDirty) return null;
  if (reviewedPersistBusy) return null;
  reviewedPersistBusy = true;
  reviewedSaveError = false;
  updateReviewedSaveStatus();
  try {
    const d = await postJSON('/reviewed/persist', { view: _resultsView, scope: _resultsScope });
    reviewedDirty = false;
    reviewedSaveError = false;
    return d;
  } catch (e) {
    reviewedSaveError = true;
    return null;
  } finally {
    reviewedPersistBusy = false;
    updateReviewedSaveStatus();
  }
}

// Закрытие вкладки: sendBeacon отдаёт запрос даже когда страница умирает.
function persistReviewedOnLeave() {
  if (!reviewedDirty) return;
  const nav = (typeof navigator !== 'undefined') ? navigator : null;
  if (!nav || typeof nav.sendBeacon !== 'function') return;
  try {
    const body = new Blob(
      [JSON.stringify({ view: _resultsView, scope: _resultsScope })],
      { type: 'application/json' },
    );
    nav.sendBeacon('/reviewed/persist', body);
    reviewedDirty = false;
  } catch (e) { /* отметки останутся в _reviewed.json — потеряем только колонку */ }
}

async function bulkCopyLinks() {
  const p = bulkParams();
  const inp = document.getElementById('bulk-count');
  const count = clampInt(inp ? inp.value : 10, 1, 50);
  try {
    const data = await postJSON('/bulk/urls', {
      view: p.view, scope: p.scope, file: p.file, city: p.city, social: p.social,
      count, skip_viewed: p.skip_viewed, exclude_keys: [...bulkState.keys, ...bulkState.copied],
    });
    const list = data.urls || [];
    if (!list.length) { showToast('Нет непросмотренных компаний с этой соцсетью', 'warning'); return; }
    list.forEach(i => { if (i.key) bulkState.copied.add(i.key); });
    showLinksModal(list, SNAMES[p.social] || p.social);
  } catch (e) {
    showToast('Ошибка: ' + e.message, 'error');
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { /* fall through to execCommand */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function showLinksModal(items, label) {
  const links = (items || []).map(i => i.url).filter(Boolean);
  const keys = (items || []).map(i => i.key).filter(Boolean);
  const overlay = document.createElement('div');
  overlay.className = 'ui-modal-overlay';
  const text = links.join('\n');
  overlay.innerHTML = `
    <div class="ui-modal links-modal">
      <h3>${links.length} ${pluralNum(links.length, 'ссылка', 'ссылки', 'ссылок')} — ${escapeHtml(label)}</h3>
      <p>Список можно вставить в заметки или открывать по одной. Когда свяжетесь с этими компаниями — поставьте им отметки кнопкой ниже, и они уйдут из очереди обхода.</p>
      <textarea readonly rows="10">${escapeHtml(text)}</textarea>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel">Закрыть</button>
        <button type="button" class="m-mark">${UI_ICONS.check}Пометить просмотренными (${keys.length})</button>
        <button type="button" class="m-ok neutral">${UI_ICONS.copy}Скопировать все</button>
      </div>
    </div>`;
  const done = () => overlay.remove();
  overlay.querySelector('.m-cancel').onclick = done;
  overlay.querySelector('.m-mark').onclick = async () => {
    if (!keys.length) { showToast('Нет записей для отметки', 'warning'); return; }
    await markReviewedBatch(keys, true);
    keys.forEach(k => bulkState.keys.add(k));
    showToast(`Отмечено просмотренными: ${keys.length}`, 'success');
    done();
  };
  overlay.querySelector('.m-ok').onclick = async () => {
    const ok = await copyText(text);
    showToast(ok ? 'Ссылки скопированы в буфер обмена' : 'Не удалось скопировать — выделите текст вручную', ok ? 'success' : 'warning');
  };
  overlay.addEventListener('click', e => { if (e.target === overlay) done(); });
  document.body.appendChild(overlay);
  const ta = overlay.querySelector('textarea');
  if (ta) { ta.focus(); ta.select(); }
}

// Ручная кнопка «Сохранить сейчас» — тот же путь, что и автосохранение,
// только сразу и с отчётом, сколько ячеек записали.
async function persistReviewedMarks() {
  const btn = document.getElementById('bulk-persist-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = UI_ICONS.busy + 'Записываю…'; }
  try {
    const d = await autoPersistReviewed(true);
    if (!d) { showToast('Не удалось записать отметки — попробуйте ещё раз', 'error'); return; }
    const extra = d.skipped ? ` · без колонки «Просмотрено»: ${d.skipped}` : '';
    const scope = { raw: 'сырые (RAW)', processed: 'обработанные', all: 'RAW + обработанные' }[_resultsView] || _resultsView;
    showToast(`Отметки записаны в ${scope}: ${d.updated} ячеек, ${d.files} ${pluralFiles(d.files)}${extra}`, 'success');
    if (d.errors && d.errors.length) {
      showToast(`Не удалось записать ${d.errors.length} ${pluralFiles(d.errors.length)}: ${d.errors[0].file}`, 'error');
    }
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.save + 'Сохранить сейчас'; }
  }
}

// ── File browser («История файлов») ─────────────────────────
function onFilesSearchInput() {
  clearTimeout(filesSearchTimer);
  filesSearchTimer = setTimeout(() => {
    const el = document.getElementById('files-search');
    filesFilter = (el ? el.value : '').trim().toLowerCase();
    renderFiles();
  }, 300);
}

async function loadFilesPanel(force) {
  if (filesLoaded && !force) { renderFiles(); return; }
  const box = document.getElementById('history-raw');
  if (box && !filesLoaded) box.innerHTML = '<div class="no-data">Загрузка…</div>';
  try {
    const d = await fetch('/files/list').then(r => r.json());
    filesData = { raw: d.raw || [], processed: d.processed || [], archive: d.archive || [] };
    filesLoaded = true;
    // Drop selections for files that no longer exist anywhere.
    const alive = new Set([...filesData.raw, ...filesData.processed, ...filesData.archive].map(it => it.path));
    _selectedFiles = new Set([..._selectedFiles].filter(p => alive.has(p)));
    updateBulkDeleteBtn();
    renderFiles();
  } catch (e) {
    ['raw', 'processed', 'archive'].forEach(s => {
      const el = document.getElementById('history-' + s);
      if (el) el.innerHTML = '<div class="no-data">Не удалось загрузить список файлов. Нажмите «Обновить».</div>';
    });
    showToast('Ошибка загрузки списка файлов', 'error');
  }
}

// Показать ошибку «файла нет», не превратив таблицу в автомата, и обновить список файлов.
function showFileNotFound(view) {
  const body = document.getElementById('tbl-body');
  if (body) body.innerHTML = '<tr><td colspan="9" class="no-data">Файл не найден в этой папке. Проверьте Историю файлов (Обновить) и откройте его снова.</td></tr>';
  showToast('Файл не найден в этой папке. Проверьте Историю файлов (Обновить) и откройте его снова.', 'warn');
  loadFilesPanel(true);
}

// File-card actions. Inline SVGs with stroke="currentColor" instead of
// emoji: the emoji 🗑 renders as a monochrome glyph that ignores `color`,
// so it vanished on the dark card. SVG inherits the themed colour.
const FILE_ACT_ICONS = {
  open:     '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-6"/><path d="M20 20V8"/></svg>',
  download: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v11"/><path d="M7.5 10 12 14.5 16.5 10"/><path d="M4 20h16"/></svg>',
  archive:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h18l-1.6-3.2H4.6L3 7z"/><path d="M5 7v13h14V7"/><path d="M10 12h4"/></svg>',
  restore:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6 5 10l4 4"/><path d="M5 10h9a4.5 4.5 0 0 1 0 9h-3"/></svg>',
  delete:   '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16"/><path d="M9.5 7V4h5v3"/><path d="M6.5 7 7.5 20h9l1-13"/><path d="M10.5 11v5.5"/><path d="M13.5 11v5.5"/></svg>',
};

function fileCardHTML(section, it) {
  // Значок перед текстом — SVG, поэтому сообщение экранируем построчно, а не
  // оборачиваем целиком (escapeHtml съел бы саму разметку значка).
  const meta = it.error
    ? UI_ICONS.warn + escapeHtml(it.error)
    : escapeHtml(`${it.records} ${pluralRecords(it.records)} • ${fmtBytes(it.size)} • ${it.modified}`);
  const icon = FILE_TYPE_ICONS[it.ext] || FILE_TYPE_ICONS.dir;
  // Архивные файлы не архивируем повторно, но даём вернуть на место.
  const archiveBtn = section === 'archive'
    ? `<button class="file-btn" data-act="restore" data-path="${escapeHtml(it.path)}" title="Вернуть файл в рабочую папку">${FILE_ACT_ICONS.restore}</button>`
    : `<button class="file-btn" data-act="archive" data-path="${escapeHtml(it.path)}" title="Убрать в архив (файл можно вернуть)">${FILE_ACT_ICONS.archive}</button>`;
  return `
    <div class="file-card">
      <div class="file-info">
        <input type="checkbox" class="file-cb" data-path="${escapeHtml(it.path)}"
          ${_selectedFiles.has(it.path) ? 'checked' : ''}
          onchange="onFileSelect(this)" title="Выбрать для массового удаления">
        <span class="file-icon">${icon}</span>
        <div class="file-text">
          <div class="file-name" title="${escapeHtml(it.path)}">${escapeHtml(it.name)}</div>
          <div class="file-meta">${meta}</div>
        </div>
      </div>
      <div class="file-actions">
        <button class="file-btn" data-act="open" data-path="${escapeHtml(it.path)}" title="Открыть в таблице">${FILE_ACT_ICONS.open}</button>
        <button class="file-btn" data-act="download" data-path="${escapeHtml(it.path)}" title="Скачать">${FILE_ACT_ICONS.download}</button>
        ${archiveBtn}
        <button class="file-btn danger" data-act="delete" data-path="${escapeHtml(it.path)}" title="Удалить навсегда">${FILE_ACT_ICONS.delete}</button>
      </div>
    </div>`;
}

// ── Bulk selection («Удалить выбранные» / «В архив» / «Отменить выбор») ──
let _selectedFiles = new Set();

function onFileSelect(cb) {
  if (cb.checked) _selectedFiles.add(cb.dataset.path);
  else _selectedFiles.delete(cb.dataset.path);
  updateBulkDeleteBtn();
}

// Three buttons follow one counter: the destructive delete, the reversible
// archive and «снять выделение». They appear together with 1+ ticked file.
function updateBulkDeleteBtn() {
  const n = _selectedFiles.size;
  const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  set('files-bulk-n', n);
  set('files-bulk-arch-n', n);
  ['btn-files-bulk-delete', 'btn-files-bulk-archive', 'btn-files-bulk-cancel'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.hidden = n === 0;
  });
}

// ✕ Отменить выбор — untick everything at once (one click instead of N).
function clearFileSelection() {
  _selectedFiles.clear();
  const boxes = document.querySelectorAll ? document.querySelectorAll('.file-cb') : [];
  for (let i = 0; i < boxes.length; i++) boxes[i].checked = false;
  updateBulkDeleteBtn();
  showToast('Выбор снят', 'info');
}

// 📦 В архив (N) — same batch endpoint as delete, action="archive"; the file
// moves to <результаты>/_archive/ГГГГ-ММ-ДД/ and can be restored (↩).
async function bulkArchiveSelected() {
  const paths = [..._selectedFiles];
  if (!paths.length) return;
  try {
    const d = await postJSON('/files/action', { paths, action: 'archive' });
    const moved = (d.moved || []).length;
    const errs = (d.errors || []).length;
    showToast(`В архив: ${moved}${errs ? ` · ошибок: ${errs}` : ''}`, errs ? 'warn' : 'success');
    if (errs) showToast(`Не удалось архивировать: ${(d.errors[0] || {}).error || 'ошибка'}`, 'error');
    // Archived files leave RAW/PROCESSED → the tick set has to be dropped.
    _selectedFiles.clear();
    updateBulkDeleteBtn();
    loadFilesPanel(true);
    setResultsView(_resultsView);
  } catch (e) {
    showToast('Ошибка архивации: ' + e.message, 'error');
  }
}

async function bulkDeleteSelected() {
  const paths = [..._selectedFiles];
  if (!paths.length) return;
  const ok = await uiConfirm(
    `Будет безвозвратно удалено файлов: ${paths.length}. Отменить это нельзя.`,
    'Удалить выбранные файлы?',
    `Удалить (${paths.length})`
  );
  if (!ok) return;
  try {
    const d = await postJSON('/files/action', { paths, action: 'delete', confirm: true });
    const errs = (d.errors || []).length;
    showToast(`Удалено: ${(d.deleted || []).length}${errs ? ` · ошибок: ${errs}` : ''}`, errs ? 'warn' : 'success');
    _selectedFiles.clear();
    updateBulkDeleteBtn();
    loadFilesPanel(true);
    setResultsView(_resultsView);   // открытый файл мог удалиться
  } catch (e) {
    showToast('Ошибка массового удаления: ' + e.message, 'error');
  }
}

// ── Сворачиваемые разделы «Истории файлов» ──────────────────
// Состояние разделов (raw/processed/archive) переживает перезагрузку.
const HISTORY_SECTIONS_KEY = 'yp_files_sections_v1';
let _historyCollapsed = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_SECTIONS_KEY));
    return saved && typeof saved === 'object' ? saved : {};
  } catch { return {}; }
})();

function toggleHistorySection(e, section) {
  // Клик по кнопке внутри заголовка (например, «Применить фильтры заново»)
  // раздел не сворачивает.
  if (e && e.target && e.target.closest && e.target.closest('button')) return;
  _historyCollapsed[section] = !_historyCollapsed[section];
  try { localStorage.setItem(HISTORY_SECTIONS_KEY, JSON.stringify(_historyCollapsed)); } catch {}
  applyHistorySections();
}

function applyHistorySections() {
  for (const section of ['raw', 'processed', 'archive']) {
    const sec = document.querySelector('.history-section[data-section="' + section + '"]');
    if (!sec) continue;
    const collapsed = !!_historyCollapsed[section];
    sec.classList.toggle('is-collapsed', collapsed);
    const head = sec.querySelector('.history-collapse');
    if (head) head.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }
}

function renderFiles() {
  const nRaw = (filesData.raw || []).length;
  const nProc = (filesData.processed || []).length;
  const nArch = (filesData.archive || []).length;
  const total = nRaw + nProc + nArch;
  const cnt = document.getElementById('files-count');
  if (cnt) {
    // Colored badges instead of one run-on line: the three sections are
    // actually distinguishable at a glance.
    cnt.innerHTML = total
      ? `<span>${total} ${pluralFiles(total)}</span>
         <span class="files-badge raw">RAW ${nRaw}</span>
         <span class="files-badge processed">PROCESSED ${nProc}</span>
         <span class="files-badge archive">ARCHIVE ${nArch}</span>`
      : '';
  }
  let shown = 0;
  for (const section of ['raw', 'processed', 'archive']) {
    const box = document.getElementById('history-' + section);
    if (!box) continue;
    const all = filesData[section] || [];
    const items = filesFilter ? all.filter(it => it.name.toLowerCase().includes(filesFilter)) : all;
    shown += items.length;
    if (!items.length) {
      const hint = filesFilter
        ? 'Ничего не найдено по фильтру'
        : (section === 'raw'
            ? 'Сырых файлов пока нет — запустите сбор данных'
            : 'Пусто — файлы появятся после обработки');
      box.innerHTML = `<div class="no-data">${hint}</div>`;
      continue;
    }
    box.innerHTML = items.map(it => fileCardHTML(section, it)).join('');
  }
  // «Найдено: X из Y» only while a filter is active — otherwise it is noise.
  const found = document.getElementById('files-found');
  if (found) found.textContent = filesFilter ? `Найдено: ${shown} из ${total}` : '';
}

function openFileInTable(rel) {
  if (!rel) return;
  setResultsSubTab('current');
  const body = document.getElementById('tbl-body');
  if (body) body.innerHTML = '<tr><td colspan="9" class="no-data">Загрузка…</td></tr>';
  const seq = ++_resultsReqSeq;      // перебивает незавершённую загрузку общего вида
  fetch('/results-view?view=' + encodeURIComponent(_resultsView) + '&file=' + encodeURIComponent(rel))
    .then(r => r.json())
    .then(d => {
      if (seq !== _resultsReqSeq) return;
      if (d.error) {
        // Файл удалён/перемещён в другой каталог или не попал в выбранный view.
        // Перезагружаем список, чтобы пользователь видел актуальное состояние.
        showFileNotFound(_resultsView);
        return;
      }
      const recs = d.records || [];
      if (!recs.length) {
        // Сервер вернул пустой список — нет данных этого поиска, либо запрос не тот.
        body.innerHTML = '<tr><td colspan="9" class="no-data">Нет данных. Запустите сбор данных, затем откройте файл в Истории файлов.</td></tr>';
        showToast('Нет данных. Запустите сбор данных, затем откройте файл в Истории файлов.', 'info');
        return;
      }
      activeCity = '';
      _lastCities = [];          // вкладки городов для одного файла не нужны
      currentFile = rel;
      loadReviewed();
      // renderTable() перечитывает данные через filterTable → источник
      // должен быть обновлён до вызова.
      allResults = recs;
      renderTable(recs);
      currentFileNote = ` · файл: ${basenameOf(rel)}`;
      renderPage();              // перерисовать счётчик с именем файла
      showToast(`${recs.length} ${pluralRecords(recs.length)} · ${basenameOf(rel)}`, 'success');
    })
    .catch(() => {
      currentFileNote = '';
      currentFile = '';
      if (body) body.innerHTML = '<tr><td colspan="9" class="no-data">Не удалось загрузить данные файла.</td></tr>';
      showToast('Не удалось загрузить данные файла. Проверьте соединение и попробуйте снова.', 'error');
    });
}

function downloadResultsFile(rel) {
  if (!rel) return;
  const url = '/download/' + String(rel).split('/').map(encodeURIComponent).join('/');
  window.location.href = url;
}

function basenameOf(rel) {
  return rel.split('/').pop() || rel;
}

async function archiveResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» переедет в output/_archive/ (папка сегодняшнего дня). Оттуда его можно вернуть.`,
    'Убрать файл в архив?', 'В архив');
  if (ok) await fileAction(rel, 'archive');
}

async function restoreResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» вернётся туда, откуда был убран (RAW или output/processed/excel/).`,
    'Вернуть файл из архива?', 'Вернуть');
  if (ok) await fileAction(rel, 'restore');
}

async function deleteResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» будет удалён без возможности восстановления.`,
    'Удалить файл навсегда?', 'Удалить навсегда');
  if (ok) await fileAction(rel, 'delete');
}

async function fileAction(rel, action) {
  try {
    const d = await postJSON('/files/action', {
      path: rel, action, confirm: action === 'delete',
    });
    const done = {
      archive: `Файл в архиве: ${d.moved_to}`,
      restore: `Файл возвращён: ${d.restored_to}`,
      delete: 'Файл удалён',
    }[action] || 'Готово';
    showToast(done, 'success');
    loadFilesPanel(true);
    // Если в таблице был открыт именно этот файл — сбрасываем на общий вид
    if (currentFile === rel) setResultsView(_resultsView);
  } catch (e) {
    showToast('Ошибка: ' + e.message, 'error');
  }
}

// ── Init of the results panel ───────────────────────────────
function initResultsPanel() {
  let sub = 'current';
  try { if (localStorage.getItem(SUBTAB_KEY) === 'history') sub = 'history'; } catch (e) {}
  try { activeCity = localStorage.getItem(CITY_TAB_KEY) || ''; } catch (e) { activeCity = ''; }
  try { if (localStorage.getItem(SCOPE_KEY) === 'all') _resultsScope = 'all'; } catch (e) {}
  updateScopeButton();
  try {
    if (localStorage.getItem(BULK_OPEN_KEY) === '0') {
      const body = document.getElementById('bulk-body');
      const arrow = document.getElementById('bulk-collapse');
      if (body) body.hidden = true;
      if (arrow) arrow.textContent = '▸';
    }
  } catch (e) {}

  const sel = document.getElementById('bulk-social');
  // Базовое имя опции фиксируем один раз и без счётчика: первый проход
  // updateStats уже дописал « — N», и захват текущего текста закреплял бы
  // счётчик в базе («ВКонтакте — 0 — 37» после второго прохода).
  if (sel) [...sel.options].forEach(o => {
    if (!o.dataset.base) o.dataset.base = o.textContent.replace(/\s*—\s*\d+\s*$/, '');
  });

  // File actions via delegation — paths are never interpolated into JS code.
  const hist = document.getElementById('rs-history');
  if (hist) hist.addEventListener('click', e => {
    const btn = e.target.closest('.file-btn');
    if (!btn) return;
    const rel = btn.dataset.path || '';
    const act = btn.dataset.act;
    if (!rel) return;
    if (act === 'open') openFileInTable(rel);
    else if (act === 'download') downloadResultsFile(rel);
    else if (act === 'archive') archiveResultsFile(rel);
    else if (act === 'restore') restoreResultsFile(rel);
    else if (act === 'delete') deleteResultsFile(rel);
  });

  setResultsSubTab(sub);
  updateBulkStats();
}

// ═══════════════════════════════════════════
//  Export filtered rows
