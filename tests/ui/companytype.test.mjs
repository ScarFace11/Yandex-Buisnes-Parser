// UI unit tests for «🎯 Тип компании» — «Только одиночки» / «Только новые»
// (offline, Node).
//
// The filter itself runs on the server (stage 2), but the hint «сколько
// подойдёт» is counted here, before «Применить фильтры заново» is pressed.
// Two rules matter for it:
//   1. it costs a request to the raw data, so it is debounced (500 ms) and only
//      the LAST answer may reach the user — an older reply arriving late would
//      show a number for a setting the user has already changed;
//   2. the number must mean something: when the source did not hand out
//      «дата добавления» (Яндекс вообще её не отдаёт), the counter has to say
//      so instead of pretending nothing matched.
//
// Run with: node --test tests/ui/companytype.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

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

// Slice `const NAME = <value>;` so the tests never duplicate the period list
// that processing.COMPANY_TYPE_MONTHS also enforces on the server.
function grabConstValue(name) {
  const prefix = 'const ' + name + ' = ';
  const i = src.indexOf(prefix);
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  let k = i + prefix.length;
  const open = src[k];
  let end;
  if (open === '{' || open === '[') {
    const close = open === '{' ? '}' : ']';
    let depth = 0;
    for (; k < src.length; k++) {
      if (src[k] === open) depth++;
      else if (src[k] === close) { depth--; if (!depth) break; }
    }
    end = k + 1;
  } else {
    end = src.indexOf(';', k);
  }
  return src.slice(i + prefix.length, end);
}

for (const name of ['COMPANY_TYPE_PREVIEW_MS', 'COMPANY_TYPE_DEFAULT_MONTHS',
                    'COMPANY_TYPE_PERIODS']) {
  (0, eval)('globalThis.' + name + ' = ' + grabConstValue(name) + ';');
}

// ── DOM stub ──────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  return {
    id, value: '', textContent: '', innerHTML: '', disabled: false, checked: false,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    closest: () => mkEl('chk-' + id),
    querySelectorAll: () => [],
  };
}
const els = {};
for (const id of ['f-only-single', 'f-only-new', 'f-new-months',
                  'company-type-new-row', 'company-type-count']) {
  els[id] = mkEl(id);
}
els['f-new-months'].value = '6';

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  createElement: () => mkEl('option'),
  body: mkEl('body'),
};

// ── Timers / network stubs ────────────────────────────────────
const timers = new Map();
let nextTimerId = 1;
const scheduledMs = [];
globalThis.setTimeout = (fn, ms) => {
  const id = nextTimerId++;
  timers.set(id, fn);
  scheduledMs.push(ms);
  return id;
};
globalThis.clearTimeout = id => { timers.delete(id); };
function flushTimers() {
  const pending = [...timers.values()];
  timers.clear();
  pending.forEach(fn => fn());
}
function pendingTimers() { return timers.size; }

const requests = [];
let deferred = [];          // ручные резолверы: порядок ответов задаёт тест
let replies = [];
globalThis.fetch = (url, opts) => {
  requests.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  return new Promise(resolve => {
    deferred.push(() => resolve({ json: () => Promise.resolve(replies.shift()) }));
  });
};
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
// Отвечаем СВЕЖЕМУ запросу (последнему в очереди): так воспроизводится
// реальный гонок — старый запрос отвечает уже после нового.
async function answer(reply) {
  replies.push(reply);
  const next = deferred.pop();
  assert.ok(next, 'нет запроса в полёте');
  next();
  await settle();
}

globalThis._pluralRu = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

// Открытие аккордеона считается лениво: счётчики не ходят в сеть при загрузке
// страницы, только когда раздел реально открыли.
globalThis.scheduleBlacklistPreview = () => {};

