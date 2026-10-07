document.addEventListener('keydown', _notifyEscape);
// Первый жест разблокирует звук (autoplay-политика).
['click', 'keydown', 'touchstart'].forEach(ev =>
  document.addEventListener(ev, unlockAudio, { once: true, passive: true }));

// ═══════════════════════════════════════════
//  Social network filter
// ═══════════════════════════════════════════
function toggleSocialFilter(key) {
  if (activeSocialFilters.has(key)) activeSocialFilters.delete(key);
  else activeSocialFilters.add(key);
  // Sync button states
  document.querySelectorAll('.sf-tag').forEach(btn => {
    btn.classList.toggle('active', activeSocialFilters.has(btn.dataset.key));
  });
  document.getElementById('sf-clear-btn')
    .classList.toggle('visible', activeSocialFilters.size > 0);
  filterTable();
}

function clearSocialFilters() {
  activeSocialFilters.clear();
  document.querySelectorAll('.sf-tag').forEach(b => b.classList.remove('active'));
  document.getElementById('sf-clear-btn').classList.remove('visible');
  filterTable();
}

// Кнопки «⊘ Дубли» больше нет: убирать дубли одним кликом без контроля было
// опасно, а объединение филиалов сетей живёт в аккордеоне «Фильтрация
// результата» («Объединять филиалы сетей» + правило объединения).

// ═══════════════════════════════════════════
//  Column visibility
// ═══════════════════════════════════════════
const COLS_KEY = 'yp_cols_v2';
const COLS = [
  { idx: 1, key: 'rev',      label: '✓ Просмотрено' },
  { idx: 2, key: 'num',      label: '# Номер' },
  { idx: 3, key: 'name',     label: 'Название' },
  { idx: 4, key: 'category', label: 'Категория' },
  { idx: 5, key: 'address',  label: 'Адрес' },
  { idx: 6, key: 'phone',    label: 'Телефон' },
  { idx: 7, key: 'score',    label: 'Оценка' },
  { idx: 8, key: 'socials',  label: 'Соцсети' },
];
let hiddenCols = new Set();

function loadColState() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLS_KEY));
    hiddenCols = new Set(Array.isArray(saved) ? saved : []);
  } catch { hiddenCols = new Set(); }
  applyColClasses();
  renderColDropdown();
}

function saveColState() {
  localStorage.setItem(COLS_KEY, JSON.stringify([...hiddenCols]));
}

function applyColClasses() {
  const tbl = document.getElementById('results-table');
  if (!tbl) return;
  COLS.forEach(c => tbl.classList.toggle('col-hide-' + c.idx, hiddenCols.has(c.key)));
  // Строка фильтра «Сеть: …» управляет скрытой колонкой соцсетей: когда
  // колонка скрыта, фильтр остаётся без объекта и только путает — прячем.
  const sfRow = document.getElementById('social-filter-row');
  if (sfRow) sfRow.classList.toggle('col-hidden', hiddenCols.has('socials'));
  // Update button badge
  const btn = document.getElementById('btn-cols');
  if (btn) {
    const n = hiddenCols.size;
    btn.classList.toggle('active', n > 0);
    btn.innerHTML = n > 0 ? `${UI_ICONS.gear}Столбцы <span style="background:var(--c);color:var(--on-accent);border-radius:10px;padding:1px 6px;font-size:10px">${COLS.length - n}/${COLS.length}</span>` : UI_ICONS.gear + 'Столбцы';
  }
}

function renderColDropdown() {
  const box = document.getElementById('col-items');
  if (!box) return;
  box.innerHTML = COLS.map(c => `
    <label class="col-item">
      <input type="checkbox" ${hiddenCols.has(c.key) ? '' : 'checked'}
        onchange="toggleCol('${c.key}', this.checked)">
      ${c.label}
    </label>`).join('');
}

function toggleCol(key, visible) {
  if (visible) hiddenCols.delete(key);
  else hiddenCols.add(key);
  saveColState();
  applyColClasses();
}

function setAllCols(visible) {
  if (visible) hiddenCols.clear();
  else COLS.forEach(c => hiddenCols.add(c.key));
  saveColState();
  applyColClasses();
  renderColDropdown();
}

function toggleColDropdown(e) {
  e.stopPropagation();
  const dd = document.getElementById('col-dropdown');
  dd.classList.toggle('open');
}

// ═══════════════════════════════════════════
//  Excel export columns («Выгрузка Excel» tab)
//  Mirrors constants.CSV_FIELDS / HEADER_LABELS. Choice persists in
//  localStorage and is sent with every run (params.excel_columns).
// ═══════════════════════════════════════════
const EXCEL_COLS_KEY = 'yp_excel_cols_v1';
const EXCEL_COLUMN_DEFS = [
  { f: 'reviewed',       l: '✓ Просмотрено' },
  { f: 'lead_score',     l: 'Оценка лида' },
  { f: 'name',           l: 'Название' },
  { f: 'category',       l: 'Категория' },
  { f: 'address',        l: 'Адрес' },
  { f: 'phone',          l: 'Телефон' },
  { f: 'rating',         l: 'Рейтинг' },
  { f: 'reviews_count',  l: 'Отзывов' },
  { f: 'vk',             l: 'ВКонтакте' },
  { f: 'vk_activity',    l: 'Активность ВК' },
  { f: 'vk_followers',   l: 'Подписчики ВК' },
  { f: 'vk_last_post_days', l: 'Последний пост (дней)' },
  { f: 'instagram',      l: 'Instagram' },
  { f: 'telegram',       l: 'Telegram' },
  { f: 'whatsapp',       l: 'WhatsApp' },
  { f: 'aggregator_url', l: 'Taplink / Linktree' },
  // Обе колонки-ссылки на карточку: в файл попадает та, что отвечает
  // источнику запуска (Яндекс или 2ГИС) — пустой колонки-двойника нет.
  { f: 'yandex_maps_url',l: 'Яндекс.Карты' },
  { f: 'twogis_url',     l: '2ГИС' },
  { f: 'query',          l: 'Запрос' },
  { f: 'parsed_at',      l: 'Дата сбора' },
  { f: 'city',           l: 'Город' },
];
let enabledExcelCols = null;  // null = все столбцы; иначе Set выбранных полей

