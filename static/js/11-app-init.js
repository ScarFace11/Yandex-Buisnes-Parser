
async function saveTemplateFromModal() {
  const nameEl = document.getElementById('tpl-name');
  const textEl = document.getElementById('tpl-text');
  const catEl = document.getElementById('tpl-category');
  const err = document.getElementById('tpl-modal-err');
  const name = (nameEl ? nameEl.value : '').trim();
  const text = (textEl ? textEl.value : '').trim();
  const category = catEl ? catEl.value : 'vk';
  const fail = msg => {
    if (err) { err.textContent = msg; err.hidden = false; }
    return false;
  };
  if (!name) return fail('Введите название шаблона');
  if (!text) return fail('Введите текст шаблона');
  if (text.length > TEMPLATE_MAX_TEXT) return fail('Текст длиннее ' + TEMPLATE_MAX_TEXT + ' символов');
  // Опечатка в имени переменной не падает при сохранении, но в сообщении
  // уедет «как есть» — предупреждаем до отправки. Сохранить можно и с
  // предупреждением (кнопка остаётся активной), повторный клик проходит.
  const known = new Set(allTemplateVars().map(v => v.key)
    .concat(Object.keys(TEMPLATE_VAR_ALIASES)));
  const unknown = usedVariables(text).filter(k => !known.has(k));
  if (unknown.length && !saveVarFromModal._varsWarned) {
    saveVarFromModal._varsWarned = true;
    const okSave = await uiChoose(
      'Неизвестные переменные: ' + unknown.map(u => '{' + u + '}').join(', ')
      + '. В сообщении они останутся как есть — проверьте имя или создайте свою переменную.',
      'Проверьте переменные',[{value: 'save', label: 'Сохранить как есть'},
                    {value: 'fix', label: 'Вернуться к правке'}]);
    if (!okSave || okSave.value !== 'save') return false;
  } else {
    saveVarFromModal._varsWarned = false;
  }
  const dup = messageTemplates.find(t =>
    t.id !== _tplEditId && t.category === category && t.name.toLowerCase() === name.toLowerCase());
  if (dup) return fail('Шаблон с таким названием уже есть в этой категории');
  if (_tplEditId) {
    const t = messageTemplates.find(x => x.id === _tplEditId);
    if (t) {
      t.name = name; t.text = text; t.category = category;
      // Составной шаблон: чекбоксы валидны только для своей категории.
      t.variant_ids = (typeof _editingVariantIds === 'function'
        ? _editingVariantIds() : []).filter(vid => {
          const inner = messageTemplates.find(x => x.id === vid);
          return inner && inner.category === category;
        });
      t.updated_at = new Date().toISOString();
    }
    pruneTemplatePicks();   // смена категории убирает шаблон из чужих наборов
  } else {
    messageTemplates.push({
      id: genTemplateId(), category, name, text,
      variant_ids: (typeof _editingVariantIds === 'function'
        ? _editingVariantIds() : []).filter(vid => {
          const inner = messageTemplates.find(x => x.id === vid);
          return inner && inner.category === category;
        }),
      is_default: false, created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }
  closeTemplateModal();
  renderTemplates();
  renderTemplatePickers();
  saveTemplatesState();
  showToast('Шаблон сохранён', 'success');
  return true;
}

function duplicateTemplate(id) {
  const t = messageTemplates.find(x => x.id === id);
  if (!t) return;
  messageTemplates.push({
    id: genTemplateId(), category: t.category, name: t.name + ' (копия)',
    text: t.text, variant_ids: (t.variant_ids || []).slice(),
    is_default: false, created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
  renderTemplates();
  saveTemplatesState();
  showToast('Шаблон продублирован', 'success');
}

async function deleteTemplate(id) {
  const t = messageTemplates.find(x => x.id === id);
  if (!t) return;
  const ok = await uiConfirm('Удалить шаблон «' + t.name + '»?', 'Удалить шаблон', 'Удалить', true);
  if (!ok) return;
  _tplSelectedIds.delete(id);
  messageTemplates = messageTemplates.filter(x => x.id !== id);
  pruneTemplatePicks();
  renderTemplates();
  renderTemplatePickers();
  saveTemplatesState();
}

async function copyTemplateText(id) {
  const t = messageTemplates.find(x => x.id === id);
  if (!t) return;
  const company = firstCompanyForPreview();
  const text = templateTextForCopy(t);
  const final = company ? substituteTemplate(text, company) : text;
  const ok = await copyText(final);
  if (ok) showToast('📋 Текст скопирован', 'success');
  else showCopyTextModal(final);
}

// Модалка-фолбэк, когда буфер обмена недоступен.
function showCopyTextModal(text) {
  const overlay = document.createElement('div');
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = '<div class="ui-modal links-modal">'
    + '<h3>Текст для отправки</h3>'
    + '<p>Автоматически скопировать не удалось — выделите текст и скопируйте сами.</p>'
    + '<textarea readonly rows="10">' + escapeHtml(text) + '</textarea>'
    + '<div class="ui-modal-btns"><button type="button" class="m-ok">Понятно</button></div></div>';
  const done = () => overlay.remove();
  overlay.querySelector('.m-ok').onclick = done;
  overlay.addEventListener('click', e => { if (e.target === overlay) done(); });
  document.body.appendChild(overlay);
}

// Универсальный выбор из N вариантов (у uiConfirm их только два).
// Возвращает {value, applyAll} или null. Чекбокс — опциональный.
function uiChoose(message, title, options, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'ui-modal-overlay';
    const btns = (options || []).map(o =>
      '<button type="button" class="m-opt' + (o.danger ? ' danger' : '') + '" data-value="'
      + escapeHtml(o.value) + '">' + escapeHtml(o.label) + '</button>').join('');
    const chk = opts.checkboxLabel
      ? '<label class="ui-modal-chk"><input type="checkbox" class="m-applyall"> '
        + escapeHtml(opts.checkboxLabel) + '</label>'
      : '';
    overlay.innerHTML = '<div class="ui-modal"><h3>' + escapeHtml(title || 'Выберите действие') + '</h3>'
      + '<p>' + escapeHtml(message || '') + '</p>' + chk
      + '<div class="ui-modal-btns">' + btns
      + '<button type="button" class="m-cancel">Отмена</button></div></div>';
    const done = val => { overlay.remove(); resolve(val); };
    overlay.querySelectorAll('.m-opt').forEach(b => b.addEventListener('click', () => {
      const box = overlay.querySelector('.m-applyall');
      done({value: b.dataset.value, applyAll: !!(box && box.checked)});
    }));
    overlay.querySelector('.m-cancel').onclick = () => done(null);
    overlay.addEventListener('click', e => { if (e.target === overlay) done(null); });
    document.body.appendChild(overlay);
    const first = overlay.querySelector('.m-opt');
    if (first && first.focus) first.focus();
  });
}

// ── Экспорт / импорт / сброс ───────────────────────────────────
function exportTemplates() {
  const payload = {
    version: 1,
    exported_at: new Date().toISOString(),
    active_template_ids: activeTemplateIds,
    templates: messageTemplates,
    custom_variables: customVariables,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'message-templates.json';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  showToast('Шаблоны экспортированы'
    + ((customVariables || []).length ? ' (со своими переменными: ' + customVariables.length + ')' : ''),
    'success');
}

// Нормализация своих переменных из чужого файла — зеркало серверной
// normalize_custom_variables (лимиты, резерв имён, дедуп).
function normalizeCustomVariablesClient(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  const seen = new Set();
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const name = String(item.name || '').trim();
    if (!name || name.length > TEMPLATE_MAX_VAR_NAME || !isValidVarName(name)
        || seen.has(name.toLowerCase())) continue;
    const column = String(item.column || '').trim();
    const value = column ? '' : String(item.value || '').trim();
    const variants = column ? []
      : _cleanVarVariantsClient(Array.isArray(item.variants) ? item.variants : []);
    if (!column && !value && variants.length < 2) continue;
    seen.add(name.toLowerCase());
    out.push({
      name, column, value, variants,
      description: String(item.description || '').trim(),
      created_at: String(item.created_at || '').trim() || new Date().toISOString(),
    });
    if (out.length >= TEMPLATE_MAX_CUSTOM_VARS) break;
  }
  return out;
}

// Импорт своих переменных: существующие (по имени, без регистра) —
// заменить/пропустить, новых — добавить. Возвращает {added, replaced, skipped}.
async function importCustomVariables(incoming) {
  const list = normalizeCustomVariablesClient(incoming);
  if (!list.length) return {added: 0, replaced: 0, skipped: 0};
  let added = 0, replaced = 0, skipped = 0;
  let applyAll = null;
  for (const v of list) {
    const existing = (customVariables || [])
      .find(x => x.name.toLowerCase() === v.name.toLowerCase());
    if (!existing) { customVariables.push(v); added++; continue; }
    let action = applyAll;
    if (!action) {
      const choice = await uiChoose('Переменная {' + existing.name + '} уже есть.',
        'Конфликт переменных',
        [{value: 'replace', label: 'Заменить'},
         {value: 'skip', label: 'Пропустить'}],
        {checkboxLabel: 'Применить ко всем'});
      if (!choice || !choice.value) { skipped++; continue; }
      action = choice.value;
      if (choice.applyAll) applyAll = action;
    }
    if (action === 'replace') {
      existing.column = v.column; existing.value = v.value;
      existing.variants = v.variants;
      existing.description = v.description; replaced++;
    } else skipped++;
  }
  return {added, replaced, skipped};
}

function importTemplatesClick() {
  const inp = document.getElementById('tpl-import-file');
  if (inp) inp.click();
}

async function importTemplates(input) {
  const file = input && input.files && input.files[0];
  if (!file) return;
  let parsed = null;
  try {
    parsed = JSON.parse(await file.text());
  } catch (e) {
    showToast('Файл не похож на JSON', 'error');
    input.value = '';
    return;
  }
  input.value = '';
  const incoming = Array.isArray(parsed) ? parsed : (parsed && Array.isArray(parsed.templates) ? parsed.templates : []);
  const normalized = normalizeTemplatesClient(incoming);
  if (!normalized.length) { showToast('В файле нет шаблонов', 'warning'); return; }

  // Свои переменные едут в том же файле (поле custom_variables): без них
  // шаблоны со своими переменными импортировались бы «с дырками».
  let varsMsg = '';
  if (parsed && !Array.isArray(parsed) && Array.isArray(parsed.custom_variables)) {
    const r = await importCustomVariables(parsed.custom_variables);
    if (r.added || r.replaced) {
      renderTemplates();
      saveTemplatesState();
    }
    if (r.added || r.replaced || r.skipped) {
      varsMsg = '; переменных: +' + r.added + '/~' + r.replaced + '/—' + r.skipped;
    }
  }

  let applyAll = null;   // null | 'replace' | 'duplicate' | 'skip'
  let added = 0, replaced = 0, duplicated = 0, skipped = 0;
  for (const t of normalized) {
    const existing = messageTemplates.find(x => x.id === t.id);
    if (!existing) { messageTemplates.push(t); added++; continue; }
    let action = applyAll;
    if (!action) {
      const choice = await uiChoose('Шаблон «' + existing.name + '» уже есть.', 'Конфликт шаблонов',
        [{value: 'replace', label: 'Заменить'},
         {value: 'duplicate', label: 'Дублировать'},
         {value: 'skip', label: 'Пропустить'}],
        {checkboxLabel: 'Применить ко всем'});
      if (!choice || !choice.value) { skipped++; continue; }
      action = choice.value;
      if (choice.applyAll) applyAll = action;
    }
    if (action === 'replace') { Object.assign(existing, t); replaced++; }
    else if (action === 'duplicate') {
      messageTemplates.push(Object.assign({}, t, {id: genTemplateId()}));
      duplicated++;
    } else skipped++;
  }
  renderTemplates();
  renderTemplatePickers();
  saveTemplatesState();
  showToast('Импорт: добавлено ' + added + ', заменено ' + replaced
    + ', дублей ' + duplicated + ', пропущено ' + skipped + varsMsg, 'success');
}

async function resetTemplates() {
  const ok = await uiConfirm('Сбросить все шаблоны к стандартным? Ваши изменения будут потеряны.',
    'Сброс шаблонов', 'Сбросить', true);
  if (!ok) return;
  try {
    const j = await postJSON('/templates/reset', {});
    if (j && j.ok) applyTemplatesState(j);
    showToast('Шаблоны сброшены к стандартным', 'success');
  } catch (e) {
    showToast('Не удалось сбросить: ' + e.message, 'error');
  }
}

function onShowMissingChange() {
  const chk = document.getElementById('tpl-show-missing');
  showMissingAsVar = !!(chk && chk.checked);
  updateTemplatePreview();
  saveTemplatesState();
}

// ── Пользовательские переменные (подвкладка «Переменные») ────
// Значение — статичный текст или столбец записи (company[column]); сервер
// нормализует так же (message_templates.normalize_custom_variables).
function isValidVarName(name) {
  return /^[A-Za-z0-9_а-яА-ЯёЁ]+$/.test(name) && !RESERVED_VAR_NAMES.has(name);
}

// Сырой список вариантов переменной -> непустые строки без дублей, кап 50
// (зеркало _clean_var_variants из message_templates.py).
function _cleanVarVariantsClient(raw) {
  const out = [];
  const seen = new Set();
  const arr = Array.isArray(raw) ? raw : [];
  for (const item of arr) {
    const s = String(item == null ? '' : item).trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
    if (out.length >= TEMPLATE_MAX_VAR_VARIANTS) break;
  }
  return out;
}

// Столбцы таблицы результатов — зеркало EXCEL_COLUMN_DEFS (без служебных).
function varColumnOptions() {
  const defs = (typeof EXCEL_COLUMN_DEFS !== 'undefined' && EXCEL_COLUMN_DEFS) || [];
  return defs
    .filter(d => d.f && !['reviewed', 'parsed_at'].includes(d.f))
    .map(d => ({ key: d.f, label: d.l }));
}

function renderVarCards() {
  const box = document.getElementById('tpl-var-cards');
  if (!box) return;
  const own = customVariables || [];
  if (!own.length) {
    box.innerHTML = '<div class="tpl-var-empty">Своих переменных пока нет — '
      + 'добавьте подпись, контакты или значение из столбца таблицы.</div>';
  } else {
    box.innerHTML = own.map(v => {
      const isVars = !v.column && Array.isArray(v.variants) && v.variants.length >= 2;
      const kind = v.column
        ? '📊 столбец: ' + escapeHtml(v.column)
        : (isVars ? '🎲 случайный выбор (' + v.variants.length + ')' : '📝 статичный текст');
      const valLine = v.column
        ? 'Значение — из столбца «' + escapeHtml(v.column) + '» строки компании.'
        : (isVars
          ? 'Варианты: ' + v.variants.slice(0, 3).map(s => '«' + escapeHtml(String(s).slice(0, 60)) + '»').join(', ')
            + (v.variants.length > 3 ? ' и ещё ' + (v.variants.length - 3) : '')
          : '«' + escapeHtml(String(v.value || '').slice(0, 120)) + ((v.value || '').length > 120 ? '…' : '') + '»');
      return '<div class="tpl-var-card" data-var="' + escapeHtml(v.name) + '">'
      + '<div class="tpl-var-card-head">'
      + '<code>{' + escapeHtml(v.name) + '}</code>'
      + '<span class="tpl-var-kind">' + kind + '</span>'
      + '<span class="tpl-var-actions">'
      + '<button type="button" class="template-more" data-vact="edit" title="Редактировать" aria-label="Редактировать">' + TEMPLATE_ICONS.edit + '</button>'
      + '<button type="button" class="template-more danger" data-vact="del" title="Удалить" aria-label="Удалить">' + TEMPLATE_ICONS.del + '</button>'
      + '</span></div>'
      + (v.description ? '<div class="tpl-var-desc">' + escapeHtml(v.description) + '</div>' : '')
      + '<div class="tpl-var-val">' + valLine + '</div></div>';
    }).join('');
    box.querySelectorAll('[data-vact]').forEach(btn => {
      btn.addEventListener('click', () => {
        const name = btn.closest('.tpl-var-card').dataset.var;
        if (btn.dataset.vact === 'edit') openVarModal(name);
        else deleteCustomVar(name);
      });
    });
  }
  const cnt = document.getElementById('tpl-var-count');
  if (cnt) cnt.textContent = own.length ? 'Своих переменных: ' + own.length : '';
}

function openVarModal(name) {
  if (!templatesLoaded) { loadTemplates().then(() => openVarModal(name)); return; }
  _tplEditVarName = name || null;
  const v = name ? (customVariables || []).find(x => x.name === name) : null;
  const title = document.getElementById('tpl-var-modal-title');
  if (title) title.innerHTML = v ? UI_ICONS.pencil + 'Редактировать переменную' : UI_ICONS.plus + 'Новая переменная';
  const nameEl = document.getElementById('tpl-var-name');
  if (nameEl) { nameEl.value = v ? v.name : ''; nameEl.disabled = !!v; }
  const src = document.getElementById('tpl-var-source');
  const isVars = !!(v && Array.isArray(v.variants) && v.variants.length);
  if (src) src.value = v ? (v.column ? 'column' : (isVars ? 'variants' : 'text')) : 'text';
  const valEl = document.getElementById('tpl-var-value');
  if (valEl) valEl.value = v && !v.column && !isVars ? (v.value || '') : '';
  const varsEl = document.getElementById('tpl-var-variants');
  if (varsEl) varsEl.value = v && isVars ? v.variants.join('\n') : '';
  const colSel = document.getElementById('tpl-var-column');
  if (colSel) {
    const cols = varColumnOptions();
    colSel.innerHTML = '<option value="">— выберите столбец —</option>'
      + cols.map(c => '<option value="' + escapeHtml(c.key) + '">' + escapeHtml(c.label) + '</option>').join('');
    colSel.value = v && v.column ? v.column : '';
  }
  const desc = document.getElementById('tpl-var-desc');
  if (desc) desc.value = v ? (v.description || '') : '';
  const err = document.getElementById('tpl-var-modal-err');
  if (err) { err.hidden = true; err.textContent = ''; }
  onVarSourceChange();
  const overlay = document.getElementById('tpl-var-modal');
  if (overlay) overlay.hidden = false;
  if (nameEl && nameEl.focus && !v) nameEl.focus();
}

function closeVarModal() {
  const overlay = document.getElementById('tpl-var-modal');
  if (overlay) overlay.hidden = true;
  _tplEditVarName = null;
}

function onVarSourceChange() {
  const src = document.getElementById('tpl-var-source');
  const mode = src ? src.value : 'text';
  const isCol = mode === 'column';
  const isVars = mode === 'variants';
  const tw = document.getElementById('tpl-var-text-wrap');
  const cw = document.getElementById('tpl-var-column-wrap');
  const vw = document.getElementById('tpl-var-variants-wrap');
  if (tw) tw.hidden = isCol || isVars;
  if (cw) cw.hidden = !isCol;
  if (vw) vw.hidden = !isVars;
}

function saveVarFromModal() {
  const err = document.getElementById('tpl-var-modal-err');
  const fail = msg => { if (err) { err.textContent = msg; err.hidden = false; } return false; };
  const nameEl = document.getElementById('tpl-var-name');
  const name = (nameEl ? nameEl.value : '').trim();
  const src = document.getElementById('tpl-var-source');
  const mode = src ? src.value : 'text';
  const isCol = mode === 'column';
  const isVars = mode === 'variants';
  const valEl = document.getElementById('tpl-var-value');
  const colSel = document.getElementById('tpl-var-column');
  const varsEl = document.getElementById('tpl-var-variants');
  const desc = (document.getElementById('tpl-var-desc') || {}).value || '';
  if (!name) return fail('Введите имя переменной');
  if (!_tplEditVarName && !isValidVarName(name)) {
    return fail('Имя: буквы, цифры и подчёркивание; имена встроенных переменных заняты');
  }
  const column = isCol ? ((colSel && colSel.value) || '') : '';
  if (isCol && !column) return fail('Выберите столбец таблицы');
  const rawVariants = isVars && varsEl ? varsEl.value.split('\n') : [];
  const variants = isVars ? _cleanVarVariantsClient(rawVariants) : [];
  if (isVars && variants.length < 2) {
    return fail('Введите минимум два разных варианта — по одному в строке');
  }
  const value = (isCol || isVars) ? '' : (valEl ? valEl.value : '').trim();
  if (!isCol && !isVars && !value) return fail('Введите текст, который будет подставляться');
  const list = customVariables || [];
  const existing = list.find(x => x.name.toLowerCase() === name.toLowerCase());
  if (existing && existing.name !== _tplEditVarName) return fail('Переменная с таким именем уже есть');
  if (existing) {
    existing.column = column;
    existing.value = value;
    existing.variants = variants;
    existing.description = desc.trim();
  } else {
    if (list.length >= TEMPLATE_MAX_CUSTOM_VARS) return fail('Переменных не может быть больше ' + TEMPLATE_MAX_CUSTOM_VARS);
    list.push({
      name, column, value, variants,
      description: desc.trim(),
      created_at: new Date().toISOString(),
    });
  }
  customVariables = list;
  closeVarModal();
  renderTemplates();
  saveTemplatesState();
  showToast('Переменная сохранена', 'success');
  return true;
}

async function deleteCustomVar(name) {
  const v = (customVariables || []).find(x => x.name === name);
  if (!v) return;
  const ok = await uiConfirm('Удалить переменную {' + name + '}? Она перестанет подставляться в шаблонах.',
    'Удалить переменную', 'Удалить', true);
  if (!ok) return;
  customVariables = customVariables.filter(x => x.name !== name);
  renderTemplates();
  saveTemplatesState();
  showToast('Переменная удалена', 'success');
}

// ── Автодополнение переменных в редакторе шаблона ────────────
// При вводе «{» под textarea открывается список переменных; фильтруется по
// тексту после «{», вставка кликом/Enter/Tab, Esc закрывает.
function allTemplateVars() {
  const own = (customVariables || []).map(v => ({
    key: v.name,
    label: v.description || (v.column ? 'из столбца «' + v.column + '»' : v.value || ''),
    own: true,
  }));
  const special = TEMPLATE_SPECIAL_VARS.map(k => ({ key: k, label: TEMPLATE_SPECIAL_LABELS[k] || '', own: false }));
  return TEMPLATE_VARS.map(([k, label]) => ({ key: k, label, own: false }))
    .concat(special)
    .concat(own);
}

function closeTemplateAutocomplete() {
  const box = document.getElementById('tpl-autocomplete');
  if (box) box.hidden = true;
  _tplAcItems = [];
  _tplAcIndex = -1;
}

function applyTemplateAutocomplete(key) {
  const ta = document.getElementById('tpl-text');
  if (!ta || typeof ta.selectionStart !== 'number') return;
  // Заменяем незакрытую фигурную скобку до каретки на полный токен переменной.
  const pos = ta.selectionStart;
  const before = ta.value.slice(0, pos);
  const open = before.lastIndexOf('{');
  if (open < 0 || before.slice(open).includes('}')) return;
  const token = '{' + key + '}';
  ta.value = ta.value.slice(0, open) + token + ta.value.slice(pos);
  const next = open + token.length;
  ta.selectionStart = ta.selectionEnd = next;
  closeTemplateAutocomplete();
  updateTemplatePreview();
  if (ta.focus) ta.focus();
}

function renderTemplateAutocomplete(fragment) {
  const box = document.getElementById('tpl-autocomplete');
  const ta = document.getElementById('tpl-text');
  if (!box || !ta) return;
  const items = allTemplateVars().filter(v =>
    !fragment || v.key.toLowerCase().startsWith(fragment.toLowerCase()));
  _tplAcItems = items;
  _tplAcIndex = -1;
  if (!items.length) { box.hidden = true; return; }
  box.innerHTML = items.map((v, i) =>
    '<button type="button" class="tpl-ac-item" data-i="' + i + '">'
    + '<code>{' + escapeHtml(v.key) + '}</code>'
    + '<span class="tpl-ac-label">' + escapeHtml(v.label || '') + '</span>'
    + (v.own ? '<span class="tpl-ac-own">своя</span>' : '')
    + '</button>').join('')
    + '<div class="tpl-ac-hint">↑↓ — выбор, Enter — вставить, Esc — закрыть</div>';
  box.hidden = false;
  box.querySelectorAll('.tpl-ac-item').forEach(btn => {
    btn.addEventListener('mousedown', e => {
      e.preventDefault();   // чтобы textarea не теряла фокус до вставки
      const item = items[Number(btn.dataset.i)];
      if (item) applyTemplateAutocomplete(item.key);
    });
  });
}

function onTemplateTextInput() {
  updateTemplatePreview();
  const ta = document.getElementById('tpl-text');
  if (!ta || typeof ta.selectionStart !== 'number') return;
  const before = ta.value.slice(0, ta.selectionStart);
  const open = before.lastIndexOf('{');
  if (open < 0 || before.slice(open).includes('}')) { closeTemplateAutocomplete(); return; }
  renderTemplateAutocomplete(before.slice(open + 1));
}

function onTemplateTextKeydown(e) {
  const box = document.getElementById('tpl-autocomplete');
  if (!box || box.hidden || !_tplAcItems.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    _tplAcIndex = e.key === 'ArrowDown'
      ? (_tplAcIndex + 1) % _tplAcItems.length
      : (_tplAcIndex - 1 + _tplAcItems.length) % _tplAcItems.length;
    box.querySelectorAll('.tpl-ac-item').forEach((btn, i) =>
      btn.classList.toggle('active', i === _tplAcIndex));
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    if (_tplAcIndex < 0 && e.key === 'Enter') return;   // Enter без выбора — перевод строки
    e.preventDefault();
    const item = _tplAcItems[Math.max(0, _tplAcIndex)];
    if (item) applyTemplateAutocomplete(item.key);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeTemplateAutocomplete();
  }
}

// ── Интеграция с таблицей ──────────────────────────────────────  // Клик по бейджу соцсети: пометить/снять просмотренное напротив организации
  // и (как раньше) скопировать текст шаблона + открыть профиль.
  async function onSocialBadgeClick(event, el) {
  const social = el.dataset.social;
  const key = el.dataset.key;
  const rows = (typeof filteredRows !== 'undefined' && filteredRows && filteredRows.length) ? filteredRows : allResults;
  const record = (rows || []).find(r => reviewKey(r) === key);
  if (!record) return;
  // Отмечаем открытой ИМЕННО эту сеть: гасим её бейдж, а строку не трогаем.
  // Отметка «просмотрено» (чекбокс строки) гасит все поля сразу — это
  // отдельное действие и не должно срабатывать от клика по соцсети.
  if (typeof markSocialViewed === 'function' && markSocialViewed(record, social)) {
    if (el.classList && el.classList.add) el.classList.add('social-opened');
  }
  const tpl = getTemplateFor(social);
  if (!tpl) return;
  event.preventDefault();
  const text = substituteTemplate(templateTextForCopy(tpl), record);
  const ok = await copyText(text);
  if (ok) showToast('📋 Текст скопирован (' + tpl.name + '). Вставьте (Ctrl+V)', 'success');
  else showCopyTextModal(text);
  window.open(el.getAttribute('href'), '_blank', 'noopener');
}

// ── Очередь сообщений массового обхода ─────────────────────────
function renderBulkQueue() {
  const box = document.getElementById('bulk-queue');
  if (!box) return;
  const texts = bulkState.texts instanceof Map ? bulkState.texts : new Map();
  const copied = bulkState.copiedTexts instanceof Set ? bulkState.copiedTexts : new Set();
  if (!texts.size) { box.hidden = true; box.innerHTML = ''; return; }
  box.hidden = false;
  const items = [...texts.entries()];
  box.innerHTML = '<div class="bulk-queue-head"><span>Тексты готовы: '
    + items.filter(([k]) => copied.has(k)).length + ' из ' + items.length + '</span>'
    + '<button type="button" onclick="bulkCopyNext()">' + UI_ICONS.copy + 'Скопировать следующее</button></div>'
    + items.map(([key, v]) =>
        '<div class="bulk-queue-item' + (copied.has(key) ? ' done' : '') + '">'
        + '<span class="bqi-name">' + escapeHtml(v.name || 'Без названия')
        + (v.tpl_name ? ' <span class="bqi-tpl">📋 (' + escapeHtml(v.tpl_name) + ')</span>' : '') + '</span>'
        + '<button type="button" data-copy="' + escapeHtml(key) + '">' + UI_ICONS.copy + '</button></div>').join('');
  box.querySelectorAll('[data-copy]').forEach(b =>
    b.addEventListener('click', () => bulkCopyOne(b.dataset.copy)));
}

async function bulkCopyOne(key) {
  const texts = bulkState.texts instanceof Map ? bulkState.texts : new Map();
  const item = texts.get(key);
  if (!item) return;
  const ok = await copyText(item.text || '');
  if (!ok) { showCopyTextModal(item.text || ''); return; }
  if (!(bulkState.copiedTexts instanceof Set)) bulkState.copiedTexts = new Set();
  bulkState.copiedTexts.add(key);
  showToast('📋 Текст для «' + (item.name || 'компании') + '» скопирован', 'success');
  renderBulkQueue();
}

async function bulkCopyNext() {
  const texts = bulkState.texts instanceof Map ? bulkState.texts : new Map();
  const copied = bulkState.copiedTexts instanceof Set ? bulkState.copiedTexts : new Set();
  const next = [...texts.keys()].find(k => !copied.has(k));
  if (!next) { showToast('Все тексты из этой пачки скопированы', 'info'); return; }
  await bulkCopyOne(next);
}

// ── Автоматическая отправка сообщений в приложении отсутствует: по ст. 18 ФЗ
// «О рекламе» реклама возможна только с предварительного согласия адресата.
// Шаблоны остаются для ручного копирования текста в таблице и в обходе.

// ═══════════════════════════════════════════
//  Пользовательское соглашение (первый вход)
// ═══════════════════════════════════════════
// Версия соглашения приходит с сервера: её видно в окне, чтобы отличие
// «перечитать» от «принять новую редакцию» не было загадкой.
let TERMS_VERSION = '';

function onTermsCheckbox() {
  const chk = document.getElementById('terms-accept-chk');
  const btn = document.getElementById('terms-accept-btn');
  if (btn) btn.disabled = !(chk && chk.checked);
}

// Окно соглашения живёт в двух режимах:
//   accept  — первый вход (или новая редакция): чекбокс и «Продолжить»;
//   readonly — «прочитать ещё раз» из шапки: только текст и «Закрыть».
function _termsMode(readOnly) {
  const row = document.getElementById('terms-accept-row');
  const decline = document.getElementById('terms-decline');
  const accept = document.getElementById('terms-accept-btn');
  const close = document.getElementById('terms-close-btn');
  if (row) row.hidden = readOnly;
  if (decline) decline.hidden = readOnly;
  if (accept) accept.hidden = readOnly;
  if (close) close.hidden = !readOnly;
  const note = document.getElementById('terms-version-note');
  if (note) {
    note.textContent = readOnly
      ? 'Редакция ' + (TERMS_VERSION || '') + ' — вы её уже приняли, можно перечитывать в любой момент.'
      : (TERMS_VERSION ? 'Редакция ' + TERMS_VERSION + '.' : '');
  }
}

// Кнопка «Соглашение» в шапке: открыть текст, ничего не переспрашивая.
function openTermsOverlay() {
  const ov = document.getElementById('terms-overlay');
  if (!ov) return;
  _termsMode(true);
  ov.hidden = false;
}

function closeTermsOverlay() {
  const ov = document.getElementById('terms-overlay');
  if (ov) ov.hidden = true;
}

// Возврат с экрана «отказ»: показать соглашение снова — уже с возможностью
// принять. Раньше окно безвозвратно удалялось, и единственным выходом
// оставалось закрыть приложение.
function reopenTerms() {
  const declined = document.getElementById('terms-declined');
  if (declined) declined.hidden = true;
  const ov = document.getElementById('terms-overlay');
  if (!ov) return;
  _termsMode(false);
  const chk = document.getElementById('terms-accept-chk');
  if (chk) chk.checked = false;
  onTermsCheckbox();
  ov.hidden = false;
}

function closeAppTab() {
  window.close();
  // Браузер может не дать закрыть вкладку — тогда хотя бы объясним.
  setTimeout(() => showToast('Закройте вкладку вручную (Ctrl+W) и завершите приложение', 'info'), 150);
}

function acceptTerms() {
  fetch('/terms/accept', {method: 'POST', headers: {'Content-Type': 'application/json'}})
    .then(r => r.json())
    .then(() => {
      // Скрываем, а не удаляем: кнопка «Соглашение» в шапке должна работать
      // и после первого принятия.
      closeTermsOverlay();
      const declined = document.getElementById('terms-declined');
      if (declined) declined.hidden = true;
      showToast('Соглашение принято — добро пожаловать', 'success');
    })
    .catch(() => showToast('Не удалось сохранить согласие — проверьте, что приложение запущено', 'error'));
}

function declineTerms() {
  closeTermsOverlay();
  const declined = document.getElementById('terms-declined');
  if (declined) declined.hidden = false;
}

// ═══════════════════════════════════════════
//  Минимально допустимая версия (ниже — не работаем)
// ═══════════════════════════════════════════
// Порог публикуется вместе с релизом и проверяется на каждом открытии окна:
// старая сборка может быть несовместима с форматом данных и маршрутами.
// Сеть недоступна → сервер отвечает без блокировки, и приложение работает.
function initVersionGate() {
  fetch('/version/minimum')
    .then(r => r.json())
    .then(v => {
      if (!v || !v.blocked) return;
      const gate = document.getElementById('version-gate');
      const text = document.getElementById('version-gate-text');
      const versions = document.getElementById('version-gate-versions');
      if (text) {
        text.textContent = 'Эта сборка приложения (v' + v.current + ') устарела: ' +
          'она работает только с данными и маршрутами версии v' + v.minimum + ' и новее. ' +
          'Продолжить работу на ней нельзя — это привело бы к ошибкам в результатах.';
      }
      if (versions) {
        versions.textContent = 'Установлено: v' + v.current +
          ' · минимально допустимая: v' + (v.minimum || '—') +
          (v.latest ? ' · актуальная: v' + v.latest : '') +
          (v.notice ? ' · ' + v.notice : '');
      }
      if (gate) gate.hidden = false;
    })
    .catch(() => {});   // сервер недоступен — не блокируем
}

// Кнопка на плашке «нужно обновить»: ведёт на страницу загрузки релиза.
function openReleasesPage() {
  fetch('/update/status')
    .then(r => r.json())
    .then(s => {
      const url = (s && s.download_url) || '';
      if (url) { window.open(url, '_blank', 'noopener'); return; }
      showToast('Ссылка на релиз недоступна — откройте страницу релизов вручную', 'info');
    })
    .catch(() => showToast('Приложение не отвечает — перезапустите его', 'error'));
}

function initTermsGate() {
  fetch('/terms/status')
    .then(r => r.json())
    .then(j => {
      TERMS_VERSION = (j && j.version) || '';
      _termsMode(Boolean(j && j.accepted));   // принято → окно только для чтения
      if (j && j.accepted) return;            // уже принято — работаем
      const ov = document.getElementById('terms-overlay');
      if (ov) ov.hidden = false;              // первый вход: блокируем интерфейс
    })
    .catch(() => {});                         // сервер недоступен — не блокируем
}

(function init() {
  // Theme
  const savedTheme = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(savedTheme ? savedTheme === 'dark' : prefersDark);

  // Отметки «Просмотрено» должны дожить до следующей сессии, даже если
  // вкладку закрыли или свернули сразу после клика.
  window.addEventListener('pagehide', persistReviewedOnLeave);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') persistReviewedOnLeave();
  });
  updateReviewedSaveStatus();

  // Initialize city combobox — start empty, user picks cities fresh each time
  selectedCities = [];
  initCitySelect();
  loadCityHistoryMeta();

  // Sidebar counters / summary live-update on any edit of the basic fields
  // Навешиваем ОДИН раз: иначе каждый «Найти компании» добавлял бы новый
  // слушатель (а с «{once:true}» — ещё и мёртвый), и один ввод вызывал бы
  // несколько пересчётов подряд.
  const _fq = document.getElementById('f-queries');
  if (_fq) _fq.addEventListener('input', () => {
    clearFieldError(_fq.closest('div'));   // красная рамка снимается при правке
    updateQueriesCounter();
    updateClearAllBtn();
    updateBasicSummary();
  });
  const _fci = document.getElementById('f-city-input');
  if (_fci) _fci.addEventListener('input', () => {
    clearFieldError(document.getElementById('fw-city'));
    updateClearAllBtn();
  });


  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    // Restore non-city settings only — cities stay empty on reload.
    if (saved) { delete saved.city; saved.cities = null; }
    applySettings(saved);
  } catch {}
  // Set initial social mode active state + social net checkboxes
  initSocialNetCheckboxes();
  setSocialMode(socialMode);
  setParseMode(parseMode);
  // «🎯 Тип компании»: селект периода выключен, пока не отмечен его чекбокс.
  syncCompanyTypeUi();
  // Initial state of sidebar counters / «Очистить всё» / accordion summary
  updateQueriesCounter();
  updateClearAllBtn();
  updateBasicSummary();
  updateRunBtnState();
  renderPresets();
  loadParseFields();
  initResultsPanel();
  loadReviewed();
  loadSocialViewed();
  loadColState();
  // Порядок столбцов («Столбцы» → перетаскивание) — отдельно от видимости.
  loadColOrder();
  applyHistorySections();
  // Stats tab shows zero cards right away — before any search
  renderDefaultStats();
  // Настройки уведомлений из localStorage + состояние кнопки.
  // Разрешение здесь больше не решает ничего: звук работает и без него,
  // а окна появляются, как только браузер разрешит.
  loadNotifySettings();
  updateNotifyBtn();

  // Чёрный список слов («🚫 Исключить по словам»): список и шаблоны — до первого
  // рендера счётчика, чтобы подсказка не мигала пустой строкой.
  fillBlacklistTemplateSelect();
  loadBlacklistWords();

  // Шаблоны сообщений («📝 Шаблоны»): состояние нужно таблице и обходу,
  // поэтому читаем сразу, а не при первом заходе на вкладку.
  loadTemplates();
  const _tplOverlay = document.getElementById('tpl-modal');
  if (_tplOverlay) _tplOverlay.addEventListener('click', e => { if (e.target === _tplOverlay) closeTemplateModal(); });
  const _tplTextEl = document.getElementById('tpl-text');
  if (_tplTextEl) _tplTextEl.addEventListener('input', updateTemplatePreview);

  // Папка для сохранения результатов: источник правды — сервер (settings.json),
  // поэтому форма заполняется ответом /output-dir, а не localStorage.
  const _advSaved = (() => { try { return localStorage.getItem(OUT_ADV_KEY); } catch (e) { return null; } })();
  const _advBox = document.getElementById('f-output-advanced');
  if (_advBox && _advSaved === '1') _advBox.checked = true;
  loadOutputDir();

  // Хранение результатов: срок автоудаления из settings.json (по умолчанию 30 дней).
  initRetention();

  // Sticky-футер «Фильтрация результата» паркуется над доком сайдбора —
  // его высота живёт в токене --dock-h (медленно меняется от шрифта/зума).
  syncDockHeight();
  window.addEventListener('resize', syncDockHeight);
  const _dockEl = document.getElementById('run-dock');
  if (_dockEl && window.ResizeObserver) new ResizeObserver(syncDockHeight).observe(_dockEl);

  // Check for updates from GitHub
  checkForUpdates();

  // API-keys status badge (✅ / ⚠️ / ❌) from .env
  refreshApiKeysStatus();

  // Пользовательское соглашение: при первом входе блокируем интерфейс,
  // пока не принято (хранится на сервере в settings.json).
  initTermsGate();

  // Устаревшую версию приложение блокирует до обновления.
  initVersionGate();

  // Браузер — единственный способ загрузки страниц: если Chrome не найден,
  // поиск работать не будет, и сказать об этом надо сразу.
  fetch('/status').then(r => r.json()).then(s => {
    if (s.browser_available === false) {
      const el = document.getElementById('browser-notice');
      if (el) el.style.display = '';
    }
    // A paused run survives a page reload: without this the dock showed
    // «Найти компании» and the only way «продолжить» was gone — users started
    // a fresh search instead and the pause looked like a stop.
    if (s.paused && s.paused.resume) {
      enterPausedState(s.paused.resume);
    }
  }).catch(() => {});
})();

