// ═══════════════════════════════════════════════════════════════
// Хранятся на сервере (settings.json) — общие для команды. Подстановка
// переменных зеркалит yandex_maps_parser/message_templates.py: держать их
// надо синхронно, иначе текст в таблице разойдётся с рассылкой.
const TEMPLATE_CATEGORIES = ['vk', 'telegram', 'whatsapp', 'instagram'];
const TEMPLATE_CAT_LABELS = {vk: 'ВКонтакте', telegram: 'Telegram', whatsapp: 'WhatsApp', instagram: 'Instagram'};
const TEMPLATE_MAX_TEXT = 4096;
const TEMPLATE_MAX_NAME = 120;
const TEMPLATE_VARS = [
  ['name', 'название компании'],
  ['city', 'город'],
  ['category', 'категория'],
  ['rating', 'рейтинг'],
  ['reviews', 'количество отзывов'],
  ['address', 'адрес'],
  ['phone', 'телефон'],
  ['lead_score', 'оценка лида'],
  ['website', 'сайт'],
  ['socials', 'список соцсетей'],
];
const TEMPLATE_VAR_FIELD = {
  name: 'name', city: 'city', category: 'category', rating: 'rating',
  reviews: 'reviews_count', address: 'address', phone: 'phone',
  lead_score: 'lead_score', website: 'website',
};
const TEMPLATE_VAR_ALIASES = {'название_бизнеса': 'name', 'reviews_count': 'reviews'};
// Служебные переменные: значение вычисляется в момент подстановки.
// Зеркало SPECIAL_VARIABLES/_GREETING_PARTS из message_templates.py.
const TEMPLATE_SPECIAL_VARS = ['дата', 'время', 'приветствие'];
const TEMPLATE_GREETING_PARTS = [[5, 'Доброй ночи'], [12, 'Доброе утро'], [18, 'Добрый день'], [22, 'Добрый вечер'], [24, 'Доброй ночи']];
const TEMPLATE_SPECIAL_LABELS = {
  'дата': 'текущая дата (ДД.ММ.ГГГГ)',
  'время': 'текущее время (ЧЧ:ММ)',
  'приветствие': 'Доброе утро/день/вечер/ночи — по времени отправки',
};
// Встроенные имена заняты: свою переменную так назвать нельзя.
const RESERVED_VAR_NAMES = new Set(Object.keys(TEMPLATE_VAR_FIELD)
  .concat(Object.keys(TEMPLATE_VAR_ALIASES))
  .concat(['socials'])
  .concat(TEMPLATE_SPECIAL_VARS));
const TEMPLATE_MAX_VAR_NAME = 60;
// Составной шаблон: не больше вариантов и вариантов у переменной (зеркало
// MAX_VARIANTS/MAX_VAR_VARIANTS из message_templates.py).
const TEMPLATE_MAX_VARIANTS = 50;
const TEMPLATE_MAX_VAR_VARIANTS = 50;
const TEMPLATE_MAX_VAR_VALUE = 1000;
const TEMPLATE_MAX_VAR_DESC = 200;
const TEMPLATE_MAX_CUSTOM_VARS = 100;

let messageTemplates = [];
let activeTemplateIds = {vk: null, telegram: null, whatsapp: null, instagram: null};
// Отдельный выбор шаблона для «Массового обхода»: null = «— шаблон не
// выбран —» (тексты не копируются), а не тихий fallback на первый шаблон.
let bulkTemplateIds = {vk: null, telegram: null, whatsapp: null, instagram: null};
// Режим выбора: single — один шаблон, random — случайный из набора.
let templateModes = {vk: 'single', telegram: 'single', whatsapp: 'single', instagram: 'single'};
let randomTemplateIds = {vk: [], telegram: [], whatsapp: [], instagram: []};
let avoidRepeats = false;
// Последний выбранный шаблон по соцсети — для «избегать повторов» (сессия).
let _lastPickedTpl = {};
let _pickModalCat = 'vk';
let showMissingAsVar = false;
let templatesLoaded = false;
let templatesLoading = null;
let _tplFilterCat = 'all';
// Подвкладка внутри «📝 Шаблоны»: список шаблонов или управление переменными.
let _tplSubtab = 'templates';
// Выделенные шаблоны для массового удаления.
let _tplSelectedIds = new Set();
// Редактируемая переменная (id/null) в модалке переменных.
let _tplEditVarName = null;
let _tplEditId = null;
let _tplSaveTimer = null;
let _tplSearchQuery = '';
// Свои переменные шаблонов: [{name, value, column, description, created_at}].
let customVariables = [];
// Автодополнение: активный вариант и индекс в отфильтрованном списке.
let _tplAcItems = [];
let _tplAcIndex = -1;
// Примерные данные для превью, когда таблица пуста: пользователь видит,
// как шаблон выглядит с реальными значениями, а не заглушку.
const TEMPLATE_DEMO_COMPANY = {
  name: 'Стоматология «Улыбка»', city: 'Москва', category: 'Стоматология',
  rating: 4.7, reviews_count: 128, address: 'ул. Тверская, 1',
  phone: '+7 495 123-45-67', lead_score: 85, website: 'example.com',
  vk: 'https://vk.com/demo', telegram: 'https://t.me/demo',
};

function firstCompanyForPreview() {
  if (typeof filteredRows !== 'undefined' && filteredRows && filteredRows.length) return filteredRows[0];
  if (typeof allResults !== 'undefined' && allResults && allResults.length) return allResults[0];
  return null;
}

function usedVariables(text) {
  const out = [];
  // \w в JS не покрывает кириллицу, а алиас {название_бизнеса} — наш.
  const re = /\{([\wА-Яа-яЁё]+)\}/g;
  const s = String(text == null ? '' : text);
  let m;
  while ((m = re.exec(s)) !== null) {
    if (!out.includes(m[1])) out.push(m[1]);
  }
  return out;
}

