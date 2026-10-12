// UI unit test: showTab('table') must not refetch /results-view while a run is
// active (the live SSE stream already fills the table; a disk snapshot would
// replace the accumulated rows with a partial/empty slice). After the run —
// and on the first open after a page reload — the saved snapshot is loaded
// exactly once.
//
// Run with: node --test "tests/ui/showtab.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readAppSrc } from './_src.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readAppSrc(root);

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
  return {
    id, hidden: false, innerHTML: '', textContent: '', style: {}, children: [],
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
  };
}

const els = {};
for (const id of [
  't-log', 'p-log', 't-table', 'p-table', 't-map', 'p-map',
  't-history', 'p-history', 't-stats', 'p-stats',
  't-templates', 'p-templates', 'btn-run',
]) els[id] = mkEl(id);

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelectorAll: () => [],   // .tab-btn / .tab-panel lists
};
globalThis.window = {};

// Calls we spy on: showTab must touch these only through the branches we test.
const calls = { setResultsView: [], updateBulkStats: 0, renderCityTabs: 0,
  loadDailyDynamics: 0, loadHistory: 0 };
globalThis.setResultsView = v => calls.setResultsView.push(v);
globalThis.updateBulkStats = () => { calls.updateBulkStats++; };
globalThis.renderCityTabs = () => { calls.renderCityTabs++; };
globalThis.loadHistory = () => { calls.loadHistory++; };
globalThis.loadSeenStatus = () => {};
globalThis.loadCityHistoryMeta = () => {};
globalThis.loadTemplates = () => Promise.resolve();
globalThis.renderTemplates = () => {};
globalThis.loadDailyDynamics = () => { calls.loadDailyDynamics++; };
globalThis.completedCityRecords = () => [];
globalThis.renderStats = () => {};
globalThis.ensureMapReady = () => {};

// Module-level state showTab closes over.
globalThis.allResults = [];
globalThis.mapInited = false;
globalThis.leafMap = null;
globalThis._lastCities = [];
globalThis._resultsView = 'raw';
globalThis._resultsLoadedOnce = false;
globalThis._runElapsed = () => '0:00';
globalThis._lastSkippedCities = [];

(0, eval)(grab('isRunActive') + '\n' + grab('showTab'));

function reset({ runActive = false, loadedOnce = false, results = [] } = {}) {
  for (const k of Object.keys(calls)) calls[k] = Array.isArray(calls[k]) ? [] : 0;
  els['btn-run']._classes.clear();
  els['btn-run']._classes.add('tab-btn');
  if (runActive) els['btn-run']._classes.add('run-active');
  globalThis._resultsLoadedOnce = loadedOnce;
  globalThis._resultsView = 'processed';
  globalThis.allResults = results;
  globalThis._lastCities = [];
}

// ── 1. Во время прогона срез с диска не трогаем ────────────────
test("showTab('table') does not refetch /results-view while a run is active", () => {
  reset({ runActive: true });
  globalThis.showTab('table');
  assert.equal(calls.setResultsView.length, 0,
    'live SSE rows must not be replaced by a disk snapshot');
  assert.equal(globalThis._resultsLoadedOnce, false,
    'the flag is only flipped by a real load');
  assert.equal(calls.updateBulkStats, 1, 'bulk counters still refresh (cheap)');
  assert.equal(calls.renderCityTabs, 0, 'no rows yet — nothing to re-tab');

  // Даже если срез уже грузили раньше, повторное открытие ничего не читает.
  reset({ runActive: true, loadedOnce: true });
  globalThis.showTab('table');
  assert.equal(calls.setResultsView.length, 0);
});

test("showTab('table') refreshes city tabs from the rows already in memory", () => {
  reset({ runActive: true, results: [{ name: 'А', city: 'Уфа' }] });
  globalThis.showTab('table');
  assert.equal(calls.setResultsView.length, 0);
  assert.equal(calls.renderCityTabs, 1, 'rows present → tabs re-rendered');
});

// ── 2. После прогона / первого открытия — ровно одна загрузка ──
test("after the run showTab('table') loads the snapshot exactly once", () => {
  reset({ runActive: false });
  globalThis.showTab('table');
  assert.deepEqual(calls.setResultsView, ['processed'],
    'the first open loads the current view');

  // Флагу доверяем: открытие вкладки второй раз не перезапрашивает срез.
  reset({ runActive: false, loadedOnce: true });
  globalThis.showTab('table');
  assert.equal(calls.setResultsView.length, 0, 'no second fetch');

  // Перезагрузка страницы: флаг false → снова ровно одна загрузка.
  reset({ runActive: false, loadedOnce: false });
  globalThis.showTab('table');
  assert.equal(calls.setResultsView.length, 1);
});

test('the real loader marks the flag, so the guard is not just the stub', () => {
  // setResultsView — единственное место, где флаг ставится в true; без этого
  // «Результаты» после перезагрузки страницы оставались на плейсхолдере.
  const body = grab('setResultsView');
  assert.match(body, /_resultsLoadedOnce\s*=\s*true/);
  // …а showTab читает и флаг, и признак активного прогона.
  const tab = grab('showTab');
  assert.match(tab, /if\s*\(!_resultsLoadedOnce\s*&&\s*!isRunActive\(\)\)\s*setResultsView\(_resultsView\)/);
});

// ── 3. Соседние вкладки не задеты этой логикой ───────────────
test("switching to «Статистика» always reloads the daily dynamics", () => {
  reset({ runActive: true });
  globalThis.showTab('stats');
  assert.equal(calls.loadDailyDynamics, 1, 'дисковая статистика грузится даже при прогоне');
  assert.equal(calls.setResultsView.length, 0);
});

test("switching to «История» loads the file list", () => {
  reset({ runActive: false });
  globalThis.showTab('history');
  assert.equal(calls.loadHistory, 1);
  assert.equal(calls.setResultsView.length, 0, 'история не трогает срез результатов');
});
