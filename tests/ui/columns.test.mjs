// UI unit tests for reordering the results-table columns («Столбцы» →
// перетаскивание за ⠿ или стрелки). Колонка «Рейтинг» больше не заперта в
// самом конце: порядок задаёт пользователь, видимость — отдельно.
//
// Run with: node --test "tests/ui/columns.test.mjs"
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
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

// `let`-объявления модульного состояния читаем как глобальные присваивания.
function grabLet(name) {
  const i = src.indexOf('let ' + name + ' =');
  assert.ok(i >= 0, 'let not found: ' + name);
  return 'globalThis.' + name + ' = ' + src.slice(i + ('let ' + name + ' = ').length,
    src.indexOf(';', i)) + ';';
}

// ── Минимальный DOM: узлы умеют перемещаться (appendChild = перенос) ──
class El {
  constructor(tag, col) {
    this.tagName = tag;
    this.children = [];
    this.dataset = col ? { col } : {};
    this._classes = new Set();
    this._parent = null;
    const classes = this._classes;
    this.classList = {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    };
  }
  get className() { return [...this._classes].join(' '); }
  appendChild(child) {
    if (child._parent) child._parent.children = child._parent.children.filter(c => c !== child);
    child._parent = this;
    this.children.push(child);
    return child;
  }
  insertBefore(node, ref) {
    const from = node._parent;
    if (from) from.children = from.children.filter(c => c !== node);
    const i = this.children.indexOf(ref);
    if (i < 0) this.children.push(node);
    else this.children.splice(i, 0, node);
    node._parent = this;
    return node;
  }
  remove() { if (this._parent) this._parent.children = this._parent.children.filter(c => c !== this); }
}

const COL_KEYS = ['rev', 'num', 'name', 'category', 'address', 'phone', 'score', 'rating', 'socials'];
const headerRow = new El('tr');
const bodyRows = [new El('tr'), new El('tr')];
for (const key of COL_KEYS) {                       // разметка «как в шаблоне»
  headerRow.appendChild(new El('th', key));
  for (const row of bodyRows) row.appendChild(new El('td', key));
}
const placeholder = new El('tr');                    // «Ничего не найдено»
const placeholderCell = new El('td');
placeholderCell.attrs = { colspan: '9' };
placeholder.appendChild(placeholderCell);

const els = {
  'results-table': new El('table'),
  'col-items': new El('div'),
  'social-filter-row': new El('div'),
  'btn-cols': new El('button'),
};
els['results-table'].children = [headerRow, ...bodyRows, placeholder];
for (const row of els['results-table'].children) row._parent = els['results-table'];

const allRows = [headerRow, ...bodyRows, placeholder];
const allCells = [
  ...headerRow.children,
  ...bodyRows.flatMap(r => r.children),
  placeholderCell,
];

globalThis.document = {
  getElementById: id => els[id] ?? null,
  querySelector: sel => {
    const m = /th\[data-col="([^"]+)"\]/.exec(sel || '');
    if (!m) return null;
    return headerRow.children.find(c => c.dataset.col === m[1]) || null;
  },
  querySelectorAll: sel => {
    if (sel === '#results-table tr') return allRows;
    if (sel === '#results-table [data-col]') return allCells.filter(c => c.dataset.col);
    if (sel === '#results-table th') return headerRow.children;
    return [];
  },
};

// Иконки кнопки «Столбцы» — только текстовая подпись, содержимое не важно.
globalThis.UI_ICONS = { gear: '', checkSquare: '', square: '' };

const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};

(0, eval)([
  'COLS', 'COL_LABELS', 'COL_ID_BY_POS',
  'COL_ORDER_KEY', 'COL_ORDER_DEFAULT', 'COL_SORT_INDEX', 'SORT_INDEX_COL',
  'NOSORT_COLS',
].map(name => {
  const i = src.indexOf('const ' + name + ' =');
  assert.ok(i >= 0, 'const not found: ' + name);
  let k = i + ('const ' + name + ' =').length;
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
  return 'globalThis.' + name + ' = ' + src.slice(i + ('const ' + name + ' =').length, end) + ';';
}).join('\n') + '\n' + grabLet('colOrder') + '\n' + grabLet('hiddenCols'));

const fns = ['normalizeColOrder', 'saveColOrder', 'loadColOrder', 'resetColOrder',
  'applyColOrder', 'applyColClasses', 'moveCol', 'renderColDropdown',
  'sortTableByKey', 'sortTable', 'resetSortHeaders', '_thByCol',
  '_stampMissingColIds'];
(0, eval)(fns.map(grab).join('\n'));

const colsOf = row => row.children.map(c => c.dataset.col || '(без data-col)');

function resetOrder() {
  globalThis.colOrder = globalThis.COL_ORDER_DEFAULT.slice();
  globalThis.hiddenCols = new Set();
  for (const c of allCells) c._classes.delete('col-hidden');
}

