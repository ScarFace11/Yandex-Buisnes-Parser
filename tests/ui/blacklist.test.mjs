// UI unit tests for the word blacklist («🚫 Исключить по словам», offline Node).
//
// The chips behave like the city chips in «Где ищем?»: a word goes into the
// field, Enter or «+» adds a chip, «✕» removes it, Backspace in an empty field
// drops the last one. The list lives in its own localStorage key
// (`blacklist_words`, {words, version, updated_at}) with a 1 s autosave, and the
// counter under the field is refreshed from POST /preview-blacklist with a
// 600 ms debounce.
//
// The functions under test are sliced verbatim from the production bundle and
// run against a minimal DOM stub (no browser needed).
//
// Run with: node --test tests/ui/blacklist.test.mjs
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

// Slice `const NAME = <value>;` (scalars and object literals) so the tests never
// duplicate the limits that processing.py enforces as well.
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

for (const name of ['BLACKLIST_KEY', 'BLACKLIST_VERSION', 'BLACKLIST_MAX_WORDS',
                    'BLACKLIST_MAX_LEN', 'BLACKLIST_SAVE_MS', 'BLACKLIST_PREVIEW_MS']) {
  (0, eval)('globalThis.' + name + ' = ' + grabConstValue(name) + ';');
}
const TEMPLATES = (0, eval)('(' + grabConstValue('BLACKLIST_TEMPLATES') + ')');
globalThis.BLACKLIST_TEMPLATES = TEMPLATES;

// ── DOM stub ──────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const el = {
    id, value: '', textContent: '', innerHTML: '', placeholder: '', hidden: false,
    disabled: false, checked: false, selectedIndex: 0, dataset: {}, children: [],
    style: {}, _focused: 0,
    set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    get className() { return [...classes].join(' '); },
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
    appendChild(child) { this.children.push(child); },
    focus() { this._focused++; this.ownerDocument.activeElement = this; },
    querySelectorAll: () => [],
    querySelector: () => null,
    closest: () => null,
  };
  return el;
}

const els = {};
for (const id of ['blacklist-chips', 'blacklist-count', 'blacklist-err',
                  'blacklist-template', 'f-blacklist-input']) {
  els[id] = mkEl(id);
}
els['f-blacklist-input'].ownerDocument = null;