function specialTemplateValue(key) {
  const now = new Date();
  const p = n => String(n).padStart(2, '0');
  if (key === 'дата') return p(now.getDate()) + '.' + p(now.getMonth() + 1) + '.' + now.getFullYear();
  if (key === 'время') return p(now.getHours()) + ':' + p(now.getMinutes());
  if (key === 'приветствие') {
    const hour = now.getHours();
    for (const [bound, form] of TEMPLATE_GREETING_PARTS) {
      if (hour < bound) return form;
    }
    return 'Добрый день';
  }
  return '';
}

// Зеркало message_templates.substitute: свои переменные приоритетнее
// встроенных (столбец — значение из записи, иначе статичный текст),
// служебные вычисляются в момент подстановки, алиасы, «—» для пустого,
// неизвестная переменная остаётся {как_есть}.
function substituteTemplate(text, company) {
  company = company || {};
  const custom = {};
  (customVariables || []).forEach(v => { if (v && v.name) custom[v.name] = v; });
  return String(text == null ? '' : text).replace(/\{([\wА-Яа-яЁё]+)\}/g, (match, key) => {
    const cv = custom[key];
    if (cv) {
      // Случайная переменная: список вариантов — случайный на каждую подстановку
      // (зеркало ветки variants в message_templates.substitute).
      const varVariants = Array.isArray(cv.variants) ? cv.variants : [];
      if (varVariants.length) {
        return String(varVariants[Math.floor(Math.random() * varVariants.length)] || '');
      }
      const v = cv.column ? company[cv.column] : cv.value;
      return (v === undefined || v === null || String(v).trim() === '')
        ? (showMissingAsVar ? match : '—') : String(v);
    }
    if (TEMPLATE_SPECIAL_VARS.includes(key)) return specialTemplateValue(key);
    const canonical = TEMPLATE_VAR_ALIASES[key] || key;
    if (canonical !== 'socials' && !(canonical in TEMPLATE_VAR_FIELD)) return match;
    let value;
    if (canonical === 'socials') {
      value = ['vk', 'telegram', 'whatsapp', 'instagram']
        .filter(k => company[k]).map(k => SLABELS[k]).join(', ');
    } else {
      value = company[TEMPLATE_VAR_FIELD[canonical]];
    }
    if (value === undefined || value === null || String(value).trim() === '') {
      return showMissingAsVar ? match : '—';
    }
    return String(value);
  });
}

function normalizeTemplatesClient(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (let i = 0; i < raw.length; i++) {
    const item = raw[i];
    if (!item || typeof item !== 'object') continue;
    const name = String(item.name || '').trim().slice(0, TEMPLATE_MAX_NAME);
    const text = String(item.text || '').trim().slice(0, TEMPLATE_MAX_TEXT);
    if (!name || !text) continue;
    const cat = TEMPLATE_CATEGORIES.includes(item.category) ? item.category : 'vk';
    // variant_ids несём как есть — валидность (своя категория, нет циклов)
    // проверяется сервером в _prune_variant_ids, а здесь только отбор мусора.
    const variantIds = Array.isArray(item.variant_ids)
      ? item.variant_ids.filter(x => typeof x === 'string').map(x => x.trim()).filter(Boolean).slice(0, TEMPLATE_MAX_VARIANTS)
      : [];
    out.push({
      id: String(item.id || '').trim() || ('tpl_' + (i + 1)),
      category: cat, name, text,
      variant_ids: [...new Set(variantIds)],
      is_default: !!item.is_default,
      created_at: item.created_at || new Date().toISOString(),
      updated_at: item.updated_at || null,
    });
  }
  return out;
}

function genTemplateId() {
  return 'tpl_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);
}

// Шаблон удалён или переехал в другую категорию — вычищаем его из наборов
// случайного выбора и из активных (не дожидаясь нормализации сервера).
function pruneTemplatePicks() {
  const alive = new Set(messageTemplates.map(t => t.id));
  // Составные шаблоны: вычистить ссылки на удалённые/чужой категории
  // (не дожидаясь нормализации сервера).
  messageTemplates.forEach(t => {
    if (Array.isArray(t.variant_ids) && t.variant_ids.length) {
      t.variant_ids = t.variant_ids.filter(vid => {
        // Самоссылка недопустима: составной шаблон не включает себя.
        if (vid === t.id) return false;
        const inner = messageTemplates.find(x => x.id === vid);
        return inner && inner.category === t.category;
      });
    }
  });
  TEMPLATE_CATEGORIES.forEach(c => {
    randomTemplateIds[c] = (randomTemplateIds[c] || []).filter(id =>
      alive.has(id) && (messageTemplates.find(t => t.id === id) || {}).category === c);
    if (activeTemplateIds[c]) {
      const t = messageTemplates.find(x => x.id === activeTemplateIds[c]);
      if (!t || t.category !== c) activeTemplateIds[c] = null;
    }
    if (bulkTemplateIds[c]) {
      const t = messageTemplates.find(x => x.id === bulkTemplateIds[c]);
      if (!t || t.category !== c) bulkTemplateIds[c] = null;
    }
  });
}

// Раскрытие составного шаблона (зеркало resolve_variant_text из
// message_templates.py): рекурсивно поднимаемся по вариантам с защитой от
// циклов. Живых вариантов нет — null (вызывающий использует собственный text).
function resolveVariantText(template) {
  const byId = {};
  messageTemplates.forEach(t => { byId[t.id] = t; });
  const seen = new Set();
  let cur = template;
  let composite = false;
  while (cur && Array.isArray(cur.variant_ids) && cur.variant_ids.length) {
    composite = true;
    if (seen.has(cur.id)) return null; // цикл — невалидно
    seen.add(cur.id);
    const pool = cur.variant_ids
      .map(vid => byId[vid])
      .filter(t => t && t.category === template.category);
    if (!pool.length) return null;
    cur = pool[Math.floor(Math.random() * pool.length)];
  }
  // Не составной (или битые варианты) — null: вызывающий использует
  // собственный текст (семантика resolve_variant_text на сервере).
  return composite ? String((cur && cur.text) || '') : null;
}

