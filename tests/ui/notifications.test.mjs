// UI unit tests for the notification settings (popover + two sounds + storage).
//
// Run with: node --test "tests/ui/notifications.test.mjs"
//
// Same harness as the other UI suites: the production functions are sliced out
// of static/js/app.js and evaluated against hand-written DOM / localStorage /
// Web Audio stubs, so no browser is needed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

// Ключ хранения берём из боевого кода: тест не должен заводить свой.
const NOTIFY_KEY = "notifications_settings";

// Slice a full function (balanced braces) from the production bundle.
function grab(name) {
  let i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  if (i >= 6 && src.slice(i - 6, i) === 'async ') i -= 6;
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
}

function grabConst(name) {
  const i = src.indexOf('const ' + name + ' =');
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  return src.slice(i, src.indexOf(';', i) + 1);
}

// ── Minimal DOM stub ─────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const attrs = {};
  const el = {
    id, value: '', textContent: '', hidden: false, disabled: false, title: '',
    style: {}, children: [],
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      contains: c => classes.has(c),
      toggle: (c, on) => {
        const want = on === undefined ? !classes.has(c) : !!on;
        if (want) classes.add(c); else classes.delete(c);
        return want;
      },
    },
    _classes: classes,
    // className — как в настоящем DOM: замена строки переписывает набор классов.
    get className() { return [...classes].join(' '); },
    set className(v) {
      classes.clear();
      String(v || '').split(/\s+/).filter(Boolean).forEach(c => classes.add(c));
    },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    getAttribute: k => (k in attrs ? attrs[k] : null),
    _focused: false,
    focus() { el._focused = true; },
    contains: () => false,
    appendChild(c) { el.children.push(c); return c; },
    remove() {},
  };
  return el;
}

const IDS = ['btn-notify', 'notify-icon', 'notify-txt', 'notify-pop', 'notify-master',
             'notify-city', 'notify-search', 'notify-save', 'notify-perm-hint'];
const els = {};
for (const id of IDS) els[id] = mkEl(id);
els['notify-pop'].hidden = true;

const listeners = {};
globalThis.document = {
  getElementById: id => els[id] || null,
  createElement: () => mkEl('dyn'),
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  title: '',
};
globalThis.window = {};

// ── localStorage stub ────────────────────────────────────────
const store = new Map();
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};

// ── toast / plural helpers the sliced code may call ──────────
const toasts = [];
globalThis.showToast = (msg, type) => toasts.push({ msg, type });
globalThis.pluralNum = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
};

// ── Web Audio + Notification stubs ───────────────────────────
const scheduled = [];      // notes handed to the oscillators
let ctxCreated = 0;
globalThis.AudioContext = function FakeAudioContext() {
  ctxCreated++;
  const ctx = {
    state: 'suspended', currentTime: 5,
    destination: {}, _resumes: 0,
    resume() { ctx._resumes++; ctx.state = 'running'; },
    createOscillator() {
      const osc = {
        type: '', frequency: { value: 0 }, connect() {},
        start(at) { scheduled.push({ freq: osc.frequency.value, at, type: osc.type }); },
        stop() {},
      };
      return osc;
    },
    createGain() {
      return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} };
    },
  };
  globalThis.__lastCtx = ctx;
  return ctx;
};

const windowsShown = [];
let permission = 'granted';// app.js берёт конструктор из window, а сам вызов — глобальный: в реальном
// браузере это один и тот же объект, в заглушке надо выставить оба.
globalThis.window.AudioContext = globalThis.AudioContext;

globalThis.Notification = function FakeNotification(title, opts) {
  windowsShown.push({ title, body: (opts || {}).body });
};
globalThis.Notification.permission = permission;
globalThis.window.Notification = globalThis.Notification;

