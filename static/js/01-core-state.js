// ═══════════════════════════════════════════
//  State
// ═══════════════════════════════════════════
let evtSource   = null;
let allResults  = [];
let filteredRows = [];
let sortCol     = -1;
let sortAsc     = true;
let curPage     = 1;
const PAGE_SIZE = 50;
let leafMap     = null;
let mapInited   = false;
let startTime   = 0;
// Когда поиск завершился (Date.now() на done) — «Время» в статистике замирает
// на фактической длительности и не растёт при каждом открытии вкладки.
let _runEnd     = null;
let activeSocialFilters = new Set();
let socialMode = 'all';  // 'all' | 'with_socials' | 'without_socials'
let parseMode = 'without_website';  // 'without_website' | 'all' — тип организаций
let notificationsEnabled = false;  // производный мастер-флаг (совместимость)
// ── Настройки уведомлений: что именно присылать (localStorage + попап) ──
const NOTIFY_KEY = 'notifications_settings';
const NOTIFY_DEFAULTS = { enabled: true, city_complete: true, search_complete: true };
// Звук настраивается отдельно: пресет на каждый тип события и общая
// громкость. Пресеты — только тоны Web Audio, никаких .mp3.
const VOLUME_DEFAULT = 0.7;
const SOUND_DEFAULTS = { city_complete: 'chime', search_complete: 'fanfare' };
const SOUND_PRESETS = {
  chime:   {label: 'Динь',        notes: [[880, 1760]],                    gain: 0.16, step: 0,    tail: 0.45},
  bell:    {label: 'Колокольчик', notes: [[1047, 2093], [1568, 3136]],      gain: 0.20, step: 0.14, tail: 0.72, type: 'triangle'},
  fanfare: {label: 'Мелодия',     notes: [523, 659, 784, [1047, 2093]],    gain: 0.26, step: 0.18, tail: 0.60},
  drop:    {label: 'Капля',       notes: [[1175, 2350], [784, 1568]],       gain: 0.18, step: 0.15, tail: 0.50},
  pulse:   {label: 'Импульс',     notes: [660, 660],                        gain: 0.18, step: 0.16, tail: 0.22, type: 'square'},
  beacon:  {label: 'Маяк',        notes: [[440, 880], [440, 880], [660, 1320]], gain: 0.20, step: 0.22, tail: 0.30, type: 'triangle'},
};
let notifySettings = Object.assign({}, NOTIFY_DEFAULTS);  // сохранённые настройки
let notifyDraft    = Object.assign({}, NOTIFY_DEFAULTS);  // черновик попапа
let _notifyHintShown = false;   // подсказку про разрешение — раз за прогон
let requiredSocials = new Set();   // AND filter: must have ALL selected socials

// ═══════════════════════════════════════════
//  Что парсить: какие поля собирать (аккордеон 02)
// ═══════════════════════════════════════════
// Каждое поле разворачивается в столбцы отчёта (excel_columns). Соцсети —
// «мастер»: без них не работают ни фильтр по соцсетям, ни массовый обход,
// ни статистика по соцсетям, ни активность ВКонтакте.
const PARSE_FIELD_COLS = {
  name:           ['name'],
  category:       ['category'],
  address:        ['address'],
  rating:         ['rating', 'reviews_count'],
  yandex_maps_url:['yandex_maps_url'],
  aggregator_url: ['aggregator_url'],
  socials:        ['vk', 'instagram', 'telegram', 'whatsapp'],
  phone:          ['phone'],
  vk_activity:    ['vk_activity', 'vk_followers', 'vk_last_post_days'],
};
// Служебные столбцы выгружаются всегда (не пользовательские данные).
const PARSE_SERVICE_COLS = ['reviewed', 'lead_score', 'query', 'parsed_at', 'city'];
const PARSE_REGULAR = [
  { k: 'name',            l: 'Название',              locked: true },
  { k: 'category',        l: 'Категория' },
  { k: 'address',         l: 'Адрес' },
  { k: 'rating',          l: 'Рейтинг и отзывы' },
  { k: 'yandex_maps_url', l: 'Ссылка на карточку' },
  { k: 'aggregator_url',  l: 'Сайт / Таплинк' },
  { k: 'socials',         l: 'Соцсети (ВК, TG, IG, WA)', master: true },
];
const PARSE_PERSONAL = [
  { k: 'phone',       l: 'Телефон организации' },
  { k: 'vk_activity', l: 'Активность ВКонтакте (подписчики, последний пост)', needsKey: true },
];
// null = значения по умолчанию (все обычные + телефон); иначе — Set ключей.
let parseFields = null;
function parseFieldsEnabled() {
  if (parseFields === null) {
    const s = new Set(PARSE_REGULAR.map(f => f.k));
    s.add('phone');   // телефон по умолчанию включён (основной контакт)
    return s;
  }
  return parseFields;
}
// Собираются ли соцсети вообще (мастер-переключатель «Соцсети»).
function socialsEnabled() { return parseFieldsEnabled().has('socials'); }
let vkMode = 'all';                 // 'all' | 'active_semi' | 'active' — VK activity filter
let _lastCompletedCityIdx = 0;     // track last completed city for notification
let _cityProgressData = {};        // {cityName: {total, found, status, pct}}
let _totalCities = 0;              // total cities in current run
let _currentCityName = '';         // name of city currently being processed
let _lastSkippedCities = [];       // skipped cities of last run (for stats tab)