// Единая точка получения текста шаблона для копирования: составной —
// случайно один из вложенных, иначе собственный текст.
function templateTextForCopy(tpl) {
  if (!tpl) return '';
  return resolveVariantText(tpl) || String(tpl.text || '');
}

// Активный шаблон категории → первый её шаблон → первый вообще.
function getActiveTemplateFor(social) {
  const id = activeTemplateIds[social];
  if (id) {
    const t = messageTemplates.find(x => x.id === id);
    if (t) return t;
  }
  return messageTemplates.find(t => t.category === social) || messageTemplates[0] || null;
}

// Шаблон для массового обхода: только явно выбранный, без fallback.
function getBulkTemplateFor(social) {
  const id = bulkTemplateIds[social];
  if (!id) return null;
  return messageTemplates.find(x => x.id === id) || null;
}

// ── Случайный выбор шаблона ────────────────────────────────────
// Зеркало message_templates.pick_random_text: с avoid_repeats последний
// использованный исключается; исключение опустошило набор (один шаблон) —
// выбор из полного набора.
function pickRandomTemplate(social) {
  const ids = randomTemplateIds[social] || [];
  const pool = messageTemplates.filter(t => ids.includes(t.id) && t.category === social);
  if (!pool.length) return null;
  let candidates = pool;
  if (avoidRepeats && pool.length > 1 && _lastPickedTpl[social]) {
    const reduced = pool.filter(t => t.id !== _lastPickedTpl[social]);
    if (reduced.length) candidates = reduced;
  }
  const picked = candidates[Math.floor(Math.random() * candidates.length)];
  _lastPickedTpl[social] = picked.id;
  return picked;
}

// Шаблон для клика/обхода/рассылки: random-режим — случайный из набора,
// иначе активный. Набор пуст или шаблоны удалены — fallback на активный.
function getTemplateFor(social) {
  if (templateModes[social] === 'random') {
    const picked = pickRandomTemplate(social);
    if (picked) return picked;
  }
  return getActiveTemplateFor(social);
}

function setActiveTemplate(social, id) {
  if (!TEMPLATE_CATEGORIES.includes(social)) return;
  activeTemplateIds[social] = id || null;
  saveTemplatesState();
}

function loadTemplates() {
  if (templatesLoaded) return Promise.resolve(messageTemplates);
  if (templatesLoading) return templatesLoading;
  templatesLoading = fetch('/templates')
    .then(r => r.json())
    .then(j => {
      applyTemplatesState(j || {});
      templatesLoaded = true;
      templatesLoading = null;
      return messageTemplates;
    })
    .catch(() => { templatesLoading = null; return messageTemplates; });
  return templatesLoading;
}

function applyTemplatesState(j) {
  messageTemplates = Array.isArray(j.templates) ? j.templates : [];
  customVariables = Array.isArray(j.custom_variables) ? j.custom_variables : [];
  const ids = {vk: null, telegram: null, whatsapp: null, instagram: null};
  if (j.active_template_ids && typeof j.active_template_ids === 'object') {
    TEMPLATE_CATEGORIES.forEach(c => { ids[c] = j.active_template_ids[c] || null; });
  }
  activeTemplateIds = ids;
  const bulkIds = {vk: null, telegram: null, whatsapp: null, instagram: null};
  if (j.bulk_active_template_ids && typeof j.bulk_active_template_ids === 'object') {
    TEMPLATE_CATEGORIES.forEach(c => { bulkIds[c] = j.bulk_active_template_ids[c] || null; });
  }
  bulkTemplateIds = bulkIds;
  // Режимы и наборы случайного выбора: сервер прислал — берём, иначе дефолты.
  templateModes = TEMPLATE_CATEGORIES.reduce((acc, c) => {
    acc[c] = (j.template_modes && j.template_modes[c] === 'random') ? 'random' : 'single';
    return acc;
  }, {});
  randomTemplateIds = TEMPLATE_CATEGORIES.reduce((acc, c) => {
    const raw = j.random_template_ids && Array.isArray(j.random_template_ids[c]) ? j.random_template_ids[c] : [];
    acc[c] = raw.filter(id => messageTemplates.some(t => t.id === id && t.category === c));
    return acc;
  }, {});
  avoidRepeats = !!j.avoid_repeats;
  showMissingAsVar = !!j.show_missing_as_var;
  const chk = document.getElementById('tpl-show-missing');
  if (chk) chk.checked = showMissingAsVar;
  renderTemplates();
  renderTemplatePickers();
}

async function postTemplatesState() {
  try {
    const j = await postJSON('/templates', {
      templates: messageTemplates,
      active_template_ids: activeTemplateIds,
      bulk_active_template_ids: bulkTemplateIds,
      show_missing_as_var: showMissingAsVar,
      template_modes: templateModes,
      random_template_ids: randomTemplateIds,
      avoid_repeats: avoidRepeats,
      custom_variables: customVariables,
    });
    if (j && j.ok) applyTemplatesState(j);
  } catch (e) {
    showToast('Не удалось сохранить шаблоны: ' + e.message, 'error');
  }
}

function saveTemplatesState() {
  if (_tplSaveTimer) clearTimeout(_tplSaveTimer);
  _tplSaveTimer = setTimeout(() => { _tplSaveTimer = null; postTemplatesState(); }, 400);
}