// ── Slice the code under test ────────────────────────────────
const fns = [
  '_notifyFlag', 'loadNotifySettings', 'saveNotifySettings', '_syncNotifyGlobals',
  'notifyAllowed', 'notifyState', 'notifyStateLabel', 'notifyStateTitle',
  'updateNotifyBtn', '_renderNotifyPermHint', 'sendNotification', 'fmtDuration',
  '_notifyOrgWord', '_notifyBoth', 'notifyCityComplete', 'notifySearchComplete',
  '_renderNotifyPopover', '_setSwitch', '_syncSubSwitches', 'notifyDraftDirty',
  '_syncNotifySaveBtn', 'toggleNotifySetting', 'toggleNotifyPopover',
  'openNotifyPopover', 'closeNotifyPopover', 'saveNotifySettingsFromPopover',
  'toggleNotifications', 'audioCtx', 'unlockAudio', '_tone', '_chime',
  'playCityDoneSound', 'playDoneSound',
  '_notifyOutsideClick', '_notifyEscape',
];
(0, eval)(fns.map(grab).join('\n') + '\n'
  + ['NOTIFY_KEY', 'NOTIFY_DEFAULTS'].map(grabConst).join('\n'));

// Module state the sliced functions close over — pre-seeded as globals.
globalThis.notifySettings = { enabled: true, city_complete: true, search_complete: true };
globalThis.notifyDraft = Object.assign({}, globalThis.notifySettings);
globalThis._notifyHintShown = false;
globalThis._audioCtx = null;
globalThis.notificationsEnabled = true;

function reset(permissionValue = 'granted', stored = null) {
  store.clear();
  if (stored !== null) store.set(NOTIFY_KEY, stored);
  globalThis.notificationsEnabled = true;
  globalThis._notifyHintShown = false;
  globalThis._audioCtx = null;
  scheduled.length = 0;
  windowsShown.length = 0;
  toasts.length = 0;
  ctxCreated = 0;
  globalThis.Notification.permission = permissionValue;
  for (const id of IDS) {
    els[id].textContent = '';
    els[id].disabled = false;
    els[id].hidden = false;
    els[id].title = '';
    els[id]._focused = false;
    els[id]._classes.clear();
    els[id].contains = () => false;
  }
  // …после общего сброса: попап закрыт, подсказка скрыта.
  els['notify-pop'].hidden = true;
  els['notify-perm-hint'].hidden = true;
}

// ── 1. Хранение настроек ─────────────────────────────────────
test('ключ хранения — ровно notifications_settings', () => {
  assert.match(grabConst('NOTIFY_KEY'), new RegExp("'" + NOTIFY_KEY + "'"));
});

test('без сохранённых настроек берутся дефолты (всё включено)', () => {
  reset('granted', null);
  const s = loadNotifySettings();
  assert.deepEqual(s, { enabled: true, city_complete: true, search_complete: true });
  assert.equal(notificationsEnabled, true, 'мастер-флаг синхронизирован');
});

test('битый JSON в localStorage не ломает уведомления', () => {
  reset('granted', '{это не json');
  assert.deepEqual(loadNotifySettings(),
    { enabled: true, city_complete: true, search_complete: true });
});

test('частичные и неверные типы нормализуются к дефолтам по полю', () => {
  reset('granted', JSON.stringify({ enabled: false, city_complete: 'да' }));
  assert.deepEqual(loadNotifySettings(),
    { enabled: false, city_complete: true, search_complete: true });
});

test('массив вместо объекта игнорируется целиком', () => {
  reset('granted', '[1,2,3]');
  assert.deepEqual(loadNotifySettings(),
    { enabled: true, city_complete: true, search_complete: true });
});

test('сохранение пишет ровно ключ notifications_settings и нужную форму', () => {
  reset();
  notifySettings = { enabled: true, city_complete: false, search_complete: true };
  saveNotifySettings();
  assert.equal(store.has(NOTIFY_KEY), true);
  assert.deepEqual(JSON.parse(store.get(NOTIFY_KEY)),
    { enabled: true, city_complete: false, search_complete: true });
  assert.equal(notificationsEnabled, true);
});