// ═══════════════════════════════════════════
//  Multi-city progress tracking
// ═══════════════════════════════════════════
function initCityProgress(totalCities) {
  _totalCities = totalCities;
  // Don't reset _cityProgressData — preserve completed cities
  const el = document.getElementById('city-progress');
  const list = document.getElementById('city-progress-list');
  if (totalCities > 1) {
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
  updateTermProgress();
}

function updateCityProgress(cityName, pct, found, status) {
  if (!cityName || _totalCities <= 1) return;
  _cityProgressData[cityName] = { pct, found, status };
  renderCityProgress();
}

function renderCityProgress() {
  const list = document.getElementById('city-progress-list');
  if (!list) return;
  const entries = Object.entries(_cityProgressData);
  // Progress bar = % of the city's own work completed; the found count lives
  // in parentheses — the two metrics no longer share one slot.
  const meta = {
    running:  { icon: '⏳', color: '#007E8C' },
    done:     { icon: '✓',  color: '#2e9e5b' },
    skipped:  { icon: '⏭',  color: '#ff9800' },
    queued:   { icon: '⏸',  color: '#9aa5ad' },
    error:    { icon: '⚠️', color: '#e05252' },
  };
  list.innerHTML = entries.map(([name, data]) => {
    const m = meta[data.status] || meta.queued;
    const foundTxt = data.found > 0 ? ` (${data.found} найд.)` : (data.status === 'queued' ? ' (ожидание)' : '');
    return `<div class="cp-item cp-${data.status}">
      <span class="cp-ico">${m.icon}</span>
      <span class="cp-name" title="${name}">${name}</span>
      <div class="cp-bar"><div class="cp-fill" style="width:${data.pct}%;background:${m.color}"></div></div>
      <span class="cp-val">${data.pct}%<span class="cp-found">${foundTxt}</span></span>
    </div>`;
  }).join('');
  updateTermProgress();
  // Summary line: «Городов обработано: X из Y»
  const wrap = document.getElementById('city-progress');
  if (wrap) {
    const done = entries.filter(([, d]) => d.status === 'done' || d.status === 'skipped').length;
    let sumEl = document.getElementById('cp-summary');
    if (!sumEl) {
      sumEl = document.createElement('div');
      sumEl.id = 'cp-summary';
      wrap.insertBefore(sumEl, list);
    }
    sumEl.innerHTML = `Городов обработано: <b>${done}</b> из <b>${entries.length}</b>`;
  }
}

// ═══════════════════════════════════════════
//  Checkbox styling
// ═══════════════════════════════════════════
document.querySelectorAll('.chk input').forEach(cb => {
  cb.addEventListener('change', () => cb.closest('.chk').classList.toggle('on', cb.checked));
});

// ═══════════════════════════════════════════
//  Accordion sections (sidebar)
// ═══════════════════════════════════════════
function toggleAccordion(hdr) {
  const sec = hdr.closest('.acc');
  const open = sec.classList.toggle('open');
  hdr.setAttribute('aria-expanded', open ? 'true' : 'false');
  // Summary under «Основные параметры» reflects edits made while open/closed
  if (sec.id === 'acc-basic') updateBasicSummary();
  // Ленивые счётчики: считаем исключения и «тип компании», только когда раздел
  // реально открыли, а не на каждой загрузке страницы.
  if (open && sec.id === 'acc-filters') {
    scheduleBlacklistPreview();
    scheduleCompanyTypePreview();
  }
}

// ═══════════════════════════════════════════
//  Steppers (− value +)
// ═══════════════════════════════════════════
function stepValue(btn, dir) {
  const stp = btn.closest('.stepper');
  const inp = stp.querySelector('input');
  const min = parseFloat(stp.dataset.min ?? inp.min ?? 0);
  const max = parseFloat(stp.dataset.max ?? inp.max ?? Infinity);
  const step = parseFloat(stp.dataset.step || inp.step || 1);
  const dec = parseInt(stp.dataset.dec || (String(step).includes('.') ? String(step).split('.')[1].length : 0), 10);
  let v = parseFloat(inp.value);
  if (isNaN(v)) v = min;
  v = Math.min(max, Math.max(min, +(v + dir * step).toFixed(dec + 1)));
  inp.value = dec ? v.toFixed(dec) : Math.round(v);
}

// ═══════════════════════════════════════════
//  Inline field validation helpers
// ═══════════════════════════════════════════
function showFieldError(wrapEl, msg) {
  const inner = wrapEl.querySelector('textarea, input, select, .city-input-wrap');
  if (inner) inner.classList.add('field-invalid');
  wrapEl.classList.add('field-invalid');
  wrapEl.classList.add('shake');
  setTimeout(() => wrapEl.classList.remove('shake'), 350);
  let err = wrapEl.querySelector('.field-error');
  if (!err) {
    err = document.createElement('div');
    err.className = 'field-error';
    wrapEl.appendChild(err);
  }
  err.innerHTML = UI_ICONS.warn + escapeHtml(msg);
}

function clearFieldError(wrapEl) {
  if (!wrapEl) return;
  wrapEl.querySelectorAll('.field-error').forEach(e => e.remove());
  wrapEl.classList.remove('field-invalid');
  wrapEl.querySelectorAll('.field-invalid').forEach(e => e.classList.remove('field-invalid'));
}

// Modern confirm dialog — replacement for window.confirm
function uiConfirm(message, title = 'Подтвердите действие', okLabel = 'Удалить', danger = true) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'ui-modal-overlay';
    overlay.innerHTML = `
      <div class="ui-modal">
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
        <div class="ui-modal-btns">
          <button type="button" class="m-cancel">Отмена</button>
          <button type="button" class="m-ok${danger ? ' danger' : ''}">${escapeHtml(okLabel)}</button>
        </div>
      </div>`;
    const done = val => { overlay.remove(); resolve(val); };
    overlay.querySelector('.m-cancel').onclick = () => done(false);
    overlay.querySelector('.m-ok').onclick = () => done(true);
    overlay.addEventListener('click', e => { if (e.target === overlay) done(false); });
    overlay.addEventListener('keydown', e => { if (e.key === 'Escape') done(false); });
    document.body.appendChild(overlay);
    overlay.querySelector('.m-ok').focus();
  });
}

