// UI unit tests for the log terminal + multi-city progress panel logic in
// static/js/app.js (run offline in Node against a DOM stub).
//
// Run with: node --test "tests/ui/logpanel.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

// Slice a full function (balanced braces) from the production bundle.
function grab(name) {
  let i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  if (i >= 6 && src.slice(i - 6, i) === 'async ') i -= 6;   // async functions
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
  let html = '';
  const el = {
    id, value: '', textContent: '', hidden: true, style: {},
    children: [], firstChild: null, scrollTop: 0, scrollHeight: 0,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
    },
    _classes: classes,
    appendChild(c) { el.children.push(c); el.firstChild = el.children[0]; },
    removeChild(c) {
      const i = el.children.indexOf(c);
      if (i >= 0) el.children.splice(i, 1);
      el.firstChild = el.children[0] || null;
    },
    remove() { /* stub: detach from parent — enough for appendLog paths */ },
    insertBefore(newEl, refEl) {
      const i = el.children.indexOf(refEl);
      if (i < 0) el.children.push(newEl);
      else el.children.splice(i, 0, newEl);
      return newEl;
    },
  };
  // innerHTML behaves like the real thing for the one case the code relies
  // on: assigning an empty string wipes the element's children (clearLog).
  Object.defineProperty(el, 'innerHTML', {
    get: () => html,
    set: v => { html = String(v); if (!html) { el.children = []; el.firstChild = null; } },
  });
  return el;
}

const els = {};
for (const id of ['log-output', 'log-ph', 'onboarding-screen', 'log-skeleton',
  'city-progress-list', 'city-progress', 'btn-tech-details', 'term-log-lbl',
  'ls-stage', 'ls-found-num', 't-stats',
  'term-progress', 'tp-done', 'tp-total', 'tp-fill', 'tp-eta', 'tp-city',
  'log-jump', 'log-jump-n', 'log-filter-empty', 'log-err-count',
  'log-autoscroll', 'tab-log-dot']) {
  els[id] = mkEl(id);
}
// log-output starts with the onboarding card, like the real page.
els['log-output'].appendChild(els['onboarding-screen']);
els['onboarding-screen'].hidden = false;

let dynCount = 0;
const createdEls = [];   // createElement output is findable by getElementById, as in a real DOM
const _mkDoc = {
  getElementById: id => els[id] || createdEls.find(e => e.id === id) || null,
  createElement: () => { const e = mkEl('dyn-' + (++dynCount)); createdEls.push(e); return e; },
  title: '',
};
globalThis.document = _mkDoc;
globalThis.window = {};
globalThis.showToast = () => {};
globalThis.setProgress = () => {};
globalThis.updateStatsBadge = () => {};
globalThis.refreshLiveStats = () => {};
globalThis.playCityDoneSound = () => {};
globalThis.renderDefaultStats = () => {};
globalThis.renderQuotaCard = () => {};
globalThis.notificationsEnabled = false;
globalThis.startTime = Date.now();
// Text helpers the sliced log functions call.
globalThis.escapeHtml = s => String(s ?? '');
globalThis.pluralRecords = n => 'записей';
globalThis.isRunActive = () => true;
// Module-level state the sliced functions close over — pre-seeded as globals.
globalThis._lastLogMsg = '';
globalThis.autoScrollEnabled = true;
globalThis._showTechDetails = false;
globalThis._cityProgressData = {};
globalThis._totalCities = 0;
globalThis._currentCityName = '';
// appendLog/toggleTechDetails close over the module-level logEl constant.
globalThis.logEl = els['log-output'];
// _trimLog closes over the module-level cap constant.
globalThis.MAX_LOG_LINES = 1200;

// ── Slice the functions under test ────────────────────────────
const fns = ['_trimLog', '_isDup', 'appendLog', 'toggleTechDetails', 'clearLog',
  'initCityProgress', 'updateCityProgress', 'renderCityProgress',
  'handleProgress', 'handleCityDone',
  'logStamp', '_elapsedStamp', '_logNorm', '_scrollLogIfFollowing', 'updateTermProgress', '_etaText',
  'setRunIndicator', 'renderLogStats',
  '_ls', '_logLevel', '_logIsNoise', '_logIsCity', '_logIndent', '_onLogScroll',
  '_updateLogJump', 'logJumpToBottom', 'setLogFilter', '_refreshLogFilter',
  'toggleLogBlock', '_logPlainText', 'saveLogFile', 'copyLogText'];