function getExcelCols() {
  return enabledExcelCols === null ? null : [...enabledExcelCols];
}

function saveExcelCols() {
  localStorage.setItem(EXCEL_COLS_KEY,
    JSON.stringify(enabledExcelCols === null ? null : [...enabledExcelCols]));
}

function renderExcelCols() {
  const grid = document.getElementById('excel-cols-grid');
  if (!grid) return;
  const all = enabledExcelCols === null;
  grid.innerHTML = EXCEL_COLUMN_DEFS.map(c => {
    const on = all || enabledExcelCols.has(c.f);
    return `<label class="chk ${on ? 'on' : ''}">
      <input type="checkbox" ${on ? 'checked' : ''}
        onchange="toggleExcelCol('${c.f}', this.checked)"> ${c.l}</label>`;
  }).join('');
  const cnt = document.getElementById('excel-cols-count');
  if (cnt) {
    const n = all ? EXCEL_COLUMN_DEFS.length : enabledExcelCols.size;
    cnt.textContent = `Активно столбцов: ${n} из ${EXCEL_COLUMN_DEFS.length}`;
  }
}

function toggleExcelCol(f, on) {
  if (enabledExcelCols === null) {
    enabledExcelCols = new Set(EXCEL_COLUMN_DEFS.map(c => c.f));
  }
  if (on) enabledExcelCols.add(f); else enabledExcelCols.delete(f);
  saveExcelCols();
  renderExcelCols();
}

function setAllExcelCols(on) {
  enabledExcelCols = on ? null : new Set();
  saveExcelCols();
  renderExcelCols();
}

function loadExcelCols() {
  try {
    const saved = JSON.parse(localStorage.getItem(EXCEL_COLS_KEY));
    if (saved === null) enabledExcelCols = null;
    else if (Array.isArray(saved)) enabledExcelCols = new Set(saved);
    else enabledExcelCols = null;
  } catch { enabledExcelCols = null; }
  renderExcelCols();
}

document.addEventListener('click', e => {
  const wrap = document.querySelector('.col-toggle-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('col-dropdown')?.classList.remove('open');
  }
  // Дропдаун шаблонов исключений закрывается кликом мимо.
  const dd = document.getElementById('blacklist-dd');
  if (dd && !dd.contains(e.target)) closeBlacklistDropdown();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('blacklist-dd-panel')?.hidden === false) {
    closeBlacklistDropdown();
  }
});

// ═════════════════════════════════════════
//  API keys → .env (Yandex + 2GIS, one button)
// ═════════════════════════════════════════

// ── API-keys block (static section at the top of the sidebar) ──
// Expand/collapse the key form; the status badge lives in the header so the
// user sees at a glance whether keys are configured without expanding.
function toggleApiKeys() {
  const body = document.getElementById('api-keys-body');
  const hdr  = document.getElementById('api-keys-toggle');
  if (!body || !hdr) return;
  body.hidden = !body.hidden;
  hdr.setAttribute('aria-expanded', body.hidden ? 'false' : 'true');
  hdr.classList.toggle('open', !body.hidden);
}

// Badge states — the badge always carries the exact count:
//   3/3 → ✅ Готово (green) · 1–2/3 → оранжевый с процентом · 0/3 → ❌.
// All three keys count equally: VK drives the lead score (+20) and the
// activity filter, so a missing VK token is worth seeing in the ratio.
function updateApiKeysStatus(yandex, twogis, vk) {
  const badge = document.getElementById('api-status-badge');
  if (!badge) return;
  const total = 3;
  const have = [yandex, twogis, vk].filter(Boolean).length;
  let cls, txt, title;
  if (have === total) {
    cls = 'ok'; txt = UI_ICONS.check + `Готово ${have}/${total}`;
    title = 'Все API-ключи настроены: Яндекс, 2GIS, VK';
  } else if (have > 0) {
    cls = 'warn'; txt = UI_ICONS.warn + `${have}/${total} ключей`;
    title = 'Настроены не все API-ключи — часть функций (соцсети, активность ВК, 2GIS) будет недоступна';
  } else {
    cls = 'err'; txt = UI_ICONS.x + `0/${total} ключей`;
    title = 'API-ключи не найдены — поиск может не работать';
  }
  badge.className = 'api-badge ' + cls;
  badge.innerHTML = txt;
  badge.title = title;
  // Per-key dots next to each field label (green = key is set).
  const dots = { 'key-dot-yandex': yandex, 'key-dot-2gis': twogis, 'key-dot-vk': vk };
  for (const [id, present] of Object.entries(dots)) {
    const dot = document.getElementById(id);
    if (dot) {
      dot.classList.toggle('on', !!present);
      dot.title = present ? 'Ключ указан (в .env)' : 'Ключ не указан';
    }
  }
}

// True when a VK token is stored — used by the «Проверять активность ВК»
// hint so the user learns about the missing token before the run, not after.
let vkTokenReady = false;

function updateVkCheckHint() {
  const hint = document.getElementById('vk-check-hint');
  if (!hint) return;
  hint.textContent = vkTokenReady
    ? 'Проверяет подписчиков и дату последнего поста через VK API. Результат кэшируется на 7 дней.'
    : 'Нужен VK-ключ в блоке «API-ключи» — без него шаг будет пропущен с предупреждением.';
}

