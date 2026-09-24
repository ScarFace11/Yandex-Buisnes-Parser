// UI unit tests for the sticky footer of «Фильтрация результата» (offline, Node).
//
// The accordion ends with «🔄 Применить фильтры заново». It parks directly ABOVE
// the sidebar run-dock («🚀 Найти компании»), otherwise the two sticky bars
// would sit on top of each other and the action would be invisible precisely
// while the user scrolls through the filters.
//
// syncDockHeight() keeps the CSS token --dock-h equal to the REAL height of the
// dock — measured, not hard-coded, because it depends on font, zoom and the
// layout breakpoint. On the phone layout the dock is static (see the #run-dock
// media query in style.css) and the bottom edge is free, so the offset must be
// 0 there; otherwise the footer would float above nothing.
//
// Run with: node --test tests/ui/filterspanel.test.mjs
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

(0, eval)(grab('syncDockHeight'));

const DOCK_MQ = '(min-width: 861px)';

// Minimal window/document stub. Returns the bag that receives --dock-h plus
// the media queries the function asked for.
function mount({ wide = true, height = 61, dock = true } = {}) {
  const css = {};
  const queries = [];
  globalThis.window = {
    matchMedia: q => { queries.push(q); return { media: q, matches: wide }; },
  };
  globalThis.document = {
    getElementById: id => (dock && id === 'run-dock' ? { id, offsetHeight: height } : null),
    documentElement: { style: { setProperty: (k, v) => { css[k] = v; } } },
  };
  return { css, queries };
}

test('на широком экране футер паркуется над доком', () => {
  const { css, queries } = mount({ wide: true, height: 68 });
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '68px', 'отступ футера должен равняться высоте дока');
  assert.deepEqual(queries, [DOCK_MQ], 'высота дока ищется по брейкпоинту сайдбора');
});

test('токен следует за реальной высотой дока (пересчёт на resize)', () => {
  const { css } = mount({ wide: true, height: 61 });
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '61px');
  globalThis.document.getElementById = id => (id === 'run-dock' ? { offsetHeight: 74 } : null);
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '74px', 'кнопка подросла — отступ обязан подрасти');
});

test('на телефоне док статичный — отступ 0', () => {
  const { css } = mount({ wide: false, height: 68 });
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '0px', 'на телефоне нижнюю кромку занимать нечем');
});

test('без matchMedia (старый браузер) док считается приклеенным', () => {
  const { css } = mount({ height: 55 });
  globalThis.window = {};
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '55px');
});

test('нулевая/неизвестная высота не портит токен', () => {
  const { css } = mount({ height: 0 });
  globalThis.syncDockHeight();
  assert.equal(css['--dock-h'], '0px');
  const missing = mount({});
  globalThis.document.getElementById = () => ({ id: 'run-dock' });
  globalThis.syncDockHeight();
  assert.equal(missing.css['--dock-h'], '0px');
});

test('нет дока или DOM — молча выходим', () => {
  mount({ dock: false });
  assert.doesNotThrow(() => globalThis.syncDockHeight());
  globalThis.document = { getElementById: () => null, documentElement: null };
  assert.doesNotThrow(() => globalThis.syncDockHeight());
  globalThis.document = { getElementById: () => null, documentElement: { style: {} } };
  assert.doesNotThrow(() => globalThis.syncDockHeight());
});

test('высота пересчитывается при загрузке, resize и смене размеров дока', () => {
  assert.match(src, /^\s*syncDockHeight\(\);\r?$/m, 'замер нужен при инициализации');
  assert.match(src, /window\.addEventListener\('resize', syncDockHeight\)/);
  assert.match(src, /new ResizeObserver\(syncDockHeight\)\.observe\(_dockEl\)/);
  assert.match(src, /if \(_dockEl && window\.ResizeObserver\)/, 'без дока/ResizeObserver не падаем');
});