globalThis.document = {
  activeElement: null,
  getElementById: id => els[id] ?? null,
  createElement: () => mkEl('option'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  body: mkEl('body'),
};
els['f-blacklist-input'].ownerDocument = globalThis.document;

// ── Timers / storage / network stubs ──────────────────────────
const timers = [];
globalThis.setTimeout = fn => { timers.push(fn); return timers.length; };
globalThis.clearTimeout = id => { if (id) timers[id - 1] = null; };
function flushTimers() {
  const pending = timers.splice(0, timers.length);
  pending.filter(Boolean).forEach(fn => fn());
}
const storage = {};
globalThis.localStorage = {
  getItem: k => (k in storage ? storage[k] : null),
  setItem: (k, v) => { storage[k] = String(v); },
  removeItem: k => { delete storage[k]; },
};
const toasts = [];
globalThis.showToast = (msg, kind) => toasts.push({ msg, kind });
const requests = [];
let previewReply = { ok: true, total: 100, excluded: 7, remaining: 93 };
globalThis.fetch = (url, opts) => {
  requests.push({ url, body: JSON.parse(opts.body) });
  return Promise.resolve({ json: () => Promise.resolve(previewReply) });
};

// State the sliced functions read from the global scope (the bundle declares
// these with `let`, so the tests provide them explicitly).
for (const name of ['blacklistWords', '_blSaveTimer', '_blPreviewTimer', '_blErrTimer', '_blPreviewSeq']) {
  globalThis[name] = name === 'blacklistWords' ? [] : (name === '_blPreviewSeq' ? 0 : null);
}
globalThis._pluralRu = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

(0, eval)([
  grab('escapeHtml'),
  grab('normalizeBlacklist'),
  grab('parseBlacklistInput'),
  grab('renderBlacklistChips'),
  grab('updateBlacklistCount'),
  grab('showBlacklistError'),
  grab('clearBlacklistError'),
  grab('addBlacklistWords'),
  grab('addBlacklistFromField'),
  grab('onBlacklistKey'),
  grab('removeBlacklistWord'),
  grab('clearBlacklist'),
  grab('applyBlacklistTemplate'),
  grab('saveBlacklistState'),
  grab('scheduleBlacklistSave'),
  grab('saveBlacklistNow'),
  grab('loadBlacklistWords'),
  grab('setBlacklistWords'),
  grab('scheduleBlacklistPreview'),
  grab('previewBlacklist'),
  grab('fillBlacklistTemplateSelect'),
].join('\n'));

function reset({ words = [], stored = null } = {}) {
  globalThis.blacklistWords = [...words];
  globalThis._blSaveTimer = null;
  globalThis._blPreviewTimer = null;
  globalThis._blErrTimer = null;
  globalThis._blPreviewSeq = 0;
  timers.splice(0, timers.length);
  requests.splice(0, requests.length);
  toasts.splice(0, toasts.length);
  for (const k of Object.keys(storage)) delete storage[k];
  if (stored !== null) storage[BLACKLIST_KEY] = stored;
  for (const id of ['blacklist-chips', 'blacklist-count', 'blacklist-err',
                    'blacklist-template', 'f-blacklist-input']) {
    els[id].innerHTML = ''; els[id].value = ''; els[id].hidden = false;
    els[id].textContent = ''; els[id].children = []; els[id].selectedIndex = 0;
    els[id].dataset = {}; els[id]._focused = 0; els[id]._classes.clear();
  }
  previewReply = { ok: true, total: 100, excluded: 7, remaining: 93 };
}

const tick = () => new Promise(r => setImmediate ? setImmediate(r) : r());

// ── 1. Добавление слова ──────────────────────────────────────
test('addBlacklistWords добавляет слово, чип и обновляет счётчик', () => {
  reset();
  assert.equal(globalThis.addBlacklistWords('Франшиза'), 1);
  assert.deepEqual(globalThis.blacklistWords, ['франшиза'], 'регистр приводится к нижнему');
  assert.match(els['blacklist-chips'].innerHTML, /class="bl-chip"/);
  assert.match(els['blacklist-chips'].innerHTML, /франшиза/);
  assert.match(els['blacklist-chips'].innerHTML, /removeBlacklistWord\(0\)/, 'крестик снимает свой чип');
  assert.match(els['blacklist-count'].textContent, /Слов в списке: 1/);
});

test('одна строка с разделителями добавляет несколько слов', () => {
  reset();
  assert.equal(globalThis.addBlacklistWords('Франшиза, VIP; сеть\nбар'), 4);
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'vip', 'сеть', 'бар']);
});

test('Enter и «+» забирают слово из поля и очищают его, фокус остаётся', () => {
  reset();
  els['f-blacklist-input'].value = 'франшиза';
  globalThis.onBlacklistKey({ key: 'Enter', preventDefault() {}, target: els['f-blacklist-input'] });
  assert.deepEqual(globalThis.blacklistWords, ['франшиза']);
  assert.equal(els['f-blacklist-input'].value, '', 'поле очищается');
  assert.ok(els['f-blacklist-input']._focused > 0, 'фокус остаётся в поле');

  els['f-blacklist-input'].value = 'vip';
  globalThis.addBlacklistFromField();
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'vip']);
});

// ── 2. Валидация ─────────────────────────────────────────────
test('пустое слово не добавляется и объясняет себя', () => {
  reset();
  assert.equal(globalThis.addBlacklistWords('   ,  ; '), 0);
  assert.deepEqual(globalThis.blacklistWords, []);
  assert.equal(els['blacklist-err'].hidden, false);
  assert.match(els['blacklist-err'].textContent, /Введите слово/);
});

test('дубликат не добавляется (и не путается с новым словом)', () => {
  reset({ words: ['франшиза'] });
  assert.equal(globalThis.addBlacklistWords('ФРАНШИЗА'), 0);
  assert.deepEqual(globalThis.blacklistWords, ['франшиза']);
  assert.match(els['blacklist-err'].textContent, /уже в списке/);
  // Смешанный ввод: новое слово добавляется, дубль просто пропускается.
  assert.equal(globalThis.addBlacklistWords('франшиза, vip'), 1);
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'vip']);
});