// ═══════════════════════════════════════════
//  VK activity + lead score (accordion 04)
// ═══════════════════════════════════════════
function setVkMode(mode) {
  vkMode = mode;
  document.querySelectorAll('.vk-mode-opt').forEach(el => {
    const radio = el.querySelector('input[type=radio]');
    const on = !!radio && radio.value === mode;
    el.classList.toggle('active', on);
    if (radio) radio.checked = on;
  });
}

// The activity controls only matter when the check is on — showing them
// always made the block look like it filtered something by itself.
function onVkCheckChange() {
  const cb = document.getElementById('f-vk-check');
  const block = document.getElementById('vk-filter-block');
  if (block) block.classList.toggle('open', !!(cb && cb.checked));
  updateVkCheckHint();
}

function onMinScoreInput() {
  const el = document.getElementById('f-min-score');
  if (!el) return;
  const v = +el.value || 0;
  // Preset buttons mirror the stored threshold; «Все» (0) is the default.
  document.querySelectorAll('.score-preset').forEach(b =>
    b.classList.toggle('active', +b.dataset.score === v));
  const hint = document.getElementById('score-hint');
  if (!hint) return;
  const base = v === 0
    ? 'Порог 0: показывать все записи'
    : `Порог ${v}: останутся лиды с оценкой ${v} и выше`;
  const scored = allResults.filter(r => r.lead_score != null && r.lead_score !== '');
  hint.textContent = scored.length
    ? `${base} · подходят ${scored.filter(r => (+r.lead_score || 0) >= v).length} из ${scored.length}.`
    : `${base}. Формула — в «ℹ️ Как считается оценка» ниже.`;
}

// Preset click → store the threshold in the same hidden field (presets,
// filterTable and min_lead_score read it) and refresh the feedback line.
function setMinScore(v) {
  const el = document.getElementById('f-min-score');
  if (el) el.value = +v || 0;
  onMinScoreInput();
  applyFiltersAndRender();
}

function applyFiltersAndRender() {
  curPage = 1;
  renderPage();
}

// Ask the backend which keys are present in .env and paint the badge.
function refreshApiKeysStatus() {
  fetch('/api-keys/status')
    .then(r => r.json())
    .then(j => { vkTokenReady = !!j.vk; updateApiKeysStatus(!!j.yandex, !!j.twogis, !!j.vk); updateVkCheckHint(); })
    .catch(() => {});
}

function saveApiKeys() {
  const btn = document.getElementById('btn-save-key');
  const yandexKey = document.getElementById('f-apikey').value.trim();
  const twogisKey = (document.getElementById('f-2gis-key') || {}).value?.trim() || '';
  const vkToken = (document.getElementById('f-vk-token') || {}).value?.trim() || '';
  const status = document.getElementById('apikey-status');

  if (!yandexKey && !twogisKey && !vkToken) {
    showToast('Введите хотя бы один ключ', 'error');
    return;
  }

  btn.disabled = true;
  const orig = btn.textContent;
  btn.innerHTML = UI_ICONS.busy + 'Сохраняю…';

  const show = (ok, msg) => {
    if (!status) return;
    status.style.display = 'block';
    status.className = ok ? 'ok' : 'err';
    status.innerHTML = (ok ? UI_ICONS.check : UI_ICONS.x) + escapeHtml(msg);
  };

  fetch('/save-api-keys', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({yandex_api_key: yandexKey, twogis_api_key: twogisKey, vk_token: vkToken})
  })
  .then(r => r.json().then(d => ({ok: r.ok, data: d})))
  .then(({ok, data}) => {
    if (ok && data.ok) {
      showToast(data.message || 'Ключи сохранены в .env', 'success');
      show(true, data.message || 'Ключи сохранены в .env');
      // Empty fields = «использовать сохранённое в .env» — reflect it
      if (yandexKey) document.getElementById('f-apikey').value = '';
      if (twogisKey) { document.getElementById('f-2gis-key').value = ''; refreshSourceKeyState(); }
      if (vkToken) document.getElementById('f-vk-token').value = '';
      refreshApiKeysStatus();
      // Новый ключ 2GIS — сервер обнулил месячный счётчик токенов: карточка
      // квоты и лог должны показать это сразу, а не после перезапуска.
      if (data.quota_reset) {
        _twogisQuotaLive = 0;
        renderQuotaCard();
        appendLog('info', '  🔄 Новый ключ 2GIS — счётчик токенов сброшен');
      }
    } else {
      showToast(data.error || 'Ошибка сохранения', 'error');
      show(false, data.error || 'Ошибка сохранения');
    }
  })
  .catch(e => {
    showToast('Ошибка соединения: ' + e.message, 'error');
    show(false, 'Ошибка соединения: ' + e.message);
  })
  .finally(() => {
    btn.disabled = false;
    btn.textContent = orig;
  });
}

// Toast notifications are implemented once, near the top of this file
// (stacked in #toast-container, top-right). The legacy centered version
// was removed in the UI redesign.

// ═══════════════════════════════════════════
//  Dark theme
// ═══════════════════════════════════════════
const THEME_KEY = 'yp_theme_v1';
let themeAnimTimer = null;

// animate=true только при ручном переключении: короткая плавная смена цветов
// вместо резкого «щелчка». Первую отрисовку анимировать нельзя — тему ставит
// мини-скрипт в <head> шаблона ещё до загрузки стилей.
function applyTheme(dark, animate) {
  const root = document.documentElement;
  if (animate) {
    root.classList.add('theme-anim');
    if (themeAnimTimer) clearTimeout(themeAnimTimer);
    themeAnimTimer = setTimeout(() => root.classList.remove('theme-anim'), 260);
  }
  root.setAttribute('data-theme', dark ? 'dark' : 'light');
  const themeBtn = document.getElementById('btn-theme');
  if (themeBtn) themeBtn.innerHTML = dark ? UI_ICONS.sun : UI_ICONS.moon;
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const next = !isDark;
  applyTheme(next, true);
  localStorage.setItem(THEME_KEY, next ? 'dark' : 'light');
}

