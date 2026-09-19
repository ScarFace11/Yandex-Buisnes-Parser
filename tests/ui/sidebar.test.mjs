// UI unit tests for the sidebar logic in static/js/app.js (run offline in Node).
//
// The functions under test are sliced verbatim from the production file and
// executed against a minimal DOM stub — no browser required.
//
// Run with: node --test tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

// Slice a full function (balanced braces) from the production bundle.
function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
}

// ── Minimal DOM stub ──────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const el = {
    id, value: '', textContent: '', innerHTML: '', placeholder: '',
    hidden: true, disabled: false, title: '',
    style: { setProperty: () => {} },
    // className assignment replaces the whole class set (as in the DOM)
    set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    get className() { return [...classes].join(' '); },
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
    querySelectorAll: () => [],
    setAttribute(k, v) { this.attrs = { ...(this.attrs || {}), [k]: v }; },
    getAttribute(k) { return (this.attrs || {})[k]; },
    appendChild() {},
  };
  return el;
}
const els = {};
for (const id of ['f-queries', 'queries-count', 'city-count', 'clear-all-btn',
  'pages-cap-note', 'f-pages', 'f-grad', 'f-gstep', 'grid-mode-row', 'grid-opts',
  'grid-lbl', 'grid-radius-out', 'grid-step-out', 'grid-step-scale', 'grid-hint',
  'btn-run-alias',
  'acc-basic-summary', 'f-city-input', 'city-dropdown', 'city-tags-row',
  'btn-run', 'btn-icon', 'btn-txt', 'btn-skip',
  'btn-stop', 'tab-log-dot',
  'status-badge',
  'api-status-badge', 'api-keys-body', 'api-keys-toggle',
  'key-dot-yandex', 'key-dot-2gis', 'key-dot-vk',
  'preset-block', 'preset-dd-wrap', 'preset-dd-btn', 'preset-dd-list',
  'preset-dd-current', 'preset-block-hint', 'preset-new-btn']) {
  els[id] = mkEl(id);
}
// Fake city chips for the fade-out assertion in clearAllInputs.
const fakeChips = [mkEl('chip-0'), mkEl('chip-1')];
els['city-tags-row'].querySelectorAll = () => fakeChips;

globalThis.document = { getElementById: id => els[id] ?? null, querySelector: () => null };
// clearAllInputs defers the re-render: capture the timer instead of waiting.
const pendingTimers = [];
globalThis.setTimeout = (fn, _ms) => { pendingTimers.push(fn); return pendingTimers.length; };
globalThis.selectedCities = [];
globalThis.citySearchText = '';
globalThis.dataSource = '2gis';

const fns = ['_pluralRu', '_countQueries', 'updateQueriesCounter', 'updateCityCount',
  'updateClearAllBtn', 'clearAllInputs', 'updateBasicSummary', 'renderCityTags',
  'isRunReady', 'updateRunBtnState', 'setRunBtnActive', 'resetBtn',
  'updateApiKeysStatus', 'updatePagesCapNote', 'setGridMode', 'onGridSlider',
  'pauseRun', 'enterPausedState', 'resumeRun', 'togglePresetDropdown',
  'setRunIndicator', '_logNorm', '_isDup'];
// stopRunWithConfirm is `async function` — grab() strips the modifier, so
// slice it manually and keep the await valid.
const asyncGrab = name => {
  const i = src.indexOf('async function ' + name + '(');
  assert.ok(i >= 0, 'async function not found in app.js: ' + name);
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
};
(0, eval)(fns.map(grab).join('\n') + '\n' + asyncGrab('stopRunWithConfirm'));
// resetBtn repaints the «Статистика» tab badge — irrelevant here.
globalThis.updateStatsBadge = () => {};
// setRunBtnActive/resetBtn rewire the dock button's onclick to these —
// provide offline stubs (the real ones live in the full bundle).
globalThis.stopRun = () => {};
globalThis.startRun = () => {};
globalThis._startRunWithParams = params => { globalThis.__lastLaunched = params; };
globalThis.showToast = () => {};
globalThis.appendLog = () => {};
globalThis.showTab = () => {};
globalThis.setStatus = (cls, txt) => { globalThis.__status = {cls, txt}; };
// onGridSlider repaints the step-scale labels via .children[0..2].
els['grid-step-scale'].children = [mkEl('sc0'), mkEl('sc1'), mkEl('sc2')];

