// UI unit tests for the «Папка для сохранения» block (static/js/app.js).
//
// Функции слайсятся из продакшн-бандла и работают на минимальной DOM-заглушке:
// браузер не отдаёт серверу абсолютный путь, поэтому поле — это текст, а
// диалог выбора открывает сервер (POST /folder-picker).
//
// Запуск: node --test tests/ui/outputdir.test.mjs
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
  return 'globalThis.' + name + ' = ' + src.slice(i + prefix.length, src.indexOf(';', i)) + ';';
}

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

// ── Minimal DOM stub ──────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  return {
    id, value: '', textContent: '', disabled: false, checked: false,
    _classes: classes, dataset: {},
    classList: {
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
  };
}

const els = {};
for (const id of ['f-output-dir', 'btn-output-browse', 'btn-output-save', 'btn-output-default',
  'f-output-advanced', 'output-advanced', 'f-output-raw', 'f-output-processed',
  'f-output-archive', 'output-dir-hint', 'output-dir-err']) {
  els[id] = mkEl(id);
}

const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
globalThis.document = { getElementById: id => els[id] ?? null };
globalThis.window = {};
const toasts = [];
globalThis.showToast = (msg, type) => toasts.push({ msg, type });
// postJSON — тонкая обёртка над fetch, покрытая отдельно: здесь её заменяем,
// чтобы проверить именно логику формы (payload и состояния).
globalThis.postJSON = async (url, body) => {
  globalThis.__calls.push({ url, body });
  return globalThis.__reply(url, body);
};
globalThis.__calls = [];
globalThis.__reply = async () => ({});

const fns = ['_setText', 'onOutputAdvancedToggle', 'updateOutputDirHint', 'showOutputDirError',
  'applyOutputDirState', 'loadOutputDir', 'pickOutputDir', 'saveOutputDir', 'resetOutputDir'];
(0, eval)(fns.map(grab).join('\n'));
(0, eval)(grabConst('OUT_ADV_KEY'));

// Цепочки .then() внутри обработчиков разворачиваются после текущего
// микротаска — ждём макрозадачу, а не один tick.
const settle = async fn => { fn(); await new Promise(r => setTimeout(r, 0)); };

function reset(output = {}) {
  globalThis.__calls = [];
  toasts.length = 0;
  Object.entries(output).forEach(([id, v]) => {
    if (!els[id]) return;
    if (v === true || v === false) els[id].checked = v;
    else els[id].value = v;
  });
  showOutputDirError('', null);
  updateOutputDirHint(null);
}

const STATE = (over = {}) => Object.assign({
  root: '/data/output', default_root: '/data/output',
  raw: '/data/output/raw', processed: '/data/output/processed',
  archive: '/data/output/_archive', advanced: false, custom: false, running: false,
}, over);