// ═══════════════════════════════════════════
//  Toast notifications (stacked, top-right)
// ═══════════════════════════════════════════
function showToast(message, type) {
  const cont = document.getElementById('toast-container');
  if (!cont) { console.log('[' + (type || 'info') + ']', message); return; }
  const toast = document.createElement('div');
  toast.className = 'toast ' + (type || 'success');
  const ok = (type || 'success') !== 'error';
  toast.innerHTML = `<span class="t-ico">${ok ? UI_ICONS.check : UI_ICONS.x}</span><span>${escapeHtml(message)}</span>`;
  cont.appendChild(toast);
  requestAnimationFrame(() => requestAnimationFrame(() => toast.classList.add('show')));
  const hide = () => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 350);
  };
  toast._autoHide = setTimeout(hide, 3500);
  toast.onclick = hide;
}

// ═══════════════════════════════════════════
//  Social mode toggle (form)
// ═══════════════════════════════════════════
function setSocialMode(mode) {
  socialMode = mode;
  document.querySelectorAll('.social-mode-opt').forEach(el => {
    const radio = el.querySelector('input[type=radio]');
    const isActive = radio.value === mode;
    el.classList.toggle('active', isActive);
    radio.checked = isActive;
  });
  updateSocialFilterHint();
  // Reveal the network tiles only for «С соцсетями»; leaving the mode clears
  // the selection so a hidden filter can never stay active.
  const netFilter = document.getElementById('social-network-filter');
  if (netFilter) netFilter.classList.toggle('open', mode === 'with_socials');
  if (mode !== 'with_socials' && requiredSocials.size) {
    requiredSocials.clear();
    document.querySelectorAll('#social-net-chk-grid .soc-tile.on').forEach(t => {
      t.classList.remove('on');
      const cb = t.querySelector('input[type=checkbox]');
      if (cb) cb.checked = false;
    });
    updateSocialFilterHint();
  }
  // Re-filter table if results exist
  if (allResults.length) filterTable();
}

// Hint under the social radios: names EXACTLY which organizations survive.
// The tiles only exist in «С соцсетями», so they can never look ignored.
function updateSocialFilterHint() {
  const hint = document.getElementById('social-mode-hint');
  if (!hint) return;
  const nets = [...requiredSocials]
    .map(k => (typeof SNAMES !== 'undefined' && SNAMES[k]) || SLABELS[k] || k)
    .join(', ');
  if (socialMode === 'without_socials') {
    hint.textContent = 'Останутся только организации без соцсетей';
  } else if (nets) {
    hint.textContent = `Останутся организации, у которых есть все отмеченные сети: ${nets}`;
  } else {
    hint.textContent = socialMode === 'with_socials'
      ? 'Останутся только организации с любой найденной соцсетью'
      : 'Попадут все организации из сырых данных';
  }
}

