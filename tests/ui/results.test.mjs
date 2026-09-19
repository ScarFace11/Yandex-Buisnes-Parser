// UI unit tests for the «Результаты» toolbox in static/js/app.js:
// city tabs, «только непросмотренные», bulk outreach panel, file browser.
//
// The functions under test are sliced verbatim from the production bundle and
// run against a minimal DOM stub (no browser needed).
//
// Run with: node --test tests/ui/results.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

// Slice a module-level `const NAME = …` (array/object literals or a plain
// value) from the production bundle, so tests never duplicate the tables.
// The slice is rewritten as a global assignment — the sliced functions read
// these names off globalThis.
function grabConst(name) {
  const prefix = 'const ' + name + ' = ';
  const i = src.indexOf(prefix);
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  let k = i + prefix.length;
  const open = src[k];
  let end;
  if (open === '[' || open === '{') {
    const close = open === '[' ? ']' : '}';
    let depth = 0;
    for (; k < src.length; k++) {
      if (src[k] === open) depth++;
      else if (src[k] === close) { depth--; if (!depth) break; }
    }
    end = k + 1;
  } else {
    end = src.indexOf(';', k);
  }
  return 'globalThis.' + name + ' = ' + src.slice(i + prefix.length, end) + ';';
}

// Slice a full function (balanced braces) from the production bundle.
// Keeps a leading `async` so async functions stay valid code.
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  const start = src.slice(Math.max(0, i - 6), i) === 'async ' ? i - 6 : i;
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(start, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
}

// ── Minimal DOM stub ──────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const el = {
    id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false,
    checked: false, title: '', dataset: {}, options: [], children: [], style: {},
    scrollWidth: 0, clientWidth: 0,
    set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    get className() { return [...classes].join(' '); },
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
    querySelectorAll: () => [],
    querySelector: () => null,
    setAttribute(k, v) { this.attrs = { ...(this.attrs || {}), [k]: v }; },
    getAttribute(k) { return (this.attrs || {})[k]; },
    appendChild() {}, remove() {}, addEventListener() {}, focus() {}, select() {},
    click() {},
  };
  return el;
}

const els = {};
for (const id of [
  'city-tabs', 'tbl-search', 'tbl-count', 'tbl-body', 'pager', 'pg-info', 'pg-prev', 'pg-next',
  'export-sel-wrap', 'f-collapse-chains', 'results-table',
  'bulk-panel', 'bulk-social', 'bulk-count', 'bulk-stats-note', 'unviewed-count', 'bulk-open-btn',
  'bulk-collapse', 'bulk-body', 'bulk-progress', 'bulk-progress-fill', 'bulk-progress-txt',
  'bulk-skip-viewed', 'bulk-mark-viewed', 'bulk-warn', 'bulk-copy-btn', 'bulk-persist-btn',
  'reviewed-save-status',
  'history-raw', 'history-processed', 'history-archive', 'files-count', 'files-search',
  'files-found',
  // Lead-score controls read by filterTable / rendered by renderPage
  'f-sort-score', 'f-min-score',
]) els[id] = mkEl(id);
els['f-sort-score'].checked = false;   // table order stays untouched by default in tests

// Social <select> with real options
['vk', 'telegram', 'whatsapp', 'instagram'].forEach(v => {
  const o = mkEl('');
  o.value = v;
  o.textContent = { vk: 'ВКонтакте', telegram: 'Telegram', whatsapp: 'WhatsApp', instagram: 'Instagram' }[v];
  els['bulk-social'].options.push(o);
});
els['bulk-social'].value = 'vk';
els['bulk-count'].value = 5;
els['bulk-skip-viewed'].checked = true;
els['bulk-mark-viewed'].checked = true;

// Preset buttons in the bulk panel
const presets = [5, 10, 20].map(n => { const b = mkEl('preset' + n); b.dataset.count = String(n); return b; });

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelector: () => null,
  querySelectorAll: sel => {
    if (sel === '#bulk-panel .bulk-preset') return presets;
    return [];
  },
  createElement: () => mkEl('created'),
  body: mkEl('body'),
};
globalThis.window = { location: { origin: 'http://127.0.0.1:5000' }, open: () => null, isSecureContext: true };

const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};

// Module-scope state the sliced functions rely on
globalThis.SOCIALS = { vk: '#4C75A3', instagram: '#C13584', telegram: '#2CA5E0', whatsapp: '#25D366' };
globalThis.SLABELS = { vk: 'VK', instagram: 'IG', telegram: 'TG', whatsapp: 'WA' };
globalThis.SNAMES = { vk: 'ВКонтакте', instagram: 'Instagram', telegram: 'Telegram', whatsapp: 'WhatsApp' };
globalThis.BULK_SOCIALS = ['vk', 'telegram', 'whatsapp', 'instagram'];
globalThis.BULK_MAX_TABS = 50;
globalThis.SUBTAB_KEY = 'yp_results_subtab';
globalThis.CITY_TAB_KEY = 'yp_results_city_tab';
globalThis.BULK_OPEN_KEY = 'yp_bulk_open';
globalThis.PAGE_SIZE = 50;
globalThis.ICONS = { xlsx: '📊', json: '📋', csv: '📄', html: '🗺' };
globalThis.reviewedState = {};
globalThis.allResults = [];
globalThis.filteredRows = [];
globalThis.curPage = 1;
globalThis.sortCol = -1;
globalThis.activeSocialFilters = new Set();
globalThis.requiredSocials = new Set();
globalThis.socialMode = 'all';
globalThis.unviewedOnly = false;
globalThis.activeCity = '';
globalThis._lastCities = [];
globalThis.currentFileNote = '';
globalThis.currentFile = '';
globalThis._resultsView = 'raw';
globalThis._resultsScope = 'current';   // «Текущий результат» = последний поиск
globalThis.bulkBusy = false;
globalThis.bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set() };
globalThis.filesData = { raw: [], processed: [], archive: [] };
globalThis.filesFilter = '';
globalThis.updateStatsBadge = () => {};