// Constants the sliced functions close over: declared with `const` in app.js,
// so eval-based slicing has to bring them along.
function grabConst(name) {
  const i = src.indexOf('const ' + name + ' =');
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  return src.slice(i, src.indexOf(';', i) + 1);
}
(0, eval)(fns.map(grab).join('\n')
  + '\n' + ['LOG_NOISE_RE', 'LOG_KEEP_RE', 'LOG_CITY_RE', 'LOG_SUBLINE_RE', 'LOG_FILTERS']
    .map(grabConst).join('\n'));

const logEl = els['log-output'];
const visibleLines = () => logEl.children.filter(c => c.className !== undefined);

// Every log test starts from a clean panel: counters, folds and the stamp
// memory are module state inside app.js, not per-element state.
function resetLog() {
  logEl.children = [];
  logEl.firstChild = null;
  logEl._classes.clear();
  logEl.clientHeight = 0;
  globalThis._logState = null;
  globalThis._lastLogMsg = '';
  globalThis._showTechDetails = false;
  els['log-jump'].hidden = true;
  els['log-filter-empty'].hidden = true;
}

// ── 1. Duplicate suppression ─────────────────────────────────
test('appendLog drops a consecutive duplicate line', () => {
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.appendLog('info', '🏙  Город 12/14: Душанбе');
  globalThis.appendLog('info', '🏙  Город 12/14: Душанбе');
  assert.equal(logEl.children.length, 1);
});

test('appendLog dedup is emoji/whitespace/case-insensitive', () => {
  logEl.children = [];
  globalThis._lastLogMsg = '';
  // Same line through different producers: city header vs summary — the
  // normalized comparison collapses them.
  globalThis.appendLog('info', '  Поиск: 1 город(ов), запросы: кафе');
  globalThis.appendLog('info', 'Поиск: 1 город(ов), запросы: кафе ');
  assert.equal(logEl.children.length, 1, 'variant whitespace still deduped');
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.appendLog('info', '🏙 Город 1/2: Уфа');
  globalThis.appendLog('info', 'Город 1/2: Уфа');
  assert.equal(logEl.children.length, 1, 'emoji-only difference deduped');
});

test('appendLog keeps non-consecutive repeats (A B A)', () => {
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.appendLog('info', 'a');
  globalThis.appendLog('info', 'b');
  globalThis.appendLog('info', 'a');
  assert.equal(logEl.children.length, 3);
});

test('appendLog drops duplicates of warn lines too', () => {
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.appendLog('warn', '  [!] одинаковая ошибка');
  globalThis.appendLog('warn', '  [!] одинаковая ошибка');
  assert.equal(logEl.children.length, 1);
});

test('progress and result events are never deduped through appendLog', () => {
  // appendLog is only used for human levels; ensure repeated calls with
  // different content still land.
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.appendLog('info', 'x');
  globalThis.appendLog('info', 'y');
  assert.equal(logEl.children.length, 2);
});

// ── 2. Tech-details toggle ───────────────────────────────────
// Developer traces are always STORED (hidden by CSS) — otherwise the
// «Технические» filter and the toggle could only reveal lines that happened
// to arrive while they were already on.
test('tech lines are stored but hidden until the toggle is on', () => {
  resetLog();
  globalThis._showTechDetails = false;
  globalThis.appendLog('tech', '2GIS API error: code=404 type=notFound');
  assert.equal(logEl.children.length, 1, 'tech line kept');
  assert.match(logEl.children[0].className, /tech/);
  assert.equal(logEl._classes.has('show-tech'), false, 'hidden by the container class');

  globalThis.toggleTechDetails();
  assert.equal(globalThis._showTechDetails, true);
  assert.equal(els['btn-tech-details'].textContent, '🙈 Скрыть детали');
  assert.equal(logEl._classes.has('show-tech'), true, 'now revealed');

  globalThis.toggleTechDetails();
  assert.equal(globalThis._showTechDetails, false);
  assert.equal(els['btn-tech-details'].textContent, '🔧 Технические детали');
  assert.equal(logEl._classes.has('show-tech'), false);
  assert.equal(globalThis._ls().stats.tech, 1, 'counted for the «Технические» filter');
});

