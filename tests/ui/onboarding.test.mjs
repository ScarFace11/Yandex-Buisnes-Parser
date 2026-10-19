// UI unit tests: шаги «Как это работает» — static/js/09-ui-extras.js.
//
// Три шага на пустом экране раньше были картинками с тенью при наведении:
// клик по ним ничего не делал. Теперь каждый делает то, о чём говорит —
// ведёт к полю, запускает поиск, открывает результаты, — а если запустить
// пока нельзя, объясняет, чего не хватает.
//
// Run with: node --test "tests/ui/onboarding.test.mjs"
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

function mkEl(id) {
  const classes = new Set();
  return {
    id, value: '', _focused: false, _clicked: 0, _scrolled: false,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
    querySelector: () => null,
    scrollIntoView() { this._scrolled = true; },
    focus() { this._focused = true; },
    click() { this._clicked++; },
  };
}

const els = {
  'f-queries': mkEl('f-queries'),
  'f-city-input': mkEl('f-city-input'),
  'btn-run': mkEl('btn-run'),
  'acc-basic': mkEl('acc-basic'),
};
els['f-queries'].value = 'кафе';

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
globalThis.setTimeout = fn => { fn(); return 0; };
globalThis.showToast = (msg, type) => { globalThis.__toasts.push([msg, type]); };
globalThis.isRunActive = () => globalThis.__runActive;
globalThis.allResults = [];
globalThis.toggleAccordion = () => { globalThis.__accordionToggled = true; };
globalThis.showTab = name => { globalThis.__tab = name; };

(0, eval)(grab('_onboardingFocus') + '\n' + grab('onboardingStep'));

function reset({ queries = 'кафе', cities = [], runActive = false, results = [] } = {}) {
  els['f-queries'].value = queries;
  els['f-queries']._focused = false;
  els['f-city-input']._focused = false;
  els['btn-run']._clicked = 0;
  els['acc-basic']._classes.clear();
  els['acc-basic']._classes.add('open');
  els['acc-basic'].querySelector = () => null;
  globalThis.__toasts = [];
  globalThis.__runActive = runActive;
  globalThis.__tab = null;
  globalThis.__accordionToggled = false;
  globalThis.selectedCities = cities;
  globalThis.allResults = results;
}

// ── Шаг 01: ведёт к незаполненному полю ───────────────────────
test('шаг 1 ставит курсор в пустое поле запроса', () => {
  reset({ queries: '' });
  globalThis.onboardingStep(1);
  assert.equal(els['f-queries']._focused, true);
  assert.equal(els['f-city-input']._focused, false);
});

test('шаг 1 при заполненном запросе ведёт к городу', () => {
  reset({ queries: 'кафе' });
  globalThis.onboardingStep(1);
  assert.equal(els['f-city-input']._focused, true);
});

test('шаг 1 раскрывает свёрнутый раздел «Основные параметры»', () => {
  reset({ queries: 'кафе' });
  els['acc-basic']._classes.clear();                 // раздел свёрнут
  els['acc-basic'].querySelector = () => ({});
  globalThis.onboardingStep(1);
  assert.equal(globalThis.__accordionToggled, true, 'свёрнутый раздел не раскрылся');
});

// ── Шаг 02: запускает поиск или объясняет, чего не хватает ────
test('шаг 2 без запроса объясняет и ведёт к запросу', () => {
  reset({ queries: '' });
  globalThis.onboardingStep(2);
  assert.equal(els['btn-run']._clicked, 0, 'без запроса запускать нечего');
  assert.equal(globalThis.__toasts.length, 1);
  assert.equal(globalThis.__toasts[0][1], 'error');
  assert.match(globalThis.__toasts[0][0], /кого искать/i);
  assert.equal(els['f-queries']._focused, true);
});

test('шаг 2 без города объясняет и ведёт к выбору города', () => {
  reset({ queries: 'кафе', cities: [] });
  globalThis.onboardingStep(2);
  assert.equal(els['btn-run']._clicked, 0);
  assert.match(globalThis.__toasts[0][0], /город/i);
  assert.equal(els['f-city-input']._focused, true);
});

test('шаг 2 с готовыми данными нажимает «Найти компании»', () => {
  reset({ queries: 'кафе', cities: ['Уфа'] });
  globalThis.onboardingStep(2);
  assert.equal(els['btn-run']._clicked, 1);
  assert.equal(globalThis.__toasts.length, 0, 'нечего объяснять — всё заполнено');
});

test('шаг 2 во время прогона не запускает второй поиск', () => {
  reset({ queries: 'кафе', cities: ['Уфа'], runActive: true });
  globalThis.onboardingStep(2);
  assert.equal(els['btn-run']._clicked, 0);
  assert.match(globalThis.__toasts[0][0], /уже идёт/i);
});

// ── Шаг 03: открывает результаты ──────────────────────────────
test('шаг 3 открывает таблицу и говорит, если пока пусто', () => {
  reset({ results: [] });
  globalThis.onboardingStep(3);
  assert.equal(globalThis.__tab, 'table');
  assert.equal(globalThis.__toasts.length, 1);
  assert.match(globalThis.__toasts[0][0], /пусто/i);

  reset({ results: [{ name: 'А' }] });
  globalThis.onboardingStep(3);
  assert.equal(globalThis.__tab, 'table');
  assert.equal(globalThis.__toasts.length, 0, 'есть записи — подсказка не нужна');
});
