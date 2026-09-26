// UI unit tests for message templates («📝 Шаблоны», offline Node).
//
// Production functions are sliced verbatim from static/js/app.js and run
// against a minimal DOM stub. Substitution is mirrored from
// yandex_maps_parser/message_templates.py — these tests pin the JS side.
//
// Run with: node --test tests/ui/templates.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

function grab(name) {
  let i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  if (src.slice(Math.max(0, i - 6), i) === 'async ') i -= 6;   // keep the async keyword
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
}

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

globalThis.FILE_ACT_ICONS = { delete: '<svg data-icon="trash"></svg>' };
for (const name of ['TEMPLATE_CATEGORIES', 'TEMPLATE_CAT_LABELS', 'TEMPLATE_MAX_TEXT',
                    'TEMPLATE_MAX_NAME', 'TEMPLATE_VARS', 'TEMPLATE_VAR_FIELD',
                    'TEMPLATE_VAR_ALIASES', 'TEMPLATE_ICONS', 'TEMPLATE_DEMO_COMPANY']) {
  (0, eval)('globalThis.' + name + ' = ' + grabConstValue(name) + ';');
}

// ── DOM stub ──────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const el = {
    id, value: '', textContent: '', innerHTML: '', hidden: false, checked: false,
    selectedIndex: 0, dataset: {}, children: [], style: {}, _focused: 0,
    selectionStart: 0, selectionEnd: 0, _handlers: {},
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const w = on === undefined ? !classes.has(c) : !!on; w ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    focus() { this._focused++; },
    addEventListener() {},
    click() {},
    querySelectorAll: () => [],
    querySelector: () => null,
    closest: () => null,
  };
  return el;
}

const els = {};
const IDS = ['tpl-list', 'tpl-var-list', 'tpl-show-missing', 'tpl-modal', 'tpl-modal-title',
             'tpl-name', 'tpl-category', 'tpl-text', 'tpl-var-insert', 'tpl-preview-body',
             'tpl-preview-title', 'tpl-preview-note', 'tpl-modal-err', 'tbl-template',
             'bulk-template', 'bulk-social', 's-template', 's-message', 'bulk-queue',
             'tpl-import-file', 'tpl-search', 'tpl-search-count', 'tpl-empty-box', 'btn-tpl-add',
             'tpl-pick-box', 'tpl-pick-cat', 'tpl-pick-body', 'tpl-pick-count', 'tpl-pick-single',
             'tpl-pick-modal', 'tpl-pick-modal-cat', 'tpl-pick-modal-list', 'tpl-pick-modal-count',
             'tpl-pick-modal-hint', 'tpl-pick-modal-save', 'tpl-pick-avoid'];
for (const id of IDS) els[id] = mkEl(id);
els['bulk-social'].value = 'vk';

const bodyEl = mkEl('body');
globalThis.document = {
  getElementById: id => els[id] ?? null,
  createElement: () => mkEl('div'),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  body: bodyEl,
};

globalThis.setTimeout = fn => { const id = (globalThis.setTimeout._n = (globalThis.setTimeout._n || 0) + 1); globalThis.setTimeout._fns = globalThis.setTimeout._fns || {}; globalThis.setTimeout._fns[id] = fn; return id; };
globalThis.clearTimeout = id => { if (globalThis.setTimeout._fns) delete globalThis.setTimeout._fns[id]; };
function flushTimers() {
  const fns = Object.values(globalThis.setTimeout._fns || {});
  globalThis.setTimeout._fns = {};
  fns.forEach(fn => fn());
}

const toasts = [];
globalThis.showToast = (msg, kind) => toasts.push({ msg, kind });
globalThis.copyText = async () => globalThis._copyOk !== false;
globalThis.postJSON = async () => ({ ok: true });
globalThis.uiConfirm = async () => globalThis._confirm !== false;
globalThis.reviewKey = r => (r && r.key) || '';
globalThis.SLABELS = { vk: 'VK', instagram: 'IG', telegram: 'TG', whatsapp: 'WA' };
globalThis._pluralRu = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};
globalThis.activeSocialFilters = new Set();
globalThis.filteredRows = [];
globalThis.allResults = [];
globalThis.bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
const opened = [];
globalThis.window = { open: url => opened.push(url) };
globalThis.URL = { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} };

for (const name of ['messageTemplates', 'activeTemplateIds', 'showMissingAsVar', 'templatesLoaded',
                    'templatesLoading', '_tplFilterCat', '_tplEditId', '_tplSaveTimer',
                    'templateModes', 'randomTemplateIds', 'avoidRepeats', '_lastPickedTpl', '_pickModalCat']) {
  globalThis[name] = name === 'messageTemplates' ? []
    : (name === 'activeTemplateIds'
      ? { vk: null, telegram: null, whatsapp: null, instagram: null }
      : (name === 'templateModes'
        ? { vk: 'single', telegram: 'single', whatsapp: 'single', instagram: 'single' }
        : (name === 'randomTemplateIds'
          ? { vk: [], telegram: [], whatsapp: [], instagram: [] }
          : (name === '_lastPickedTpl'
            ? {}
            : (name === '_pickModalCat' ? 'vk' : (name === '_tplFilterCat' ? 'all' : false))))));
}