// ═══════════════════════════════════════════
//  Parse-mode toggle: «Только без сайтов» / «Все организации»
// ═══════════════════════════════════════════
function setParseMode(mode) {
  parseMode = mode;
  document.querySelectorAll('.parse-mode-opt').forEach(el => {
    const radio = el.querySelector('input[type=radio]');
    const isActive = radio.value === mode;
    el.classList.toggle('active', isActive);
    radio.checked = isActive;
  });
  const hint = document.getElementById('parse-mode-hint');
  if (hint) {
    hint.textContent = mode === 'all'
      ? 'Парсить все организации, независимо от наличия сайта'
      : 'Находить только компании без собственного сайта — ваши потенциальные клиенты';
  }
}

// Grid coverage mode ('whole' | 'manual') — single source of truth for
// use_grid: the old f-grid checkbox no longer exists in the markup.
let _gridMode = 'whole';
// Браузер — единственный способ загрузки страниц: показываем бейдж
// «Chrome найден / не найден» (лёгкий запрос, без сетевых проб).
// Сеть отвалилась — бейдж просто не показываем, форме это не вредит.
function refreshBrowserAvailability() {
  const box = document.getElementById('engine-availability');
  if (!box) return;
  fetch('/engines/status').then(r => r.ok ? r.json() : null).then(s => {
    if (!s || !s.ok) return;
    // Это браузер ДЛЯ СБОРА (CDP), а не браузер по умолчанию: интерфейс
    // может открываться в другом, а страницы Яндекс.Карт грузит этот.
    // Подходят только Chromium-браузеры (Chrome/Chromium/Edge); Safari и
    // Firefox CDP-автоматизацию не поддерживают.
    box.innerHTML = s.chrome
      ? '<span class="engine-badge ok" title="Этим браузером программа открывает страницы для сбора — он не обязан совпадать с вашим браузером по умолчанию">'
        + '✔ Для сбора найден: ' + (s.chrome_path || 'Chromium-браузер').split(/[\\/]/).pop() + '</span>'
      : '<span class="engine-badge miss" title="Сбор идёт через Chrome DevTools Protocol: нужен Chrome, Chromium или Edge">'
        + '✖ Chromium-браузер не найден — установите Google Chrome, Chromium или Edge (Safari и Firefox не подходят)</span>';
    box.style.display = '';
  }).catch(() => {});
}

// ═══════════════════════════════════════════
//  Social network checkboxes (AND filter)
// ═══════════════════════════════════════════
function initSocialNetCheckboxes() {
  const grid = document.getElementById('social-net-chk-grid');
  if (!grid) return;
  grid.innerHTML = Object.entries(SLABELS).map(([key, label]) =>
    `<label class="soc-tile soc-tile-sm" style="--tile:${SOCIALS[key] || '#9aa'}" onclick="event.preventDefault();toggleRequiredSocial('${key}', this)" title="${escapeHtml(SNAMES[key] || label)}">
       <span class="soc-ico">${label}</span>
       <span class="soc-name">${SNAMES[key] || label}</span>
       <span class="soc-mark">✓</span>
       <input type="checkbox" value="${key}" style="display:none" data-soc-key="${key}">
     </label>`
  ).join('');
}

function toggleRequiredSocial(key, tileEl) {
  const cb = tileEl ? tileEl.querySelector('input[type=checkbox]') : null;
  const checked = cb ? !cb.checked : !requiredSocials.has(key);
  if (cb) cb.checked = checked;
  if (checked) requiredSocials.add(key);
  else requiredSocials.delete(key);
  if (tileEl) tileEl.classList.toggle('on', checked);
  updateSocialFilterHint();
  if (allResults.length) filterTable();
}

// ═══════════════════════════════════════════
//  Grid toggle (legacy hook — the markup now uses radio modes)
// ═══════════════════════════════════════════
function toggleGrid() {
  // Legacy checkbox support (e.g. restored presets) — maps to radio mode.
  setGridMode(document.getElementById('f-grid')?.checked ? 'manual' : 'whole');
}

// ── Grid coverage mode: «Весь город» / «Настроить вручную» ─────
// The hidden checkbox f-grid stays the single source of truth for the
// backend contract (use_grid), and the hidden number inputs f-grad/f-gstep
// keep their ids so getParams()/presets work unchanged.
function setGridMode(mode) {
  const row = document.getElementById('grid-mode-row');
  if (row) {
    row.querySelectorAll('.grid-mode-opt').forEach(el => {
      const radio = el.querySelector('input[type=radio]');
      const isActive = el.dataset.mode === mode;
      el.classList.toggle('active', isActive);
      if (radio) radio.checked = isActive;
    });
  }
  const manual = mode === 'manual';
  _gridMode = mode;
  const opts = document.getElementById('grid-opts');
  if (opts) opts.style.display = manual ? '' : 'none';
  const lbl = document.getElementById('grid-lbl');
  if (lbl) lbl.classList.toggle('on', manual);
  if (manual) onGridSlider();
}

