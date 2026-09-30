// UI unit tests for «Динамика по дням» (вкладка «Статистика») in static/js/app.js.
//
// The renderer is sliced verbatim from the production bundle and run against a
// minimal DOM stub — the chart is plain markup, so no browser is needed.
//
// Run with: node --test tests/ui/statsdaily.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

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

// Минимальный DOM-узел: столько интерфейса, сколько требует код графика.
// classList и getBoundingClientRect «настоящие» — на них держится подсказка.
function mkEl(id) {
  const el = {
    id, value: '', textContent: '', innerHTML: '', hidden: false, style: {}, dataset: {},
    clientWidth: 0, isConnected: true, _cls: new Set(), _attrs: {},
    _rect: { left: 0, top: 0, width: 200, height: 40 },
    classList: {
      add: (...c) => c.forEach(x => el._cls.add(x)),
      remove: (...c) => c.forEach(x => el._cls.delete(x)),
      toggle: (c, on) => { if (on) el._cls.add(c); else el._cls.delete(c); },
      contains: c => el._cls.has(c),
    },
    // Как в DOM: right/bottom считаются от left/top + размер, поэтому тесты
    // задают только left/top/width/height, а код читает полный прямоугольник.
    getBoundingClientRect: () => ({
      left: el._rect.left, top: el._rect.top,
      width: el._rect.width, height: el._rect.height,
      right: el._rect.left + el._rect.width, bottom: el._rect.top + el._rect.height,
    }),
    querySelector: () => null, querySelectorAll: () => [],
    appendChild() {}, remove() {}, addEventListener() {},
    setAttribute: (k, v) => { el._attrs[k] = String(v); },
    getAttribute: k => (k in el._attrs ? el._attrs[k] : null),
  };
  return el;
}

const els = { 'stats-daily': mkEl('stats-daily'), 'p-stats': mkEl('p-stats') };
els['p-stats']._rect = { left: 0, top: 100, width: 1200, height: 600 };
// Подсказка живёт в <body>: проверяем именно это, а не вложенность в график.
const body = mkEl('body');
const appended = [];
body.appendChild = el => appended.push(el);
globalThis.window = { innerWidth: 1200, innerHeight: 800, addEventListener() {} };
globalThis.document = { getElementById: id => els[id] ?? null, querySelector: () => null,
                        querySelectorAll: () => [], createElement: () => mkEl('created'),
                        body };

(0, eval)(['UI_ICONS', 'DAILY_SEGMENTS', 'DAILY_DEFAULT_DAYS', 'DAILY_WEEKDAYS',
           'DAILY_TIP_GAP'].map(grabConst).join('\n'));
(0, eval)(['escapeHtml', '_pluralRu', '_fmtCount', '_fmtTick', 'dailyAxis', '_dailyDense',
           '_dailyDayLabel', '_dayFull', '_todayIso', '_dailyQuery', '_dailyRangeLabel',
           '_dailyEmptyText', '_dailyNoteHTML', 'dailyControlsHTML', 'dailyCustomHTML',
           'dailySectionHTML', 'dailyHoursChartHTML', 'renderDailyDynamics', 'loadDailyDynamics', '_reloadDaily',
           'setDailyRange', 'setDailyMonth', '_dateInputValue', 'applyDailyCustom',
           'toggleDailyCustom', '_dailyTipNode', '_dailyTipHTML', '_dailyTipBounds',
           '_placeDailyTip', '_showDailyTip', '_hideDailyTip', '_bindDailyHover'].map(grab).join('\n'));

// Module-scope state (declared with `let` in the bundle, so not grabbable).
const daysRange = days => ({ kind: 'days', days, month: '', from: '', to: '' });
globalThis._dailyRange = daysRange(7);
globalThis._dailyPayload = null;
globalThis._dailyCustomOpen = false;
globalThis._dailySeq = 0;
globalThis._dailyHoverBound = false;   // подсказки вешаются один раз на контейнер
globalThis._dailyTip = null;
globalThis._dailyTipCol = null;
globalThis._dailyTipSize = null;

let fetches = [];
globalThis.fetch = async url => {
  fetches.push(url);
  return { ok: true, json: async () => globalThis.__dailyResponse };
};