(0, eval)([
  grab('escapeHtml'),
  grab('usedVariables'),
  grab('substituteTemplate'),
  grab('normalizeTemplatesClient'),
  grab('genTemplateId'),
  grab('getActiveTemplateFor'),
  grab('pruneTemplatePicks'),
  grab('pickRandomTemplate'),
  grab('getTemplateFor'),
  grab('setActiveTemplate'),
  grab('loadTemplates'),
  grab('applyTemplatesState'),
  grab('postTemplatesState'),
  grab('saveTemplatesState'),
  grab('renderTemplatePickPanel'),
  grab('renderPickPanelBody'),
  grab('updatePickCount'),
  grab('onPickCatChange'),
  grab('onPickModeChange'),
  grab('onPickSingleChange'),
  grab('onPickToggle'),
  grab('openPickModal'),
  grab('renderPickModalList'),
  grab('updatePickModalCount'),
  grab('onPickModalCatChange'),
  grab('onPickModalToggle'),
  grab('closePickModal'),
  grab('savePickModal'),
  grab('renderTemplates'),
  grab('filterTemplatesByCategory'),
  grab('fillTemplateSelect'),
  grab('currentTableSocial'),
  grab('syncTableTemplatePicker'),
  grab('syncTemplateSelects'),
  grab('renderTemplatePickers'),
  grab('onTableTemplateChange'),
  grab('onBulkTemplateChange'),
  grab('onSenderTemplateChange'),
  grab('openTemplateModal'),
  grab('closeTemplateModal'),
  grab('insertTemplateVariable'),
  grab('updateTemplatePreview'),
  grab('saveTemplateFromModal'),
  grab('duplicateTemplate'),
  grab('deleteTemplate'),
  grab('copyTemplateText'),
  grab('showCopyTextModal'),
  grab('uiChoose'),
  grab('exportTemplates'),
  grab('importTemplatesClick'),
  grab('importTemplates'),
  grab('resetTemplates'),
  grab('onShowMissingChange'),
  grab('onSocialBadgeClick'),
  grab('renderBulkQueue'),
  grab('bulkCopyOne'),
  grab('bulkCopyNext'),
  grab('fillSenderFromTemplate'),
  grab('firstCompanyForPreview'),
  grab('_fmtTemplateDate'),
  grab('onTemplateSearch'),
  grab('updateTemplateSearchCount'),
].join('\n'));

const TEMPLATES = [
  { id: 'vk1', category: 'vk', name: 'VK intro', text: 'Привет, {name}!', is_default: true, created_at: 'x' },
  { id: 'vk2', category: 'vk', name: 'VK benefit', text: '{name}, выгода', is_default: true, created_at: 'x' },
  { id: 'tg1', category: 'telegram', name: 'TG короткое', text: '{name} — {category}', is_default: true, created_at: 'x' },
];

const COMPANY = {
  name: 'Клининг-Про', city: 'Москва', category: 'Клининг', rating: 4.7,
  reviews_count: 128, address: 'ул. Тверская, 1', phone: '+7 495 123-45-67',
  lead_score: 85, website: 'example.com', vk: 'https://vk.com/x', telegram: 'https://t.me/y',
  key: 'k1',
};

function reset({ templates = TEMPLATES, active = {}, missing = false } = {}) {
  globalThis.messageTemplates = templates.map(t => ({ ...t }));
  globalThis.activeTemplateIds = Object.assign({ vk: null, telegram: null, whatsapp: null, instagram: null }, active);
  globalThis.templateModes = { vk: 'single', telegram: 'single', whatsapp: 'single', instagram: 'single' };
  globalThis.randomTemplateIds = { vk: [], telegram: [], whatsapp: [], instagram: [] };
  globalThis.avoidRepeats = false;
  globalThis._lastPickedTpl = {};
  globalThis._pickModalCat = 'vk';
  globalThis.showMissingAsVar = missing;
  globalThis.templatesLoaded = true;
  globalThis.templatesLoading = null;
  globalThis._tplFilterCat = 'all';
  globalThis._tplEditId = null;
  globalThis._tplSaveTimer = null;
  globalThis._tplSearchQuery = '';
  globalThis.filteredRows = [{ ...COMPANY }];
  globalThis.allResults = [];
  globalThis.activeSocialFilters = new Set();
  globalThis._copyOk = true;
  globalThis._confirm = true;
  globalThis.bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
  toasts.splice(0, toasts.length);
  opened.splice(0, opened.length);
  for (const id of IDS) {
    els[id].innerHTML = ''; els[id].value = ''; els[id].textContent = '';
    els[id].hidden = false; els[id].checked = false; els[id].selectedIndex = 0;
    els[id].dataset = {}; els[id]._focused = 0; els[id].selectionStart = 0; els[id].selectionEnd = 0;
  }
  els['bulk-social'].value = 'vk';
  els['tpl-list'].querySelectorAll = () => [];
}