// Slider UI: values out, live ratio hint, forecast, sync into
// the hidden inputs (f-grad/f-gstep are the values getParams() reads).
// Step is hard-linked to Radius: max(Шаг) = Радиус (ideal ceiling R/2), so a
// sparse layout is impossible to configure — the slider simply won't go there.
function onGridSlider() {
  const grad = document.getElementById('f-grad');
  const gstep = document.getElementById('f-gstep');
  const rOut = document.getElementById('grid-radius-out');
  const sOut = document.getElementById('grid-step-out');
  const sScale = document.getElementById('grid-step-scale');
  const hint = document.getElementById('grid-hint');
  if (!grad || !gstep) return;
  let r = +grad.value, s = +gstep.value;
  // ── Link: Шаг never exceeds Радиус; ceiling R/2 as the overlap limit ──
  const stepMax = Math.max(1, r);              // hard cap = radius itself
  if (+gstep.max !== stepMax) gstep.max = stepMax;
  if (s > stepMax) { s = stepMax; gstep.value = s; }
  if (sOut) sOut.textContent = s;
  if (sScale) {                                // keep the right scale label in sync
    sScale.children[0].textContent = '1 км';
    sScale.children[1].textContent = Math.round(stepMax / 2) + ' км';
    sScale.children[2].textContent = stepMax + ' км';
  }
  if (rOut) rOut.textContent = r;
  // Paint the filled part of the track (webkit gradient var)
  const paint = el => {
    const min = +el.min || 0, max = +el.max || 100;
    el.style.setProperty('--fill', Math.round(((+el.value - min) / (max - min)) * 100) + '%');
  };
  paint(grad); paint(gstep);
  if (!hint) return;

  const nQueries = (document.getElementById('f-queries')?.value || '').split('\n').map(x=>x.trim()).filter(Boolean).length || 1;
  const pages = Math.min(5, Math.max(1, +document.getElementById('f-pages')?.value || 1));

  // ── 1) Coverage state — three bands around the 1:4 ratio ──────────
  // Яндекс не имеет радиуса точки: при шаг > R/2 между областями поиска
  // остаются «дыры», и часть города не просматривается. 1:4 держит
  // перекрытие достаточно щедрым.
  const ratio4 = s / Math.max(1, r);            // step : radius, 0.25 = ideal
  let stateTxt, tone;
  if (s > r / 2) {
    stateTxt = 'Слишком редко — между точками будут «дыры». Вы пропустите часть компаний. Уменьшите шаг';
    tone = 'sparse';
  } else if (ratio4 < 0.125) {
    if (ratio4 < 0.0625) {
      stateTxt = 'Избыточно плотно — поиск займёт много времени и запросов, хотя данные почти не улучшатся';
      tone = 'dense2';
    } else {
      stateTxt = 'Плотно — запросов заметно больше нужного, покрытие уже полное';
      tone = 'dense';
    }
  } else {
    stateTxt = 'Оптимально — ячейки слегка перекрываются. Покрытие полное';
    tone = 'ok';
  }

  // ── 2) Forecast: сколько точек и страниц откроет браузер ────────
  const cells = Math.max(1, Math.round(Math.PI * Math.pow(r / Math.max(1, s), 2) * 0.64) + 1);
  const tokens = cells * nQueries * pages;
  const tokFmt = n => n >= 10000 ? Math.round(n / 1000) + ' тыс.' : n.toLocaleString('ru-RU');
  const tokWord = n => (n % 10 === 1 && n % 100 !== 11) ? 'точка'
    : ([2,3,4].includes(n % 10) && ![12,13,14].includes(n % 100)) ? 'точки' : 'точек';

  // ── 3) Render: line 1 = state, line 2 = forecast; color only the fragments ──
  hint.classList.remove('sparse', 'dense', 'dense2', 'ok', 'warn');
  if (tone) hint.classList.add(tone);
  const recTxt = `Рекомендуемое соотношение: 1:4 · Текущее: ${s} : ${r}`;
  const toneIcon = tone === 'ok' ? UI_ICONS.check : tone === 'sparse' ? UI_ICONS.warn : UI_ICONS.info;
  const line1 = `<span class="hint-state">${toneIcon}${stateTxt}</span>`
    + ` <span class="hint-rec">${recTxt}</span>`;
  const line2 = `<span class="hint-tok tok-src">Прогноз: ~${tokFmt(cells)} ${tokWord(cells)}, `
    + `~${tokFmt(tokens)} страниц поиска · ограничений тарифа нет</span>`;
  hint.innerHTML = `<div class="hint-line">${line1}</div><div class="hint-line">${line2}</div>`;
}

