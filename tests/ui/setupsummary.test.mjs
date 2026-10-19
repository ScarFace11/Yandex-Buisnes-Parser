// UI unit tests: «живая сводка настройки» (верх боковой панели) — static/js/12-setup-summary.js.
//
// Сводка — единственное место, где сразу видно, что именно будет запущено:
// запрос, города, тип организаций, соцсети и форматы. Тесты держат три вещи:
//   • значения и «чего не хватает» (чип без города/запроса/формата — warn);
//   • разметку чипов: у каждого есть data-setup-jump в свой раздел;
//   • прыжок по чипу действительно раскрывает раздел и ставит фокус в поле.
//
// Run with: node --test "tests/ui/setupsummary.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readAppSrc } from './_src.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readAppSrc(root);

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

function grabConst(name) {
  const i = src.indexOf('const ' + name + ' = {');
  assert.ok(i >= 0, 'const not found: ' + name);
  const end = src.indexOf('};', i);
  return src.slice(i, end + 2);
}

// Простая константа (число/строка): до первой «;» вне тела функции.
function grabScalarConst(name) {
  const i = src.indexOf('const ' + name + ' = ');
  assert.ok(i >= 0, 'const not found: ' + name);
  const end = src.indexOf(';', i);
  return src.slice(i, end + 1);
}

// ── DOM stub ─────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const attrs = {};
  return {
    id, value: '', textContent: '', innerHTML: '', hidden: false,
    dataset: {}, style: {},
    _classes: classes, _attrs: attrs, _focused: false,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute(k, v) { attrs[k] = v; },
    getAttribute(k) { return attrs[k]; },
    scrollIntoView() { this._scrolled = true; },
    focus() { this._focused = true; },
  };
}

const els = {
  'f-queries': mkEl('f-queries'),
  'f-excel': mkEl('f-excel'), 'f-json': mkEl('f-json'),
  'f-csv': mkEl('f-csv'), 'f-map': mkEl('f-map'),
  'f-city-input': mkEl('f-city-input'),
  'setup-summary': mkEl('setup-summary'),
  'acc-formats': mkEl('acc-formats'),
  // Параметры «Глубины поиска»: из них считается оценка объёма.
  'f-pages': mkEl('f-pages'), 'f-grad': mkEl('f-grad'),
  'f-gstep': mkEl('f-gstep'), 'f-max-candidates': mkEl('f-max-candidates'),
};
els['f-queries'].value = 'кафе';
els['f-excel'].checked = true;
els['f-json'].checked = false;
els['f-csv'].checked = false;
els['f-map'].checked = false;
els['f-pages'].value = '1';
els['f-grad'].value = '20';
els['f-gstep'].value = '5';
els['f-max-candidates'].value = '200';

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
globalThis.requestAnimationFrame = () => 0;
globalThis.escapeHtml = s => String(s);
globalThis.selectedCities = [];
globalThis.parseMode = 'without_website';
globalThis.socialMode = 'all';
globalThis._gridMode = 'whole';
globalThis.toggleAccordion = hdr => hdr.closest('.acc')._classes.add('open');

// const-объявления из исходника достаются как свойства globalThis: в
// косвенном eval `const` создаёт лексическую переменную модуля, а не свойство
// глобального объекта, и со стороны теста её не видно.
const sliced = [
  grabConst('SETUP_SUM_TARGETS').replace(/^const /, 'globalThis.SETUP_SUM_TARGETS = '),
  grabScalarConst('SETUP_CARDS_PER_PAGE').replace(/^const /, 'globalThis.SETUP_CARDS_PER_PAGE = '),
  grab('gridCellsEstimate'),
  grab('_setupQueries'),
  grab('_setupCities'),
  grab('_setupFormats'),
  grab('setupVolumeEstimate'),
  grab('_setupNum'),
  grab('_setupPlural'),
  grab('buildSetupSummary'),
  grab('_setupJump'),
];
(0, eval)(sliced.join('\n'));

const byKey = () => Object.fromEntries(
  globalThis.buildSetupSummary().map(it => [it.key, it]));