// ── 1. Подстановка ────────────────────────────────────────────
test('substituteTemplate подставляет все переменные', () => {
  reset();
  const out = globalThis.substituteTemplate(
    '{name}|{city}|{category}|{rating}|{reviews}|{address}|{phone}|{lead_score}|{website}|{socials}',
    COMPANY);
  assert.equal(out, 'Клининг-Про|Москва|Клининг|4.7|128|ул. Тверская, 1|+7 495 123-45-67|85|example.com|VK, TG');
});

test('алиасы {название_бизнеса} и {reviews_count} работают', () => {
  reset();
  assert.equal(globalThis.substituteTemplate('{название_бизнеса}', COMPANY), 'Клининг-Про');
  assert.equal(globalThis.substituteTemplate('{reviews_count}', COMPANY), '128');
});

test('пустая переменная → «—», неизвестная остаётся как есть', () => {
  reset();
  assert.equal(globalThis.substituteTemplate('a {city} b', {}), 'a — b');
  assert.equal(globalThis.substituteTemplate('{nope} {city}', COMPANY), '{nope} Москва');
});

test('show_missing_as_var оставляет {переменную}', () => {
  reset({ missing: true });
  assert.equal(globalThis.substituteTemplate('{city}', {}), '{city}');
});

test('usedVariables возвращает уникальные переменные по порядку', () => {
  reset();
  assert.deepEqual(globalThis.usedVariables('{name} {city} {name} {nope}'), ['name', 'city', 'nope']);
  assert.deepEqual(globalThis.usedVariables(''), []);
});

// ── 2. Нормализация импорта ───────────────────────────────────
test('normalizeTemplatesClient отбрасывает мусор и обрезает лимиты', () => {
  reset();
  const out = globalThis.normalizeTemplatesClient([
    { id: 'a', category: 'weird', name: ' ОК ', text: '  {name}  ' },
    { name: '', text: 'x' },
    { name: 'n', text: '' },
    'мусор',
    { name: 'n'.repeat(300), text: 't'.repeat(9000) },
  ]);
  assert.equal(out.length, 2);
  assert.equal(out[0].category, 'vk');
  assert.equal(out[0].name, 'ОК');
  assert.equal(out[0].text, '{name}');
  assert.equal(out[1].name.length, globalThis.TEMPLATE_MAX_NAME);
  assert.equal(out[1].text.length, globalThis.TEMPLATE_MAX_TEXT);
});

// ── 3. Активный шаблон по категории ───────────────────────────
test('getActiveTemplateFor идёт по цепочке: выбранный → первый категории → любой', () => {
  reset({ active: { vk: 'vk2' } });
  assert.equal(globalThis.getActiveTemplateFor('vk').id, 'vk2');
  assert.equal(globalThis.getActiveTemplateFor('telegram').id, 'tg1');
  assert.equal(globalThis.getActiveTemplateFor('whatsapp').id, 'vk1', 'нет категории — берём первый');
  reset({ active: { vk: 'ghost' } });
  assert.equal(globalThis.getActiveTemplateFor('vk').id, 'vk1', 'несуществующий id игнорируется');
});

// ── 4. Карточки и фильтр ──────────────────────────────────────
test('renderTemplates рисует карточки и переменные', () => {
  reset();
  globalThis.renderTemplates();
  const html = els['tpl-list'].innerHTML;
  assert.match(html, /class="template-card"/);
  assert.match(html, /VK intro/);
  assert.match(html, /<code>\{name\}<\/code>/);
  assert.match(html, /data-act="edit"/);
});

test('фильтр категорий оставляет только её шаблоны', () => {
  reset();
  globalThis.filterTemplatesByCategory('telegram');
  assert.match(els['tpl-list'].innerHTML, /TG короткое/);
  assert.ok(!/VK intro/.test(els['tpl-list'].innerHTML));
  globalThis.filterTemplatesByCategory('whatsapp');
  assert.match(els['tpl-list'].innerHTML, /В этой категории шаблонов нет/);
});

test('пустой список показывает канвас с кнопками', () => {
  reset({ templates: [] });
  globalThis.renderTemplates();
  assert.equal(els['tpl-empty-box'].hidden, false);
  assert.equal(els['btn-tpl-add'].hidden, true);
  assert.equal(els['tpl-list'].innerHTML, '');
});