// ── 3. clearLog resets the duplicate guard ───────────────────
test('clearLog resets the last-line memory', () => {
  globalThis._lastLogMsg = 'Старая строка';
  globalThis.clearLog();
  assert.equal(globalThis._lastLogMsg, '');
});

// ── 4. City progress panel ───────────────────────────────────
test('city_list event prefills queued cities with ⏸ and (ожидание)', () => {
  globalThis._cityProgressData = {};
  globalThis._totalCities = 0;
  els['city-progress'].children = [];
  els['city-progress-list'].innerHTML = '';
  globalThis.handleProgress('city_list|Ташкент/Санкт-Петербург');
  assert.equal(globalThis._totalCities, 2);
  const html = els['city-progress-list'].innerHTML;
  assert.match(html, /⏸/);
  assert.match(html, /\(ожидание\)/);
  const sum = els['city-progress'].children.find(c => c.id === 'cp-summary');
  assert.ok(sum, 'summary element created');
  assert.match(sum.innerHTML, /Городов обработано: <b>0<\/b> из <b>2<\/b>/);
});

test('city transition marks the current city as running (⏳)', () => {
  // Real flow: city_list arrives before the first city transition.
  globalThis._cityProgressData = {};
  globalThis._totalCities = 0;
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.handleProgress('city_list|Ташкент/Санкт-Петербург');
  globalThis.handleProgress('city/1/2/Ташкент');
  const html = els['city-progress-list'].innerHTML;
  assert.match(html, /⏳/);
  assert.match(html, /cp-running/);
});

test('progress ping updates % and shows found count in parentheses', () => {
  // _currentCityName was set to «Ташкент» by the previous transition.
  globalThis.handleProgress('45/100/кафе/37/0');
  const html = els['city-progress-list'].innerHTML;
  assert.match(html, /45%/);
  assert.match(html, /\(37 найд\.\)/);
});

test('city_done marks ✓, 100% and updates the «обработано» counter', () => {
  globalThis.handleProgress('city_done|1|2|Ташкент|done|45');
  const html = els['city-progress-list'].innerHTML;
  assert.match(html, /✓/);
  assert.match(html, /100%/);
  assert.match(html, /\(45 найд\.\)/);
  const sum = els['city-progress'].children.find(c => c.id === 'cp-summary');
  assert.match(sum.innerHTML, /Городов обработано: <b>1<\/b> из <b>2<\/b>/);
});

test('queued city stays grey (cp-queued) while another is running', () => {
  const html = els['city-progress-list'].innerHTML;
  assert.match(html, /cp-queued/);        // Санкт-Петербург still queued
  assert.match(html, /Санкт-Петербург/);
});

test('single-city runs keep the panel hidden', () => {
  els['city-progress'].style.display = '';
  globalThis.initCityProgress(1);
  assert.equal(els['city-progress'].style.display, 'none');
});

// ── 5. Elapsed stamps + autoscroll ───────────────────────────
test('every log line carries an absolute [HH:MM:SS] stamp (delta in title)', () => {
  logEl.children = [];
  globalThis._lastLogMsg = '';
  globalThis.startTime = Date.now();
  globalThis.appendLog('info', 'строка');
  // Absolute wall-clock time [HH:MM:SS], run-start delta moved to the title.
  // Second repeats are hidden by CSS («same»), the text is always rendered.
  assert.match(logEl.children[0].innerHTML, /class="ll-time(?: same)?">\[\d\d:\d\d:\d\d\]</);
  assert.match(logEl.children[0].title, /^\+\d+:\d\d$/, 'elapsed delta in hover title');
  // Elapsed helper: 90 seconds in → +1:30.
  globalThis.startTime = Date.now() - 90000;
  assert.equal(globalThis._elapsedStamp(), '+1:30');
  // Absolute stamp always matches HH:MM:SS.
  assert.match(globalThis.logStamp(), /^\d\d:\d\d:\d\d$/);
});