// fetch stub for the bulk runs (tests overwrite `bulkBatch` per case)
globalThis.bulkBatch = [];
let fetchCalls = [];
globalThis.fetch = async (url, opts) => {
  fetchCalls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  if (url === '/bulk/urls') {
    return { ok: true, json: async () => ({ urls: globalThis.bulkBatch, returned: globalThis.bulkBatch.length,
                                           total: globalThis.bulkBatch.length, remaining: 0 }) };
  }
  if (url === '/reviewed/batch') return { ok: true, json: async () => ({ ok: true, changed: 1 }) };
  return { ok: true, json: async () => ({}) };
};
const toasts = [];
globalThis.showToast = (msg, type) => toasts.push({ msg, type });

// Автосохранение отметок планирует таймер на 5 с — в тестах его ловим,
// а не ждём (иначе процесс висит лишние секунды). Список сбрасывает
// resetState().
const scheduled = [];
globalThis.setTimeout = (cb, ms) => { scheduled.push({ cb, ms }); return 0; };
globalThis.clearTimeout = () => {};

// Score tables and limits live at module scope — load them verbatim.
(0, eval)(['SCORE_MAX', 'SCORE_AGGREGATORS', 'SCORE_EXPENSIVE', 'SCORE_RULES',
  'REVIEWED_AUTOSAVE_MS'].map(grabConst).join('\n'));

const fns = [
  'pluralNum', 'pluralRecords', 'pluralProfiles', 'pluralFiles', 'fmtBytes', 'basenameOf',
  'clampInt', 'safeSocialUrl', 'cityOf', 'reviewKey', 'isReviewed', 'escapeHtml', 'safeUrl',
  'socialsHTML', 'renderPage', 'filterTable', 'refreshReviewedUI',
  'bulkScopeRows', 'bulkScopeStats', 'bulkOpenable', 'bulkWillOpen', 'renderCityTabs', 'setCityTab',
  'updateBulkStats', 'renderBulkProgress', 'resetBulkProgress', 'setBulkCount',
  'toggleUnviewedOnly', 'fileCardHTML', 'renderFiles', 'bulkParams',
  'showBulkWarn', 'hideBulkWarn', 'postJSON', 'openBlankTabs', 'fillTab', 'closeTab',
  'markReviewedBatch', 'bulkOpenBatch',
  // Автосохранение отметок «Просмотрено»
  'markReviewedDirty', 'updateReviewedSaveStatus', 'autoPersistReviewed', 'persistReviewedOnLeave',
  'setResultsSubTab', 'exportFiltered', 'persistReviewedMarks',
  // Lead score: filterTable mirrors the server-side threshold + ordering,
  // renderPage renders the «Оценка» cell, scoreHTML explains it per record.
  'minScoreThreshold', 'scoreHTML', 'scoreBreakdown', 'scoreWhyText', 'scoreNum',
  'scoreOwnWebsite', 'scoreRating',
];
(0, eval)(fns.map(grab).join('\n'));
// Module-level bulk-selection state closed over by fileCardHTML/renderFiles.
globalThis._selectedFiles = new Set();

// ── Fixtures ──────────────────────────────────────────────────
const REC = (name, city, extra = {}) => ({
  name, city, address: 'ул. Мира, 1', yandex_maps_url: 'https://ya.ru/' + name,
  ...extra,
});
const ROWS = [
  REC('А', 'Уфа', { vk: 'https://vk.com/a', telegram: 'https://t.me/a' }),
  REC('Б', 'Уфа', { vk: 'https://vk.com/b' }),
  REC('В', 'Москва', { vk: 'https://vk.com/v', whatsapp: 'https://wa.me/1' }),
  REC('Г', 'Москва'),
];

function resetState(rows = ROWS) {
  globalThis.allResults = rows.map(r => ({ ...r }));
  globalThis.filteredRows = [];
  globalThis.reviewedState = {};
  globalThis.activeCity = '';
  globalThis.unviewedOnly = false;
  globalThis.currentFileNote = '';
  globalThis.currentFile = '';
  globalThis.bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set() };
  globalThis.bulkBusy = false;
  scheduled.length = 0;
  globalThis.reviewedDirty = false;
  globalThis.reviewedSaveError = false;
  globalThis.reviewedSaveTimer = null;
  globalThis.reviewedPersistBusy = false;
  els['bulk-count'].value = 5;
  els['bulk-skip-viewed'].checked = true;
  els['bulk-social'].value = 'vk';
  els['city-tabs'].innerHTML = '';
  els['city-tabs'].hidden = false;
  els['tbl-search'].value = '';
}

// ── 1. Formatters ─────────────────────────────────────────────
test('plural helpers cover Russian plural forms', () => {
  const p = (n, f) => globalThis[f](n);
  assert.equal(p(1, 'pluralRecords'), 'запись');
  assert.equal(p(2, 'pluralRecords'), 'записи');
  assert.equal(p(5, 'pluralRecords'), 'записей');
  assert.equal(p(11, 'pluralRecords'), 'записей');
  assert.equal(p(21, 'pluralRecords'), 'запись');
  assert.equal(p(1, 'pluralProfiles'), 'профиль');
  assert.equal(p(3, 'pluralProfiles'), 'профиля');
  assert.equal(p(12, 'pluralProfiles'), 'профилей');
  assert.equal(p(1, 'pluralFiles'), 'файл');
  assert.equal(p(7, 'pluralFiles'), 'файлов');
});

test('fmtBytes switches units at the right thresholds', () => {
  assert.equal(globalThis.fmtBytes(0), '0 Б');
  assert.equal(globalThis.fmtBytes(900), '900 Б');
  assert.equal(globalThis.fmtBytes(2048), '2.0 КБ');
  assert.equal(globalThis.fmtBytes(45000), '44 КБ');
  assert.equal(globalThis.fmtBytes(2 * 1048576), '2.0 МБ');
});