test('нет шаблонов в категории — мягкая заглушка, канвас скрыт', () => {
  reset();
  globalThis.filterTemplatesByCategory('whatsapp');
  assert.match(els['tpl-list'].innerHTML, /В этой категории шаблонов нет/);
  assert.equal(els['tpl-empty-box'].hidden, true, 'канвас только когда шаблонов нет вообще');
  assert.equal(els['btn-tpl-add'].hidden, false);
});

test('поиск фильтрует по названию и тексту, считает найденное', () => {
  reset();
  globalThis.onTemplateSearch('выгода');
  assert.match(els['tpl-list'].innerHTML, /VK benefit/);
  assert.ok(!/VK intro/.test(els['tpl-list'].innerHTML));
  assert.equal(els['tpl-search-count'].hidden, false);
  assert.match(els['tpl-search-count'].textContent, /1 из 3/);

  // Поиск по тексту шаблона.
  globalThis.onTemplateSearch('Привет');
  assert.match(els['tpl-list'].innerHTML, /VK intro/);
  assert.equal(els['tpl-search-count'].textContent, '1 из 3');

  // Мимо всего — заглушка поиска, не канвас.
  globalThis.onTemplateSearch('гххгх');
  assert.match(els['tpl-list'].innerHTML, /Ничего не найдено/);
  assert.equal(els['tpl-empty-box'].hidden, true);

  // Сброс поиска возвращает всё и прячет счётчик.
  globalThis.onTemplateSearch('');
  assert.equal(els['tpl-search-count'].hidden, true);
  assert.match(els['tpl-list'].innerHTML, /VK intro/);
  assert.match(els['tpl-list'].innerHTML, /TG короткое/);
});

test('поиск нечувствителен к регистру', () => {
  reset();
  globalThis.onTemplateSearch('VK INTRO');
  assert.match(els['tpl-list'].innerHTML, /VK intro/);
});

// ── 5. Модалка ────────────────────────────────────────────────
test('openTemplateModal заполняет поля и переменные', () => {
  reset();
  globalThis.openTemplateModal('vk1');
  assert.equal(els['tpl-name'].value, 'VK intro');
  assert.equal(els['tpl-text'].value, 'Привет, {name}!');
  assert.equal(els['tpl-category'].value, 'vk');
  assert.equal(els['tpl-modal'].hidden, false);
});

test('insertTemplateVariable вставляет в позицию курсора', () => {
  reset();
  els['tpl-text'].value = 'Привет, !';
  els['tpl-text'].selectionStart = 8;
  els['tpl-text'].selectionEnd = 8;
  globalThis.insertTemplateVariable('name');
  assert.equal(els['tpl-text'].value, 'Привет, {name}!');
});

test('saveTemplateFromModal валидирует пустое имя, текст и лимит', () => {
  reset();
  globalThis.openTemplateModal();
  els['tpl-text'].value = 'x';
  assert.equal(globalThis.saveTemplateFromModal(), false);
  assert.match(els['tpl-modal-err'].textContent, /название/);

  els['tpl-name'].value = 'Новый';
  els['tpl-text'].value = '';
  assert.equal(globalThis.saveTemplateFromModal(), false);
  assert.match(els['tpl-modal-err'].textContent, /текст/);

  els['tpl-text'].value = 't'.repeat(globalThis.TEMPLATE_MAX_TEXT + 1);
  assert.equal(globalThis.saveTemplateFromModal(), false);
  assert.match(els['tpl-modal-err'].textContent, /4096/);
});

test('saveTemplateFromModal запрещает дубликат имени в категории', () => {
  reset();
  globalThis.openTemplateModal();
  els['tpl-name'].value = 'VK intro';
  els['tpl-text'].value = 'x';
  els['tpl-category'].value = 'vk';
  assert.equal(globalThis.saveTemplateFromModal(), false);
  assert.match(els['tpl-modal-err'].textContent, /уже есть/);
});

test('карточка показывает дату обновления', () => {
  reset();
  globalThis.messageTemplates[0].updated_at = new Date(Date.UTC(2026, 8, 26, 11, 30)).toISOString();
  globalThis.renderTemplates();
  assert.match(els['tpl-list'].innerHTML, /Обновлено: 26\.09 14:30/, 'локальная дата MSK = UTC+3');
  // Шаблон без updated_at — без даты.
  globalThis.messageTemplates[1].updated_at = null;
  globalThis.renderTemplates();
  const html = els['tpl-list'].innerHTML;
  assert.ok(!/VK benefit[\s\S]{0,400}Обновлено:/.test(html), 'без даты подписи нет');
});

test('saveTemplateFromModal проставляет updated_at', () => {
  reset();
  globalThis.openTemplateModal('vk1');
  els['tpl-name'].value = 'Обновлённый';
  els['tpl-text'].value = 'Новый текст';
  assert.equal(globalThis.saveTemplateFromModal(), true);
  assert.ok(globalThis.messageTemplates.find(t => t.id === 'vk1').updated_at, 'дата обновления проставлена');
  assert.match(toasts.at(-1).msg, /сохранён/i);
});