// ═══════════════════════════════════════════
//  Search History
// ═══════════════════════════════════════════
function loadHistory() {
  const el = document.getElementById('history-list');
  if (!el) return;
  el.innerHTML = '<div class="no-data">Загрузка...</div>';

  fetch('/history')
    .then(r => r.json())
    .then(data => {
      const history = data.history || [];
      const stats = data.stats || {};
      if (!history.length) {
        el.innerHTML = '<div class="no-data">История пуста</div>';
        return;
      }
      el.innerHTML = `
        <div class="hist-summary">
          Всего поисков: <b>${stats.total}</b> · Найдено записей: <b>${stats.total_results}</b> · Общее время: <b>${Math.round(stats.total_time / 60)}мин</b>
        </div>
        ${history.map(h => renderHistoryEntry(h)).join('')}
      `;
    })
    .catch(err => {
      el.innerHTML = `<div class="no-data">Ошибка загрузки: ${err.message}</div>`;
    });
}

function toggleHistoryCard(btn) {
  btn.closest('.hist-card').classList.toggle('open');
}

// Download every file of a run as one ZIP archive
function downloadRunZip(files) {
  if (!files || !files.length) { showToast('Нет файлов для скачивания', 'error'); return; }
  const a = document.createElement('a');
  a.href = '/download-zip?files=' + encodeURIComponent(files.join('|'));
  a.download = '';
  document.body.appendChild(a);
  a.click();
  a.remove();
  showToast(`Архив с ${files.length} файл(ами) готовится…`, 'success');
}