// City data is defined above as CITIES_DATA with population info.
// City combobox UI is implemented via initCitySelect/addCity/removeCity functions.

// ═══════════════════════════════════════════
//  SENDER
// ═══════════════════════════════════════════
let sendEvtSource = null;
let senderRunning = false;
const SENDER_CFG_KEY = 'yp_sender_v1';

function toggleSenderLimit() {
  const t = document.getElementById('s-limit-type').value;
  document.getElementById('s-limit-n-wrap').style.display = t === 'n' ? '' : 'none';
}

function toggleSenderConfig() {
  const body = document.getElementById('sender-cfg-body');
  const btn  = document.getElementById('sender-cfg-tog');
  const visible = body.style.display !== 'none';
  body.style.display = visible ? 'none' : '';
  btn.textContent = visible ? 'развернуть ▼' : 'свернуть ▲';
}

function appendSendLog(level, msg) {
  const ph = document.getElementById('send-log-ph');
  if (ph) ph.remove();
  const el = document.getElementById('send-log-output');
  const d = document.createElement('div');
  d.className = 'll ' + (level || 'info');
  d.textContent = msg.replace(/\x1b\[[0-9;]*m/g, '');
  el.appendChild(d);
  _trimLog(el);
  el.scrollTop = el.scrollHeight;
}

function clearSendLog() {
  document.getElementById('send-log-output').innerHTML = '';
}

function updateSenderStats(sent, skip, err) {
  const bar = document.getElementById('sender-stats-bar');
  bar.style.display = 'flex';
  document.getElementById('ss-sent').textContent = sent;
  document.getElementById('ss-skip').textContent = skip;
  document.getElementById('ss-err').textContent  = err;
}

function loadSenderFiles() {
  fetch('/send/files')
    .then(r => r.json())
    .then(data => {
      const sel = document.getElementById('s-excel-file');
      const cur = sel.value;
      sel.innerHTML = '<option value="">— выберите файл —</option>';
      (data.files || []).forEach(f => {
        const opt = document.createElement('option');
        opt.value = f; opt.textContent = f;
        if (f === cur) opt.selected = true;
        sel.appendChild(opt);
      });
    })
    .catch(() => {});
}

function saveSenderConfig() {
  const randomChk = document.getElementById('s-random-tpl');
  const cfg = {
    message:  document.getElementById('s-message').value,
    delayMin: document.getElementById('s-delay-min').value,
    delayMax: document.getElementById('s-delay-max').value,
    limitType:document.getElementById('s-limit-type').value,
    limitN:   document.getElementById('s-limit-n').value,
    file:     document.getElementById('s-excel-file').value,
    randomTpl: !!(randomChk && randomChk.checked),
  };
  localStorage.setItem(SENDER_CFG_KEY, JSON.stringify(cfg));
}

function restoreSenderConfig() {
  try {
    const cfg = JSON.parse(localStorage.getItem(SENDER_CFG_KEY));
    if (!cfg) return;
    // Tokens are intentionally never restored from browser storage.
    // Remove a token left by older versions.
    if (cfg.token != null) {
      delete cfg.token;
      localStorage.setItem(SENDER_CFG_KEY, JSON.stringify(cfg));
    }
    if (cfg.message  != null) document.getElementById('s-message').value    = cfg.message;
    if (cfg.delayMin != null) document.getElementById('s-delay-min').value  = cfg.delayMin;
    if (cfg.delayMax != null) document.getElementById('s-delay-max').value  = cfg.delayMax;
    if (cfg.limitType!= null) {
      document.getElementById('s-limit-type').value = cfg.limitType;
      toggleSenderLimit();
    }
    if (cfg.limitN   != null) document.getElementById('s-limit-n').value    = cfg.limitN;
    if (cfg.randomTpl != null) {
      const _rc = document.getElementById('s-random-tpl');
      if (_rc) _rc.checked = !!cfg.randomTpl;
    }
    // file restored after files load
    window._senderPendingFile = cfg.file;
  } catch {}
}

function startSend() {
  const token   = document.getElementById('s-token').value.trim();
  const message = document.getElementById('s-message').value.trim();
  const file    = document.getElementById('s-excel-file').value;
  const social  = document.getElementById('s-social').value;
  const delMin  = parseFloat(document.getElementById('s-delay-min').value) || 1.5;
  const delMax  = parseFloat(document.getElementById('s-delay-max').value) || 3.5;
  const ltType  = document.getElementById('s-limit-type').value;
  const limitN  = parseInt(document.getElementById('s-limit-n').value) || 10;
  const randomChk = document.getElementById('s-random-tpl');
  const senderRandom = !!(randomChk && randomChk.checked);
  // Random-режим рассылки: набор для vk из настроек «🎲 Выбор шаблона».
  const senderIds = (randomTemplateIds['vk'] || []).slice();
  const senderRandomActive = senderRandom && senderIds.length > 0;

  if (!file) {
    showFieldError(document.getElementById('fw-send-file'), 'Выберите Excel-файл с результатами');
    showToast('Выберите Excel-файл с результатами', 'error');
    return;
  }
  if (!token) {
    showFieldError(document.getElementById('fw-send-token'), 'Введите ключ доступа VK');
    showToast('Введите VK access_token', 'error');
    return;
  }
  if (!message && !senderRandomActive) {
    showFieldError(document.getElementById('fw-send-msg'), 'Шаблон сообщения не может быть пустым');
    showToast('Шаблон сообщения не может быть пустым', 'error');
    return;
  }

  clearSendLog();
  saveSenderConfig();

  const params = {
    social,
    excel_file:   file,
    access_token: token,
    message_tpl:  message,
    limit:        ltType === 'all' ? 0 : limitN,
    delay_min:    delMin,
    delay_max:    delMax,
  };
  if (senderRandomActive) {
    params.message_tpl_ids = senderIds;
    params.tpl_avoid_repeats = avoidRepeats;
    params.message_tpl = '';
  }

  document.getElementById('btn-send-run').disabled = true;
  document.getElementById('send-btn-icon').innerHTML = '<span class="spin"></span>';
  document.getElementById('send-btn-txt').textContent = 'Рассылка…';
  document.getElementById('btn-send-stop').style.display = 'inline-block';
  document.getElementById('sender-stats-bar').style.display = 'none';
  senderRunning = true;

  fetch('/send/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params)
  })
  .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); startSendSSE(); })
  .catch(err => {
    appendSendLog('warn', '  [!] ' + err.message);
    resetSendBtn();
  });
}