// ── 1. Порядок ────────────────────────────────────────────────
test('the default order keeps «Рейтинг» next to «Оценка», соцсети — последними', () => {
  assert.deepEqual(globalThis.COL_ORDER_DEFAULT,
    ['rev', 'num', 'name', 'category', 'address', 'phone', 'score', 'rating', 'socials']);
  assert.notEqual(globalThis.COL_ORDER_DEFAULT.at(-1), 'rating',
    'раньше рейтинг стоял в самом конце — за краем экрана');
});

test('a saved order is normalised: чужие ключи прочь, забытые в конец', () => {
  const norm = globalThis.normalizeColOrder;
  assert.deepEqual(norm(null), globalThis.COL_ORDER_DEFAULT);
  assert.deepEqual(norm(['name', 'name', 'ghost']),
    ['name', 'rev', 'num', 'category', 'address', 'phone', 'score', 'rating', 'socials']);
  // Порядок из будущей версии не теряет колонок.
  assert.deepEqual([...norm(['socials', 'name'])].sort(),
    [...globalThis.COL_ORDER_DEFAULT].sort());
});

test('applyColOrder moves header and body cells into the saved order', () => {
  resetOrder();
  globalThis.colOrder = ['name', 'rev', 'num', 'category', 'address', 'phone',
                         'score', 'rating', 'socials'];
  globalThis.applyColOrder();
  assert.deepEqual(colsOf(headerRow), globalThis.colOrder);
  for (const row of bodyRows) assert.deepEqual(colsOf(row), globalThis.colOrder);
  // Плейсхолдер «Ничего не найдено» не ломается: у него нет data-col.
  assert.equal(placeholder.children.length, 1);
});

test('moveCol swaps two neighbours, saves and persists', () => {
  resetOrder();
  globalThis.moveCol('rating', -1);           // рейтинг ещё левее
  assert.deepEqual(globalThis.colOrder.slice(6, 8), ['rating', 'score']);
  assert.deepEqual(JSON.parse(store[globalThis.COL_ORDER_KEY]),
    globalThis.colOrder);

  // Границы: первый влево и последний вправо — без изменений.
  const before = globalThis.colOrder.slice();
  globalThis.moveCol('rev', -1);
  globalThis.moveCol('socials', 1);
  assert.deepEqual(globalThis.colOrder, before, 'за границу списка не выходим');
});

test('loadColOrder restores the saved order and survives broken JSON', () => {
  resetOrder();
  store[globalThis.COL_ORDER_KEY] = JSON.stringify(['score', 'name', 'category',
    'address', 'phone', 'rating', 'socials', 'rev', 'num']);
  globalThis.loadColOrder();
  assert.equal(globalThis.colOrder[0], 'score');
  assert.deepEqual(colsOf(headerRow), globalThis.colOrder);

  store[globalThis.COL_ORDER_KEY] = '{не json';
  globalThis.loadColOrder();
  assert.deepEqual(globalThis.colOrder, globalThis.COL_ORDER_DEFAULT);
});

test('resetColOrder returns the stock order', () => {
  resetOrder();
  globalThis.moveCol('socials', -1);
  globalThis.resetColOrder();
  assert.deepEqual(globalThis.colOrder, globalThis.COL_ORDER_DEFAULT);
  assert.deepEqual(colsOf(headerRow), globalThis.COL_ORDER_DEFAULT);
});

// ── 2. Скрытие не привязано к позиции ─────────────────────────
test('a hidden column is hidden by class on its own cells, not by position', () => {
  resetOrder();
  globalThis.colOrder = ['name', 'rev', 'num', 'category', 'address', 'phone',
                         'score', 'rating', 'socials'];
  globalThis.hiddenCols = new Set(['phone']);
  globalThis.applyColOrder();
  const hidden = allCells.filter(c => c._classes.has('col-hidden'));
  assert.equal(hidden.length, 1 + bodyRows.length, 'th + td каждого столбца');
  assert.ok(hidden.every(c => c.dataset.col === 'phone'),
    'после перестановки спрятан именно телефон, а не шестая колонка');
});

// ── 3. Сортировка остаётся привязана к колонке ────────────────
test('sorting maps the column key to the legacy numeric index', () => {
  assert.deepEqual(globalThis.COL_SORT_INDEX,
    { rev: null, num: null, name: 2, category: 3, address: 4, phone: 5, score: 6, socials: null, rating: null });
  // «Рейтинг» и «Соцсети» не сортируются — как и раньше.
  assert.equal(globalThis.COL_SORT_INDEX.rating, null);
  assert.equal(globalThis.COL_SORT_INDEX.socials, null);
});