function renderHistoryEntry(entry) {
  const date = new Date(entry.timestamp * 1000);
  const dateStr = date.toLocaleDateString('ru-RU') + ' ' + date.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  const isDone = entry.status === 'completed';
  const statusIcon = isDone ? '✔' : entry.status === 'stopped' ? '⏹' : '?';
  const statusText = isDone ? 'Завершён' : entry.status === 'stopped' ? 'Остановлен' : (entry.status || '—');
  const statusCls = isDone ? 'completed' : entry.status === 'stopped' ? 'stopped' : 'unknown';
  const elapsedMin = Math.round(entry.elapsed_sec / 60);
  const elapsedSec = Math.round(entry.elapsed_sec % 60);
  const timeStr = elapsedMin > 0 ? `${elapsedMin}м ${elapsedSec}с` : `${elapsedSec}с`;
  const userFiles = (entry.files || []).filter(f => !f.startsWith('_'));

  return `
    <div class="hist-card" data-run="${escapeHtml(entry.run_id || '')}">
      <button type="button" class="hist-hdr" onclick="toggleHistoryCard(this)" aria-expanded="false">
        <span class="hist-status ${statusCls}">${statusIcon}</span>
        <span class="hist-head">
          <span class="hist-title">${escapeHtml(entry.queries.join(', '))}</span>
          <span class="hist-meta">
            <span>🏙 <b>${entry.cities.length}</b> ${entry.cities.length === 1 ? 'город' : 'города'}</span>
            <span>📊 <b>${entry.results_count}</b> записей</span>
            <span>⏱ ${timeStr}</span>
            <span>${dateStr}</span>
          </span>
        </span>
        <span class="hist-chip ${statusCls}">${statusText}</span>
        <span class="hist-chev"></span>
      </button>
      <div class="hist-body"><div>
        <div class="hist-detail">
          <div class="hist-sub">
            <b>Города:</b> ${entry.cities.map(escapeHtml).join(', ')}<br>
            <b>Режим:</b> ${escapeHtml(entry.social_mode || '—')} · <b>Запросы:</b> ${entry.queries.map(escapeHtml).join(', ')}
          </div>
          <div class="hist-dl-row">
            <span class="hist-dl-lbl">Файлы:</span>
            ${userFiles.length
              ? `<a class="hist-dl-all" href="#" data-run-files="${escapeHtml(userFiles.join('|'))}" onclick="event.preventDefault();downloadRunZip(this.dataset.runFiles.split('|'))">⬇ Скачать все разом</a>`
              : `<span class="hist-dl-lbl" style="text-transform:none;letter-spacing:0">нет файлов</span>`}
            ${userFiles.map(f =>
              `<a class="hist-dl" href="/download/${encodeURIComponent(f)}" download>${fileIcon(f)} ${escapeHtml(f.split('_').pop())}</a>`
            ).join('')}
          </div>
          <div class="hist-dl-row">
            <button class="hist-btn blue" data-run="${escapeHtml(entry.run_id || '')}" onclick="rerunSearch(this.dataset.run)">${UI_ICONS.refresh}Повторить поиск</button>
            <button class="hist-btn red" data-run="${escapeHtml(entry.run_id || '')}" onclick="deleteHistory(this.dataset.run)">${UI_ICONS.trash}Удалить</button>
          </div>
        </div>
      </div></div>
    </div>`;
}