// ── 1. Russian pluralization ─────────────────────────────────
test('_pluralRu covers all Russian plural forms', () => {
  const g = (n) => globalThis._pluralRu(n, 'город', 'города', 'городов');
  assert.equal(g(1), 'город');
  assert.equal(g(2), 'города');
  assert.equal(g(4), 'города');
  assert.equal(g(5), 'городов');
  assert.equal(g(11), 'городов');   // 11-14 always «городов»
  assert.equal(g(12), 'городов');
  assert.equal(g(14), 'городов');
  assert.equal(g(21), 'город');     // …but 21, 31, 101 go back to «город»
  assert.equal(g(22), 'города');
  assert.equal(g(25), 'городов');
  assert.equal(g(101), 'город');
  assert.equal(g(111), 'городов');
});

// ── 2. Queries counter ───────────────────────────────────────
test('queries counter: hidden on empty, singular for 1, plural for 2-4', () => {
  els['f-queries'].value = '';
  globalThis.updateQueriesCounter();
  assert.equal(els['queries-count'].hidden, true);

  els['f-queries'].value = 'кафе';
  globalThis.updateQueriesCounter();
  assert.equal(els['queries-count'].textContent, '• Будет выполнен 1 запрос');
  assert.equal(els['queries-count'].hidden, false);

  els['f-queries'].value = 'кафе\nресторан';
  globalThis.updateQueriesCounter();
  assert.equal(els['queries-count'].textContent, '• Будет выполнено 2 запроса');
});

test('queries counter ignores whitespace-only lines', () => {
  els['f-queries'].value = 'кафе\n\n   \nресторан\n\t\n';
  globalThis.updateQueriesCounter();
  assert.equal(els['queries-count'].textContent, '• Будет выполнено 2 запроса');
});

test('queries counter caps the displayed number at 10+', () => {
  els['f-queries'].value = Array.from({ length: 12 }, (_, i) => 'q' + i).join('\n');
  globalThis.updateQueriesCounter();
  assert.equal(els['queries-count'].textContent, '• Будет выполнено 10+ запросов');
});

// ── 3. City counter ──────────────────────────────────────────
test('city counter pluralizes and hides when empty', () => {
  globalThis.selectedCities = ['Уфа'];
  globalThis.updateCityCount();
  assert.equal(els['city-count'].textContent, '(1 город)');

  globalThis.selectedCities = ['Уфа', 'Казань', 'Сочи', 'Уфа2', 'Пермь'];
  globalThis.updateCityCount();
  assert.equal(els['city-count'].textContent, '(5 городов)');

  globalThis.selectedCities = [];
  globalThis.updateCityCount();
  assert.equal(els['city-count'].hidden, true);
});

// ── 4. «Очистить всё» visibility ─────────────────────────────
test('clear-cities button visibility: only cities (or city search text) matter', () => {
  globalThis.selectedCities = [];
  globalThis.citySearchText = '';
  els['f-queries'].value = '';
  globalThis.updateClearAllBtn();
  assert.equal(els['clear-all-btn'].hidden, true, 'hidden when everything is empty');

  globalThis.selectedCities = ['Уфа'];
  globalThis.updateClearAllBtn();
  assert.equal(els['clear-all-btn'].hidden, false, 'visible with a city');

  globalThis.selectedCities = [];
  globalThis.citySearchText = 'Уф';
  globalThis.updateClearAllBtn();
  assert.equal(els['clear-all-btn'].hidden, false, 'visible with city search text');

  // Queries alone no longer show the button — it clears CITIES only.
  globalThis.citySearchText = '';
  els['f-queries'].value = 'кафе';
  globalThis.updateClearAllBtn();
  assert.equal(els['clear-all-btn'].hidden, true, 'hidden with queries only');

  els['f-queries'].value = '   ';
  globalThis.updateClearAllBtn();
  assert.equal(els['clear-all-btn'].hidden, true, 'whitespace-only queries count as empty');
});

