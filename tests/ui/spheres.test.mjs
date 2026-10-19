// UI unit test: подписи под сферами — когда парсили и по каким городам.
//
// Строка истории решает, пойдёт пользователь по этому городу снова или нет,
// поэтому проверяем формат и слова: «41 запуска» и потерянные города за
// пределами первых пяти читались как ошибка данных.
//
// Run with: node --test "tests/ui/spheres.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readAppSrc } from './_src.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readAppSrc(root);

function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found: ' + name);
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces: ' + name);
}

const dd = { innerHTML: '' };
globalThis.document = { getElementById: id => (id === 'sphere-dropdown' ? dd : null) };
globalThis.escapeHtml = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
globalThis._spheresCatalog = [];
globalThis._spheresHistory = {};

(0, eval)(
  grab('_runsWord') + '\n' + grab('sphereHistoryLine') + '\n' +
  grab('_sphereSortKey') + '\n' + grab('renderSphereDropdown')
);

test('«ещё не парсили» — когда история пуста', () => {
  globalThis._spheresHistory = {};
  assert.equal(globalThis.sphereHistoryLine('dental'), 'ещё не парсили');
});

test('подпись показывает дату, города и число запусков', () => {
  globalThis._spheresHistory = {
    cafe: { last_ts: 1792257412, cities: ['Уфа', 'Казань'], cities_total: 4, runs: 52 },
  };
  const line = globalThis.sphereHistoryLine('cafe');
  assert.match(line, /🕒 \d{2}\.\d{2}\.\d{4} · Уфа, Казань \+2 · 52 запуска/);
});

test('единственный запуск не подписывается числом', () => {
  globalThis._spheresHistory = { cafe: { last_ts: 1792257412, cities: ['Уфа'], cities_total: 1, runs: 1 } };
  assert.doesNotMatch(globalThis.sphereHistoryLine('cafe'), /запуск/);
});

test('русские склонения не дают «41 запуска»', () => {
  assert.equal(globalThis._runsWord(1), 'запуск');
  assert.equal(globalThis._runsWord(2), 'запуска');
  assert.equal(globalThis._runsWord(5), 'запусков');
  assert.equal(globalThis._runsWord(11), 'запусков');
  assert.equal(globalThis._runsWord(21), 'запуск');
  assert.equal(globalThis._runsWord(41), 'запуск');
});

test('недавно парсенные сферы идут первыми, непарсенные — по алфавиту', () => {
  globalThis._spheresCatalog = [
    { id: 'cafe', name: 'Кафе и кофейни', icon: '☕', queries: ['кафе', 'кофейня'] },
    { id: 'dental', name: 'Стоматология', icon: '🦷', queries: ['стоматология'] },
    { id: 'auto', name: 'Автосервисы', icon: '🔧', queries: ['автосервис'] },
  ];
  globalThis._spheresHistory = { cafe: { last_ts: 1792257412, cities: ['Уфа'], cities_total: 1, runs: 2 } };
  globalThis.renderSphereDropdown();
  const order = [...dd.innerHTML.matchAll(/data-sphere="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['cafe', 'auto', 'dental']);
  assert.match(dd.innerHTML, /Кафе и кофейни/);
  assert.match(dd.innerHTML, /1 слово/);
  assert.match(dd.innerHTML, /2 слова/);
});

test('пустой каталог объясняет причину, а не молчит', () => {
  globalThis._spheresCatalog = [];
  globalThis._spheresHistory = {};
  globalThis.renderSphereDropdown();
  assert.match(dd.innerHTML, /Сферы не загрузились/);
});