(0, eval)([
  grab('toggleAccordion'),
  grab('onlySingleChecked'),
  grab('newMonthsValue'),
  grab('newMonthsPeriod'),
  grab('companyTypeOn'),
  grab('syncCompanyTypeUi'),
  grab('onCompanyTypeChange'),
  grab('updateCompanyTypeCount'),
  grab('scheduleCompanyTypePreview'),
  grab('previewCompanyType'),
  grab('companyTypeCountHTML'),
].join('\n'));

function reset({ single = false, onlyNew = false, period = '6' } = {}) {
  globalThis._ctPreviewTimer = null;
  globalThis._ctPreviewSeq = 0;
  els['f-only-single'].checked = single;
  els['f-only-new'].checked = onlyNew;
  els['f-new-months'].value = period;
  els['company-type-count'].innerHTML = '';
  els['company-type-new-row']._classes = undefined;
  timers.clear();
  scheduledMs.length = 0;
  requests.length = 0;
  deferred = [];
  replies = [];
  globalThis.syncCompanyTypeUi();
}

const count = () => els['company-type-count'].innerHTML;

// ── Значения фильтров ─────────────────────────────────────────

test('оба фильтра выключены: ни запроса, ни счёта', () => {
  reset();
  assert.equal(globalThis.companyTypeOn(), false);
  globalThis.scheduleCompanyTypePreview();
  assert.equal(requests.length, 0, 'сеть молчит');
  assert.equal(pendingTimers(), 0, 'таймер не заводится');
  assert.match(count(), /Отметьте фильтры/);
});

test('payload: одиночки без периода и период без одиночек', async () => {
  reset({ single: true });
  assert.equal(globalThis.newMonthsValue(), null, 'без чекбокса период не едет');
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  assert.deepEqual(requests[0].body, { only_single_branch: true, only_new_months: null });

  reset({ onlyNew: true, period: '12' });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  assert.deepEqual(requests[0].body, { only_single_branch: false, only_new_months: 12 });
});

test('селект периода выключен, пока не отмечен его чекбокс', () => {
  reset();
  assert.equal(els['f-new-months'].disabled, true, 'выключенный фильтр не редактируется');
  assert.equal(els['company-type-new-row'].classList.contains('on'), false);

  els['f-only-new'].checked = true;
  globalThis.syncCompanyTypeUi();
  assert.equal(els['f-new-months'].disabled, false);
  assert.equal(els['company-type-new-row'].classList.contains('on'), true);

  els['f-only-new'].checked = false;
  globalThis.syncCompanyTypeUi();
  assert.equal(els['f-new-months'].disabled, true);
  assert.equal(els['company-type-new-row'].classList.contains('on'), false);
});

test('период помнится, даже когда фильтр выключен (для пресета)', () => {
  reset({ onlyNew: false, period: '24' });
  assert.equal(globalThis.newMonthsValue(), null);
  assert.equal(globalThis.newMonthsPeriod(), '24');
});

test('неизвестный период из DOM не уезжает на сервер', () => {
  reset({ onlyNew: true, period: '99' });
  assert.equal(globalThis.newMonthsValue(), 6, 'дефолт вместо произвольного числа');
});

// ── Дебаунс и устаревшие ответы ───────────────────────────────

test('серия правок — один запрос через 500 мс', () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  globalThis.scheduleCompanyTypePreview();
  globalThis.scheduleCompanyTypePreview();
  assert.equal(pendingTimers(), 1, 'таймер перевзводится, а не копится');
  assert.deepEqual(scheduledMs.slice(-1), [500]);
  flushTimers();
  assert.equal(requests.length, 1, 'три правки — один запрос');
});