// ── 5. clearAllInputs — cities-only reset ─────────────────────
test('clearAllInputs clears cities + city input, but PRESERVES the queries', () => {
  // Arrange: everything filled
  globalThis.selectedCities = ['Уфа', 'Казань'];
  els['f-queries'].value = 'кафе\nресторан';
  els['f-city-input'].value = 'уф';
  els['city-dropdown'].innerHTML = '<div></div>';
  els['city-dropdown']._classes.add('open');
  globalThis.updateQueriesCounter();
  globalThis.updateClearAllBtn();
  assert.equal(els['queries-count'].hidden, false);
  assert.equal(els['clear-all-btn'].hidden, false);

  // Act
  pendingTimers.length = 0;
  globalThis.clearAllInputs();

  // Assert: immediate effects
  assert.equal(els['f-city-input'].value, '', 'city input cleared');
  assert.equal(els['f-queries'].value, 'кафе\nресторан', 'queries textarea PRESERVED');
  assert.equal(els['queries-count'].hidden, false, 'queries counter still visible');
  assert.equal(els['city-dropdown'].innerHTML, '', 'dropdown emptied');
  assert.equal(els['city-dropdown']._classes.has('open'), false, 'dropdown closed');
  assert.equal(globalThis.selectedCities.length, 0, 'city array cleared');
  for (const chip of fakeChips) {
    assert.equal(chip._classes.has('chip-out'), true, 'chip gets the fade-out class');
  }

  // Deferred re-render (captured setTimeout) refreshes the rest
  pendingTimers.splice(0).forEach(fn => fn());
  assert.equal(els['clear-all-btn'].hidden, true, 'button hides after re-render');
  assert.equal(els['city-count'].hidden, true, 'city counter hides after re-render');
});

// ── 6. Accordion summary ─────────────────────────────────────
test('summary: full format with 2GIS source', () => {
  globalThis.selectedCities = ['Уфа', 'Казань', 'Сочи'];
  els['f-queries'].value = 'кафе\nресторан\nпарикмахерская';
  globalThis.dataSource = '2gis';
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].textContent,
    'Кого ищем: кафе, ресторан, парикмахерская • Городов: 3 • Источник: 2GIS');
  assert.notEqual(els['acc-basic-summary'].style.display, 'none');
});

test('summary reflects the data source switch', () => {
  globalThis.selectedCities = ['Уфа'];
  els['f-queries'].value = 'кафе';
  globalThis.dataSource = 'yandex';
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].textContent,
    'Кого ищем: кафе • Городов: 1 • Источник: Яндекс');
});

test('summary truncates long query lists to 3 words + ellipsis', () => {
  els['f-queries'].value = 'кафе круглосуточное самообслуживание\nресторан';
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].textContent,
    'Кого ищем: кафе, круглосуточное, самообслуживание, … • Городов: 1 • Источник: Яндекс');
});

test('summary shows «не задано» for missing queries, hides when nothing set', () => {
  els['f-queries'].value = '';
  globalThis.selectedCities = ['Уфа'];
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].textContent,
    'Кого ищем: не задано • Городов: 1 • Источник: Яндекс');

  globalThis.selectedCities = [];
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].style.display, 'none');
});

test('summary ignores whitespace-only queries', () => {
  els['f-queries'].value = '   \n\t\n';
  globalThis.selectedCities = [];
  globalThis.updateBasicSummary();
  assert.equal(els['acc-basic-summary'].style.display, 'none');
});

// ── 7. Run-button readiness (sticky dock states) ─────────────
test('isRunReady: needs at least one query AND one city', () => {
  globalThis.selectedCities = [];
  els['f-queries'].value = '';
  assert.equal(globalThis.isRunReady(), false, 'nothing filled');

  els['f-queries'].value = 'кафе';
  assert.equal(globalThis.isRunReady(), false, 'queries without cities');

  els['f-queries'].value = '';
  globalThis.selectedCities = ['Уфа'];
  assert.equal(globalThis.isRunReady(), false, 'cities without queries');

  els['f-queries'].value = 'кафе\nресторан';
  assert.equal(globalThis.isRunReady(), true, 'both filled → ready');

  els['f-queries'].value = '   \n';
  assert.equal(globalThis.isRunReady(), false, 'whitespace-only queries are not queries');
});