function rerunSearch(runId) {
  fetch(`/history/${runId}`)
    .then(r => r.json())
    .then(entry => {
      // Populate form with historical parameters
      document.getElementById('f-queries').value = entry.queries.join('\n');
      // Set cities
      selectedCities = [...entry.cities];
      renderCityTags();
      // Set social mode
      setSocialMode(entry.social_mode || 'all');
      // Switch to log tab and start
      showTab('log');
      startRun();
    })
    .catch(err => showToast('Не удалось повторить поиск: ' + err.message, 'error'));
}

async function deleteHistory(runId) {
  if (!(await uiConfirm('Удалить эту запись из истории?', 'Удалить запись', 'Удалить'))) return;
  fetch(`/history/${runId}`, { method: 'DELETE' })
    .then(() => { loadHistory(); loadCityHistoryMeta(); showToast('Запись удалена', 'success'); })
    .catch(() => showToast('Не удалось удалить запись', 'error'));
}

async function clearAllHistory() {
  if (!(await uiConfirm('Удалить ВСЮ историю поисков? Информация о поиске по городам в списке тоже будет стёрта.', 'Очистить историю', 'Очистить всё'))) return;
  fetch('/history/clear', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      loadHistory();
      loadCityHistoryMeta();
      showToast('История очищена', 'success');
    })
    .catch(err => showToast('Ошибка: ' + err.message, 'error'));
}