test('clampInt keeps values inside the allowed range', () => {
  assert.equal(globalThis.clampInt('7', 1, 50), 7);
  assert.equal(globalThis.clampInt(0, 1, 50), 1);
  assert.equal(globalThis.clampInt(999, 1, 50), 50);
  assert.equal(globalThis.clampInt('abc', 5, 50), 5);
  assert.equal(globalThis.clampInt(-3, 5, 50), 5);
});

test('basenameOf takes the last path segment', () => {
  assert.equal(globalThis.basenameOf('processed/excel/кафе_уфа_filtered.xlsx'), 'кафе_уфа_filtered.xlsx');
  assert.equal(globalThis.basenameOf('raw.xlsx'), 'raw.xlsx');
});

// ── 2. Reviewed key / social URL safety ───────────────────────
test('safeSocialUrl accepts http(s) and rejects everything else', () => {
  assert.equal(globalThis.safeSocialUrl('https://vk.com/x'), 'https://vk.com/x');
  assert.equal(globalThis.safeSocialUrl(' http://vk.com/x '), 'http://vk.com/x');
  assert.equal(globalThis.safeSocialUrl('javascript:alert(1)'), '');
  assert.equal(globalThis.safeSocialUrl('tg://resolve?domain=x'), '');
  assert.equal(globalThis.safeSocialUrl(''), '');
});

test('reviewKey prefers the card URL, then falls back to name|city|address', () => {
  assert.equal(globalThis.reviewKey({ yandex_maps_url: 'y', twogis_url: 't' }), 'y');
  assert.equal(globalThis.reviewKey({ yandex_maps_url: '', twogis_url: 't' }), 't');
  assert.equal(globalThis.reviewKey({ name: 'Бар', city: 'Уфа', address: 'ул. Мира, 1' }),
    'n:Бар|Уфа|ул. Мира, 1');
  assert.equal(globalThis.reviewKey({}), '');
  assert.equal(globalThis.reviewKey(null), '');
});

test('isReviewed consults the marks store through reviewKey', () => {
  resetState();
  const row = ROWS[0];
  assert.equal(globalThis.isReviewed(row), false);
  globalThis.reviewedState[globalThis.reviewKey(row)] = true;
  assert.equal(globalThis.isReviewed(row), true);
});

// ── 3. City tabs ──────────────────────────────────────────────
test('cityOf falls back to «Без города»', () => {
  assert.equal(globalThis.cityOf({ city: 'Уфа' }), 'Уфа');
  assert.equal(globalThis.cityOf({ city: '  ' }), 'Без города');
  assert.equal(globalThis.cityOf({}), 'Без города');
});

test('bulkScopeRows narrows to the active city tab', () => {
  resetState();
  assert.equal(globalThis.bulkScopeRows().length, 4);
  globalThis.activeCity = 'Уфа';
  assert.equal(globalThis.bulkScopeRows().length, 2);
  globalThis.activeCity = 'Нет такого';
  assert.equal(globalThis.bulkScopeRows().length, 0);
});

test('renderCityTabs hides its row for a single city', () => {
  resetState();
  globalThis.renderCityTabs([{ city: 'Уфа', count: 4 }]);
  assert.equal(els['city-tabs'].hidden, true);
  assert.equal(els['city-tabs'].innerHTML, '');
  assert.equal(globalThis.activeCity, '');
});

test('renderCityTabs renders «Все» plus a tab per city with counts', () => {
  resetState();
  globalThis.renderCityTabs([
    { city: 'Москва', count: 2 },
    { city: 'Уфа', count: 2 },
  ]);
  const html = els['city-tabs'].innerHTML;
  assert.equal(els['city-tabs'].hidden, false);
  assert.match(html, /Все <span class="city-count">\(4\)<\/span>/);
  assert.match(html, /Москва <span class="city-count">\(2\)<\/span>/);
  assert.match(html, /Уфа <span class="city-count">\(2\)<\/span>/);
  // «Все» is active by default
  assert.match(html, /class="city-tab active" data-city="" onclick="setCityTab\(''\)">Все/);
});

test('renderCityTabs keeps a valid saved city active and drops an unknown one', () => {
  resetState();
  const cities = [{ city: 'Москва', count: 2 }, { city: 'Уфа', count: 2 }];
  globalThis.activeCity = 'Уфа';
  globalThis.renderCityTabs(cities);
  assert.equal(globalThis.activeCity, 'Уфа');
  assert.match(els['city-tabs'].innerHTML, /class="city-tab active" data-city="Уфа"/);

  globalThis.activeCity = 'Удалённый город';
  globalThis.renderCityTabs(cities);
  assert.equal(globalThis.activeCity, '', 'unknown city resets the tab to «Все»');
});

test('setCityTab persists the choice and re-filters the table', () => {
  resetState();
  globalThis.renderCityTabs([{ city: 'Уфа', count: 2 }, { city: 'Москва', count: 2 }]);
  globalThis.setCityTab('Москва');
  assert.equal(globalThis.activeCity, 'Москва');
  assert.equal(localStorage.getItem('yp_results_city_tab'), 'Москва');
  assert.equal(globalThis.curPage, 1);
  assert.equal(globalThis.filteredRows.length, 2, 'table shows only the selected city');
  globalThis.setCityTab('');
  assert.equal(globalThis.filteredRows.length, 4);
});

// ── 4. Bulk outreach counters ─────────────────────────────────
test('bulkScopeStats counts unviewed companies per social', () => {
  resetState();
  const s = globalThis.bulkScopeStats();
  assert.equal(s.unviewed, 4);
  assert.deepEqual(s.by_social, { vk: 3, telegram: 1, whatsapp: 1, instagram: 0 });
  assert.deepEqual(s.with_social, { vk: 3, telegram: 1, whatsapp: 1, instagram: 0 });
});