test('настройки переживают перезагрузку (save → load)', () => {
  reset();
  notifySettings = { enabled: true, city_complete: false, search_complete: false };
  saveNotifySettings();
  notifySettings = { enabled: false, city_complete: true, search_complete: true };
  assert.deepEqual(loadNotifySettings(),
    { enabled: true, city_complete: false, search_complete: false });
});

test('недоступный localStorage — работаем на дефолтах и не падаем', () => {
  reset();
  const saved = globalThis.localStorage;
  globalThis.localStorage = undefined;
  try {
    assert.deepEqual(loadNotifySettings(),
      { enabled: true, city_complete: true, search_complete: true });
    assert.doesNotThrow(() => saveNotifySettings());
  } finally {
    globalThis.localStorage = saved;
  }
});

// ── 2. Гейт типов ────────────────────────────────────────────
test('notifyAllowed учитывает мастер и тип уведомления', () => {
  reset();
  const cases = [
    [{ enabled: true,  city_complete: true,  search_complete: true },  [true, true]],
    [{ enabled: true,  city_complete: false, search_complete: true },  [false, true]],
    [{ enabled: true,  city_complete: true,  search_complete: false }, [true, false]],
    [{ enabled: false, city_complete: true,  search_complete: true },  [false, false]],
  ];
  for (const [settings, [city, search]] of cases) {
    notifySettings = settings;
    _syncNotifyGlobals();
    assert.equal(notifyAllowed('city_complete'), city, JSON.stringify(settings));
    assert.equal(notifyAllowed('search_complete'), search, JSON.stringify(settings));
  }
});

test('состояние и подпись кнопки отражают, какие типы включены', () => {
  reset();
  const cases = [
    [{ enabled: false, city_complete: true,  search_complete: true },  'all_off', 'Уведомления выкл.'],
    [{ enabled: true,  city_complete: true,  search_complete: false }, 'partial', 'Уведомления: города'],
    [{ enabled: true,  city_complete: false, search_complete: true },  'partial', 'Уведомления: поиск'],
    [{ enabled: true,  city_complete: true,  search_complete: true },  'all_on',  'Уведомления вкл.'],
  ];
  for (const [settings, state, label] of cases) {
    notifySettings = settings;
    assert.equal(notifyState(), state, JSON.stringify(settings));
    assert.equal(notifyStateLabel(), label, JSON.stringify(settings));
  }
});

test('иконка и подпись кнопки обновляются, «запрещено» даёт ⚠, но не прячет состояние', () => {
  reset('denied');
  notifySettings = { enabled: true, city_complete: true, search_complete: false };
  updateNotifyBtn();
  assert.equal(els['notify-icon'].textContent, '🔔');
  assert.match(els['notify-txt'].textContent, /Уведомления: города/);
  assert.match(els['notify-txt'].textContent, /⚠/);
  assert.equal(els['btn-notify']._classes.has('denied'), true);
  assert.match(els['btn-notify'].title, /Города: вкл · Поиск: выкл/);

  notifySettings = { enabled: false, city_complete: true, search_complete: true };
  updateNotifyBtn();
  assert.equal(els['notify-icon'].textContent, '🔕');
});

test('подсказка про разрешение объясняет, что звук работает и без окон', () => {
  reset('denied');
  _renderNotifyPermHint();
  assert.equal(els['notify-perm-hint'].hidden, false);
  assert.match(els['notify-perm-hint'].textContent, /Звук работает/);

  reset('granted');
  _renderNotifyPermHint();
  assert.equal(els['notify-perm-hint'].hidden, true, 'когда всё разрешено — подсказки нет');
});

// ── 3. Попап: черновик и сохранение ──────────────────────────
test('открытие попапа рисует сохранённые настройки, тумблеры — черновик', () => {
  reset();
  notifySettings = { enabled: true, city_complete: false, search_complete: true };
  openNotifyPopover();
  assert.equal(els['notify-pop'].hidden, false);
  assert.equal(els['notify-master'].getAttribute('aria-checked'), 'true');
  assert.equal(els['notify-city'].getAttribute('aria-checked'), 'false');
  assert.equal(els['notify-search'].getAttribute('aria-checked'), 'true');
  assert.equal(els['notify-master']._focused, true, 'фокус уходит в попап');

  toggleNotifySetting('city_complete');
  assert.equal(els['notify-city'].getAttribute('aria-checked'), 'true');
  assert.equal(notifySettings.city_complete, false, 'настройки ещё не изменены');
  assert.equal(notifyDraft.city_complete, true, 'изменение живёт в черновике');
});