// ── 1. Значения ────────────────────────────────────────────────
test('сводка показывает запрос, города, объём, тип, соцсети и форматы', () => {
  globalThis.selectedCities = ['Уфа'];
  globalThis.parseMode = 'all';
  globalThis.socialMode = 'with_socials';
  globalThis._gridMode = 'whole';
  els['f-json'].checked = true;
  const chips = byKey();

  assert.deepEqual(Object.keys(chips),
    ['queries', 'cities', 'volume', 'type', 'socials', 'formats']);
  assert.equal(chips.queries.value, 'кафе');
  assert.equal(chips.cities.value, 'Уфа');
  assert.equal(chips.type.value, 'все организации');
  assert.equal(chips.socials.value, 'только с соцсетями');
  assert.equal(chips.formats.value, 'Excel, JSON');
  for (const key of Object.keys(chips)) {
    assert.equal(chips[key].tone, 'ok', key + ': всё заполнено → не предупреждение');
  }
});

test('нехватка данных отмечается как предупреждение', () => {
  globalThis.selectedCities = [];
  els['f-queries'].value = '   \n  ';
  els['f-excel'].checked = false;
  els['f-json'].checked = false;
  const chips = byKey();

  assert.equal(chips.queries.value, 'не задано');
  assert.equal(chips.queries.tone, 'warn');
  assert.equal(chips.cities.value, 'не выбрано');
  assert.equal(chips.cities.tone, 'warn');
  assert.equal(chips.formats.value, 'не выбрано');
  assert.equal(chips.formats.tone, 'warn');
  // Тип и соцсети всегда имеют значение по умолчанию — они не «пустые».
  assert.equal(chips.type.tone, 'ok');
  assert.equal(chips.socials.tone, 'ok');
});

test('список запросов и длинный список городов сворачиваются в «+N»', () => {
  els['f-queries'].value = 'кафе\nстоматология\nбар';
  globalThis.selectedCities = ['Москва', 'Уфа', 'Казань', 'Сочи'];
  const chips = byKey();

  assert.equal(chips.queries.value, 'кафе +2');
  assert.equal(chips.cities.value, 'Москва, Уфа +2');
});

// ── 1b. Оценка объёма ──────────────────────────────────────────
test('объём в режиме «весь город»: одна точка на город', () => {
  globalThis._gridMode = 'whole';
  globalThis.selectedCities = ['Уфа', 'Казань'];
  els['f-queries'].value = 'кафе\nбар';
  els['f-pages'].value = '2';
  els['f-max-candidates'].value = '10000';

  const vol = globalThis.setupVolumeEstimate();
  assert.equal(vol.cells, 1, 'автоматика ищет с одной точки на город');
  // 2 города × 2 запроса × 1 точка × 2 страницы = 8 страниц выдачи
  assert.equal(vol.searchPages, 8);
  assert.equal(vol.cards, 8 * 25);
  assert.equal(vol.capped, false);
  assert.equal(byKey().volume.value, '≈200 организаций · 8 стр.');
  assert.match(byKey().volume.detail, /8 страниц выдачи/, 'число и слово должны согласоваться');
});

test('объём в ручной сетке растёт вместе с числом точек', () => {
  globalThis._gridMode = 'manual';
  globalThis.selectedCities = ['Москва'];
  els['f-queries'].value = 'кафе';
  els['f-pages'].value = '1';
  els['f-grad'].value = '20';
  els['f-gstep'].value = '5';
  els['f-max-candidates'].value = '10000';

  const vol = globalThis.setupVolumeEstimate();
  assert.equal(vol.cells, globalThis.gridCellsEstimate(20, 5));
  assert.ok(vol.cells > 1, 'сетка должна давать больше одной точки');
  assert.equal(vol.searchPages, vol.cells);
  assert.equal(byKey().volume.value, `≈${(vol.cells * 25).toLocaleString('ru-RU')} организаций · ${vol.cells} стр.`);
});

