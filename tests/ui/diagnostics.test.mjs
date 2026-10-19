// UI unit tests for «🩺 Диагностика» (offline, Node).
//
// Панель показывает результаты проверок, которые целиком приходят с сервера
// (пути к папкам, тексты ошибок сервисов). Поэтому здесь проверяется прежде
// всего отображение: ничего не теряется, ничего не выполняется как код, а
// «Проверить всё» — единственный путь, который может потратить квоту 2ГИС.
//
// Run with: node --test tests/ui/diagnostics.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readAppSrc, MODAL_A11Y_STUB } from './_src.mjs';

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
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  const end = src.indexOf('\n};', i);
  return src.slice(i, end + 3);
}

// ── DOM stub ──────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  return {
    id, value: '', textContent: '', innerHTML: '', disabled: false, hidden: false,
    className: '', _listeners: {},
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    setAttribute(k, v) { this[k] = v; },
    addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); },
    remove() { delete els[this.id]; },
  };
}
const els = {};
for (const id of ['diag-overlay', 'diag-summary', 'diag-results']) els[id] = mkEl(id);

const runButtons = [mkEl('diag-run-all'), mkEl('diag-run-keys'), mkEl('diag-run-local')];
const DIAG_LABELS = ['#i-check-square Проверить всё', '#i-key Только ключи',
                     '#i-folder Без запросов к API'];
runButtons.forEach((b, i) => { b.innerHTML = DIAG_LABELS[i]; });

const appended = [];
const docListeners = [];
globalThis.document = {
  getElementById: id => els[id] ?? null,
  createElement: () => mkEl('created'),
  querySelectorAll: sel => (sel === '.diag-run' ? runButtons : []),
  addEventListener: (type, fn) => docListeners.push({ type, fn }),
  removeEventListener: (type, fn) => {
    const i = docListeners.findIndex(l => l.type === type && l.fn === fn);
    if (i >= 0) docListeners.splice(i, 1);
  },
  // appendChild повторяет настоящее DOM: элемент становится доступен по id.
  body: { appendChild: el => { appended.push(el); if (el.id) els[el.id] = el; } },
};

const requests = [];
let nextReply = { ok: true, results: [] };
let fetchThrows = false;
const stubFetch = (url, opts) => {
  requests.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  if (fetchThrows) return Promise.reject(new Error('offline'));
  return Promise.resolve({ json: () => Promise.resolve(nextReply) });
};
globalThis.fetch = stubFetch;

// Слова статусов для текстового отчёта: объявлены однострочной константой,
// поэтому grabConst (ищет «\n};») их не вырежет — задаём здесь как есть.
globalThis.DIAG_STATUS_WORDS = { ok: 'OK', warn: 'ВНИМАНИЕ', error: 'ОШИБКА' };

globalThis.escapeHtml = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
globalThis._pluralRu = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

(0, eval)([
  MODAL_A11Y_STUB,
  grabConst('UI_ICONS'),
  grabConst('DIAG_GROUP_NAMES'),
  grabConst('DIAG_GROUP_TITLES'),
  grabConst('DIAG_STATUS'),
  grab('showDiagnostics'),
  grab('_diagEscape'),
  grab('closeDiagnostics'),
  grab('runDiagnostics'),
  grab('setDiagSummary'),
  grab('renderDiagnostics'),
  grab('diagRowHTML'),
  grab('diagReportText'),
  grab('copyDiagReport'),
  grab('_syncDiagCopyBtn'),
].join('\n'));

function reset() {
  // Возвращаем стандартную заглушку сети: тест, подменивший fetch, не должен
  // оставлять после себя «висящий» промис для следующих тестов.
  globalThis.fetch = stubFetch;
  globalThis._diagBusy = false;
  globalThis._diagLast = [];
  els['diag-overlay'] = mkEl('diag-overlay');
  els['diag-summary'].innerHTML = '';
  els['diag-summary'].className = '';
  els['diag-results'].innerHTML = '';
  runButtons.forEach((b, i) => {
    b.disabled = false;
    b.innerHTML = DIAG_LABELS[i];
  });
  requests.length = 0;
  appended.length = 0;
  docListeners.length = 0;
  fetchThrows = false;
  nextReply = { ok: true, results: [] };
}

const ROW = (id, group, status, title = 'проверка', detail = '', hint = '') =>
  ({ id, group, status, title, detail, hint });

// ── Строка отчёта ─────────────────────────────────────────────