test('bulkScopeStats skips reviewed companies when skip_viewed is on', () => {
  resetState();
  globalThis.reviewedState[globalThis.reviewKey(ROWS[0])] = true;
  let s = globalThis.bulkScopeStats();
  assert.equal(s.unviewed, 3, 'reviewed rows are not counted as remaining');
  assert.deepEqual(s.by_social, { vk: 2, telegram: 0, whatsapp: 1, instagram: 0 });
  assert.deepEqual(s.with_social, { vk: 3, telegram: 1, whatsapp: 1, instagram: 0 });

  els['bulk-skip-viewed'].checked = false;
  s = globalThis.bulkScopeStats();
  assert.equal(s.unviewed, 3);
  assert.equal(s.by_social.vk, 3, 'with skip off the reviewed company is offered again');
});

test('updateBulkStats paints counters, option labels and the button', () => {
  resetState();
  globalThis.updateBulkStats();
  assert.equal(els['unviewed-count'].textContent, '4');
  assert.match(els['bulk-stats-note'].textContent, /ВКонтакте: 3/);
  assert.equal(els['bulk-social'].options[0].textContent, 'ВКонтакте — 3');
  assert.equal(els['bulk-social'].options[3].textContent, 'Instagram — 0');
  assert.equal(els['bulk-open-btn'].disabled, false);
  // 3 of the 4 sample companies have VK; 5 were requested
  assert.match(els['bulk-open-btn'].textContent, /Открыть 3 профиля/);
  assert.ok(presets[0]._classes.has('active'), 'preset 5 is highlighted');
});

test('updateBulkStats opens everything asked for in one click', () => {
  resetState();
  els['bulk-count'].value = '20';
  globalThis.updateBulkStats();
  // Запросили 20, но непросмотренных с VK всего 3 — обещаем ровно 3
  assert.match(els['bulk-open-btn'].textContent, /Открыть 3 профиля/);
  assert.ok(!presets[0]._classes.has('active'));
});

test('updateBulkStats disables the button only when everything is viewed', () => {
  resetState([REC('Без соцсетей', 'Уфа')]);
  globalThis.updateBulkStats();
  assert.equal(els['bulk-open-btn'].disabled, true);
  assert.match(els['bulk-open-btn'].textContent, /Все просмотрены/);
});

test('updateBulkStats keeps the button live between batches', () => {
  resetState();
  // 3 записи с VK: две в Уфе, одна в Москве
  globalThis.updateBulkStats();
  assert.equal(els['bulk-open-btn'].disabled, false);
  assert.match(els['bulk-open-btn'].textContent, /Открыть 3 профиля/);

  els['bulk-count'].value = '2';
  globalThis.updateBulkStats();
  assert.match(els['bulk-open-btn'].textContent, /Открыть 2 профиля/);

  // После батча осталось 1 — кнопка по-прежнему живая и считает честно
  globalThis.reviewedState[globalThis.reviewKey(ROWS[0])] = true;
  globalThis.reviewedState[globalThis.reviewKey(ROWS[1])] = true;
  globalThis.updateBulkStats();
  assert.equal(els['bulk-open-btn'].disabled, false, 'кнопка не выключается после первого батча');
  assert.match(els['bulk-open-btn'].textContent, /Открыть 1 профиль/);

  // Осталось 0 → единственный случай, когда кнопка гаснет
  globalThis.reviewedState[globalThis.reviewKey(ROWS[2])] = true;
  globalThis.updateBulkStats();
  assert.equal(els['bulk-open-btn'].disabled, true);
  assert.match(els['bulk-open-btn'].textContent, /Все просмотрены/);
});

test('bulkWillOpen never promises more than what is left', () => {
  resetState();
  assert.equal(globalThis.bulkWillOpen(5), 3, 'остаток меньше запрошенного');
  assert.equal(globalThis.bulkWillOpen(2), 2);
  assert.equal(globalThis.bulkWillOpen(500), 3, 'лимит 50 и остаток 3');
  globalThis.reviewedState[globalThis.reviewKey(ROWS[0])] = true;
  globalThis.reviewedState[globalThis.reviewKey(ROWS[1])] = true;
  globalThis.reviewedState[globalThis.reviewKey(ROWS[2])] = true;
  assert.equal(globalThis.bulkWillOpen(5), 0);
});

test('renderBulkProgress counts the session against what is left', () => {
  resetState();
  globalThis.renderBulkProgress();
  assert.equal(els['bulk-progress'].hidden, true, 'пока ничего не открывали — прячем');

  globalThis.bulkState = { social: 'vk', opened: 5, blocked: 1, keys: new Set(), copied: new Set() };
  globalThis.renderBulkProgress();
  assert.equal(els['bulk-progress'].hidden, false);
  // 5 открыто + 1 заблокировано + 3 непросмотренных VK = 9
  assert.equal(els['bulk-progress-fill'].style.width, '56%');
  assert.match(els['bulk-progress-txt'].textContent, /Открыто 5 из 9/);
  assert.match(els['bulk-progress-txt'].textContent, /заблокировано 1/);

  globalThis.resetBulkProgress();
  assert.equal(globalThis.bulkState.opened, 0);
  assert.equal(globalThis.bulkState.blocked, 0);
  assert.equal(els['bulk-progress'].hidden, true);
});

test('setBulkCount clamps the input and repaints the button', () => {
  resetState();
  globalThis.setBulkCount(99);
  assert.equal(els['bulk-count'].value, 50);
  globalThis.setBulkCount(10);
  assert.equal(els['bulk-count'].value, 10);
  assert.ok(presets[1]._classes.has('active'), 'preset 10 highlighted');
});

test('bulkParams sends the opened file so the crawl follows the file view', () => {
  resetState();
  globalThis.currentFile = 'raw/raw_a.xlsx';
  globalThis.activeCity = 'Уфа';
  els['bulk-count'].value = '20';
  const p = globalThis.bulkParams();
  assert.equal(p.file, 'raw/raw_a.xlsx');
  assert.equal(p.city, 'Уфа');
  assert.equal(p.social, 'vk');
  assert.equal(p.view, 'raw');
  assert.equal(p.scope, 'current', 'обход идёт по текущему поиску, а не по всей папке');
  assert.equal(p.skip_viewed, true);
  assert.equal(p.mark_viewed, true);
});