test('слово длиннее 50 символов отбрасывается', () => {
  reset();
  assert.equal(globalThis.addBlacklistWords('я'.repeat(BLACKLIST_MAX_LEN + 1)), 0);
  assert.deepEqual(globalThis.blacklistWords, []);
  assert.match(els['blacklist-err'].textContent, new RegExp(String(BLACKLIST_MAX_LEN)));
  // Ровно 50 — граница включительная.
  assert.equal(globalThis.addBlacklistWords('x'.repeat(BLACKLIST_MAX_LEN)), 1);
});

test('в списке не может быть больше 100 слов', () => {
  reset({ words: Array.from({ length: BLACKLIST_MAX_WORDS }, (_, i) => 'слово' + i) });
  assert.equal(globalThis.addBlacklistWords('лишнее'), 0);
  assert.equal(globalThis.blacklistWords.length, BLACKLIST_MAX_WORDS);
  assert.match(els['blacklist-err'].textContent, new RegExp(String(BLACKLIST_MAX_WORDS)));
});

test('ошибка гаснет сама и снимается при удачном добавлении', () => {
  reset();
  globalThis.addBlacklistWords('');
  assert.equal(els['blacklist-err'].hidden, false);
  globalThis.addBlacklistWords('франшиза');
  assert.equal(els['blacklist-err'].hidden, true, 'успешное добавление убирает ошибку');
  flushTimers();   // авто-скрытие по таймеру не должно ничего ломать
  assert.equal(els['blacklist-err'].hidden, true);
});

// ── 3. Удаление и очистка ────────────────────────────────────
test('removeBlacklistWord убирает только свой чип', () => {
  reset({ words: ['франшиза', 'vip', 'сеть'] });
  globalThis.renderBlacklistChips();
  globalThis.removeBlacklistWord(1);
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'сеть']);
  assert.ok(!/vip/.test(els['blacklist-chips'].innerHTML));
  assert.match(els['blacklist-chips'].innerHTML, /removeBlacklistWord\(1\)">✕<\/span><\/span>$/, 'индексы пересчитаны');
  globalThis.removeBlacklistWord(9);            // вне диапазона — молча игнорируем
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'сеть']);
});

test('Backspace в пустом поле снимает последний чип, в непустом — нет', () => {
  reset({ words: ['франшиза', 'vip'] });
  const inp = els['f-blacklist-input'];
  inp.value = 'сет';
  globalThis.onBlacklistKey({ key: 'Backspace', target: inp });
  assert.deepEqual(globalThis.blacklistWords, ['франшиза', 'vip'], 'в непустом поле Backspace правит текст');
  inp.value = '';
  globalThis.onBlacklistKey({ key: 'Backspace', target: inp });
  assert.deepEqual(globalThis.blacklistWords, ['франшиза']);
});

test('«Очистить список» гасит чипы и опустошает список', () => {
  reset({ words: ['франшиза', 'vip'] });
  globalThis.renderBlacklistChips();
  globalThis.clearBlacklist();
  assert.deepEqual(globalThis.blacklistWords, [], 'список пуст сразу');
  assert.equal(els['blacklist-count'].textContent, 'Список пуст — исключений нет');
  flushTimers();                                  // чипы догорают, рисуется пустой список
  assert.equal(els['blacklist-chips'].innerHTML, '');
  assert.deepEqual(globalThis.blacklistWords, []);
});

test('«Очистить список» на пустом списке ничего не ломает', () => {
  reset();
  globalThis.clearBlacklist();
  assert.equal(toasts.at(-1).msg, 'Список исключений уже пуст');
  assert.deepEqual(globalThis.blacklistWords, []);
});