// Иконки карточек — SVG на currentColor (как у карточек файлов): эмодзи-мусорка
// не наследует цвет темы и выбивается в тёмной (тест test_ui_markup следит).
const TEMPLATE_ICONS = {
  edit: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L18 10l-4-4L4 16z"/><path d="M13.5 6.5 17.5 10.5"/></svg>',
  copy: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>',
  dup: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8.5v7"/><path d="M8.5 12h7"/></svg>',
  del: FILE_ACT_ICONS.delete,
};

// Чистим выделение от шаблонов, которых больше нет (после удаления/фильтра).
function pruneTemplateSelection() {
  const alive = new Set(messageTemplates.map(t => t.id));
  _tplSelectedIds = new Set([..._tplSelectedIds].filter(id => alive.has(id)));
}

function toggleTemplateSelected(id, checked) {
  if (checked) _tplSelectedIds.add(id);
  else _tplSelectedIds.delete(id);
  updateTplSelectionUi();
}

function updateTplSelectionUi() {
  const btn = document.getElementById('btn-tpl-del-selected');
  if (btn) {
    const n = _tplSelectedIds.size;
    btn.hidden = n === 0;
    btn.disabled = n === 0;
    btn.innerHTML = UI_ICONS.trash + 'Удалить выбранные (' + n + ')';
  }
  updateSelectAllBtn();
}

function toggleSelectAllTemplates() {
  const visible = _visibleTemplates();
  const allSelected = visible.length > 0
    && visible.every(t => _tplSelectedIds.has(t.id));
  visible.forEach(t => {
    if (allSelected) _tplSelectedIds.delete(t.id);
    else _tplSelectedIds.add(t.id);
  });
  renderTemplates();
  updateTplSelectionUi();
}

// Видимый сейчас список (с учётом фильтра категории и поиска).
function _visibleTemplates() {
  let items = _tplFilterCat === 'all'
    ? messageTemplates.slice()
    : messageTemplates.filter(t => t.category === _tplFilterCat);
  const q = _tplSearchQuery.trim().toLowerCase();
  if (q) {
    items = items.filter(t =>
      t.name.toLowerCase().includes(q) || t.text.toLowerCase().includes(q));
  }
  return items;
}

// Пакетное удаление: одно подтверждение на весь выбор, затем один проход.
async function deleteSelectedTemplates() {
  const ids = [..._tplSelectedIds];
  if (!ids.length) return;
  const chosen = ids.map(id => messageTemplates.find(t => t.id === id)).filter(Boolean);
  if (!chosen.length) { _tplSelectedIds.clear(); updateTplSelectionUi(); return; }
  const names = chosen.map(t => '«' + t.name + '»');
  const head = names.slice(0, 3).join(', ');
  const tail = names.length > 3 ? ' и ещё ' + (names.length - 3) : '';
  const ok = await uiConfirm('Удалить шаблоны: ' + head + tail + '?',
    'Удалить шаблоны (' + chosen.length + ')', 'Удалить', true);
  if (!ok) return;
  const gone = new Set(ids);
  messageTemplates = messageTemplates.filter(t => !gone.has(t.id));
  _tplSelectedIds.clear();
  pruneTemplatePicks();
  renderTemplates();
  renderTemplatePickers();
  saveTemplatesState();
}