function stopSend() {
  fetch('/send/stop', {method: 'POST'}).catch(() => {});
  appendSendLog('warn', '  [!] Остановка запрошена…');
}

function startSendSSE() {
  if (sendEvtSource) { sendEvtSource.close(); sendEvtSource = null; }
  sendEvtSource = new EventSource('/send/logs');
  let stats = {sent: 0, skipped: 0, errors: 0};

  sendEvtSource.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;
    if (msg.type === 'log') {
      appendSendLog(msg.level, msg.msg);
    } else if (msg.type === 'done') {
      stats = msg.stats || stats;
      updateSenderStats(stats.sent || 0, stats.skipped || 0, stats.errors || 0);
      const stopped = msg.stopped;
      appendSendLog(stopped ? 'warn' : 'ok',
        stopped ? '  [⏹] Рассылка остановлена.' : '  [✓] Рассылка завершена.');
      resetSendBtn();
      sendEvtSource.close(); sendEvtSource = null;
    }
  };
  sendEvtSource.onerror = () => {
    appendSendLog('warn', '  [!] Соединение прервано.');
    resetSendBtn();
    if (sendEvtSource) { sendEvtSource.close(); sendEvtSource = null; }
  };
}

function resetSendBtn() {
  senderRunning = false;
  document.getElementById('btn-send-run').disabled = false;
  document.getElementById('send-btn-icon').innerHTML = UI_ICONS.send;
  document.getElementById('send-btn-txt').textContent = 'Запустить рассылку';
  document.getElementById('btn-send-stop').style.display = 'none';
}

// ═══════════════════════════════════════════
//  Logs modal
// ═══════════════════════════════════════════
function showLogsModal() {
  const existing = document.querySelector('.logs-modal-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.className = 'logs-modal-overlay';
  overlay.innerHTML = `<div class="logs-modal">
    <h3>${UI_ICONS.book}Логи запусков</h3>
    <div class="logs-empty">Загрузка…</div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  fetch('/logs/list')
    .then(r => r.json())
    .then(data => {
      const logs = data.logs || [];
      const modal = overlay.querySelector('.logs-modal');
      if (!logs.length) {
        modal.innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3><div class="logs-empty">Логов пока нет. Запустите поиск чтобы создать лог.</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
        return;
      }
      const listHtml = logs.map(l => {
        const sizeKB = (l.size / 1024).toFixed(1);
        return `<li>
          <span class="log-name">${escapeHtml(l.name)}</span>
          <span class="log-meta">${l.modified} · ${sizeKB} КБ</span>
          <span class="log-actions">
            <a class="log-view" href="/logs/view/${encodeURIComponent(l.name)}" target="_blank">👁 Смотреть</a>
            <a class="log-dl" href="/logs/download/${encodeURIComponent(l.name)}" download>💾 Скачать</a>
          </span>
        </li>`;
      }).join('');
      modal.innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3>
        <ul class="logs-list">${listHtml}</ul>
        <div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
    })
    .catch(() => {
      overlay.querySelector('.logs-modal').innerHTML = `<h3>${UI_ICONS.book}Логи запусков</h3><div class="logs-empty">Ошибка загрузки</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
    });
}

// ═══════════════════════════════════════════
//  🩺 Диагностика: самопроверка по кнопке
// ═══════════════════════════════════════════
// Отвечает на «ничего не работает» без чтения логов: живые ли ключи, куда
// пишем, готово ли окружение и понимает ли текущая версия старые сборы.
// Живые проверки ключей стоят квоты 2ГИС и времени, поэтому запускаются
// ТОЛЬКО по нажатию и разделены по кнопкам: «только ключи» / «без запросов
// к API». Тексты приходят с сервера, поэтому любой из них пропускается
// через escapeHtml.
// Заголовки групп и значки статусов — из того же спрайта, что и кнопки: в
// отчёте рядом стоят три состояния, и разнобой между ними читался как шум.
const DIAG_GROUP_TITLES = {
  keys:  UI_ICONS.key + 'Ключи API',
  files: UI_ICONS.folder + 'Файлы и папки',
  data:  UI_ICONS.box + 'Данные прошлых сборов',
  env:   UI_ICONS.info + 'Окружение',
};
const DIAG_STATUS = {
  ok:    { icon: UI_ICONS.check, label: 'в порядке' },
  warn:  { icon: UI_ICONS.warn,  label: 'предупреждение' },
  error: { icon: UI_ICONS.x,     label: 'ошибка' },
};
let _diagBusy = false;