// ── 4. Сохранение в localStorage ─────────────────────────────
test('автосохранение идёт с задержкой и пишет слова с версией и датой', () => {
  reset();
  globalThis.addBlacklistWords('франшиза');
  assert.equal(storage[BLACKLIST_KEY], undefined, 'до debounce в хранилище тихо');
  flushTimers();
  const saved = JSON.parse(storage[BLACKLIST_KEY]);
  assert.deepEqual(saved.words, ['франшиза']);
  assert.equal(saved.version, BLACKLIST_VERSION);
  assert.match(saved.updated_at, /^\d{4}-\d{2}-\d{2}T/, 'дата в ISO');
});

test('быстрые правки схлопываются в одно сохранение', () => {
  reset();
  globalThis.addBlacklistWords('раз');
  const afterOne = timers.filter(Boolean).length;
  globalThis.addBlacklistWords('два');
  globalThis.addBlacklistWords('три');
  assert.equal(timers.filter(Boolean).length, afterOne, 'таймеры перезаписываются, а не копятся');
  assert.equal(storage[BLACKLIST_KEY], undefined, 'до flush в хранилище ничего нет');
  flushTimers();
  assert.deepEqual(JSON.parse(storage[BLACKLIST_KEY]).words, ['раз', 'два', 'три']);
});

test('«💾 Сохранить список» сохраняет сразу и говорит об этом', () => {
  reset();
  globalThis.addBlacklistWords('франшиза');
  globalThis.saveBlacklistNow();
  assert.deepEqual(JSON.parse(storage[BLACKLIST_KEY]).words, ['франшиза']);
  assert.match(toasts.at(-1).msg, /Список сохранён: 1 слово/);
  flushTimers();
  assert.deepEqual(JSON.parse(storage[BLACKLIST_KEY]).words, ['франшиза'], 'повторно не портится');
});

test('loadBlacklistWords читает новый формат, голый массив и мусор', () => {
  reset({ stored: JSON.stringify({ words: ['Франшиза', 'vip'], version: 1, updated_at: 'x' }) });
  assert.deepEqual(globalThis.loadBlacklistWords(), ['франшиза', 'vip']);
  assert.match(els['blacklist-chips'].innerHTML, /франшиза/);

  reset({ stored: JSON.stringify(['Сеть']) });           // старый формат — просто массив
  assert.deepEqual(globalThis.loadBlacklistWords(), ['сеть']);

  reset({ stored: '{битый json' });
  assert.deepEqual(globalThis.loadBlacklistWords(), []);
  reset({ stored: JSON.stringify({ words: 'не массив' }) });
  assert.deepEqual(globalThis.loadBlacklistWords(), []);
});

test('setBlacklistWords (пресет) нормализует и сохраняет список', () => {
  reset();
  assert.deepEqual(globalThis.setBlacklistWords(['Франшиза', 'франшиза', '', 'я'.repeat(80)]), ['франшиза']);
  flushTimers();
  assert.deepEqual(JSON.parse(storage[BLACKLIST_KEY]).words, ['франшиза']);
});

// ── 5. Шаблоны ───────────────────────────────────────────────
test('шаблон добавляется К списку, а не вместо него', () => {
  reset({ words: ['франшиза'] });
  const key = Object.keys(TEMPLATES)[0];
  const added = globalThis.applyBlacklistTemplate(key);
  assert.equal(added, TEMPLATES[key].words.filter(w => w !== 'франшиза').length);
  assert.ok(globalThis.blacklistWords.includes('франшиза'), 'прежние слова на месте');
  TEMPLATES[key].words.forEach(w => assert.ok(globalThis.blacklistWords.includes(w.toLowerCase()), w));
  assert.equal(els['blacklist-template'].selectedIndex, 0, 'селект возвращается к плейсхолдеру');
});

test('повторный шаблон сообщает, что слова уже в списке', () => {
  reset();
  const key = Object.keys(TEMPLATES)[1];
  globalThis.applyBlacklistTemplate(key);
  const n = globalThis.blacklistWords.length;
  assert.equal(globalThis.applyBlacklistTemplate(key), 0);
  assert.equal(globalThis.blacklistWords.length, n);
  assert.match(toasts.at(-1).msg, /уже в списке/);
  assert.equal(globalThis.applyBlacklistTemplate('нет-такого'), 0, 'мусорный ключ безопасен');
});