function renderTemplates() {
  const list = document.getElementById('tpl-list');
  if (list) {
    const items = _visibleTemplates();
    const q = _tplSearchQuery.trim().toLowerCase();
    pruneTemplateSelection();
    const emptyBox = document.getElementById('tpl-empty-box');
    const addBtn = document.getElementById('btn-tpl-add');
    if (!items.length) {
      list.innerHTML = '';
      const noTemplates = !messageTemplates.length;
      // Совсем нет шаблонов — канвас с кнопками; поиск/фильтр — мягкая заглушка.
      if (emptyBox) emptyBox.hidden = !(noTemplates && !q);
      if (addBtn) addBtn.hidden = noTemplates && !q;
      list.innerHTML = (noTemplates && !q) ? '' : '<div class="tpl-empty">'
        + (q ? 'Ничего не найдено по «' + escapeHtml(q) + '»' : 'В этой категории шаблонов нет')
        + '</div>';
    } else {
      if (emptyBox) emptyBox.hidden = true;
      if (addBtn) addBtn.hidden = false;
      list.innerHTML = items.map(t => {
        const vars = usedVariables(t.text);
        // Составной: вместо собственного текста копируется случайный вложенный
        // — показываем это в карточке, иначе текст сбивает с толку.
        const composite = (t.variant_ids || []).length;
        const compBadge = composite
          ? '<span class="tpl-comp-badge" title="При копировании возьмётся случайный текст из ' + composite
            + ' вложенных шаблонов">🎲 случайный из ' + composite + '</span>' : '';
        const upd = t.updated_at ? _fmtTemplateDate(t.updated_at) : null;
        // id шаблона приходит из чужого JSON при импорте и может содержать
        // кавычки — inline-onchange с конкатенацией здесь небезопасен
        // (escapeHtml не защищает JS-контекст), поэтому обработчик вешается
        // ниже через addEventListener, а id читается из dataset.
        return '<div class="template-card" data-id="' + escapeHtml(t.id) + '">'
          + '<div class="template-head">'
          + '<label class="tpl-card-chk" title="Выбрать для удаления">'
          + '<input type="checkbox" class="tpl-check" data-tpl-check="' + escapeHtml(t.id) + '"'
          + (_tplSelectedIds.has(t.id) ? ' checked' : '') + '></label>'
          + '<span class="template-name">' + escapeHtml(t.name) + '</span>'
          + '<span class="template-cat">' + escapeHtml(TEMPLATE_CAT_LABELS[t.category] || t.category) + '</span>'
          + '<span class="template-actions">'
          + '<button type="button" class="template-more" data-act="edit" title="Редактировать" aria-label="Редактировать">' + TEMPLATE_ICONS.edit + '</button>'
          + '<button type="button" class="template-more" data-act="copy" title="Скопировать текст" aria-label="Скопировать текст">' + TEMPLATE_ICONS.copy + '</button>'
          + '<button type="button" class="template-more danger" data-act="del" title="Удалить" aria-label="Удалить">' + TEMPLATE_ICONS.del + '</button>'
          + '<span class="tpl-more-wrap">'
          + '<button type="button" class="template-more" data-act="menu" title="Ещё" aria-label="Ещё действия" aria-haspopup="true">⋮</button>'
          + '<span class="tpl-menu" hidden>'
          + '<button type="button" data-act="dup">Дублировать</button>'
          + '</span></span>'
          + '</span></div>'
          + (compBadge
            ? '<div class="template-text tpl-comp-text">' + compBadge + '</div>'
            : '<div class="template-text">' + escapeHtml(t.text) + '</div>')
          + '<div class="template-meta">'
          + '<span class="template-vars">Переменные: '
          + (vars.length ? vars.map(v => '<code>{' + escapeHtml(v) + '}</code>').join(' ') : '—')
          + '</span>'
          + (upd ? '<span class="template-upd">Обновлено: ' + escapeHtml(upd) + '</span>' : '')
          + '</div></div>';
      }).join('');
      list.querySelectorAll('.template-card').forEach(card => {
        const id = card.dataset.id;
        const chk = card.querySelector('.tpl-check');
        if (chk) {
          chk.addEventListener('change', () => toggleTemplateSelected(id, chk.checked));
        }
        card.querySelectorAll('[data-act]').forEach(btn => {
          btn.addEventListener('click', e => {
            e.stopPropagation();
            const act = btn.dataset.act;
            if (act === 'edit') openTemplateModal(id);
            else if (act === 'copy') copyTemplateText(id);
            else if (act === 'dup') duplicateTemplate(id);
            else if (act === 'del') deleteTemplate(id);
            else if (act === 'menu') {
              // Меню «ещё»: открытие/закрытие, чужие клики его закрывают.
              const menu = card.querySelector('.tpl-menu');
              if (menu) menu.hidden = !menu.hidden;
            }
          });
        });
      });
    }
    updateTemplateSearchCount(items.length);
    updateTplSelectionUi();
    updateSelectAllBtn();
  }
  const varlist = document.getElementById('tpl-var-list');
  if (varlist) {
    const builtIn = TEMPLATE_VARS
      .map(([k, label]) => '<div><code>{' + k + '}</code> — ' + escapeHtml(label) + '</div>');
    const special = TEMPLATE_SPECIAL_VARS
      .map(k => '<div><code>{' + k + '}</code> — ' + escapeHtml(TEMPLATE_SPECIAL_LABELS[k] || '') + '</div>');
    const own = (customVariables || []).map(v =>
      '<div><code>{' + escapeHtml(v.name) + '}</code> — '
      + escapeHtml(v.description || (v.column ? 'из столбца «' + v.column + '»' : v.value || '—')) + '</div>');
    varlist.innerHTML = builtIn.concat(special).concat(own).join('');
  }
  renderVarCards();
  document.querySelectorAll('.tpl-cat').forEach(b => b.classList.toggle('active', b.dataset.cat === _tplFilterCat));
}

// «Обновлено: 26.09 14:30» — локальная дата без секунд.
function _fmtTemplateDate(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const p = n => String(n).padStart(2, '0');
    return p(d.getDate()) + '.' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  } catch (e) { return ''; }
}

function onTemplateSearch(value) {
  _tplSearchQuery = String(value || '');
  renderTemplates();
}

function updateTemplateSearchCount(n) {
  const el = document.getElementById('tpl-search-count');
  if (!el) return;
  const q = _tplSearchQuery.trim();
  if (!q) { el.hidden = true; el.textContent = ''; return; }
  el.hidden = false;
  el.textContent = n + ' из ' + messageTemplates.length;
}

function filterTemplatesByCategory(cat) {
  _tplFilterCat = cat || 'all';
  renderTemplates();
}

// Кнопка «Выделить все»: подпись зависит от того, выбраны ли уже все видимые.
function updateSelectAllBtn() {
  const btn = document.getElementById('btn-tpl-select-all');
  if (!btn) return;
  const visible = _visibleTemplates();
  const all = visible.length > 0 && visible.every(t => _tplSelectedIds.has(t.id));
  btn.textContent = all ? 'Снять выделение' : 'Выделить все';
}

// ── Подвкладки «Шаблоны» / «Переменные» ─────────────────────
function showTplSubtab(which) {
  _tplSubtab = (which === 'vars') ? 'vars' : 'templates';
  const tplPane = document.getElementById('tpl-pane-templates');
  const varPane = document.getElementById('tpl-pane-vars');
  if (tplPane) tplPane.hidden = _tplSubtab !== 'templates';
  if (varPane) varPane.hidden = _tplSubtab !== 'vars';
  document.querySelectorAll('.tpl-subtab').forEach(b =>
    b.classList.toggle('active', b.dataset.subtab === _tplSubtab));
  if (_tplSubtab === 'vars') renderVarCards();
}