// ── «Волшебная палочка»: auto-tune coverage to the recommended pair ──
// Radius = 20 km, Step = Radius/4 (5 km) — the overlap-safe default for
// both sources. Animates the sliders smoothly so the user sees the values,
// the track fill and the hint color settle together.
function gridAutoTune() {
  const grad = document.getElementById('f-grad');
  const gstep = document.getElementById('f-gstep');
  if (!grad || !gstep) return;
  setGridMode('manual');                       // reveal sliders if hidden
  const from = { r: +grad.value, s: +gstep.value };
  const to   = { r: 20, s: 5 };                // 20/4 = 5 → ratio 1:4
  if (from.r === to.r && from.s === to.s) {    // nothing to change — pulse the hint
    const hint = document.getElementById('grid-hint');
    if (hint) { hint.classList.add('wand-ok'); setTimeout(() => hint.classList.remove('wand-ok'), 700); }
    return;
  }
  const DUR = 450, t0 = performance.now();
  const ease = t => 1 - Math.pow(1 - t, 3);    // easeOutCubic
  const step = now => {
    const t = Math.min(1, (now - t0) / DUR);
    const k = ease(t);
    grad.value  = Math.round(from.r + (to.r - from.r) * k);
    gstep.value = Math.round(from.s + (to.s - from.s) * k);
    onGridSlider();                            // repaint fill + hint every frame
    if (t < 1) requestAnimationFrame(step);
    else { grad.value = to.r; gstep.value = to.s; onGridSlider(); }
  };
  requestAnimationFrame(step);
}

// ═══════════════════════════════════════════
//  City combobox — population data
// ═══════════════════════════════════════════
const CITIES_DATA = [
  {name:'Москва',pop:13104177},{name:'Санкт-Петербург',pop:5600044},{name:'Новосибирск',pop:1635338},{name:'Екатеринбург',pop:1544376},{name:'Казань',pop:1308660},
  {name:'Нижний Новгород',pop:1204985},{name:'Челябинск',pop:1196680},{name:'Самара',pop:1173299},{name:'Уфа',pop:1144809},{name:'Ростов-на-Дону',pop:1142162},
  {name:'Красноярск',pop:1196913},{name:'Воронеж',pop:1058261},{name:'Пермь',pop:1055397},{name:'Волгоград',pop:1028036},{name:'Краснодар',pop:1121291},
  {name:'Саратов',pop:838042},{name:'Тюмень',pop:816907},{name:'Тольятти',pop:694998},{name:'Ижевск',pop:648318},{name:'Барнаул',pop:630877},
  {name:'Ульяновск',pop:617075},{name:'Иркутск',pop:623005},{name:'Хабаровск',pop:617448},{name:'Ярославль',pop:599169},{name:'Владивосток',pop:605647},
  {name:'Махачкала',pop:609621},{name:'Томск',pop:576746},{name:'Оренбург',pop:564407},{name:'Кемерово',pop:556434},{name:'Новокузнецк',pop:537385},
  {name:'Рязань',pop:538962},{name:'Астрахань',pop:520339},{name:'Набережные Челны',pop:533392},{name:'Пенза',pop:501109},{name:'Липецк',pop:510024},
  {name:'Тула',pop:472522},{name:'Киров',pop:501468},{name:'Чебоксары',pop:497611},{name:'Калининград',pop:490449},{name:'Брянск',pop:399704},
  {name:'Курск',pop:452331},{name:'Иваново',pop:400315},{name:'Магнитогорск',pop:413571},{name:'Тверь',pop:414070},{name:'Ставрополь',pop:398539},
  {name:'Нижний Тагил',pop:362224},{name:'Белгород',pop:399690},{name:'Архангельск',pop:338867},{name:'Владимир',pop:352347},{name:'Сочи',pop:466078},
  {name:'Симферополь',pop:365511},{name:'Якутск',pop:349315},{name:'Улан-Удэ',pop:437543},{name:'Мурманск',pop:270283},{name:'Чита',pop:341509},
  {name:'Вологда',pop:313549},{name:'Череповец',pop:312379},{name:'Саранск',pop:316525},{name:'Смоленск',pop:325656},{name:'Орёл',pop:307478},
  {name:'Калуга',pop:341393},{name:'Курган',pop:311417},{name:'Тамбов',pop:290624},{name:'Кострома',pop:277656},{name:'Сургут',pop:396410},
  {name:'Нижневартовск',pop:283034},{name:'Новороссийск',pop:279038},{name:'Ханты-Мансийск',pop:315066},{name:'Нальчик',pop:242531},{name:'Владикавказ',pop:304286},
  {name:'Грозный',pop:328277},{name:'Майкоп',pop:234900},{name:'Черкесск',pop:123260},{name:'Элиста',pop:103749},{name:'Нарьян-Мар',pop:24723},
  {name:'Петрозаводск',pop:281680},{name:'Псков',pop:215560},{name:'Великий Новгород',pop:223400},{name:'Сыктывкар',pop:233310},{name:'Ухта',pop:99441},
  {name:'Северодвинск',pop:183720},{name:'Комсомольск-на-Амуре',pop:249610},{name:'Благовещенск',pop:225090},{name:'Южно-Сахалинск',pop:207396},{name:'Находка',pop:156390},
  {name:'Петропавловск-Камчатский',pop:181460},{name:'Магадан',pop:92050},{name:'Уссурийск',pop:180790},{name:'Рыбинск',pop:175560},{name:'Абакан',pop:184780},
  {name:'Бийск',pop:208140},{name:'Рубцовск',pop:143590},{name:'Бердск',pop:51580},{name:'Кызыл',pop:120060},{name:'Горно-Алтайск',pop:58470},
  {name:'Дзержинск',pop:227200},{name:'Саров',pop:93260},{name:'Арзамас',pop:103440},{name:'Сызрань',pop:165750},{name:'Новокуйбышевск',pop:100690},
  {name:'Братск',pop:234730},{name:'Ангарск',pop:226390},{name:'Усть-Илимск',pop:59960},{name:'Воткинск',pop:97500},{name:'Сарапул',pop:96160},
  {name:'Глазов',pop:93590},{name:'Зеленодольск',pop:97420},{name:'Альметьевск',pop:159740},{name:'Нижнекамск',pop:234044},{name:'Чистополь',pop:58930},
  {name:'Дербент',pop:126940},{name:'Каспийск',pop:121100},{name:'Хасавюрт',pop:144710},{name:'Буйнакск',pop:65610},{name:'Избербаш',pop:56820},
  {name:'Котлас',pop:58780},{name:'Коряжма',pop:35660},{name:'Кушва',pop:28580},{name:'Верхний Уфалей',pop:28580},{name:'Тутаев',pop:99340},
  {name:'Переславль-Залесский',pop:38540},{name:'Углич',pop:32130},{name:'Ростов',pop:31030},{name:'Мышкин',pop:5570},{name:'Суздаль',pop:10200},
  {name:'Плёс',pop:1840},{name:'Навашино',pop:14450},{name:'Выкса',pop:45250},{name:'Балахна',pop:49800},{name:'Кстово',pop:65310},
  {name:'Жигулёвск',pop:55080},{name:'Отрадный',pop:47370},{name:'Свободный',pop:49060},{name:'Заречный',pop:28480},{name:'Обь',pop:30930},
  {name:'Искитим',pop:57830},{name:'Тогучин',pop:18320},{name:'Кизляр',pop:48450},
  // CIS
  {name:'Минск',pop:2009800},{name:'Алматы',pop:2154700},{name:'Ташкент',pop:2822500},{name:'Баку',pop:2303200},{name:'Бишкек',pop:1121900},
  {name:'Астана',pop:1354900},{name:'Тбилиси',pop:1118035},{name:'Ереван',pop:1106100},{name:'Душанбе',pop:1201800},{name:'Ашхабад',pop:1031900},{name:'Кишинёв',pop:820900},
];
const MAX_POP = CITIES_DATA[0].pop; // Moscow = largest
// Pre-built lookup for O(1) city search by name
const _citiesByName = new Map(CITIES_DATA.map(c => [c.name.toLowerCase(), c]));