// ── Seen store management ────────────────────────
function loadSeenStatus() {
  fetch('/seen/status')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('seen-status');
      if (!el) return;
      if (data.count > 0) {
        const date = data.saved_at ? new Date(data.saved_at).toLocaleString('ru-RU') : '';
        el.style.display = 'block';
        el.innerHTML = `${UI_ICONS.box}В кэше <b>${data.count}</b> бизнесов${date ? ' (обновлено: ' + date + ')' : ''}. Повторные запуски по тем же городам пропустят уже найденные.`;
      } else {
        el.style.display = 'none';
      }
    })
    .catch(() => {});
}

async function clearSeenStore() {
  if (!(await uiConfirm('Очистить кэш бизнесов? Все города будут обработаны заново.', 'Очистить кэш', 'Очистить'))) return;
  fetch('/seen/clear', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        const el = document.getElementById('seen-status');
        if (el) { el.style.display = 'none'; el.innerHTML = ''; }
        showToast(`Кэш очищен: удалено ${data.cleared} бизнесов. Все города будут обработаны заново.`, 'success');
        // Labels are derived from /history — refresh so a cleared store
        // doesn't leave stale "last searched" lines in the dropdown.
        loadCityHistoryMeta();
      }
    })
    .catch(err => showToast('Ошибка: ' + err.message, 'error'));
}