test('updateRunBtnState: grey+disabled when not ready, teal when ready', () => {
  globalThis.selectedCities = [];
  els['f-queries'].value = '';
  els['btn-run'].disabled = false;
  els['btn-run']._classes.delete('run-ready');
  globalThis.updateRunBtnState();
  assert.equal(els['btn-run'].disabled, true, 'disabled when nothing filled');
  assert.equal(els['btn-run']._classes.has('run-ready'), false, 'no teal when not ready');

  globalThis.selectedCities = ['Уфа'];
  els['f-queries'].value = 'кафе';
  globalThis.updateRunBtnState();
  assert.equal(els['btn-run'].disabled, false, 'enabled when ready');
  assert.equal(els['btn-run']._classes.has('run-ready'), true, 'teal when ready');
});

test('setRunBtnActive: one control — main button = ⏸ Пауза, small ⏹ stops', () => {
  els['btn-run'].disabled = false;
  els['btn-run']._classes.add('run-ready');
  els['btn-run'].hidden = false;
  els['btn-stop'].hidden = true;
  els['btn-stop'].onclick = null;
  globalThis.setRunBtnActive();
  // The main button stays visible and becomes the pause control.
  assert.equal(els['btn-run'].hidden, false, 'main button visible while running');
  assert.equal(typeof els['btn-run'].onclick, 'function', 'onclick wired to pauseRun');
  assert.equal(els['btn-run']._classes.has('run-active'), true, 'red active style');
  assert.equal(els['btn-run']._classes.has('run-ready'), false, 'teal removed');
  assert.equal(els['btn-txt'].textContent, 'Пауза');
  assert.equal(els['btn-icon'].textContent, '⏸');
  // The small stop button appears next to it.
  assert.equal(els['btn-stop'].hidden, false, 'stop button visible');
  assert.equal(typeof els['btn-stop'].onclick, 'function', 'stop wired to stopRunWithConfirm');

  // updateRunBtnState must not flip anything back mid-run
  globalThis.updateRunBtnState();
  assert.equal(els['btn-run']._classes.has('run-active'), true, 'stays active mid-run');
});

test('stopRunWithConfirm: stops only after uiConfirm agrees', async () => {
  els['btn-stop'].hidden = false;
  let stopped = 0;
  const prevConfirm = globalThis.uiConfirm;
  const prevStop = globalThis.stopRun;
  globalThis.uiConfirm = async () => true;
  globalThis.stopRun = () => { stopped++; };
  await globalThis.stopRunWithConfirm();
  assert.equal(stopped, 1, 'stop ran after confirmation');

  stopped = 0;
  globalThis.uiConfirm = async () => false;
  await globalThis.stopRunWithConfirm();
  assert.equal(stopped, 0, 'stop skipped when declined');
  globalThis.uiConfirm = prevConfirm;
  globalThis.stopRun = prevStop;
});

test('pauseRun: disables the main button, shows the wait text', () => {
  els['btn-run'].disabled = false;
  els['btn-txt'].textContent = 'Пауза';
  globalThis.pauseRun();
  assert.equal(els['btn-run'].disabled, true, 'button disabled while pausing');
  assert.equal(els['btn-txt'].textContent, '⏳ Завершаем город…');
});

test('enterPausedState: orange resume button + paused badge', () => {
  els['btn-run'].hidden = true;
  els['btn-run']._classes.add('run-active');
  els['btn-stop'].hidden = false;
  const resume = {queries: ['кафе'], all_cities: ['Уфа'], params: {queries: ['кафе'], cities: ['Уфа']}};
  globalThis.enterPausedState(resume);
  assert.equal(els['btn-run'].hidden, false, 'main button visible again');
  assert.equal(els['btn-run'].disabled, false, 'resume button enabled');
  assert.equal(typeof els['btn-run'].onclick, 'function', 'onclick wired to resumeRun');
  assert.equal(els['btn-run']._classes.has('run-paused'), true, 'orange paused style');
  assert.equal(els['btn-run']._classes.has('run-active'), false, 'run-active cleared');
  assert.equal(els['btn-txt'].textContent, 'Продолжить поиск');
  assert.equal(els['btn-icon'].textContent, '▶', 'resume icon ▶');
  assert.equal(els['btn-stop'].hidden, true, 'stop button hidden while paused');
  assert.equal(globalThis.__status.cls, 'paused', 'status badge = paused');
  assert.equal(globalThis.__status.txt, '⏸ Пауза');
});