// ── 5. Table filters ──────────────────────────────────────────
test('filterTable applies the city tab filter', () => {
  resetState();
  globalThis.filterTable();
  assert.equal(globalThis.filteredRows.length, 4);
  assert.equal(els['tbl-count'].textContent, '4 записей');
  globalThis.activeCity = 'Уфа';
  globalThis.filterTable();
  assert.equal(globalThis.filteredRows.length, 2);
  assert.equal(els['tbl-count'].textContent, '2 записей');
});

test('toggleUnviewedOnly hides reviewed rows and toggles the button', () => {
  resetState();
  globalThis.reviewedState[globalThis.reviewKey(ROWS[0])] = true;
  globalThis.toggleUnviewedOnly();
  assert.equal(globalThis.unviewedOnly, true);
  assert.equal(globalThis.filteredRows.length, 3);

  globalThis.toggleUnviewedOnly();
  assert.equal(globalThis.unviewedOnly, false);
  assert.equal(globalThis.filteredRows.length, 4);
});

test('refreshReviewedUI re-applies the unviewed filter after a bulk run', () => {
  resetState();
  globalThis.toggleUnviewedOnly();            // 4 rows open
  globalThis.reviewedState[globalThis.reviewKey(ROWS[0])] = true;
  globalThis.reviewedState[globalThis.reviewKey(ROWS[1])] = true;
  globalThis.refreshReviewedUI();
  assert.equal(globalThis.filteredRows.length, 2, 'marked rows drop out at once');
  assert.equal(els['tbl-count'].textContent, '2 записей');
  assert.equal(els['unviewed-count'].textContent, '2', 'bulk counter follows the marks');
});

test('currentFileNote is appended to the table counter', () => {
  resetState();
  globalThis.currentFileNote = ' · файл: raw_a.xlsx';
  globalThis.filterTable();
  assert.equal(els['tbl-count'].textContent, '4 записей · файл: raw_a.xlsx');
});

// ── 6. Bulk opening (popup-blocker regression) ────────────────
// Fake browser tabs: each one records the URL it was pointed at and whether
// it was closed. `blocked` = popup blocker on; `blockedAfter` = it kicks in
// after the first N windows.
let lastTabs = [];

async function runBulk(batch, { blocked = false, blockedAfter = null, count = '5', onFetch = null } = {}) {
  resetState();
  toasts.length = 0;
  fetchCalls = [];
  globalThis.bulkBatch = batch;
  const realOpen = globalThis.window.open;
  const realFetch = globalThis.fetch;
  lastTabs = [];
  let made = 0;
  globalThis.window.open = () => {
    if (blocked || (blockedAfter != null && made >= blockedAfter)) { lastTabs.push(null); return null; }
    made++;
    const w = { location: { href: '' }, opener: 'self', closed: false, close() { this.closed = true; } };
    lastTabs.push(w);
    return w;
  };
  if (onFetch) globalThis.fetch = (url, opts) => { onFetch(url); return realFetch(url, opts); };
  els['bulk-count'].value = count;
  try {
    await globalThis.bulkOpenBatch();
  } finally {
    globalThis.window.open = realOpen;
    globalThis.fetch = realFetch;
  }
}

test('openBlankTabs opens every requested tab in one go', () => {
  const realOpen = globalThis.window.open;
  globalThis.window.open = () => ({ location: {} });
  try {
    assert.equal(globalThis.openBlankTabs(5).length, 5);
    assert.equal(globalThis.openBlankTabs(0).length, 0);
  } finally { globalThis.window.open = realOpen; }
});

test('openBlankTabs reports a blocked window as null', () => {
  const realOpen = globalThis.window.open;
  globalThis.window.open = () => null;
  try { assert.deepEqual(globalThis.openBlankTabs(3), [null, null, null]); }
  finally { globalThis.window.open = realOpen; }
});

test('fillTab points the tab at the profile and detaches the opener', () => {
  const w = { location: { href: '' }, opener: 'self' };
  assert.equal(globalThis.fillTab(w, 'https://vk.com/x'), true);
  assert.equal(w.location.href, 'https://vk.com/x');
  assert.equal(w.opener, null, 'вкладка не получает доступ к нашему окну');
  assert.equal(globalThis.fillTab(null, 'https://vk.com/x'), false, 'заблокированная вкладка');
  globalThis.closeTab(null);            // не должно бросать
});

test('bulkOpenBatch opens the tabs BEFORE the server answers', async () => {
  let tabsAtFetch = -1;
  await runBulk([
    { url: 'https://vk.com/a', key: 'k1', name: 'А' },
    { url: 'https://vk.com/b', key: 'k2', name: 'Б' },
    { url: 'https://vk.com/c', key: 'k3', name: 'В' },
  ], { count: '3', onFetch: url => { if (url === '/bulk/urls') tabsAtFetch = lastTabs.length; } });
  assert.equal(tabsAtFetch, 3, 'вкладки открыты до запроса — иначе браузер блокирует их');
  assert.deepEqual(lastTabs.map(w => w.location.href),
    ['https://vk.com/a', 'https://vk.com/b', 'https://vk.com/c']);
  assert.ok(!lastTabs.some(w => w.closed), 'все нужные вкладки остались открытыми');
});

test('bulkOpenBatch closes the tabs it did not need', async () => {
  await runBulk([{ url: 'https://vk.com/a', key: 'k1', name: 'А' }], { count: '3' });
  assert.equal(lastTabs.length, 3, 'три вкладки открыты загодя');
  assert.equal(lastTabs[0].closed, false);
  assert.equal(lastTabs[1].closed, true, 'лишние пустые вкладки закрываются');
  assert.equal(lastTabs[2].closed, true);
  assert.ok(toasts.some(t => /Открыто 1 профиль/.test(t.msg)));
});