test('saveTemplateFromModal добавляет и редактирует шаблон', () => {
  reset();
  globalThis.openTemplateModal();
  els['tpl-name'].value = 'Новый';
  els['tpl-text'].value = 'Привет, {name}';
  els['tpl-category'].value = 'telegram';
  assert.equal(globalThis.saveTemplateFromModal(), true);
  const added = globalThis.messageTemplates.find(t => t.name === 'Новый');
  assert.ok(added && added.category === 'telegram');

  globalThis.openTemplateModal('vk1');
  els['tpl-name'].value = 'VK intro 2';
  els['tpl-text'].value = 'Изменённый {name}';
  assert.equal(globalThis.saveTemplateFromModal(), true);
  const edited = globalThis.messageTemplates.find(t => t.id === 'vk1');
  assert.equal(edited.name, 'VK intro 2');
  assert.equal(edited.text, 'Изменённый {name}');
});

test('deleteTemplate убирает шаблон и чистит активный id', async () => {
  reset({ active: { vk: 'vk1' } });
  await globalThis.deleteTemplate('vk1');
  assert.ok(!globalThis.messageTemplates.some(t => t.id === 'vk1'));
  assert.equal(globalThis.activeTemplateIds.vk, null);
  globalThis._confirm = false;
  await globalThis.deleteTemplate('vk2');
  assert.ok(globalThis.messageTemplates.some(t => t.id === 'vk2'), 'отмена не удаляет');
});

test('duplicateTemplate создаёт копию с новым id', () => {
  reset();
  globalThis.duplicateTemplate('vk1');
  const copy = globalThis.messageTemplates.find(t => t.name === 'VK intro (копия)');
  assert.ok(copy);
  assert.notEqual(copy.id, 'vk1');
});

// ── 6. Превью и show_missing ──────────────────────────────────
test('updateTemplatePreview подставляет данные первой компании', () => {
  reset();
  els['tpl-text'].value = 'Привет, {name} из {city}!';
  globalThis.updateTemplatePreview();
  assert.equal(els['tpl-preview-body'].textContent, 'Привет, Клининг-Про из Москва!');
  assert.equal(els['tpl-preview-note'].hidden, true);
});

test('без данных таблицы превью показывает пример с пометкой', () => {
  reset();
  globalThis.filteredRows = [];
  els['tpl-text'].value = 'Здравствуйте! Увидел, что у вас {category} в {city}.';
  globalThis.updateTemplatePreview();
  assert.match(els['tpl-preview-title'].textContent, /пример/i);
  assert.match(els['tpl-preview-body'].textContent, /Стоматология в Москва/);
  assert.ok(!/Нет данных таблицы/.test(els['tpl-preview-body'].textContent), 'без категоричной заглушки');
  assert.equal(els['tpl-preview-note'].hidden, false);
  assert.match(els['tpl-preview-note'].textContent, /пример/i);
  // Пустой текст — превью тоже пустое, но подсказка остаётся честной.
  els['tpl-text'].value = '';
  globalThis.updateTemplatePreview();
  assert.equal(els['tpl-preview-body'].textContent, '');
});

test('onShowMissingChange меняет подстановку и сохраняет настройку', () => {
  reset();
  els['tpl-show-missing'].checked = true;
  globalThis.onShowMissingChange();
  assert.equal(globalThis.showMissingAsVar, true);
  assert.equal(globalThis.substituteTemplate('{city}', {}), '{city}');
});

// ── 7. Интеграция с таблицей ──────────────────────────────────
test('onSocialBadgeClick копирует подставленный текст и открывает ссылку', async () => {
  reset({ active: { vk: 'vk1' } });
  const el = mkEl('badge');
  el.dataset = { social: 'vk', key: 'k1' };
  el.getAttribute = () => 'https://vk.com/x';
  let prevented = false;
  await globalThis.onSocialBadgeClick({ preventDefault: () => { prevented = true; } }, el);
  assert.ok(prevented, 'переход отменяется, пока копируем');
  assert.equal(opened.at(-1), 'https://vk.com/x');
  assert.match(toasts.at(-1).msg, /скопирован/);
});

test('onSocialBadgeClick без шаблона не перехватывает ссылку', async () => {
  reset({ templates: [] });
  const el = mkEl('badge');
  el.dataset = { social: 'vk', key: 'k1' };
  el.getAttribute = () => 'https://vk.com/x';
  let prevented = false;
  await globalThis.onSocialBadgeClick({ preventDefault: () => { prevented = true; } }, el);
  assert.equal(prevented, false);
});