test('объём не превышает потолок «Макс. организаций»', () => {
  globalThis._gridMode = 'manual';
  globalThis.selectedCities = ['Москва', 'Питер', 'Казань'];
  els['f-queries'].value = 'кафе';
  els['f-pages'].value = '5';
  els['f-grad'].value = '20';
  els['f-gstep'].value = '2';
  els['f-max-candidates'].value = '200';

  const vol = globalThis.setupVolumeEstimate();
  assert.equal(vol.cards, 200, 'потолок срабатывает раньше страниц');
  assert.equal(vol.capped, true);
  const chip = byKey().volume;
  assert.match(chip.value, /^≈200 организаций/);
  assert.match(chip.detail, /Потолок «Макс. организаций» \(200\) сработает раньше/);
  // В подсказке видна вся арифметика, а не только итог.
  assert.match(chip.detail, /Точек поиска на город: \d+/);
  assert.match(chip.detail, /Страниц на точку: 5/);
});

test('без города и запроса объём не считается', () => {
  globalThis.selectedCities = [];
  els['f-queries'].value = '';
  const chip = byKey().volume;
  assert.equal(chip.value, '—');
  assert.match(chip.detail, /Выберите город и запрос/);
});

test('число и существительное согласуются', () => {
  // «1 страница», «2 страницы», «5 страниц» — иначе в подсказке было бы
  // «2 страниц выдачи».
  const p = globalThis._setupPlural;
  assert.equal(p(1, 'страница', 'страницы', 'страниц'), 'страница');
  assert.equal(p(2, 'страница', 'страницы', 'страниц'), 'страницы');
  assert.equal(p(5, 'страница', 'страницы', 'страниц'), 'страниц');
  assert.equal(p(11, 'страница', 'страницы', 'страниц'), 'страниц');
  assert.equal(p(21, 'страница', 'страницы', 'страниц'), 'страница');
  assert.equal(p(112, 'страница', 'страницы', 'страниц'), 'страниц');
});

test('оценка точек — одна формула с подсказкой «Глубины поиска»', () => {
  // Если формулу поменяют в одном месте, числа в сводке и в подсказке
  // разойдутся и пользователь увидит два разных прогноза одного и того же.
  const src = readAppSrc(root);
  assert.match(src, /function gridCellsEstimate\(/);
  assert.match(src, /const cells = gridCellsEstimate\(r, s\)/,
    'подсказка слайдеров обязана считать той же функцией');
});

// ── 2. Разметка чипов ─────────────────────────────────────────
test('каждый чип — кнопка со своим разделом и пометкой нехватки', () => {
  // Состояние формы задаётся явно: тесты не должны зависеть от порядка.
  els['f-queries'].value = '';
  els['f-excel'].checked = false;
  globalThis.selectedCities = [];
  const html = globalThis.buildSetupSummary()
    .map(it => `<i data-setup-jump="${globalThis.SETUP_SUM_TARGETS[it.key]}"`
      + ` data-setup-key="${it.key}" class="${it.tone === 'warn' ? 'is-missing' : ''}"></i>`)
    .join('');
  assert.match(html, /data-setup-key="queries"[^>]*/);
  assert.match(html, /data-setup-jump="acc-basic"[^>]*data-setup-key="queries"/);
  assert.match(html, /data-setup-jump="acc-filters"[^>]*data-setup-key="type"/);
  assert.match(html, /data-setup-jump="acc-formats"[^>]*data-setup-key="formats"/);
  assert.match(html, /data-setup-jump="acc-tech"[^>]*data-setup-key="volume"/,
    'объём ведёт к «Глубине поиска»');
  // Запросы, города и форматы пусты (см. предыдущий тест) → все три warn.
  assert.equal((html.match(/is-missing/g) || []).length, 3);
});

// ── 3. Прыжок к разделу ───────────────────────────────────────
test('чип раскрывает свёрнутый раздел, подкручивает его и ставит фокус', () => {
  const sec = els['acc-formats'];
  sec._classes.clear();
  const hdr = { closest: () => sec };
  sec.querySelector = () => hdr;
  els['f-excel']._focused = false;

  globalThis._setupJump('acc-formats', 'formats');

  assert.equal(sec._classes.has('open'), true, 'раздел раскрыт');
  assert.equal(sec._scrolled, true, 'раздел подкручен в видимую область');
  assert.equal(els['f-excel']._focused, true, 'фокус ушёл в поле формата');
});