test('«Сохранить» недоступна без изменений и включается после переключения', () => {
  reset();
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  openNotifyPopover();
  assert.equal(els['notify-save'].disabled, true);
  toggleNotifySetting('search_complete');
  assert.equal(els['notify-save'].disabled, false);
  toggleNotifySetting('search_complete');
  assert.equal(els['notify-save'].disabled, true, 'вернули как было — снова нечего сохранять');
});

test('выключенный мастер усыпляет подтумблеры, но их выбор помнится', () => {
  reset();
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  openNotifyPopover();
  toggleNotifySetting('enabled');                       // мастер выключен
  assert.equal(els['notify-city'].disabled, true);
  assert.equal(els['notify-search'].disabled, true);

  toggleNotifySetting('city_complete');                 // по спящему — ничего
  assert.equal(notifyDraft.city_complete, true);

  toggleNotifySetting('enabled');                       // вернули мастер
  assert.equal(els['notify-city'].disabled, false);
  assert.equal(notifyDraft.city_complete, true, 'прежний выбор типов сохранился');
});

test('сохранение применяет черновик, пишет localStorage, тостит и закрывает попап', () => {
  reset();
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  openNotifyPopover();
  toggleNotifySetting('city_complete');
  saveNotifySettingsFromPopover();

  assert.equal(notifySettings.city_complete, false);
  assert.deepEqual(JSON.parse(store.get(NOTIFY_KEY)),
    { enabled: true, city_complete: false, search_complete: true });
  assert.equal(els['notify-pop'].hidden, true);
  assert.equal(toasts.length, 1);
  assert.match(toasts[0].msg, /Настройки сохранены/);

  openNotifyPopover();
  assert.equal(els['notify-city'].getAttribute('aria-checked'), 'false', 'после переоткрытия — сохранённое');
});

test('закрытие без «Сохранить» откатывает черновик', () => {
  reset();
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  openNotifyPopover();
  toggleNotifySetting('enabled');
  closeNotifyPopover();

  assert.equal(notifySettings.enabled, true, 'настройки не тронуты');
  assert.equal(notifyDraft.enabled, true, 'черновик сброшен');
  assert.equal(els['notify-pop'].hidden, true);
  openNotifyPopover();
  assert.equal(els['notify-master'].getAttribute('aria-checked'), 'true');
});

test('Esc и клик вне попапа закрывают его, клик внутри — нет', () => {
  reset();
  openNotifyPopover();
  toggleNotifySetting('enabled');

  // клик внутри: цель «принадлежит» попапу
  els['notify-pop'].contains = () => true;
  _notifyOutsideClick({ target: {} });
  assert.equal(els['notify-pop'].hidden, false);

  // клик снаружи
  els['notify-pop'].contains = () => false;
  _notifyOutsideClick({ target: {} });
  assert.equal(els['notify-pop'].hidden, true);
  assert.equal(notifySettings.enabled, true, 'клик вне тоже откатывает черновик');

  // Esc
  openNotifyPopover();
  toggleNotifySetting('enabled');
  _notifyEscape({ key: 'Escape' });
  assert.equal(els['notify-pop'].hidden, true);
  assert.equal(notifyDraft.enabled, true);

  // другой клавишей попап не закрывается
  openNotifyPopover();
  _notifyEscape({ key: 'Enter' });
  assert.equal(els['notify-pop'].hidden, false);
});