test('опции шаблонов строятся из реестра и не дублируются', () => {
  reset();
  globalThis.fillBlacklistTemplateSelect();
  assert.equal(els['blacklist-template'].children.length, Object.keys(TEMPLATES).length);
  assert.equal(els['blacklist-template'].children[0].value, Object.keys(TEMPLATES)[0]);
  assert.ok(TEMPLATES[Object.keys(TEMPLATES)[0]].label.includes('🏪'));
  globalThis.fillBlacklistTemplateSelect();
  assert.equal(els['blacklist-template'].children.length, Object.keys(TEMPLATES).length, 'повторный вызов не дублирует');
});

// ── 6. Счётчик исключений ────────────────────────────────────
test('счётчик считается с debounce — одним запросом на серию правок', async () => {
  reset();
  globalThis.addBlacklistWords('франшиза');
  globalThis.addBlacklistWords('vip');
  assert.equal(requests.length, 0, 'до debounce в сеть не ходим');
  flushTimers();
  await tick();
  assert.equal(requests.length, 1, 'три слова → один запрос');
  assert.equal(requests[0].url, '/preview-blacklist');
  assert.deepEqual(requests[0].body.words, ['франшиза', 'vip']);
  assert.equal(els['blacklist-count'].textContent, '🚫 Исключит 7 из 100 компаний — останется 93');
});

test('ответ на устаревший список не перетирает свежий счётчик', async () => {
  reset();
  globalThis.addBlacklistWords('франшиза');
  flushTimers();                       // запрос №1 (ответ ещё не пришёл)
  globalThis.blacklistWords.push('vip');
  globalThis._blPreviewTimer = null;
  globalThis.scheduleBlacklistPreview();
  flushTimers();                       // запрос №2
  previewReply = { ok: true, total: 10, excluded: 2, remaining: 8 };
  await tick();
  assert.equal(requests.length, 2);
  assert.ok(/Исключит 7 из 100/.test(els['blacklist-count'].textContent) === false,
            'первый ответ должен быть проигнорирован');
});

test('пустой список не ходит в сеть, ноль исключений объясняется словами', async () => {
  reset();
  globalThis.scheduleBlacklistPreview();
  flushTimers();
  await tick();
  assert.equal(requests.length, 0);
  assert.equal(els['blacklist-count'].textContent, 'Список пуст — исключений нет');

  reset();
  previewReply = { ok: true, total: 40, excluded: 0, remaining: 40 };
  globalThis.addBlacklistWords('франшиза');
  flushTimers();
  await tick();
  assert.match(els['blacklist-count'].textContent, /Ничего не исключается/);

  reset();
  previewReply = { ok: true, total: 0, excluded: 0, remaining: 0 };
  globalThis.addBlacklistWords('франшиза');
  flushTimers();
  await tick();
  assert.match(els['blacklist-count'].textContent, /Нет сырых данных/);
});

test('сеть молчит — счётчик честно говорит об этом', async () => {
  reset();
  globalThis.fetch = () => Promise.reject(new Error('offline'));
  globalThis.addBlacklistWords('франшиза');
  flushTimers();
  await tick();
  assert.match(els['blacklist-count'].textContent, /Не удалось посчитать/);
});

// ── 7. Что уходит на сервер ──────────────────────────────────
test('список уезжает в форму, в рефильтр и в пресет', () => {
  assert.match(grab('refilterNow'), /blacklist_words:\s*\[\.\.\.blacklistWords\]/, 'рефильтр обязан отправить список');
  assert.match(grab('getParams'), /blacklist_words:\s*\[\.\.\.blacklistWords\]/, 'новый поиск — тоже');
  assert.match(grab('getCurrentSettings'), /blacklist:\s*\[\.\.\.blacklistWords\]/, 'пресет забирает список');
  assert.match(grab('applySettings'), /setBlacklistWords\(s\.blacklist\)/, 'и возвращает его обратно');
  assert.match(grab('refilterNow'), /🚫 Blacklist: исключено \$\{data\.blacklist_excluded \|\| 0\} компаний/,
               'журнал рефильтра: у рефильтра нет потоковых логов сервера');
});