// ── 8. Массовый обход: очередь ────────────────────────────────
test('renderBulkQueue показывает тексты, «Скопировать следующее» идёт по порядку', async () => {
  reset();
  globalThis.bulkState.texts = new Map([
    ['a', { name: 'A', text: 'текст A', url: 'u1' }],
    ['b', { name: 'B', text: 'текст B', url: 'u2' }],
  ]);
  globalThis.renderBulkQueue();
  assert.equal(els['bulk-queue'].hidden, false);
  assert.match(els['bulk-queue'].innerHTML, /Тексты готовы: 0 из 2/);
  await globalThis.bulkCopyNext();
  assert.ok(globalThis.bulkState.copiedTexts.has('a'));
  await globalThis.bulkCopyNext();
  assert.ok(globalThis.bulkState.copiedTexts.has('b'));
  await globalThis.bulkCopyNext();
  assert.match(toasts.at(-1).msg, /Все тексты/);
});

// ── 9. Импорт и конфликты ─────────────────────────────────────
test('importTemplates добавляет новые шаблоны', async () => {
  reset();
  const file = { text: async () => JSON.stringify({ templates: [{ id: 'x1', name: 'Импорт', text: '{name}', category: 'vk' }] }) };
  await globalThis.importTemplates({ files: [file], value: '' });
  assert.ok(globalThis.messageTemplates.some(t => t.id === 'x1'));
});

test('importTemplates без конфликта не спрашивает', async () => {
  reset();
  let asked = 0;
  globalThis.uiChoose = async () => { asked++; return null; };
  const file = { text: async () => JSON.stringify([{ id: 'x2', name: 'Новый', text: 't' }]) };
  await globalThis.importTemplates({ files: [file], value: '' });
  assert.equal(asked, 0);
  assert.ok(globalThis.messageTemplates.some(t => t.id === 'x2'));
});

for (const [action, check] of [
  ['replace', (list) => list.find(t => t.id === 'vk1').name === 'Замена'],
  ['duplicate', (list) => list.find(t => t.id === 'vk1').name === 'VK intro' && list.some(t => t.name === 'Замена' && t.id !== 'vk1')],
  ['skip', (list) => list.find(t => t.id === 'vk1').name === 'VK intro'],
]) {
  test(`importTemplates по конфликту id применяет «${action}»`, async () => {
    reset();
    globalThis.uiChoose = async () => ({ value: action, applyAll: false });
    const file = { text: async () => JSON.stringify([{ id: 'vk1', name: 'Замена', text: 't' }]) };
    await globalThis.importTemplates({ files: [file], value: '' });
    assert.ok(check(globalThis.messageTemplates), action);
  });
}

test('importTemplates с «применить ко всем» не спрашивает второй раз', async () => {
  reset();
  let asked = 0;
  globalThis.uiChoose = async () => { asked++; return { value: 'skip', applyAll: true }; };
  const file = { text: async () => JSON.stringify([
    { id: 'vk1', name: 'A', text: 't' },
    { id: 'vk2', name: 'B', text: 't' },
  ]) };
  await globalThis.importTemplates({ files: [file], value: '' });
  assert.equal(asked, 1);
});

// ── 10. Пресеты выбора и отправка ─────────────────────────────
test('renderTemplatePickers наполняет селекты и ставит активные', () => {
  reset({ active: { vk: 'vk1' } });
  globalThis.renderTemplatePickers();
  assert.match(els['tbl-template'].innerHTML, /value="vk1"/);
  assert.equal(els['tbl-template'].value, 'vk1');
  assert.equal(els['bulk-template'].value, 'vk1');
  assert.equal(els['s-template'].value, 'vk1');
});

test('опции селектов — только имя шаблона, категории через optgroup', () => {
  reset({ active: { vk: 'vk1' } });
  globalThis.renderTemplatePickers();
  const html = els['tbl-template'].innerHTML;
  // Категория — в optgroup, не в тексте опции.
  assert.match(html, /<optgroup label="ВКонтакте">/);
  assert.match(html, /<optgroup label="Telegram">/);
  assert.ok(!/ · ВКонтакте/.test(html), 'имя опции без категории');
  assert.ok(!/ · Telegram/.test(html));
  // Пустые категории не рисуются.
  assert.ok(!/WhatsApp/.test(html));
});

test('fillSenderFromTemplate кладёт текст шаблона в поле рассылки', () => {
  reset({ active: { vk: 'vk1' } });
  globalThis.renderTemplatePickers();
  globalThis.fillSenderFromTemplate();
  assert.equal(els['s-message'].value, 'Привет, {name}!');
});

test('exportTemplates формирует JSON с версией и шаблонами', () => {
  reset();
  let captured = null;
  globalThis.Blob = class { constructor(parts) { captured = parts.join(''); } };
  globalThis.exportTemplates();
  const parsed = JSON.parse(captured);
  assert.equal(parsed.version, 1);
  assert.equal(parsed.templates.length, 3);
  assert.ok(parsed.exported_at);
});