test('bulkOpenBatch marks the profiles it opened as viewed', async () => {
  // keys must match real records so the counters can react
  const k = [globalThis.reviewKey(ROWS[0]), globalThis.reviewKey(ROWS[1])];
  await runBulk([
    { url: 'https://vk.com/a', key: k[0], name: 'А' },
    { url: 'https://vk.com/b', key: k[1], name: 'Б' },
  ]);
  assert.equal(globalThis.bulkState.opened, 2);
  assert.equal(globalThis.bulkState.blocked, 0, 'no false «blocked» results');
  assert.equal(globalThis.reviewedState[k[0]], true);
  assert.equal(globalThis.reviewedState[k[1]], true);
  assert.equal(els['unviewed-count'].textContent, '2', 'counter drops by the opened batch');
  assert.equal(els['bulk-warn'].hidden, true, 'no warning banner');
  const markCall = fetchCalls.find(c => c.url === '/reviewed/batch');
  assert.deepEqual(markCall.body, { keys: k, reviewed: true });
  assert.ok(toasts.some(t => /Открыто 2/.test(t.msg)), 'reports how many tabs were opened');
});

test('bulkOpenBatch tells the user how many of N tabs opened', async () => {
  await runBulk([
    { url: 'https://vk.com/a', key: 'k1', name: 'А' },
    { url: 'https://vk.com/b', key: 'k2', name: 'Б' },
    { url: 'https://vk.com/c', key: 'k3', name: 'В' },
  ], { count: '3', blockedAfter: 1 });
  assert.equal(globalThis.bulkState.opened, 1);
  assert.equal(globalThis.bulkState.blocked, 2);
  assert.equal(globalThis.reviewedState['k1'], true, 'открытое помечается просмотренным');
  assert.ok(!('k2' in globalThis.reviewedState), 'неоткрытое не помечается');
  assert.equal(els['bulk-warn'].hidden, false, 'the user is told popups were blocked');
  assert.match(els['bulk-warn'].innerHTML, /Открыто 1 из 3/);
  assert.match(els['bulk-warn'].innerHTML, /Скопировать ссылки/);
  assert.ok(toasts.some(t => /Открыто 1 из 3/.test(t.msg)));
  assert.equal(els['bulk-open-btn'].disabled, false, 'кнопка остаётся активной после батча');
});

test('bulkOpenBatch marks nothing when every tab was blocked', async () => {
  await runBulk([
    { url: 'https://vk.com/a', key: 'k1', name: 'А' },
    { url: 'https://vk.com/b', key: 'k2', name: 'Б' },
  ], { count: '2', blocked: true });
  assert.equal(globalThis.bulkState.opened, 0);
  assert.equal(globalThis.bulkState.blocked, 2);
  assert.deepEqual(globalThis.reviewedState, {}, 'nothing is marked as viewed');
  assert.equal(els['bulk-warn'].hidden, false);
  assert.match(els['bulk-warn'].innerHTML, /Открыто 0 из 2/);
  assert.ok(!fetchCalls.some(c => c.url === '/reviewed/batch'), 'no marks sent to the server');
});

test('bulkOpenBatch respects the «Помечать как просмотренные» switch', async () => {
  els['bulk-mark-viewed'].checked = false;
  await runBulk([{ url: 'https://vk.com/a', key: 'k1', name: 'А' }]);
  els['bulk-mark-viewed'].checked = true;
  assert.equal(globalThis.bulkState.opened, 1);
  assert.deepEqual(globalThis.reviewedState, {}, 'marks stay off when the checkbox is off');
  assert.ok(globalThis.bulkState.keys.has('k1'), 'but the profile is not offered again');
});

test('bulkOpenBatch reports an empty queue and leaves no blank tabs', async () => {
  await runBulk([], { count: '2' });
  assert.equal(globalThis.bulkState.opened, 0);
  assert.deepEqual(globalThis.reviewedState, {});
  assert.ok(lastTabs.length === 2 && lastTabs.every(w => w.closed),
    'предварительно открытые пустые вкладки закрываются');
  assert.ok(toasts.some(t => /Нет непросмотренных/.test(t.msg)));
});

// ── 7. File browser ───────────────────────────────────────────
test('fileCardHTML shows meta, four actions for RAW and no archive for ARCHIVE', () => {
  const raw = globalThis.fileCardHTML('raw', {
    name: 'raw_2026-09-15_22-19_кафе_уфа.xlsx', path: 'raw/raw_2026-09-15_22-19_кафе_уфа.xlsx',
    size: 18432, records: 42, modified: '15.09.2026 22:19', ext: 'xlsx',
  });
  assert.match(raw, /42 записи • 18 КБ • 15\.09\.2026 22:19/);
  assert.match(raw, /📊/);
  ['open', 'download', 'archive', 'delete'].forEach(a =>
    assert.match(raw, new RegExp('data-act="' + a + '"'), 'missing action ' + a));

  const arch = globalThis.fileCardHTML('archive', {
    name: 'old.xlsx', path: '_archive/2026-01-01/old.xlsx', size: 10, records: 1,
    modified: '01.01.2026 00:00', ext: 'xlsx',
  });
  assert.ok(!/data-act="archive"/.test(arch), 'archived files cannot be archived again');
  assert.match(arch, /data-act="restore"/, 'but they can be restored');
  assert.match(arch, /data-act="delete"/);
  assert.match(arch, /↩/);
});

test('archived cards keep open and download available', () => {
  const arch = globalThis.fileCardHTML('archive', {
    name: 'old.xlsx', path: '_archive/2026-01-01/old.xlsx', size: 10, records: 1,
    modified: '01.01.2026 00:00', ext: 'xlsx',
  });
  assert.match(arch, /data-act="open"/);
  assert.match(arch, /data-act="download"/);
});

test('fileCardHTML surfaces read errors instead of a record count', () => {
  const broken = globalThis.fileCardHTML('raw', {
    name: 'broken.xlsx', path: 'raw/broken.xlsx', size: 5, error: 'не удалось прочитать файл',
    modified: '01.01.2026 00:00', ext: 'xlsx',
  });
  assert.match(broken, /⚠ не удалось прочитать файл/);
  assert.ok(!/записей/.test(broken));
});