function showDiagnostics() {
  const existing = document.getElementById('diag-overlay');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'diag-overlay';
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal diag-modal" role="dialog" aria-modal="true" aria-labelledby="diag-title">
      <h3 id="diag-title">${UI_ICONS.pulse}Диагностика</h3>
      <div class="diag-lead">Проверю ключи API, права на папку результатов, окружение и данные прошлых
        сборов — это четыре причины, из-за которых чаще всего «ничего не работает». Читать логи не нужно.</div>
      <div class="diag-note">${UI_ICONS.key}Проверка ключей делает живые запросы: 2ГИС списывает 1–2 запроса из месячной
        квоты, Яндекс — один пробный. Остальные проверки бесплатны и мгновенны.</div>
      <div class="diag-actions">
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['keys','files','data','env'], this)">${UI_ICONS.checkSquare}Проверить всё</button>
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['keys'], this)">${UI_ICONS.key}Только ключи</button>
        <button type="button" class="btn-sm diag-run" onclick="runDiagnostics(['files','data','env'], this)">${UI_ICONS.folder}Без запросов к API</button>
      </div>
      <div class="diag-summary" id="diag-summary" role="status" aria-live="polite">Нажмите «Проверить всё» — покажу, что работает, а что нет.</div>
      <div class="diag-results" id="diag-results"></div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel" onclick="closeDiagnostics()">Закрыть</button>
      </div>
    </div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeDiagnostics(); });
  overlay.addEventListener('keydown', e => { if (e.key === 'Escape') closeDiagnostics(); });
  document.body.appendChild(overlay);
  // Клавиатура: Esc должен работать и без клика внутри модалки.
  document.addEventListener('keydown', _diagEscape);
}

function _diagEscape(e) {
  if (e && e.key === 'Escape') closeDiagnostics();
}

function closeDiagnostics() {
  document.removeEventListener('keydown', _diagEscape);
  const overlay = document.getElementById('diag-overlay');
  if (overlay) overlay.remove();
}

// Группы проверок: ['keys'] стоит квоту и сети, остальные — только локальные.
function runDiagnostics(groups, btn) {
  if (_diagBusy) return Promise.resolve();
  const list = Array.isArray(groups) && groups.length ? groups : ['keys', 'files', 'data', 'env'];
  _diagBusy = true;
  const buttons = [...document.querySelectorAll('.diag-run')];
  // innerHTML, а не textContent: подписи несут значок из спрайта, и возврат
  // через textContent вставил бы <svg …> в кнопку как обычный текст.
  const labels = buttons.map(b => b.innerHTML);
  const pressed = btn || buttons[0];
  const pressedLabel = pressed ? pressed.innerHTML : '';
  buttons.forEach(b => { b.disabled = true; });
  if (pressed) pressed.innerHTML = UI_ICONS.busy + 'Проверяю…';
  setDiagSummary('⏳ Идут проверки…' + (list.includes('keys') ? ' Ключи проверяются живыми запросами.' : ''));
  return fetch('/diagnostics/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({groups: list}),
  })
    .then(r => r.json())
    .then(data => {
      if (!data || data.ok === false) {
        setDiagSummary('⛔ Проверки не выполнились: '
          + escapeHtml((data && data.error) || 'сервер не ответил'), 'error');
        return;
      }
      renderDiagnostics(data.results || [], list);
    })
    .catch(() => setDiagSummary('⛔ Не удалось выполнить проверки — сервер недоступен.', 'error'))
    .then(() => {
      _diagBusy = false;
      buttons.forEach((b, i) => { b.disabled = false; b.innerHTML = labels[i]; });
      if (pressed) pressed.innerHTML = pressedLabel;
    });
}

function setDiagSummary(html, status) {
  const el = document.getElementById('diag-summary');
  if (!el) return;
  el.innerHTML = html;
  el.className = 'diag-summary' + (status ? ' diag-summary-' + status : '');
}

function renderDiagnostics(results, groups) {
  const box = document.getElementById('diag-results');
  if (!box) return;
  const errors = results.filter(r => r.status === 'error').length;
  const warns = results.filter(r => r.status === 'warn').length;
  const ok = results.filter(r => r.status === 'ok').length;
  const plural = _pluralRu(results.length, 'проверка', 'проверки', 'проверок');
  let summary = `Проверок: ${results.length} (${plural}): `
    + `<b>${ok}</b> в порядке`
    + (warns ? `, <b>${warns}</b> с предупреждениями` : '')
    + (errors ? `, <b>${errors}</b> с ошибками` : '') + '.';
  if (errors) summary += ' Сначала разберитесь с ошибками — с ними работа не пойдёт.';
  else if (warns) summary += ' Ошибок нет; предупреждения — это места, где результат будет хуже обычного.';
  else summary += ' Всё готово к работе.';
  setDiagSummary(summary, errors ? 'error' : (warns ? 'warn' : 'ok'));

  const order = Array.isArray(groups) && groups.length ? groups : Object.keys(DIAG_GROUP_TITLES);
  box.innerHTML = order.map(group => {
    const rows = results.filter(r => r.group === group);
    if (!rows.length) return '';
    return `<div class="diag-group">
      <div class="diag-group-title">${DIAG_GROUP_TITLES[group] || escapeHtml(group)}</div>
      ${rows.map(diagRowHTML).join('')}
    </div>`;
  }).join('') || '<div class="diag-empty">Проверки ничего не вернули.</div>';
}

// Одна строка отчёта: значок по статусу, заголовок, объяснение и что делать.
function diagRowHTML(row) {
  const meta = DIAG_STATUS[row.status] || DIAG_STATUS.warn;
  const detail = row.detail ? `<div class="diag-detail">${escapeHtml(row.detail)}</div>` : '';
  const hint = row.hint ? `<div class="diag-hint">${UI_ICONS.info}${escapeHtml(row.hint)}</div>` : '';
  return `<div class="diag-row" data-status="${escapeHtml(row.status || 'warn')}">
    <div class="diag-row-head">
      <span class="diag-ico" aria-hidden="true">${meta.icon}</span>
      <span class="diag-title">${escapeHtml(row.title || '')}</span>
      <span class="diag-sr">${meta.label}</span>
    </div>
    ${detail}${hint}
  </div>`;
}

// ═══════════════════════════════════════════
//  Version check from GitHub
// ═══════════════════════════════════════════
// Poll GitHub every 30 minutes while the page stays open; the header button
// re-uses the same check on demand.
const UPDATE_CHECK_INTERVAL = 30 * 60 * 1000;