test('diagRowHTML: статус, объяснение и совет', () => {
  const html = diagRowHTML(ROW('x', 'keys', 'error', 'Ключ недействителен',
                               'Яндекс ответил: Invalid api key.', 'Проверьте ключ.'));
  assert.match(html, /data-status="error"/);
  assert.match(html, /#i-x/);
  assert.match(html, /Ключ недействителен/);
  assert.match(html, /Invalid api key\./);
  assert.match(html, /#i-info/);
  assert.match(html, /Проверьте ключ\./);
  assert.match(html, /ошибка/, 'статус должен быть виден и словами (скринридер)');
});

test('diagRowHTML: тексты с сервера экранируются', () => {
  const html = diagRowHTML(ROW('x', 'files', 'warn',
                               '<img src=x onerror="alert(1)">',
                               'путь <b>C:\\tmp</b>', 'совет <script>bad()</scr' + 'ipt>'));
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<script/);
  assert.match(html, /&lt;img/);
  assert.match(html, /&lt;script&gt;/);
});

test('diagRowHTML: неизвестный статус не ломает строку', () => {
  const html = diagRowHTML({ id: 'x', group: 'env', status: 'что-то', title: 'Т' });
  assert.match(html, /data-status="что-то"/);
  assert.match(html, /#i-warn/);
});

// ── Итог и группы ─────────────────────────────────────────────

test('renderDiagnostics: итог считает статусы и объясняет, что делать', () => {
  renderDiagnostics([
    ROW('a', 'keys', 'error', 'Ошибка'),
    ROW('b', 'keys', 'warn', 'Предупреждение'),
    ROW('c', 'files', 'ok', 'Норма'),
  ], ['keys', 'files']);
  const summary = els['diag-summary'].innerHTML;
  assert.match(summary, /Проверок: 3/);
  assert.match(summary, /<b>1<\/b> в порядке/);
  assert.match(summary, /<b>1<\/b> с предупреждениями/);
  assert.match(summary, /<b>1<\/b> с ошибками/);
  assert.match(summary, /Сначала разберитесь с ошибками/);
  assert.equal(els['diag-summary'].className, 'diag-summary diag-summary-error');
});

test('renderDiagnostics: без ошибок — бодрый итог', () => {
  renderDiagnostics([ROW('a', 'env', 'ok', 'Норма')], ['env']);
  assert.match(els['diag-summary'].innerHTML, /Всё готово к работе/);
  assert.equal(els['diag-summary'].className, 'diag-summary diag-summary-ok');
});

test('renderDiagnostics: только предупреждения — не «всё хорошо»', () => {
  renderDiagnostics([ROW('a', 'data', 'warn', 'Старый сбор')], ['data']);
  assert.match(els['diag-summary'].innerHTML, /предупреждения — это места, где результат будет хуже/);
  assert.equal(els['diag-summary'].className, 'diag-summary diag-summary-warn');
});

test('renderDiagnostics: группы идут в порядке запуска и не смешиваются', () => {
  renderDiagnostics([
    ROW('a', 'keys', 'ok', 'Ключ Яндекс'),
    ROW('b', 'data', 'warn', 'Старый сбор'),
    ROW('c', 'files', 'ok', 'Папка'),
  ], ['keys', 'files', 'data']);
  const html = els['diag-results'].innerHTML;
  assert.ok(html.indexOf('Ключи API') < html.indexOf('Файлы и папки'), 'порядок групп');
  assert.ok(html.indexOf('Файлы и папки') < html.indexOf('Данные прошлых сборов'));
  const keysBlock = html.slice(html.indexOf('Ключи API'), html.indexOf('Файлы и папки'));
  assert.match(keysBlock, /Ключ Яндекс/);
  assert.doesNotMatch(keysBlock, /Старый сбор/, 'чужая проверка не должна попасть в группу');
});

test('renderDiagnostics: группы без строк не рисуются, пустой отчёт объясняется', () => {
  renderDiagnostics([ROW('a', 'keys', 'ok', 'Т')], ['keys', 'env']);
  assert.doesNotMatch(els['diag-results'].innerHTML, /Окружение/);

  renderDiagnostics([], []);
  assert.match(els['diag-results'].innerHTML, /Проверки ничего не вернули/);
});

// ── Запуск проверок ───────────────────────────────────────────

test('локальные проверки не трогают ключи (и не тратят квоту)', async () => {
  reset();
  nextReply = { ok: true, results: [ROW('a', 'files', 'ok', 'Папка')] };
  await globalThis.runDiagnostics(['files', 'data', 'env'], runButtons[2]);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/diagnostics/run');
  assert.deepEqual(requests[0].body.groups, ['files', 'data', 'env']);
  assert.ok(!requests[0].body.groups.includes('keys'), 'ключи проверяются только отдельной кнопкой');
  assert.match(els['diag-results'].innerHTML, /Папка/);
});

test('во время проверок кнопки выключены, потом возвращаются к прежним подписям', async () => {
  reset();
  const seen = {};
  const realFetch = globalThis.fetch;
  globalThis.fetch = (url, opts) => {
    seen.disabled = runButtons.map(b => b.disabled);
    seen.pressed = runButtons[0].innerHTML;
    seen.summary = els['diag-summary'].innerHTML;
    return realFetch(url, opts);
  };
  nextReply = { ok: true, results: [ROW('a', 'keys', 'ok', 'Т')] };
  await globalThis.runDiagnostics(['keys'], runButtons[0]);
  globalThis.fetch = realFetch;

  assert.deepEqual(seen.disabled, [true, true, true], 'все кнопки выключены во время работы');
  assert.match(seen.pressed, /Проверяю/);
  assert.match(seen.summary, /Ключи проверяются живыми запросами/, 'предупреждаем о квоте заранее');
  assert.deepEqual(runButtons.map(b => b.disabled), [false, false, false]);
  assert.equal(runButtons[0].innerHTML, DIAG_LABELS[0], 'подпись вернулась');
});

test('повторное нажатие во время работы не запускает вторую проверку', async () => {
  reset();
  let release;
  // Запрос уходит сразу, но «висит» в сети — так второй клик приходится ровно
  // на время работы первой проверки.
  const pendingFetch = (url, opts) => {
    requests.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
    return new Promise(res => { release = () => res({ json: () => Promise.resolve(nextReply) }); });
  };
  globalThis.fetch = pendingFetch;
  nextReply = { ok: true, results: [] };
  const first = globalThis.runDiagnostics(['files'], runButtons[2]);
  await globalThis.runDiagnostics(['files'], runButtons[2]);
  assert.equal(requests.length, 1, 'второй запрос не уходит');
  release();
  await first;
  globalThis.fetch = stubFetch;
});

test('сервер ответил ошибкой — показываем её словами', async () => {
  reset();
  nextReply = { ok: false, error: 'Диагностика не смогла выполниться: RuntimeError', results: [] };
  await globalThis.runDiagnostics(['keys'], runButtons[0]);
  assert.match(els['diag-summary'].innerHTML, /Проверки не выполнились: Диагностика не смогла/);
  assert.equal(els['diag-summary'].className, 'diag-summary diag-summary-error');
});

test('сервер недоступен — панель не падает и говорит об этом', async () => {
  reset();
  fetchThrows = true;
  await globalThis.runDiagnostics(['keys'], runButtons[0]);
  assert.match(els['diag-summary'].innerHTML, /сервер недоступен/);
  assert.deepEqual(runButtons.map(b => b.disabled), [false, false, false]);
});

test('пустой список групп означает полную проверку', async () => {
  reset();
  await globalThis.runDiagnostics([], runButtons[0]);
  assert.deepEqual(requests[0].body.groups, ['keys', 'files', 'data', 'runs', 'env']);
});

// ── Модалка ───────────────────────────────────────────────────

test('showDiagnostics: три кнопки запуска и предупреждение о квоте', () => {
  reset();
  globalThis.showDiagnostics();
  assert.equal(appended.length, 1, 'модалка добавляется в body');
  const overlay = appended[0];
  assert.equal(overlay.id, 'diag-overlay');
  assert.match(overlay.innerHTML, /#i-pulse/);
  assert.match(overlay.innerHTML, /Диагностика/);
  assert.match(overlay.innerHTML, /runDiagnostics\(\['keys','files','data','runs','env'\]/);
  assert.match(overlay.innerHTML, /runDiagnostics\(\['keys'\]/);
  assert.match(overlay.innerHTML, /runDiagnostics\(\['files','data','runs','env'\]/);
  assert.match(overlay.innerHTML, /живой запрос к ВКонтакте/,
    'человек должен знать, что проверка ключей делает внешний запрос');
  assert.match(overlay.innerHTML, /id="diag-summary"/);
  assert.match(overlay.innerHTML, /id="diag-results"/);
});

test('модалка закрывается: Esc, клик вне и кнопка «Закрыть»', () => {
  reset();
  globalThis.showDiagnostics();
  const overlay = appended[0];
  assert.equal(docListeners.filter(l => l.type === 'keydown').length, 1,
    'Esc должен работать и без фокуса внутри модалки');

  // Esc
  globalThis._diagEscape({ key: 'Escape' });
  assert.equal(els['diag-overlay'], undefined, 'Esc закрывает модалку');
  assert.equal(docListeners.filter(l => l.type === 'keydown').length, 0, 'слушатель Esc снимается');

  // Клик по подложке
  reset();
  globalThis.showDiagnostics();
  const overlay2 = appended[0];
  const [clickHandler] = overlay2._listeners.click;
  clickHandler({ target: overlay2 });
  assert.equal(els['diag-overlay'], undefined, 'клик вне модалки закрывает её');

  // Клик внутри — не закрывает.
  reset();
  globalThis.showDiagnostics();
  const overlay3 = appended[0];
  const [clickHandler3] = overlay3._listeners.click;
  clickHandler3({ target: { id: 'внутри' } });
  assert.ok(els['diag-overlay'], 'клик внутри модалки ничего не закрывает');
});

test('повторное открытие не плодит копии модалки', () => {
  reset();
  const overlay = mkEl('diag-overlay');
  els['diag-overlay'] = overlay;
  globalThis.showDiagnostics();
  assert.equal(appended.length, 1, 'старая подложка удаляется, новая добавляется');
});

test('closeDiagnostics безопасен без открытой модалки', () => {
  reset();
  delete els['diag-overlay'];
  assert.doesNotThrow(() => globalThis.closeDiagnostics());
});

// ── Живая проба браузера (глубокий режим) ────────────────────

test('showDiagnostics: отдельная кнопка живой пробы браузера', () => {
  reset();
  globalThis.showDiagnostics();
  const html = appended[0].innerHTML;
  assert.match(html, /runDiagnostics\(\['engines'\], this, true\)/,
    'проверка вкладки и выдачи — отдельная кнопка');
  assert.match(html, /Проверить браузер/);
  assert.match(html, /страницу выдачи/,
    'человек должен знать, что кнопка открывает настоящий браузер');
});

test('глубокая проба уезжает на сервер флагом deep', async () => {
  reset();
  await globalThis.runDiagnostics(['engines'], runButtons[0], true);
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].body.groups, ['engines']);
  assert.equal(requests[0].body.deep, true);
});

test('обычные проверки просят быстрый режим', async () => {
  reset();
  await globalThis.runDiagnostics(['keys'], runButtons[1]);
  assert.equal(requests[0].body.deep, false,
    'без явного флага сервер не открывает браузер');
});

// ── Прогоны, легенда и копирование отчёта ────────────────────

test('группа «Прогоны и кэш» есть в кнопках и в отчёте', () => {
  reset();
  globalThis.showDiagnostics();
  assert.match(appended[0].innerHTML, /'runs'/, 'история прогонов — часть «Проверить всё»');
  globalThis.renderDiagnostics([{
    group: 'runs', status: 'ok', title: 'Последний прогон',
    detail: '17.10.2026 14:32: Уфа · 42 организации',
  }], ['runs']);
  assert.match(els['diag-results'].innerHTML, /Прогоны и кэш/);
  assert.match(els['diag-results'].innerHTML, /42 организации/);
});

test('легенда объясняет три статуса словами', () => {
  reset();
  globalThis.showDiagnostics();
  const html = appended[0].innerHTML;
  assert.match(html, /diag-legend/);
  assert.match(html, /в порядке/);
  assert.match(html, /сбор не пойдёт/);
  assert.match(html, /цвет полосы слева и есть статус/i,
    'легенда должна объяснять, что означает цвет');
});

test('в окне видно, как проверить без запуска интерфейса', () => {
  reset();
  globalThis.showDiagnostics();
  const html = appended[0].innerHTML;
  assert.match(html, /--check/);
  assert.match(html, /без окна приложения/);
});

test('текстовый отчёт годится для пересылки: без разметки, с подсказками', () => {
  globalThis._diagLast = [
    { group: 'runs', status: 'warn', title: 'Прогонов ещё не было',
      detail: 'История пуста.', hint: 'Запустите поиск.' },
    { group: 'files', status: 'ok', title: 'Папка доступна', detail: 'output' },
  ];
  const text = globalThis.diagReportText();
  assert.doesNotMatch(text, /<svg|<div|<span/, 'в буфер обмена не должен попадать HTML');
  assert.match(text, /Прогоны и кэш/);
  assert.match(text, /\[ВНИМАНИЕ\]/);
  assert.match(text, /→ Запустите поиск\./);
  assert.match(text, /Итог: 2 проверок: 1 в порядке, 1 с предупреждениями/);
  assert.doesNotMatch(text, /ключ|token/i, 'в отчёте не должно быть даже намёка на секреты');
});

test('копирование отчёта не падает без результатов', async () => {
  reset();
  assert.equal(await globalThis.copyDiagReport(null), false);
});

test('неключевые проверки не запускаются на загрузке страницы', () => {
  // Панель не должна сама ходить в сеть: единственный вызов — кнопка.
  assert.equal(src.includes("runDiagnostics(['keys'"), true);
  assert.doesNotMatch(src, /\n\s*showDiagnostics\(\);\s*\n/,
    'модалка не открывается автоматически при загрузке');
});