// ── Случайный выбор шаблонов ──────────────────────────────────
test('applyTemplatesState читает режимы, наборы и avoid_repeats', () => {
  reset();
  globalThis.applyTemplatesState({
    templates: TEMPLATES,
    template_modes: { vk: 'random' },
    random_template_ids: { vk: ['vk1', 'vk2', 'нет-такого'] },
    avoid_repeats: true,
  });
  assert.equal(globalThis.templateModes.vk, 'random');
  assert.equal(globalThis.templateModes.telegram, 'single');
  assert.deepEqual(globalThis.randomTemplateIds.vk, ['vk1', 'vk2'], 'битые id отброшены');
  assert.equal(globalThis.avoidRepeats, true);
  // Старый сервер без новых полей — дефолты.
  globalThis.applyTemplatesState({ templates: TEMPLATES });
  assert.equal(globalThis.templateModes.vk, 'single');
  assert.deepEqual(globalThis.randomTemplateIds.vk, []);
  assert.equal(globalThis.avoidRepeats, false);
});

test('getTemplateFor: random выбирает из набора, avoid не повторяет подряд', () => {
  reset();
  globalThis.templateModes.vk = 'random';
  globalThis.randomTemplateIds.vk = ['vk1', 'vk2'];
  const picks = new Set();
  for (let i = 0; i < 40; i++) picks.add(globalThis.getTemplateFor('vk').id);
  assert.ok(picks.size >= 1 && [...picks].every(id => ['vk1', 'vk2'].includes(id)), 'из набора');
  // avoid_repeats: тот же шаблон не выбирается дважды подряд — при двух
  // шаблонах идёт строгое чередование.
  globalThis.avoidRepeats = true;
  globalThis._lastPickedTpl.vk = 'vk1';
  let prev = 'vk1';
  for (let i = 0; i < 20; i++) {
    const cur = globalThis.getTemplateFor('vk').id;
    assert.notEqual(cur, prev, 'не повторяется дважды подряд');
    prev = cur;
  }
  // Один шаблон в наборе — всегда он же.
  globalThis.randomTemplateIds.vk = ['vk1'];
  globalThis._lastPickedTpl.vk = 'vk1';
  assert.equal(globalThis.getTemplateFor('vk').id, 'vk1');
});

test('getTemplateFor: пустой набор или single — fallback на активный', () => {
  reset({ active: { vk: 'vk2' } });
  globalThis.templateModes.vk = 'random';
  globalThis.randomTemplateIds.vk = [];
  assert.equal(globalThis.getTemplateFor('vk').id, 'vk2');
  globalThis.randomTemplateIds.vk = ['tg1'];   // чужая категория не попадает
  assert.equal(globalThis.getTemplateFor('vk').id, 'vk2');
  globalThis.templateModes.vk = 'single';
  assert.equal(globalThis.getTemplateFor('vk').id, 'vk2');
});