test('enterPausedState: tooltip/toast carry pause position + 2GIS quota', () => {
  let toastMsg = null;
  const prevToast = globalThis.showToast;
  globalThis.showToast = (msg, type) => { toastMsg = {msg, type}; };
  const resume = {
    queries: ['кафе'], all_cities: ['Уфа', 'Москва'],
    params: {queries: ['кафе'], cities: ['Уфа', 'Москва']},
    position: {city: 'Уфа', city_idx: 1, cities_total: 2, query: 'кафе',
               point: 7, points_total: 12, records: 45},
    quota: {used: 320, cap: 1000, spent_this_run: 45},
  };
  globalThis.enterPausedState(resume);
  const title = els['btn-run'].title;
  assert.ok(title.includes('Уфа (город 1 из 2)'), 'city+index in tooltip: ' + title);
  assert.ok(title.includes('«кафе»'), 'query in tooltip');
  assert.ok(title.includes('точка 7/12'), 'point in tooltip');
  assert.ok(title.includes('найдено 45'), 'records in tooltip');
  assert.ok(title.includes('осталось запросов к 2GIS: 680'), 'quota left in tooltip');
  assert.ok(toastMsg && toastMsg.msg.includes('Уфа'), 'toast mentions pause city');
  globalThis.showToast = prevToast;
});

test('enterPausedState: no position → generic title, no quota line', () => {
  const resume = {queries: [], all_cities: [], params: {}};
  globalThis.enterPausedState(resume);
  assert.equal(els['btn-run'].title, 'Продолжить поиск с сохранённого места');
});

test('resumeRun: relaunches with the SAME params + resume:true', () => {
  globalThis.__lastLaunched = null;
  globalThis._pausedRun = {queries: ['кафе'], all_cities: ['Уфа'], params: {queries: ['кафе'], cities: ['Уфа'], pages: 3}};
  els['btn-run']._classes.add('run-paused');
  globalThis.resumeRun();
  const launched = globalThis.__lastLaunched;
  assert.ok(launched, 'launch happened');
  assert.equal(launched.resume, true, 'resume flag set');
  assert.deepEqual(launched.queries, ['кафе'], 'queries preserved');
  assert.deepEqual(launched.cities, ['Уфа'], 'cities preserved');
  assert.equal(launched.pages, 3, 'other params preserved');
  assert.equal(els['btn-run']._classes.has('run-paused'), false, 'paused style cleared');
  assert.equal(globalThis._pausedRun, null, 'paused run consumed');
});

test('resumeRun: falls back to the payload queries/cities when params are thin', () => {
  // The server hands the resume payload both ways round — a payload without
  // the full params must still relaunch instead of doing nothing.
  globalThis.__lastLaunched = null;
  globalThis._pausedRun = {queries: ['кафе'], all_cities: ['Уфа'], params: {}};
  globalThis.resumeRun();
  const launched = globalThis.__lastLaunched;
  assert.ok(launched, 'launch happened');
  assert.equal(launched.resume, true);
  assert.deepEqual(launched.queries, ['кафе']);
  assert.deepEqual(launched.cities, ['Уфа']);
});

test('resumeRun: an unrecoverable payload reports instead of silently failing', () => {
  globalThis.__lastLaunched = null;
  globalThis._pausedRun = {params: {}};
  let toasted = null;
  const prevToast = globalThis.showToast;
  globalThis.showToast = (msg, type) => { toasted = {msg, type}; };
  try {
    globalThis.resumeRun();
    assert.equal(globalThis.__lastLaunched, null, 'nothing launched');
    assert.equal(toasted.type, 'error');
  } finally {
    globalThis.showToast = prevToast;
    globalThis._pausedRun = null;
  }
});

test('resumeRun without a paused run: no launch, error toast', () => {
  globalThis.__lastLaunched = null;
  globalThis._pausedRun = null;
  let toasted = null;
  const prevToast = globalThis.showToast;
  globalThis.showToast = (msg, type) => { toasted = {msg, type}; };
  try {
    globalThis.resumeRun();
    assert.equal(globalThis.__lastLaunched, null, 'nothing launched');
    assert.equal(toasted.type, 'error');
  } finally {
    globalThis.showToast = prevToast;
  }
});