// Селекты выбора шаблона: опция — только название (категория и так видна
// по контексту: селект таблицы показывает активную соцсеть, у обхода и
// рассылки она своя), шаблоны сгруппированы по категориям через optgroup.
function fillTemplateSelect(sel, includeEmpty) {
  if (!sel) return;
  const prev = sel.value;
  const groups = TEMPLATE_CATEGORIES
    .map(cat => ({cat, items: messageTemplates.filter(t => t.category === cat)}))
    .filter(g => g.items.length);
  sel.innerHTML = (includeEmpty ? '<option value="">— шаблон не выбран —</option>' : '')
    + groups.map(g =>
        '<optgroup label="' + escapeHtml(TEMPLATE_CAT_LABELS[g.cat]) + '">'
        + g.items.map(t =>
            '<option value="' + escapeHtml(t.id) + '">' + escapeHtml(t.name) + '</option>').join('')
        + '</optgroup>').join('');
  if (prev && messageTemplates.some(t => t.id === prev)) sel.value = prev;
}

function currentTableSocial() {
  if (typeof activeSocialFilters !== 'undefined' && activeSocialFilters && activeSocialFilters.size === 1) {
    return [...activeSocialFilters][0];
  }
  return 'vk';
}

function syncTableTemplatePicker() {
  const sel = document.getElementById('tbl-template');
  if (!sel) return;
  const t = getActiveTemplateFor(currentTableSocial());
  sel.value = t ? t.id : '';
}

function syncTemplateSelects() {
  const bulkSel = document.getElementById('bulk-template');
  if (bulkSel) {
    const social = (document.getElementById('bulk-social') || {}).value || 'vk';
    // Для обхода — только явный выбор: не выбран → пустое значение («—
    // шаблон не выбран —»), а не подстановка первого шаблона категории.
    bulkSel.value = bulkTemplateIds[social] || '';
  }
  const tplNote = document.getElementById('bulk-tpl-note');
  if (tplNote) {
    const social = (document.getElementById('bulk-social') || {}).value || 'vk';
    if (templateModes[social] === 'random') {
      const n = (randomTemplateIds[social] || []).length
        || messageTemplates.filter(t => t.category === social).length;
      tplNote.hidden = false;
      tplNote.textContent = '🎲 случайный из ' + n;
    } else if (!bulkTemplateIds[social]) {
      tplNote.hidden = false;
      tplNote.textContent = '— текст не копируется';
    } else {
      tplNote.hidden = true;
    }
  }
  const senderSel = document.getElementById('s-template');
  if (senderSel) {
    const t = getActiveTemplateFor('vk');
    senderSel.value = t ? t.id : '';
  }
  syncTableTemplatePicker();
}

function renderTemplatePickers() {
  fillTemplateSelect(document.getElementById('tbl-template'), false);
  fillTemplateSelect(document.getElementById('bulk-template'), true);
  fillTemplateSelect(document.getElementById('s-template'), true);
  syncTemplateSelects();
  renderTemplatePickPanel();
}

// ── Панель «🎲 Выбор шаблона» ──────────────────────────────────
// Режим хранится per-категория: панель показывает настройку той соцсети,
// что выбрана в селекте категории, и не мешает остальным.
function renderTemplatePickPanel() {
  const catSel = document.getElementById('tpl-pick-cat');
  if (!catSel) return;
  catSel.innerHTML = TEMPLATE_CATEGORIES
    .map(c => '<option value="' + c + '">' + escapeHtml(TEMPLATE_CAT_LABELS[c]) + '</option>').join('');
  if (!TEMPLATE_CATEGORIES.includes(_pickModalCat)) _pickModalCat = 'vk';
  catSel.value = _pickModalCat;
  renderPickPanelBody();
}

function renderPickPanelBody() {
  const body = document.getElementById('tpl-pick-body');
  if (!body) return;
  const cat = _pickModalCat;
  const mode = templateModes[cat] || 'single';
  document.querySelectorAll('input[name="tpl-pick-mode"]').forEach(r => { r.checked = r.value === mode; });
  const catTemplates = messageTemplates.filter(t => t.category === cat);
  if (mode === 'single') {
    const active = getActiveTemplateFor(cat);
    body.innerHTML = catTemplates.length
      ? '<label class="lbl" for="tpl-pick-single">Шаблон:</label>'
        + '<select id="tpl-pick-single" onchange="onPickSingleChange()">'
        + catTemplates.map(t => '<option value="' + escapeHtml(t.id) + '">' + escapeHtml(t.name) + '</option>').join('')
        + '</select>'
      : '<div class="tpl-pick-list-empty">В этой категории пока нет шаблонов.</div>';
    const sel = document.getElementById('tpl-pick-single');
    if (sel) sel.value = active ? active.id : '';
  } else {
    const ids = randomTemplateIds[cat] || [];
    body.innerHTML = catTemplates.length
      ? catTemplates.map(t =>
          '<label class="chk"><input type="checkbox" data-pick-id="' + escapeHtml(t.id) + '"'
          + (ids.includes(t.id) ? ' checked' : '') + ' onchange="onPickToggle(\'' + escapeHtml(t.id) + '\')">'
          + escapeHtml(t.name) + '</label>').join('')
      : '<div class="tpl-pick-list-empty">В этой категории пока нет шаблонов.</div>';
  }
  updatePickCount();
}

function updatePickCount() {
  const el = document.getElementById('tpl-pick-count');
  if (!el) return;
  if ((templateModes[_pickModalCat] || 'single') !== 'random') { el.textContent = ''; return; }
  const total = messageTemplates.filter(t => t.category === _pickModalCat).length;
  el.textContent = 'Выбрано: ' + (randomTemplateIds[_pickModalCat] || []).length + ' из ' + total;
}

function onPickCatChange() {
  const sel = document.getElementById('tpl-pick-cat');
  _pickModalCat = (sel && sel.value) || 'vk';
  renderPickPanelBody();
}

function onPickModeChange() {
  const checked = document.querySelector('input[name="tpl-pick-mode"]:checked');
  if (!checked) return;
  templateModes[_pickModalCat] = checked.value;
  renderPickPanelBody();
  saveTemplatesState();
}