const SERIES = [
  { date: '2026-09-29', found: 50, reviewed: 2, files: 1 },
  { date: '2026-09-30', found: 100, reviewed: 0, files: 2 },
];
const payload = over => Object.assign(
  { mode: 'days', days: 7, start: '2026-09-24', end: '2026-09-30', truncated: false,
    series: SERIES, totals: { found: 150, reviewed: 2, undated: 0 } }, over);

// Разрез по колонкам-дням: `class="dyn-col"` / `class="dyn-col is-today"`,
// но НЕ `class="dyn-cols"` (контейнер ряда) — иначе в списке появился бы
// лишний кусок до первой колонки.
const columnsOf = html => html.split(/class="dyn-col[ "]/).slice(1);

// ── Форматирование и шкала ────────────────────────────────────

test('_fmtCount: разряды разделяются, чтобы «1 062» читалось', () => {
  assert.equal(_fmtCount(0), '0');
  assert.equal(_fmtCount(1062), '1 062');
  assert.equal(_fmtCount(1500000), '1 500 000');
});

test('_fmtTick: длинные подписи оси сжимаются, короткие — нет', () => {
  assert.equal(_fmtTick(500), '500');
  assert.equal(_fmtTick(1500), '1 500');
  assert.equal(_fmtTick(15000), '15к');
});

test('dailyAxis: верх шкалы круглый, делений 3–5', () => {
  assert.deepEqual(dailyAxis(100), { top: 100, step: 50, n: 2 });
  assert.deepEqual(dailyAxis(1062), { top: 1500, step: 500, n: 3 });
  assert.deepEqual(dailyAxis(7), { top: 8, step: 2, n: 4 });
  // Совсем маленькие максимумы не превращаются в дробные деления.
  assert.deepEqual(dailyAxis(1), { top: 1, step: 1, n: 1 });
  assert.equal(dailyAxis(9).step, 5);
  for (const max of [1, 2, 3, 5, 9, 14, 60, 100, 240, 1062, 98765]) {
    const a = dailyAxis(max);
    assert.ok(a.top >= max, 'верх не ниже максимума: ' + max);
    assert.ok(a.n >= 1 && a.n <= 4, 'делений от 1 до 4: ' + max);
    assert.ok(Number.isInteger(a.step) && a.step >= 1, 'шаг целый: ' + max);
  }
});

test('_dailyDense: подписи прячутся, когда на них нет ширины', () => {
  els['stats-daily'].clientWidth = 900;
  assert.equal(_dailyDense(7), false);
  assert.equal(_dailyDense(30), true);
  // Скрытая вкладка (ширина 0) — считаем ряд плотным, если дней больше 7.
  els['stats-daily'].clientWidth = 0;
  assert.equal(_dailyDense(7), false);
  assert.equal(_dailyDense(14), true);
});

// ── Раскладка ─────────────────────────────────────────────────