// DEV-сборка (config.is_dev_build) не обновляется публичными релизами:
// сервер отвечает dev:true, баннер и точка обновления не показываются.
let _devBuild = false;

function checkForUpdates(silent) {
  // Frozen build: /update/status also reports latest version + whether the
  // in-app updater is available. Source runs fall back to /check-version.
  return fetch('/update/status')
    .then(r => r.json())
    .then(data => {
      if (data.dev) {
        _devBuild = true;
        setUpdateIndicator(false);
        return { newer: false, dev: true, version: data.current };
      }
      if (data.newer) {
        showUpdateBanner(data.latest, data.changelog || '',
          data.download_url || 'https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest');
        setUpdateIndicator(true, data.latest);
        return { newer: true, version: data.latest };
      }
      setUpdateIndicator(false);
      // Сервер может объяснить, почему объявленную версию пока нельзя
      // поставить (релиз ещё не опубликован) — это не ошибка связи.
      return { newer: false, version: data.latest || data.current, notice: data.notice || '' };
    })
    .catch(() => {
      // /update/status unavailable — legacy /check-version fallback
      return fetch('/check-version')
        .then(r => r.json())
        .then(data => {
          if (data.dev) {
            _devBuild = true;
            setUpdateIndicator(false);
            return { newer: false, dev: true, version: data.current };
          }
          if (data.newer) {
            showUpdateBanner(data.remote, data.changelog || '', data.download_url || '');
            setUpdateIndicator(true, data.remote);
            return { newer: true, version: data.remote };
          }
          setUpdateIndicator(false);
          return { newer: false, version: data.current };
        })
        .catch(() => ({ newer: false, error: true }));
    })
    .then(res => {
      if (silent) return res;
      if (res.dev) showToast('DEV-сборка — авто-обновление отключено (только для разработки)', 'info');
      else if (res.error) showToast('Не удалось связаться с GitHub — проверьте интернет', 'error');
      else if (res.newer) showToast(`Новая версия v${res.version} — обновите через баннер сверху`, 'success');
      else if (res.notice) showToast(res.notice, 'info');
      else showToast('Вы на последней версии ✓', 'success');
      return res;
    });
}

// Header button: manual re-check with visual feedback
function manualUpdateCheck(btn) {
  if (!btn || btn.dataset.busy) return;
  btn.dataset.busy = '1';
  btn.classList.remove('has-update');
  btn.innerHTML = '<span class="spin" style="width:11px;height:11px;border-width:1.5px"></span>'
    + '<span class="hdr-lbl">Проверяю…</span>';
  checkForUpdates(false)
    .catch(() => {})
    .finally(() => {
      delete btn.dataset.busy;
      // Надпись восстанавливает индикатор: он заново решит, «🔄 Обновления»
      // или «⬆ Обновить до vX» — исходный innerHTML больше не запоминаем,
      // иначе он затирал бы свежий статус проверки.
      renderUpdateIndicator();
    });
}

// Periodic background check (silent — banner only, no toasts).
// DEV-сборку не проверяем вовсе: узнав про dev:true, выходим из цикла.
setInterval(() => { if (!_devBuild) checkForUpdates(true); }, UPDATE_CHECK_INTERVAL);

// ── Индикация обновления в шапке ──
// Кнопка «Обновления» живёт в приклеенной шапке, поэтому её видно при любой
// прокрутке: она и есть главный индикатор (надпись «⬆ Обновить до vX» +
// пульсация), а тонкая точка — только дополнение к ней.
// Подпись — в обёртке .hdr-lbl: на узком экране она скрывается, и в шапке
// остаются только значки (иначе кнопка снова растягивала страницу вбок).
const UPDATE_BTN_IDLE = UI_ICONS.refresh + '<span class="hdr-lbl">Обновления</span>';
let _availableVersion = '';

function renderUpdateIndicator() {
  const btn = document.getElementById('btn-updates');
  if (!btn) return;
  const on = !!_availableVersion;
  if (!btn.dataset.busy) {
    btn.classList.toggle('has-update', on);
    btn.innerHTML = on
      ? (UI_ICONS.upload + '<span class="hdr-lbl">' + `Обновить до v${_availableVersion}` + '</span>')
      : UPDATE_BTN_IDLE;
    btn.setAttribute('aria-label', on ? `Обновить до v${_availableVersion}` : 'Обновления');
  }
  let dot = document.getElementById('update-dot');
  if (!dot) {
    dot = document.createElement('span');
    dot.id = 'update-dot';
    dot.title = 'Доступно обновление';
    btn.appendChild(dot);
  }
  if (on) {
    dot.dataset.version = _availableVersion;
    dot.classList.add('on');
  } else {
    dot.classList.remove('on');
  }
}

function setUpdateIndicator(on, version) {
  _availableVersion = on ? String(version || '') : '';
  renderUpdateIndicator();
}

// Высоту баннера нельзя зашить в CSS: на узком экране кнопки переносятся на
// вторую строку, и страницу нужно сдвинуть ровно на его высоту.
function _syncBannerOffset() {
  const banner = document.getElementById('update-banner');
  document.body.classList.toggle('has-update-banner', !!banner);
  document.body.style.paddingTop = banner ? banner.offsetHeight + 'px' : '';
}
window.addEventListener('resize', _syncBannerOffset);

// Закрытый баннер не возвращаем для ТОЙ ЖЕ версии (кнопка в шапке всё равно
// продолжает сообщать об обновлении), но новую версию показываем снова.
let _dismissedBannerVersion = '';

function dismissUpdateBanner() {
  const banner = document.getElementById('update-banner');
  _dismissedBannerVersion = banner ? (banner.dataset.version || '') : '';
  if (banner) banner.remove();
  _syncBannerOffset();
}