function formatPopulation(pop) {
  if (pop >= 1000000) return (pop / 1000000).toFixed(1).replace(/\.0$/,'') + 'м';
  if (pop >= 1000) return Math.round(pop / 1000) + 'к';
  return String(pop);
}

// ═══════════════════════════════════════════
//  City combobox — UI
// ═══════════════════════════════════════════
let selectedCities = [];
let citySearchText = '';

// ── City search-history meta ────────────────────────────────
// Map cityName -> {lastTs: number, queries: string[]} built from /history,
// so the city dropdown can show when a city was last searched and with
// which keywords. /history returns newest-first entries, so the first
// entry mentioning a city IS its last search — its timestamp and queries
// are shown together. Derived from the same store the history tab uses,
// so clearing history automatically clears these labels too.
let _cityHistory = {};

function loadCityHistoryMeta() {
  return fetch('/history?limit=100')
    .then(r => r.json())
    .then(data => {
      const map = {};
      const hist = data.history || [];
      for (const e of hist) {
        const ts = e.timestamp || 0;
        for (const city of (e.cities || [])) {
          if (!(city in map)) {
            map[city] = { lastTs: ts, queries: [...(e.queries || [])] };
          }
        }
      }
      _cityHistory = map;
      // If the dropdown is open, re-render so "last searched" lines appear
      const dd = document.getElementById('city-dropdown');
      if (dd && dd.classList.contains('open')) updateCityDropdown();
    })
    .catch(() => {});
}

// HTML for the "last searched" line under a city name in the dropdown.
// Variant Б+В: show up to 3 keywords, "+N" for the rest, full list in a
// tooltip. Empty string when the city was never searched.
function cityHistoryLine(name) {
  const h = _cityHistory[name];
  if (!h || !h.lastTs) return '';
  const dateStr = new Date(h.lastTs * 1000).toLocaleDateString('ru-RU'); // ДД.ММ.ГГГГ
  const qs = h.queries;
  let kw = qs.slice(0, 3).join(', ');
  if (qs.length > 3) kw += ` +${qs.length - 3}`;
  const full = qs.join(', ');
  return `<div class="city-option-hist" title="Искали: ${escapeHtml(full)} · ${dateStr}">🕒 ${dateStr} · ${escapeHtml(kw)}</div>`;
}