// ── 1. Заполнение формы ───────────────────────────────────────
test('applyOutputDirState fills the field and explains the default', () => {
  reset();
  applyOutputDirState(STATE({}));

  assert.equal(els['f-output-dir'].value, '/data/output');
  assert.equal(els['f-output-advanced'].checked, false);
  assert.match(els['output-dir-hint'].textContent, /По умолчанию: \/data\/output/);
  assert.match(els['output-dir-hint'].textContent, /raw\//);
  assert.equal(els['output-dir-err'].hidden, true);
});

test('a custom folder is described with all three real paths', () => {
  reset();
  applyOutputDirState(STATE({
    custom: true, root: 'D:/Клиенты',
    raw: 'D:/Клиенты/raw', processed: 'D:/Клиенты/processed', archive: 'D:/Клиенты/_archive',
  }));

  assert.equal(els['f-output-dir'].value, 'D:/Клиенты');
  const hint = els['output-dir-hint'].textContent;
  assert.match(hint, /D:\/Клиенты\/raw/);
  assert.match(hint, /D:\/Клиенты\/processed/);
  assert.match(hint, /D:\/Клиенты\/_archive/);
  assert.match(hint, /Ключи, кэш найденного и история остаются/, 'служебные файлы не переезжают');
});

test('advanced mode reveals per-stage folders', () => {
  reset();
  applyOutputDirState(STATE({advanced: true, raw: 'E:/raWs', processed: 'E:/proc'}));

  assert.equal(els['f-output-advanced'].checked, true);
  assert.equal(els['output-advanced']._classes.has('open'), true, 'блок подпапок раскрыт');
  assert.equal(els['f-output-raw'].value, 'E:/raWs');
  assert.equal(els['f-output-processed'].value, 'E:/proc');
  assert.match(els['output-dir-hint'].textContent, /E:\/raWs/);
});

test('the advanced toggle remembers itself in localStorage', () => {
  reset();
  els['f-output-advanced'].checked = true;
  onOutputAdvancedToggle();
  assert.equal(localStorage.getItem(OUT_ADV_KEY), '1');
  assert.equal(els['output-advanced']._classes.has('open'), true);

  els['f-output-advanced'].checked = false;
  onOutputAdvancedToggle();
  assert.equal(localStorage.getItem(OUT_ADV_KEY), '0');
  assert.equal(els['output-advanced']._classes.has('open'), false);
});

// ── 2. Загрузка с сервера ─────────────────────────────────────
test('loadOutputDir takes the server state as the source of truth', async () => {
  reset();
  globalThis.fetch = async () => ({ok: true, json: async () => STATE({custom: true, root: '/mnt/data'})});
  loadOutputDir();
  await new Promise(r => setImmediate(r));

  assert.equal(els['f-output-dir'].value, '/mnt/data');
});

test('a failed load leaves the form alone instead of inventing a path', async () => {
  reset({ 'f-output-dir': '/keep/me' });
  globalThis.fetch = async () => { throw new Error('offline'); };
  loadOutputDir();
  await new Promise(r => setImmediate(r));

  assert.equal(els['f-output-dir'].value, '/keep/me');
  assert.equal(els['output-dir-err'].hidden, true, 'молчаливая ошибка загрузки не пугает пользователя');
});

// ── 3. Сохранение ─────────────────────────────────────────────
test('saveOutputDir sends the path and refreshes the hint', async () => {
  reset({ 'f-output-dir': 'D:/Клиенты 2026' });
  globalThis.__reply = async () => STATE({ok: true, custom: true, root: 'D:/Клиенты 2026',
    raw: 'D:/Клиенты 2026/raw', processed: 'D:/Клиенты 2026/processed',
    archive: 'D:/Клиенты 2026/_archive'});
  await settle(saveOutputDir);

  const call = globalThis.__calls[0];
  assert.equal(call.url, '/output-dir');
  assert.equal(call.body.root, 'D:/Клиенты 2026');
  assert.equal(call.body.advanced, false);
  assert.match(els['output-dir-hint'].textContent, /D:\/Клиенты 2026\/raw/);
  assert.ok(toasts.some(t => /обновлена/.test(t.msg)));
});

test('an active run turns the save into «применится со следующего города»', async () => {
  reset({ 'f-output-dir': 'D:/Next' });
  globalThis.__reply = async () => STATE({ok: true, custom: true, root: 'D:/Next', pending: true, running: true});
  await settle(saveOutputDir);

  assert.ok(toasts.some(t => /со следующего города/.test(t.msg)), JSON.stringify(toasts));
});

test('advanced mode sends per-stage folders and keeps them', async () => {
  reset({ 'f-output-dir': 'D:/root', 'f-output-advanced': true,
          'f-output-raw': 'E:/raw', 'f-output-processed': '', 'f-output-archive': '' });
  globalThis.__reply = async (url, body) => STATE({ok: true, advanced: true, root: body.root,
    raw: body.raw, processed: 'D:/root/processed', archive: 'D:/root/_archive'});
  await settle(saveOutputDir);

  const {body} = globalThis.__calls[0];
  assert.equal(body.advanced, true);
  assert.equal(body.raw, 'E:/raw');
  assert.equal(body.processed, '', 'пустое поле = общая папка');
  assert.equal(els['f-output-raw'].value, 'E:/raw');
});

test('a rejected path surfaces an inline error and keeps the old state', async () => {
  reset({ 'f-output-dir': 'Z:/нет-прав' });
  globalThis.__reply = async () => ({ok: false, error: 'Папка недоступна: нет прав',
                                      errors: {root: 'Папка недоступна: нет прав'}});
  await settle(saveOutputDir);

  assert.equal(els['output-dir-err'].hidden, false);
  assert.match(els['output-dir-err'].textContent, /нет прав/);
  assert.equal(els['f-output-dir']._classes.has('field-invalid'), true, 'поле подсвечено');
  assert.ok(!toasts.some(t => /обновлена/.test(t.msg)), 'об успехе не сообщаем');
});

test('the save button is usable again after failure', async () => {
  reset({ 'f-output-dir': '/x' });
  globalThis.__reply = async () => { throw new Error('boom'); };
  await settle(saveOutputDir);

  assert.equal(els['btn-output-save'].disabled, false);
  assert.equal(els['btn-output-save'].textContent, '💾 Сохранить');
  assert.match(els['output-dir-err'].textContent, /Не удалось сохранить/);
});

// ── 4. Обзор и сброс ──────────────────────────────────────────
test('«📁 Обзор…» asks the server for a folder and fills the field', async () => {
  reset({ 'f-output-dir': '' });
  globalThis.__reply = async url => (url === '/folder-picker'
    ? {ok: true, path: 'C:\\Users\\user\\MyData'}
    : {ok: false});
  await settle(pickOutputDir);

  assert.equal(els['f-output-dir'].value, 'C:\\Users\\user\\MyData');
  assert.equal(els['btn-output-browse'].disabled, false);
  assert.equal(els['btn-output-browse'].textContent, '📁 Обзор…');
  assert.ok(toasts.some(t => /нажмите «Сохранить»/.test(t.msg)), 'выбор ещё не сохранён');
});

test('a cancelled dialog changes nothing', async () => {
  reset({ 'f-output-dir': 'D:/was' });
  globalThis.__reply = async () => ({ok: false, cancelled: true});
  await settle(pickOutputDir);

  assert.equal(els['f-output-dir'].value, 'D:/was');
  assert.equal(els['output-dir-err'].hidden, true);
});

test('a broken dialog explains itself instead of failing silently', async () => {
  reset();
  globalThis.__reply = async () => ({ok: false, error: 'Диалог не открылся: нет дисплея'});
  await settle(pickOutputDir);

  assert.equal(els['output-dir-err'].hidden, false);
  assert.match(els['output-dir-err'].textContent, /нет дисплея/);
});

test('«↺ По умолчанию» resets the folder to output/', async () => {
  reset({ 'f-output-dir': 'D:/Клиенты', 'f-output-advanced': true, 'f-output-raw': 'E:/raw' });
  globalThis.__reply = async () => STATE({ok: true, reset: true});
  await settle(resetOutputDir);

  assert.equal(globalThis.__calls[0].body.reset, true);
  assert.equal(els['f-output-dir'].value, '/data/output');
  assert.equal(els['f-output-advanced'].checked, false, 'расширенный режим снят');
  assert.equal(els['f-output-raw'].value, '', 'переопределения очищены');
});