test('the log follows the tail by default and stops when the user scrolls up', () => {
  resetLog();
  logEl.scrollTop = 0;
  logEl.scrollHeight = 500;
  globalThis.appendLog('info', 'первая строка');
  assert.equal(logEl.scrollTop, 500, 'sticks to the tail by default');

  // The reader scrolls up: 400px away from the tail on a 100px-high viewport.
  logEl.clientHeight = 100;
  logEl.scrollTop = 0;
  globalThis._onLogScroll();
  assert.equal(globalThis._ls().follow, false, 'autoscroll released');

  globalThis.appendLog('info', 'вторая строка');
  assert.equal(logEl.scrollTop, 0, 'a scrolled-up reader is not yanked to the tail');
  assert.equal(els['log-jump'].hidden, false, 'the «К последней строке» button appears');
  assert.equal(els['log-jump-n'].textContent, '1', 'and counts what is waiting');

  globalThis.logJumpToBottom();
  assert.equal(els['log-jump'].hidden, true);
  assert.equal(globalThis._ls().follow, true);
  assert.equal(globalThis._ls().below, 0);
});

test('app.js has no leftover autoscroll switch wiring', () => {
  assert.ok(!/autoScrollEnabled/.test(src), 'autoScrollEnabled global is gone');
  assert.ok(!/getElementById\(['"]autoscroll['"]\)/.test(src), 'no autoscroll checkbox lookup left');
  assert.ok(!/Здесь появится ход поиска/.test(src), 'the old placeholder caption is gone');
});

// ── 6. Aggregate progress above the log ──────────────────────
test('aggregate bar counts finished cities + the running one\u2019s %', () => {
  globalThis._cityProgressData = {
    'Ташкент': {pct: 100, found: 45, status: 'done'},
    'Санкт-Петербург': {pct: 50, found: 10, status: 'running'},
  };
  globalThis._totalCities = 2;
  globalThis.updateTermProgress();
  assert.equal(els['term-progress'].hidden, false);
  assert.equal(els['tp-done'].textContent, 1);
  assert.equal(els['tp-total'].textContent, 2);
  assert.equal(els['tp-fill'].style.width, '75.0%');

  globalThis._totalCities = 1;
  globalThis.updateTermProgress();
  assert.equal(els['term-progress'].hidden, true, 'single city → hidden');
});

// ── 7. Run indicator on the «Ход поиска» tab ─────────────────
test('tab dot follows the run lifecycle', () => {
  globalThis.setRunIndicator(true);
  assert.equal(els['tab-log-dot'].hidden, false);
  globalThis.setRunIndicator(false);
  assert.equal(els['tab-log-dot'].hidden, true);
});

// ── 8. Structured stats card ─────────────────────────────────
test('renderLogStats draws rows with bars instead of ASCII art', () => {
  logEl.children = [];
  globalThis.renderLogStats(JSON.stringify({
    total: 50,
    by_social: [{label: 'ВКонтакте', count: 37}, {label: 'Telegram', count: 30}],
    by_query: [],
    top_categories: [{label: 'кафе', count: 9}],
  }));
  assert.equal(logEl.children.length, 1);
  assert.equal(logEl.children[0].className, 'log-stats');
  const html = logEl.children[0].innerHTML;
  assert.match(html, /ВКонтакте/);
  assert.match(html, /width:100%/, 'longest bar is full width');
  assert.match(html, /Топ категорий/);

  // A broken payload must never paint an empty card.
  logEl.children = [];
  globalThis.renderLogStats('{not json');
  assert.equal(logEl.children.length, 0);
});

// ── 9. Level colours ─────────────────────────────────────────
test('every level gets its own colour class', () => {
  resetLog();
  globalThis.appendLog('ok', '  ✅ Сохранено');
  globalThis.appendLog('warn', '  ⚠ Предупреждение');
  globalThis.appendLog('error', '  [✖] Не найдено');
  globalThis.appendLog('info', '  📡 Ищу');
  const cls = logEl.children.map(c => c.className);
  assert.match(cls[0], /\bok\b/);
  assert.match(cls[1], /\bwarn\b/);
  assert.match(cls[2], /\berror\b/);
  assert.match(cls[3], /\binfo\b/);
});

test('a warn-level line marked [!] is painted as an error', () => {
  resetLog();
  globalThis.appendLog('warn', '  [!] Ошибка записи Excel');
  assert.match(logEl.children[0].className, /\berror\b/);
  assert.equal(globalThis._ls().stats.err, 1);
});

// ── 10. Filters ──────────────────────────────────────────────
test('filters are one class on the container, with an empty verdict', () => {
  resetLog();
  globalThis.appendLog('info', '  📡 Ищу кафе');
  globalThis.setLogFilter('errors');
  assert.equal(globalThis._ls().filter, 'errors');
  assert.equal(logEl._classes.has('f-errors'), true);
  assert.equal(els['log-filter-empty'].hidden, false);
  assert.equal(els['log-filter-empty'].textContent, '✅ Ошибок нет');

  globalThis.appendLog('warn', '  [✖] Сломалось');
  assert.equal(els['log-filter-empty'].hidden, true, 'a warning fills the errors filter');
  assert.equal(els['log-err-count'].textContent, '1');
  assert.equal(els['log-err-count'].hidden, false);

  globalThis.setLogFilter('all');
  assert.equal(logEl._classes.has('f-all'), true);
  assert.equal(logEl._classes.has('f-errors'), false, 'only one filter class at a time');
});

// The «Важные» filter owns the WHOLE technical stream: geocoding, raw
// coordinates, per-query banners, page/point counters, HTTP statuses and
// client traces. Results and statuses stay readable in both filters.
test('«Важные» hides every technical line and keeps the results', () => {
  const noise = [
    '  Геокодирую «Москва»…',
    '  → 61.24178, 73.39383',
    '  ─── Запрос «кафе»: начало поиска',
    '  🔍 Поиск: «кафе» в Москва…',
    '  page 2/5',
    '  HTTP 200',
    '  point 3/12',
    '  Checkpoint: 40 ранее найденных, 3 точек уже обработано.',
    '  browser_client: cache initialized, 12 entries',
  ];
  const keep = [
    '  🏙  Город 1/2: Москва',
    '  🔍 Поиск в «Москва» — запросы: кафе',
    '  🗺  Источник: 2GIS (официальный API — соцсети и сайты уже в ответе)',
    '  🗺  Источник: Яндекс.Карты',
    '  ✅ «кафе»: 50 записей',
    '  📦 Raw: 50 организаций (без фильтров) → output/raw/',
    '  🎯 Processed: 44 организаций → 2 файлов в output/processed/',
    '  💾 Карта: готово → output/map.html',
    '  [!] Не удалось загрузить детали — пропускаю организацию',
  ];
  resetLog();
  noise.forEach(t => globalThis.appendLog('info', t));
  keep.forEach(t => globalThis.appendLog('info', t));
  assert.equal(globalThis._ls().stats.noise, noise.length,
    'each technical line is classified as noise');
  noise.forEach((t, i) => assert.match(logEl.children[i].className, /\bnoise\b/, 'noise: ' + t));
  keep.forEach((t, i) =>
    assert.ok(!/\bnoise\b/.test(logEl.children[noise.length + i].className), 'kept: ' + t));
});

test('«Технические»/«Все» still show the mechanics «Важные» hides', () => {
  resetLog();
  globalThis.appendLog('info', '  → 61.24178, 73.39383');
  globalThis.appendLog('info', '  🏙  Город 1/1: Уфа');
  globalThis.setLogFilter('tech');
  // The line stays in the DOM (CSS decides visibility), it is only tagged.
  assert.equal(logEl.children.length, 2);
  assert.match(logEl.children[0].className, /\bnoise\b/);
  globalThis.setLogFilter('all');
  assert.equal(logEl._classes.has('f-all'), true);
});

test('«Важные» marks mechanics as noise but never drops them', () => {
  resetLog();
  globalThis.appendLog('info', '  📡 Геокодирую «Ленина 1»');
  globalThis.appendLog('info', '  🏙  Город 1/1: Уфа');
  globalThis.setLogFilter('important');
  assert.equal(globalThis._ls().stats.noise, 1);
  assert.match(logEl.children[0].className, /\bnoise\b/);
  assert.equal(els['log-filter-empty'].hidden, true, 'the city header is still important');

  globalThis.setLogFilter('tech');
  globalThis.appendLog('tech', 'http_client: GET 429');
  assert.equal(els['log-filter-empty'].hidden, true);
  assert.equal(globalThis._ls().stats.tech, 1);
});

// ── 11. City folds + hierarchy ───────────────────────────────
test('city headers open a fold and later lines can be collapsed', () => {
  resetLog();
  globalThis.appendLog('info', '  🏙  Город 1/2: Уфа');
  globalThis.appendLog('info', '  📡 Ищу кафе');
  const hdr = logEl.children[0];
  assert.match(hdr.className, /\bcity\b/);
  assert.equal(typeof hdr.onclick, 'function', 'the header is clickable');

  hdr.onclick();
  assert.equal(globalThis._ls().collapsed[0], true);
  assert.equal(hdr._classes.has('collapsed'), true);
  assert.equal(logEl.children[1].style.display, 'none');

  hdr.onclick();
  assert.equal(logEl.children[1].style.display, '', 'unfolded again');

  hdr.onclick();
  globalThis.appendLog('info', '  📡 Строка при свёрнутом блоке');
  assert.equal(logEl.children[2].style.display, 'none', 'a folded block stays folded');
});

test('indented sub-lines get the hierarchy class', () => {
  resetLog();
  globalThis.appendLog('info', '  queries=[\'кафе\']');
  globalThis.appendLog('info', '  📡 Ищу кафе');
  assert.match(logEl.children[0].className, /\bind-1\b/);
  assert.ok(!/\bind-1\b/.test(logEl.children[1].className));
});

// ── 12. Timestamps ───────────────────────────────────────────
test('the stamp column is dimmed when the second has not changed', () => {
  resetLog();
  globalThis.appendLog('info', 'a');
  globalThis.appendLog('info', 'b');
  const first = /\[(\d\d:\d\d:\d\d)\]/.exec(logEl.children[0].innerHTML);
  assert.ok(first, 'the first line always carries a time');
  const second = logEl.children[1].innerHTML;
  const m = /\[(\d\d:\d\d:\d\d)\]/.exec(second);
  if (m && m[1] === first[1]) assert.match(second, /ll-time same/, 'repeated second is dimmed');
  else assert.match(second, /ll-time"/, 'a new second is printed');
});

// ── 13. Save / copy the whole log ────────────────────────────
test('_logPlainText writes one stamped line per log row', () => {
  resetLog();
  globalThis.appendLog('info', 'первая');
  globalThis.appendLog('ok', '  ✅ вторая');
  const lines = globalThis._logPlainText().split('\n');
  assert.equal(lines.length, 2, 'the cards and placeholders are not lines');
  assert.match(lines[0], /^\[\d\d:\d\d:\d\d\] первая$/);
  assert.match(lines[1], /вторая$/);

  // A cleared log saves nothing — the buttons must not write an empty file.
  globalThis.clearLog();
  assert.equal(globalThis._logPlainText(), '');
});

// ── 14. Progress strip: current city + overall bar (no per-city dupe) ──
// The run used to paint every city twice: as mini bars here and in the top
// strip. The log panel now owns the AGGREGATE only.
test('progress strip names the running city and sizes the overall bar', () => {
  globalThis._cityProgressData = {
    'Ташкент': {pct: 100, found: 45, status: 'done'},
    'Санкт-Петербург': {pct: 50, found: 10, status: 'running'},
  };
  globalThis._totalCities = 2;
  globalThis.updateTermProgress();
  assert.equal(els['tp-city'].textContent, 'Санкт-Петербург');
  assert.equal(els['tp-done'].textContent, 1);
  assert.equal(els['tp-total'].textContent, 2);
  // 1 finished city + the running one at 50% of 2 cities = 75%.
  assert.equal(els['tp-fill'].style.width, '75.0%');
});

test('the log panel never repeats the city list (top strip owns it)', () => {
  const tpl = readFileSync(join(root, 'templates', 'index.html'), 'utf8');
  assert.ok(!/id="tp-cities"/.test(tpl), 'tp-cities markup is gone');
  assert.ok(!/tp-chip/.test(src), 'per-city chips are not rendered any more');
  const css = readFileSync(join(root, 'static', 'css', 'style.css'), 'utf8');
  assert.ok(!/\.tp-chip/.test(css), 'chip styles are gone too');
  // …while the top strip caps its height and scrolls instead of growing.
  assert.match(css, /#city-progress-list\{[^}]*max-height/);
  assert.match(css, /#city-progress-list\{[^}]*overflow-y:auto/);
});