test('повторный клик по кнопке открывает и закрывает попап', () => {
  reset();
  toggleNotifyPopover({ stopPropagation() {} });
  assert.equal(els['notify-pop'].hidden, false);
  assert.equal(els['btn-notify'].getAttribute('aria-expanded'), 'true');
  toggleNotifyPopover({ stopPropagation() {} });
  assert.equal(els['notify-pop'].hidden, true);
  assert.equal(els['btn-notify'].getAttribute('aria-expanded'), 'false');
});

test('toggleNotifications остаётся рабочим мастер-выключателем', () => {
  reset();
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  toggleNotifications();
  assert.equal(notifySettings.enabled, false);
  assert.equal(JSON.parse(store.get(NOTIFY_KEY)).enabled, false);
  toggleNotifications();
  assert.equal(notifySettings.enabled, true);
});

// ── 4. Тексты уведомлений ────────────────────────────────────
test('fmtDuration: секунды, минуты, часы', () => {
  assert.equal(fmtDuration(45), '45 сек');
  assert.equal(fmtDuration(59.4), '59 сек');
  assert.equal(fmtDuration(60), '1 мин 00 сек');       // граница: ровная минута
  assert.equal(fmtDuration(754), '12 мин 34 сек');
  assert.equal(fmtDuration(3900), '1 ч 05 мин');
  assert.equal(fmtDuration(0), '0 сек');
  assert.equal(fmtDuration(undefined), '0 сек');       // нет данных — не NaN
});

test('уведомление о городе: текст, счёт и что звук играет', () => {
  reset('granted');
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  _syncNotifyGlobals();
  const ok = notifyCityComplete({ name: 'Москва', idx: 2, total: 5, status: 'done', records: 150 });

  assert.equal(ok, true);
  assert.equal(windowsShown.length, 1);
  assert.match(windowsShown[0].title, /Город «Москва» обработан/);
  assert.match(windowsShown[0].body, /2\/5/);
  assert.match(windowsShown[0].body, /150 организаций/);
  assert.equal(scheduled.some(n => n.freq === 880), true, 'звук города сыграл');
  assert.equal(scheduled.some(n => n.freq === 523), false, 'финальная мелодия не звучит');
});

test('пропущенный город помечается, единственное число склоняется', () => {
  reset('granted');
  notifyCityComplete({ name: 'Уфа', idx: 1, total: 3, status: 'skipped', records: 1 });
  assert.match(windowsShown[0].title, /пропущен/);
  assert.match(windowsShown[0].body, /1 организация$/);
});

test('уведомление о поиске: города, найдено, время', () => {
  reset('granted');
  notifySearchComplete({ cities: 5, found: 750, seconds: 754 });
  assert.equal(windowsShown.length, 1);
  assert.match(windowsShown[0].title, /Поиск завершён/);
  assert.equal(windowsShown[0].body, 'Городов: 5 · Найдено: 750 организаций · 12 мин 34 сек');
  assert.equal(scheduled.some(n => n.freq === 523), true, 'финальная мелодия сыграла');
});

test('выключенный тип не даёт ни звука, ни окна', () => {
  reset('granted');
  notifySettings = { enabled: true, city_complete: false, search_complete: false };
  _syncNotifyGlobals();
  assert.equal(notifyCityComplete({ name: 'Москва', idx: 1, total: 1, status: 'done', records: 5 }), false);
  assert.equal(notifySearchComplete({ cities: 1, found: 5, seconds: 10 }), false);
  assert.equal(windowsShown.length, 0);
  assert.deepEqual(scheduled, []);
});

test('выключенный мастер глушит всё, даже включённые типы', () => {
  reset('granted');
  notifySettings = { enabled: false, city_complete: true, search_complete: true };
  _syncNotifyGlobals();
  assert.equal(notifyCityComplete({ name: 'Москва', idx: 1, total: 1, status: 'done', records: 5 }), false);
  assert.deepEqual(scheduled, []);
  assert.equal(windowsShown.length, 0);
});