function onPickSingleChange() {
  const sel = document.getElementById('tpl-pick-single');
  if (sel) setActiveTemplate(_pickModalCat, sel.value || null);
}

function onPickToggle(id) {
  const ids = randomTemplateIds[_pickModalCat] || [];
  const idx = ids.indexOf(id);
  if (idx >= 0) ids.splice(idx, 1); else ids.push(id);
  randomTemplateIds[_pickModalCat] = ids;
  updatePickCount();
  saveTemplatesState();
}

// ── Модалка настройки случайного выбора ────────────────────────
function openPickModal() {
  if (!templatesLoaded) { loadTemplates().then(() => openPickModal()); return; }
  const overlay = document.getElementById('tpl-pick-modal');
  if (!overlay) return;
  const catSel = document.getElementById('tpl-pick-modal-cat');
  if (catSel) {
    catSel.innerHTML = TEMPLATE_CATEGORIES
      .map(c => '<option value="' + c + '">' + escapeHtml(TEMPLATE_CAT_LABELS[c]) + '</option>').join('');
    catSel.value = _pickModalCat;
  }
  const avoid = document.getElementById('tpl-pick-avoid');
  if (avoid) avoid.checked = avoidRepeats;
  renderPickModalList();
  overlay.hidden = false;
}

function renderPickModalList() {
  const list = document.getElementById('tpl-pick-modal-list');
  if (!list) return;
  const catTemplates = messageTemplates.filter(t => t.category === _pickModalCat);
  const ids = randomTemplateIds[_pickModalCat] || [];
  list.innerHTML = catTemplates.length
    ? catTemplates.map(t =>
        '<label class="chk"><input type="checkbox" data-pick-id="' + escapeHtml(t.id) + '"'
        + (ids.includes(t.id) ? ' checked' : '') + ' onchange="onPickModalToggle(\'' + escapeHtml(t.id) + '\')">'
        + escapeHtml(t.name) + '</label>').join('')
    : '<div class="tpl-pick-list-empty">В этой категории пока нет шаблонов — создайте их во вкладке.</div>';
  updatePickModalCount();
}

function updatePickModalCount() {
  const count = document.getElementById('tpl-pick-modal-count');
  const hint = document.getElementById('tpl-pick-modal-hint');
  const save = document.getElementById('tpl-pick-modal-save');
  const ids = randomTemplateIds[_pickModalCat] || [];
  const total = messageTemplates.filter(t => t.category === _pickModalCat).length;
  if (count) count.innerHTML = UI_ICONS.spreadsheet + 'Выбрано: ' + ids.length + ' из ' + total;
  if (save) save.disabled = ids.length === 0;
  if (hint) {
    if (!ids.length) { hint.textContent = 'Выберите хотя бы один шаблон, чтобы сохранить набор.'; hint.hidden = false; }
    else if (ids.length === 1) { hint.textContent = 'Выбран один шаблон — он будет использоваться всегда. Выберите 2+ для случайного выбора.'; hint.hidden = false; }
    else { hint.hidden = true; }
  }
}

function onPickModalCatChange() {
  const sel = document.getElementById('tpl-pick-modal-cat');
  _pickModalCat = (sel && sel.value) || 'vk';
  renderPickModalList();
  renderPickPanelBody();
}

function onPickModalToggle(id) {
  const ids = randomTemplateIds[_pickModalCat] || [];
  const idx = ids.indexOf(id);
  if (idx >= 0) ids.splice(idx, 1); else ids.push(id);
  randomTemplateIds[_pickModalCat] = ids;
  updatePickModalCount();
}

function closePickModal() {
  const overlay = document.getElementById('tpl-pick-modal');
  if (overlay) overlay.hidden = true;
  // Отмена — состояние не менялось до «Сохранить», но панель перерисуем:
  // чекбоксы модалки живут в тех же массивах, синхронизируем отображение.
  renderPickPanelBody();
}

function savePickModal() {
  const ids = randomTemplateIds[_pickModalCat] || [];
  if (!ids.length) return;
  const avoid = document.getElementById('tpl-pick-avoid');
  avoidRepeats = !!(avoid && avoid.checked);
  templateModes[_pickModalCat] = 'random';
  saveTemplatesState();
  renderPickPanelBody();
  const overlay = document.getElementById('tpl-pick-modal');
  if (overlay) overlay.hidden = true;
  showToast('Набор из ' + ids.length + ' ' + _pluralRu(ids.length, 'шаблона', 'шаблонов', 'шаблонов')
    + ' сохранён для «' + (TEMPLATE_CAT_LABELS[_pickModalCat] || _pickModalCat) + '»', 'success');
}

function onTableTemplateChange() {
  const sel = document.getElementById('tbl-template');
  if (sel) setActiveTemplate(currentTableSocial(), sel.value || null);
}

function onBulkTemplateChange() {
  const sel = document.getElementById('bulk-template');
  const social = (document.getElementById('bulk-social') || {}).value || 'vk';
  if (sel) { bulkTemplateIds[social] = sel.value || null; saveTemplatesState(); }
}

function onSenderTemplateChange() {
  const sel = document.getElementById('s-template');
  if (sel) setActiveTemplate('vk', sel.value || null);
}

// ── Редактор вариантов составного шаблона ──────────────────
// Состояние чекбоксов в модалке — отдельно от сохранённых variant_ids,
// чтобы «Отмена» не трогала данные.
let _variantEditorPicks = null;

function _editingVariantIds() {
  return (_variantEditorPicks || []).slice();
}