test('renderFiles filters by name and fills the counters line', () => {
  resetState();
  globalThis.filesData = {
    raw: [
      { name: 'raw_кафе_уфа.xlsx', path: 'raw/raw_кафе_уфа.xlsx', size: 10, records: 3, modified: 'x', ext: 'xlsx' },
      { name: 'raw_бар_уфа.xlsx', path: 'raw/raw_бар_уфа.xlsx', size: 10, records: 5, modified: 'x', ext: 'xlsx' },
    ],
    processed: [
      { name: 'кафе_уфа_filtered.json', path: 'processed/json/кафе_уфа_filtered.json', size: 10, records: 3, modified: 'x', ext: 'json' },
    ],
    archive: [],
  };  globalThis.filesFilter = '';
  globalThis.renderFiles();
  // Colored badges instead of one run-on line.
  assert.match(els['files-count'].innerHTML, /3 файла/);
  assert.match(els['files-count'].innerHTML, /files-badge raw">RAW 2</);
  assert.match(els['files-count'].innerHTML, /files-badge processed">PROCESSED 1</);
  assert.match(els['files-count'].innerHTML, /files-badge archive">ARCHIVE 0</);
  assert.equal(els['files-found'].textContent, '', 'no counter while the search is empty');
  assert.equal((els['history-raw'].innerHTML.match(/file-card/g) || []).length, 2);
  assert.match(els['history-processed'].innerHTML, /📋/, 'json files get their own icon');
  assert.match(els['history-archive'].innerHTML, /no-data/, 'empty section shows a placeholder');


  globalThis.filesFilter = 'бар';
  globalThis.renderFiles();
  assert.equal((els['history-raw'].innerHTML.match(/file-card/g) || []).length, 1);
  assert.match(els['history-raw'].innerHTML, /raw_бар_уфа\.xlsx/);
  assert.equal(els['files-found'].textContent, 'Найдено: 1 из 3', 'counter reflects the filtered set');

  globalThis.filesFilter = 'ничего-нет';
  globalThis.renderFiles();
  assert.match(els['history-raw'].innerHTML, /Ничего не найдено по фильтру/);
  assert.equal(els['files-found'].textContent, 'Найдено: 0 из 3');
});

test('renderFiles hints what to do for an empty RAW section', () => {
  resetState();
  globalThis.filesData = { raw: [], processed: [], archive: [] };
  globalThis.filesFilter = '';
  globalThis.renderFiles();
  assert.match(els['history-raw'].innerHTML, /Сырых файлов пока нет/);
  assert.equal(els['files-count'].innerHTML, '');
});

// ── 8. Reviewed marks: automatic saving ──────────────────────
test('markReviewedDirty schedules the autosave and shows the pending state', () => {
  resetState();
  globalThis.markReviewedDirty();
  assert.equal(globalThis.reviewedDirty, true);
  assert.equal(scheduled.length, 1, 'таймер автосохранения поставлен');
  assert.equal(scheduled[0].ms, 5000, 'дебаунс 5 секунд');
  assert.match(els['reviewed-save-status'].textContent, /Есть несохранённые отметки/);

  // Ещё клик — старый таймер сбрасывается, остаётся один
  scheduled.length = 0;
  globalThis.markReviewedDirty();
  assert.equal(scheduled.length, 1, 'повторный клик не плодит таймеры');
});

test('the scheduled autosave writes the marks into the current view', async () => {
  resetState();
  fetchCalls = [];
  globalThis._resultsView = 'processed';
  globalThis.markReviewedDirty();
  const cb = scheduled[0].cb;
  scheduled.length = 0;
  await cb();
  await new Promise(r => setImmediate(r));
  const call = fetchCalls.find(c => c.url === '/reviewed/persist');
  assert.ok(call, 'отметки уходят в /reviewed/persist без нажатия кнопки');
  assert.deepEqual(call.body, { view: 'processed', scope: 'current' });
  assert.equal(globalThis.reviewedDirty, false);
  assert.match(els['reviewed-save-status'].textContent, /Все отметки сохранены/);
});

test('autoPersistReviewed does nothing when there is nothing to save', async () => {
  resetState();
  fetchCalls = [];
  const d = await globalThis.autoPersistReviewed();
  assert.equal(d, null);
  assert.ok(!fetchCalls.some(c => c.url === '/reviewed/persist'));
  // force = кнопка «Сохранить сейчас» — сохраняет даже без изменений
  const forced = await globalThis.autoPersistReviewed(true);
  assert.ok(forced, 'ручное сохранение всегда идёт на сервер');
});

test('a failed autosave keeps the marks unsaved for a retry', async () => {
  resetState();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async url => { if (url === '/reviewed/persist') throw new Error('offline'); return realFetch(url); };
  try {
    const d = await globalThis.autoPersistReviewed(true);
    assert.equal(d, null);
  } finally { globalThis.fetch = realFetch; }
  assert.equal(globalThis.reviewedSaveError, true);
  assert.match(els['reviewed-save-status'].textContent, /Отметки не записаны/);
});

test('markReviewedBatch marks the batch dirty (autosave covers the bulk path)', async () => {
  resetState();
  scheduled.length = 0;
  await globalThis.markReviewedBatch(['k1', 'k2'], true);
  assert.equal(globalThis.reviewedDirty, true, 'батч тоже попадёт в xlsx');
  assert.equal(scheduled.length, 1);
});

test('closing the tab flushes the marks through sendBeacon', () => {
  resetState();
  const seen = [];
  // globalThis.navigator сам по себе только для чтения — подменяем метод.
  const realBeacon = globalThis.navigator.sendBeacon;
  globalThis.navigator.sendBeacon = (url, body) => { seen.push({ url, type: body.type }); return true; };
  try {
    globalThis.persistReviewedOnLeave();
    assert.equal(seen.length, 0, 'нечего сохранять — запрос не уходит');
    globalThis.reviewedDirty = true;
    globalThis.persistReviewedOnLeave();
    assert.equal(seen.length, 1);
    assert.equal(seen[0].url, '/reviewed/persist');
    assert.equal(seen[0].type, 'application/json');
    assert.equal(globalThis.reviewedDirty, false);
  } finally {
    if (realBeacon === undefined) delete globalThis.navigator.sendBeacon;
    else globalThis.navigator.sendBeacon = realBeacon;
  }
});

test('switching to «История файлов» saves the marks first', async () => {
  resetState();
  fetchCalls = [];
  globalThis.filesLoaded = true;          // панель файлов уже загружена — не ходим за ней
  globalThis.reviewedDirty = true;
  globalThis.setResultsSubTab('history');
  await new Promise(r => setImmediate(r));
  assert.ok(fetchCalls.some(c => c.url === '/reviewed/persist'),
    'переключение подвкладки дописывает отметки в файлы');
  assert.equal(globalThis.reviewedDirty, false);
});

test('exportFiltered saves the marks before building the file', async () => {
  resetState();
  fetchCalls = [];
  globalThis.filteredRows = [REC('А', 'Уфа')];
  globalThis.reviewedDirty = true;
  globalThis.URL = { createObjectURL: () => 'blob:1', revokeObjectURL: () => {} };
  await globalThis.exportFiltered('csv');
  const urls = fetchCalls.map(c => c.url);
  assert.ok(urls.indexOf('/reviewed/persist') >= 0, 'отметки сохраняются');
  assert.ok(urls.indexOf('/export-filtered') > urls.indexOf('/reviewed/persist'),
    'сначала отметки, потом сама выгрузка');
});

test('«Сохранить сейчас» reports what it wrote', async () => {
  resetState();
  toasts.length = 0;
  globalThis.reviewedDirty = true;
  await globalThis.persistReviewedMarks();
  assert.equal(els['bulk-persist-btn'].disabled, false, 'кнопка снова активна');
  assert.equal(els['bulk-persist-btn'].textContent, '💾 Сохранить сейчас');
  assert.ok(toasts.some(t => /Отметки записаны/.test(t.msg)));
});

// ── 9. Lead score breakdown (tooltip) ────────────────────────
test('scoreHTML lists only the criteria that fired', () => {
  const r = {
    name: 'Клиника', lead_score: 90, phone: '+7 900 000-00-00', website: '',
    rating: '4.7', reviews_count: '128', vk_activity: 'active', category: 'Стоматология',
  };
  const html = globalThis.scoreHTML(r);
  assert.match(html, /score-badge hot/);
  assert.match(html, /✅ Нет сайта \+30/);
  assert.match(html, /✅ Активный ВК \+20/);
  assert.match(html, /✅ Рейтинг 4\.7 \+15/);
  assert.match(html, /✅ Отзывов 128 \+15/);
  assert.match(html, /✅ Есть телефон \+5/);
  assert.match(html, /✅ Дорогая категория \+5/);
  assert.ok(!/❌/.test(html), 'ни одного промаха — только сработавшие критерии');
  assert.match(html, /Итого: 90 \(макс\. 90\)/);
});

test('scoreHTML marks the criteria that did not fire', () => {
  const why = globalThis.scoreWhyText({ lead_score: 0, website: 'https://kafe.ru', category: 'Кафе' }, 0);
  assert.match(why, /❌ Сайт есть/);
  assert.match(why, /❌ Телефон — не указан/);
  assert.match(why, /❌ Дорогая категория — нет/);
  assert.match(why, /❌ Рейтинг — нет данных/);
  assert.ok(!/✅/.test(why));
  assert.match(why, /Итого: 0 \(макс\. 90\)/);
});

test('scoreBreakdown sums exactly what the tooltip shows', () => {
  const { sum, lines } = globalThis.scoreBreakdown({ phone: '+7 1', category: 'Кафе', lead_score: 0 });
  assert.equal(sum, 35, 'нет сайта 30 + телефон 5');
  assert.equal(lines.filter(l => l.startsWith('✅')).length, 2);
});

test('score breakdown treats a taplink page as «нет сайта»', () => {
  const why = globalThis.scoreWhyText({ aggregator_url: 'https://taplink.cc/x', website: '', lead_score: 30 }, 30);
  assert.match(why, /✅ Нет сайта \+30/);
  assert.match(why, /Итого: 30 \(макс\. 90\)/);
});

test('score breakdown normalises a 0..50 rating', () => {
  const { sum } = globalThis.scoreBreakdown({ website: 'https://x.ru', rating: '47' });
  assert.equal(sum, 15, '47 → 4.7 → рейтинг засчитан');
});

test('score breakdown hides the losing VK variant', () => {
  const active = globalThis.scoreWhyText({ website: 'https://x.ru', vk_activity: 'active', lead_score: 20 }, 20);
  assert.match(active, /✅ Активный ВК \+20/);
  assert.ok(!/Полуактивный/.test(active), 'полуактивный не поминается, когда ВК активен');
  const semi = globalThis.scoreWhyText({ website: 'https://x.ru', vk_activity: 'semi', lead_score: 10 }, 10);
  assert.match(semi, /✅ Полуактивный ВК \+10/);
  assert.ok(!/ВК не активен/.test(semi), 'активный не поминается, когда ВК полуактивен');
  const none = globalThis.scoreWhyText({ website: 'https://x.ru', lead_score: 0 }, 0);
  assert.match(none, /❌ ВК не активен/);
  assert.match(none, /❌ Полуактивный ВК — нет/);
});

test('score tooltip admits when the stored score differs from the data', () => {
  const why = globalThis.scoreWhyText({ phone: '+7 1', category: 'Кафе', lead_score: 35 }, 35);
  assert.match(why, /Итого: 35/);
  const stale = globalThis.scoreWhyText({ website: 'https://x.ru', lead_score: 20 }, 20);
  assert.match(stale, /оценка сохранена при поиске/);
  assert.match(stale, /критерии дают 0/);
});

test('scoreHTML shows a dash when the score was never computed', () => {
  assert.equal(globalThis.scoreHTML({ lead_score: '' }), '<span class="score-na">—</span>');
  assert.equal(globalThis.scoreHTML({}), '<span class="score-na">—</span>');
});
