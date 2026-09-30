// UI unit tests for the lazy Leaflet loader (offline, Node).
//
// Карта — единственная вкладка, которой нужна сторонняя библиотека. Раньше
// <script src="unpkg…"> стоял в <head>: 148 КБ грузились всем и всегда, а без
// интернета вкладка «На карте» не открывалась вообще. Теперь библиотека лежит
// рядом с приложением, а тесты проверяют ровно то, что легко сломать:
// однократность загрузки, честную ошибку и повторную попытку после неё.
//
// Run with: node --test tests/ui/leaflet.test.mjs
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

// `let _leafletPromise = null;` — состояние загрузчика, объявленное через let.
function grabDecl(name) {
  const m = new RegExp('(?:let|const) ' + name + '\\s*=').exec(src);
  assert.ok(m, 'declaration not found in app.js: ' + name);
  return src.slice(m.index, src.indexOf(';', m.index) + 1);
}

// ── DOM stub: только head.appendChild и создание тегов ────────
const injected = [];
function mkEl(tag) {
  const el = {
    tagName: tag.toUpperCase(), _attrs: {}, _listeners: {},
    setAttribute(k, v) { this._attrs[k] = v; },
    addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
    // Скрипт получает обработчики свойствами (js.onload/js.onerror), поэтому
    // fire обязан звать и их — иначе промис загрузки не завершится никогда.
    fire(type, ev) {
      const handler = this['on' + type];
      if (typeof handler === 'function') handler(ev || {});
      (this._listeners[type] || []).forEach(fn => fn(ev || {}));
    },
  };
  return el;
}
const mapContainer = { innerHTML: '', id: 'map-container' };
globalThis.document = {
  getElementById: id => (id === 'map-container' ? mapContainer : null),
  createElement: tag => mkEl(tag),
  head: { appendChild: el => { injected.push(el); return el; } },
};
// В браузере Leaflet кладёт себя в window.L — в тесте это тот же глобальный
// объект, поэтому window === globalThis (как в tests/ui/notifications.test.mjs).
globalThis.window = globalThis;
globalThis.escapeHtml = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// initMap строит карту на Leaflet — здесь важно только, что он вызван.
let inited = 0;
globalThis.initMap = () => { inited++; };

(0, eval)([
  grabDecl('_leafletPromise'),
  grab('loadLeaflet'),
  grab('ensureMapReady'),
  // Состояние объявлено через let в области eval, поэтому сброс тоже должен
  // жить там: снаружи по имени его не видно (как __consts в notifications).
  'globalThis.__resetLeaflet = () => { _leafletPromise = null; };',
].join('\n'));

function reset() {
  injected.length = 0;
  mapContainer.innerHTML = '';
  inited = 0;
  globalThis.__resetLeaflet();
  delete globalThis.L;
  globalThis.LEAFLET_ASSETS = { css: '/static/vendor/leaflet/leaflet.css',
                                js: '/static/vendor/leaflet/leaflet.js' };
}

// ── Загрузка ──────────────────────────────────────────────────

test('подключает css и js из переданных путей, а не из интернета', async () => {
  reset();
  const p = loadLeaflet();
  assert.equal(injected.length, 2, 'одна ссылка на стили и один скрипт');
  const [css, js] = injected;
  assert.equal(css.tagName, 'LINK');
  assert.equal(css.href, '/static/vendor/leaflet/leaflet.css');
  assert.equal(js.tagName, 'SCRIPT');
  assert.equal(js.src, '/static/vendor/leaflet/leaflet.js');
  globalThis.L = {};                  // браузер: Leaflet уже определился
  js.fire('load');
  await p;
});

test('повторные вызовы не грузят библиотеку второй раз', async () => {
  reset();
  const a = loadLeaflet();
  const b = loadLeaflet();
  assert.equal(injected.length, 2, 'двойная загрузка: ' + injected.length + ' тегов');
  assert.equal(a, b, 'один и тот же промис');
  globalThis.L = {};
  injected[1].fire('load');
  await a;
  // И после успешной загрузки — та же библиотека, без новых тегов.
  globalThis.L = {};
  await loadLeaflet();
  assert.equal(injected.length, 2);
});

test('уже загруженный Leaflet не подключается заново', async () => {
  reset();
  globalThis.L = { map: () => {} };
  await loadLeaflet();
  assert.equal(injected.length, 0, 'библиотека уже в странице — ничего не грузим');
});

test('без путей к файлам честно отказывает', async () => {
  reset();
  globalThis.LEAFLET_ASSETS = {};
  await assert.rejects(() => loadLeaflet(), /путь к библиотеке карт не передан/);
  assert.equal(injected.length, 0);
});

test('скрипт не загрузился — отклоняем и не остаёмся в «загружается»', async () => {
  reset();
  const p = loadLeaflet();
  injected[1].fire('error');
  await assert.rejects(() => p, /файл библиотеки карт недоступен/);
  // Провал не запоминается: следующий клик по вкладке пробует снова.
  const again = loadLeaflet();
  assert.equal(injected.length, 4, 'вторая попытка должна создать новые теги');
  globalThis.L = {};
  injected[3].fire('load');
  await again;
});

test('скрипт загрузился, но Leaflet не появился — это тоже ошибка', async () => {
  reset();
  const p = loadLeaflet();
  injected[1].fire('load');          // L так и не определён
  await assert.rejects(() => p, /не инициализировалась/);
});

// ── Вкладка карты ─────────────────────────────────────────────

test('ensureMapReady инициализирует карту после загрузки библиотеки', async () => {
  reset();
  ensureMapReady();
  assert.match(mapContainer.innerHTML, /Загружаю карту/, 'пока грузится — не пустой прямоугольник');
  assert.equal(inited, 0, 'карта строится только с библиотекой');
  globalThis.L = {};
  injected[1].fire('load');
  await new Promise(r => setImmediate(r));
  assert.equal(inited, 1);
});

test('ошибка загрузки видна на месте карты, а не в консоли', async () => {
  reset();
  ensureMapReady();
  injected[1].fire('error');
  await new Promise(r => setImmediate(r));
  assert.match(mapContainer.innerHTML, /Карта недоступна/);
  assert.match(mapContainer.innerHTML, /результаты и выгрузка работают без неё/i);
  assert.equal(inited, 0, 'без библиотеки карту не строим');
});

test('сообщение об ошибке экранируется', async () => {
  reset();
  globalThis.LEAFLET_ASSETS = { js: '' };
  ensureMapReady();
  await new Promise(r => setImmediate(r));
  assert.match(mapContainer.innerHTML, /Карта недоступна/);
  assert.doesNotMatch(mapContainer.innerHTML, /<script/);
});