function renderTemplateVariantsEditor(t) {
  const chk = document.getElementById('tpl-composite');
  const wrap = document.getElementById('tpl-variants-wrap');
  const list = document.getElementById('tpl-variants-list');
  if (!chk || !wrap || !list) return;
  const cat = (document.getElementById('tpl-category') || {}).value || 'vk';
  const pool = messageTemplates.filter(x => x.id !== (t && t.id) && x.category === cat);
  _variantEditorPicks = (t && Array.isArray(t.variant_ids)) ? t.variant_ids.slice() : [];
  chk.checked = _variantEditorPicks.length > 0;
  wrap.hidden = !chk.checked;
  list.innerHTML = pool.length
    ? pool.map(x =>
      '<label class="chk"><input type="checkbox" value="' + escapeHtml(x.id) + '"'
      + (_variantEditorPicks.includes(x.id) ? ' checked' : '')
      + ' onchange="onVariantItemToggle(this)">'
      + escapeHtml(x.name) + '</label>').join('')
    : '<div class="tpl-var-empty">Других шаблонов этой категории пока нет — создайте их, затем отметьте здесь.</div>';
}

function onCompositeToggle() {
  const chk = document.getElementById('tpl-composite');
  const wrap = document.getElementById('tpl-variants-wrap');
  if (wrap) wrap.hidden = !(chk && chk.checked);
}

// Смена категории в модалке: чекбоксы вариантов сбрасываем (они валидны
// только для своей категории), список перерисовываем под новую категорию.
function onTemplateCategoryChange() {
  _variantEditorPicks = [];
  const t = _tplEditId ? messageTemplates.find(x => x.id === _tplEditId) : null;
  renderTemplateVariantsEditor(t);
  const chk = document.getElementById('tpl-composite');
  if (chk) chk.checked = false;
}

function onVariantItemToggle(input) {
  if (!input || !input.value) return;
  const id = input.value;
  const set = new Set(_variantEditorPicks || []);
  if (input.checked) {
    if (!set.has(id) && set.size >= TEMPLATE_MAX_VARIANTS) {
      input.checked = false;
      showToast('Вариантов не может быть больше ' + TEMPLATE_MAX_VARIANTS, 'warning');
      return;
    }
    set.add(id);
  } else set.delete(id);
  _variantEditorPicks = [...set];
}

// ── Модалка редактирования ─────────────────────────────────────
function openTemplateModal(id) {
  if (!templatesLoaded) { loadTemplates().then(() => openTemplateModal(id)); return; }
  _tplEditId = id || null;
  const t = id ? messageTemplates.find(x => x.id === id) : null;
  const title = document.getElementById('tpl-modal-title');
  if (title) title.innerHTML = UI_ICONS.pencil + (t ? 'Редактировать шаблон' : 'Новый шаблон');
  const nameEl = document.getElementById('tpl-name');
  if (nameEl) nameEl.value = t ? t.name : '';
  const textEl = document.getElementById('tpl-text');
  if (textEl) textEl.value = t ? t.text : '';
  const catSel = document.getElementById('tpl-category');
  if (catSel) {
    catSel.innerHTML = TEMPLATE_CATEGORIES
      .map(c => '<option value="' + c + '">' + escapeHtml(TEMPLATE_CAT_LABELS[c]) + '</option>').join('');
    catSel.value = t ? t.category : (_tplFilterCat !== 'all' ? _tplFilterCat : 'vk');
  }
  const ins = document.getElementById('tpl-var-insert');
  if (ins) {
    ins.innerHTML = '<option value="">— переменная —</option>'
      + allTemplateVars().map(v => '<option value="' + escapeHtml(v.key) + '">'
        + escapeHtml('{' + v.key + '}' + (v.own ? ' · своя' : '')) + '</option>').join('');
    ins.selectedIndex = 0;
  }
  const err = document.getElementById('tpl-modal-err');
  if (err) { err.hidden = true; err.textContent = ''; }
  renderTemplateVariantsEditor(t);
  updateTemplatePreview();
  const overlay = document.getElementById('tpl-modal');
  if (overlay) overlay.hidden = false;
  if (nameEl && nameEl.focus) nameEl.focus();
}

function closeTemplateModal() {
  const overlay = document.getElementById('tpl-modal');
  if (overlay) overlay.hidden = true;
  _tplEditId = null;
}

function insertTemplateVariable(name) {
  if (!name) return;
  const ta = document.getElementById('tpl-text');
  const ins = document.getElementById('tpl-var-insert');
  if (!ta) return;
  const token = '{' + name + '}';
  if (typeof ta.selectionStart === 'number') {
    const s = ta.selectionStart, e = ta.selectionEnd;
    ta.value = ta.value.slice(0, s) + token + ta.value.slice(e);
    ta.selectionStart = ta.selectionEnd = s + token.length;
  } else {
    ta.value += token;
  }
  if (ins) ins.selectedIndex = 0;
  updateTemplatePreview();
  if (ta.focus) ta.focus();
}

// Превью в модалке обновляется при вводе (oninput) и при вставке переменной.
// Нет данных таблицы — показываем шаблон на примерных данных с пометкой
// «Пример», а не категоричную заглушку.
function updateTemplatePreview() {
  const body = document.getElementById('tpl-preview-body');
  if (!body) return;
  const text = (document.getElementById('tpl-text') || {}).value || '';
  const title = document.getElementById('tpl-preview-title');
  const note = document.getElementById('tpl-preview-note');
  const company = firstCompanyForPreview();
  if (company) {
    if (title) title.innerHTML = UI_ICONS.eye + 'Превью с данными из первой компании:';
    if (note) note.hidden = true;
    body.textContent = substituteTemplate(text, company);
  } else {
    if (title) title.innerHTML = UI_ICONS.eye + 'Превью (пример):';
    body.textContent = substituteTemplate(text, TEMPLATE_DEMO_COMPANY);
    if (note) {
      note.innerHTML = UI_ICONS.info + 'Это пример на вымышленных данных. Реальные данные компаний подставятся при работе с таблицей.';
      note.hidden = false;
    }
  }
}