test('resetSortHeaders keeps nosort and hidden classes, drops arrows', () => {
  resetOrder();
  const ratingTh = headerRow.children.find(c => c.dataset.col === 'rating');
  ratingTh.classList.add('nosort', 'col-hidden', 'desc');
  const nameTh = headerRow.children.find(c => c.dataset.col === 'name');
  nameTh.classList.add('asc');
  globalThis.resetSortHeaders();
  assert.equal(ratingTh._classes.has('desc'), false, 'стрелка сброшена');
  assert.equal(ratingTh._classes.has('nosort'), true);
  assert.equal(ratingTh._classes.has('col-hidden'), true, 'скрытие сортировка не снимает');
  assert.equal(nameTh._classes.has('asc'), false);
  assert.equal(headerRow.children.find(c => c.dataset.col === 'num')._classes.has('nosort'), true);
});

// ── 4. Разметка списка ────────────────────────────────────────
test('the dropdown markup offers drag-and-drop with labels and no move arrows', () => {
  resetOrder();
  globalThis.renderColDropdown();
  const html = els['col-items'].innerHTML;
  assert.match(html, /draggable="true"/);
  assert.match(html, /onColDragStart\(event, 'rev'\)/);
  assert.match(html, /onColDragOver\(event, /);
  assert.match(html, /class="col-grip"/);
  assert.match(html, /toggleCol\('rating', this\.checked\)/);
  // Подпись обёрнута в span: у flex-контейнера text-overflow схлопывал текст.
  assert.match(html, /<span class="col-lbl-txt">Рейтинг<\/span>/);
  assert.match(html, /<span class="col-lbl-txt">Соцсети<\/span>/);
  // Стрелки перемещения убраны — порядок меняется только перетаскиванием.
  assert.ok(!html.includes('col-arrow'), 'стрелок перемещения в разметке нет');
  assert.ok(!html.includes('moveCol('), 'обработчики стрелок убраны');
});

test('a stale template without data-col still gets ordered and hidden', () => {
  // Уже запущенный сервер отдаёт старый index.html (Jinja кэширует шаблон) —
  // ячейки без data-col нумеруются по позиции статической разметки.
  resetOrder();
  const legacyHeader = new El('tr');
  const legacyRow = new El('tr');
  const legacyPlaceholder = new El('tr');
  legacyPlaceholder.appendChild(new El('td'));
  for (const _ of COL_KEYS) {
    legacyHeader.appendChild(new El('th'));
    legacyRow.appendChild(new El('td'));
  }
  const rows = [legacyHeader, legacyRow, legacyPlaceholder];
  const cells = [...legacyHeader.children, ...legacyRow.children];
  const expected = ['name', 'rev', 'num', 'category', 'address', 'phone',
                    'score', 'rating', 'socials'];
  const realQSA = globalThis.document.querySelectorAll;
  globalThis.document.querySelectorAll = sel => {
    if (sel === '#results-table tr') return rows;
    if (sel === '#results-table [data-col]') return cells.filter(c => c.dataset.col);
    return [];
  };
  try {
    globalThis.hiddenCols = new Set(['rating']);
    globalThis.colOrder = expected.slice();
    globalThis.applyColOrder();
  } finally {
    globalThis.document.querySelectorAll = realQSA;
    globalThis.colOrder = globalThis.COL_ORDER_DEFAULT.slice();
    globalThis.hiddenCols = new Set();
  }
  assert.deepEqual(colsOf(legacyHeader), expected, 'ячейки без data-col всё равно переставились');
  assert.deepEqual(colsOf(legacyRow), expected);
  assert.equal(legacyRow.children[7].dataset.col, 'rating');
  assert.equal(legacyRow.children[7]._classes.has('col-hidden'), true,
    'скрытие нашло колонку после проставления ключей по позиции');
  assert.equal(legacyPlaceholder.children[0].dataset.col, undefined,
    'плейсхолдер «Ничего не найдено» не считается столбцом');
});

test('the template gives every column a stable data-col and keyed sort', () => {
  const tpl = readFileSync(join(root, 'templates', 'index.html'), 'utf8');
  for (const key of COL_KEYS) assert.match(tpl, new RegExp(`data-col="${key}"`));
  assert.match(tpl, /onclick="sortTableByKey\('name'\)"/);
  assert.match(tpl, /onclick="resetColOrder\(\)"/);
  assert.ok(!/onclick="sortTable\(\d\)"/.test(tpl), 'позиционный sortTable(N) в шапке ломается при перестановке');
  assert.ok(!/col-hide-\d/.test(src), 'позиционное скрытие колонок больше не используется');
  const css = readFileSync(join(root, 'static', 'css', 'style.css'), 'utf8');
  assert.match(css, /#results-table \.col-hidden\{display:none\}/);
  assert.ok(!/#results-table\.col-hide-/.test(css));
});