// ── 5. Каналы: окно, тост, звук ──────────────────────────────
test('запрещённые уведомления не мешают звуку и заменяются тостом', () => {
  reset('denied');
  notifySettings = { enabled: true, city_complete: true, search_complete: true };
  _syncNotifyGlobals();
  assert.equal(notifyCityComplete({ name: 'Пермь', idx: 1, total: 2, status: 'done', records: 12 }), true);

  assert.equal(windowsShown.length, 0, 'окна нет — браузер запретил');
  assert.equal(toasts.length, 1, 'событие не потерялось: показан тост');
  assert.match(toasts[0].msg, /Город «Пермь» обработан/);
  assert.match(toasts[0].msg, /Разрешите уведомления/, 'в первом тосте есть подсказка');
  assert.equal(scheduled.some(n => n.freq === 880), true, 'звук всё равно играет');

  // второй город: подсказка уже не повторяется
  notifyCityComplete({ name: 'Тверь', idx: 2, total: 2, status: 'done', records: 3 });
  assert.equal(toasts.length, 2);
  assert.doesNotMatch(toasts[1].msg, /Разрешите уведомления/);
});

test('без Notification API звук работает, а событие уходит тостом', () => {
  reset();
  const saved = globalThis.Notification;
  // В браузере без API свойства в window просто нет — удаляем, а не зануляем.
  delete globalThis.Notification;
  delete globalThis.window.Notification;
  try {
    assert.equal(playCityDoneSound(), true, 'звук не зависит от Notification API');
    notifySettings = { enabled: true, city_complete: true, search_complete: true };
    _syncNotifyGlobals();
    notifyCityComplete({ name: 'Сочи', idx: 1, total: 1, status: 'done', records: 2 });
    assert.equal(toasts.length, 1);
    assert.match(toasts[0].msg, /Сочи/);
  } finally {
    globalThis.Notification = saved;
    globalThis.window.Notification = saved;
  }
});

// ── 6. Звуки: два разных и один контекст ─────────────────────
test('звук города и звук поиска — разные и узнаваемо различны', () => {
  reset();
  playCityDoneSound();
  const city = scheduled.map(n => n.freq);
  const cityAt = scheduled.map(n => n.at);

  reset();
  playDoneSound();
  const done = scheduled.map(n => n.freq);
  const doneAt = scheduled.map(n => n.at);

  assert.deepEqual(city, [880, 1760], 'город: «динь» с тихим обертоном');
  assert.deepEqual(done, [523, 659, 784, 1047, 2093], 'поиск: мелодия C5–E5–G5–C6 с аккордом');
  assert.equal(city.length === done.length, false);
  assert.equal(Math.max(...city) > Math.min(...done), true, 'наборы частот не пересекаются по характеру');
  const cityLen = Math.max(...cityAt) - Math.min(...cityAt);
  const doneLen = Math.max(...doneAt) - Math.min(...doneAt);
  assert.ok(doneLen > cityLen, 'финальный сигнал длиннее: ' + doneLen + ' > ' + cityLen);
});

test('аудио-контекст создаётся один раз и разблокируется жестом', () => {
  reset();
  playCityDoneSound();
  playDoneSound();
  notifyCityComplete({ name: 'Москва', idx: 1, total: 1, status: 'done', records: 1 });
  assert.equal(ctxCreated, 1, 'новый AudioContext на каждый сигнал больше не создаётся');
  assert.equal(globalThis.__lastCtx.state, 'running', 'первый сигнал сам снимает suspended');
  assert.equal(globalThis.__lastCtx._resumes, 1);
  unlockAudio();
  assert.equal(globalThis.__lastCtx._resumes, 1, 'повторно running-контекст не будим');
});

test('звук не падает, если Web Audio недоступен', () => {
  reset();
  const saved = globalThis.AudioContext;
  globalThis.AudioContext = undefined;
  globalThis.window.AudioContext = undefined;
  globalThis._audioCtx = null;
  try {
    assert.equal(playCityDoneSound(), false);
    assert.doesNotThrow(() => playDoneSound());
  } finally {
    globalThis.AudioContext = saved;
    globalThis.window.AudioContext = saved;
  }
});