test('dailySectionHTML: колонка на каждый день, два столбца в колонке', () => {
  const html = dailySectionHTML(payload());
  assert.equal(columnsOf(html).length, 2, 'по одному столбцу на день окна');
  assert.equal((html.match(/dyn-bar dyn-found/g) || []).length, 2);
  assert.equal((html.match(/dyn-bar dyn-review/g) || []).length, 2);
  assert.match(html, /dyn-wd">ср</, 'подпись дня недели');
  assert.match(html, /dyn-dm">30\.09</, 'подпись даты');
  assert.match(html, /Динамика по дням/);
});

test('dailySectionHTML: шкала общая, высота считается от вертикали оси', () => {
  const html = dailySectionHTML(payload());
  const [first, second] = columnsOf(html);
  assert.match(first, /dyn-bar dyn-found" style="height:50%"/);
  assert.match(second, /dyn-bar dyn-found" style="height:100%"/);
});

test('dailySectionHTML: ось подписана, сетка идёт по тем же делениям', () => {
  const html = dailySectionHTML(payload());          // максимум 100 → 0/50/100
  const axis = html.slice(html.indexOf('dyn-yaxis'), html.indexOf('dyn-area'));
  assert.deepEqual([...axis.matchAll(/style="bottom:([\d.]+)%">([^<]+)</g)]
    .map(m => [Number(m[1]), m[2]]), [[0, '0'], [50, '50'], [100, '100']]);
  const grid = html.slice(html.indexOf('dyn-grid'), html.indexOf('dyn-cols'));
  // Нулевая линия — граница .dyn-stack, отдельной линии на ней не нужно.
  assert.deepEqual([...grid.matchAll(/bottom:([\d.]+)%/g)].map(m => Number(m[1])), [50, 100]);
});

test('dailySectionHTML: у столбца есть цифра, и она едет вместе с ним', () => {
  const [first, second] = columnsOf(dailySectionHTML(payload()));
  assert.match(second, /dyn-vlab" style="bottom:calc\(100% \+ 3px\)">100</);
  assert.match(first, /dyn-vlab" style="bottom:calc\(50% \+ 3px\)">50</);
  // Цвет подписи — от серии: акцентная над найденным, зелёная над просмотренным.
  assert.match(second, /dyn-series dyn-found"><span class="dyn-vlab"/);
  assert.match(second, /dyn-series dyn-review"><span class="dyn-vlab is-zero"/);
});

test('dailySectionHTML: нулевой день — насечка без inline-высоты', () => {
  // inline-высота перебила бы правило .is-zero, поэтому её быть не должно.
  const html = dailySectionHTML(payload({
    series: [{ date: '2026-09-30', found: 0, reviewed: 0, files: 0 }],
    days: 1, totals: { found: 5, reviewed: 1 },
  }));
  assert.match(html, /class="dyn-bar dyn-found is-zero"><\/div>/);
  assert.match(html, /class="dyn-bar dyn-review is-zero"><\/div>/);
  assert.ok(!/class="dyn-bar[^"]*is-zero"[^>]*style=/.test(html), 'у насечки нет inline-высоты');
  // …а подпись ноля есть: пользователь должен видеть цифру, а не пустоту.
  assert.match(html, /dyn-vlab is-zero" style="bottom:calc\(0% \+ 3px\)">0</);
});

test('dailySectionHTML: сегодняшний день помечен, остальные — нет', () => {
  const html = dailySectionHTML(payload());
  assert.equal((html.match(/is-today/g) || []).length, 1);
  assert.match(columnsOf(html)[1], /^is-today"/, 'последний день окна — сегодня');
});

test('dailySectionHTML: день несёт данные для подсказки', () => {
  const second = columnsOf(dailySectionHTML(payload()))[1];
  assert.match(second, /data-wd="ср"/);
  assert.match(second, /data-dm="30\.09"/);
  assert.match(second, /data-found="100"/);
  assert.match(second, /data-review="0"/);
  assert.match(second, /data-files="2"/);
  const first = columnsOf(dailySectionHTML(payload()))[0];
  assert.match(first, /data-pct="4"/, 'разобрано = просмотрено / найдено в этот день');
});

test('dailySectionHTML: легенда и итоги периода', () => {
  const html = dailySectionHTML(payload());
  assert.match(html, /Найдено <b>150<\/b>/);
  assert.match(html, /Просмотрено <b>2<\/b>/);
  assert.match(html, /В среднем <b>75<\/b> в день/);
  assert.match(html, /Лучший день — <b>ср, 30\.09<\/b>: 100/);
  assert.match(html, /Разобрано <b>1%<\/b>/);
});

test('dailySectionHTML: плотный ряд получает is-dense', () => {
  els['stats-daily'].clientWidth = 900;
  const seven = dailySectionHTML(payload());
  const thirty = dailySectionHTML(payload({ days: 30, series: Array.from({ length: 30 }, (_, i) =>
    ({ date: '2026-09-' + String(i + 1).padStart(2, '0'), found: i, reviewed: 0, files: 1 })) }));
  assert.ok(!/dyn-chart is-dense/.test(seven));
  assert.match(thirty, /dyn-chart is-dense/);
});

test('dailySectionHTML: aria-label описывает период и итоги', () => {
  const label = dailySectionHTML(payload()).match(/role="img" aria-label="([^"]*)"/)[1];
  assert.match(label, /2 дней/);
  assert.match(label, /найдено 150/);
  assert.match(label, /просмотрено 2/);
  assert.match(label, /в среднем 75 в день/);
});

// ── Состояния ─────────────────────────────────────────────────

test('dailySectionHTML: пустой период объясняется, а не рисуется нулями', () => {
  const html = dailySectionHTML(payload({ series: [], totals: { found: 0, reviewed: 0 } }));
  assert.match(html, /ничего не найдено и не отмечено просмотренным/);
  assert.ok(!html.includes('dyn-chart'), 'пустой график не рисуется');
  assert.match(html, /dyn-range/, 'переключатель периода остаётся доступным');
});

test('dailySectionHTML: пустой месяц и пустой диапазон названы датами', () => {
  const empty = { series: [], totals: { found: 0, reviewed: 0 } };
  const month = dailySectionHTML(payload(Object.assign(
    { mode: 'month', days: 31, start: '2026-08-01', end: '2026-08-31' }, empty)));
  assert.match(month, /С 01\.08\.2026 по 31\.08\.2026 ничего не найдено/);

  const range = dailySectionHTML(payload(Object.assign(
    { mode: 'range', days: 11, start: '2026-07-20', end: '2026-07-30' }, empty)));
  assert.match(range, /С 20\.07\.2026 по 30\.07\.2026 ничего не найдено/);

  const today = dailySectionHTML(payload(Object.assign(
    { mode: 'days', days: 1, start: '2026-09-30', end: '2026-09-30' }, empty)));
  assert.match(today, /За сегодня ничего не найдено/);
});

test('dailySectionHTML: отметки без даты объясняются, а не молчат', () => {
  const html = dailySectionHTML(payload({ totals: { found: 150, reviewed: 0, undated: 12 } }));
  assert.match(html, /Ещё 12 отметок «просмотрено»/);
  assert.match(html, /в динамике по дням они не участвуют/);
  // Без таких отметок лишней строки нет.
  assert.ok(!dailySectionHTML(payload()).includes('dyn-note'));
  // И одна отметка — «отметка», а не «отметок».
  assert.match(dailySectionHTML(payload({ totals: { found: 1, reviewed: 0, undated: 1 } })),
    /Ещё 1 отметка/);
});

test('dailySectionHTML: обрезанный период признаётся', () => {
  assert.match(dailySectionHTML(payload({ truncated: true })), /Период длиннее года/);
  assert.ok(!dailySectionHTML(payload()).includes('Период длиннее года'));
});

test('dailySectionHTML: даты периода подписаны под легендой', () => {
  assert.match(dailySectionHTML(payload()), /dyn-span">24\.09\.2026 — 30\.09\.2026</);
  assert.match(dailySectionHTML(payload({ days: 1, start: '2026-09-30', end: '2026-09-30' })),
    /dyn-span">30\.09\.2026</);
});

test('dailySectionHTML: за один день нет «в среднем» и «лучшего дня»', () => {
  const html = dailySectionHTML(payload({
    days: 1, start: '2026-09-30', end: '2026-09-30',
    series: [{ date: '2026-09-30', found: 100, reviewed: 3, files: 2 }],
    totals: { found: 100, reviewed: 3 },
  }));
  assert.ok(!html.includes('В среднем'), 'среднее за один день — это он сам');
  assert.ok(!html.includes('Лучший день'), 'лучший день за сутки — вся сутки');
  assert.match(html, /Разобрано <b>3%<\/b>/);
});

test('dailySectionHTML: загрузка и ошибка — разные состояния', () => {
  assert.match(dailySectionHTML({ days: 7, loading: true }), /Считаю файлы результатов/);
  assert.match(dailySectionHTML(null), /Не удалось загрузить динамику/);
});

// ── Период ────────────────────────────────────────────────────

test('dailyControlsHTML: четыре быстрых периода, подсвечен один', () => {
  globalThis._dailyRange = daysRange(7);
  const html = dailyControlsHTML();
  for (const label of ['Сегодня', '7 дн.', '14 дн.', '30 дн.']) {
    assert.ok(html.includes('>' + label + '</button>'), label);
  }
  assert.match(html, /class="dyn-range is-on" aria-pressed="true" onclick="setDailyRange\(7\)"/);
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 1, 'подсвечен только один сегмент');
  // «Сегодня» — это окно в один день: «за сутки» и «за сегодня» — одно и то же.
  assert.match(html, /onclick="setDailyRange\(1\)">Сегодня</);
  assert.match(html, /<input type="month" id="dyn-month"/);
});

test('dailyControlsHTML: месяц и свой диапазон снимают подсветку сегментов', () => {
  globalThis._dailyRange = { kind: 'month', days: 7, month: '2026-08', from: '', to: '' };
  let html = dailyControlsHTML();
  assert.equal((html.match(/aria-pressed="true"/g) || []).length, 0);
  assert.match(html, /value="2026-08"/);
  assert.ok(!/dyn-more is-on/.test(html), 'кнопка диапазона не активна');

  globalThis._dailyRange = { kind: 'custom', days: 7, month: '', from: '2026-01-01', to: '2026-02-01' };
  html = dailyControlsHTML();
  assert.match(html, /class="dyn-range dyn-more is-on"/);
  assert.ok(!html.includes('2026-01-01'), 'даты диапазона — в своём блоке, а не в шапке');
});

test('dailyCustomHTML: поля предзаполнены текущим периодом и скрыты по умолчанию', () => {
  globalThis._dailyRange = daysRange(7);
  globalThis._dailyPayload = payload();
  globalThis._dailyCustomOpen = false;
  let html = dailyCustomHTML();
  assert.match(html, /class="dyn-custom" id="dyn-custom" hidden/);
  assert.match(html, /id="dyn-from" class="dyn-date" value="2026-09-24"/);
  assert.match(html, /id="dyn-to" class="dyn-date" value="2026-09-30"/);
  assert.match(html, /onclick="applyDailyCustom\(\)"/);
  globalThis._dailyCustomOpen = true;
  html = dailyCustomHTML();
  assert.ok(!/id="dyn-custom" hidden/.test(html), 'развёрнутый блок не скрыт');
});

test('_dailyQuery: каждый режим периода — своей строкой запроса', () => {
  globalThis._dailyRange = daysRange(30);
  assert.equal(_dailyQuery(), 'days=30');
  globalThis._dailyRange = { kind: 'month', days: 7, month: '2026-08', from: '', to: '' };
  assert.equal(_dailyQuery(), 'month=2026-08');
  globalThis._dailyRange = { kind: 'custom', days: 7, month: '', from: '2026-08-01', to: '2026-08-31' };
  assert.equal(_dailyQuery(), 'from=2026-08-01&to=2026-08-31');
});

test('setDailyRange: переключает период и перезапрашивает сервер', async () => {
  globalThis._dailyRange = daysRange(7);
  fetches = [];
  globalThis.__dailyResponse = payload({ days: 14, series: [] });
  setDailyRange(14);
  assert.deepEqual(globalThis._dailyRange, daysRange(14));
  await new Promise(r => setImmediate(r));
  assert.deepEqual(fetches, ['/stats/daily?days=14']);
  assert.match(els['stats-daily'].innerHTML, /dyn-range is-on" aria-pressed="true" onclick="setDailyRange\(14\)"/);
});

test('setDailyRange: повторный выбор того же периода ничего не делает', () => {
  globalThis._dailyRange = daysRange(7);
  fetches = [];
  setDailyRange(7);
  assert.deepEqual(fetches, []);
});

test('setDailyMonth: месяц меняет запрос, очистка поля возвращает сегменты', async () => {
  globalThis._dailyRange = daysRange(7);
  fetches = [];
  globalThis.__dailyResponse = payload({ mode: 'month', days: 31,
    start: '2026-08-01', end: '2026-08-31', series: [] });
  setDailyMonth('2026-08');
  assert.deepEqual(globalThis._dailyRange,
    { kind: 'month', days: 7, month: '2026-08', from: '', to: '' });
  await new Promise(r => setImmediate(r));
  assert.deepEqual(fetches, ['/stats/daily?month=2026-08']);

  // Очистка поля не оставляет период без контрола: возвращаемся к сегментам.
  setDailyMonth('');
  assert.equal(globalThis._dailyRange.kind, 'days');
  assert.deepEqual(fetches, ['/stats/daily?month=2026-08', '/stats/daily?days=7']);
});

test('applyDailyCustom: берёт даты из полей, перепутанные — переставляет', async () => {
  globalThis._dailyRange = daysRange(7);
  els['dyn-from'] = mkEl('dyn-from');
  els['dyn-to'] = mkEl('dyn-to');
  els['dyn-from'].value = '2026-07-20';
  els['dyn-to'].value = '2026-07-30';
  fetches = [];
  globalThis.__dailyResponse = payload({ mode: 'range', days: 11,
    start: '2026-07-20', end: '2026-07-30', series: [] });
  applyDailyCustom();
  assert.deepEqual(globalThis._dailyRange,
    { kind: 'custom', days: 7, month: '', from: '2026-07-20', to: '2026-07-30' });
  assert.equal(globalThis._dailyCustomOpen, true, 'блок дат остаётся развёрнутым');
  await new Promise(r => setImmediate(r));
  assert.deepEqual(fetches, ['/stats/daily?from=2026-07-20&to=2026-07-30']);
});

test('applyDailyCustom: поля, заполненные наоборот, — просто период наизнанку', async () => {
  globalThis._dailyRange = daysRange(7);
  els['dyn-from'].value = '2026-07-30';
  els['dyn-to'].value = '2026-07-20';
  fetches = [];
  applyDailyCustom();
  await new Promise(r => setImmediate(r));
  assert.equal(globalThis._dailyRange.from, '2026-07-20');
  assert.equal(globalThis._dailyRange.to, '2026-07-30');
  assert.deepEqual(fetches, ['/stats/daily?from=2026-07-20&to=2026-07-30']);
});

test('applyDailyCustom: без обеих дат период не меняется', () => {
  globalThis._dailyRange = daysRange(7);
  els['dyn-from'].value = '';
  els['dyn-to'].value = '2026-07-30';
  fetches = [];
  applyDailyCustom();
  assert.deepEqual(fetches, []);
  assert.deepEqual(globalThis._dailyRange, daysRange(7));
});

test('toggleDailyCustom: разворачивает и сворачивает блок дат', () => {
  const panel = mkEl('dyn-custom');
  panel.hidden = true;
  els['dyn-custom'] = panel;
  globalThis._dailyCustomOpen = false;
  toggleDailyCustom();
  assert.equal(globalThis._dailyCustomOpen, true);
  assert.equal(panel.hidden, false);
  toggleDailyCustom();
  assert.equal(globalThis._dailyCustomOpen, false);
  assert.equal(panel.hidden, true);
});

test('renderDailyDynamics: пишет в контейнер страницы', () => {
  els['stats-daily'].innerHTML = '';
  globalThis._dailyPayload = null;
  renderDailyDynamics(payload());
  assert.match(els['stats-daily'].innerHTML, /dyn-chart/);
  assert.match(els['stats-daily'].innerHTML, /Динамика по дням/);
  assert.match(els['stats-daily'].innerHTML, /dyn-custom/);
  assert.ok(!els['stats-daily'].innerHTML.includes('dyn-tip'), 'подсказки в разметке графика нет');
  assert.equal(globalThis._dailyPayload.mode, 'days', 'ответ запоминается для полей периода');
});

// ── Подсказка при наведении ───────────────────────────────────

const COL_ATTRS = { 'data-wd': 'сб', 'data-dm': '26.09', 'data-found': '100',
                    'data-review': '3', 'data-files': '2', 'data-pct': '3' };

function mkCol(rect, attrs = COL_ATTRS) {
  const col = mkEl('col');
  col._rect = rect;
  col._attrs = Object.assign({}, attrs);
  return col;
}

let tipNode = null;
function freshTip() {
  tipNode = mkEl('created');
  tipNode._rect = { left: 0, top: 0, width: 160, height: 56 };
  globalThis.document.createElement = () => tipNode;
  globalThis._dailyTip = null;
  globalThis._dailyTipCol = null;
  globalThis._dailyTipSize = null;
  return tipNode;
}

test('подсказка: разбор дня, а не только числа', () => {
  const tip = freshTip();
  _showDailyTip(mkCol({ left: 300, top: 400, width: 40, height: 158 }));
  assert.match(tip.innerHTML, /сб, 26\.09/);
  assert.match(tip.innerHTML, /Найдено<b>100<\/b>/);
  assert.match(tip.innerHTML, /Просмотрено<b>3<\/b>/);
  assert.match(tip.innerHTML, /2 файла · разобрано 3%/);
  assert.ok(tip._cls.has('is-on'), 'подсказка показана');
  _hideDailyTip();
  assert.equal(tip._cls.has('is-on'), false, 'и скрывается при уходе курсора');
});

test('подсказка: живёт в <body>, а не внутри графика', () => {
  const tip = freshTip();
  _showDailyTip(mkCol({ left: 300, top: 400, width: 40, height: 158 }));
  assert.equal(tip.className, 'dyn-tip');
  assert.equal(tip.getAttribute('aria-hidden'), 'true');
  assert.ok(appended.includes(tip), 'карточка вне графика — её не режет панель');
});

test('подсказка: над столбцом по центру и целиком в окне', () => {
  const tip = freshTip();
  _showDailyTip(mkCol({ left: 300, top: 400, width: 40, height: 158 }));
  assert.equal(tip.style.left, '240px');   // 300 + 40/2 - 160/2
  assert.equal(tip.style.top, '336px');    // 400 - 8 - 56
  assert.equal(tip._cls.has('is-below'), false);

  // У правого края карточка целиком внутри окна: 1200 - 160 - 4.
  _showDailyTip(mkCol({ left: 1190, top: 400, width: 40, height: 158 }));
  assert.equal(tip.style.left, '1036px');
});

test('подсказка: у верха панели уходит ПОД столбец, а не обрезается', () => {
  const tip = freshTip();
  // Панель начинается на 100px, а над столбцом всего 120-8-56 = 56px —
  // именно этот случай обрезался за верхом панели.
  _showDailyTip(mkCol({ left: 300, top: 120, width: 40, height: 158 }));
  assert.equal(tip._cls.has('is-below'), true);
  assert.equal(tip.style.top, '286px');    // 120 + 158 + 8
  // Места сверху достаточно — подсказка возвращается наверх.
  _showDailyTip(mkCol({ left: 300, top: 300, width: 40, height: 158 }));
  assert.equal(tip._cls.has('is-below'), false);
});

test('подсказка: не вылезает за нижний край окна', () => {
  const tip = freshTip();
  const vh = window.innerHeight;
  window.innerHeight = 300;
  _showDailyTip(mkCol({ left: 300, top: 320, width: 40, height: 158 }));
  assert.equal(tip.style.top, '240px');    // 300 - 56 - 4
  window.innerHeight = vh;
});

test('подсказка: панель ниже экрана не утаскивает карточку за край', () => {
  // Мобильная раскладка может поставить панель статистики ниже окна целиком.
  // Считая границей её верх, подсказка оказалась бы вообще за экраном.
  const tip = freshTip();
  const savedPanel = els['p-stats']._rect;
  const savedVh = window.innerHeight;
  els['p-stats']._rect = { left: 0, top: 1450, width: 1200, height: 1000 };
  window.innerHeight = 780;
  _showDailyTip(mkCol({ left: 300, top: 1625, width: 40, height: 158 }));
  assert.ok(parseFloat(tip.style.top) + 56 <= 780, 'карточка целиком в окне: ' + tip.style.top);
  els['p-stats']._rect = savedPanel;
  window.innerHeight = savedVh;
});

test('подсказка: позиция пересчитывается на каждом движении, а не при смене дня', () => {
  const tip = freshTip();
  const col = mkCol({ left: 300, top: 400, width: 40, height: 158 });
  _showDailyTip(col);
  assert.equal(tip.style.left, '240px');
  // Тот же столбец после прокрутки или смены масштаба: курсор не двигался,
  // но подсказка обязана остаться над ним, а не в старой точке.
  col._rect = { left: 600, top: 400, width: 40, height: 158 };
  _showDailyTip(col);
  assert.equal(tip.style.left, '540px');
  assert.match(tip.innerHTML, /сб, 26\.09/, 'содержимое не перерисовывалось зря');
});

// ── Почасовой «Сегодня» ────────────────────────────────────

const hoursPayload = over => Object.assign(
  { mode: 'days', days: 1, start: '2026-09-30', end: '2026-09-30', truncated: false,
    hours: Array.from({ length: 24 }, (_, h) => ({ hour: h, found: 0, files: 0 })),
    series: [{ date: '2026-09-30', found: 0, reviewed: 0, files: 0 }],
    totals: { found: 0, reviewed: 0, undated: 0 } }, over);

test('dailyQuery: «Сегодня» просит почасовой разворот', () => {
  globalThis._dailyRange = daysRange(1);
  assert.equal(_dailyQuery(), 'days=1&hours=1');
  globalThis._dailyRange = daysRange(7);
  assert.equal(_dailyQuery(), 'days=7');
});

test('dailyQuery: диапазон из одного дня тоже почасовой', () => {
  globalThis._dailyRange = { kind: 'custom', days: 7, month: '', from: '2026-09-30', to: '2026-09-30' };
  assert.equal(_dailyQuery(), 'from=2026-09-30&to=2026-09-30&hours=1');
  globalThis._dailyRange = { kind: 'custom', days: 7, month: '', from: '2026-09-29', to: '2026-09-30' };
  assert.equal(_dailyQuery(), 'from=2026-09-29&to=2026-09-30');
  globalThis._dailyRange = daysRange(7);
});

test('часы: 14:01 и 14:50 попадают в одну колонку «14»', () => {
  const hours = Array.from({ length: 24 }, (_, h) => ({ hour: h, found: h === 14 ? 45 : 0, files: h === 14 ? 2 : 0 }));
  const html = dailySectionHTML(hoursPayload({
    hours,
    series: [{ date: '2026-09-30', found: 45, reviewed: 0, files: 2 }],
    totals: { found: 45, reviewed: 0, undated: 0 },
  }));
  const cols = columnsOf(html);
  assert.ok(cols.length >= 2 && cols.length <= 24, 'окно от первого до последнего часа с данными: ' + cols.length);
  assert.match(html, /data-dm="14:00"/, 'час подписан для подсказки');
  assert.match(html, /data-found="45"/);
  assert.match(html, /по часам/, 'период помечен как почасовой');
  assert.doesNotMatch(html, /class="dyn-facts/, 'факты «в среднем в день» к часам не относятся');
});

test('часы: пустой день без файлов с часом — обычный дневной столбец', () => {
  const html = dailySectionHTML(hoursPayload({
    hours: null,
    series: [{ date: '2026-09-30', found: 7, reviewed: 0, files: 1 }],
    totals: { found: 7, reviewed: 0, undated: 0 },
  }));
  assert.match(html, /class="dyn-cols is-single/, 'одна колонка ограничена по ширине');
  assert.doesNotMatch(html, /по часам/);
});

test('часы: дневной столбец с нулевыми часами не превращается в пустые сутки', () => {
  // Файлы с часом есть, но записей в них 0: дневной столбец честнее.
  const html = dailySectionHTML(hoursPayload({
    series: [{ date: '2026-09-30', found: 3, reviewed: 0, files: 1 }],
    totals: { found: 3, reviewed: 0, undated: 0 },
  }));
  assert.match(html, /class="dyn-cols is-single/);
});

test('часы: колонка часа несёт данные для подсказки', () => {
  const hours = Array.from({ length: 24 }, (_, h) => ({ hour: h, found: h === 21 ? 192 : 0, files: h === 21 ? 4 : 0 }));
  const html = dailySectionHTML(hoursPayload({ hours, totals: { found: 192, reviewed: 0, undated: 0 },
    series: [{ date: '2026-09-30', found: 192, reviewed: 0, files: 4 }] }));
  const col = columnsOf(html).find(c => c.includes('data-found="192"'));
  assert.ok(col, 'колонка с данными существует');
  assert.match(col, /data-wd="Час"/);
  assert.match(col, /data-dm="21:00"/);
  assert.match(col, /data-files="4"/);
});