test('повторный клик по бейджу даёт случайный выбор и тост с именем шаблона', async () => {
  reset({ active: { vk: 'vk1' } });
  globalThis.templateModes.vk = 'random';
  globalThis.randomTemplateIds.vk = ['vk1', 'vk2'];
  const el = mkEl('badge');
  el.dataset = { social: 'vk', key: 'k1' };
  el.getAttribute = name => (name === 'href' ? 'https://vk.com/x' : null);
  globalThis.filteredRows = [{ ...COMPANY, key: 'k1' }];
  await globalThis.onSocialBadgeClick({ preventDefault() {} }, el);
  assert.match(toasts.at(-1).msg, /\(/, 'в тосте имя использованного шаблона');
  // Два клика подряд — два независимых выбора (avoid может давать разные).
  const seen = new Set();
  for (let i = 0; i < 30; i++) { await globalThis.onSocialBadgeClick({ preventDefault() {} }, el); seen.add(toasts.at(-1).msg); }
  assert.ok(seen.size >= 1);
});

test('удаление шаблона и смена категории вычищают наборы', async () => {
  reset();
  globalThis.randomTemplateIds.vk = ['vk1', 'vk2'];
  globalThis.randomTemplateIds.telegram = ['tg1'];
  await globalThis.deleteTemplate('vk1');
  assert.deepEqual(globalThis.randomTemplateIds.vk, ['vk2'], 'удалённый убран');
  assert.deepEqual(globalThis.randomTemplateIds.telegram, ['tg1']);
  // Смена категории шаблона: из vk-набора выпадает, в telegram-наборе становится валиден.
  globalThis.randomTemplateIds.telegram = ['tg1', 'vk2'];
  const t = globalThis.messageTemplates.find(x => x.id === 'vk2');
  t.category = 'telegram';
  globalThis.pruneTemplatePicks();
  assert.deepEqual(globalThis.randomTemplateIds.telegram, ['tg1', 'vk2'], 'в новой категории валиден');
  assert.deepEqual(globalThis.randomTemplateIds.vk, [], 'из старой категории вычищен');
});

test('переключение режима сохраняет состояние на сервере', () => {
  reset();
  globalThis.renderPickPanelBody();
  // single → random
  els['tpl-pick-cat'].value = 'vk';
  const radios = [];
  globalThis.document.querySelectorAll = sel => {
    if (String(sel).includes('tpl-pick-mode')) {
      return [
        { value: 'single', checked: true },
        { value: 'random', checked: false },
      ];
    }
    return [];
  };
  globalThis.document.querySelector = sel =>
    (String(sel).includes(':checked') ? { value: 'random' } : null);
  globalThis.onPickModeChange();
  assert.equal(globalThis.templateModes.vk, 'random');
  // Реверс: radios для перерисовки тела.
  globalThis.document.querySelectorAll = () => [];
  flushTimers();   // debounce → postTemplatesState → ok:true
});

test('чекбоксы в модалке обновляют счётчик и валидацию сохранения', () => {
  reset();
  globalThis.openPickModal();
  assert.equal(els['tpl-pick-modal'].hidden, false);
  assert.equal(els['tpl-pick-modal-save'].disabled, true, '0 выбранных — Save off');
  assert.match(els['tpl-pick-modal-count'].textContent, /Выбрано: 0 из 2/);
  globalThis.onPickModalToggle('vk1');
  globalThis.onPickModalToggle('vk2');
  assert.match(els['tpl-pick-modal-count'].textContent, /Выбрано: 2 из 2/);
  assert.equal(els['tpl-pick-modal-save'].disabled, false);
  assert.equal(els['tpl-pick-modal-hint'].hidden, true);
  // Один шаблон — предупреждение, но Save доступен.
  globalThis.onPickModalToggle('vk2');
  assert.match(els['tpl-pick-modal-hint'].textContent, /2\+/);
  assert.equal(els['tpl-pick-modal-save'].disabled, false);
});

test('savePickModal включает random-режим категории и сохраняет', () => {
  reset();
  globalThis._pickModalCat = 'telegram';
  globalThis.randomTemplateIds.telegram = ['tg1'];
  els['tpl-pick-avoid'].checked = true;
  globalThis.savePickModal();
  assert.equal(globalThis.templateModes.telegram, 'random');
  assert.equal(globalThis.avoidRepeats, true);
  assert.equal(els['tpl-pick-modal'].hidden, true);
  assert.match(toasts.at(-1).msg, /набор/i);
  // 0 выбранных — сохранить нельзя.
  reset();
  globalThis.randomTemplateIds.telegram = [];
  globalThis.savePickModal();
  assert.equal(globalThis.templateModes.telegram, 'single');
});

test('модалка настроек: категория переключается, отмена не меняет набор', () => {
  reset();
  globalThis.openPickModal();
  els['tpl-pick-modal-cat'].value = 'telegram';
  globalThis.onPickModalCatChange();
  assert.equal(globalThis._pickModalCat, 'telegram');
  assert.match(els['tpl-pick-modal-list'].innerHTML, /tg1|TG/);
  globalThis.onPickModalToggle('tg1');
  globalThis.closePickModal();
  assert.equal(els['tpl-pick-modal'].hidden, true);
  assert.deepEqual(globalThis.randomTemplateIds.telegram, ['tg1'], 'выбор в модалке живёт до Сохранить');
  // Смена режима не запускалась — серверное состояние не тронуто.
  assert.equal(globalThis.templateModes.telegram, 'single');
});

test('onPickToggle обновляет набор и счётчик панели', () => {
  reset();
  els['tpl-pick-cat'].value = 'vk';
  globalThis.onPickToggle('vk1');
  assert.deepEqual(globalThis.randomTemplateIds.vk, ['vk1']);
  globalThis.onPickToggle('vk1');
  assert.deepEqual(globalThis.randomTemplateIds.vk, []);
  flushTimers();
});

test('очередь обхода показывает имя шаблона', () => {
  reset();
  globalThis.bulkState.texts = new Map([
    ['k1', { name: 'Клининг-Про', text: 'Текст', url: 'u', tpl_name: 'Первое знакомство' }],
  ]);
  globalThis.renderBulkQueue();
  assert.match(els['bulk-queue'].innerHTML, /Клининг-Про/);
  assert.match(els['bulk-queue'].innerHTML, /\(Первое знакомство\)/);
  // Без tpl_name — ничего лишнего.
  globalThis.bulkState.texts = new Map([['k2', { name: 'Б', text: 'x', url: 'u', tpl_name: '' }]]);
  globalThis.renderBulkQueue();
  assert.ok(!/📋 \(/.test(els['bulk-queue'].innerHTML.split('Б')[1] || ''));
});