function showUpdateBanner(newVer, changelog, url) {
  // Remove existing banner if any
  const existing = document.getElementById('update-banner');
  if (existing) existing.remove();
  // Пользователь закрыл баннер этой версии — уважаем выбор: индикация
  // остаётся в шапке («⬆ Обновить до vX»), но окно больше не перекрываем.
  if (_dismissedBannerVersion && _dismissedBannerVersion === String(newVer)) {
    _syncBannerOffset();
    return;
  }

  // Frozen build: «Обновить сейчас» is the PRIMARY action — it downloads,
  // installs and restarts inside the app (no GitHub visit needed).
  // Source run: no in-app updater, so GitHub becomes the primary action.
  fetch('/update/status').then(r => r.json()).then(st => {
    // Сам обновляет файлы только Windows-сборка; macOS-бандл и исходники
    // получают ссылку на релиз (auto_apply=false приходит с сервера).
    const frozen = !!st.frozen && st.auto_apply !== false;
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.dataset.version = String(newVer);
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <button class="ub-btn" id="ub-changelog" onclick="showChangelog()" title="Подробнее об изменениях в новой версии">${UI_ICONS.file}Что нового</button>
      ${frozen
        ? `<button class="ub-btn ub-primary" id="ub-self-update" onclick="selfUpdate()" title="Скачать и установить прямо из приложения — после установки просто обновите страницу">${UI_ICONS.upload}Обновить сейчас</button>
           <a class="ub-btn" href="${url}" target="_blank" rel="noopener noreferrer" title="Страница релизов на GitHub">GitHub ↗</a>`
        : `<a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer" title="Скачайте сборку для своей системы на странице релизов">Скачать v${newVer} ↗</a>`}
      <button class="ub-close" onclick="dismissUpdateBanner()" title="Скрыть (индикация останется в шапке)">${UI_ICONS.x}</button>
    `;
    document.body.prepend(banner);
    _syncBannerOffset();
  }).catch(() => {
    // /update/status is dead — render the source-mode banner (GitHub primary)
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.dataset.version = String(newVer);
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
      <button class="ub-close" onclick="dismissUpdateBanner()" title="Скрыть (индикация останется в шапке)">${UI_ICONS.x}</button>
    `;
    document.body.prepend(banner);
    _syncBannerOffset();
  });
}

// ── Changelog viewer: full version.json (whats-new) in a modal ──
let _changelogCache = null;

function showChangelog() {
  const close = () => document.getElementById('changelog-overlay')?.remove();
  const render = (meta, err) => {
    const cur = (document.getElementById('app-version') || {}).textContent || '';
    const rows = (meta && meta.history ? meta.history : [])
      .map(h => `
        <div class="cl-entry ${h.version === (meta.version || '') ? 'cl-latest' : ''}">
          <div class="cl-ver">v${escapeHtml(h.version || '?')}${h.version === (meta.version || '') ? '<span class="cl-tag">новейшая</span>' : ''}${cur.includes(h.version) ? '<span class="cl-tag cl-yours">у вас</span>' : ''}</div>
          <div class="cl-text">${escapeHtml(h.changelog || '—')}</div>
        </div>`).join('')
      || `<div class="cl-entry"><div class="cl-text">${err ? 'Не удалось загрузить список изменений — проверьте интернет.' : escapeHtml((meta && meta.changelog) || '—')}</div></div>`;
    const overlay = document.createElement('div');
    overlay.id = 'changelog-overlay';
    overlay.className = 'ui-modal-overlay';
    overlay.innerHTML = `
      <div class="ui-modal changelog-modal">
        <h3>${UI_ICONS.file}Что нового</h3>
        <div class="cl-list">${rows}</div>
        <div class="ui-modal-btns">
          <button type="button" class="m-cancel" onclick="document.getElementById('changelog-overlay').remove()">Закрыть</button>
        </div>
      </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    document.body.appendChild(overlay);
  };
  if (_changelogCache) { render(_changelogCache); return; }
  fetch('/update/changelog')
    .then(r => r.json())
    .then(meta => { _changelogCache = meta; render(meta); })
    .catch(() => render(null, true));
}

// ── Self-update: download → apply → the app restarts itself ──
let _selfUpdating = false;

async function selfUpdate() {
  if (_selfUpdating) return;
  const btn = document.getElementById('ub-self-update');
  const txt = el => { if (btn) btn.textContent = el; };
  _selfUpdating = true;
  try {
    txt('⏳ Скачиваю…');
    const dl = await fetch('/update/download', { method: 'POST' })
      .then(r => r.json());
    if (!dl.ok) throw new Error(dl.error || 'Ошибка скачивания');

    txt('⏳ Устанавливаю…');
    const ap = await fetch('/update/apply', { method: 'POST' })
      .then(r => r.json());
    if (!ap.ok) throw new Error(ap.error || 'Ошибка установки');

    if (typeof showToast === 'function') showToast(ap.message || 'Обновление установлено, перезапускаюсь…', 'success');
    txt('✓ Перезапуск…');
    // The backend stops itself and the updater .bat restarts the exe.
    // Poll /update/status — as soon as the server answers again with a
    // fresh version, reload the page.
    const deadline = Date.now() + 60000;
    const poll = setInterval(async () => {
      try {
        const s = await fetch('/update/status', { cache: 'no-store' }).then(r => r.json());
        clearInterval(poll);
        location.reload();
      } catch (e) { if (Date.now() > deadline) { clearInterval(poll); location.reload(); } }
    }, 1500);
  } catch (e) {
    _selfUpdating = false;
    txt('⬆ Обновить сейчас');
    if (typeof showToast === 'function') showToast('Не удалось обновиться: ' + e.message, 'error');
  }
}
// ═══════════════════════════════════════════════════════════════
//  Шаблоны сообщений («📝 Шаблоны»)