test('resetBtn restores «Найти компании» and re-evaluates readiness', () => {
  // Run finishes, form is still filled → back to teal
  els['btn-run'].disabled = true;
  els['btn-run']._classes.add('run-active');
  els['btn-txt'].textContent = '⏸ Пауза';
  els['btn-run'].onclick = () => {};           // simulate the mid-run pause wiring
  globalThis.selectedCities = ['Уфа'];
  els['f-queries'].value = 'кафе';
  globalThis.resetBtn();
  assert.equal(els['btn-run'].disabled, false);
  assert.equal(els['btn-txt'].textContent, 'Найти компании');
  assert.equal(typeof els['btn-run'].onclick, 'function', 'onclick back to startRun');
  assert.equal(els['btn-run']._classes.has('run-active'), false, 'red cleared');
  assert.equal(els['btn-run']._classes.has('run-ready'), true, 'teal restored');
  assert.equal(els['btn-icon'].textContent, '🚀');

  // Run finishes, user cleared the form during the run → back to grey
  els['btn-run'].disabled = true;
  els['btn-run']._classes.add('run-active');
  globalThis.selectedCities = [];
  els['f-queries'].value = '';
  globalThis.resetBtn();
  assert.equal(els['btn-run'].disabled, true, 'grey when the form is empty again');
  assert.equal(els['btn-run']._classes.has('run-ready'), false);
});

// ── N1. Reset wiring ─────────────────────────────────────────
test('resetBtn rewires the dock button back to startRun', () => {
  const btn = els['btn-run'];
  const saved = btn.onclick;
  btn.onclick = () => {};                      // simulate mid-run stop wiring
  globalThis.resetBtn();
  assert.equal(typeof btn.onclick, 'function', 'onclick restored');
  btn.onclick = saved;
});

// ── N2. 2GIS pages-cap note ──────────────────────────────────
test('updatePagesCapNote: amber note only for 2GIS with pages > 5', () => {
  const note = els['pages-cap-note'];
  const pages = els['f-pages'];
  // Yandex: never capped
  globalThis.dataSource = 'yandex';
  pages.value = 15;
  globalThis.updatePagesCapNote();
  assert.equal(note.hidden, true, 'Yandex has no 5-page cap');

  // 2GIS: capped above 5
  globalThis.dataSource = '2gis';
  pages.value = 15;
  globalThis.updatePagesCapNote();
  assert.equal(note.hidden, false, 'visible for 2GIS with 15 pages');
  assert.match(note.textContent, /15 до 5/);
  pages.value = 5;
  globalThis.updatePagesCapNote();
  assert.equal(note.hidden, true, 'hidden at exactly 5 pages');
  pages.value = 3;
  globalThis.updatePagesCapNote();
  assert.equal(note.hidden, true, 'hidden below the cap');
  pages.value = 1;
});

// ── N3. Wand / grid null-safety (run inside the stub DOM) ────
test('grid functions are null-safe in a stub DOM (wand regression guard)', () => {
  globalThis.setGridMode('manual');
  globalThis.setGridMode('whole');
  globalThis.onGridSlider();
});

// ── N. API-keys badge states ─────────────────────────────────
test('updateApiKeysStatus: all 3 keys → «Готово 3/3»', () => {
  globalThis.updateApiKeysStatus(true, true, true);
  const b = els['api-status-badge'];
  assert.ok(b._classes.has('ok'));
  assert.match(b.textContent, /Готово 3\/3/);
});
test('updateApiKeysStatus: partial → orange badge with the exact ratio', () => {
  globalThis.updateApiKeysStatus(true, true, false);
  const b = els['api-status-badge'];
  assert.ok(b._classes.has('warn'), 'orange warn class');
  assert.match(b.textContent, /2\/3/, 'exact count shown');
  globalThis.updateApiKeysStatus(true, false, false);
  assert.ok(els['api-status-badge']._classes.has('warn'));
  assert.match(els['api-status-badge'].textContent, /1\/3/);
});
test('updateApiKeysStatus: no keys → «0/3» + err', () => {
  globalThis.updateApiKeysStatus(false, false, false);
  const b = els['api-status-badge'];
  assert.ok(b._classes.has('err'));
  assert.match(b.textContent, /0\/3/);
});
test('updateApiKeysStatus: per-key dots follow each key', () => {
  globalThis.updateApiKeysStatus(true, false, true);
  assert.ok(els['key-dot-yandex']._classes.has('on'), 'yandex dot on');
  assert.ok(!els['key-dot-2gis']._classes.has('on'), '2gis dot off');
  assert.ok(els['key-dot-vk']._classes.has('on'), 'vk dot on');
});