test('ответ на устаревшую настройку не перетирает свежий счётчик', async () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();                                   // запрос №1
  els['f-only-new'].checked = true;                // пользователь включил второй фильтр
  globalThis.scheduleCompanyTypePreview();
  flushTimers();                                   // запрос №2

  assert.equal(requests.length, 2);
  // Второй (свежий) запрос отвечает первым, затем приходит опоздавший первый.
  assert.deepEqual(requests[1].body, { only_single_branch: true, only_new_months: 6 });
  await answer({ ok: true, total: 100, single: 10, new: 20, both: 5, with_date: 100, months: 6 });
  const fresh = count();
  await answer({ ok: true, total: 100, single: 90, new: 90, both: 90, with_date: 100, months: 6 });
  assert.equal(count(), fresh, 'опоздавший ответ проигнорирован');
  assert.match(count(), /Подойдёт <b>5<\/b>/);
});

// ── Тексты счётчика ───────────────────────────────────────────

test('оба фильтра: подойдёт пересечение, разбивка и охват дат', async () => {
  reset({ single: true, onlyNew: true, period: '6' });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 500, single: 213, new: 147, both: 22,
                 with_date: 260, months: 6 });
  assert.match(count(), /Подойдёт <b>22<\/b> из 500 компаний/);
  assert.match(count(), /одиночек <b>213<\/b>/);
  assert.match(count(), /новых за 6 мес — <b>147<\/b>/);
  assert.match(count(), /обоим условиям — <b>22<\/b>/);
  assert.match(count(), /у 240 компаний даты нет — они остаются в отчёте/);
});

test('только одиночки: в счёте нет строки про новых', async () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 500, single: 213, new: 147, both: 22,
                 with_date: 500, months: 6 });
  assert.match(count(), /Подойдёт <b>213<\/b> из 500/);
  assert.doesNotMatch(count(), /новых за/);
});

test('только новые: подойдёт число новых за выбранный период', async () => {
  reset({ onlyNew: true, period: '1' });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 500, single: 213, new: 47, both: 12,
                 with_date: 500, months: 1 });
  assert.match(count(), /Подойдёт <b>47<\/b> из 500/);
  assert.match(count(), /новых за 1 мес — <b>47<\/b>/);
});

test('дат нет вовсе — счётчик объясняет, а не молчит', async () => {
  reset({ onlyNew: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 500, single: 213, new: 500, both: 213,
                 with_date: 0, months: 6 });
  assert.match(count(), /нет дат добавления/);
  assert.doesNotMatch(count(), /у 500 компаний даты нет/, 'не дублируем одну и ту же мысль');
});

test('большая выгрузка показывается приблизительно', async () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 12345, single: 1000, new: 0, both: 0,
                 with_date: 12345, months: null });
  assert.match(count(), /из ~12000 компаний/);
});

test('пустые сырые данные — честный ответ вместо нуля', async () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: true, total: 0, single: 0, new: 0, both: 0, with_date: 0, months: null });
  assert.match(count(), /Нет сырых данных/);
});

test('ошибка считает себя ошибкой, а не «0 компаний»', async () => {
  reset({ single: true });
  globalThis.scheduleCompanyTypePreview();
  flushTimers();
  await answer({ ok: false, error: 'boom' });
  assert.match(count(), /Не удалось посчитать компании/);
});

test('открытие раздела «Фильтрация результата» считает и «тип компании»', () => {
  reset({ single: true });
  const sec = {
    id: 'acc-filters',
    classList: { toggle: () => true },
  };
  const hdr = { closest: () => sec, setAttribute: () => {} };
  globalThis.toggleAccordion(hdr);
  assert.equal(pendingTimers(), 1, 'открытие раздела планирует пересчёт');
  flushTimers();
  assert.equal(requests.length, 1);
});

test('отметка чекбокса сразу пересчитывает, выключение — сбрасывает подпись', () => {
  reset();
  els['f-only-single'].checked = true;
  globalThis.onCompanyTypeChange();
  assert.equal(pendingTimers(), 1, 'включение фильтра планирует пересчёт');
  flushTimers();
  assert.equal(requests.length, 1);

  els['f-only-single'].checked = false;
  globalThis.onCompanyTypeChange();
  assert.match(count(), /Отметьте фильтры/);
  assert.equal(pendingTimers(), 0, 'выключение не ходит в сеть');
});
