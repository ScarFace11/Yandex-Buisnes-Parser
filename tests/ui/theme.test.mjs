// Тема интерфейса: три режима и их цикл — светлая → тёмная → как в системе.
//
// Covered here:
//   • themePref(): по умолчанию 'system', мусор в хранилище — тоже 'system';
//   • toggleTheme(): цикл кнопки и применение системной темы в режиме 'system';
//   • смена prefers-color-scheme двигает интерфейс только в режиме 'system'.
//
// Механика переключения в живом интерфейсе (значок, aria-label, анимация)
// проверяется в браузере (tests/test_a11y_keyboard.py); здесь — логика режимов,
// которая может незаметно сломаться при рефакторинге.
//
// Run with: node --test tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readAppSrc } from './_src.mjs';

const src = readAppSrc();

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

// Литералы темы: строка кончается "';", массив — '];', объект — '};'.
function grabLiteral(name) {
  const m = new RegExp('const\\s+' + name + '\\s*=').exec(src);
  assert.ok(m, 'const not found in app.js: ' + name);
  const i = m.index;
  const eq = src.indexOf('=', i) + 1;
  let j = eq;
  while (j < src.length && /\s/.test(src[j])) j++;
  let end;
  if (src[j] === "'" || src[j] === '"') end = src.indexOf("';", i) + 2;
  else if (src[j] === '[') end = src.indexOf('];', i) + 2;
  else end = src.indexOf('};', i) + 2;
  assert.ok(end > i, 'конец литерала не найден: ' + name);
  return src.slice(i, end).trim().replace(/;$/, '');
}

// Верхнеуровневый блок подписки на смену системной темы — захватывается
// отдельно от функций (внутри new Function он и регистрирует слушатель).
function grabBlock(snippet) {
  const i = src.indexOf(snippet);
  assert.ok(i >= 0, 'block not found in app.js: ' + snippet);
  const body = src.indexOf('{', i);
  let depth = 0;
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing block: ' + snippet);
}

const CODE = [
  grabLiteral('THEME_KEY'), grabLiteral('THEME_ORDER'), grabLiteral('THEME_RU'),
  'let themeAnimTimer = null;',
  grab('themePref'), grab('systemPrefersDark'), grab('applyTheme'),
  grab('applyThemePref'), grab('toggleTheme'),
  grabBlock('if (window.matchMedia) {'),
].join('\n');

// Окружение под контролем теста: хранилище, matchMedia и DOM.
function makeApp({ stored = null, sysDark = false } = {}) {
  const state = { stored, sysDark, theme: null };
  const ls = {
    getItem: k => (k === 'yp_theme_v1' ? state.stored : null),
    setItem: (k, v) => { if (k === 'yp_theme_v1') state.stored = v; },
  };
  let mqListener = null;
  const win = {
    matchMedia: () => ({
      // matches — ГЕТТЕР: состояние системы может смениться после подписки.
      get matches() { return state.sysDark; },
      addEventListener: (_name, fn) => { mqListener = fn; },
    }),
  };
  const btn = { innerHTML: '', title: '', setAttribute: () => {} };
  const doc = {
    documentElement: {
      setAttribute: (_k, v) => { state.theme = v; },
      getAttribute: () => state.theme,
      classList: { add: () => {}, remove: () => {} },
    },
    getElementById: id => (id === 'btn-theme' ? btn : null),
  };
  const api = new Function(
    'localStorage', 'window', 'document', 'UI_ICONS', 'setTimeout', 'clearTimeout',
    CODE + '; return { themePref, applyThemePref, toggleTheme };')(
      ls, win, doc,
      { auto: 'ICON-auto', sun: 'ICON-sun', moon: 'ICON-moon' },
      () => 0, () => {});
  return { state, api, btn, fireSystemChange: () => { if (mqListener) mqListener(); } };
}

test('по умолчанию режим — «как в системе»', () => {
  assert.equal(makeApp({ sysDark: false }).api.themePref(), 'system');
  assert.equal(makeApp({ sysDark: true }).api.themePref(), 'system');
});

test('мусор в хранилище не ломает выбор темы', () => {
  assert.equal(makeApp({ stored: 'neon' }).api.themePref(), 'system');
});

test('кнопка циклически меняет: светлая → тёмная → как в системе → светлая', () => {
  let a = makeApp({ stored: 'light', sysDark: false });
  a.api.toggleTheme();
  assert.equal(a.state.stored, 'dark');
  assert.equal(a.state.theme, 'dark');

  a = makeApp({ stored: 'dark', sysDark: true });
  a.api.toggleTheme();
  assert.equal(a.state.stored, 'system');
  assert.equal(a.state.theme, 'dark');           // системная тёмная — применилась тёмная
  assert.equal(a.btn.innerHTML, 'ICON-auto');    // и значок «авто», не солнце/луна

  a = makeApp({ stored: 'system', sysDark: true });
  a.api.toggleTheme();
  assert.equal(a.state.stored, 'light');
  assert.equal(a.state.theme, 'light');
});

test('в режиме «система» смена темы ОС двигает интерфейс', () => {
  const a = makeApp({ stored: null, sysDark: true });
  a.api.applyThemePref(false);
  assert.equal(a.state.theme, 'dark');
  a.state.sysDark = false;
  a.fireSystemChange();
  assert.equal(a.state.theme, 'light');
});

test('явная светлая/тёмная не реагирует на смену системной темы', () => {
  const a = makeApp({ stored: 'light', sysDark: true });
  a.api.applyThemePref(false);
  assert.equal(a.state.theme, 'light');
  a.state.sysDark = false;
  a.fireSystemChange();
  assert.equal(a.state.theme, 'light');
});