function initCitySelect() {
  const box = document.getElementById('city-select-box');
  box.innerHTML = '';

  // ── Tags row ──
  const tagsRow = document.createElement('div');
  tagsRow.className = 'city-tags-row';
  tagsRow.id = 'city-tags-row';
  box.appendChild(tagsRow);

  // ── Input row ──
  const wrap = document.createElement('div');
  wrap.className = 'city-input-wrap';
  wrap.id = 'city-input-wrap';
  const inp = document.createElement('input');
  inp.type = 'text'; inp.id = 'f-city-input';
  inp.placeholder = 'Добавить город…';
  inp.autocomplete = 'off';
  const clr = document.createElement('button');
  clr.className = 'city-clear';
  clr.innerHTML = UI_ICONS.x;
  clr.onclick = (e) => {
    e.preventDefault();
    citySearchText = '';
    inp.value = '';
    updateCityDropdown();
    inp.focus();
  };
  wrap.appendChild(inp);
  wrap.appendChild(clr);
  box.appendChild(wrap);

  // ── Dropdown ──
  // Appended to document.body with position:fixed so no accordion overflow
  // can clip it (the list used to be cut at the accordion border).
  const dd = document.createElement('div');
  dd.className = 'city-dropdown'; dd.id = 'city-dropdown';
  document.body.appendChild(dd);

  // ── Events (attached once) ──
  inp.addEventListener('input', e => {
    citySearchText = e.target.value;
    clr.classList.toggle('visible', citySearchText.length > 0);
    updateCityDropdown();
  });
  inp.addEventListener('focus', () => { updateCityDropdown(); });
  inp.addEventListener('blur', () => {
    setTimeout(() => {
      if (dd.contains(document.activeElement)) return; // focus moved into the dropdown
      dd.classList.remove('open');
      if (citySearchText.trim()) {
        const match = _citiesByName.get(citySearchText.trim().toLowerCase());
        if (match && !selectedCities.includes(match.name)) addCity(match.name);
        citySearchText = '';
        inp.value = '';
        clr.classList.remove('visible');
      }
    }, 200);
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const visible = getFilteredCities();
      if (visible.length) addCity(visible[0].name);
      else if (citySearchText.trim()) addCity(citySearchText.trim());
    }
    if (e.key === 'Escape') dd.classList.remove('open');
    if (e.key === 'Backspace' && !inp.value && selectedCities.length) {
      removeCity(selectedCities.length - 1);
    }
  });

  // Initial render of tags
  renderCityTags();
}

// ── Fixed positioning for the body-level dropdown ────────────
// Anchors the dropdown to the input's on-screen rect. Runs on open and on
// window scroll/resize so the list follows the input while either panel scrolls.
function positionCityDropdown() {
  const inp = document.getElementById('f-city-input');
  const dd  = document.getElementById('city-dropdown');
  if (!inp || !dd) return;
  if (!dd.classList.contains('open')) return;
  const r = inp.getBoundingClientRect();
  dd.style.position = 'fixed';
  dd.style.top = (r.bottom + 4) + 'px';
  dd.style.left = r.left + 'px';
  dd.style.width = r.width + 'px';
  dd.style.maxHeight = Math.max(120, window.innerHeight - r.bottom - 16) + 'px';
  dd.style.zIndex = '9999';
}

// Close on outside click (mousedown so it fires before blur's timeout)
document.addEventListener('mousedown', e => {
  const dd  = document.getElementById('city-dropdown');
  const inp = document.getElementById('f-city-input');
  if (!dd) return;
  if (dd.classList.contains('open') && !dd.contains(e.target) && e.target !== inp) {
    dd.classList.remove('open');
  }
});
window.addEventListener('scroll', positionCityDropdown, true);  // capture: panel scrolls
window.addEventListener('resize', positionCityDropdown);

function renderCityTags() {
  const tagsRow = document.getElementById('city-tags-row');
  if (!tagsRow) return;
  tagsRow.innerHTML = selectedCities.map((c, i) =>
    `<span class="city-tag">${c}<span class="city-tag-x" role="button" aria-label="Убрать город" onclick="removeCity(${i})">${UI_ICONS.x}</span></span>`
  ).join('');
  // Update placeholder
  const inp = document.getElementById('f-city-input');
  if (inp) inp.placeholder = selectedCities.length ? 'Добавить город…' : 'Начните вводить название города…';
  updateCityCount();
  updateClearAllBtn();
  updateBasicSummary();
  updateRunBtnState();
}

refreshBrowserAvailability();   // бейдж «Chrome найден/не найден» в форме

// ═══════════════════════════════════════════
//  Sidebar counters / clear-all / accordion summary (01 · Основные параметры)
