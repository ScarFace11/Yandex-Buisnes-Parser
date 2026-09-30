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
let dataSource = 'yandex';  // 'yandex' | '2gis' — источник данных
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

// ═══════════════════════════════════════════
//  Data-source toggle: Яндекс.Карты / 2GIS
// ═══════════════════════════════════════════
let _twogisKeyPresent = null;  // null = not yet checked; else bool
function setDataSource(src) {
  dataSource = src;
  document.querySelectorAll('.source-mode-opt').forEach(el => {
    const radio = el.querySelector('input[type=radio]');
    const isActive = radio.value === src;
    el.classList.toggle('active', isActive);
    radio.checked = isActive;
  });
  const hint = document.getElementById('source-hint');
  if (hint) {
    const keySpan = '<span class="source-hint-key" id="source-key-state"></span>';
    hint.innerHTML = src === '2gis'
      ? `<b>Быстрее.</b> Контакты и соцсети — только через Chrome. <b>Ключ</b> автоматически подтягивается из .env.<br>${keySpan}`
      : '<b>Медленнее.</b> Соцсети собираются с карточек организаций. <b>Требует</b> API-ключ Яндекса.';
  }
  if (src === '2gis') refreshSourceKeyState();
  updateBasicSummary();
  updatePagesCapNote();
  // 2GIS has a 50-orgs-per-point cap → the default coverage should be the
  // overlap-friendly 4×1 ratio; refresh the hint (it embeds token estimates
  // only for 2GIS) and, on first switch to 2GIS, nudge sliders to it.
  onGridSlider();
  if (src === '2gis' && !_grid2gisNudged) {
    _grid2gisNudged = true;
    if (_gridMode === 'manual') {
      const grad = document.getElementById('f-grad'), gstep = document.getElementById('f-gstep');
      if (grad && gstep && (+gstep.value > +grad.value / 4 + 1)) {
        gstep.value = Math.max(1, Math.round(+grad.value / 4));
        onGridSlider();
      }
    }
  }
}
let _grid2gisNudged = false;

// 2GIS never returns more than 5 pages per search point (5 × 10 = 50 orgs).
// The «Страниц» stepper still allows 1–20, so when 2GIS is active and the
// value exceeds the cap we say so right under the stepper instead of
// silently wasting the user's setting.
function updatePagesCapNote() {
  const note = document.getElementById('pages-cap-note');
  if (!note) return;
  const pages = +document.getElementById('f-pages')?.value || 1;
  const capped = dataSource === '2gis' && pages > 5;
  note.hidden = !capped;
  if (capped) note.textContent = `2GIS отдаёт максимум 5 страниц (50 организаций с точки) — значение будет ограничено с ${pages} до 5`;
}

// Grid coverage mode ('whole' | 'manual') — single source of truth for
// use_grid: the old f-grid checkbox no longer exists in the markup.
let _gridMode = 'whole';
// Live 2GIS Places quota (tokens spent this run), streamed via progress events.
let _twogisQuotaLive = 0;

// Show whether a 2GIS key is available (.env or the advanced-settings field)
function refreshSourceKeyState() {
  const el = document.getElementById('source-key-state');
  if (!el) return;
  const local = ((document.getElementById('f-2gis-key') || {}).value || '').trim();
  if (local) {
    el.textContent = 'Ключ указан в настройках — будет использован он';
    el.classList.remove('missing');
    return;
  }
  const firstTime = _twogisKeyPresent === null;
  fetch('/twogis/key-status')
    .then(r => r.json())
    .then(j => {
      _twogisKeyPresent = !!j.present;
      el.textContent = _twogisKeyPresent
        ? 'Ключ найден в .env — можно запускать'
        : 'Ключ не найден: добавьте TWOGIS_API_KEY в .env или поле ниже, иначе поиск пойдёт через Яндекс';
      el.classList.toggle('missing', !_twogisKeyPresent);
    })
    .catch(() => {
      if (firstTime) el.textContent = '';
    });
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

// Slider UI: values out, live ratio hint, 2GIS token estimate, sync into
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

  const is2gis = dataSource === '2gis';
  const nQueries = (document.getElementById('f-queries')?.value || '').split('\n').map(x=>x.trim()).filter(Boolean).length || 1;
  const pages = Math.min(5, Math.max(1, +document.getElementById('f-pages')?.value || 1));

  // ── 1) Coverage state — three bands around the 1:4 ratio ──────────
  // 2GIS circles each point at ~1.5×step (twogis.py), so neighbours always
  // overlap; its real risk is the 50-orgs-per-point cap in dense districts.
  // Yandex has no per-point radius: step > R/2 can leave "holes" between
  // search areas — parts of the city go unsearched. 1:4 keeps overlap
  // generous for both sources.
  const ratio4 = s / Math.max(1, r);            // step : radius, 0.25 = ideal
  let stateTxt, tone;
  if (s > r / 2) {
    stateTxt = is2gis
      ? 'Слишком редко — в плотных районах упрётесь в лимит 50 организаций на точку'
      : 'Слишком редко — между точками будут «дыры». Вы пропустите часть компаний. Уменьшите шаг';
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

  // ── 2) Token forecast (backend formula: π(R/шаг)²·0.64 + 1) ──────
  // Corrected: radius-based, not diameter (was overestimating ~3.5×).
  const cells = Math.max(1, Math.round(Math.PI * Math.pow(r / Math.max(1, s), 2) * 0.64) + 1);
  const tokens = cells * nQueries * pages;
  const tokenPct = Math.round(tokens / 10);     // % of the 1000-request free tier
  const tokCls = tokenPct > 100 ? 'tok-crit' : tokenPct > 50 ? 'tok-warn' : 'tok-ok';
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
  const forecast = `Прогноз: ~${tokFmt(cells)} ${tokWord(cells)}, ~${tokFmt(tokens)} запросов к API`
    + ` (~${tokFmt(tokens * 10)} организаций, ${tokenPct}% бесплатного тарифа)`;
  const line2 = is2gis
    ? `<span class="hint-tok ${tokCls}">${forecast}</span>`
    : `<span class="hint-tok tok-src">Прогноз: ~${tokFmt(cells)} ${tokWord(cells)}, ~${tokFmt(tokens)} запросов · без лимита тарифа</span>`;
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

// ═══════════════════════════════════════════
//  Sidebar counters / clear-all / accordion summary (01 · Основные параметры)
// ═══════════════════════════════════════════
// Russian plural: 1 → one, 2-4 → few, 5-20 → many (n%10, n%100 rules).
function _pluralRu(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// Count non-empty (trimmed) lines of the queries textarea.
function _countQueries() {
  const el = document.getElementById('f-queries');
  if (!el) return 0;
  return (el.value || '').split('\n').map(s => s.trim()).filter(Boolean).length;
}

// «Будет выполнен 1 запрос / Будет выполнено N запросов» — hidden when empty;
// capped at «10+» so the UI never gets crowded (edge case 3).
function updateQueriesCounter() {
  const el = document.getElementById('queries-count');
  if (!el) return;
  const n = _countQueries();
  if (!n) { el.hidden = true; return; }
  const shown = n >= 10 ? '10+' : String(n);
  el.textContent = `• Будет выполнен${n === 1 ? '' : 'о'} ${shown} ${_pluralRu(n, 'запрос', 'запроса', 'запросов')}`;
  el.hidden = false;
  updateRunBtnState();
}

// «(3 города)» next to the «Где ищем?» label — 1 город / 2-4 города / 5+ городов.
function updateCityCount() {
  const el = document.getElementById('city-count');
  if (!el) return;
  const n = selectedCities.length;
  if (!n) { el.hidden = true; return; }
  el.textContent = `(${n} ${_pluralRu(n, 'город', 'города', 'городов')})`;
  el.hidden = false;
}

// ── Run-button readiness / state ─────────────────────────────
// The «Найти компании» button is always visible (sticky dock) and must
// communicate what is missing: grey while there are no cities or no queries,
// teal when the search can start, red while a run is in progress.
function isRunReady() {
  const queries = document.getElementById('f-queries');
  const hasQueries = !!(queries && (queries.value || '').split('\n').map(s => s.trim()).filter(Boolean).length);
  return hasQueries && selectedCities.length > 0;
}

// Repaints #btn-run according to its current state:
//   ready      → teal (run-ready class)
//   not ready  → grey via :disabled + not-allowed cursor
//   run active → red (run-active class; the button becomes the pause control)
function updateRunBtnState() {
  const btn = document.getElementById('btn-run');
  if (!btn) return;
  // Mid-run the red «⏸ Пауза» state is owned by
  // setRunBtnActive()/resetBtn() — never flip it back to grey/teal.
  if (btn.classList.contains('run-active')) return;
  if (btn.classList.contains('run-paused')) return;
  btn.disabled = !isRunReady();
  btn.classList.toggle('run-ready', isRunReady());
}

// ── Sticky-футер «Фильтрация результата» ─────────────────────
// Две прилипающие панели не должны накладываться друг на друга: кнопка
// «🔄 Применить фильтры заново» паркуется прямо НАД доком сайдбора
// («🚀 Найти компании»). Высоту дока замеряем, а не хардкодим — она зависит
// от шрифта, зума и брейкпоинта. На телефоне док статичный (медиа-запрос
// #run-dock), нижнюю кромку занимать нечему — там 0.
function syncDockHeight() {
  const dock = document.getElementById('run-dock');
  const root = document.documentElement;
  if (!dock || !root || !root.style || !root.style.setProperty) return;
  const mq = window.matchMedia && window.matchMedia('(min-width: 861px)');
  const pinned = mq ? mq.matches : true;
  root.style.setProperty('--dock-h', (pinned ? (dock.offsetHeight || 0) : 0) + 'px');
}

// While the run is live the dock button reads red «⏸ Пауза» and clicking it
// pauses the search (graceful unwind + checkpoint); the small ⏹ button next
// to it stops the run entirely after a confirmation.
function setRunBtnActive() {
  const btn = document.getElementById('btn-run');
  if (!btn) return;
  btn.hidden = false;
  btn.disabled = false;
  btn.onclick = pauseRun;
  btn.classList.remove('run-ready');
  btn.classList.remove('run-paused');
  btn.classList.add('run-active');
  const icon = document.getElementById('btn-icon');
  if (icon) icon.innerHTML = UI_ICONS.pause;
  const txt = document.getElementById('btn-txt');
  if (txt) txt.textContent = 'Пауза';
  const stopBtn = document.getElementById('btn-stop');
  if (stopBtn) { stopBtn.hidden = false; stopBtn.disabled = false; stopBtn.onclick = stopRunWithConfirm; }
}

// ⏸ Pause: graceful unwind that remembers the run. The server answers
// immediately; the real paused state arrives with the done SSE message.
function pauseRun() {
  const btn = document.getElementById('btn-run');
  const txt = document.getElementById('btn-txt');
  if (btn) {
    btn.disabled = true;
    // Город добивается до конца (graceful): кнопка честно говорит об этом.
    if (txt) txt.innerHTML = UI_ICONS.busy + 'Завершаем город…';
  }
  const backToIdle = () => {
    // Нечего было паузить (запуск уже завершился) — иначе кнопка висела бы
    // в «Ставим на паузу…» до конца сессии.
    resetBtn();
    setStatus('done', 'Готово');
    setRunIndicator(false);
    showToast('Поиск уже завершился — продолжать нечего', 'info');
  };
  try {
    fetch('/stop?pause=1', {method: 'POST'})
      .then(r => r.json().catch(() => ({})))
      .then(d => {
        // Сервер отвечает, какой запуск действительно остановлен: пустой
        // список = паузить было нечего.
        if (Array.isArray(d.targets) && !d.targets.length) { backToIdle(); return; }
        showToast('⏸ Пауза. Завершаем текущий город…', 'info');
      })
      .catch(() => {});
  } catch (e) { /* network errors surface via SSE onerror */ }
}

// ⏹ Stop: the destructive option — ask before unwinding the run without
// a checkpoint resume point.
async function stopRunWithConfirm() {
  const ok = await uiConfirm(
    'Поиск будет остановлен полностью. Прогресс точки будет потерян для продолжения, но уже собранные данные сохранятся.',
    'Остановить поиск?',
    'Остановить'
  );
  if (!ok) return;
  stopRun();
}

// ⏹ Stop while PAUSED. The paused run has no live process, so there is
// nothing to unwind — what the user abandons is the saved resume point.
// Without this the ⏹ button used to disappear on pause and «Продолжить»
// was the only way out of a paused search.
async function stopPausedRun() {
  const ok = await uiConfirm(
    'Поиск закончится здесь, уже собранные данные сохранятся. Продолжить с места остановки будет нельзя.',
    'Отменить продолжение поиска?',
    'Остановить'
  );
  if (!ok) return;
  try { fetch('/stop', {method: 'POST'}).catch(() => {}); } catch (e) {}
  resetBtn();
  setStatus('done', 'Готово');
  appendLog('ok', '  ⏹ Поиск остановлен — точка продолжения сброшена.');
  showToast('⏹ Поиск остановлен — точка продолжения сброшена', 'info');
}

// ⏸ Paused state (after the done message with paused=true): the dock
// shows ONE orange button that resumes the run; stop stays available.
function enterPausedState(resume) {
  _pausedRun = resume || null;
  const btn = document.getElementById('btn-run');
  // Where the search stopped + quota spent so far (2GIS) → tooltip + toast.
  const pos = (resume && resume.position) || {};
  const quota = (resume && resume.quota) || null;
  let posTxt = '';
  if (pos.city) {
    posTxt = 'Остановились: ' + pos.city;
    if (pos.cities_total) posTxt += ' (город ' + (pos.city_idx || '?') + ' из ' + pos.cities_total + ')';
    if (pos.query) posTxt += ' • запрос «' + pos.query + '»';
    if (pos.points_total) posTxt += ' • точка ' + (pos.point || '?') + '/' + pos.points_total;
    if (pos.records) posTxt += ' • найдено ' + pos.records;
  }
  let quotaTxt = '';
  if (quota && quota.cap) {
    const left = Math.max(0, quota.cap - (quota.used || 0));
    quotaTxt = ' • осталось запросов к 2GIS: ' + left;
  }
  const title = posTxt
    ? 'Продолжить поиск с места паузы. ' + posTxt + quotaTxt
    : 'Продолжить поиск с сохранённого места';
  if (btn) {
    btn.hidden = false;
    btn.disabled = false;
    btn.onclick = resumeRun;
    btn.classList.remove('run-active');
    btn.classList.add('run-paused');
    btn.title = title;
  }
  // ⏹ stays visible while the search is paused (and means «отменить
  // продолжение»): hiding it left the user with no way to stop.
  const stopBtn = document.getElementById('btn-stop');
  if (stopBtn) { stopBtn.hidden = false; stopBtn.disabled = false; stopBtn.onclick = stopPausedRun; }
  const icon = document.getElementById('btn-icon');
  if (icon) icon.innerHTML = UI_ICONS.play;
  const txt = document.getElementById('btn-txt');
  if (txt) txt.textContent = 'Продолжить поиск';
  setRunIndicator(false);
  setStatus('paused', 'Пауза');
  if (posTxt) {
    appendLog('info', '  📍 ' + posTxt + quotaTxt);
  }
  showToast(posTxt ? '⏸ ' + posTxt + quotaTxt : 'Поиск на паузе — прогресс сохранён', 'info');
}

// ▶ Resume: relaunch the paused run with the SAME params + resume=true.
// The checkpoint/global seen-cache make the parser skip finished points
// and cities, so nothing is parsed twice.
function resumeRun() {
  if (!_pausedRun) { showToast('Нет данных для продолжения — запустите поиск заново', 'error'); return; }
  const params = Object.assign({}, _pausedRun.params || {});
  // Belt-and-braces: the resume payload carries queries + cities twice (as
  // convenience fields and inside params). Fall back to them if a payload
  // ever arrives without the full params — the button must never be a no-op.
  if (!Array.isArray(params.queries) || !params.queries.length) {
    params.queries = (_pausedRun.queries || []).slice();
  }
  if (!Array.isArray(params.cities) || !params.cities.length) {
    // «Продолжить» гоняет только оставшиеся города (текущий недобранный —
    // с начала, без дублей за счёт seen-cache); all_cities — запасной путь.
    params.cities = (Array.isArray(_pausedRun.remaining_cities) && _pausedRun.remaining_cities.length)
      ? _pausedRun.remaining_cities.slice()
      : (_pausedRun.all_cities || []).slice();
  }
  if (!params.queries.length || !params.cities.length) {
    showToast('Не удалось восстановить параметры поиска — запустите его заново', 'error');
    return;
  }
  params.resume = true;
  _pausedRun = null;
  const btn = document.getElementById('btn-run');
  if (btn) {
    btn.classList.remove('run-paused');
    btn.title = 'Продолжить поиск с сохранённого места';
  }
  _startRunWithParams(params);
}

let _pausedRun = null;

// 🗑 «Очистить города» is visible only while there is something to clear:
// selected cities or city search text. Queries are NOT cleared by this
// button (see clearAllInputs), so queries alone don't make it appear.
function updateClearAllBtn() {
  const btn = document.getElementById('clear-all-btn');
  if (!btn) return;
  btn.hidden = !(selectedCities.length || (citySearchText || '').trim());
}

// Instant clear without alert(): chips fade out via .chip-out, then everything
// in «Основные параметры» resets (cities + city input + queries).
// «Очистить города»: removes selected cities + city input text. The queries
// textarea is deliberately NOT cleared — the button is labeled «города» and
// erasing the user's search queries here would destroy their work.
function clearAllInputs() {
  selectedCities = [];
  citySearchText = '';
  const inp = document.getElementById('f-city-input');
  if (inp) inp.value = '';
  const clr = document.querySelector('.city-clear');
  if (clr) clr.classList.remove('visible');
  const dd = document.getElementById('city-dropdown');
  if (dd) { dd.classList.remove('open'); dd.innerHTML = ''; }
  const tagsRow = document.getElementById('city-tags-row');
  if (tagsRow) {
    tagsRow.querySelectorAll('.city-tag').forEach(t => t.classList.add('chip-out'));
    setTimeout(() => { renderCityTags(); }, 190);
    return; // renderCityTags refreshes counters + summary + run button
  }
  updateCityCount();
  updateClearAllBtn();
  updateBasicSummary();
  updateRunBtnState();
}

// Queries summary line for the collapsed «Основные параметры» accordion:
// «Кого ищем: кафе, ресторан, парикмахерская • Городов: 3 • Источник: 2GIS».
// Long query lists are trimmed to the first 3 words + «…»; empty → placeholder.
function updateBasicSummary() {
  const el = document.getElementById('acc-basic-summary');
  if (!el) return;
  const queries = (document.getElementById('f-queries')?.value || '')
    .split('\n').map(s => s.trim()).filter(Boolean);
  const summaryHidden = !queries.length && !selectedCities.length;
  el.style.display = summaryHidden ? 'none' : '';
  if (summaryHidden) return;
  let qPart = 'Кого ищем: не задано';
  if (queries.length) {
    const words = queries.join(' ').split(/\s+/).filter(Boolean);
    const text = words.length > 3 ? words.slice(0, 3).join(', ') + ', …' : words.join(', ');
    qPart = `Кого ищем: ${text}`;
  }
  const cPart = selectedCities.length ? `Городов: ${selectedCities.length}` : 'Городов: не выбрано';
  const sPart = `Источник: ${dataSource === '2gis' ? '2GIS' : 'Яндекс'}`;
  el.textContent = `${qPart} • ${cPart} • ${sPart}`;
}

function getFilteredCities() {
  const selSet = new Set(selectedCities);
  const q = citySearchText.trim().toLowerCase();
  return CITIES_DATA
    .filter(c => !selSet.has(c.name))
    .filter(c => !q || c.name.toLowerCase().includes(q))
    .sort((a, b) => b.pop - a.pop);
}

function updateCityDropdown() {
  const dd = document.getElementById('city-dropdown');
  if (!dd) return;
  const cities = getFilteredCities();
  if (!cities.length) { dd.classList.remove('open'); dd.innerHTML = ''; return; }
  dd.innerHTML = cities.map(c => {
    const pct = Math.round(c.pop / MAX_POP * 100);
    const hue = Math.round(pct * 1.2); // 0=red, 120=green
    // Приглушённые оттенки (терракота/охра/шалфей): насыщенность −40% и
    // светлота +13% — цвет читается как индикатор, а не кричит. Контраст
    // к фону сохраняется в обеих темах.
    const barColor = `hsl(${hue}, 38%, 55%)`;
    const safeName = c.name.replace(/'/g, "\\'");
    return `<div class="city-option" onmousedown="addCity('${safeName}')">`
      + `<div class="city-option-top">`
      +   `<span class="city-option-name">${c.name}</span>`
      +   `<span class="city-option-pop">${formatPopulation(c.pop)}</span>`
      + `</div>`
      + cityHistoryLine(c.name)
      + `<div class="city-option-bar"><div class="city-option-bar-fill" style="width:${pct}%;background:${barColor}"></div></div>`
      + `</div>`;
  }).join('');
  dd.classList.add('open');
  positionCityDropdown();
}

function addCity(name) {
  if (!name || selectedCities.includes(name)) return;
  selectedCities.push(name);
  citySearchText = '';
  renderCityTags();
  // Clear input
  const inp = document.getElementById('f-city-input');
  if (inp) inp.value = '';
  const clr = document.querySelector('.city-clear');
  if (clr) clr.classList.remove('visible');
}

function removeCity(idx) {
  selectedCities.splice(idx, 1);
  renderCityTags();
}

// ═══════════════════════════════════════════
//  🚫 Чёрный список слов («Исключить по словам»)
// ═══════════════════════════════════════════
// UX повторяет чипы городов: слово вводится в поле, Enter или «+» добавляет
// чип, «✕» убирает, Backspace в пустом поле снимает последний. Список живёт
// в своём ключе localStorage (с версией и датой) и автосохраняется с задержкой,
// но есть и явная кнопка «💾 Сохранить список» — она сохраняет сразу.
// Лимиты те же, что в yandex_maps_parser/processing.py.
const BLACKLIST_KEY = 'blacklist_words';
const BLACKLIST_VERSION = 1;
const BLACKLIST_MAX_WORDS = 100;
const BLACKLIST_MAX_LEN = 50;
const BLACKLIST_SAVE_MS = 1000;      // автосохранение в localStorage (debounce)
const BLACKLIST_PREVIEW_MS = 600;    // пересчёт счётчика исключений (debounce)
// Пользовательские списки («💾 Сохранить список»): отдельный ключ, чтобы
// их нельзя было случайно снести очисткой текущего списка слов.
const BLACKLIST_LISTS_KEY = 'blacklist_lists';
const BLACKLIST_LISTS_VERSION = 1;
const BLACKLIST_MAX_LISTS = 20;
const BLACKLIST_LIST_NAME_MAX = 40;

let blacklistWords = [];
let _blSaveTimer = null;
let _blPreviewTimer = null;
let _blErrTimer = null;
let _blPreviewSeq = 0;               // ответы приходят не по порядку — берём последний
let _blAnimateWords = new Set();     // слова, которые надо анимировать при ближайшем рендере

// Шаблоны — готовые наборы слов под частые задачи. Добавляются К текущему
// списку (не заменяют его), поэтому два шаблона складываются в один.
const BLACKLIST_TEMPLATES = {
  franchise:   {label: 'Франшизы и сети',        words: ['франшиза', 'франчайзи', 'филиал', 'сеть']},
  gov:         {label: 'Госсектор',              words: ['администрация', 'министерство', 'мфц', 'гбу', 'муп']},
  marketplace: {label: 'Маркетплейсы и ПВЗ',     words: ['пункт выдачи', 'пвз', 'wildberries', 'ozon']},
  delivery:    {label: 'Доставка и тёмные кухни', words: ['доставка', 'тёмная кухня', 'dark kitchen']},
};

// Сохранённые списки: {version, lists:[{name, words, updated_at}]}.
function getBlacklistLists() {
  try {
    const j = JSON.parse(localStorage.getItem(BLACKLIST_LISTS_KEY));
    if (!j || !Array.isArray(j.lists)) return [];
    return j.lists
      .filter(l => l && typeof l.name === 'string' && l.name.trim() && Array.isArray(l.words))
      .map(l => ({name: String(l.name).trim().slice(0, BLACKLIST_LIST_NAME_MAX),
                  words: normalizeBlacklist(l.words), updated_at: l.updated_at || null}));
  } catch (e) { return []; }
}

function saveBlacklistLists(lists) {
  try {
    localStorage.setItem(BLACKLIST_LISTS_KEY, JSON.stringify({
      version: BLACKLIST_LISTS_VERSION,
      lists: (Array.isArray(lists) ? lists : []).slice(0, BLACKLIST_MAX_LISTS),
    }));
  } catch (e) { /* приватный режим или квота — список просто не сохранится */ }
}

// Дропдаун «📂 Загрузить шаблон» — кастомный вместо <select>: у нативного
// не бывает кнопок внутри опций, а сохранённым спискам нужны ✎/🗑 прямо
// в строке. Панель строится из реестра встроенных шаблонов и сохранённых
// списков — подписи не дублируются в разметке; пересобирается при каждом
// изменении списков, поэтому кэш заполнения не нужен.
function fillBlacklistTemplateSelect() {
  const btn = document.getElementById('blacklist-template');
  const panel = document.getElementById('blacklist-dd-panel');
  if (!btn || !panel) return;
  const builtins = Object.entries(BLACKLIST_TEMPLATES);
  const saved = getBlacklistLists();
  panel.innerHTML = ''
    + (builtins.length
      ? '<div class="bl-dd-group">Встроенные шаблоны</div>'
        + builtins.map(([key, tpl]) =>
          '<button type="button" class="bl-dd-item" data-value="builtin:' + key + '"'
          + ' title="Добавить слова шаблона к текущему списку">'
          + escapeHtml(tpl.label) + '</button>').join('')
      : '')
    + '<div class="bl-dd-group' + (saved.length ? ' bl-dd-group-gap' : '') + '">Мои списки</div>'
    + (saved.length
      ? saved.map(l =>
          '<div class="bl-dd-row" data-name="' + escapeHtml(l.name) + '">'
          + '<button type="button" class="bl-dd-item bl-dd-apply" data-value="saved:' + escapeHtml(l.name) + '"'
          + ' title="Добавить слова списка к текущему">' + escapeHtml(l.name)
          + ' <span class="bl-dd-n">(' + l.words.length + ')</span></button>'
          + '<span class="bl-dd-actions">'
          + '<button type="button" class="bl-tpl-act" data-act="edit" title="Перезаписать этот список текущими словами"'
          + ' aria-label="Перезаписать список «' + escapeHtml(l.name) + '»">'
          + UI_ICONS.pencil + '</button>'
          + '<button type="button" class="bl-tpl-act bl-tpl-del" data-act="del" title="Удалить сохранённый список"'
          + ' aria-label="Удалить список «' + escapeHtml(l.name) + '»">'
          + UI_ICONS.x + '</button>'
          + '</span></div>').join('')
      : '<div class="bl-dd-empty">Пока нет сохранённых списков — «Сохранить список» создаст первый</div>')
    + '<div class="bl-dd-note">Шаблон добавляется к списку, а не заменяет его</div>';
  renderBlacklistListManage(saved);
}

function toggleBlacklistDropdown(event) {
  if (event) event.stopPropagation();
  const btn = document.getElementById('blacklist-template');
  const panel = document.getElementById('blacklist-dd-panel');
  if (!btn || !panel) return;
  const open = panel.hidden;
  if (open) fillBlacklistTemplateSelect();   // свежие списки на каждое открытие
  panel.hidden = !open;
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function closeBlacklistDropdown() {
  const btn = document.getElementById('blacklist-template');
  const panel = document.getElementById('blacklist-dd-panel');
  if (panel) panel.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

// Управление сохранёнными списками: применить — кликом по строке,
// перезаписать/удалить — кнопками рядом. Встроенные шаблоны неизменяемы.
function renderBlacklistListManage(saved) {
  const panel = document.getElementById('blacklist-dd-panel');
  if (!panel) return;
  const lists = Array.isArray(saved) ? saved : getBlacklistLists();
  // Применение шаблона (встроенного и своего).
  panel.querySelectorAll('.bl-dd-item[data-value]').forEach(item =>
    item.addEventListener('click', () => { closeBlacklistDropdown(); applyBlacklistTemplate(item.dataset.value); }));
  // Кнопки ✎/🗑 у своих списков.
  panel.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', async e => {
    e.stopPropagation();
    const row = btn.closest('.bl-dd-row');
    const name = row ? row.dataset.name : null;
    if (!name) return;
    const all = getBlacklistLists();
    const idx = all.findIndex(l => l.name === name);
    if (idx < 0) return;
    if (btn.dataset.act === 'del') {
      if (!(await uiConfirm('Удалить сохранённый список «' + name + '»?', 'Удалить список', 'Удалить'))) return;
      all.splice(idx, 1);
      saveBlacklistLists(all);
      fillBlacklistTemplateSelect();
      showToast('Список «' + name + '» удалён', 'success');
    } else {
      if (!blacklistWords.length) { showToast('Текущий список пуст — перезаписывать нечем', 'info'); return; }
      if (!(await uiConfirm('Перезаписать список «' + name + '» текущими словами ('
          + blacklistWords.length + ')?', 'Редактировать список', 'Перезаписать'))) return;
      all[idx] = {name, words: [...blacklistWords], updated_at: new Date().toISOString()};
      saveBlacklistLists(all);
      fillBlacklistTemplateSelect();
      showToast('Список «' + name + '» обновлён', 'success');
    }
  }));
}

// «💾 Сохранить список» → модалка с именем (замена браузерного prompt()).
// Дубликат имени не блокирует: предлагается перезаписать существующий список.
function openBlacklistSaveModal() {
  if (!blacklistWords.length) { showToast('Список пуст — сначала добавьте слова', 'info'); return; }
  const overlay = document.createElement('div');
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal preset-modal">
      <h3>Сохранить список</h3>
      <p>В шаблон войдут текущие слова: ${blacklistWords.length} ${_pluralRu(blacklistWords.length, 'слово', 'слова', 'слов')}.</p>
      <input type="text" id="blacklist-list-name" maxlength="${BLACKLIST_LIST_NAME_MAX}" placeholder="Например: Франшизы и сети" autocomplete="off">
      <div class="preset-modal-meta">Появится в «Загрузить шаблон» → «Мои списки»</div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel">Отмена</button>
        <button type="button" class="m-ok">${UI_ICONS.save}Сохранить</button>
      </div>
    </div>`;
  const input = overlay.querySelector('#blacklist-list-name');
  const done = val => { overlay.remove(); document.removeEventListener('keydown', onKey, true); if (val) finishSaveList(val); };
  const onKey = e => {
    if (e.key === 'Escape') { e.stopPropagation(); done(false); }
    else if (e.key === 'Enter' && input.value.trim()) { e.stopPropagation(); done(input.value.trim()); }
  };
  const finishSaveList = name => {
    const lists = getBlacklistLists();
    const idx = lists.findIndex(l => l.name === name);
    if (idx >= 0) {
      uiConfirm('Список «' + name + '» уже есть — перезаписать его текущими словами?',
        'Перезаписать список', 'Перезаписать').then(ok => {
        if (!ok) { setTimeout(() => { openBlacklistSaveModal(); const again = document.getElementById('blacklist-list-name'); if (again) again.value = name; }, 0); return; }
        lists[idx] = {name, words: [...blacklistWords], updated_at: new Date().toISOString()};
        saveBlacklistLists(lists);
        fillBlacklistTemplateSelect();
        showToast('Список «' + name + '» обновлён — он в «Загрузить шаблон» → «Мои списки»', 'success');
      });
      return;
    }
    lists.unshift({name, words: [...blacklistWords], updated_at: new Date().toISOString()});
    saveBlacklistLists(lists);
    fillBlacklistTemplateSelect();
    showToast('Список «' + name + '» сохранён — он в «Загрузить шаблон» → «Мои списки»', 'success');
  };
  overlay.querySelector('.m-cancel').onclick = () => done(false);
  overlay.querySelector('.m-ok').onclick = () => {
    const name = input.value.trim();
    if (!name) { input.classList.add('field-invalid'); input.focus(); return; }
    done(name);
  };
  overlay.addEventListener('click', e => { if (e.target === overlay) done(false); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(overlay);
  input.focus();
}

// Сплит по [,;\n], trim, lowercase, пустые и дубликаты выброшены, слова
// длиннее 50 символов отброшены (это не слово, а вставленный текст).
function normalizeBlacklist(value) {
  const out = [];
  (Array.isArray(value) ? value : []).forEach(item => {
    String(item == null ? '' : item).split(/[,;\n]+/).forEach(part => {
      const w = part.trim().toLowerCase();
      if (!w || w.length > BLACKLIST_MAX_LEN) return;
      if (out.includes(w) || out.length >= BLACKLIST_MAX_WORDS) return;
      out.push(w);
    });
  });
  return out;
}

// Что именно произойдёт с введённой строкой — до того, как список изменится:
// столько-то добавим, столько-то уже есть, столько-то не слова.
function parseBlacklistInput(text, existing) {
  const have = Array.isArray(existing) ? existing : blacklistWords;
  const parts = String(text == null ? '' : text).split(/[,;\n]+/)
    .map(s => s.trim().toLowerCase()).filter(Boolean);
  const added = [];
  let tooLong = 0, duplicates = 0, limitReached = false;
  for (const w of parts) {
    if (w.length > BLACKLIST_MAX_LEN) { tooLong++; continue; }
    if (have.includes(w) || added.includes(w)) { duplicates++; continue; }
    if (have.length + added.length >= BLACKLIST_MAX_WORDS) { limitReached = true; continue; }
    added.push(w);
  }
  return {added, tooLong, duplicates, limitReached, empty: !parts.length};
}

function renderBlacklistChips(opts) {
  const box = document.getElementById('blacklist-chips');
  // Анимируем только слова, добавленные этой правкой: иначе при каждом
  // перерендере (innerHTML пересобирается целиком) прыгали бы все чипы.
  const animate = _blAnimateWords;
  if (box) {
    box.innerHTML = blacklistWords.map((w, i) =>
      '<span class="bl-chip' + (animate.has(w) ? ' bl-new' : '') + '"><span>' + escapeHtml(w) + '</span>'
      + '<span class="bl-chip-x" role="button" tabindex="0" aria-label="Убрать слово «' + escapeHtml(w) + '»"'
      + ' onclick="removeBlacklistWord(' + i + ')"'
      + ' onkeydown="onBlacklistChipKey(event, ' + i + ')">' + UI_ICONS.x + '</span></span>'
    ).join('');
  }
  _blAnimateWords = new Set();
  updateBlacklistCount();
  // Ленивый счётчик: на загрузке страницы (opts.preview === false) в сеть не
  // ходим — исключения считаются при открытии раздела и на каждое изменение.
  if (!opts || opts.preview !== false) scheduleBlacklistPreview();
}

// Сразу видно, что список не пуст; точные цифры (сколько компаний исключится)
// приезжают с сервера — считать их на клиенте значило бы держать вторую
// копию логики поиска.
function updateBlacklistCount(text) {
  const el = document.getElementById('blacklist-count');
  if (!el) return;
  if (text != null) { el.textContent = text; return; }
  el.textContent = blacklistWords.length
    ? `Слов в списке: ${blacklistWords.length}`
    : 'Список пуст — исключений нет';
}

function showBlacklistError(msg) {
  const el = document.getElementById('blacklist-err');
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  if (_blErrTimer) clearTimeout(_blErrTimer);
  _blErrTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

function clearBlacklistError() {
  const el = document.getElementById('blacklist-err');
  if (el) { el.hidden = true; el.textContent = ''; }
  if (_blErrTimer) { clearTimeout(_blErrTimer); _blErrTimer = null; }
}

// Добавляет слова из строки (поле ввода или шаблон). Возвращает, сколько слов
// реально добавилось, — на это опираются тосты и тесты.
function addBlacklistWords(text, opts) {
  const silent = !!(opts && opts.silent);
  const res = parseBlacklistInput(text);
  if (res.empty) {
    if (!silent) showBlacklistError('Введите слово');
    return 0;
  }
  if (res.tooLong) {
    if (!silent) showBlacklistError(`Слово длиннее ${BLACKLIST_MAX_LEN} символов — не добавлено`);
  } else if (res.limitReached) {
    if (!silent) showBlacklistError(`В списке уже ${BLACKLIST_MAX_WORDS} слов — больше нельзя`);
  } else if (!res.added.length && res.duplicates) {
    if (!silent) showBlacklistError('Такое слово уже в списке');
  } else {
    clearBlacklistError();
  }
  if (!res.added.length) return 0;
  blacklistWords.push(...res.added);
  _blAnimateWords = new Set(res.added);
  renderBlacklistChips();
  scheduleBlacklistSave();
  return res.added.length;
}

// «+» и Enter: слово из поля. Поле очищается, но фокус остаётся — так можно
// вводить слова одно за другим, не возвращаясь мышью к полю.
function addBlacklistFromField() {
  const inp = document.getElementById('f-blacklist-input');
  if (!inp) return 0;
  const n = addBlacklistWords(inp.value);
  if (n) inp.value = '';
  if (inp.focus) inp.focus();
  return n;
}

function onBlacklistKey(e) {
  if (e.key === 'Enter') { e.preventDefault(); addBlacklistFromField(); return; }
  // Backspace в пустом поле убирает последний чип — как в поле городов.
  if (e.key === 'Backspace' && !e.target.value && blacklistWords.length) {
    removeBlacklistWord(blacklistWords.length - 1);
  }
}

function removeBlacklistWord(i) {
  if (typeof i !== 'number' || i < 0 || i >= blacklistWords.length) return;
  blacklistWords.splice(i, 1);
  renderBlacklistChips();
  scheduleBlacklistSave();
}

// Крестик чипа — тоже кнопка: с клавиатуры он должен срабатывать по Enter и
// пробелу, а не только мышью.
function onBlacklistChipKey(e, i) {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); removeBlacklistWord(i); }
}

function clearBlacklist() {
  if (!blacklistWords.length) { showToast('Список исключений уже пуст', 'info'); return; }
  blacklistWords = [];
  const box = document.getElementById('blacklist-chips');
  // Гасим чипы так же, как «Очистить города», и лишь потом перерисовываем.
  if (box && box.querySelectorAll) {
    box.querySelectorAll('.bl-chip').forEach(c => c.classList.add('bl-out'));
    setTimeout(() => { renderBlacklistChips(); }, 190);
  } else {
    renderBlacklistChips();
  }
  updateBlacklistCount('Список пуст — исключений нет');
  scheduleBlacklistSave();
  scheduleBlacklistPreview();
}

// Шаблон (builtin:<key> или saved:<имя>) добавляется К списку: два шаблона
// складываются, ничего не теряется. После применения селект возвращается
// к плейсхолдеру, чтобы тот же шаблон можно было выбрать повторно.
function applyBlacklistTemplate(value) {
  closeBlacklistDropdown();            // панель закрывается после выбора
  const v = String(value || '');
  let label = '', words = null;
  if (v.startsWith('builtin:')) {
    const tpl = BLACKLIST_TEMPLATES[v.slice(8)];
    if (tpl) { label = tpl.label; words = tpl.words; }
  } else if (v.startsWith('saved:')) {
    const name = v.slice(6);
    const list = getBlacklistLists().find(l => l.name === name);
    if (list) { label = name; words = list.words; }
  }
  if (!words) return 0;
  const n = addBlacklistWords(words.join('\n'), {silent: true});
  showToast(n ? `Шаблон «${label}»: добавлено слов — ${n}`
              : 'Слова шаблона уже в списке', n ? 'success' : 'info');
  return n;
}

// Сохранение: ключ свой (`blacklist_words`), с версией и датой — так формат
// можно будет поменять, не гадая, что лежит в браузере.
function saveBlacklistState(showMsg) {
  try {
    localStorage.setItem(BLACKLIST_KEY, JSON.stringify({
      words: [...blacklistWords],
      version: BLACKLIST_VERSION,
      updated_at: new Date().toISOString(),
    }));
  } catch (e) { /* приватный режим или квота: список просто не переживёт перезагрузку */ }
  if (showMsg) {
    showToast(blacklistWords.length
      ? `Список сохранён: ${blacklistWords.length} ${_pluralRu(blacklistWords.length, 'слово', 'слова', 'слов')}`
      : 'Список исключений сохранён (пустой)', 'success');
  }
}

function scheduleBlacklistSave() {
  if (_blSaveTimer) clearTimeout(_blSaveTimer);
  _blSaveTimer = setTimeout(() => { _blSaveTimer = null; saveBlacklistState(false); }, BLACKLIST_SAVE_MS);
}

function saveBlacklistNow() {
  if (_blSaveTimer) { clearTimeout(_blSaveTimer); _blSaveTimer = null; }
  saveBlacklistState(true);
}

function loadBlacklistWords() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(BLACKLIST_KEY)); } catch (e) { stored = null; }
  // Текущий формат — {words, version, updated_at}; голый массив — старый.
  const raw = Array.isArray(stored) ? stored : (stored && Array.isArray(stored.words) ? stored.words : []);
  blacklistWords = normalizeBlacklist(raw);
  // На загрузке страницы только показываем число слов: счётчик исключений
  // считается при открытии раздела (см. toggleAccordion).
  renderBlacklistChips({preview: false});
  return blacklistWords;
}

// Полная замена списка (пресет, настройки) — нормализует и сохраняет.
function setBlacklistWords(list) {
  const before = new Set(blacklistWords);
  blacklistWords = normalizeBlacklist(list);
  _blAnimateWords = new Set(blacklistWords.filter(w => !before.has(w)));
  renderBlacklistChips();
  scheduleBlacklistSave();
  return blacklistWords;
}

function scheduleBlacklistPreview() {
  if (_blPreviewTimer) clearTimeout(_blPreviewTimer);
  // Любое изменение списка отменяет ответы в пути — в том числе когда список
  // опустел: иначе «🚫 Исключит N…» от старого списка воскресало бы поверх
  // «Список пуст».
  _blPreviewSeq++;
  if (!blacklistWords.length) {
    updateBlacklistCount('Список пуст — исключений нет');
    return;
  }
  updateBlacklistCount(`Слов в списке: ${blacklistWords.length}. Считаю, сколько компаний исключится…`);
  _blPreviewTimer = setTimeout(() => { _blPreviewTimer = null; previewBlacklist(); }, BLACKLIST_PREVIEW_MS);
}

// POST /preview-blacklist: сколько компаний снимает текущий список — по сырым
// данным текущего поиска, той же логикой, что и этап 2.
function previewBlacklist() {
  const words = [...blacklistWords];
  if (!words.length) { updateBlacklistCount('Список пуст — исключений нет'); return Promise.resolve(); }
  const seq = ++_blPreviewSeq;
  return fetch('/preview-blacklist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({words}),
  })
    .then(r => r.json())
    .then(j => {
      if (seq !== _blPreviewSeq) return;   // список уже изменился — ответ устарел
      if (!j || !j.ok) { updateBlacklistCount('Не удалось посчитать исключения'); return; }
      if (!j.total) { updateBlacklistCount('Нет сырых данных текущего поиска — сначала запустите сбор'); return; }
      const many = _pluralRu(j.total, 'компании', 'компаний', 'компаний');
      updateBlacklistCount(j.excluded
        ? `🚫 Исключит ${j.excluded} из ${j.total} ${many} — останется ${j.remaining}`
        : `Ничего не исключается — слова не совпали (проверено ${j.total} ${many})`);
    })
    .catch(() => { if (seq === _blPreviewSeq) updateBlacklistCount('Не удалось посчитать исключения'); });
}

// ═══════════════════════════════════════════
//  🎯 Тип компании: только одиночки / только новые
// ═══════════════════════════════════════════
// Оба фильтра применяет сервер (этап 2), но счётчик «сколько подойдёт» живёт
// здесь и читает сырые данные текущего поиска — той же функцией, что и фильтр.
// Периоды и дефолт совпадают с processing.COMPANY_TYPE_MONTHS.
const COMPANY_TYPE_PREVIEW_MS = 500;   // пересчёт счётчика (debounce)
const COMPANY_TYPE_PERIODS = {1: '1 мес', 3: '3 мес', 6: '6 мес', 12: '1 год', 24: '2 года'};
const COMPANY_TYPE_DEFAULT_MONTHS = 6;

let _ctPreviewTimer = null;
let _ctPreviewSeq = 0;                 // ответы приходят не по порядку — берём последний

function onlySingleChecked() {
  return !!(document.getElementById('f-only-single') || {}).checked;
}

// Период «новых»: null — фильтр выключен (сервер трактует так же).
function newMonthsValue() {
  const cb = document.getElementById('f-only-new');
  if (!cb || !cb.checked) return null;
  const n = parseInt((document.getElementById('f-new-months') || {}).value, 10);
  return Object.prototype.hasOwnProperty.call(COMPANY_TYPE_PERIODS, n)
    ? n : COMPANY_TYPE_DEFAULT_MONTHS;
}

// Период из селекта — даже когда чекбокс выключен (пресет помнит выбор).
function newMonthsPeriod() {
  const n = parseInt((document.getElementById('f-new-months') || {}).value, 10);
  return Object.prototype.hasOwnProperty.call(COMPANY_TYPE_PERIODS, n) ? String(n) : '6';
}

function companyTypeOn() {
  return onlySingleChecked() || !!newMonthsValue();
}

// Строка периода гаснет вместе с чекбоксом: селект без своего фильтра читался
// бы как самостоятельная настройка, которая ничего не делает.
function syncCompanyTypeUi() {
  const cb = document.getElementById('f-only-new');
  const on = !!(cb && cb.checked);
  const row = document.getElementById('company-type-new-row');
  if (row && row.classList) row.classList.toggle('on', on);
  const sel = document.getElementById('f-new-months');
  if (sel) sel.disabled = !on;
  ['f-only-single', 'f-only-new'].forEach(id => {
    const box = document.getElementById(id);
    const lbl = box && box.closest ? box.closest('.chk') : null;
    if (lbl && lbl.classList) lbl.classList.toggle('on', !!box.checked);
  });
  const cnt = document.getElementById('company-type-count');
  if (cnt && cnt.classList) cnt.classList.toggle('on', companyTypeOn());
}

function onCompanyTypeChange() {
  syncCompanyTypeUi();
  scheduleCompanyTypePreview();
}

function updateCompanyTypeCount(html) {
  const el = document.getElementById('company-type-count');
  if (el) el.innerHTML = html;
}

function scheduleCompanyTypePreview() {
  if (_ctPreviewTimer) clearTimeout(_ctPreviewTimer);
  // Любое изменение фильтров отменяет ответы в пути: иначе «подойдёт N» от
  // старой настройки воскресало бы поверх новой.
  _ctPreviewSeq++;
  if (!companyTypeOn()) {
    updateCompanyTypeCount('Отметьте фильтры — посчитаю, сколько компаний подойдёт');
    return;
  }
  updateCompanyTypeCount('Считаю, сколько компаний подойдёт…');
  _ctPreviewTimer = setTimeout(
    () => { _ctPreviewTimer = null; previewCompanyType(); },
    COMPANY_TYPE_PREVIEW_MS,
  );
}

// POST /preview-company-type: сервер считает по сырым данным текущего поиска
// теми же функциями, что и сам фильтр, — цифра не может разойтись с результатом.
function previewCompanyType() {
  if (!companyTypeOn()) return Promise.resolve();
  const single = onlySingleChecked();
  const months = newMonthsValue();
  const seq = ++_ctPreviewSeq;
  return fetch('/preview-company-type', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({only_single_branch: single, only_new_months: months}),
  })
    .then(r => r.json())
    .then(j => {
      if (seq !== _ctPreviewSeq) return;      // настройка уже изменилась — ответ устарел
      if (!j || !j.ok) { updateCompanyTypeCount('Не удалось посчитать компании'); return; }
      if (!j.total) { updateCompanyTypeCount('Нет сырых данных текущего поиска — сначала запустите сбор'); return; }
      updateCompanyTypeCount(companyTypeCountHTML(j));
    })
    .catch(() => { if (seq === _ctPreviewSeq) updateCompanyTypeCount('Не удалось посчитать компании'); });
}

// «Подойдёт 138 из 500: одиночек 213 + новых 147, обоим условиям — 22».
// Фильтры работают по И, поэтому при обоих включённых в отчёте останутся `both`.
// Большая выгрузка показывается приблизительно («~5000»), чтобы не обещать
// точность, которой нет: цифра — ориентир перед обработкой.
function companyTypeCountHTML(j) {
  const single = onlySingleChecked();
  const months = newMonthsValue();
  const pass = (single && months) ? j.both : (single ? j.single : j.new);
  const total = j.total > 5000 ? '~' + Math.floor(j.total / 1000) * 1000 : String(j.total);
  const plural = _pluralRu(j.total, 'компании', 'компаний', 'компаний');
  const parts = [];
  if (single) parts.push(`одиночек <b>${j.single}</b>`);
  if (months) {
    parts.push(`новых за ${COMPANY_TYPE_PERIODS[j.months || months] || ''} — <b>${j.new}</b>`);
  }
  let html = `🎯 Подойдёт <b>${pass}</b> из ${total} ${plural}: ${parts.join(' + ')}`;
  if (single && months && j.both) html += `, обоим условиям — <b>${j.both}</b>`;
  const notes = [];
  const noDate = Math.max(0, j.total - (j.with_date || 0));
  if (months && !j.with_date) {
    notes.push('у этой выгрузки нет дат добавления — фильтр «новые» ничего не отсеивает');
  } else if (months && noDate) {
    notes.push(`у ${noDate} ${_pluralRu(noDate, 'компании', 'компаний', 'компаний')} даты нет — они остаются в отчёте`);
  }
  if (notes.length) html += `<span class="ct-note">${notes.join('. ')}.</span>`;
  return html;
}

// ═══════════════════════════════════════════
//  Tabs
// ═══════════════════════════════════════════
// ═══════════════════════════════════════════
//  Notification toggle
// ═══════════════════════════════════════════
// Кнопка в шапке теперь открывает попап настроек (см. toggleNotifyPopover),
// а эта функция осталась как простой «мастер-выключатель»:
// глушит всё разом — и звук, и окна (настройки типов не трогает).
function toggleNotifications() {
  notifySettings.enabled = !notifySettings.enabled;
  saveNotifySettings();
  if (typeof _renderNotifyPopover === 'function') _renderNotifyPopover();
}

// Прошло времени поиска: во время прогона — живое, после завершения —
// зафиксированное (_runEnd ставится в onRunDone и сбрасывается при новом запуске).
function _runElapsed() {
  const end = _runEnd || Date.now();
  return Math.max(0, (end - (startTime || end)) / 1000);
}

function showTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('t-' + name).classList.add('active');
  document.getElementById('p-' + name).classList.add('active');
  if (name === 'map' && allResults.length && !mapInited) ensureMapReady();
  if (name === 'map' && leafMap) setTimeout(() => leafMap.invalidateSize(), 50);
  // Results tab: refresh city tabs + bulk counters (cheap, data may be stale)
  if (name === 'table') {
    if (allResults.length) renderCityTabs(_lastCities);
    updateBulkStats();
  }
  // Load history when switching to history tab
  if (name === 'history') {
    loadHistory();
    loadSeenStatus();
    loadCityHistoryMeta();
  }
  // Шаблоны сообщений: состояние общее, догружаем и перерисовываем карточки.
  if (name === 'templates') {
    loadTemplates().then(() => renderTemplates());
  }
  // Stats tab: «Динамика по дням» считается сервером по файлам на диске и
  // грузится всегда — даже когда результатов в этой сессии ещё нет.
  if (name === 'stats') {
    loadDailyDynamics();
  }
  // Re-render stats when switching to the stats tab. During an active run
  // only finished cities are shown (stable numbers); after the run ends the
  // full result set is rendered.
  if (name === 'stats' && allResults.length) {
    const recs = isRunActive() ? completedCityRecords() : allResults;
    if (recs.length) renderStats(recs, _runElapsed(), _lastSkippedCities);
  }
}

// ═══════════════════════════════════════════
//  Status + progress
// ═══════════════════════════════════════════
// Подпись состояния приходит без эмодзи: значок рисует сама пилюля
// (#status-badge .ico в style.css) по классу состояния. Третий аргумент —
// для случаев, когда класс и глиф не совпадают («остановлено по таймауту»
// остаётся классом stopped, но иконка там та же).
function setStatus(cls, text, icon) {
  const b = document.getElementById('status-badge');
  if (!b) return;
  b.className = cls;
  b.innerHTML = (icon || STATUS_ICONS[cls] || UI_ICONS.info) + escapeHtml(text);
}
function setProgress(pct, label) {
  const pw = document.getElementById('prog-wrap');
  const pb = document.getElementById('prog-bar');
  const pl = document.getElementById('prog-label');
  pw.style.display = pct >= 0 ? '' : 'none';
  pl.style.display = pct >= 0 ? '' : 'none';
  if (pct >= 0) { pb.style.width = pct + '%'; pl.textContent = label || ''; }
}
function hideProgress() {
  setProgress(-1);
  const ls = document.getElementById('live-stats');
  if (ls) ls.style.display = 'none';
}

// ── Aggregate run progress above the log ────────────────────────
// The bar shows the share of the WHOLE run (finished cities + the running
// one's own %), the label counts CITIES — the two metrics never share a slot.
function updateTermProgress() {
  const wrap = document.getElementById('term-progress');
  if (!wrap) return;
  const total = _totalCities || 0;
  if (total < 2) { wrap.hidden = true; return; }   // single city → header panel is hidden too
  const entries = Object.entries(_cityProgressData);
  const done = entries.filter(([, d]) => d.status === 'done' || d.status === 'skipped').length;
  const running = entries.reduce((s, [, d]) => s + (d.status === 'running' ? (d.pct || 0) / 100 : 0), 0);
  const frac = Math.min(1, (done + running) / total);
  wrap.hidden = false;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('tp-done', done);
  set('tp-total', total);
  // Which city is being worked on right now — «3 из 12» alone never said it.
  const runningEntry = entries.find(([, d]) => d.status === 'running');
  set('tp-city', (runningEntry && runningEntry[0]) || _currentCityName || '—');
  const fill = document.getElementById('tp-fill');
  if (fill) fill.style.width = (frac * 100).toFixed(1) + '%';
  const eta = document.getElementById('tp-eta');
  if (eta) eta.textContent = (typeof isRunActive === 'function' && isRunActive()) ? _etaText(frac) : '';
  // The per-city bars are NOT repeated here: the top strip (#city-progress)
  // already shows every city with its own bar, and painting them twice made
  // a 50-city run impossible to read.
}

function _etaText(frac) {
  const elapsed = (Date.now() - (startTime || Date.now())) / 1000;
  if (!frac || frac < 0.03 || elapsed < 5) return '';
  const left = Math.round(elapsed * (1 - frac) / frac);
  if (left < 60) return `Осталось ≈ ${Math.max(1, left)} с`;
  return `Осталось ≈ ${Math.ceil(left / 60)} мин`;
}

// Pulsing dot in the «Ход поиска» tab while a run is active.
function setRunIndicator(on) {
  const dot = document.getElementById('tab-log-dot');
  if (dot) dot.hidden = !on;
}

// ═══════════════════════════════════════════
//  Log output
// ═══════════════════════════════════════════
const logEl = document.getElementById('log-output');
// Long runs emit thousands of lines; without a cap the DOM grows unbounded
// and scrolling/layout gets janky. Keep the newest MAX_LOG_LINES.
const MAX_LOG_LINES = 1200;
let _showTechDetails = false;   // «Технические детали» toggle state
let _lastLogMsg = '';           // last emitted text — consecutive-duplicate guard

// Elapsed stamp [MM:SS] counted from the run start — the same shape as the
// prefix in logs/*.log, so UI and file can be read side by side.
// Absolute wall-clock stamp [HH:MM:SS] — restart/resume-proof and directly
// comparable with the file log. The elapsed delta from the run start stays
// available in the line's title (hover) and in _elapsedStamp().
function logStamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}
// [+m:ss] since the run started — shown as the hover title of each line.
function _elapsedStamp() {
  const t0 = (typeof startTime === 'number' && startTime) ? startTime : 0;
  const sec = t0 ? Math.max(0, Math.floor((Date.now() - t0) / 1000)) : 0;
  return '+' + Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}

// ── Log panel state ─────────────────────────────────────────────────────
// One object instead of a pile of top-level variables: filter, autoscroll,
// city blocks and the counters behind «Ошибок нет». Read through _ls() so
// every helper here stays self-contained (the same code runs in the page and
// in the Node DOM-stub tests).
function _ls() {
  const g = globalThis;
  if (!g._logState) {
    g._logState = {
      filter: 'all',    // all | important | errors | tech
      follow: true,     // autoscroll follows the tail
      below: 0,         // lines that arrived while the user scrolled up
      block: -1,        // index of the city block currently accepting lines
      lastSec: '',      // last rendered HH:MM:SS — repeats are dimmed
      collapsed: {},    // {blockIdx: true} — collapsed city blocks
      meta: [],         // per-line {noise,err,tech} — counters + trimming
      stats: {total: 0, noise: 0, err: 0, tech: 0},
    };
  }
  return g._logState;
}

// ── Autoscroll + «К последней строке» ───────────────────────────────────
// The tail is followed until the user scrolls up; then the floating button
// counts what arrived and jumps back. Nothing is silently lost.
function _scrollLogIfFollowing() {
  if (!logEl) return;
  if (_ls().follow) logEl.scrollTop = logEl.scrollHeight;
}
function _onLogScroll() {
  if (!logEl) return;
  const S = _ls();
  const near = (logEl.scrollHeight - logEl.scrollTop - (logEl.clientHeight || 0)) <= 48;
  S.follow = near;
  if (near) S.below = 0;
  _updateLogJump();
}
function _updateLogJump() {
  const btn = document.getElementById('log-jump');
  if (!btn) return;
  const S = _ls();
  const show = !S.follow && S.below > 0;
  btn.hidden = !show;
  const n = document.getElementById('log-jump-n');
  if (n) n.textContent = S.below > 99 ? '99+' : String(S.below);
}
function logJumpToBottom() {
  const S = _ls();
  S.follow = true;
  S.below = 0;
  if (logEl) logEl.scrollTop = logEl.scrollHeight;
  _updateLogJump();
}
if (logEl && logEl.addEventListener) logEl.addEventListener('scroll', _onLogScroll);

function _trimLog(el) {
  const S = _ls();
  while (el.children.length > MAX_LOG_LINES) {
    const meta = S.meta.shift();
    if (meta) {
      S.stats.total--;
      if (meta.noise) S.stats.noise--;
      if (meta.err)   S.stats.err--;
      if (meta.tech)  S.stats.tech--;
    }
    const first = el.firstChild || el.children[0];
    if (!first) break;
    el.removeChild(first);
  }
}

// ── Levels and hierarchy ────────────────────────────────────────────────
// ✅ успех → зелёный, 📡/🔍 инфо → бирюза, ⚠ → оранжевый, [!]/🚨 → красный.
// Уровень решает класс; текст — только запасной признак для источников,
// которые шлют всё как «info».
function _logLevel(level, text) {
  if (level === 'tech') return 'tech';
  if (level === 'error' || /\[✖\]|\[!\]|🚨/.test(text)) return 'error';
  if (level === 'warn' || /^\s*⚠/.test(text)) return 'warn';
  if (level === 'ok' || /✅|✔/.test(text)) return 'ok';
  if (level === 'info') return 'info';
  return 'sys';
}
// Механика: геокодинг, старт запросов, координаты вида «→ 61.24178, 73.39383»,
// постраничные и поточечные счётчики, HTTP-статусы, трейсы клиентов
// (http/cdp/browser, rate-limit), checkpoint, кэш.
const LOG_NOISE_RE = /геокодирую|запрос начат|начало поиска|───\s*Запрос|api_hits|cache_hit|\[SYS\]|(?:http|cdp|browser)_client|rate_limit|checkpoint|→\s*-?\d+[.,]\d+|поиск:\s*«|\bpage \d+(?:\/\d+)?\b|\bpoint \d+\/\d+|\bHTTP \d{3}\b|раньше найденных/i;
// Белый список: результаты, статусы и ошибки видны в «Важном» ВСЕГДА, что бы
// ещё ни было в строке. Проверяется первым — поэтому «✅ «кафе»: 50 записей»
// не уедет в технические из-за случайного совпадения с шаблоном механики.
// («📡» и «🗺» сами по себе НЕ признак важного: та же иконка стоит на
// служебном «Геокодирую» — поэтому важен текст, а не один эмодзи.)
const LOG_KEEP_RE = /🏙|Город\s+\d+\s*\/\s*\d+|🔍 Поиск в |Источник:|✅|📦\s*Raw|🎯\s*Processed|💾 Карта|⏪|📍|⏸|🚨|⚠|\[!\]|\[✖\]|Остановлен|Готово|Пауза|Ничего не найдено/;
function _logIsNoise(lvl, text) {
  if (LOG_KEEP_RE.test(text)) return false;
  return lvl === 'tech' || lvl === 'sys' || LOG_NOISE_RE.test(text);
}
const LOG_CITY_RE = /🏙|Город\s+\d+\s*\/\s*\d+/i;
// Подстроки конфигурации идут под шапкой города с отступом.
const LOG_SUBLINE_RE = /^\s{4,}\S|^\s*(?:queries|grid|workers|checkpoint|proxies|output|social_mode|source|radius)\s*=[\s\S]*$/i;
function _logIsCity(text) { return LOG_CITY_RE.test(text); }
function _logIndent(text) { return LOG_SUBLINE_RE.test(text) ? 1 : 0; }
// Drop consecutive identical lines: re-entrant warnings and city headers
// must not paint the log with visually duplicated rows. The comparison is
// normalized (case, whitespace, emoji stripped) so «Поиск: 1 город» vs
// "Поиск: 1 город " variants still count as one line.
function _logNorm(msg) {
  return String(msg)
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu, '')
    .replace(/[\s\u00A0]+/g, ' ')
    .trim()
    .toLowerCase();
}
function _isDup(msg) { return _logNorm(msg) === _logNorm(_lastLogMsg); }
function appendLog(level, msg) {
  const clean = msg.replace(/\x1b\[[0-9;]*m/g, '');
  const S = _ls();
  const lvl = _logLevel(level, clean);
  const tech = lvl === 'tech';
  // Developer traces never participate in the duplicate guard (they repeat
  // legitimately), and they are kept even while hidden: the «Технические»
  // filter and the 🔧 toggle can only show what was stored.
  if (!tech && _isDup(clean)) return;
  if (!tech) _lastLogMsg = clean;
  const ph = document.getElementById('log-ph');
  if (ph) ph.remove();
  // Remove the «Как это работает» onboarding card once real log lines arrive.
  const ob = document.getElementById('onboarding-screen');
  if (ob) ob.remove();
  // Drop the skeleton loaders — real data has arrived
  const skel = document.getElementById('log-skeleton');
  if (skel) skel.remove();
  const noise = _logIsNoise(lvl, clean);
  const err = lvl === 'error' || lvl === 'warn';
  const isCity = _logIsCity(clean);
  // Quota warnings (2GIS Places и др.) get louder visual treatment:
  // 🚨 → red banner, ⚠ + «израсходовано» → amber banner.
  let extraCls = '';
  if (/🚨/.test(clean) || (/⚠/.test(clean) && /израсходовано|квота|лимит .*запросов/i.test(clean))) {
    extraCls = /🚨/.test(clean) ? 'quota-critical' : 'quota-warn';
  }
  // A city header opens a new foldable block; every later line joins it.
  let blk = -1;
  if (isCity) S.block += 1;
  blk = S.block;
  let cls = lvl + (noise ? ' noise' : '') + (_logIndent(clean) ? ' ind-1' : '');
  if (isCity) cls += ' city';
  const d = document.createElement('div');
  d.className = 'll ' + cls + (extraCls ? ' ' + extraCls : '');
  d._lvl = lvl;
  d._city = isCity;
  d._blk = blk;
  d._txt = clean;      // raw text — «Сохранить лог» / «Копировать» read this
  d.title = _elapsedStamp();
  // The stamp column shows the time only when the second changes — a long run
  // would otherwise repeat «14:30:15» fifty times. The exact time of every
  // line stays in the hover title, and the column keeps its width so the
  // lines stay aligned.
  const stamp = logStamp();
  const sameSec = stamp === S.lastSec;
  S.lastSec = stamp;
  d._stamp = stamp;
  const caret = isCity ? '<span class="ll-caret">▼</span>' : '';
  d.innerHTML = `<span class="ll-time${sameSec ? ' same' : ''}">[${stamp}]</span>${caret}${escapeHtml(clean)}`;
  if (isCity) {
    d._blk = blk;
    d.onclick = () => toggleLogBlock(blk);
  }
  logEl.appendChild(d);
  // Lines of an already-collapsed city must not pop open that block.
  if (!isCity && blk >= 0 && S.collapsed[blk] && d.style) d.style.display = 'none';
  S.meta.push({noise, err, tech});
  S.stats.total++;
  if (noise) S.stats.noise++;
  if (err)   S.stats.err++;
  if (tech)  S.stats.tech++;
  _trimLog(logEl);
  if (S.follow) {
    _scrollLogIfFollowing();
  } else if (!tech) {
    S.below++;
    _updateLogJump();
  }
  _refreshLogFilter();
  // Quota banners also pop a toast — they're easy to miss in a scrolling log.
  if (extraCls === 'quota-critical') {
    showToast(clean.replace(/^\s*\[!?\*?\]?\s*/, ''), 'error');
  }
}

// ── Log filters ────────────────────────────────────────────────────────
// The filter is one class on the container: hiding is pure CSS, so switching
// «Все / Важные / Ошибки / Технические» never re-renders or loses a line.
const LOG_FILTERS = {
  all:       () => ({ok: true, msg: ''}),
  important: () => ({ok: _ls().stats.total - _ls().stats.noise > 0,
                     msg: 'Важных сообщений нет — включите «Все»'}),
  errors:    () => ({ok: _ls().stats.err > 0, msg: '✅ Ошибок нет'}),
  tech:      () => ({ok: _ls().stats.tech > 0, msg: 'Технических записей нет'}),
};
function setLogFilter(name) {
  const S = _ls();
  S.filter = Object.prototype.hasOwnProperty.call(LOG_FILTERS, name) ? name : 'all';
  const btns = document.querySelectorAll ? document.querySelectorAll('[data-lfilter]') : [];
  for (let i = 0; i < btns.length; i++) {
    const b = btns[i];
    const on = b.getAttribute && b.getAttribute('data-lfilter') === S.filter;
    if (b.classList) b.classList.toggle('active', on);
  }
  _refreshLogFilter();
}
function _refreshLogFilter() {
  const S = _ls();
  if (logEl && logEl.classList) {
    ['all', 'important', 'errors', 'tech'].forEach(f => logEl.classList.remove('f-' + f));
    logEl.classList.add('f-' + S.filter);
  }
  // Badge on «Ошибки»: how many error/warning lines are in the panel right now.
  const badge = document.getElementById('log-err-count');
  if (badge) {
    badge.textContent = String(S.stats.err);
    badge.hidden = S.stats.err === 0;
  }
  const spec = (LOG_FILTERS[S.filter] || LOG_FILTERS.all)();
  const empty = document.getElementById('log-filter-empty');
  if (empty) {
    empty.textContent = spec.msg;
    empty.hidden = spec.ok;
  }
}

// ── Collapsible city blocks ────────────────────────────────────────────
// Cities are the backbone of a long run: everything between two «🏙 Город …»
// headers belongs to that city and can be folded away.
function toggleLogBlock(idx) {
  const S = _ls();
  if (idx === undefined || idx === null || idx < 0) return;
  const collapsed = !S.collapsed[idx];
  S.collapsed[idx] = collapsed;
  if (!logEl || !logEl.children) return;
  for (let i = 0; i < logEl.children.length; i++) {
    const el = logEl.children[i];
    if (!el || el._blk !== idx) continue;
    if (el._city) {
      if (el.classList) el.classList.toggle('collapsed', collapsed);
      el.title = collapsed ? 'Развернуть город' : 'Свернуть город';
    } else if (el.style) {
      el.style.display = collapsed ? 'none' : '';
    }
  }
}

// ── Лог целиком: сохранить / скопировать ──────────────────────────────
function _logPlainText() {
  const out = [];
  if (logEl && logEl.children) {
    for (let i = 0; i < logEl.children.length; i++) {
      const el = logEl.children[i];
      if (!el || !el._lvl) continue;          // placeholder / stats card
      const raw = String(el._txt !== undefined ? el._txt : (el.textContent || ''));
      const txt = raw.replace(/\s+$/, '');
      if (txt) out.push(el._stamp ? `[${el._stamp}] ${txt}` : txt);
    }
  }
  return out.join('\n');
}
function saveLogFile() {
  const text = _logPlainText();
  if (!text) { showToast('Лог пуст — сохранять нечего', 'error'); return; }
  try {
    const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `yp-log-${ts}.log`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('Лог сохранён', 'ok');
  } catch (e) {
    showToast('Не удалось сохранить лог: ' + e.message, 'error');
  }
}
async function copyLogText() {
  const text = _logPlainText();
  if (!text) { showToast('Лог пуст — копировать нечего', 'error'); return; }
  const ok = await copyText(text);
  showToast(ok ? 'Лог скопирован в буфер обмена' : 'Не удалось скопировать лог',
            ok ? 'ok' : 'error');
}

// ── Иконки интерфейса ─────────────────────────────────────────────
// Глифы живут в спрайте (templates/index.html, #icon-sprite): кнопка из
// шаблона и кнопка, которую собирает JS, берут один и тот же <symbol> и не
// могут разойтись по форме и толщине штриха. Ссылка, а не inline-<path>,
// ещё и не дублируется в двух файлах. Иконка наследует currentColor через
// класс .ico, поэтому переключается вместе с темой.
// Эмодзи для этого не годились: на Windows они рисовались цветными, на
// macOS монохромными, а часть значков (⏸ ⏹ 🔤) заменялась на чужой глиф —
// ряд кнопок разъезжался.
// Значения — плоские строки: тесты подгружают объект через eval, и вызов
// функции-фабрики им пришлось бы тащить в область видимости.
const UI_ICONS = {
  search:      '<svg class="ico" aria-hidden="true"><use href="#i-search"/></svg>',
  refresh:     '<svg class="ico" aria-hidden="true"><use href="#i-refresh"/></svg>',
  upload:      '<svg class="ico" aria-hidden="true"><use href="#i-upload"/></svg>',
  pause:       '<svg class="ico" aria-hidden="true"><use href="#i-pause"/></svg>',
  play:        '<svg class="ico" aria-hidden="true"><use href="#i-play"/></svg>',
  stop:        '<svg class="ico" aria-hidden="true"><use href="#i-stop"/></svg>',
  code:        '<svg class="ico" aria-hidden="true"><use href="#i-code"/></svg>',
  eye:         '<svg class="ico" aria-hidden="true"><use href="#i-eye"/></svg>',
  eyeOff:      '<svg class="ico" aria-hidden="true"><use href="#i-eye-off"/></svg>',
  bell:        '<svg class="ico" aria-hidden="true"><use href="#i-bell"/></svg>',
  bellOff:     '<svg class="ico" aria-hidden="true"><use href="#i-bell-off"/></svg>',
  sun:         '<svg class="ico" aria-hidden="true"><use href="#i-sun"/></svg>',
  moon:        '<svg class="ico" aria-hidden="true"><use href="#i-moon"/></svg>',
  x:           '<svg class="ico" aria-hidden="true"><use href="#i-x"/></svg>',
  check:       '<svg class="ico" aria-hidden="true"><use href="#i-check"/></svg>',
  square:      '<svg class="ico" aria-hidden="true"><use href="#i-square"/></svg>',
  checkSquare: '<svg class="ico" aria-hidden="true"><use href="#i-check-square"/></svg>',
  trash:       '<svg class="ico" aria-hidden="true"><use href="#i-trash"/></svg>',
  save:        '<svg class="ico" aria-hidden="true"><use href="#i-save"/></svg>',
  folder:      '<svg class="ico" aria-hidden="true"><use href="#i-folder"/></svg>',
  folderOpen:  '<svg class="ico" aria-hidden="true"><use href="#i-folder-open"/></svg>',
  spreadsheet: '<svg class="ico" aria-hidden="true"><use href="#i-spreadsheet"/></svg>',
  file:        '<svg class="ico" aria-hidden="true"><use href="#i-file"/></svg>',
  text:        '<svg class="ico" aria-hidden="true"><use href="#i-text"/></svg>',
  book:        '<svg class="ico" aria-hidden="true"><use href="#i-book"/></svg>',
  dice:        '<svg class="ico" aria-hidden="true"><use href="#i-dice"/></svg>',
  pencil:      '<svg class="ico" aria-hidden="true"><use href="#i-pencil"/></svg>',
  plus:        '<svg class="ico" aria-hidden="true"><use href="#i-plus"/></svg>',
  download:    '<svg class="ico" aria-hidden="true"><use href="#i-download"/></svg>',
  bolt:        '<svg class="ico" aria-hidden="true"><use href="#i-bolt"/></svg>',
  bulb:        '<svg class="ico" aria-hidden="true"><use href="#i-bulb"/></svg>',
  send:        '<svg class="ico" aria-hidden="true"><use href="#i-send"/></svg>',
  box:         '<svg class="ico" aria-hidden="true"><use href="#i-box"/></svg>',
  warn:        '<svg class="ico" aria-hidden="true"><use href="#i-warn"/></svg>',
  info:        '<svg class="ico" aria-hidden="true"><use href="#i-info"/></svg>',
  copy:        '<svg class="ico" aria-hidden="true"><use href="#i-copy"/></svg>',
  key:         '<svg class="ico" aria-hidden="true"><use href="#i-key"/></svg>',
  external:    '<svg class="ico" aria-hidden="true"><use href="#i-external"/></svg>',
  pulse:       '<svg class="ico" aria-hidden="true"><use href="#i-pulse"/></svg>',
  chart:       '<svg class="ico" aria-hidden="true"><use href="#i-chart"/></svg>',
  gear:        '<svg class="ico" aria-hidden="true"><use href="#i-gear"/></svg>',
  busy:        '<svg class="ico" aria-hidden="true"><use href="#i-hourglass"/></svg>',
};

// Значок пилюли состояния в шапке — по КЛАССУ состояния, а не по строке
// текста: текст меняется («В очереди» → «Выполняется» → «Готово»), а класс
// уже задаёт цвет пилюли, так что глиф и цвет не могут разойтись.
// Раньше эмодзи стояли прямо в строках статуса, и один и тот же смысл
// рисовался разными наборами глифов: ⏳ (эмодзи) в «Выполняется», ⏹ и ✔
// (символы) в «Остановлено»/«Готово». На Windows часть из них цветная.
const STATUS_ICONS = {
  running: UI_ICONS.busy,     // поиск идёт
  queued:  UI_ICONS.busy,     // ждём своей очереди
  paused:  UI_ICONS.pause,
  stopped: UI_ICONS.stop,
  error:   UI_ICONS.x,
  done:    UI_ICONS.check,
};

// Show/hide developer-detail lines collected behind the toggle.
function toggleTechDetails() {
  _showTechDetails = !_showTechDetails;
  const btn = document.getElementById('btn-tech-details');
  if (btn) {
    btn.innerHTML = (_showTechDetails ? UI_ICONS.eyeOff + 'Скрыть детали'
                                      : UI_ICONS.code + 'Технические детали');
    btn.classList.toggle('active', _showTechDetails);
  }
  const logPanel = document.getElementById('log-output');
  if (logPanel) logPanel.classList.toggle('show-tech', _showTechDetails);
  _refreshLogFilter();
}
// Structured stats card (stats.py emits a JSON payload instead of ASCII bars).
// Rendered as real rows with bars so it reads at a glance in both themes.
function renderLogStats(payload) {
  let d;
  try { d = typeof payload === 'string' ? JSON.parse(payload) : payload; } catch (e) { return; }
  if (!d || !d.total) return;
  const rows = (items, withBar) => {
    const max = Math.max(1, ...items.map(x => x.count));
    return items.map(it => {
      // Normalized against the max + 5px floor for tiny values (<3),
      // same rules as the «Статистика» tab bars.
      const min = withBar && it.count < 3 ? 'min-width:5px;' : '';
      return `
      <div class="log-stats-row">
        <span class="log-stats-label" title="${escapeHtml(it.label)}">${escapeHtml(it.label)}</span>
        ${withBar ? `<span class="log-stats-track"><span class="log-stats-bar" style="${min}width:${Math.round(it.count / max * 100)}%"></span></span>` : ''}
        <span class="log-stats-value">${it.count}${withBar ? '' : ' шт.'}</span>
      </div>`;
    }).join('');
  };
  const section = (title, items, withBar) =>
    (items && items.length)
      ? `<div class="log-stats-section"><div class="log-stats-title">${title}</div>${rows(items, withBar)}</div>`
      : '';
  const card = document.createElement('div');
  card.className = 'log-stats';
  card.innerHTML =
    `<div class="log-stats-head">📊 Статистика <span>${d.total} ${pluralRecords(d.total)}</span></div>`
    + section('По соцсетям', d.by_social, true)
    + section('По запросам', d.by_query, true)
    + section('Топ категорий', d.top_categories, false);
  const ph = document.getElementById('log-ph');
  if (ph) ph.remove();
  logEl.appendChild(card);
  _trimLog(logEl);
  _scrollLogIfFollowing();
}

function clearLog() {
  const S = _ls();
  logEl.innerHTML = '';
  _lastLogMsg = '';
  // Counters, folds and the stamp memory describe lines that no longer exist.
  S.meta = [];
  S.stats = {total: 0, noise: 0, err: 0, tech: 0};
  S.block = -1;
  S.collapsed = {};
  S.lastSec = '';
  S.below = 0;
  S.follow = true;
  _updateLogJump();
  // No header caption any more — the empty state lives inside the log itself.
  const ph = document.createElement('div');
  ph.className = 'log-empty';
  ph.id = 'log-ph';
  ph.textContent = 'Лог очищен — новые записи появятся здесь';
  logEl.appendChild(ph);
  _refreshLogFilter();
  renderDefaultStats();
}

// ═══════════════════════════════════════════
//  Progress message parsing
// ═══════════════════════════════════════════
function handleProgress(raw) {
  const parts = raw.split('/');
  // City completion event: city_done|idx|total|name|status|records
  if (raw.startsWith('city_done|')) {
    handleCityDone(raw);
    return;
  }
  // Full city queue (emitted once at run start): city_list|A/B/C
  if (raw.startsWith('city_list|')) {
    const names = raw.slice('city_list|'.length).split('/').map(s => s.trim()).filter(Boolean);
    if (names.length > 1) {
      initCityProgress(names.length);
      names.forEach(n => {
        if (!_cityProgressData[n]) updateCityProgress(n, 0, 0, 'queued');
      });
      renderCityProgress();
    }
    return;
  }
  // City transition event: city/idx/total/name
  if (parts[0] === 'city' && parts.length >= 4) {
    const idx   = parseInt(parts[1]);
    const total = parseInt(parts[2]);
    const name  = parts.slice(3).join('/');
    const label = `🏙  Город ${idx}/${total}: ${name}`;
    setProgress(-1, label);
    appendLog('info', label);
    const lsStage = document.getElementById('ls-stage');
    if (lsStage) lsStage.textContent = name;
    _lastCompletedCityIdx = idx;
    // Init multi-city progress
    if (total > 1) initCityProgress(total);
    _currentCityName = name;
    updateCityProgress(name, 0, 0, 'running');
    return;
  }
  if (parts.length >= 2) {
    const cur = parseInt(parts[0]), tot = parseInt(parts[1]);
    const stage = parts[2] || '';
    const found = parts.length >= 4 ? parseInt(parts[3]) : 0;
    // 5th segment (optional): 2GIS Places quota used this run (child process
    // streams it via progress events because /status can't see the child).
    if (parts.length >= 5) {
      const q = parseInt(parts[4]);
      if (!isNaN(q) && q > 0) { _twogisQuotaLive = q; renderQuotaCard(); }
    }
    const pct = tot > 0 ? Math.round(cur / tot * 100) : 0;
    const elapsedSec = (Date.now() - startTime) / 1000;

    let etaStr = '';
    if (cur > 2 && tot > cur && elapsedSec > 1) {
      const speed = cur / elapsedSec;
      const etaSec = Math.round((tot - cur) / speed);
      if (etaSec > 0) {
        etaStr = etaSec < 60
          ? ` · осталось ~${etaSec}с`
          : ` · осталось ~${Math.ceil(etaSec / 60)}м`;
      }
    }

    const stageLabel = stage ? ` · «${stage}»` : '';
    const foundLabel = found > 0 ? ` · ${found} найдено` : '';
    setProgress(pct, `${pct}%${stageLabel}${foundLabel}${etaStr}`);
    document.title = `${pct}% ⏳ (${found} найдено) — Парсер`;

    // Update live stats strip
    const lsFound = document.getElementById('ls-found-num');
    if (lsFound) lsFound.textContent = found;
    const lsStage = document.getElementById('ls-stage');
    if (lsStage) lsStage.textContent = stage ? `«${stage}» · ${cur} из ${tot}` : `${cur} из ${tot}`;

    // Update city-specific progress
    if (_currentCityName) {
      updateCityProgress(_currentCityName, pct, found, 'running');
    }
  }
}

// ═══════════════════════════════════════════
//  Run / Stop
// ═══════════════════════════════════════════
function getParams() {
  return {
    queries:         document.getElementById('f-queries').value.split('\n').map(s=>s.trim()).filter(Boolean),
    cities:          [...selectedCities],
    output_excel:    document.getElementById('f-excel').checked,
    output_json:     document.getElementById('f-json').checked,
    output_csv:      document.getElementById('f-csv').checked,
    output_map:      document.getElementById('f-map').checked,
    max_pages:       +document.getElementById('f-pages').value   || 1,
    max_workers:     +document.getElementById('f-workers').value || 20,
    query_workers:   +document.getElementById('f-query-workers').value || 2,
    max_candidates:  getMaxCandidates(),
    parse_mode:      parseMode,
    source:          dataSource,
    excel_columns:   getExcelCols(),
    use_grid:        _gridMode === 'manual',
    grid_radius:     +document.getElementById('f-grad').value  || 20,
    grid_step:       +document.getElementById('f-gstep').value || 5,
    // Соцсети с карточек собираются всегда: без них не работают ни фильтр
    // по соцсетям, ни оценка лида (шаг 03).
    fetch_detail:    true,
    collapse_chains: document.getElementById('f-collapse-chains').checked,
    chain_key:       (document.getElementById('f-chain-key') || {}).value || 'name_city',
    // Two-stage pipeline: the web app always collects raw (stage 1);
    // parse_mode is applied afterwards (stage 2).
    pipeline:        'raw',
    raw_mode:        (document.getElementById('f-raw-mode') || {}).value || 'keep',
    continue_cities: document.getElementById('f-continue')?.checked || false,
    continue_limit:  parseInt((document.getElementById('f-continue-limit')||{}).value, 10) || 0,
    api_key:         document.getElementById('f-apikey').value.trim(),
    twogis_api_key:  (document.getElementById('f-2gis-key') || {}).value?.trim() || '',
    social_mode:     socialMode,
    required_socials: [...requiredSocials],
    // Stage-2 lead scoring / VK activity (accordion «Фильтрация результата»).
    vk_check:         !!(document.getElementById('f-vk-check')||{}).checked,
    vk_mode:          vkMode,
    vk_max_post_days: parseInt((document.getElementById('f-vk-max-days')||{}).value, 10) || 0,
    vk_min_followers: parseInt((document.getElementById('f-vk-min-followers')||{}).value, 10) || 0,
    min_lead_score:   parseInt((document.getElementById('f-min-score')||{}).value, 10) || 0,
    sort_by_score:    (document.getElementById('f-sort-score')||{}).checked !== false,
    // «🚫 Исключить по словам»: слова снимают записи до остальных фильтров.
    blacklist_words:  [...blacklistWords],
    // «🎯 Тип компании»: одиночки и/или новые (null — фильтр выключен).
    only_single_branch: onlySingleChecked(),
    only_new_months:    newMonthsValue(),
  };
}

// Лимит организаций на город: защита от некорректного ввода.
// Пустое/0/отрицательное → 200 (по умолчанию), больше 10000 → 10000.
function getMaxCandidates() {
  const el = document.getElementById('f-max-candidates');
  let v = parseInt(el.value, 10);
  if (!v || v < 1) v = 200;
  if (v > 10000) v = 10000;
  if (el.value !== String(v)) el.value = v;
  return v;
}

// ♾ Continuation mode: show the limit stepper only when enabled.
function onContinueToggle() {
  const cb = document.getElementById('f-continue');
  const row = document.getElementById('continue-limit-row');
  if (!cb || !row) return;
  row.style.display = cb.checked ? '' : 'none';
}

// Reset everything that belongs to one run (fresh display on new launch,
// no leftovers from previous runs: city progress, live stats, results).
function resetRunUI() {
  _cityProgressData = {};
  _totalCities = 0;
  _currentCityName = '';
  _lastCompletedCityIdx = 0;
  if (_liveStatsTimer) { clearTimeout(_liveStatsTimer); _liveStatsTimer = null; }
  const listEl = document.getElementById('city-progress-list');
  if (listEl) listEl.innerHTML = '';
  const cpEl = document.getElementById('city-progress');
  if (cpEl) cpEl.style.display = 'none';
  const lsNum = document.getElementById('ls-found-num');
  if (lsNum) lsNum.textContent = '0';
  const lsStage = document.getElementById('ls-stage');
  if (lsStage) lsStage.textContent = '';
  updateTermProgress();
  updateStatsBadge();
}

function startRun() {
  const params = getParams();
  // Belt-and-braces: the button is normally disabled when not ready, but a
  // stale state must never start an empty run.
  if (!params.queries.length || !params.cities.length) updateRunBtnState();
  clearFieldError(document.getElementById('fw-city'));
  const queriesBox = document.getElementById('f-queries').closest('div');
  clearFieldError(queriesBox);
  // Live-clear: errors disappear as soon as the user edits the field again
  document.getElementById('f-queries').addEventListener('input', e => {
    clearFieldError(queriesBox);
    updateQueriesCounter();   // keeps the «Будет выполнено N запросов» counter live
  });
  const _cityInput = document.getElementById('f-city-input');
  if (_cityInput) _cityInput.addEventListener('input', () => clearFieldError(document.getElementById('fw-city')), { once: true });
  if (!params.queries.length) {
    document.getElementById('f-queries').classList.add('field-invalid');
    showFieldError(queriesBox, 'Введите хотя бы один запрос');
    showToast('Введите хотя бы один запрос', 'error');
    return;
  }
  if (!params.cities.length) {
    showFieldError(document.getElementById('fw-city'), 'Введите город');
    showToast('Введите хотя бы один город', 'error');
    return;
  }

  clearLog();
  // Skeleton loaders while the backend spins up — replaced by real log lines
  logEl.insertAdjacentHTML('beforeend', `
    <div id="log-skeleton" class="log-skeleton">
      ${['sk-w20','sk-w65','sk-w35','sk-w80','sk-w50'].map(w =>
        `<div class="sk-row"><span class="sk-bar sk-ico" style="border-radius:50%"></span><span class="sk-bar ${w}"></span></div>`
      ).join('')}
    </div>`);
  allResults = []; filteredRows = [];
  if (_liveRenderTimer) { clearTimeout(_liveRenderTimer); _liveRenderTimer = null; }
  _resetTableBadge();
  document.getElementById('tbl-body').innerHTML =
    '<tr><td colspan="9" class="no-data">Ожидание результатов…</td></tr>';
  // Stats keep their default zero cards during the run — numbers fill in
  // live as cities complete.
  renderDefaultStats();
  document.getElementById('dl-section').style.display = 'none';
  mapInited = false; if (leafMap) { leafMap.remove(); leafMap = null; }
  document.getElementById('map-container').innerHTML = '';

  _startRunWithParams(params);
}

// Core launch used by both startRun() (fresh form params) and resumeRun()
// (paused run params + resume:true): pre-launch UI state + POST /run + SSE.
function _startRunWithParams(params) {
  resetRunUI();
  // A resumed run keeps the tiles the user had chosen (they are part of the
  // saved params) — only a fresh launch starts from an empty selection.
  requiredSocials.clear();
  initSocialNetCheckboxes();
  if (Array.isArray(params.required_socials) && params.required_socials.length) {
    params.required_socials.forEach(k => {
      const inp = document.querySelector('#social-net-chk-grid input[data-soc-key="' + k + '"]');
      const tile = inp ? inp.closest('.soc-tile') : null;
      if (tile) toggleRequiredSocial(k, tile);
    });
  }
  updateSocialFilterHint();
  setRunIndicator(true);
  setStatus('running', 'Выполняется');
  setProgress(0, 'Запуск…');
  setRunBtnActive();
  // `cities` is always present on a fresh launch; a resumed payload is
  // server-built, so never assume the array exists (a throw here used to
  // leave the button dead — «продолжить» did nothing at all).
  if ((params.cities || []).length > 1) {
    document.getElementById('btn-skip').style.display = 'inline-block';
  }
  startTime = Date.now();
  _runEnd = null;   // новый поиск — таймер «Время» снова живой
  // Show live stats strip and reset counters
  const ls = document.getElementById('live-stats');
  if (ls) { ls.style.display = 'flex'; }
  const lsNum = document.getElementById('ls-found-num');
  if (lsNum) lsNum.textContent = '0';
  const lsStage = document.getElementById('ls-stage');
  if (lsStage) lsStage.textContent = 'запуск…';

  showTab('log');
  saveSettings();

  if (evtSource) { evtSource.close(); evtSource = null; }

  fetch('/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(params)})
    .then(r => r.json().then(d => ({ok: r.ok, status: r.status, data: d})))
    .then(({ok, status, data}) => {
      if (status === 409 || (data && data.error)) {
        appendLog('warn', '  [!] ' + (data.error || 'Ошибка запуска'));
        showToast(data.error || 'Ошибка запуска', 'error');
        resetBtn(); setStatus('error','Ошибка'); hideProgress();
        return;
      }
      if (data && data.queued) {
        appendLog('info', `  ⏳ Поиск поставлен в очередь (позиция: ${data.position}). Текущий поиск завершится автоматически.`);
        setStatus('queued', 'В очереди');
        document.getElementById('btn-txt').textContent = 'В очереди…';
        setProgress(0, `Очередь: позиция ${data.position}`);
        // Poll /status and start SSE when our queued run becomes active.
        // A deadline guards against polling forever if the run is cancelled
        // or the queue is cleared server-side.
        const _queuedRunId = data.run_id;
        const _pollDeadline = Date.now() + 30 * 60 * 1000; // 30 min
        const _pollInterval = setInterval(() => {
          if (Date.now() > _pollDeadline) {
            clearInterval(_pollInterval);
            appendLog('warn', '  [!] Ожидание в очереди прервано по таймауту. Запустите поиск заново.');
            resetBtn(); setStatus('stopped', 'Таймаут очереди'); hideProgress();
            return;
          }
          fetch('/status').then(r => r.json()).then(s => {
            if (s.active_run === _queuedRunId || !s.queued) {
              clearInterval(_pollInterval);
              if (s.active_run === _queuedRunId) {
                // Our run is now active — connect SSE
                startTime = Date.now();
                _runEnd = null;
                startSSE();
              }
            }
          }).catch(() => {});
        }, 2000);
        return;
      }
      startSSE();
    })
    .catch(err => { appendLog('warn', '  [!] ' + err.message); resetBtn(); setStatus('error','Ошибка'); hideProgress(); });
}

function stopRun() {
  _lastCompletedCityIdx = 0;
  fetch('/stop', {method:'POST'}).catch(()=>{});
  appendLog('warn', '  [!] Остановка запрошена…');
}

// ── Skip City ───────────────────────────────────────────────
function skipCity() {
  // Fetch current city info for confirmation
  fetch('/skip-city', {method:'POST'})
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        appendLog('ok', `  ⏭ Город «${data.city}» пропущен (${data.records} записей)`);
      }
    })
    .catch(() => {});
}

function showSkipConfirm() {
  // Fetch current city info for confirmation dialog (check=true means don't skip yet)
  fetch('/skip-city?check=1', {method:'POST'})
    .then(r => r.json())
    .then(data => {
      const city = data.city || '…';
      const records = data.records || 0;
      const overlay = document.createElement('div');
      overlay.className = 'skip-modal-overlay';
      overlay.innerHTML = `
        <div class="skip-modal">
          <h3>⏭ Пропустить город?</h3>
          <p>Вы уверены, что хотите пропустить город <b>«${city}»</b>?<br>
          Собрано <b>${records}</b> записей. Данные будут сохранены.</p>
          <div class="skip-modal-btns">
            <button class="skip-cancel" onclick="this.closest('.skip-modal-overlay').remove()">Отмена</button>
            <button class="skip-confirm" onclick="skipCity();this.closest('.skip-modal-overlay').remove()">Пропустить</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    })
    .catch(() => {});
}

function handleCityDone(raw) {
  // City completion event: city_done|idx|total|name|status|records
  const parts = raw.split('|');
  if (parts[0] === 'city_done' && parts.length >= 6) {
    const idx     = parseInt(parts[1]);
    const total   = parseInt(parts[2]);
    const name    = parts[3];
    const status  = parts[4]; // 'done' or 'skipped'
    const records = parseInt(parts[5]) || 0;
    const icon    = status === 'skipped' ? '⏭' : '✅';
    const label   = status === 'skipped'
      ? `${icon} Город ${idx}/${total}: ${name} — пропущен (${records} записей)`
      : `${icon} Город ${idx}/${total}: ${name} — завершён (${records} записей)`;
    appendLog(status === 'skipped' ? 'ok' : 'info', label);
    // Update city progress to completed
    updateCityProgress(name, 100, records, status);
    // City finished — update the tab badge and render its stats right away
    // (finished cities only), so per-city numbers are exact while the next
    // city is still running.
    updateStatsBadge();
    refreshLiveStats();
    // Уведомление/звук «город завершён» — только если этот тип включён.
    // (typeof — потому что в node-тестах функция может быть не подложена.)
    if (typeof notifyCityComplete === 'function') {
      notifyCityComplete({ name, idx, total, status, records });
    }
  }
}

// ═══════════════════════════════════════════
//  Live per-city stats (multi-city runs)
// ═══════════════════════════════════════════
function isRunActive() {
  const btn = document.getElementById('btn-run');
  return btn ? btn.disabled : false;
}

// Records belonging to cities whose search already finished (done/skipped).
// The still-running city is excluded so its partial counts never appear as
// final numbers in the per-city cards.
function completedCityRecords() {
  const done = new Set();
  for (const [name, d] of Object.entries(_cityProgressData)) {
    if (d.status === 'done' || d.status === 'skipped') done.add(name);
  }
  return allResults.filter(r => r && r.city && done.has(r.city));
}

let _liveStatsTimer = null;

// Render the stats panel from finished cities only. Called right after each
// city_done event; the delayed second pass catches a record that was emitted
// a moment after the event (queue ordering is not strictly guaranteed).
function refreshLiveStats() {
  const doRender = () => {
    _liveStatsTimer = null;
    const recs = completedCityRecords();
    if (!recs.length) return;
    renderStats(recs, _runElapsed(), _lastSkippedCities);
  };
  doRender();
  if (_liveStatsTimer) clearTimeout(_liveStatsTimer);
  _liveStatsTimer = setTimeout(doRender, 1500);
}

// Show how many cities finished on the «Статистика» tab button, so the user
// notices stats are ready while the run is still in progress. When no run is
// active the plain label is restored.
function updateStatsBadge() {
  const btn = document.getElementById('t-stats');
  if (!btn) return;
  if (!isRunActive()) { btn.innerHTML = 'Статистика'; return; }
  const cnt = Object.values(_cityProgressData)
    .filter(d => d.status === 'done' || d.status === 'skipped').length;
  btn.innerHTML = cnt > 0
    ? `Статистика <span class="live-badge">${cnt}</span>`
    : 'Статистика';
}

function startSSE(runId) {
  const url = runId ? `/logs?run_id=${runId}` : '/logs';
  evtSource = new EventSource(url);
  evtSource.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;      if (msg.type === 'log') {
      if (msg.level === 'progress') { handleProgress(msg.msg); return; }
      if (msg.level === 'analytics') { /* analytics handled by renderStats */ return; }
      if (msg.level === 'stats') { renderLogStats(msg.msg); return; }
      appendLog(msg.level, msg.msg);
    } else if (msg.type === 'result') {
      onLiveResult(msg.data);
    } else if (msg.type === 'done') {
      onRunDone(msg);
      evtSource.close(); evtSource = null;
    }
  };
  evtSource.onerror = () => {
    setStatus('error','Соединение прервано');
    resetBtn(); hideProgress();
    evtSource.close(); evtSource = null;
  };
}

// ═══════════════════════════════════════════
//  Live streaming result handler
// ═══════════════════════════════════════════
function _resetTableBadge() {
  document.getElementById('t-table').textContent = 'Результаты';
}

let _liveRenderTimer = null;

function onLiveResult(rec) {
  allResults.push(rec);

  // On first result: reveal the right panel
  if (allResults.length === 1) {
    document.querySelector('.right-col').classList.add('revealed');
    document.getElementById('social-filter-row').classList.remove('empty');
    const exportWrap = document.getElementById('export-sel-wrap');
    if (exportWrap) exportWrap.style.display = 'flex';
  }

  // Animate the Results tab badge (cheap, immediate)
  const tabBtn = document.getElementById('t-table');
  tabBtn.innerHTML = `Результаты <span class="live-badge">${allResults.length}</span>`;

  // Throttle filter + table re-render: with thousands of live records a
  // per-record re-render is O(n²) DOM churn and the UI stutters.
  scheduleLiveRender();
}

function scheduleLiveRender() {
  if (_liveRenderTimer) return;
  _liveRenderTimer = setTimeout(() => {
    _liveRenderTimer = null;
    // Re-apply current filter (respects search box + social filters + social mode)
    const q = document.getElementById('tbl-search').value.trim().toLocaleLowerCase('ru-RU');
    const SOCIAL_KEYS = Object.keys(SOCIALS);
    filteredRows = allResults.filter(r => {
      const searchable = Object.values(r).some(value =>
        String(value ?? '').toLocaleLowerCase('ru-RU').includes(q)
      );
      if (q && !searchable) return false;
      // Social mode filter
      if (socialMode === 'with_socials') {
        const hasAny = SOCIAL_KEYS.some(k => r[k]);
        if (!hasAny) return false;
      } else if (socialMode === 'without_socials') {
        const hasAny = SOCIAL_KEYS.some(k => r[k]);
        if (hasAny) return false;
      }
      // Required socials AND filter
      if (requiredSocials.size > 0) {
        if (![...requiredSocials].every(key => r[key])) return false;
      }
      if (activeSocialFilters.size > 0) {
        if (![...activeSocialFilters].some(key => r[key])) return false;
      }
      return true;
    });

    // Always re-render (even while the results tab is hidden): the table then
    // already shows the latest partial rows whenever the user opens it mid-run.
    // Rendering is throttled and only builds one 50-row page, so the cost of
    // keeping a hidden panel current is negligible.
    renderPage();
  }, 250);
}

function onRunDone(msg) {
  const stopped = msg.stopped;
  const skippedCities = msg.skipped_cities || [];
  _lastSkippedCities = skippedCities;
  // ⏸ Paused run: keep the dock in paused mode and keep the SSE/UI state —
  // the user continues with one click instead of reconfiguring the search.
  if (msg.paused) {
    enterPausedState(msg.resume || null);
    appendLog('ok', '  ⏸ Поиск на паузе — прогресс сохранён. Нажмите «Продолжить поиск».');
    showToast('Поиск на паузе — прогресс сохранён', 'info');
    return;                                   // no resetBtn / no downloads UI churn
  }
  setStatus(stopped ? 'stopped' : 'done', stopped ? 'Остановлено' : 'Готово');
  document.title = 'Яндекс.Карты — Парсер бизнесов';
  resetBtn();
  hideProgress();
  // Фиксируем момент завершения: «Время» в статистике больше не растёт.
  if (!_runEnd) _runEnd = Date.now();
  showDownloads(msg.files || [], msg.formats || []);
  // «Всё уже спарсено раньше»: сервер сообщает, что поиск вернул организации,
  // но все они уже были в кэше — файлы при этом не создаются. Без этого
  // сообщения повторный запуск выглядел как «нашлось 0» без причины.
  if (msg.all_seen && !stopped) {
    showToast('Все найденные организации уже парсились ранее — новых нет. Кэш: «История» → 🗑 Очистить кэш', 'warning');
  }
  const elapsed = _runElapsed();

  // Which files may carry full records (english keys): the internal merged
  // frontend file plus any user-facing per-city JSON files.
  const allFiles = msg.files || [];
  const mergedFile = allFiles.find(f => f === '_results_for_frontend.json');
  const cityFiles = allFiles.filter(f => f.endsWith('.json') && !f.startsWith('_'));
  const candidates = mergedFile ? [mergedFile] : cityFiles;

  const finalize = (data) => {
    allResults = data;
    _resetTableBadge();
    loadReviewed();
    // City dropdown "last searched" labels come from /history — refresh
    // them now so the date/keywords update right after a finished run.
    loadCityHistoryMeta();
    renderTable(allResults);
    if (allResults.length) {
      renderStats(allResults, elapsed, skippedCities);
      showTab('table');
    } else {
      // Completed with nothing found — replace the "waiting…" placeholder.
      // «Уже парсились ранее» must be told apart from «ничего не подошло»:
      // the first one is fixed by clearing the seen cache, not by filters.
      const emptyMsg = msg.all_seen
        ? 'Ничего нового: все организации этого города уже были спарсены ранее. '
          + 'Файлы не создавались. Чтобы пройти город заново — вкладка «История» → «🗑 Очистить кэш».'
        : 'Результатов не найдено. Измените запросы, города или фильтры.';
      document.getElementById('stats-body').innerHTML =
        `<div class="no-data">${emptyMsg}</div>`;
    }
    // Notification / sound (only on clean completion)
    if (!stopped && typeof notifySearchComplete === 'function') {
      notifySearchComplete({
        cities:  _totalCities || selectedCities.length || 0,
        found:   Array.isArray(allResults) ? allResults.length : 0,
        seconds: _runElapsed(),
      });
    }
  };

  // Union the live-streamed records (may include a partially-finished city
  // when the run was stopped) with anything the server wrote to disk, so a
  // stop never makes the table emptier than what was already collected.
  const liveFallback = Array.isArray(allResults) ? allResults.slice() : [];

  const union = (a, b) => {
    const seen = new Set();
    return a.concat(b).filter(r => {
      if (!r || typeof r !== 'object') return false;
      // Only business-shaped records belong in the table (guards against
      // stray entries like search-history items with no name/url).
      if (!r.name && !r.yandex_maps_url && !r.twogis_url) return false;
      const k = r.yandex_maps_url || r.twogis_url || (r.name + '|' + r.address);
      if (!k || seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  };

  if (!candidates.length) {
    // No JSON files at all (e.g. stopped before any city finished, or
    // only Excel output) — live-streamed records are the source of truth.
    finalize(liveFallback);
    return;
  }

  Promise.all(candidates.map(f =>
    fetch('/results/' + encodeURIComponent(f))
      .then(r => r.json())
      .catch(() => null)
  )).then(arrays => {
    let data = [];
    arrays.forEach(a => {
      if (Array.isArray(a) && a.length) data = data.concat(a);
    });
    finalize(union(liveFallback, data));
  }).catch(() => finalize(liveFallback));
}

function resetBtn() {
  const btn = document.getElementById('btn-run');
  if (btn) {
    btn.disabled = false;
    btn.onclick = startRun;                    // back to the run control
    btn.classList.remove('run-active');
    btn.classList.remove('run-paused');
    btn.hidden = false;
    btn.title = '';

  }
  const stopBtn = document.getElementById('btn-stop');
  if (stopBtn) { stopBtn.hidden = true; stopBtn.onclick = null; }
  _pausedRun = null;
  setRunIndicator(false);
  document.getElementById('btn-icon').innerHTML = UI_ICONS.search;
  document.getElementById('btn-txt').textContent = 'Найти компании';
  document.getElementById('btn-skip').style.display = 'none';
  // Run finished → back to ready/grey depending on what is filled in.
  updateRunBtnState();
  updateStatsBadge();
}

// ═══════════════════════════════════════════
//  Downloads
// ═══════════════════════════════════════════
// ═════════════════════════════════════════
//  Results view: raw / processed / all (two-stage pipeline)
// ═════════════════════════════════════════
let _resultsView = 'raw';
// «Текущий результат» — срез ПОСЛЕДНЕГО поиска, а не всей папки: файлы
// прошлых запусков живут в «Истории файлов» (scope=all — явный показ всего).
let _resultsScope = 'current';
// Номер последнего запроса: ответы отменённых переключений игнорируются,
// иначе медленный ответ «Сырых данных» перетирал уже показанные
// «Обработанные» — в таблице оставались данные не той вкладки.
let _resultsReqSeq = 0;

function updateScopeButton() {
  const b = document.getElementById('btn-scope-all');
  if (!b) return;
  const on = _resultsScope === 'all';
  b.classList.toggle('active', on);
  b.innerHTML = (on ? UI_ICONS.checkSquare : UI_ICONS.square) + 'Все поиски';
  b.title = on
    ? 'Показаны файлы всех поисков в папке. Нажмите, чтобы вернуться к текущему поиску.'
    : 'Показаны только результаты текущего поиска. Нажмите, чтобы увидеть все файлы в папке (прошлые поиски).';
}

function toggleScopeAll() {
  _resultsScope = _resultsScope === 'all' ? 'current' : 'all';
  try { localStorage.setItem(SCOPE_KEY, _resultsScope); } catch (e) {}
  updateScopeButton();
  setResultsView(_resultsView);
}

function setResultsView(view) {
  if (!['raw', 'processed', 'all'].includes(view)) view = 'raw';
  _resultsView = view;
  document.querySelectorAll('#results-toggle .rt-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  const body = document.getElementById('tbl-body');
  if (body) body.innerHTML = '<tr><td colspan="7" class="no-data">Загрузка…</td></tr>';
  currentFileNote = _resultsScope === 'all' ? ' · все файлы в папке' : '';
  currentFile = '';
  const seq = ++_resultsReqSeq;
  const scope = _resultsScope;
  fetch('/results-view?view=' + encodeURIComponent(view) + '&scope=' + encodeURIComponent(scope))
    .then(r => r.json())
    .then(data => {
      if (seq !== _resultsReqSeq) return;   // устаревший ответ — вкладку уже переключили
      allResults = data.records || [];
      _lastCities = data.cities || [];
      _resetTableBadge();
      loadReviewed();
      renderTable(allResults);
      if (!allResults.length) {
        let msg = view === 'processed'
          ? 'Ничего не найдено по заданным фильтрам. Измените настройки.'
          : 'Нет данных. Запустите сбор — сырые результаты появятся здесь.';
        if (scope === 'current') {
          msg += ' Файлы прошлых поисков — в «Истории файлов» (или включите «Все поиски»).';
        }
        document.getElementById('tbl-body').innerHTML =
          `<tr><td colspan="7" class="no-data">${msg}</td></tr>`;
      }
      updateBulkStats();
      if (typeof updateStatsBadge === 'function') updateStatsBadge();
    })
    .catch(() => {
      if (seq !== _resultsReqSeq) return;
      document.getElementById('tbl-body').innerHTML =
        '<tr><td colspan="7" class="no-data">Ошибка загрузки данных</td></tr>';
    });
}

// ═══════════════════════════════════════════
//  «Куда сохранять»: папка результатов
//  Папка живёт в settings.json на сервере (её читает и парсер), поэтому
//  источник правды — GET /output-dir, а не localStorage.
// ═══════════════════════════════════════════
const OUT_ADV_KEY = 'yp_output_advanced';
let _outputDirs = null;      // последнее состояние от сервера

function _setText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }

function onOutputAdvancedToggle() {
  const on = !!(document.getElementById('f-output-advanced') || {}).checked;
  const box = document.getElementById('output-advanced');
  if (box) box.classList.toggle('open', on);
  try { localStorage.setItem(OUT_ADV_KEY, on ? '1' : '0'); } catch (e) {}
}

function updateOutputDirHint(state) {
  const hint = document.getElementById('output-dir-hint');
  if (!hint || !state) return;
  const custom = !!state.custom || !!state.advanced;
  hint.textContent = custom
    ? `Файлы сохраняются в: ${state.raw} · ${state.processed} · ${state.archive}. Ключи, кэш найденного и история остаются в папке приложения.`
    : `По умолчанию: ${state.root}. Внутри создаются raw/, processed/ и _archive/.`;
}

function showOutputDirError(msg, field) {
  const box = document.getElementById('output-dir-err');
  if (box) { box.innerHTML = UI_ICONS.warn + escapeHtml(msg); box.hidden = !msg; }
  ['f-output-dir', 'f-output-raw', 'f-output-processed', 'f-output-archive'].forEach(id => {
    const el = document.getElementById(id);
    if (el && el.classList) el.classList.toggle('field-invalid', !!msg && (!field || id === field));
  });
}

function applyOutputDirState(state, opts) {
  if (!state) return;
  _outputDirs = state;
  const root = document.getElementById('f-output-dir');
  if (root) root.value = state.root || '';
  const adv = document.getElementById('f-output-advanced');
  if (adv) adv.checked = !!state.advanced;
  const fill = (id, value) => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  // В обычном режиме поля показывают фактические подпапки общей папки —
  // так видно, куда реально попадут файлы.
  fill('f-output-raw', state.advanced ? state.raw : '');
  fill('f-output-processed', state.advanced ? state.processed : '');
  fill('f-output-archive', state.advanced ? state.archive : '');
  onOutputAdvancedToggle();
  updateOutputDirHint(state);
  showOutputDirError('', null);
  if (opts && opts.toast) {
    showToast(opts.pending
      ? '📁 Папка сохранена — применится со следующего города'
      : '📁 Папка для сохранения обновлена', opts.pending ? 'info' : 'success');
  }
}

function loadOutputDir() {
  fetch('/output-dir')
    .then(r => r.json())
    .then(d => { if (d && d.root) applyOutputDirState(d); })
    .catch(() => {});
}

// 📁 Обзор… — системный диалог открывает сервер (браузер не отдаёт путь).
function pickOutputDir() {
  const btn = document.getElementById('btn-output-browse');
  if (btn) { btn.disabled = true; btn.innerHTML = UI_ICONS.busy + 'Открываю…'; }
  postJSON('/folder-picker', {})
    .then(d => {
      if (d && d.ok && d.path) {
        const el = document.getElementById('f-output-dir');
        if (el) el.value = d.path;
        showOutputDirError('', null);
        showToast('Папка выбрана — нажмите «Сохранить»', 'info');
      } else if (!(d && d.cancelled)) {
        showOutputDirError((d && d.error) || 'Не удалось выбрать папку', null);
      }
    })
    .catch(() => showOutputDirError('Не удалось открыть диалог выбора папки', null))
    .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.folder + 'Обзор…'; } });
}

function saveOutputDir() {
  const val = id => ((document.getElementById(id) || {}).value || '').trim();
  const advanced = !!(document.getElementById('f-output-advanced') || {}).checked;
  const btn = document.getElementById('btn-output-save');
  if (btn) { btn.disabled = true; btn.innerHTML = UI_ICONS.busy + 'Проверяю…'; }
  postJSON('/output-dir', {
    root: val('f-output-dir'), advanced,
    raw: advanced ? val('f-output-raw') : '',
    processed: advanced ? val('f-output-processed') : '',
    archive: advanced ? val('f-output-archive') : '',
  })
    .then(d => {
      if (d && d.ok) {
        applyOutputDirState(d, {toast: true, pending: d.pending});
      } else {
        showOutputDirError((d && d.error) || 'Не удалось сохранить папку', null);
      }
    })
    .catch(() => showOutputDirError('Не удалось сохранить папку', null))
    .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.save + 'Сохранить'; } });
}

function resetOutputDir() {
  const btn = document.getElementById('btn-output-default');
  if (btn) btn.disabled = true;
  postJSON('/output-dir', {reset: true})
    .then(d => {
      if (d && d.ok) {
        applyOutputDirState(d, {toast: true, pending: d.pending});
      } else {
        showOutputDirError((d && d.error) || 'Не удалось вернуть папку по умолчанию', null);
      }
    })
    .catch(() => showOutputDirError('Не удалось вернуть папку по умолчанию', null))
    .finally(() => { if (btn) btn.disabled = false; });
}

// 🔄 Re-run stage 2 (filtering) on the saved raw data — no new crawling.
// There are two of these buttons (the filter accordion and the RAW section of
// «История файлов»); both drive the same call and show the same progress.
// Подпись с иконкой: эмодзи здесь перекрывало SVG из разметки (textContent
// стирал значок), поэтому и восстановление идёт тем же инлайновым SVG.
const REFILTER_LABEL = UI_ICONS.refresh + 'Применить фильтры заново';
function _refilterButtons() {
  return ['btn-refilter', 'btn-refilter-files']
    .map(id => document.getElementById(id)).filter(Boolean);
}
function refilterNow() {
  const buttons = _refilterButtons();
  // How much work is coming: the raw files are already on disk, so the count
  // is known before the request starts.
  const rawCount = ((filesData || {}).raw || []).length;
  const busy = rawCount ? `Обрабатываю ${rawCount} ${pluralFiles(rawCount)}…` : 'Обработка…';
  buttons.forEach(b => { b.disabled = true; b.innerHTML = UI_ICONS.busy + busy; });
  const formats = [];
  if (document.getElementById('f-excel')?.checked) formats.push('excel');
  if (document.getElementById('f-json')?.checked)  formats.push('json');
  if (document.getElementById('f-csv')?.checked)   formats.push('csv');
  if (document.getElementById('f-map')?.checked)   formats.push('html');
  if (!formats.length) formats.push('excel');
  // The payload mirrors a fresh run: EVERY stage-2 filter travels along.
  // Leaving the VK/score ones out made «Применить фильтры заново» quietly
  // return a different slice than the same settings during a search.
  const body = {
    formats,
    collapse_chains: document.getElementById('f-collapse-chains')?.checked || false,
    chain_key:       (document.getElementById('f-chain-key') || {}).value || 'name_city',
    parse_mode:      parseMode || 'all',
    social_mode:     socialMode || 'all',
    required_socials:[...requiredSocials],
    raw_mode:        (document.getElementById('f-raw-mode')||{}).value || 'keep',
    vk_check:         !!(document.getElementById('f-vk-check') || {}).checked,
    vk_mode:          vkMode || 'all',
    vk_max_post_days: (document.getElementById('f-vk-max-days')     || {}).value || 0,
    vk_min_followers: (document.getElementById('f-vk-min-followers') || {}).value || 0,
    min_lead_score:   (document.getElementById('f-min-score') || {}).value || 0,
    sort_by_score:    (document.getElementById('f-sort-score') || {}).checked !== false,
    blacklist_words:  [...blacklistWords],
    // «🎯 Тип компании» — тот же payload, что и у обычного запуска.
    only_single_branch: onlySingleChecked(),
    only_new_months:    newMonthsValue(),
  };
  fetch('/process-filters', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) {
        showToast(data.error || 'Ошибка обработки', 'error');
        appendLog('warn', '  [!] ' + (data.error || 'Ошибка обработки'));
        return;
      }
      if (data.empty) {
        showToast('Ничего не найдено по заданным фильтрам. Измените настройки', 'warn');
        appendLog('warn', '  ⚠ Ничего не найдено по заданным фильтрам. Измените настройки.');
        return;
      }
      // Полный путь: папка результатов может быть пользовательской.
      const outDir = data.out_dir ? data.out_dir.replace(/[\\/]+$/, '') : 'output';
      // У рефильтра нет потоковых логов сервера, поэтому строку про blacklist
      // пишем по счётчику из ответа — иначе слово-исключение «работает молча».
      if (blacklistWords.length) {
        appendLog('info', `  🚫 Blacklist: исключено ${data.blacklist_excluded || 0} компаний`);
      }
      // То же для «типа компании»: у рефильтра нет потоковых логов сервера.
      if (data.company_type_excluded) {
        appendLog('info', `  🎯 Тип компании: исключено ${data.company_type_excluded}`
          + ` (одиночки ${data.single_excluded || 0}, новые ${data.new_excluded || 0})`);
      }
      showToast(`Готово: ${data.count} организаций → ${data.files.length} файлов`, 'success');
      appendLog('ok', `  🎯 Processed: ${data.count} организаций → ${data.files.length} файлов в ${outDir}/processed/`);
      // The file lists just changed under the user's feet — refresh them.
      loadFilesPanel(true);
      setResultsView(_resultsView === 'raw' ? 'processed' : _resultsView);
      updateStatsBadge();
    })
    .catch(() => showToast('Ошибка обработки', 'error'))
    .finally(() => {
      buttons.forEach(b => { b.disabled = false; b.innerHTML = REFILTER_LABEL; });
    });
}

// Значки типов файлов — из того же спрайта, что и кнопки: в списке на 100+
// строк эмодзи рисовались цветными квадратами разной ширины и не слушали
// цвет темы (в тёмной теме выглядели как чужие).
const FILE_TYPE_ICONS = {
  xlsx: '<svg class="ico" aria-hidden="true"><use href="#i-spreadsheet"/></svg>',
  json: '<svg class="ico" aria-hidden="true"><use href="#i-text"/></svg>',
  csv:  '<svg class="ico" aria-hidden="true"><use href="#i-file"/></svg>',
  html: '<svg class="ico" aria-hidden="true"><use href="#i-map"/></svg>',
  dir:  '<svg class="ico" aria-hidden="true"><use href="#i-folder"/></svg>',
};
function fileIcon(n) {
  const ext = String(n || '').toLowerCase().split('.').pop();
  return FILE_TYPE_ICONS[ext] || FILE_TYPE_ICONS.dir;
}

function showDownloads(files, formats) {
  const allowed = new Set(formats || []);
  const filtered = files.filter(f => {
    // Internal/temp files never shown in downloads
    if (f.startsWith('_')) return false;
    if (f.endsWith('.xlsx')) return allowed.has('xlsx');
    if (f.endsWith('.csv')) return allowed.has('csv');
    if (f.endsWith('.json')) return allowed.has('json');
    return true;  // map html, etc.
  });
  if (!filtered.length) return;
  const sec = document.getElementById('dl-section');
  document.getElementById('dl-btns').innerHTML = filtered.map(f =>
    `<a class="dl-btn" href="/download/${encodeURIComponent(f)}" download>${fileIcon(f)} ${f}</a>`
  ).join('');
  sec.style.display = '';
}

// ═══════════════════════════════════════════
//  Table
// ═══════════════════════════════════════════
// Only four client-facing networks are collected/coloured (backend parity).
// Brand chip colours — read from the shared CSS tokens so the same rule works
// in both themes and white initials always keep WCAG AA contrast (the raw
// WhatsApp/Telegram greens were far too light for white text).
const SOCIALS = {vk:'var(--vk)',instagram:'var(--ig)',telegram:'var(--tg)',whatsapp:'var(--wa)'};
const SLABELS = {vk:'VK',instagram:'IG',telegram:'TG',whatsapp:'WA'};
const SNAMES = {vk:'ВКонтакте',instagram:'Instagram',telegram:'Telegram',whatsapp:'WhatsApp'};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[ch]));
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''), window.location.origin);
    return url.protocol === 'https:' ? url.href : '#';
  } catch {
    return '#';
  }
}

// Ячейка «Телефон»: у записи бывает десяток номеров, и comma-joined строка
// растягивала таблицу за горизонт. Нормализуем: каждый номер — своей
// строкой, ячейка ограничена по ширине и высоте (прокрутка внутри).
// Полный список остаётся в title и попадает в Excel/CSV без изменений.
function phoneHTML(row) {
  const raw = String(row.phone || '').trim();
  if (!raw) return '—';
  const list = raw.split(',').map(s => s.trim()).filter(Boolean);
  if (list.length <= 1) return escapeHtml(raw);
  return `<div class="tbl-phone" title="${escapeHtml(raw)}">`
    + list.map(p => `<span>${escapeHtml(p)}</span>`).join('')
    + '</div>';
}

function socialsHTML(row) {
  let h = '';
  const key = escapeHtml(reviewKey(row));
  for (const [p, color] of Object.entries(SOCIALS)) {
    const url = row[p];
    if (url) h += `<a class="social-badge" style="background:${color}" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener noreferrer"`
      + ` title="${escapeHtml(SNAMES[p] || SLABELS[p])}"`
      + ` data-social="${p}" data-key="${key}" onclick="onSocialBadgeClick(event, this)">${SLABELS[p]}</a>`;
  }
  return h || '—';
}

// ── Lead score breakdown ─────────────────────────────────────
// Зеркало yandex_maps_parser/lead_score.py: те же шесть бонусов, чтобы
// подсказка называла именно те критерии, которые сработали у этой записи.
const SCORE_MAX = 90;
const SCORE_AGGREGATORS = /taplink|linktree|linktr\.ee|becons\.ai|illions\.app/i;
// Дорогие категории — копия EXPENSIVE_CATEGORY_KEYWORDS из constants.py.
const SCORE_EXPENSIVE = [
  'стоматолог', 'dent', 'клиник', 'медицин', 'косметолог',
  'недвижим', 'агентств недвижим', 'застройщик', 'риелтор',
  'автосервис', 'автосалон', 'автомойк', 'шиномонтаж', 'автошкол',
  'строитель', 'ремонт квартир', 'отделк', 'кровл', 'окн', 'натяжн',
  'юрист', 'юридическ', 'адвокат', 'бухгалтер', 'аудит',
  'мебел', 'кухн', 'шкаф',
  'туризм', 'турагентств', 'отел', 'гостиниц',
  'банкетн', 'ресторан', 'свадебн', 'event',
];

function scoreNum(value) {
  const v = parseFloat(String(value == null ? '' : value).replace(',', '.'));
  return isFinite(v) ? v : 0;
}

function scoreOwnWebsite(r) {
  const site = String(r.website || r.aggregator_url || '').trim();
  if (!site) return false;
  return !SCORE_AGGREGATORS.test(site);
}

function scoreRating(r) {
  let v = scoreNum(r.rating);
  if (v > 5) v = v / 10;         // некоторые источники отдают 0..50
  return v;
}

// Каждое правило: сколько даёт, когда сработало, и что писать, когда нет.
// `no`: null = строку вообще не показываем (альтернатива уже заняла место).
const SCORE_RULES = [
  { pts: 30, hit: r => !scoreOwnWebsite(r),
    yes: () => 'Нет сайта', no: () => 'Сайт есть' },
  { pts: 20, hit: r => String(r.vk_activity || '').toLowerCase() === 'active',
    yes: () => 'Активный ВК',
    no: r => String(r.vk_activity || '').toLowerCase() === 'semi' ? null : 'ВК не активен' },
  { pts: 10, hit: r => String(r.vk_activity || '').toLowerCase() === 'semi',
    yes: () => 'Полуактивный ВК',
    no: r => String(r.vk_activity || '').toLowerCase() === 'active' ? null : 'Полуактивный ВК — нет' },
  { pts: 15, hit: r => scoreRating(r) >= 4.5,
    yes: r => `Рейтинг ${scoreRating(r)}`,
    no: r => scoreRating(r) > 0 ? `Рейтинг ${scoreRating(r)} < 4.5` : 'Рейтинг — нет данных' },
  { pts: 15, hit: r => scoreNum(r.reviews_count) >= 50,
    yes: r => `Отзывов ${Math.round(scoreNum(r.reviews_count))}`,
    no: r => scoreNum(r.reviews_count) > 0
      ? `Отзывов ${Math.round(scoreNum(r.reviews_count))} < 50` : 'Отзывов — нет данных' },
  { pts: 5, hit: r => !!String(r.phone || '').trim(),
    yes: () => 'Есть телефон', no: () => 'Телефон — не указан' },
  { pts: 5, hit: r => SCORE_EXPENSIVE.some(w => String(r.category || '').toLowerCase().includes(w)),
    yes: () => 'Дорогая категория', no: () => 'Дорогая категория — нет' },
];

// { sum, lines } — сумма сработавших правил и готовые строки подсказки.
function scoreBreakdown(r) {
  const lines = [];
  let sum = 0;
  for (const rule of SCORE_RULES) {
    if (rule.hit(r)) {
      sum += rule.pts;
      lines.push(`✅ ${rule.yes(r)} +${rule.pts}`);
    } else {
      const miss = rule.no(r);
      if (miss) lines.push(`❌ ${miss}`);
    }
  }
  return { sum, lines };
}

// Подсказка отвечает на вопрос «почему именно столько»: только сработавшие
// критерии, остальные — как промахи, внизу сумма.
function scoreWhyText(r, v) {
  const { sum, lines } = scoreBreakdown(r);
  const head = lines.length ? lines.join('\n') : 'Ни один критерий не сработал';
  const tail = sum === v
    ? `Итого: ${v} (макс. ${SCORE_MAX})`
    : `Итого: ${v} (макс. ${SCORE_MAX}) — оценка сохранена при поиске,\nпо текущим данным критерии дают ${sum}`;
  return head + '\n' + '─'.repeat(20) + '\n' + tail;
}

// Lead score badge: green ≥ 70 (горячий), amber ≥ 45, grey below. «—» means
// the score was never computed (file written before this feature).
function scoreHTML(r) {
  const raw = r.lead_score;
  if (raw == null || raw === '') return '<span class="score-na">—</span>';
  const v = +raw || 0;
  const cls = v >= 70 ? 'hot' : v >= 45 ? 'warm' : 'cold';
  return `<span class="score-badge ${cls}" title="${escapeHtml(scoreWhyText(r, v))}">${v}</span>`;
}

function renderTable(data) {
  activeSocialFilters.clear();
  document.querySelectorAll('.sf-tag').forEach(b => b.classList.remove('active'));
  document.getElementById('sf-clear-btn').classList.remove('visible');
  filteredRows = [...data];
  curPage = 1; sortCol = -1;
  document.getElementById('tbl-search').value = '';
  resetSortHeaders();
  // Show the social filter row only when there are results
  // Показ строки и видимость колонки соцсетей — независимы: классы, а не
  // inline display, иначе перебивали бы друг друга.
  document.getElementById('social-filter-row').classList.toggle('empty', !data.length);
  // City tabs + bulk counters follow the freshly loaded data
  renderCityTabs(_lastCities);
  updateBulkStats();
  // Re-derive through filterTable so the optional quality filters
  // (collapse chains / min contact) apply to the final view too.
  filterTable();
}

// Client-side mirror of the server's optional output filters
// ("Объединять филиалы сетей"), so the live table matches what gets
// written to files.
function collapseChainsClient(rows) {
  const norm = n => String(n || '').toLowerCase().replace(/[^a-zа-яё0-9]/gi, '');
  const phoneDigits = p => String(p || '').replace(/\D/g, '');
  const groups = new Map();
  for (const r of rows) {
    const key = (r.city || '') + '|' + norm(r.name);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  const out = [];
  for (const [key, group] of groups) {
    if (group.length < 2) { out.push(...group); continue; }
    // Merge members that share phone digits or a social URL
    const clusters = [];
    for (const r of group) {
      const pd = phoneDigits(r.phone);
      const socials = Object.keys(SOCIALS).filter(k => r[k]).map(k => r[k]);
      let slot = null;
      for (const c of clusters) {
        if (pd && c.some(x => phoneDigits(x.phone) === pd)) { slot = c; break; }
        if (socials.length && c.some(x => Object.keys(SOCIALS).some(k => socials.includes(x[k])))) { slot = c; break; }
      }
      (slot || (clusters.push([]), clusters[clusters.length-1])).push(r);
    }
    for (const c of clusters) {
      if (c.length < 2) { out.push(...c); continue; }
      const base = c.reduce((best, r) =>
        (Object.keys(SOCIALS).filter(k => r[k]).length + (phoneDigits(r.phone)?1:0) >
         Object.keys(SOCIALS).filter(k => best[k]).length + (phoneDigits(best.phone)?1:0)) ? r : best);
      const merged = Object.assign({}, base);
      const phones = [];
      const soc = {};
      for (const r of c) {
        String(r.phone || '').split(',').map(s => s.trim()).forEach(p => { if (p && !phones.includes(p)) phones.push(p); });
        Object.keys(SOCIALS).forEach(k => { if (r[k] && !soc[k]) soc[k] = r[k]; });
      }
      merged.phone = phones.join(', ');
      Object.assign(merged, soc);
      out.push(merged);
    }
  }
  return out;
}

function filterTable() {
  const q = document.getElementById('tbl-search').value.trim().toLocaleLowerCase('ru-RU');
  const SOCIAL_KEYS = Object.keys(SOCIALS);
  let source = allResults;
  // Optional quality filters (mirror of the server-side ones)
  const collapseChains = document.getElementById('f-collapse-chains');
  if (collapseChains && collapseChains.checked) source = collapseChainsClient(source);
  filteredRows = source.filter(r => {
    // City tab ('' = все города)
    if (activeCity && cityOf(r) !== activeCity) return false;
    // «Только непросмотренные»
    if (unviewedOnly && isReviewed(r)) return false;
    // Search every visible/data field
    const searchable = Object.values(r).some(value =>
      String(value ?? '').toLocaleLowerCase('ru-RU').includes(q)
    );
    if (q && !searchable) return false;
    // Social mode filter (form-level toggle)
    if (socialMode === 'with_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]);
      if (!hasAny) return false;
    } else if (socialMode === 'without_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]);
      if (hasAny) return false;
    }
    // Required socials (AND filter): must have ALL checked socials
    if (requiredSocials.size > 0) {
      const hasAll = [...requiredSocials].every(key => r[key]);
      if (!hasAll) return false;
    }
    // Social filter buttons in table — OR logic: row must have at least one
    if (activeSocialFilters.size > 0) {
      const hasSocial = [...activeSocialFilters].some(key => r[key]);
      if (!hasSocial) return false;
    }
    // Lead-score threshold (mirror of the server-side stage-2 filter)
    if (minScoreThreshold() && (+r.lead_score || 0) < minScoreThreshold()) return false;
    return true;
  });
  // «Сначала горячие» — same ordering the processed files get.
  const sortCb = document.getElementById('f-sort-score');
  if (sortCb && sortCb.checked && filteredRows.some(r => r.lead_score != null && r.lead_score !== '')) {
    filteredRows = filteredRows.slice().sort((a, b) => (+b.lead_score || 0) - (+a.lead_score || 0));
  }
  // Список строк собирается заново — прежняя сортировка по клику заголовка
  // к нему больше не относится: без сброса стрелка и порядок расходились бы,
  // и «Массовый обход» повторял бы порядок, которого на экране нет.
  sortCol = -1;
  sortAsc = true;
  curPage = 1;
  renderPage();
  // Смена фильтра соцсети в таблице — подтянуть активный для неё шаблон.
  syncTableTemplatePicker();
}

function minScoreThreshold() {
  const el = document.getElementById('f-min-score');
  return el ? (parseInt(el.value, 10) || 0) : 0;
}

// col 1 — это «#», порядковый номер строки в текущем отображении, а не поле
// данных: сортировать его бессмысленно (номера всё равно идут 1,2,3…), поэтому
// колонка не кликабельна и стрелку не показывает.
const NOSORT_COLS = new Set([0, 1]);

// Перерисовка стирает классы заголовков — «#» должен остаться без стрелок.
function resetSortHeaders() {
  const ths = document.querySelectorAll('#results-table th');
  ths.forEach(t => t.className = '');
  if (ths[1]) ths[1].className = 'nosort';
}

function sortTable(col) {
  if (NOSORT_COLS.has(col)) return;
  const th = document.querySelectorAll('#results-table th')[col];
  if (!th) return;
  if (sortCol === col) { sortAsc = !sortAsc; }
  else { sortCol = col; sortAsc = true; }
  // Score is a number — compare it as one, not as a string.
  if (col === 6) {
    resetSortHeaders();
    document.querySelectorAll('#results-table th')[col].className = sortAsc ? 'asc' : 'desc';
    filteredRows.sort((a, b) => {
      const va = +a.lead_score || 0, vb = +b.lead_score || 0;
      return sortAsc ? va - vb : vb - va;
    });
    renderPage();
    return;
  }
  resetSortHeaders();
  th.className = sortAsc ? 'asc' : 'desc';
  // col 0 = ✓ и col 1 = # — не сортируются, col 2 = name, ...
  const keys = ['', '', 'name', 'category', 'address', 'phone', 'lead_score'];
  const key = keys[col];
  filteredRows.sort((a, b) => {
    const va = a[key] || '', vb = b[key] || '';
    return sortAsc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
  });
  renderPage();
}

function renderPage() {
  const total = filteredRows.length;
  const pages = Math.ceil(total / PAGE_SIZE) || 1;
  if (curPage > pages) curPage = pages;
  const start = (curPage - 1) * PAGE_SIZE;
  const slice = filteredRows.slice(start, start + PAGE_SIZE);

  document.getElementById('tbl-count').textContent = total ? `${total} записей${currentFileNote}` : '';
  const exportWrap = document.getElementById('export-sel-wrap');
  if (exportWrap) exportWrap.style.display = total ? 'flex' : 'none';

  const tbody = document.getElementById('tbl-body');
  if (!total) {
    tbody.innerHTML = '<tr><td colspan="9" class="no-data">Ничего не найдено</td></tr>';
    document.getElementById('pager').style.display = 'none';
    return;
  }

  tbody.innerHTML = slice.map((r, i) => {
    // Same key as the backend _review_key(): card URL, else name|city|address.
    const rawReviewUrl = reviewKey(r);
    const reviewUrl = escapeHtml(rawReviewUrl);
    const isRev = isReviewed(r);
    return `
    <tr class="${isRev ? 'is-reviewed' : ''}">
      <td style="text-align:center"><input type="checkbox" class="rev-cb"
        ${isRev ? 'checked' : ''} ${!rawReviewUrl ? 'disabled' : ''}
        data-review-url="${reviewUrl}"
        onchange="toggleReviewed(this.dataset.reviewUrl, this)"></td>
      <td>${start + i + 1}</td>
      <td><a class="tbl-link" href="${escapeHtml(safeUrl(r.yandex_maps_url || r.twogis_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.name || '—')}</a></td>
      <td class="tbl-cat">${escapeHtml(r.category || '—')}</td>
      <td>${escapeHtml(r.address || '—')}</td>
      <td>${phoneHTML(r)}</td>
      <td>${scoreHTML(r)}</td>
      <td>${socialsHTML(r)}</td>
    </tr>`;
  }).join('');

  const pager = document.getElementById('pager');
  pager.style.display = pages > 1 ? 'flex' : 'none';
  document.getElementById('pg-info').textContent = `Стр. ${curPage} / ${pages}`;
  document.getElementById('pg-prev').disabled = curPage <= 1;
  document.getElementById('pg-next').disabled = curPage >= pages;
}

function changePage(d) { curPage += d; renderPage(); }

// ═══════════════════════════════════════════
//  Reviewed state
// ═══════════════════════════════════════════
let reviewedState = {};

function loadReviewed() {
  fetch('/reviewed').then(r => r.json()).then(data => {
    reviewedState = data || {};
    if (filteredRows.length) renderPage();
    updateBulkStats();          // «Осталось непросмотренных» зависит от отметок
  }).catch(() => {});
}

function toggleReviewed(url, cb) {
  if (!url) return;
  const checked = cb.checked;
  if (checked) reviewedState[url] = true; else delete reviewedState[url];
  const row = cb.closest('tr');
  if (row) row.classList.toggle('is-reviewed', checked);
  fetch('/reviewed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, reviewed: checked})
  }).catch(() => {});
  markReviewedDirty();
  updateBulkStats();
}

// ══════════════════════════════════════════════════════════════
//  Results tab: sub-tabs, city tabs, bulk outreach, file browser
// ══════════════════════════════════════════════════════════════
const SUBTAB_KEY    = 'yp_results_subtab';   // current | history
const CITY_TAB_KEY  = 'yp_results_city_tab';  // '' = все города
const BULK_OPEN_KEY = 'yp_bulk_open';         // 1 | 0 — панель развёрнута
const SCOPE_KEY     = 'yp_results_scope';     // current | all (текущий поиск | вся папка)
const BULK_MAX_TABS = 50;                     // предел вкладок за один клик

const BULK_SOCIALS = ['vk', 'telegram', 'whatsapp', 'instagram'];

let activeCity = '';            // выбранная вкладка города ('' = все)
let _lastCities = [];           // города текущего вида (от /results-view)
let unviewedOnly = false;       // фильтр «только непросмотренные»
let currentFileNote = '';       // «· файл: …» когда таблица показывает один файл
let currentFile = '';           // rel-путь файла, открытого из «Истории файлов»
let bulkBusy = false;
let bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
let filesLoaded = false;
let filesData = { raw: [], processed: [], archive: [] };
let filesFilter = '';
let filesSearchTimer = null;

// Mirrors the backend _review_key() — keep both in sync.
function reviewKey(r) {
  if (!r) return '';
  const y = String(r.yandex_maps_url || '').trim();
  if (y) return y;
  const t = String(r.twogis_url || '').trim();
  if (t) return t;
  const name = String(r.name || '').trim();
  const addr = String(r.address || '').trim();
  if (!name && !addr) return '';
  return 'n:' + [name, String(r.city || '').trim(), addr].join('|');
}

function isReviewed(r) {
  const k = reviewKey(r);
  return !!(k && reviewedState[k]);
}

// Перерисовать таблицу и счётчики после изменения отметок
// (нужно и когда включён фильтр «только непросмотренные» —
//  помеченные строки должны из него исчезнуть).
function refreshReviewedUI() {
  updateBulkStats();
  if (unviewedOnly) { curPage = 1; filterTable(); }
  else if (filteredRows.length) renderPage();
}

function safeSocialUrl(u) {
  const s = String(u || '').trim();
  return /^https?:\/\//i.test(s) ? s : '';
}

// ── Массовое открытие вкладок ────────────────────────────────
// window.open ПОСЛЕ await теряет user-activation, поэтому браузер отдавал
// только первую вкладку из пяти. Схема, которая работает: пустые вкладки
// открываются СИНХРОННО прямо в обработчике клика, а URL-ы из ответа сервера
// подставляются в них уже потом.
function openBlankTabs(n) {
  const wins = [];
  for (let i = 0; i < n; i++) {
    let w = null;
    try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    wins.push(w || null);          // null = вкладку заблокировал браузер
  }
  return wins;
}

// Направить уже открытую вкладку на URL профиля. false = вкладка потеряна
// (заблокирована или закрыта), тогда показываем fallback «Скопировать ссылки».
function fillTab(win, url) {
  if (!win) return false;
  try {
    win.location.href = url;
    try { win.opener = null; } catch (e) { /* cross-origin после навигации */ }
    return true;
  } catch (e) {
    return false;
  }
}

function closeTab(win) {
  if (!win) return;
  try { win.close(); } catch (e) { /* уже закрыта */ }
}

function clampInt(v, lo, hi) {
  const n = parseInt(v, 10);
  if (isNaN(n)) return lo;
  return Math.max(lo, Math.min(hi, n));
}

function pluralNum(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

function pluralRecords(n) { return pluralNum(n, 'запись', 'записи', 'записей'); }
function pluralProfiles(n) { return pluralNum(n, 'профиль', 'профиля', 'профилей'); }
function pluralFiles(n) { return pluralNum(n, 'файл', 'файла', 'файлов'); }

function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' Б';
  if (n < 1024 * 1024) return (n / 1024).toFixed(n / 1024 < 10 ? 1 : 0) + ' КБ';
  return (n / 1048576).toFixed(1) + ' МБ';
}

function basenameOf(p) { return String(p || '').split('/').pop(); }

function postJSON(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(async r => {
    let data = {};
    try { data = await r.json(); } catch (e) { data = {}; }
    if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
    return data;
  });
}

// ── Sub-tabs: «Текущий результат» / «История файлов» ─────────
function setResultsSubTab(name) {
  const showCurrent = name !== 'history';
  document.querySelectorAll('#results-subtabs .subt-tab').forEach(b =>
    b.classList.toggle('active', (b.dataset.sub === 'history') === !showCurrent));
  const rc = document.getElementById('rs-current');
  const rh = document.getElementById('rs-history');
  if (rc) rc.hidden = !showCurrent;
  if (rh) rh.hidden = showCurrent;
  try { localStorage.setItem(SUBTAB_KEY, showCurrent ? 'current' : 'history'); } catch (e) {}
  if (!showCurrent) {
    // Уходим из таблицы — самый удобный момент дописать отметки в файлы.
    autoPersistReviewed();
    if (!filesLoaded) loadFilesPanel();
    else renderFiles();
  }
}

// ── City tabs ───────────────────────────────────────────────
function cityOf(r) { return String((r && r.city) || '').trim() || 'Без города'; }

function bulkScopeRows() {
  if (!activeCity) return allResults;
  return allResults.filter(r => cityOf(r) === activeCity);
}

function renderCityTabs(cities) {
  const box = document.getElementById('city-tabs');
  if (!box) return;
  const list = Array.isArray(cities) ? cities : [];
  if (list.length < 2) {            // один город — вкладки не нужны
    box.innerHTML = '';
    box.hidden = true;
    activeCity = '';
    return;
  }
  if (activeCity && !list.some(c => c.city === activeCity)) activeCity = '';
  box.hidden = false;
  const total = list.reduce((s, c) => s + (Number(c.count) || 0), 0);
  const tabs = [
    `<button class="city-tab${activeCity ? '' : ' active'}" data-city="" onclick="setCityTab('')">Все <span class="city-count">(${total})</span></button>`,
  ].concat(list.map(c =>
    `<button class="city-tab${c.city === activeCity ? ' active' : ''}" data-city="${escapeHtml(c.city)}" onclick="setCityTab(this.dataset.city)">${escapeHtml(c.city)} <span class="city-count">(${c.count})</span></button>`
  ));
  box.innerHTML = tabs.join('');
}

function setCityTab(city) {
  activeCity = String(city || '');
  try { localStorage.setItem(CITY_TAB_KEY, activeCity); } catch (e) {}
  document.querySelectorAll('#city-tabs .city-tab').forEach(b =>
    b.classList.toggle('active', (b.dataset.city || '') === activeCity));
  curPage = 1;
  filterTable();
  updateBulkStats();
}

// ── «Только непросмотренные» ─────────────────────────────────
function toggleUnviewedOnly() {
  unviewedOnly = !unviewedOnly;
  const b = document.getElementById('btn-unviewed');
  if (b) {
    b.classList.toggle('active', unviewedOnly);
    b.innerHTML = (unviewedOnly ? UI_ICONS.checkSquare : UI_ICONS.square) + 'Непросмотренные';
  }
  curPage = 1;
  filterTable();
}

// ── Bulk outreach panel ─────────────────────────────────────
function toggleBulkPanel() {
  const body = document.getElementById('bulk-body');
  const arrow = document.getElementById('bulk-collapse');
  if (!body) return;
  const open = body.hidden;
  body.hidden = !open;
  if (arrow) arrow.textContent = open ? '▾' : '▸';
  try { localStorage.setItem(BULK_OPEN_KEY, open ? '1' : '0'); } catch (e) {}
}

function setBulkCount(n) {
  const inp = document.getElementById('bulk-count');
  if (inp) inp.value = clampInt(n, 1, BULK_MAX_TABS);
  updateBulkStats();
}

// Сколько всего непросмотренных в текущем городе и сколько из них
// доступны по каждой соцсети (skip_viewed учитывается в by_social).
function bulkScopeStats() {
  const rows = bulkScopeRows();
  const skip = !!(document.getElementById('bulk-skip-viewed') || {}).checked;
  const stats = { unviewed: 0, with_social: {}, by_social: {} };
  BULK_SOCIALS.forEach(s => { stats.with_social[s] = 0; stats.by_social[s] = 0; });
  for (const r of rows) {
    const rev = isReviewed(r);
    if (!rev) stats.unviewed++;
    for (const s of BULK_SOCIALS) {
      if (!safeSocialUrl(r[s])) continue;
      stats.with_social[s]++;
      if (!(skip && rev)) stats.by_social[s]++;
    }
  }
  return stats;
}

// Сколько профилей выбранной соцсети ещё не просмотрено — ровно это число
// ограничивает следующий клик. Кнопка активна, пока оно больше нуля.
function bulkOpenable() {
  const sel = document.getElementById('bulk-social');
  const stats = bulkScopeStats();
  return stats.by_social[(sel && sel.value) || 'vk'] || 0;
}

// Сколько вкладок откроет клик: сколько запросили, но не больше остатка
// непросмотренных и жёсткого лимита BULK_MAX_TABS.
function bulkWillOpen(requested) {
  return Math.max(0, Math.min(clampInt(requested, 1, BULK_MAX_TABS), bulkOpenable()));
}

function updateBulkStats() {
  const panel = document.getElementById('bulk-panel');
  if (!panel) return;
  const stats = bulkScopeStats();
  const sel = document.getElementById('bulk-social');
  const social = (sel && sel.value) || 'vk';

  const cnt = document.getElementById('unviewed-count');
  if (cnt) cnt.textContent = String(stats.unviewed);
  const note = document.getElementById('bulk-stats-note');
  if (note) note.textContent = ` · с ${SNAMES[social] || social}: ${stats.by_social[social] || 0}`;

  const order = document.getElementById('bulk-order-note');
  if (order) order.textContent = bulkOrderLabel();

  if (sel) {
    [...sel.options].forEach(o => {
      const base = o.dataset.base || o.textContent;
      o.dataset.base = base;
      o.textContent = `${base} — ${stats.by_social[o.value] || 0}`;
    });
  }

  const inp = document.getElementById('bulk-count');
  const count = clampInt(inp ? inp.value : 5, 1, BULK_MAX_TABS);
  document.querySelectorAll('#bulk-panel .bulk-preset').forEach(b =>
    b.classList.toggle('active', Number(b.dataset.count) === count));

  // Выбор шаблона следует за выбранной соцсетью.
  syncTemplateSelects();

  const btn = document.getElementById('bulk-open-btn');
  if (btn) {
    const openable = stats.by_social[social] || 0;
    const willOpen = Math.min(count, openable, BULK_MAX_TABS);
    if (bulkBusy) {
      btn.disabled = true;
      btn.innerHTML = UI_ICONS.busy + 'Открываем…';
    } else if (!openable) {
      // Обход закончен: непросмотренных с этой соцсетью больше нет.
      btn.disabled = true;
      btn.innerHTML = UI_ICONS.check + 'Все просмотрены';
    } else {
      // Кнопка обещает ровно то, что откроется этим кликом.
      btn.disabled = false;
      btn.innerHTML = UI_ICONS.external + `Открыть ${willOpen} ${pluralProfiles(willOpen)}`;
    }
  }
  renderBulkProgress();
}

function renderBulkProgress() {
  const box = document.getElementById('bulk-progress');
  if (!box) return;
  if (!bulkState.opened && !bulkState.blocked) { box.hidden = true; return; }
  box.hidden = false;
  // Знаменатель — сколько всего оставалось непросмотренным с этой соцсетью
  // плюс уже открытое за сессию: процент не зависит от размера пачки.
  const total = bulkState.opened + bulkState.blocked + bulkOpenable();
  const pct = total ? Math.min(100, Math.round((bulkState.opened / total) * 100)) : 0;
  const fill = document.getElementById('bulk-progress-fill');
  if (fill) fill.style.width = pct + '%';
  const txt = document.getElementById('bulk-progress-txt');
  if (txt) {
    txt.textContent = `Открыто ${bulkState.opened} из ${total}`
      + (bulkState.blocked ? ` · заблокировано ${bulkState.blocked}` : '');
  }
}

function resetBulkProgress() {
  bulkState = { social: bulkState.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
  hideBulkWarn();
  updateBulkStats();
}

function showBulkWarn(msg) {
  const box = document.getElementById('bulk-warn');
  if (!box) return;
  box.hidden = false;
  box.innerHTML = msg;
}

function hideBulkWarn() {
  const box = document.getElementById('bulk-warn');
  if (box) { box.hidden = true; box.innerHTML = ''; }
}

// Порядок обхода = порядок строк в таблице. По умолчанию таблица отсортирована
// по оценке лида («Сначала горячие»), а клик по заголовку сортирует по своей
// колонке: раньше обход шёл в порядке файла и вкладки открывались вразброс
// относительно того, что видит пользователь.
function bulkSortSpec() {
  if (sortCol >= 2) return {col: sortCol, asc: !!sortAsc};
  const cb = document.getElementById('f-sort-score');
  return (cb && cb.checked) ? {col: 6, asc: false} : {col: null, asc: true};
}

function bulkOrderLabel() {
  const spec = bulkSortSpec();
  if (spec.col === 6) return 'Порядок: сначала горячие (по оценке)';
  if (spec.col) return 'Порядок: как в таблице (по колонке)';
  return 'Порядок: как в файле';
}

function bulkParams() {
  const sel = document.getElementById('bulk-social');
  const sort = bulkSortSpec();
  return {
    view: _resultsView,
    scope: _resultsScope,       // обход идёт по тому же срезу, что и таблица
    file: currentFile,          // обход идёт по открытому файлу, если он открыт
    city: activeCity,
    social: (sel && sel.value) || 'vk',
    skip_viewed: !!(document.getElementById('bulk-skip-viewed') || {}).checked,
    mark_viewed: !!(document.getElementById('bulk-mark-viewed') || {}).checked,
    sort_col: sort.col,
    sort_asc: sort.asc,
  };
}

async function bulkOpenBatch() {
  if (bulkBusy) return;
  const p = bulkParams();
  const inp = document.getElementById('bulk-count');
  const requested = clampInt(inp ? inp.value : 5, 1, BULK_MAX_TABS);

  // Другая соцсеть — начинаем сессию обхода заново.
  if (bulkState.social !== p.social) {
    bulkState = { social: p.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set(), texts: new Map(), copiedTexts: new Set() };
    hideBulkWarn();
  }

  // Пустые вкладки открываются СИНХРОННО, до запроса к серверу: после await
  // браузер уже не считает их частью клика и блокирует всё, кроме первой.
  const wanted = Math.min(requested, BULK_MAX_TABS);
  const tabs = openBlankTabs(wanted);

  bulkBusy = true;
  updateBulkStats();
  try {
    // Шаблон для этой соцсети — сервер вернёт готовый текст на каждую запись.
    // В random-режиме шлём id набора: сервер сам выбирает per-record.
    const randomMode = templateModes[p.social] === 'random'
      && (randomTemplateIds[p.social] || []).length > 0;
    const bulkTpl = randomMode ? null : getActiveTemplateFor(p.social);
    const data = await postJSON('/bulk/urls', {
      view: p.view, scope: p.scope, file: p.file, city: p.city, social: p.social,
      count: wanted, skip_viewed: p.skip_viewed, exclude_keys: [...bulkState.keys],
      // Порядок вкладок — как порядок строк в таблице.
      sort_col: p.sort_col, sort_asc: p.sort_asc,
      template: bulkTpl ? bulkTpl.text : '',
      show_missing_as_var: showMissingAsVar,
      template_ids: randomMode ? randomTemplateIds[p.social] : [],
      tpl_avoid_repeats: avoidRepeats,
    });
    const list = (data.urls || []).filter(i => i && i.url);
    if (!list.length) {
      // Очередь пуста — предварительно открытые вкладки закрываем, чтобы
      // у пользователя не остались пустые.
      tabs.forEach(closeTab);
      showToast('Нет непросмотренных компаний с этой соцсетью', 'warning');
      return;
    }

    // Заполняем уже открытые вкладки и закрываем лишние (сервер мог отдать
    // меньше, чем мы запросили, если очередь закончилась).
    const openedItems = [];
    let blocked = 0;
    for (let i = 0; i < tabs.length; i++) {
      const item = list[i];
      if (!item) { closeTab(tabs[i]); continue; }
      if (fillTab(tabs[i], item.url)) openedItems.push(item); else blocked++;
    }

    if (openedItems.length) {
      bulkState.opened += openedItems.length;
      openedItems.forEach(i => { if (i.key) bulkState.keys.add(i.key); });
      // Готовые тексты кладём в очередь: браузер не даёт копировать при
      // переключении внешней вкладки, поэтому копируем по кнопке.
      if (bulkTpl || randomMode) {
        if (!(bulkState.texts instanceof Map)) bulkState.texts = new Map();
        openedItems.forEach(i => {
          if (i.key) bulkState.texts.set(i.key, {name: i.name || '', text: i.text || '', url: i.url, tpl_name: i.tpl_name || ''});
        });
        renderBulkQueue();
      }
      if (p.mark_viewed) await markReviewedBatch(openedItems.map(i => i.key), true);
    }
    bulkState.blocked += blocked;
    if (blocked) {
      showBulkWarn(`⚠ Открыто ${openedItems.length} из ${list.length}: браузер заблокировал ${blocked} ${pluralProfiles(blocked)}. Разрешите всплывающие окна для этого сайта — или нажмите «📋 Скопировать ссылки» и откройте их вручную.`);
      showToast(`Открыто ${openedItems.length} из ${list.length}. Разрешите всплывающие окна`, 'warning');
    } else {
      hideBulkWarn();
      showToast(`Открыто ${openedItems.length} ${pluralProfiles(openedItems.length)}`, 'success');
    }
  } catch (e) {
    // Запрос упал — открытые пустые вкладки не должны висеть у пользователя.
    tabs.forEach(closeTab);
    showToast('Ошибка обхода: ' + e.message, 'error');
  } finally {
    bulkBusy = false;
    updateBulkStats();
    if (allResults.length) refreshReviewedUI();
  }
}

async function markReviewedBatch(keys, val) {
  const clean = [...new Set((keys || []).filter(Boolean))];
  if (!clean.length) return;
  const before = {};
  clean.forEach(k => {
    before[k] = !!reviewedState[k];
    // снятая отметка = ключа нет (не false), чтобы состояние совпадало с _reviewed.json
    if (val) reviewedState[k] = true; else delete reviewedState[k];
  });
  try {
    await postJSON('/reviewed/batch', { keys: clean, reviewed: val });
  } catch (e) {
    clean.forEach(k => { if (before[k]) reviewedState[k] = true; else delete reviewedState[k]; });
    showToast('Не удалось сохранить отметки: ' + e.message, 'error');
    refreshReviewedUI();
    return;
  }
  // Сервер отметки принял — теперь их надо дописать в xlsx.
  markReviewedDirty();
  refreshReviewedUI();
}

// ══════════════════════════════════════════════════════════════
//  Автосохранение отметок «Просмотрено»
// ══════════════════════════════════════════════════════════════
// Отметки сразу уходят в _reviewed.json (таблица и обход их видят), но в
// xlsx их надо переписать отдельным запросом. Раньше это делала только
// кнопка, о которой все забывали — и отметки не доживали до следующей
// сессии. Теперь пишем сами: через 5 с после последнего клика, при уходе со
// страницы, при переключении на «Историю файлов» и перед экспортом.
const REVIEWED_AUTOSAVE_MS = 5000;
let reviewedDirty = false;      // есть отметки, ещё не записанные в xlsx
let reviewedSaveError = false;  // последняя запись не удалась
let reviewedSaveTimer = null;
let reviewedPersistBusy = false;

function markReviewedDirty() {
  reviewedDirty = true;
  reviewedSaveError = false;
  updateReviewedSaveStatus();
  if (reviewedSaveTimer) clearTimeout(reviewedSaveTimer);
  reviewedSaveTimer = setTimeout(() => {
    reviewedSaveTimer = null;
    autoPersistReviewed();
  }, REVIEWED_AUTOSAVE_MS);
}

function updateReviewedSaveStatus() {
  const el = document.getElementById('reviewed-save-status');
  if (!el) return;
  let cls, txt;
  if (reviewedPersistBusy) {
    cls = 'busy'; txt = '⏳ Записываю отметки в файлы…';
  } else if (reviewedSaveError) {
    cls = 'err'; txt = '⚠ Отметки не записаны — нажмите «Сохранить сейчас»';
  } else if (reviewedDirty) {
    cls = 'dirty'; txt = '⏳ Есть несохранённые отметки — запишутся сами через пару секунд';
  } else {
    cls = 'ok'; txt = '✅ Все отметки сохранены';
  }
  el.textContent = txt;
  el.className = 'rev-save-status ' + cls;
}

// force = сохранить даже без изменений (ручная кнопка). Возвращает ответ
// сервера или null, если запись не удалась.
async function autoPersistReviewed(force) {
  if (!force && !reviewedDirty) return null;
  if (reviewedPersistBusy) return null;
  reviewedPersistBusy = true;
  reviewedSaveError = false;
  updateReviewedSaveStatus();
  try {
    const d = await postJSON('/reviewed/persist', { view: _resultsView, scope: _resultsScope });
    reviewedDirty = false;
    reviewedSaveError = false;
    return d;
  } catch (e) {
    reviewedSaveError = true;
    return null;
  } finally {
    reviewedPersistBusy = false;
    updateReviewedSaveStatus();
  }
}

// Закрытие вкладки: sendBeacon отдаёт запрос даже когда страница умирает.
function persistReviewedOnLeave() {
  if (!reviewedDirty) return;
  const nav = (typeof navigator !== 'undefined') ? navigator : null;
  if (!nav || typeof nav.sendBeacon !== 'function') return;
  try {
    const body = new Blob(
      [JSON.stringify({ view: _resultsView, scope: _resultsScope })],
      { type: 'application/json' },
    );
    nav.sendBeacon('/reviewed/persist', body);
    reviewedDirty = false;
  } catch (e) { /* отметки останутся в _reviewed.json — потеряем только колонку */ }
}

async function bulkCopyLinks() {
  const p = bulkParams();
  const inp = document.getElementById('bulk-count');
  const count = clampInt(inp ? inp.value : 10, 1, 50);
  try {
    const data = await postJSON('/bulk/urls', {
      view: p.view, scope: p.scope, file: p.file, city: p.city, social: p.social,
      count, skip_viewed: p.skip_viewed, exclude_keys: [...bulkState.keys, ...bulkState.copied],
    });
    const list = data.urls || [];
    if (!list.length) { showToast('Нет непросмотренных компаний с этой соцсетью', 'warning'); return; }
    list.forEach(i => { if (i.key) bulkState.copied.add(i.key); });
    showLinksModal(list, SNAMES[p.social] || p.social);
  } catch (e) {
    showToast('Ошибка: ' + e.message, 'error');
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { /* fall through to execCommand */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function showLinksModal(items, label) {
  const links = (items || []).map(i => i.url).filter(Boolean);
  const keys = (items || []).map(i => i.key).filter(Boolean);
  const overlay = document.createElement('div');
  overlay.className = 'ui-modal-overlay';
  const text = links.join('\n');
  overlay.innerHTML = `
    <div class="ui-modal links-modal">
      <h3>${links.length} ${pluralNum(links.length, 'ссылка', 'ссылки', 'ссылок')} — ${escapeHtml(label)}</h3>
      <p>Список можно вставить в заметки или открывать по одной. Когда свяжетесь с этими компаниями — поставьте им отметки кнопкой ниже, и они уйдут из очереди обхода.</p>
      <textarea readonly rows="10">${escapeHtml(text)}</textarea>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel">Закрыть</button>
        <button type="button" class="m-mark">${UI_ICONS.check}Пометить просмотренными (${keys.length})</button>
        <button type="button" class="m-ok neutral">${UI_ICONS.copy}Скопировать все</button>
      </div>
    </div>`;
  const done = () => overlay.remove();
  overlay.querySelector('.m-cancel').onclick = done;
  overlay.querySelector('.m-mark').onclick = async () => {
    if (!keys.length) { showToast('Нет записей для отметки', 'warning'); return; }
    await markReviewedBatch(keys, true);
    keys.forEach(k => bulkState.keys.add(k));
    showToast(`Отмечено просмотренными: ${keys.length}`, 'success');
    done();
  };
  overlay.querySelector('.m-ok').onclick = async () => {
    const ok = await copyText(text);
    showToast(ok ? 'Ссылки скопированы в буфер обмена' : 'Не удалось скопировать — выделите текст вручную', ok ? 'success' : 'warning');
  };
  overlay.addEventListener('click', e => { if (e.target === overlay) done(); });
  document.body.appendChild(overlay);
  const ta = overlay.querySelector('textarea');
  if (ta) { ta.focus(); ta.select(); }
}

// Ручная кнопка «Сохранить сейчас» — тот же путь, что и автосохранение,
// только сразу и с отчётом, сколько ячеек записали.
async function persistReviewedMarks() {
  const btn = document.getElementById('bulk-persist-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = UI_ICONS.busy + 'Записываю…'; }
  try {
    const d = await autoPersistReviewed(true);
    if (!d) { showToast('Не удалось записать отметки — попробуйте ещё раз', 'error'); return; }
    const extra = d.skipped ? ` · без колонки «Просмотрено»: ${d.skipped}` : '';
    const scope = { raw: 'сырые (RAW)', processed: 'обработанные', all: 'RAW + обработанные' }[_resultsView] || _resultsView;
    showToast(`Отметки записаны в ${scope}: ${d.updated} ячеек, ${d.files} ${pluralFiles(d.files)}${extra}`, 'success');
    if (d.errors && d.errors.length) {
      showToast(`Не удалось записать ${d.errors.length} ${pluralFiles(d.errors.length)}: ${d.errors[0].file}`, 'error');
    }
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.save + 'Сохранить сейчас'; }
  }
}

// ── File browser («История файлов») ─────────────────────────
function onFilesSearchInput() {
  clearTimeout(filesSearchTimer);
  filesSearchTimer = setTimeout(() => {
    const el = document.getElementById('files-search');
    filesFilter = (el ? el.value : '').trim().toLowerCase();
    renderFiles();
  }, 300);
}

async function loadFilesPanel(force) {
  if (filesLoaded && !force) { renderFiles(); return; }
  const box = document.getElementById('history-raw');
  if (box && !filesLoaded) box.innerHTML = '<div class="no-data">Загрузка…</div>';
  try {
    const d = await fetch('/files/list').then(r => r.json());
    filesData = { raw: d.raw || [], processed: d.processed || [], archive: d.archive || [] };
    filesLoaded = true;
    // Drop selections for files that no longer exist anywhere.
    const alive = new Set([...filesData.raw, ...filesData.processed, ...filesData.archive].map(it => it.path));
    _selectedFiles = new Set([..._selectedFiles].filter(p => alive.has(p)));
    updateBulkDeleteBtn();
    renderFiles();
  } catch (e) {
    ['raw', 'processed', 'archive'].forEach(s => {
      const el = document.getElementById('history-' + s);
      if (el) el.innerHTML = '<div class="no-data">Не удалось загрузить список файлов. Нажмите «Обновить».</div>';
    });
    showToast('Ошибка загрузки списка файлов', 'error');
  }
}

// File-card actions. Inline SVGs with stroke="currentColor" instead of
// emoji: the emoji 🗑 renders as a monochrome glyph that ignores `color`,
// so it vanished on the dark card. SVG inherits the themed colour.
const FILE_ACT_ICONS = {
  open:     '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-6"/><path d="M20 20V8"/></svg>',
  download: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v11"/><path d="M7.5 10 12 14.5 16.5 10"/><path d="M4 20h16"/></svg>',
  archive:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7h18l-1.6-3.2H4.6L3 7z"/><path d="M5 7v13h14V7"/><path d="M10 12h4"/></svg>',
  restore:  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6 5 10l4 4"/><path d="M5 10h9a4.5 4.5 0 0 1 0 9h-3"/></svg>',
  delete:   '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16"/><path d="M9.5 7V4h5v3"/><path d="M6.5 7 7.5 20h9l1-13"/><path d="M10.5 11v5.5"/><path d="M13.5 11v5.5"/></svg>',
};

function fileCardHTML(section, it) {
  // Значок перед текстом — SVG, поэтому сообщение экранируем построчно, а не
  // оборачиваем целиком (escapeHtml съел бы саму разметку значка).
  const meta = it.error
    ? UI_ICONS.warn + escapeHtml(it.error)
    : escapeHtml(`${it.records} ${pluralRecords(it.records)} • ${fmtBytes(it.size)} • ${it.modified}`);
  const icon = FILE_TYPE_ICONS[it.ext] || FILE_TYPE_ICONS.dir;
  // Архивные файлы не архивируем повторно, но даём вернуть на место.
  const archiveBtn = section === 'archive'
    ? `<button class="file-btn" data-act="restore" data-path="${escapeHtml(it.path)}" title="Вернуть файл в рабочую папку">${FILE_ACT_ICONS.restore}</button>`
    : `<button class="file-btn" data-act="archive" data-path="${escapeHtml(it.path)}" title="Убрать в архив (файл можно вернуть)">${FILE_ACT_ICONS.archive}</button>`;
  return `
    <div class="file-card">
      <div class="file-info">
        <input type="checkbox" class="file-cb" data-path="${escapeHtml(it.path)}"
          ${_selectedFiles.has(it.path) ? 'checked' : ''}
          onchange="onFileSelect(this)" title="Выбрать для массового удаления">
        <span class="file-icon">${icon}</span>
        <div class="file-text">
          <div class="file-name" title="${escapeHtml(it.path)}">${escapeHtml(it.name)}</div>
          <div class="file-meta">${meta}</div>
        </div>
      </div>
      <div class="file-actions">
        <button class="file-btn" data-act="open" data-path="${escapeHtml(it.path)}" title="Открыть в таблице">${FILE_ACT_ICONS.open}</button>
        <button class="file-btn" data-act="download" data-path="${escapeHtml(it.path)}" title="Скачать">${FILE_ACT_ICONS.download}</button>
        ${archiveBtn}
        <button class="file-btn danger" data-act="delete" data-path="${escapeHtml(it.path)}" title="Удалить навсегда">${FILE_ACT_ICONS.delete}</button>
      </div>
    </div>`;
}

// ── Bulk selection («Удалить выбранные» / «В архив» / «Отменить выбор») ──
let _selectedFiles = new Set();

function onFileSelect(cb) {
  if (cb.checked) _selectedFiles.add(cb.dataset.path);
  else _selectedFiles.delete(cb.dataset.path);
  updateBulkDeleteBtn();
}

// Three buttons follow one counter: the destructive delete, the reversible
// archive and «снять выделение». They appear together with 1+ ticked file.
function updateBulkDeleteBtn() {
  const n = _selectedFiles.size;
  const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
  set('files-bulk-n', n);
  set('files-bulk-arch-n', n);
  ['btn-files-bulk-delete', 'btn-files-bulk-archive', 'btn-files-bulk-cancel'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.hidden = n === 0;
  });
}

// ✕ Отменить выбор — untick everything at once (one click instead of N).
function clearFileSelection() {
  _selectedFiles.clear();
  const boxes = document.querySelectorAll ? document.querySelectorAll('.file-cb') : [];
  for (let i = 0; i < boxes.length; i++) boxes[i].checked = false;
  updateBulkDeleteBtn();
  showToast('Выбор снят', 'info');
}

// 📦 В архив (N) — same batch endpoint as delete, action="archive"; the file
// moves to <результаты>/_archive/ГГГГ-ММ-ДД/ and can be restored (↩).
async function bulkArchiveSelected() {
  const paths = [..._selectedFiles];
  if (!paths.length) return;
  try {
    const d = await postJSON('/files/action', { paths, action: 'archive' });
    const moved = (d.moved || []).length;
    const errs = (d.errors || []).length;
    showToast(`В архив: ${moved}${errs ? ` · ошибок: ${errs}` : ''}`, errs ? 'warn' : 'success');
    if (errs) showToast(`Не удалось архивировать: ${(d.errors[0] || {}).error || 'ошибка'}`, 'error');
    // Archived files leave RAW/PROCESSED → the tick set has to be dropped.
    _selectedFiles.clear();
    updateBulkDeleteBtn();
    loadFilesPanel(true);
    setResultsView(_resultsView);
  } catch (e) {
    showToast('Ошибка архивации: ' + e.message, 'error');
  }
}

async function bulkDeleteSelected() {
  const paths = [..._selectedFiles];
  if (!paths.length) return;
  const ok = await uiConfirm(
    `Будет безвозвратно удалено файлов: ${paths.length}. Отменить это нельзя.`,
    'Удалить выбранные файлы?',
    `Удалить (${paths.length})`
  );
  if (!ok) return;
  try {
    const d = await postJSON('/files/action', { paths, action: 'delete', confirm: true });
    const errs = (d.errors || []).length;
    showToast(`Удалено: ${(d.deleted || []).length}${errs ? ` · ошибок: ${errs}` : ''}`, errs ? 'warn' : 'success');
    _selectedFiles.clear();
    updateBulkDeleteBtn();
    loadFilesPanel(true);
    setResultsView(_resultsView);   // открытый файл мог удалиться
  } catch (e) {
    showToast('Ошибка массового удаления: ' + e.message, 'error');
  }
}

function renderFiles() {
  const nRaw = (filesData.raw || []).length;
  const nProc = (filesData.processed || []).length;
  const nArch = (filesData.archive || []).length;
  const total = nRaw + nProc + nArch;
  const cnt = document.getElementById('files-count');
  if (cnt) {
    // Colored badges instead of one run-on line: the three sections are
    // actually distinguishable at a glance.
    cnt.innerHTML = total
      ? `<span>${total} ${pluralFiles(total)}</span>
         <span class="files-badge raw">RAW ${nRaw}</span>
         <span class="files-badge processed">PROCESSED ${nProc}</span>
         <span class="files-badge archive">ARCHIVE ${nArch}</span>`
      : '';
  }
  let shown = 0;
  for (const section of ['raw', 'processed', 'archive']) {
    const box = document.getElementById('history-' + section);
    if (!box) continue;
    const all = filesData[section] || [];
    const items = filesFilter ? all.filter(it => it.name.toLowerCase().includes(filesFilter)) : all;
    shown += items.length;
    if (!items.length) {
      const hint = filesFilter
        ? 'Ничего не найдено по фильтру'
        : (section === 'raw'
            ? 'Сырых файлов пока нет — запустите сбор данных'
            : 'Пусто — файлы появятся после обработки');
      box.innerHTML = `<div class="no-data">${hint}</div>`;
      continue;
    }
    box.innerHTML = items.map(it => fileCardHTML(section, it)).join('');
  }
  // «Найдено: X из Y» only while a filter is active — otherwise it is noise.
  const found = document.getElementById('files-found');
  if (found) found.textContent = filesFilter ? `Найдено: ${shown} из ${total}` : '';
}

function openFileInTable(rel) {
  if (!rel) return;
  setResultsSubTab('current');
  const body = document.getElementById('tbl-body');
  if (body) body.innerHTML = '<tr><td colspan="7" class="no-data">Загрузка…</td></tr>';
  const seq = ++_resultsReqSeq;      // перебивает незавершённую загрузку общего вида
  fetch('/results-view?view=' + encodeURIComponent(_resultsView) + '&file=' + encodeURIComponent(rel))
    .then(r => r.json())
    .then(d => {
      if (seq !== _resultsReqSeq) return;
      if (d.error) throw new Error(d.error);
      const recs = d.records || [];
      activeCity = '';
      _lastCities = [];          // вкладки городов для одного файла не нужны
      currentFile = rel;
      loadReviewed();
      // renderTable() перечитывает данные через filterTable → источник
      // должен быть обновлён до вызова.
      allResults = recs;
      renderTable(recs);
      currentFileNote = ` · файл: ${basenameOf(rel)}`;
      renderPage();              // перерисовать счётчик с именем файла
      showToast(`${recs.length} ${pluralRecords(recs.length)} · ${basenameOf(rel)}`, 'success');
    })
    .catch(() => {
      currentFileNote = '';
      currentFile = '';
      if (body) body.innerHTML = '<tr><td colspan="7" class="no-data">Файл не найден. Возможно, он был удалён.</td></tr>';
      showToast('Файл не найден. Обновите список.', 'error');
    });
}

function downloadResultsFile(rel) {
  if (!rel) return;
  const url = '/download/' + String(rel).split('/').map(encodeURIComponent).join('/');
  window.location.href = url;
}

async function archiveResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» переедет в output/_archive/ (папка сегодняшнего дня). Оттуда его можно вернуть.`,
    'Убрать файл в архив?', 'В архив');
  if (ok) await fileAction(rel, 'archive');
}

async function restoreResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» вернётся туда, откуда был убран (RAW или output/processed/excel/).`,
    'Вернуть файл из архива?', 'Вернуть');
  if (ok) await fileAction(rel, 'restore');
}

async function deleteResultsFile(rel) {
  const ok = await uiConfirm(
    `Файл «${rel}» будет удалён без возможности восстановления.`,
    'Удалить файл навсегда?', 'Удалить навсегда');
  if (ok) await fileAction(rel, 'delete');
}

async function fileAction(rel, action) {
  try {
    const d = await postJSON('/files/action', {
      path: rel, action, confirm: action === 'delete',
    });
    const done = {
      archive: `Файл в архиве: ${d.moved_to}`,
      restore: `Файл возвращён: ${d.restored_to}`,
      delete: 'Файл удалён',
    }[action] || 'Готово';
    showToast(done, 'success');
    loadFilesPanel(true);
    // Если в таблице был открыт именно этот файл — сбрасываем на общий вид
    if (currentFile === rel) setResultsView(_resultsView);
  } catch (e) {
    showToast('Ошибка: ' + e.message, 'error');
  }
}

// ── Init of the results panel ───────────────────────────────
function initResultsPanel() {
  let sub = 'current';
  try { if (localStorage.getItem(SUBTAB_KEY) === 'history') sub = 'history'; } catch (e) {}
  try { activeCity = localStorage.getItem(CITY_TAB_KEY) || ''; } catch (e) { activeCity = ''; }
  try { if (localStorage.getItem(SCOPE_KEY) === 'all') _resultsScope = 'all'; } catch (e) {}
  updateScopeButton();
  try {
    if (localStorage.getItem(BULK_OPEN_KEY) === '0') {
      const body = document.getElementById('bulk-body');
      const arrow = document.getElementById('bulk-collapse');
      if (body) body.hidden = true;
      if (arrow) arrow.textContent = '▸';
    }
  } catch (e) {}

  const sel = document.getElementById('bulk-social');
  if (sel) [...sel.options].forEach(o => { o.dataset.base = o.textContent; });

  // File actions via delegation — paths are never interpolated into JS code.
  const hist = document.getElementById('rs-history');
  if (hist) hist.addEventListener('click', e => {
    const btn = e.target.closest('.file-btn');
    if (!btn) return;
    const rel = btn.dataset.path || '';
    const act = btn.dataset.act;
    if (!rel) return;
    if (act === 'open') openFileInTable(rel);
    else if (act === 'download') downloadResultsFile(rel);
    else if (act === 'archive') archiveResultsFile(rel);
    else if (act === 'restore') restoreResultsFile(rel);
    else if (act === 'delete') deleteResultsFile(rel);
  });

  setResultsSubTab(sub);
  updateBulkStats();
}

// ═══════════════════════════════════════════
//  Export filtered rows
// ═══════════════════════════════════════════
// ── Экспорт/импорт данных приложения (отметки + настройки) ──
// Кнопки во вкладке «Форматы вывода». Экспорт — обычная ссылка на zip;
// импорт показывает сводку и перезагружает отметки, чтобы таблица и
// динамика увидели их сразу.
function exportAppData() {
  window.location.href = '/data/export';
  showToast('Готовлю архив с отметками и настройками…', 'info');
}

async function importAppData(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.zip')) {
    showToast('Нужен zip-архив из «Экспорта данных»', 'warning');
    input.value = '';
    return;
  }
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/data/import', { method: 'POST', body: fd });
    const d = await r.json();
    if (!d.ok) { showToast(d.error || 'Импорт не удался', 'error'); input.value = ''; return; }
    const parts = [];
    if (d.marks) parts.push(_pluralRu(d.marks, 'отметка', 'отметки', 'отметок'));
    if (d.settings) parts.push('настройки');
    showToast('Импортировано: ' + (parts.join(', ') || 'ничего нового'), 'success');
    // Отметки приходят с сервера: перечитываем их и перерисовываем таблицу.
    try { loadReviewed(); } catch (e) {}
    try { _reloadDaily(); } catch (e) {}
  } catch (e) {
    showToast('Импорт не удался — сервер не ответил', 'error');
  }
  input.value = '';
}

async function exportFiltered(fmt) {
  if (!filteredRows.length) return;
  // Выгрузка должна нести актуальные отметки, а не те, что были до батча.
  await autoPersistReviewed(true);
  fetch('/export-filtered', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({rows: filteredRows, format: fmt})
  })
  .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
  .then(blob => {
    const ext = fmt === 'xlsx' ? 'xlsx' : 'csv';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `filtered_export.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  })
  .catch(e => showToast('Ошибка экспорта: ' + e.message, 'error'));
}

// ═══════════════════════════════════════════
//  Map (Leaflet)
// ═══════════════════════════════════════════
// Leaflet подключается по требованию: библиотека лежит рядом с приложением
// (static/vendor/leaflet) и грузится только при открытии вкладки «На карте».
// Раньше <script> и <link> стояли в <head> и тянулись с unpkg при каждой
// загрузке страницы — без интернета вкладка не работала вообще.
// Промис кешируется: десять кликов по вкладке дают одну загрузку.
let _leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (_leafletPromise) return _leafletPromise;
  const assets = window.LEAFLET_ASSETS || {};
  _leafletPromise = new Promise((resolve, reject) => {
    if (!assets.js) { reject(new Error('путь к библиотеке карт не передан')); return; }
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = assets.css;
    document.head.appendChild(css);
    const js = document.createElement('script');
    js.src = assets.js;
    js.onload = () => (window.L ? resolve() : reject(new Error('библиотека карт не инициализировалась')));
    js.onerror = () => reject(new Error('файл библиотеки карт недоступен'));
    document.head.appendChild(js);
  });
  // Неудачу не запоминаем: следующий клик по вкладке попробует снова.
  _leafletPromise.catch(() => { _leafletPromise = null; });
  return _leafletPromise;
}

// Вкладка карты: сначала библиотека, потом карта. Ошибку показываем на месте
// карты — вместо пустого прямоугольника.
function ensureMapReady() {
  const container = document.getElementById('map-container');
  if (container && !window.L) container.innerHTML = '<div class="no-data" style="padding:40px">Загружаю карту…</div>';
  loadLeaflet()
    .then(() => initMap())
    .catch(err => {
      if (container) {
        container.innerHTML = '<div class="no-data" style="padding:40px">Карта недоступна: '
          + escapeHtml(err && err.message ? err.message : 'библиотека не загрузилась')
          + '. Результаты и выгрузка работают без неё.</div>';
      }
    });
}

function initMap() {
  const container = document.getElementById('map-container');
  const pts = allResults.filter(r => r.lat && r.lon);
  if (!pts.length) {
    container.innerHTML = '<div class="no-data" style="padding:60px">Нет данных с координатами</div>';
    return;
  }

  leafMap = L.map(container).setView([parseFloat(pts[0].lat), parseFloat(pts[0].lon)], 13);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {attribution:'© OpenStreetMap contributors', maxZoom:19}).addTo(leafMap);

  pts.forEach(r => {
    const lat = parseFloat(r.lat), lon = parseFloat(r.lon);
    if (isNaN(lat) || isNaN(lon)) return;
    // Попап — теми же классами, что и остальные всплывающие: инлайн-стили
    // тянули за собой старую палитру (#888, тёмно-зелёный, красный) и
    // не переключались вместе с темой.
    const socials = Object.entries(SOCIALS)
      .filter(([p]) => r[p])
      .map(([p, c]) => `<a class="map-soc" style="--tile:${c}" href="${escapeHtml(safeUrl(r[p]))}"`
        + ` target="_blank" rel="noopener noreferrer">${SLABELS[p]}</a>`)
      .join('');
    const popup = `
      <div class="map-pop">
        <div class="map-pop-name">${escapeHtml(r.name || '')}</div>
        ${r.category ? `<div class="map-pop-cat">${escapeHtml(r.category)}</div>` : ''}
        ${r.address ? `<div class="map-pop-row">${escapeHtml(r.address)}</div>` : ''}
        ${r.phone ? `<div class="map-pop-row">${escapeHtml(r.phone)}</div>` : ''}
        ${socials ? `<div class="map-pop-soc">${socials}</div>` : ''}
        <div class="map-pop-links">
          ${r.twogis_url ? `<a href="${escapeHtml(safeUrl(r.twogis_url))}" target="_blank" rel="noopener noreferrer">Открыть в 2ГИС ↗</a>` : ''}
          ${r.yandex_maps_url ? `<a href="${escapeHtml(safeUrl(r.yandex_maps_url))}" target="_blank" rel="noopener noreferrer">Открыть на Я.Картах ↗</a>` : ''}
        </div>
      </div>`;
   L.marker([lat,lon]).addTo(leafMap).bindPopup(popup).bindTooltip(escapeHtml(r.name||''));
  });

  // Fit bounds
  const latLngs = pts.map(r => [parseFloat(r.lat), parseFloat(r.lon)]);
  leafMap.fitBounds(L.latLngBounds(latLngs).pad(0.1));
  mapInited = true;
}

// ═══════════════════════════════════════════
//  Stats
// ═══════════════════════════════════════════
const CAT_COLORS = ['#1A6B3C','#2980b9','#8e44ad','#c0392b','#d35400','#16a085','#2c3e50','#27ae60','#f39c12','#7f8c8d'];

// ═══════════════════════════════════════
//  Default stats (always visible, even before the first search)
// ═══════════════════════════════════════
function renderDefaultStats() {
  const body = document.getElementById('stats-body');
  if (!body) return;
  body.innerHTML = `
    <div class="stat-cards">
      <div class="stat-card"><div class="num">0</div><div class="lbl">Всего найдено</div></div>
      <div class="stat-card"><div class="num">0</div><div class="lbl">С соцсетями</div></div>
      <div class="stat-card"><div class="num">—</div><div class="lbl">Время</div></div>
    </div>
    <div id="quota-slot"></div>
    <div class="stat-section">
      <h3>По соцсетям</h3>
      <div class="no-data" style="padding:18px 12px">Данные появятся после запуска поиска</div>
    </div>
    <div class="stat-section">
      <h3>Топ категорий</h3>
      <div class="no-data" style="padding:18px 12px">Данные появятся после запуска поиска</div>
    </div>`;
  // 2GIS quota card (if tokens were spent in this process) — idempotent.
  renderQuotaCard();
}

// ── 2GIS Places API quota card ─────────────────────────────
// Free-tier cap = 1000 billed requests per CALENDAR MONTH per key.
// 2GIS has no live-balance endpoint, so "spent" is our own persistent
// counter (output/.2gis_quota.json + this run); "left" = cap − spent.
// The counter survives app restarts and resets each month.
function quotaCardHtml() {
  const tq = _twogisQuotaLive;
  if (tq <= 0) return '';
  const cap = 1000, pct = Math.min(100, Math.round(tq / cap * 100));
  const cls = pct >= 95 ? 'crit' : pct >= 85 ? 'warn' : '';
  const left = Math.max(0, cap - tq);
  // Пояснение — в tooltip (ⓘ): раньше текст на карточке занимал больше места,
  // чем сами цифры. Читается при наведении на «ⓘ».
  const tip = 'Счётчик приложения: ≈ ' + (tq * 10).toLocaleString('ru-RU')
    + ' организаций · 1 запрос ≈ 10 организаций. 2GIS не показывает точный '
    + 'остаток — платный лимит видно только в Platform Manager (dev.2gis.ru) '
    + 'с задержкой ~1 день. Цифру израсходованных запросов можно ввести вручную.';
  return `
  <div class="stat-section">
    <div class="stat-city-card quota-card ${cls}">
      <h4>🧮 Токены 2GIS Places API
        <span class="quota-info" tabindex="0" title="${escapeHtml(tip)}" aria-label="Пояснение к счётчику">ⓘ</span></h4>
      <div class="quota-big"><span class="quota-num">${_fmtCount(tq)}</span><span class="quota-cap">/ ${cap}</span></div>
      <div class="quota-track"><div class="quota-fill" style="width:${pct}%"></div></div>
      <div class="quota-left">Осталось: <b>${_fmtCount(left)} запросов</b> (≈ ${_fmtCount(left * 10)} организаций)</div>
      <input type="number" class="quota-manual" min="0" max="100000" placeholder="${tq}"
             aria-label="Израсходовано за месяц — вручную"
             title="Знаете точный расход из Platform Manager? Введите его — счётчик замещается. Пустое поле оставляет текущее значение."
             onchange="setTwogisQuotaManual(this)">
    </div>
  </div>`;
}

// Ручная коррекция счётчика: точный расход виден в Platform Manager, автосчёт
// покрывает только запросы из этого приложения. Пустое значение — ничего.
async function setTwogisQuotaManual(input) {
  const raw = String(input.value || '').trim();
  if (!raw) { input.value = ''; return; }
  const value = parseInt(raw, 10);
  if (!isFinite(value) || value < 0) { input.value = ''; return; }
  try {
    const r = await fetch('/twogis/quota', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ used: value }),
    });
    const d = await r.json();
    if (d.ok) {
      _twogisQuotaLive = d.used;
      input.value = '';
      renderQuotaCard();
      showToast('Счётчик 2GIS обновлён: ' + _fmtCount(d.used), 'success');
    } else {
      showToast(d.error || 'Не удалось обновить счётчик', 'error');
    }
  } catch (e) {
    showToast('Не удалось обновить счётчик', 'error');
  }
}

function renderQuotaCard() {
  const slot = document.getElementById('quota-slot');
  if (!slot) return;              // stats tab not rendered yet — renderStats will pick it up
  slot.innerHTML = quotaCardHtml();
}

// Shared bar renderer for the stats sections. Bars are normalized against
// the MAXIMUM value (not the record total), so the largest bar is always
// full width and small values stay comparable. Tiny counts (<3) get a
// minimal 5px bar so they stay visible; the exact number is in the tail.
function barRows(rows) {
  if (!rows || !rows.length) return '';
  const max = Math.max(...rows.map(r => r.count)) || 1;
  return rows.map(r => {
    const pct = Math.max(Math.round(r.count / max * 100), 1);
    const min = r.count < 3 ? 5 : 0;          // px floor for tiny values
    const style = `width:${pct}%;${min ? `min-width:${min}px;` : ''}background:${r.color}`;
    return `
        <div class="bar-row">
          <div class="bar-lbl" title="${escapeHtml(r.label)}">${escapeHtml(r.label)}</div>
          <div class="bar-track"><div class="bar-fill" style="${style}"></div></div>
          <div class="bar-val">${r.count}</div>
        </div>`;
  }).join('');
}

// Кольцевая диаграмма для долей (соцсети): SVG-окружности со штрих-даш-
// массивом. Радиус 70 при ободе 16 — центр свободен под итог. Доли < 0.5%
// сливаются с дорожкой, поэтому каждая дуга получает минимум 0.5%. Одна
// соцсеть — полное кольцо (окружность целиком, а не 100%-dash).
function donutHTML(rows, centerLabel) {
  if (!rows || !rows.length) return '';
  const total = rows.reduce((s, r) => s + r.count, 0) || 1;
  const C = 2 * Math.PI * 70;
  let offset = 0;
  // Подпись внутри сектора: середина дуги под углом a (0° = вверх, по часовой).
  // Сектор < 8% не подписываем — число там не помещается, остаётся в легенде.
  const labels = rows.map(r => {
    const pct = r.count / total;
    if (pct < 0.08) return '';
    const a = (offset / C) * 2 * Math.PI + (r.count / total) * Math.PI;
    const x = 84 + Math.sin(a) * 70;
    const y = 84 - Math.cos(a) * 70;
    return `<text class="donut-pct" x="${x.toFixed(1)}" y="${y.toFixed(1)}"`
      + ` fill="#fff">${Math.round(pct * 100)}%</text>`;
  });
  const arcs = rows.map(r => {
    const frac = r.count / total;
    const len = Math.max(frac * C, 0.005 * C);
    const dash = `${len} ${C - len}`;
    const el = `<circle class="donut-arc" cx="84" cy="84" r="70"`
      + ` stroke="${r.color}" stroke-dasharray="${dash}"`
      + ` stroke-dashoffset="${-offset}" stroke-linecap="butt"`
      + ` title="${escapeHtml(r.label)}: ${r.count}"></circle>`;
    offset += frac * C;
    return el;
  }).join('');
  const single = rows.length === 1
    ? `<circle class="donut-arc" cx="84" cy="84" r="70" stroke="${rows[0].color}"`
      + ` title="${escapeHtml(rows[0].label)}: ${rows[0].count}"></circle>`
    : arcs;
  const legend = rows.map(r => `
      <div class="donut-legend-row">
        <i class="donut-swatch" style="background:${r.color}"></i>
        <span title="${escapeHtml(r.label)}">${escapeHtml(r.label)}</span>
        <b>${r.count} · ${Math.round(r.count / total * 100)}%</b>
      </div>`).join('');
  return `<div class="donut-wrap">`
    + `<div class="donut"><svg width="168" height="168" viewBox="0 0 168 168" aria-hidden="true">`
    + `<circle class="donut-track" cx="84" cy="84" r="70"></circle>${single}${labels.join('')}</svg>`
    + `<div class="donut-center"><b>${_fmtCount(total)}</b>`
    + `<span>${escapeHtml(centerLabel || '')}</span></div></div>`
    + `<div class="donut-legend">${legend}</div></div>`;
}

function renderStats(data, elapsed, skippedCities) {
  if (!data.length) return;
  const total  = data.length;
  const withSo = data.filter(r => Object.keys(SOCIALS).some(p => r[p])).length;
  const dur    = elapsed ? (elapsed < 60 ? elapsed.toFixed(0)+'с' : (elapsed/60).toFixed(1)+'м') : '—';

  const cards = [
    {num: total,   lbl: 'Всего найдено'},
    {num: withSo,  lbl: 'С соцсетями'},
    {num: dur,     lbl: 'Время'},
  ];

  const socialKeys = Object.keys(SOCIALS);
  const hasSocial = r => socialKeys.some(p => r[p]);

  // Socials breakdown (overall, all cities)
  const socialCounts = socialKeys.map(p => ({
    name: SLABELS[p], count: data.filter(r => r[p]).length, color: SOCIALS[p]
  })).filter(s => s.count > 0).sort((a,b) => b.count - a.count);

  // Categories
  const catMap = {};
  data.forEach(r => (r.category||'').split(',').forEach(c => {
    const t = c.trim(); if (t) catMap[t] = (catMap[t]||0) + 1;
  }));
  const cats = Object.entries(catMap).sort((a,b)=>b[1]-a[1]).slice(0,10);

  // Per-city breakdown — records carry a city stamp from the backend.
  const byCity = {};
  data.forEach(r => {
    const c = (r.city || '').trim() || '—';
    (byCity[c] = byCity[c] || []).push(r);
  });
  const cityNames = Object.keys(byCity).filter(c => c !== '—');
  const cityCardsHtml = cityNames.length > 0 ? `<div class="stat-section"><h3>По городам</h3><div class="stat-city-grid">`
    + cityNames.map(name => {
      const cd = byCity[name];
      const cityTotal = cd.length;
      const cityWithSo = cd.filter(hasSocial).length;
      const citySocials = socialKeys
        .map(p => ({p, count: cd.filter(r => r[p]).length}))
        .filter(s => s.count > 0)
        .sort((a,b) => b.count - a.count)
        .slice(0, 6);
      const chips = citySocials.length
        ? `<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:3px">`
          + citySocials.map(s => `<span style="background:${SOCIALS[s.p]};color:#fff;border-radius:10px;font-size:10px;padding:1px 6px;font-weight:600">${SLABELS[s.p]} ${s.count}</span>`).join('')
          + `</div>`
        : '';
      return `<div class="stat-city-card">
        <h4>${escapeHtml(name)}</h4>
        <div class="stat-mini-row"><span>Всего</span><span>${cityTotal}</span></div>
        <div class="stat-mini-row"><span>С соцсетями</span><span>${cityWithSo}</span></div>
        <div class="stat-mini-row"><span>Без соцсетей</span><span>${cityTotal - cityWithSo}</span></div>
        ${chips}
      </div>`;
    }).join('') + `</div></div>` : '';


  // Show skipped cities if any
  let skippedHtml = '';
  if (skippedCities && skippedCities.length > 0) {
    skippedHtml = `<div class="stat-section"><h3>⏭ Пропущенные города</h3><div class="stat-city-grid">`;
    skippedCities.forEach(sc => {
      skippedHtml += `<div class="stat-city-card" style="border-left:3px solid rgba(100,140,200,.6)">
        <h4>${escapeHtml(sc.name)}</h4>
        <div class="stat-mini-row"><span>Статус</span><span style="color:rgba(100,140,200,1)">Пропущен</span></div>
        <div class="stat-mini-row"><span>Записей собрано</span><span>${sc.records_found}</span></div>
      </div>`;
    });
    skippedHtml += `</div></div>`;
  }

  const body = document.getElementById('stats-body');
  // Fetch live analytics + cache stats + 2GIS Places quota
  Promise.all([
    fetch('/analytics').then(r=>r.json()).catch(()=>({})),
    fetch('/cache/stats').then(r=>r.json()).catch(()=>({})),
    fetch('/status').then(r=>r.json()).catch(()=>({}))
  ]).then(([a, c, st]) => {
    // Prefer the live value streamed from the child process (progress events);
    // /status is the fallback (thread mode + past runs in this process).
    if ((st && st.twogis_quota_used) > _twogisQuotaLive) _twogisQuotaLive = st.twogis_quota_used;
    const quotaHtml = quotaCardHtml();
    const analyticsHtml = (a && a.total_requests) || (c && c.total) ? `
    <div class="stat-section">
      <h3>${UI_ICONS.bolt}Аналитика</h3>
      <div class="stat-cards">
        ${a.total_requests ? `
        <div class="stat-card" title="Фактическая скорость запросов к API (запросов в секунду)"><div class="num">${a.rps_actual}</div><div class="lbl">RPS (факт.)</div></div>
        <div class="stat-card" title="Целевая скорость запросов — лимит, который мы стараемся не превышать"><div class="num">${a.rps_target}</div><div class="lbl">RPS (цель)</div></div>
        <div class="stat-card" title="Средняя задержка ответа сервера"><div class="num">${a.avg_latency}с</div><div class="lbl">Среднее</div></div>
        <div class="stat-card" title="Медианная задержка: половина запросов отвечает быстрее этого времени"><div class="num">${a.p50_latency}с</div><div class="lbl">P50</div></div>
        <div class="stat-card" title="95-й процентиль: 95% запросов отвечают быстрее этого времени (показывает самые медленные ответы)"><div class="num">${a.p95_latency}с</div><div class="lbl">P95</div></div>
        <div class="stat-card"><div class="num">${a.total_requests}</div><div class="lbl">Запросов</div></div>
        <div class="stat-card"><div class="num">${a.errors}</div><div class="lbl">Ошибок</div></div>
        <div class="stat-card"><div class="num">${a.rate_limits}</div><div class="lbl">429</div></div>
        ` : ''}
        ${c.valid ? `
        <div class="stat-card" title="Свежие записи кэша — повторные запросы берутся из кэша мгновенно и не тратят лимит API"><div class="num">${c.valid}</div><div class="lbl">Кэш (активных)</div></div>
        <div class="stat-card" title="Устаревшие записи кэша — данные старше 7 дней, будут перезапрошены"><div class="num">${c.expired}</div><div class="lbl">Кэш (устаревших)</div></div>
        ` : ''}
      </div>
    </div>` : '';
    body.innerHTML = `
    <div class="stat-cards">${cards.map(c =>
      `<div class="stat-card"${c.tip ? ` title="${escapeHtml(c.tip)}"` : ''}><div class="num">${c.num}</div><div class="lbl">${c.lbl}</div></div>`
    ).join('')}</div>

    ${quotaHtml}

    ${analyticsHtml}

    ${cityCardsHtml}

    ${skippedHtml}

    ${(socialCounts.length || cats.length) ? `
    <div class="stat-split">
      <div class="stat-split-main">
        ${cats.length ? `
        <div class="stat-section">
          <h3>Топ категорий</h3>
          ${barRows(cats.map(([name, cnt], i) => ({label: name, count: cnt, color: CAT_COLORS[i%CAT_COLORS.length]})))}
        </div>` : ''}
      </div>
      <div class="stat-split-side">
        ${socialCounts.length ? `
        <div class="stat-section">
          <h3>По соцсетям</h3>
          ${donutHTML(socialCounts.map(s => ({label: s.name, count: s.count, color: s.color})), 'записей')}
        </div>` : ''}
      </div>
    </div>` : ''}
  `;
    // Свежие файлы и отметки могли появиться только что — обновляем динамику,
    // но не во время прогона: там renderStats зовётся каждые 1.5 с, а обход
    // папки с пересчётом строк дешевле не становится.
    if (!isRunActive()) loadDailyDynamics();
  }).catch(()=>{});
}

// ═══════════════════════════════════════════
//  «Динамика по дням» (вкладка «Статистика»)
// ═══════════════════════════════════════════
// Данные считает сервер (/stats/daily): «найдено» — по строкам файлов
// результатов за день, «просмотрено» — по дате отметки в _reviewed.json.
// Блок живёт в своём контейнере #stats-daily: он показывает работу за все
// дни, а не только за текущую сессию, и должен быть на месте даже тогда,
// когда #stats-body ещё показывает заглушку «запустите поиск».
// Быстрые периоды. «Сегодня» — окно в один день (`days=1`), которое сервер
// разворачивает в почасовой ряд: время поиска пишется в имя файла
// (`raw_2026-09-30_14-01_…`), поэтому 14:01 и 14:50 попадают в колонку «14».
const DAILY_SEGMENTS = [
  {days: 1, label: 'Сегодня'}, {days: 7, label: '7 дн.'},
  {days: 14, label: '14 дн.'}, {days: 30, label: '30 дн.'},
];
const DAILY_DEFAULT_DAYS = 7;

// Период графика — три режима на одни и те же дни: набор сегментов,
// календарный месяц (input[type=month]) и произвольный диапазон «с … по …».
// Окно считает сервер и возвращает его в ответе (`start`/`end`), поэтому
// даты в полях и столбцы на графике не могут разойтись.
let _dailyRange = {kind: 'days', days: DAILY_DEFAULT_DAYS, month: '', from: '', to: ''};
let _dailyPayload = null;      // последний ответ: им предзаполнены поля периода
let _dailyCustomOpen = false;  // развёрнут ли блок «с … по …»
let _dailySeq = 0;             // ответ на устаревший период рисовать нельзя

const DAILY_WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

function _dailyDayLabel(iso) {
  const d = new Date(iso + 'T00:00:00');
  if (isNaN(d.getTime())) return {wd: '', dm: iso};
  return {
    wd: DAILY_WEEKDAYS[d.getDay()],
    dm: String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0'),
  };
}

// Полная дата для подписи периода: 30.09.2026. В столбце хватает «30.09»,
// а в «с 01.09.2026 по 30.09.2026» год нужен — иначе непонятно, за что график.
function _dayFull(iso) {
  const s = String(iso || '');
  return /^\d{4}-\d{2}-\d{2}$/.test(s)
    ? s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(0, 4) : s;
}

function _todayIso() {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
    + '-' + String(d.getDate()).padStart(2, '0');
}

// Строка запроса к /stats/daily по текущему режиму периода. «Сегодня»
// просит почасовой разворот: час в имени файла — единственный честный
// источник времени поиска.
function _dailyQuery() {
  const r = _dailyRange;
  if (r.kind === 'custom' && r.from && r.to) {
    if (r.from === r.to) return 'from=' + encodeURIComponent(r.from)
      + '&to=' + encodeURIComponent(r.to) + '&hours=1';
  }
  if (r.kind === 'custom' && r.from && r.to) {
    return 'from=' + encodeURIComponent(r.from) + '&to=' + encodeURIComponent(r.to);
  }
  if (r.kind === 'month' && r.month) return 'month=' + encodeURIComponent(r.month);
  return 'days=' + (r.days || DAILY_DEFAULT_DAYS) + (r.days === 1 ? '&hours=1' : '');
}

// Подпись показанного периода: одна дата для одного дня, диапазон — для окна.
function _dailyRangeLabel(payload) {
  if (!payload) return '';
  return payload.days > 1
    ? _dayFull(payload.start) + ' — ' + _dayFull(payload.end)
    : _dayFull(payload.end);
}

// «Ничего не найдено» с человеческим именем периода: для набора 7/14/30 дней
// это «за последние 7 дней», для месяца и диапазона — датами.
function _dailyEmptyText(payload) {
  if (payload.mode === 'days' || payload.mode === 'hours') {
    const n = Number(payload.days) || 1;
    return n === 1 ? 'За сегодня'
      : 'За последние ' + n + ' ' + _pluralRu(n, 'день', 'дня', 'дней');
  }
  return 'С ' + _dayFull(payload.start) + ' по ' + _dayFull(payload.end);
}

// О чём график умалчивает: отметки без даты (старый формат `_reviewed.json`)
// и обрезанный период. Молчать об этом хуже всего: «просмотрено 0» при сотне
// отмеченных строк выглядит как поломка счётчика.
function _dailyNoteHTML(payload) {
  const out = [];
  const undated = Number((payload.totals || {}).undated || 0);
  if (undated) {
    out.push('Ещё ' + _fmtCount(undated) + ' '
      + _pluralRu(undated, 'отметка', 'отметки', 'отметок')
      + ' «просмотрено» сделаны до того, как отметки начали хранить дату, —'
      + ' в динамике по дням они не участвуют.');
  }
  if (payload.truncated) {
    out.push('Период длиннее года: показаны последние 366 дней.');
  }
  return out.length ? '<div class="dyn-note">' + out.join(' ') + '</div>' : '';
}

// Разряды тонким пробелом (1 062): числа читаются быстрее, а локаль браузера
// на формат не влияет — тесты сравнивают строки.
function _fmtCount(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

// Подписи оси — компактнее: у гуттера ширина 34px, и «123 456» в него не
// влезает, а «123к» — влезает и читается на делении шкалы.
function _fmtTick(n) {
  const v = Math.round(Number(n) || 0);
  return v >= 10000 ? Math.round(v / 1000) + 'к' : _fmtCount(v);
}

// Шкала графика: верхняя метка кратна шагу, шаг — из лестницы 0.5/1/2/2.5/5/10
// от порядка максимума, делений 3–5. Так на оси всегда круглые числа
// (50/100/150), а столбец самого богатого дня занимает бо́льшую часть высоты:
// «просто максимум» давал подписи вида 531 и 1062.
function dailyAxis(max) {
  const top = Math.max(1, Math.ceil(Number(max) || 0));
  const pow = Math.pow(10, Math.floor(Math.log10(top)));
  // Для небольших чисел шаг 2.5 дал бы дробные подписи (7.5 откликов).
  const mults = pow < 10 ? [0.5, 1, 2, 5, 10] : [0.5, 1, 2, 2.5, 5, 10];
  for (const m of mults) {
    const step = Math.max(1, m * pow);
    const n = Math.ceil(top / step);
    if (n >= 2 && n <= 4) return {top: n * step, step: step, n: n};
  }
  return {top: top, step: top, n: 1};   // совсем маленькие максимумы: 0 и он сам
}

// Подписи колонок скрываются, когда на них нет места: 9.5px-число требует
// ~30px, поэтому плотность считаем по реальной ширине блока, а не по числу
// дней — на телефоне и на десктопе порог разный.
function _dailyDense(count) {
  const box = document.getElementById('stats-daily');
  const width = box ? box.clientWidth : 0;
  if (!width) return count > 7;            // ширина неизвестна (скрытая вкладка)
  return count * 30 > width - 44;          // 44 — гуттер оси и отступы
}

function dailyControlsHTML() {
  const r = _dailyRange;
  const segs = DAILY_SEGMENTS.map(s => {
    const on = r.kind === 'days' && s.days === r.days;
    return `<button type="button" class="dyn-range${on ? ' is-on' : ''}"`
      + ` aria-pressed="${on}" onclick="setDailyRange(${s.days})">${s.label}</button>`;
  }).join('');
  // У поля месяца свой формат границы (YYYY-MM): полная дата в max сделала бы
  // текущий месяц невалидным, и браузер не дал бы его выбрать.
  const thisMonth = _todayIso().slice(0, 7);
  return '<div class="dyn-controls">'
    + `<div class="dyn-ranges" role="group" aria-label="Быстрый период">${segs}</div>`
    + `<input type="month" id="dyn-month" class="dyn-month" max="${thisMonth}"`
    + ' aria-label="Календарный месяц" title="Показать календарный месяц"'
    + ` value="${escapeHtml(r.kind === 'month' ? r.month : '')}"`
    + ' onchange="setDailyMonth(this.value)">'
    + `<button type="button" class="dyn-range dyn-more${r.kind === 'custom' ? ' is-on' : ''}"`
    + ` aria-expanded="${_dailyCustomOpen}" onclick="toggleDailyCustom()">Период…</button>`
    + '</div>';
}

// Блок «с … по …» — отдельной строкой под шапкой: в одну строку с сегментами
// он сжимал их до нечитаемого на телефоне. Даты предзаполнены текущим
// периодом: обычно правят один его конец, а не набирают оба заново.
function dailyCustomHTML() {
  const r = _dailyRange;
  const last = _dailyPayload || {};
  const from = r.kind === 'custom' ? r.from : (last.start || '');
  const to = r.kind === 'custom' ? r.to : (last.end || '');
  const today = _todayIso();
  const enter = " onkeydown=\"if(event.key==='Enter')applyDailyCustom()\"";
  const input = (id, val) => `<input type="date" id="${id}" class="dyn-date"`
    + ` value="${escapeHtml(val)}" min="2015-01-01" max="${today}"${enter}>`;
  return `<div class="dyn-custom" id="dyn-custom"${_dailyCustomOpen ? '' : ' hidden'}>`
    + '<span class="dyn-custom-lbl">с</span>' + input('dyn-from', from)
    + '<span class="dyn-custom-lbl">по</span>' + input('dyn-to', to)
    + '<button type="button" class="dyn-apply" onclick="applyDailyCustom()">Показать</button>'
    + '</div>';
}

function dailySectionHTML(payload) {
  const head = `<div class="dyn-head"><h3>${UI_ICONS.chart}Динамика по дням</h3>`
             + dailyControlsHTML() + '</div>' + dailyCustomHTML();
  const wrap = body => `<div class="stat-section dyn-section">${head}${body}</div>`;

  if (!payload) {
    return wrap('<div class="dyn-empty">Не удалось загрузить динамику — сервер не ответил.</div>');
  }
  if (payload.loading) {
    return wrap('<div class="dyn-empty">Считаю файлы результатов…</div>');
  }
  const series = payload.series || [];
  const totals = payload.totals || {found: 0, reviewed: 0};
  const note = _dailyNoteHTML(payload);
  if (!series.length || (!totals.found && !totals.reviewed)) {
    return wrap('<div class="dyn-empty">' + _dailyEmptyText(payload)
      + ' ничего не найдено и не отмечено просмотренным.</div>' + note);
  }

  // «Сегодня» рисуется по часам, если серверу есть из чего их собрать:
  // время поиска пишется в имя raw-файла, а у processed его нет. Если
  // файлы с часом не дали строк (найдено — из processed), дневной столбец
  // честнее пустых суток.
  if (payload.hours && payload.hours.some(h => h.found)) {
    return wrap(dailyHoursChartHTML(payload));
  }

  // Одна шкала на оба ряда: «просмотрено» — это часть найденного, и на своей
  // шкале короткая полоса выглядела бы такой же высокой, как длинная.
  const maxFound = Math.max(1, ...series.map(d => d.found));
  const axis = dailyAxis(maxFound);
  const ticks = [];
  for (let i = 0; i <= axis.n; i++) ticks.push(i * axis.step);
  const dense = _dailyDense(series.length);
  const todayIso = series[series.length - 1].date;

  // Нулевой день высоты не получает вовсе: .is-zero рисует насечку 2px, а
  // inline-высота её бы перебила (inline сильнее правила класса).
  const bar = (cls, value) => {
    const pct = value ? Math.max(2, Math.round(value / axis.top * 100)) : 0;
    return `<div class="dyn-bar ${cls}${pct ? '' : ' is-zero'}"`
         + (pct ? ` style="height:${pct}%"` : '') + `></div>`;
  };
  // Цифра над своим столбцом: bottom считается от его же высоты, поэтому
  // подпись всегда едет вместе со столбцом. Ноль — приглушённый: он не
  // «данные», а их отсутствие.
  const series_ = (cls, value) => {
    const pct = value ? Math.max(2, Math.round(value / axis.top * 100)) : 0;
    const lab = `<span class="dyn-vlab${value ? '' : ' is-zero'}"`
              + ` style="bottom:calc(${pct}% + 3px)">${_fmtCount(value)}</span>`;
    return `<div class="dyn-series ${cls}">${lab}${bar(cls, value)}</div>`;
  };

  const cols = series.map(d => {
    const {wd, dm} = _dailyDayLabel(d.date);
    const pct = d.found ? Math.round(d.reviewed / d.found * 100) : 0;
    return `<div class="dyn-col${d.date === todayIso ? ' is-today' : ''}"`
      + ` data-wd="${wd}" data-dm="${dm}" data-found="${d.found}"`
      + ` data-review="${d.reviewed}" data-files="${d.files || 0}" data-pct="${pct}">`
      + `<div class="dyn-stack">${series_('dyn-found', d.found)}${series_('dyn-review', d.reviewed)}</div>`
      + `<div class="dyn-day"><span class="dyn-wd">${wd}</span><span class="dyn-dm">${dm}</span></div>`
      + `</div>`;
  }).join('');

  // Сетка и подписи оси живут в общем поле с колонками: линия — абсолютный
  // элемент, поэтому она точно совпадает с высотой столбца самой богатой дни.
  // Один день без почасовых данных — единственный столбец: ограничиваем его
  // ширину (is-single), иначе колонка растянется на всю страницу.
  const single = series.length === 1 ? ' is-single' : '';
  const grid = '<div class="dyn-grid" aria-hidden="true">'
    + ticks.filter(t => t > 0).map(t =>
        `<i style="bottom:${t / axis.top * 100}%"></i>`).join('')
    + '</div>';
  const yaxis = '<div class="dyn-yaxis" aria-hidden="true">'
    + ticks.map(t => `<span class="dyn-tick" style="bottom:${t / axis.top * 100}%">`
        + `${_fmtTick(t)}</span>`).join('')
    + '</div>';

  // Подпись периода в той же строке: у месяца и произвольного диапазона
  // сегменты не подсвечены, и без дат непонятно, что именно показано.
  const legend = '<div class="dyn-legend">'
    + `<span class="dyn-key"><i class="dyn-sw dyn-found"></i>Найдено <b>${_fmtCount(totals.found)}</b></span>`
    + `<span class="dyn-key"><i class="dyn-sw dyn-review"></i>Просмотрено <b>${_fmtCount(totals.reviewed)}</b></span>`
    + `<span class="dyn-span">${escapeHtml(_dailyRangeLabel(payload))}</span>`
    + '</div>';

  // Итоги периода: средний темп, лучший день и доля разобранного — то, ради
  // чего в график вообще смотрят. Для одного дня средний темп — это он сам,
  // а «лучший день» — весь период, поэтому такие факты не показываем.
  const avg = Math.round(totals.found / series.length);
  const best = series.reduce((a, b) => (b.found > a.found ? b : a), series[0]);
  const bestLbl = _dailyDayLabel(best.date);
  const share = totals.found ? Math.round(totals.reviewed / totals.found * 100) : 0;
  const facts = [];
  if (series.length > 1) {
    facts.push('<span class="dyn-fact dyn-fact-avg">В среднем <b>' + _fmtCount(avg) + '</b> в день</span>');
    if (best.found) {
      facts.push('<span class="dyn-fact dyn-fact-best" title="День с самым большим числом найденных">Лучший день — <b>'
        + bestLbl.wd + ', ' + bestLbl.dm + '</b>: ' + _fmtCount(best.found) + '</span>');
    }
  }
  facts.push('<span class="dyn-fact dyn-fact-share" title="Отмечено просмотренными из найденных за период">Разобрано <b>'
    + share + '%</b></span>');

  const aria = `Динамика с ${_dayFull(payload.start)} по ${_dayFull(payload.end)}`
             + ` (${series.length} дней): найдено ${totals.found},`
             + ` просмотрено ${totals.reviewed}, в среднем ${avg} в день`;
  return wrap(
    `<div class="dyn-chart${dense ? ' is-dense' : ''}" role="img" aria-label="${escapeHtml(aria)}">`
    + `<div class="dyn-plot">${yaxis}<div class="dyn-area">${grid}`
    + `<div class="dyn-cols${single}">${cols}</div></div></div>`
    + '</div>'
    + legend
    + `<div class="dyn-facts">${facts.join('')}</div>`
    + note);
}

// ── Почасовой график «Сегодня» ─────────────────────────────
// Тот же plot, что и у дневного графика: одна шкала, сетка и ось — общие
// helpers. Отличия — в подписях (колонка «14» вместо «ср 30.09») и в том,
// что «просмотрено» за день остаётся в легенде, но не разбивается по часам:
// время отметки в данных не хранится, поэтому раскладывать его по часам
// нельзя. Пустые часы за активностью поиска не рисуются: на шкале 00–23
// ряд из нулей до 9 утра — это шум, а не информация.
function dailyHoursChartHTML(payload) {
  const hours = payload.hours || [];
  const totals = payload.totals || {found: 0, reviewed: 0};
  const withData = hours.filter(h => h.found);
  const firstH = withData.length ? withData[0].hour : 0;
  const lastH = withData.length ? withData[withData.length - 1].hour : 23;
  // Окно от первого до последнего часа с данными (+1 час запаса), минимум 3.
  const from = Math.max(0, firstH - 1);
  const to = Math.min(23, Math.max(lastH + 1, from + 2));
  const shown = hours.slice(from, to + 1);

  const maxFound = Math.max(1, ...shown.map(h => h.found));
  const axis = dailyAxis(maxFound);
  const ticks = [];
  for (let i = 0; i <= axis.n; i++) ticks.push(i * axis.step);
  const dense = _dailyDense(shown.length);

  const bar = (cls, value) => {
    const pct = value ? Math.max(2, Math.round(value / axis.top * 100)) : 0;
    return `<div class="dyn-bar ${cls}${pct ? '' : ' is-zero'}"`
         + (pct ? ` style="height:${pct}%"` : '') + `></div>`;
  };
  const series_ = (cls, value) => {
    const pct = value ? Math.max(2, Math.round(value / axis.top * 100)) : 0;
    const lab = `<span class="dyn-vlab${value ? '' : ' is-zero'}"`
              + ` style="bottom:calc(${pct}% + 3px)">${_fmtCount(value)}</span>`;
    return `<div class="dyn-series ${cls}">${lab}${bar(cls, value)}</div>`;
  };

  const cols = shown.map(h => {
    const lbl = String(h.hour).padStart(2, '0');
    return `<div class="dyn-col" data-wd="Час" data-dm="${lbl}:00"`
      + ` data-found="${h.found}" data-review="0" data-files="${h.files || 0}" data-pct="0">`
      + `<div class="dyn-stack">${series_('dyn-found', h.found)}${series_('dyn-review', 0)}</div>`
      + `<div class="dyn-day"><span class="dyn-dm">${lbl}</span></div>`
      + `</div>`;
  }).join('');

  const grid = '<div class="dyn-grid" aria-hidden="true">'
    + ticks.filter(t => t > 0).map(t =>
        `<i style="bottom:${t / axis.top * 100}%"></i>`).join('')
    + '</div>';
  const yaxis = '<div class="dyn-yaxis" aria-hidden="true">'
    + ticks.map(t => `<span class="dyn-tick" style="bottom:${t / axis.top * 100}%">`
        + `${_fmtTick(t)}</span>`).join('')
    + '</div>';

  const label = _dayFull(payload.end);
  const legend = '<div class="dyn-legend">'
    + `<span class="dyn-key"><i class="dyn-sw dyn-found"></i>Найдено <b>${_fmtCount(totals.found)}</b></span>`
    + `<span class="dyn-key"><i class="dyn-sw dyn-review"></i>Просмотрено <b>${_fmtCount(totals.reviewed)}</b></span>`
    + `<span class="dyn-span">${escapeHtml(label)} · по часам</span>`
    + '</div>';

  const aria = `Почасовая динамика за ${label}: найдено ${totals.found},`
             + ` просмотрено ${totals.reviewed}`;
  return `<div class="dyn-chart${dense ? ' is-dense' : ''}" role="img" aria-label="${escapeHtml(aria)}">`
    + `<div class="dyn-plot">${yaxis}<div class="dyn-area">${grid}`
    + `<div class="dyn-cols">${cols}</div></div></div>`
    + '</div>'
    + legend;
}

// ── Подсказка при наведении ────────────────────────────────
// Своя карточка вместо атрибута title: в title не влезает разбор дня, а
// системная подсказка перекрывает сам график и исчезает через секунду.
//
// Живёт она в <body> с position:fixed — не внутри графика, как раньше:
// * панель «Статистика» прокручивается (overflow-y:auto) и режет всё, что
//   вылезло за её верх: подсказка над богатым столбцом у высокого графика
//   обрезалась именно так;
// * у .dyn-cols overflow-x:auto — вложенную подсказку срезала бы и она.
// Координаты берутся из getBoundingClientRect(), то есть в тех же CSS-пикселях,
// в которых заданы left/top у fixed-элемента. При масштабировании страницы
// масштабируются оба значения одинаково, и подсказка остаётся приклеенной к
// столбцу — раньше она считалась от вложенных смещений и уезжала от курсора.
let _dailyTip = null;
let _dailyTipCol = null;    // колонка, для которой сейчас посчитано содержимое
let _dailyTipSize = null;   // размер замеряется при смене содержимого, а не на каждый mousemove

const DAILY_TIP_GAP = 8;

function _dailyTipNode() {
  if (!_dailyTip || !_dailyTip.isConnected) {
    _dailyTip = document.createElement('div');
    _dailyTip.className = 'dyn-tip';
    _dailyTip.setAttribute('aria-hidden', 'true');
    document.body.appendChild(_dailyTip);
    _dailyTipCol = null;
    _dailyTipSize = null;
  }
  return _dailyTip;
}

function _dailyTipHTML(col) {
  const g = k => Number(col.getAttribute('data-' + k) || 0);
  const title = col.getAttribute('data-wd') + ', ' + col.getAttribute('data-dm');
  const files = g('files');
  return `<div class="dyn-tip-day">${escapeHtml(title)}</div>`
    + `<div class="dyn-tip-row"><i class="dyn-sw dyn-found"></i>Найдено<b>${_fmtCount(g('found'))}</b></div>`
    + `<div class="dyn-tip-row"><i class="dyn-sw dyn-review"></i>Просмотрено<b>${_fmtCount(g('review'))}</b></div>`
    + `<div class="dyn-tip-note">${files ? files + ' ' + _pluralRu(files, 'файл', 'файла', 'файлов')
        + ' · ' : ''}разобрано ${g('pct')}%</div>`;
}

// Границы, в которых подсказке разрешено стоять: видимая часть окна, но не
// выше верха панели статистики — под ней шапка приложения, и заезжать на неё
// некрасиво, даже когда подсказку никто не режет. Верх панели зажимается
// в окно: на мобильной раскладке панель может оказаться ниже экрана целиком,
// и «её верх» утащил бы подсказку за край.
function _dailyTipBounds(size) {
  const panel = document.getElementById('p-stats');
  const r = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const vh = window.innerHeight;
  const limit = Math.max(0, vh - size.height - 4);
  return {top: r && r.height ? Math.min(Math.max(r.top, 0), limit) : 0, bottom: vh};
}

function _placeDailyTip(tip, cr) {
  const size = _dailyTipSize;
  if (!size || !cr) return;
  const pad = 4;
  const b = _dailyTipBounds(size);
  const minTop = b.top + pad;
  const maxTop = Math.max(minTop, b.bottom - size.height - pad);
  // По центру столбца, но целиком в экране: половина карточки за краем окна
  // выглядела бы как подсказка «не к тому» дню.
  let left = cr.left + cr.width / 2 - size.width / 2;
  left = Math.min(Math.max(left, pad), window.innerWidth - size.width - pad);
  // Над столбцом; если места нет (столбец уехал под шапку) — под ним.
  let top = cr.top - DAILY_TIP_GAP - size.height;
  const below = top < minTop;
  if (below) top = cr.bottom + DAILY_TIP_GAP;
  top = Math.min(Math.max(top, minTop), maxTop);
  tip.style.left = Math.round(left) + 'px';
  tip.style.top = Math.round(top) + 'px';
  tip.classList.toggle('is-below', below);
}

function _showDailyTip(col) {
  if (!col) return;
  const tip = _dailyTipNode();
  if (col !== _dailyTipCol) {
    tip.innerHTML = _dailyTipHTML(col);
    _dailyTipCol = col;
    _dailyTipSize = null;
  }
  tip.classList.add('is-on');
  if (!_dailyTipSize) {
    const r = tip.getBoundingClientRect();
    _dailyTipSize = {width: r.width, height: r.height};
  }
  _placeDailyTip(tip, col.getBoundingClientRect());
}

function _hideDailyTip() {
  if (_dailyTip) _dailyTip.classList.remove('is-on');
  _dailyTipCol = null;
}

let _dailyHoverBound = false;
function _bindDailyHover() {
  const box = document.getElementById('stats-daily');
  if (!box || _dailyHoverBound) return;
  _dailyHoverBound = true;
  // Позиция пересчитывается на каждом mousemove, а не только при смене
  // столбца: после прокрутки или смены масштаба курсор остаётся в той же
  // колонке, и подсказка замерла бы в старой точке.
  box.addEventListener('mousemove', e => {
    const col = e.target && e.target.closest ? e.target.closest('.dyn-col') : null;
    if (col) _showDailyTip(col); else _hideDailyTip();
  });
  box.addEventListener('mouseleave', _hideDailyTip);
  // Прокрутка и масштаб двигают столбцы без события mousemove — подсказку
  // лучше спрятать, чем оставить висеть в устаревшей точке.
  const panel = document.getElementById('p-stats');
  if (panel && panel.addEventListener) panel.addEventListener('scroll', _hideDailyTip, {passive: true});
  if (window.addEventListener) window.addEventListener('resize', _hideDailyTip);
}

function renderDailyDynamics(payload) {
  const box = document.getElementById('stats-daily');
  if (!box) return;
  // Последний удачный ответ — им предзаполнены поля периода, в том числе во
  // время загрузки следующего.
  if (payload && payload.series) _dailyPayload = payload;
  box.innerHTML = dailySectionHTML(payload);
  // Ряд может быть длинным (месяц, диапазон): показываем свежие дни, а не
  // начало периода, которое уже прокрутилось влево.
  const cols = box.querySelector ? box.querySelector('.dyn-cols') : null;
  if (cols) cols.scrollLeft = cols.scrollWidth;
  _bindDailyHover();
}

async function loadDailyDynamics() {
  const box = document.getElementById('stats-daily');
  if (!box) return;
  // Первый показ — сразу заголовок с переключателем периода, чтобы блок не
  // появлялся «из ничего» после ответа сервера.
  if (!box.innerHTML) renderDailyDynamics({days: _dailyRange.days, loading: true});
  // Счётчик, а не флаг занятости: пока грузится 7 дней, пользователь может
  // выбрать 30, и ответ на старый запрос не должен перерисовать новый период.
  const seq = ++_dailySeq;
  try {
    const r = await fetch('/stats/daily?' + _dailyQuery());
    const data = await r.json();
    if (seq !== _dailySeq) return;
    renderDailyDynamics(data);
  } catch (e) {
    if (seq === _dailySeq) renderDailyDynamics(null);
  }
}

// Перезапрос с тем же состоянием: заголовок и поля периода видны сразу.
function _reloadDaily() {
  renderDailyDynamics({days: _dailyRange.days, loading: true});
  loadDailyDynamics();
}

function setDailyRange(n) {
  const days = Number(n) || DAILY_DEFAULT_DAYS;
  if (_dailyRange.kind === 'days' && days === _dailyRange.days) return;
  _dailyRange = {kind: 'days', days: days, month: '', from: '', to: ''};
  _reloadDaily();
}

// Календарный месяц целиком. Очистка поля возвращает набор 7/14/30 дней:
// пустой контрол рядом с активным периодом читался бы как «ничего выбрано».
function setDailyMonth(month) {
  const value = String(month || '').trim();
  if (!value) {
    if (_dailyRange.kind !== 'month') return;
    _dailyRange = {kind: 'days', days: _dailyRange.days, month: '', from: '', to: ''};
    _reloadDaily();
    return;
  }
  if (_dailyRange.kind === 'month' && value === _dailyRange.month) return;
  _dailyRange = {kind: 'month', days: _dailyRange.days, month: value, from: '', to: ''};
  _reloadDaily();
}

function _dateInputValue(id) {
  const el = document.getElementById(id);
  const v = el && el.value ? String(el.value) : '';
  return /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '';
}

function applyDailyCustom() {
  const from = _dateInputValue('dyn-from');
  const to = _dateInputValue('dyn-to');
  if (!from || !to) return;
  const a = from <= to ? from : to;      // поля, заполненные наоборот, — не ошибка
  const b = from <= to ? to : from;
  if (_dailyRange.kind === 'custom' && a === _dailyRange.from && b === _dailyRange.to) return;
  _dailyRange = {kind: 'custom', days: _dailyRange.days, month: '', from: a, to: b};
  _dailyCustomOpen = true;
  _reloadDaily();
}

function toggleDailyCustom() {
  _dailyCustomOpen = !_dailyCustomOpen;
  const panel = document.getElementById('dyn-custom');
  if (panel) panel.hidden = !_dailyCustomOpen;
  const btn = document.querySelector ? document.querySelector('.dyn-more') : null;
  if (btn) btn.setAttribute('aria-expanded', String(_dailyCustomOpen));
}

// ═══════════════════════════════════════════
//  localStorage settings
// ═══════════════════════════════════════════
const SETTINGS_KEY = 'yp_settings_v1';
const PRESETS_KEY  = 'yp_presets_v1';

function getCurrentSettings() {
  return {
    queries:  document.getElementById('f-queries').value,
    // Полный пресет: города и всё, что видно в форме.
    cities:   [...selectedCities],
    source:   dataSource,
    excel:    document.getElementById('f-excel').checked,
    json:     document.getElementById('f-json').checked,
    csv:      document.getElementById('f-csv').checked,
    map:      document.getElementById('f-map').checked,
    pages:    document.getElementById('f-pages').value,
    workers:  document.getElementById('f-workers').value,
    queryWorkers: document.getElementById('f-query-workers').value,
    maxCandidates: document.getElementById('f-max-candidates').value,
    grid:     _gridMode === 'manual',
    grad:     document.getElementById('f-grad').value,
    gstep:    document.getElementById('f-gstep').value,
    collapseChains: document.getElementById('f-collapse-chains').checked,
    rawMode:  (document.getElementById('f-raw-mode')||{}).value || 'keep',
    chainKey: (document.getElementById('f-chain-key')||{}).value || 'name_city',
    socialMode: socialMode,
    // Tiles only exist in «С соцсетями» — the interface clears them otherwise.
    requiredSocials: socialMode === 'with_socials' ? [...requiredSocials] : [],
    vkCheck:  !!(document.getElementById('f-vk-check')||{}).checked,
    vkMode:   vkMode,
    vkMaxDays: (document.getElementById('f-vk-max-days')||{}).value || 0,
    vkMinFollowers: (document.getElementById('f-vk-min-followers')||{}).value || 0,
    sortScore: (document.getElementById('f-sort-score')||{}).checked !== false,
    minScore: (document.getElementById('f-min-score')||{}).value || 0,
    // Пресет забирает и чёрный список слов — иначе он «терял» половину
    // настроек этапа 2.
    blacklist: [...blacklistWords],
    // «🎯 Тип компании»: и галочка, и выбранный период (галочка выключена —
    // период всё равно помним, чтобы пресет возвращал настройку целиком).
    onlySingle: onlySingleChecked(),
    onlyNew: !!newMonthsValue(),
    onlyNewPeriod: newMonthsPeriod(),
    parseMode: parseMode,
    continueMode: (document.getElementById('f-continue')||{}).checked || false,
    continueLimit: parseInt((document.getElementById('f-continue-limit')||{}).value, 10) || 5,
     // API keys are entered for the current run only and are never persisted.
  };
}

function applySettings(s) {
  if (!s) return;
  if (s.queries  != null) {
    document.getElementById('f-queries').value = s.queries;
    updateQueriesCounter();
    updateClearAllBtn();
    updateBasicSummary();
    updateRunBtnState();
  }
  // Cities: presets restore them, localStorage keeps the old behaviour
  // (fresh start each reload) — the caller passes {cities:null} there.
  if (s.cities != null && Array.isArray(s.cities)) {
    selectedCities = s.cities.filter(c => typeof c === 'string' && c.trim()).slice(0, 50);
    renderCityTags();
  }
  if (s.source === 'yandex' || s.source === '2gis') setDataSource(s.source);
  if (s.excel    != null) { document.getElementById('f-excel').checked = s.excel;   document.getElementById('f-excel').closest('.chk').classList.toggle('on', s.excel); }
  if (s.json     != null) { document.getElementById('f-json').checked  = s.json;    document.getElementById('f-json').closest('.chk').classList.toggle('on', s.json); }
  if (s.csv      != null) { document.getElementById('f-csv').checked   = s.csv;     document.getElementById('f-csv').closest('.chk').classList.toggle('on', s.csv); }
  if (s.map      != null) { document.getElementById('f-map').checked   = s.map;     document.getElementById('f-map').closest('.chk').classList.toggle('on', s.map); }
  if (s.pages    != null) document.getElementById('f-pages').value    = s.pages;
  updatePagesCapNote();
  if (s.workers  != null) document.getElementById('f-workers').value  = s.workers;
  if (s.queryWorkers != null) document.getElementById('f-query-workers').value = s.queryWorkers;
  if (s.maxCandidates != null) document.getElementById('f-max-candidates').value = s.maxCandidates;
  if (s.vkCheck != null) { const cb = document.getElementById('f-vk-check'); if (cb) { cb.checked = !!s.vkCheck; onVkCheckChange(); } }
  if (s.vkMode) setVkMode(s.vkMode);
  if (s.vkMaxDays != null) { const el = document.getElementById('f-vk-max-days'); if (el) el.value = s.vkMaxDays; }
  if (s.vkMinFollowers != null) { const el = document.getElementById('f-vk-min-followers'); if (el) el.value = s.vkMinFollowers; }
  if (s.sortScore != null) { const cb = document.getElementById('f-sort-score'); if (cb) cb.checked = !!s.sortScore; }
  if (s.minScore != null) { const el = document.getElementById('f-min-score'); if (el) { el.value = s.minScore; onMinScoreInput(); } }
  if (Array.isArray(s.blacklist)) setBlacklistWords(s.blacklist);
  if (s.chainKey != null) { const el = document.getElementById('f-chain-key'); if (el) el.value = s.chainKey; }
  if (s.grid     != null) setGridMode(s.grid ? 'manual' : 'whole');
  if (s.grad     != null) document.getElementById('f-grad').value    = s.grad;
  if (s.gstep    != null) document.getElementById('f-gstep').value   = s.gstep;
  if (s.grad != null || s.gstep != null) onGridSlider();
  if (s.collapseChains != null) { document.getElementById('f-collapse-chains').checked = s.collapseChains; document.getElementById('f-collapse-chains').closest('.chk').classList.toggle('on', s.collapseChains); }
  if (s.rawMode != null) { const rm = document.getElementById('f-raw-mode'); if (rm) rm.value = s.rawMode; }
  if (s.socialMode) setSocialMode(s.socialMode);
  // Restore the tiles after the mode radio — only «С соцсетами» keeps them.
  if (s.socialMode === 'with_socials' && Array.isArray(s.requiredSocials)) {
    requiredSocials.clear();
    document.querySelectorAll('#social-net-chk-grid .soc-tile').forEach(t => {
      t.classList.remove('on');
      const cb = t.querySelector('input[type=checkbox]');
      if (cb) cb.checked = false;
    });
    s.requiredSocials.forEach(key => {
      // data-soc-key lives on the input INSIDE the tile label
      const inp = document.querySelector('#social-net-chk-grid input[data-soc-key="' + key + '"]');
      const tile = inp ? inp.closest('.soc-tile') : null;
      if (tile) toggleRequiredSocial(key, tile);
    });
    updateSocialFilterHint();
  }
  if (s.parseMode) setParseMode(s.parseMode);
  if (s.onlyNewPeriod != null) {
    const m = document.getElementById('f-new-months');
    if (m && String(s.onlyNewPeriod) in COMPANY_TYPE_PERIODS) m.value = String(s.onlyNewPeriod);
  }
  if (s.onlySingle != null) {
    const cb = document.getElementById('f-only-single');
    if (cb) cb.checked = !!s.onlySingle;
  }
  if (s.onlyNew != null) {
    const cb = document.getElementById('f-only-new');
    if (cb) cb.checked = !!s.onlyNew;
  }
  if (s.onlySingle != null || s.onlyNew != null || s.onlyNewPeriod != null) syncCompanyTypeUi();
  if (s.continueMode != null) {
    const cb = document.getElementById('f-continue');
    if (cb) cb.checked = !!s.continueMode;
    onContinueToggle();
  }
  if (s.continueLimit != null) {
    const lim = document.getElementById('f-continue-limit');
    if (lim) lim.value = s.continueLimit;
  }
   // Do not restore API keys from browser storage.
}

function saveSettings() {
  const settings = getCurrentSettings();
  // Clean keys saved by older versions of the application.
  delete settings.apikey;
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

// ═══════════════════════════════════════════
//  Presets
// ═══════════════════════════════════════════
function getPresets() {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY)) || []; } catch { return []; }
}
function savePresets(p) { localStorage.setItem(PRESETS_KEY, JSON.stringify(p)); }

function renderPresets() {
  // Presets live in a static block at the TOP of the sidebar (under API
  // keys) as a dropdown — discoverable before any accordion is opened.
  const wrap = document.getElementById('preset-dd-wrap');
  const list = document.getElementById('preset-dd-list');
  const hint = document.getElementById('preset-block-hint');
  const presets = getPresets();
  if (!wrap || !list) return;
  if (!presets.length) {
    wrap.hidden = true;
    list.innerHTML = '';                      // drop stale items from the last render
    if (hint) hint.textContent = 'Пресетов пока нет — настройте поиск и сохраните его кнопкой «+ Новый». Хранятся в этом браузере.';
    return;
  }
  if (hint) hint.textContent = 'Выберите пресет — все настройки подставятся автоматически. Хранятся в этом браузере.';
  wrap.hidden = false;
  list.innerHTML = presets.map((p, i) => {
    const safeName = String(p.name).replace(/"/g, '&quot;');
    return '<div class="preset-dd-item" role="option" tabindex="0" data-i="' + i + '"'
      + ' title="Применить пресет «' + safeName + '»">'
      + '<span class="preset-dd-name">' + safeName + '</span>'
      + '<span class="preset-dd-actions">'
      + '<button type="button" class="preset-dd-edit" title="Перезаписать пресет текущими настройками формы" aria-label="Редактировать пресет" data-edit="' + i + '">' + UI_ICONS.pencil + '</button>'
      + '<button type="button" class="preset-dd-del" title="Удалить пресет" aria-label="Удалить пресет" data-del="' + i + '">' + UI_ICONS.x + '</button>'
      + '</span>'
      + '</div>';
  }).join('');
  list.querySelectorAll('.preset-dd-item').forEach(item => {
    item.addEventListener('click', e => {
      if (e.target.closest('.preset-dd-del') || e.target.closest('.preset-dd-edit')) return;   // manage, not apply
      closePresetDropdown();
      loadPreset(+item.dataset.i);
    });
    item.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); closePresetDropdown(); loadPreset(+item.dataset.i); }
    });
  });
  list.querySelectorAll('.preset-dd-edit').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const idx = +btn.dataset.edit;
      const preset = getPresets()[idx];
      if (!preset) return;
      if (!(await uiConfirm('Перезаписать пресет «' + preset.name + '» текущими настройками формы?', 'Редактировать пресет', 'Перезаписать', false))) return;
      const presets = getPresets();
      presets[idx] = {name: preset.name, settings: getCurrentSettings()};
      savePresets(presets);
      markAppliedPreset(preset.name);
      showToast('Пресет «' + preset.name + '» обновлён', 'success');
    });
  });
  list.querySelectorAll('.preset-dd-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const idx = +btn.dataset.del;
      const preset = getPresets()[idx];
      if (!preset) return;
      if (!(await uiConfirm('Удалить пресет «' + preset.name + '»?', 'Удалить пресет', 'Удалить'))) return;
      deletePreset(idx);
      showToast('Пресет «' + preset.name + '» удалён', 'success');
    });
  });
}

function togglePresetDropdown(force) {
  const btn  = document.getElementById('preset-dd-btn');
  const list = document.getElementById('preset-dd-list');
  if (!btn || !list) return;
  const open = typeof force === 'boolean' ? force : list.hidden;
  list.hidden = !open;
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  btn.classList.toggle('open', open);
}

function closePresetDropdown() {
  togglePresetDropdown(false);
}

// Outside click + Escape close the dropdown.
(function initPresetDropdown() {
  const btn  = document.getElementById('preset-dd-btn');
  const wrap = document.getElementById('preset-dd-wrap');
  if (btn) btn.addEventListener('click', () => togglePresetDropdown());
  if (wrap) {
    document.addEventListener('click', e => {
      if (!wrap.hidden && !wrap.contains(e.target)) closePresetDropdown();
    });
  }
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && wrap && !wrap.hidden) closePresetDropdown();
  });
})();

// Show the applied preset's name in the closed dropdown.
function markAppliedPreset(name) {
  const cur = document.getElementById('preset-dd-current');
  if (cur) cur.textContent = name || 'Выберите пресет…';
  const btn = document.getElementById('preset-dd-btn');
  if (btn) btn.classList.toggle('has-selection', !!name);
}

// ── In-app «save preset» modal (replaces the browser prompt()) ──────
// Same .ui-modal styling as uiConfirm; validates the name, shows how many
// of the 10 preset slots are used, and supports Enter/Esc.
function openPresetModal() {
  const existing = getPresets();
  const overlay = document.createElement('div');
  overlay.className = 'ui-modal-overlay';
  overlay.innerHTML = `
    <div class="ui-modal preset-modal">
      <h3>Сохранить пресет</h3>
      <p>В текущий пресет войдут запросы, города, источник, форматы и все параметры сбора.</p>
      <input type="text" id="preset-name-input" maxlength="40" placeholder="Например: Кафе Уфа, 2GIS" autocomplete="off">
      <div class="preset-modal-meta">Сохранённых пресетов: ${existing.length} из 10</div>
      <div class="ui-modal-btns">
        <button type="button" class="m-cancel">Отмена</button>
        <button type="button" class="m-ok">${UI_ICONS.save}Сохранить</button>
      </div>
    </div>`;
  const done = val => { overlay.remove(); document.removeEventListener('keydown', onKey, true); if (val) finishSavePreset(val); };
  const onKey = e => {
    if (e.key === 'Escape') { e.stopPropagation(); done(false); }
    else if (e.key === 'Enter' && input.value.trim()) { e.stopPropagation(); done(input.value.trim()); }
  };
  const finishSavePreset = name => {
    const presets = getPresets();
    if (presets.some(p => p.name === name)) {
      showToast('Пресет «' + name + '» уже существует — выберите другое имя', 'error');
      openPresetModal();                       // reopen pre-filled
      const again = document.getElementById('preset-name-input');
      if (again) again.value = name;
      return;
    }
    presets.unshift({name, settings: getCurrentSettings()});
    savePresets(presets.slice(0, 10));
    renderPresets();
    showToast('Пресет «' + name + '» сохранён — примените его из блока «Мои пресеты» наверху', 'success');
  };
  const input = overlay.querySelector('#preset-name-input');
  overlay.querySelector('.m-cancel').onclick = () => done(false);
  overlay.querySelector('.m-ok').onclick = () => {
    const name = input.value.trim();
    if (!name) { input.classList.add('field-invalid'); input.focus(); return; }
    done(name);
  };
  overlay.addEventListener('click', e => { if (e.target === overlay) done(false); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(overlay);
  input.focus();
}

// ── Grid magic-wand listener ─────────────────────────────────
// stopPropagation keeps the click from bubbling into any accordion/section
// handler (a click here used to collapse the whole «Глубина поиска» block).
(function initGridWand() {
  const wand = document.getElementById('grid-wand-btn');
  if (!wand) return;
  wand.addEventListener('click', e => {
    e.stopPropagation();
    try { gridAutoTune(); }
    catch (err) { console.error('gridAutoTune failed:', err); }
  });
})();

// Kept as an alias: older presets chips / docs referenced savePreset().
function savePreset() { openPresetModal(); }

function loadPreset(i) {
  const p = getPresets()[i];
  if (p) {
    applySettings(p.settings);
    markAppliedPreset(p.name);
    showToast('Пресет «' + p.name + '» применён — все настройки подставлены', 'success');
  }
}

function deletePreset(i) {
  const p = getPresets();
  const deletedName = p[i] ? p[i].name : null;
  p.splice(i, 1);
  savePresets(p);
  renderPresets();
  if (deletedName) {
    const cur = document.getElementById('preset-dd-current');
    if (cur && cur.textContent === deletedName) markAppliedPreset(null);
  }
}

// ── Reset the whole form to factory defaults ─────────────────
// Mirrors the HTML defaults: opposite of applySettings. Also clears the
// «applied preset» highlight — after a reset no preset is active.
const FORM_DEFAULTS = {
  queries: '', source: 'yandex', excel: true, json: true, csv: false, map: false,
  pages: 1, workers: 20, queryWorkers: 2, maxCandidates: 200,
  grid: false, grad: 20, gstep: 5,
  validate: false, resume: false, collapseChains: false, rawMode: 'keep', chainKey: 'name_city',
  socialMode: 'all', requiredSocials: [], fetchSocials: true, parseMode: 'without_website',
  vkCheck: false, vkMode: 'all', vkMaxDays: 0, vkMinFollowers: 0,
  sortScore: true, minScore: 0,
  continueMode: false, continueLimit: 5,
  // Сброс к значениям по умолчанию чистит и чёрный список слов.
  blacklist: [],
  // «🎯 Тип компании»: по умолчанию оба фильтра выключены, период — 6 мес.
  onlySingle: false, onlyNew: false, onlyNewPeriod: '6',
};

function resetToDefaults() {
  applySettings({...FORM_DEFAULTS, cities: []});
  markAppliedPreset(null);
  saveSettings();                 // keep localStorage in sync with the reset
  updateQueriesCounter();
  updateClearAllBtn();
  updateBasicSummary();
  updateRunBtnState();
  showToast('Настройки сброшены к значениям по умолчанию', 'success');
}

// ═══════════════════════════════════════════
//  Browser Notifications
// ═══════════════════════════════════════════
// ── Настройки: чтение / запись / состояние ───────────────────
// Ключ и форма — `notifications_settings`:
//   {enabled, city_complete, search_complete}
// Битый JSON, чужой тип поля или недоступный localStorage не должны
// оставлять пользователя без уведомлений вообще — откатываемся к дефолтам.
function _notifyFlag(value, fallback) {
  return typeof value === 'boolean' ? value : fallback;
}

// Громкость — доля 0…1. Ни число строкой, ни мусор из старой версии
// настроек не должны превращать звук в «то играет, то нет».
function _notifyVolume(value, fallback) {
  const num = (typeof value === 'number') ? value : parseFloat(value);
  if (!isFinite(num)) return fallback;
  return Math.min(1, Math.max(0, num));
}

// Пресет проверяем по реестру: удалённый в новой версии id не должен
// оставлять пользователя без звука.
function _notifySound(value, fallback) {
  return (typeof value === 'string' && Object.prototype.hasOwnProperty.call(SOUND_PRESETS, value))
    ? value : fallback;
}

function loadNotifySettings() {
  let raw = null;
  try {
    if (typeof localStorage !== 'undefined' && localStorage) raw = localStorage.getItem(NOTIFY_KEY);
  } catch (e) { raw = null; }        // приватный режим: настройки доживут до перезагрузки
  let parsed = null;
  try { parsed = raw ? JSON.parse(raw) : null; } catch (e) { parsed = null; }
  const src = (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : {};
  notifySettings = {
    enabled:         _notifyFlag(src.enabled,         NOTIFY_DEFAULTS.enabled),
    city_complete:   _notifyFlag(src.city_complete,   NOTIFY_DEFAULTS.city_complete),
    search_complete: _notifyFlag(src.search_complete, NOTIFY_DEFAULTS.search_complete),
    volume:          _notifyVolume(src.volume,        VOLUME_DEFAULT),
    sound_city:      _notifySound(src.sound_city,     SOUND_DEFAULTS.city_complete),
    sound_search:    _notifySound(src.sound_search,   SOUND_DEFAULTS.search_complete),
  };
  notifyDraft = Object.assign({}, notifySettings);
  _syncNotifyGlobals();
  return notifySettings;
}

function saveNotifySettings() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) {
      localStorage.setItem(NOTIFY_KEY, JSON.stringify(notifySettings));
    }
  } catch (e) { /* нет доступа к хранилищу — молча живём до перезагрузки */ }
  _syncNotifyGlobals();
  updateNotifyBtn();
  return notifySettings;
}

// Старый глобал остаётся мастер-флагом: его читают sendNotification
// и урезанные функции в node-тестах.
function _syncNotifyGlobals() {
  notificationsEnabled = !!notifySettings.enabled;
}

function notifyAllowed(kind) {
  return !!notifySettings.enabled && !!notifySettings[kind];
}

// all_off | partial | all_on — нужно кнопке и подписи состояния
function notifyState() {
  if (!notifySettings.enabled) return 'all_off';
  const on = ['city_complete', 'search_complete'].filter(k => notifySettings[k]).length;
  if (on === 0) return 'all_off';
  return on === 2 ? 'all_on' : 'partial';
}

function notifyStateLabel() {
  // Короткая подпись: режимы (города/поиск) перечислены в tooltip, в шапке
  // им хватает точки-индикатора и слова «Уведомления».
  const st = notifyState();
  if (st === 'all_off') return 'Уведомления';
  if (st === 'all_on')  return 'Уведомления';
  return 'Уведомления';
}

// Подпись кнопки показывает и состояние типов, и проблему с разрешением:
// раньше в состоянии «запрещено» состояние типов пропадало вовсе.
function notifyStateTitle() {
  const c = notifySettings.city_complete ? 'вкл' : 'выкл';
  const s = notifySettings.search_complete ? 'вкл' : 'выкл';
  let t = `Города: ${c} · Поиск: ${s}. Клик — настройки.`;
  if (!('Notification' in window)) {
    t = 'Браузер не поддерживает системные уведомления — покажем тост. ' + t;
  } else if (Notification.permission === 'denied') {
    t = 'Уведомления запрещены в браузере — покажем тост вместо окна. ' + t;
  }
  return t;
}

function updateNotifyBtn() {
  const btn  = document.getElementById('btn-notify');
  const icon = document.getElementById('notify-icon');
  const txt  = document.getElementById('notify-txt');
  if (!btn || !icon || !txt) return;
  const st   = notifyState();
  const warn = !('Notification' in window) || Notification.permission === 'denied';
  btn.className = warn ? 'denied' : (notifySettings.enabled ? 'granted' : '');
  icon.innerHTML = st === 'all_off' ? UI_ICONS.bellOff : UI_ICONS.bell;
  // Точка-индикатор: зелёная — хоть один тип уведомлений включён, серая —
  // все выключены. Подпись в шапке одна («Уведомления»), состояние — точкой
  // и в tooltip: длинный режим «Уведомления: поиск» удлинял шапку.
  const dot = st === 'all_off' ? ' is-off' : '';
  txt.innerHTML = escapeHtml(notifyStateLabel())
    + `<i class="notify-dot${dot}" aria-hidden="true"></i>`
    + (warn ? ' ' + UI_ICONS.warn : '');
  btn.title        = notifyStateTitle();
  const pop = document.getElementById('notify-pop');
  btn.setAttribute('aria-expanded', pop && !pop.hidden ? 'true' : 'false');
}

function _renderNotifyPermHint() {
  const el = document.getElementById('notify-perm-hint');
  if (!el) return;
  let msg = '';
  if (!('Notification' in window)) {
    msg = 'Браузер не поддерживает системные уведомления: вместо окна покажем тост. Звук работает.';
  } else if (Notification.permission === 'denied') {
    msg = 'Браузер запретил уведомления: окна не показываются, вместо них — тост. Звук работает. '
        + 'Разрешить можно в настройках браузера для этой страницы.';
  } else if (Notification.permission === 'default') {
    msg = 'Разрешение на уведомления спросим при первом сохранении. Звук работает и без него.';
  }
  el.textContent = msg;
  el.hidden = !msg;
}

// ── Отправка: окно, иначе тост (событие не теряется) ─────────
// Окно уходит, только когда браузер разрешил уведомления; если нет — тост,
// а подсказку про разрешение добавляем один раз, чтобы не повторяться.
function sendNotification(title, body) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return false;
  if (!notificationsEnabled) return false;
  try {
    const n = new Notification(title, {body});
    n.onclick = () => { window.focus(); n.close(); };
    return true;
  } catch (e) { return false; }   // браузер может блокировать без service worker
}

function fmtDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total} сек`;
  const m = Math.floor(total / 60);
  if (m < 60) return `${m} мин ${String(total % 60).padStart(2, '0')} сек`;
  return `${Math.floor(m / 60)} ч ${String(m % 60).padStart(2, '0')} мин`;
}

function _notifyOrgWord(n) {
  return (typeof pluralNum === 'function')
    ? pluralNum(n, 'организация', 'организации', 'организаций')
    : 'организаций';
}

function _notifyBoth(title, body) {
  if (sendNotification(title, body)) return true;
  const hint = _notifyHintShown ? '' : ' Разрешите уведомления в браузере, чтобы получать окна.';
  _notifyHintShown = true;
  try { showToast(`${title} — ${body}${hint}`, 'info'); } catch (e) { /* тостов нет (тесты) */ }
  return false;
}

function notifyCityComplete(info) {
  if (!notifyAllowed('city_complete')) return false;
  playCityDoneSound();
  const skipped = info.status === 'skipped';
  const title = skipped
    ? `⏭ Город «${info.name}» пропущен`
    : `🏙 Город «${info.name}» обработан`;
  const body = `${info.idx}/${info.total} · Найдено: ${info.records} ${_notifyOrgWord(info.records)}`;
  _notifyBoth(title, body);
  return true;
}

function notifySearchComplete(info) {
  if (!notifyAllowed('search_complete')) return false;
  playDoneSound();
  const body = `Городов: ${info.cities} · Найдено: ${info.found} ${_notifyOrgWord(info.found)}`
             + ` · ${fmtDuration(info.seconds)}`;
  _notifyBoth('✅ Поиск завершён', body);
  return true;
}

// ── Completion sounds (Web Audio API — тоны генерируются кодом) ──
// Один общий контекст на всю страницу: прежний код создавал новый
// AudioContext на каждый сигнал, упирался в лимит браузера и не всегда
// успевал разблокироваться после жеста.
let _audioCtx = null;

function audioCtx() {
  if (_audioCtx) return _audioCtx;
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (!Ctor) return null;
  try { _audioCtx = new Ctor(); } catch (e) { return null; }
  return _audioCtx;
}

// Autoplay-политика: контекст стартует «suspended» до первого жеста.
function unlockAudio() {
  const ctx = audioCtx();
  if (ctx && ctx.state === 'suspended' && typeof ctx.resume === 'function') {
    try { ctx.resume(); } catch (e) { /* браузер не дал — тишина */ }
  }
}

function _tone(ctx, freq, at, dur, gain, type) {
  try {
    const osc = ctx.createOscillator();
    const g   = ctx.createGain();
    osc.connect(g);
    g.connect(ctx.destination);
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    // Громкость 0 — это валидная настройка (звук выключен), а exponentialRamp
    // от нуля браузеры считают ошибкой: держим нижнюю границу.
    g.gain.setValueAtTime(Math.max(0.0001, gain), at);
    g.gain.exponentialRampToValueAtTime(0.001, at + dur);
    osc.start(at);
    osc.stop(at + dur);
  } catch (e) { /* Web Audio unavailable */ }
}

// notes: частоты или пары [основная, обертон]; opts: gain/step/tail/type/volume
function _chime(notes, opts) {
  const ctx = audioCtx();
  if (!ctx) return false;
  unlockAudio();
  const o = opts || {};
  const vol = _notifyVolume(o.volume, 1);          // множитель громкости (0…1)
  const gain = (o.gain || 0.2) * vol;
  const step = o.step || 0.15, tail = o.tail || 0.35;
  notes.forEach((note, i) => {
    const pair = Array.isArray(note);
    const at = ctx.currentTime + i * step;
    _tone(ctx, pair ? note[0] : note, at, tail, gain, o.type || 'sine');
    if (pair && note[1]) _tone(ctx, note[1], at, tail, gain * 0.35, 'triangle');
  });
  return true;
}

// Пресет по id (неизвестный — дефолт своего типа, чтобы звук не пропадал).
function _preset(id, fallback) {
  return SOUND_PRESETS[id] || SOUND_PRESETS[fallback] || SOUND_PRESETS[SOUND_DEFAULTS.city_complete];
}

function _soundKey(kind) {
  return kind === 'search' ? 'sound_search' : 'sound_city';
}

// Единая точка воспроизведения: пресет и громкость берутся из настроек, а
// для предпросмотра — из черновика попапа (слышно ровно то, что сохранится).
function playNotifySound(kind, opts) {
  const o = opts || {};
  const src = o.draft ? notifyDraft : notifySettings;
  const fallback = kind === 'search' ? SOUND_DEFAULTS.search_complete : SOUND_DEFAULTS.city_complete;
  const id = _notifySound(src[_soundKey(kind)], fallback);
  const preset = _preset(id, fallback);
  return _chime(preset.notes, {
    gain: preset.gain, step: preset.step, tail: preset.tail, type: preset.type,
    volume: _notifyVolume(src.volume, VOLUME_DEFAULT),
  });
}

// Город: по умолчанию мягкий короткий «динь»; поиск — финальная мелодия.
function playCityDoneSound() {
  return playNotifySound('city');
}

function playDoneSound() {
  return playNotifySound('search');
}

// Кнопка «▶ Прослушать» в попапе — играет выбранный в черновике звук.
function previewNotifySound(kind) {
  return playNotifySound(kind, { draft: true });
}

// ── Попап настроек ──────────────────────────────────
function _renderNotifyPopover() {
  notifyDraft = Object.assign({}, notifySettings);
  _setSwitch(document.getElementById('notify-master'), notifyDraft.enabled);
  _syncSubSwitches();
  _renderSoundPickers();
  _renderNotifyPermHint();
  _syncNotifySaveBtn();
}

// ── Звук: пресет на каждый тип + громкость ──────────────────
// Варианты списка берём из реестра пресетов: подписи живут в одном месте,
// и добавленный пресет появляется в попапе сам.
function _fillSoundSelect(sel, value) {
  if (!sel) return;
  sel.innerHTML = '';                    // перерисовка не должна копить опции
  Object.keys(SOUND_PRESETS).forEach(id => {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = SOUND_PRESETS[id].label;
    opt.selected = (id === value);
    sel.appendChild(opt);
  });
  sel.value = value;
}

function _renderSoundPickers() {
  _fillSoundSelect(document.getElementById('notify-sound-city'), notifyDraft.sound_city);
  _fillSoundSelect(document.getElementById('notify-sound-search'), notifyDraft.sound_search);
  _renderVolume();
}

function _renderVolume() {
  const pct = Math.round(_notifyVolume(notifyDraft.volume, VOLUME_DEFAULT) * 100);
  const el  = document.getElementById('notify-volume');
  const out = document.getElementById('notify-vol-val');
  if (el) el.value = String(pct);
  if (out) out.textContent = pct + '%';
}

// Смена пресета сразу его проигрывает — выбор звука без прослушивания
// был бы выбором наугад.
function notifySoundChanged(kind) {
  const key     = _soundKey(kind);
  const sel     = document.getElementById('notify-sound-' + (kind === 'search' ? 'search' : 'city'));
  const fallback = kind === 'search' ? SOUND_DEFAULTS.search_complete : SOUND_DEFAULTS.city_complete;
  if (key in notifyDraft) notifyDraft[key] = _notifySound(sel ? sel.value : '', fallback);
  _syncNotifySaveBtn();
  previewNotifySound(kind);
}

function _volumeFromSlider(el) {
  const raw = el ? parseFloat(el.value) : NaN;
  if (!isFinite(raw)) return VOLUME_DEFAULT;
  return Math.min(1, Math.max(0, raw / 100));
}

// oninput — только цифра рядом с ползунком; onchange (отпустили) — прослушка.
function notifyVolumeInput() {
  notifyDraft.volume = _volumeFromSlider(document.getElementById('notify-volume'));
  _renderVolume();
  _syncNotifySaveBtn();
}

function notifyVolumeCommit() {
  notifyVolumeInput();
  previewNotifySound('city');
}

function _setSwitch(el, on) {
  if (!el) return;
  el.classList.toggle('on', !!on);
  el.setAttribute('aria-checked', on ? 'true' : 'false');
}

// Подтумблеры спят, пока выключен мастер, но их значения в черновике живут:
// включили мастер обратно — выбор типов вернулся.
function _syncSubSwitches() {
  [['notify-city', 'city_complete'], ['notify-search', 'search_complete']].forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = !notifyDraft.enabled;
    _setSwitch(el, notifyDraft[key]);
  });
}

function notifyDraftDirty() {
  return notifyDraft.enabled         !== notifySettings.enabled
      || notifyDraft.city_complete   !== notifySettings.city_complete
      || notifyDraft.search_complete !== notifySettings.search_complete
      || _notifyVolume(notifyDraft.volume, VOLUME_DEFAULT)
         !== _notifyVolume(notifySettings.volume, VOLUME_DEFAULT)
      || notifyDraft.sound_city      !== notifySettings.sound_city
      || notifyDraft.sound_search    !== notifySettings.sound_search;
}

function _syncNotifySaveBtn() {
  const btn = document.getElementById('notify-save');
  if (btn) btn.disabled = !notifyDraftDirty();
}

function toggleNotifySetting(key) {
  if (!(key in notifyDraft)) return;
  if (key !== 'enabled' && !notifyDraft.enabled) return;   // спят вместе с мастером
  notifyDraft[key] = !notifyDraft[key];
  const id = key === 'enabled' ? 'notify-master'
           : (key === 'city_complete' ? 'notify-city' : 'notify-search');
  _setSwitch(document.getElementById(id), notifyDraft[key]);
  _syncSubSwitches();
  _syncNotifySaveBtn();
}

function toggleNotifyPopover(ev) {
  if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation();
  const pop = document.getElementById('notify-pop');
  if (!pop) return;
  if (pop.hidden) openNotifyPopover(); else closeNotifyPopover();
}

function openNotifyPopover() {
  const pop = document.getElementById('notify-pop');
  if (!pop) return;
  _renderNotifyPopover();
  pop.hidden = false;
  updateNotifyBtn();
  const first = document.getElementById('notify-master');
  if (first && typeof first.focus === 'function') first.focus();
}

// Закрытие без «Сохранить» — откат черновика к сохранённым настройкам.
function closeNotifyPopover() {
  const pop = document.getElementById('notify-pop');
  if (!pop || pop.hidden) return;
  notifyDraft = Object.assign({}, notifySettings);
  pop.hidden = true;
  updateNotifyBtn();
}

function saveNotifySettingsFromPopover() {
  notifySettings = Object.assign({}, notifyDraft);
  saveNotifySettings();
  _renderNotifyPermHint();
  closeNotifyPopover();
  try { showToast('Настройки сохранены', 'success'); } catch (e) { /* тесты */ }
  // Разрешение спрашиваем ПОСЛЕ применения — жест есть, а звук уже включён.
  if (notifySettings.enabled && ('Notification' in window) && Notification.permission === 'default') {
    Notification.requestPermission().then(() => { updateNotifyBtn(); _renderNotifyPermHint(); });
  }
  return notifySettings;
}

// Клик вне попапа и Esc — то же, что «Отмена»: изменения не применяются.
// Обработчики именованные: их текст проверяют node-тесты.
function _notifyOutsideClick(e) {
  const pop = document.getElementById('notify-pop');
  const btn = document.getElementById('btn-notify');
  if (!pop || pop.hidden) return;
  if (pop.contains(e.target) || (btn && btn.contains(e.target))) return;
  closeNotifyPopover();
}

function _notifyEscape(e) {
  const pop = document.getElementById('notify-pop');
  if (e && e.key === 'Escape' && pop && !pop.hidden) closeNotifyPopover();
}

document.addEventListener('mousedown', _notifyOutsideClick);
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
const COLS_KEY = 'yp_cols_v1';
const COLS = [
  { idx: 1, key: 'rev',      label: '✓ Просмотрено' },
  { idx: 2, key: 'num',      label: '# Номер' },
  { idx: 3, key: 'name',     label: 'Название' },
  { idx: 4, key: 'category', label: 'Категория' },
  { idx: 5, key: 'address',  label: 'Адрес' },
  { idx: 6, key: 'phone',    label: 'Телефон' },
  { idx: 7, key: 'socials',  label: 'Соцсети' },
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
const TEMPLATE_MAX_VAR_VALUE = 1000;
const TEMPLATE_MAX_VAR_DESC = 200;
const TEMPLATE_MAX_CUSTOM_VARS = 100;

let messageTemplates = [];
let activeTemplateIds = {vk: null, telegram: null, whatsapp: null, instagram: null};
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
    out.push({
      id: String(item.id || '').trim() || ('tpl_' + (i + 1)),
      category: cat, name, text,
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
  TEMPLATE_CATEGORIES.forEach(c => {
    randomTemplateIds[c] = (randomTemplateIds[c] || []).filter(id =>
      alive.has(id) && (messageTemplates.find(t => t.id === id) || {}).category === c);
    if (activeTemplateIds[c]) {
      const t = messageTemplates.find(x => x.id === activeTemplateIds[c]);
      if (!t || t.category !== c) activeTemplateIds[c] = null;
    }
  });
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
          + '<span class="template-name">📝 ' + escapeHtml(t.name) + '</span>'
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
          + '<div class="template-text">' + escapeHtml(t.text) + '</div>'
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
    const t = getActiveTemplateFor(social);
    bulkSel.value = t ? t.id : '';
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
  if (sel) setActiveTemplate(social, sel.value || null);
}

function onSenderTemplateChange() {
  const sel = document.getElementById('s-template');
  if (sel) setActiveTemplate('vk', sel.value || null);
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
    if (t) { t.name = name; t.text = text; t.category = category; t.updated_at = new Date().toISOString(); }
    pruneTemplatePicks();   // смена категории убирает шаблон из чужих наборов
  } else {
    messageTemplates.push({
      id: genTemplateId(), category, name, text,
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
    text: t.text, is_default: false, created_at: new Date().toISOString(),
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
  const text = company ? substituteTemplate(t.text, company) : t.text;
  const ok = await copyText(text);
  if (ok) showToast('📋 Текст скопирован', 'success');
  else showCopyTextModal(text);
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
    if (!column && !value) continue;
    seen.add(name.toLowerCase());
    out.push({
      name, column, value,
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
    box.innerHTML = own.map(v =>
      '<div class="tpl-var-card" data-var="' + escapeHtml(v.name) + '">'
      + '<div class="tpl-var-card-head">'
      + '<code>{' + escapeHtml(v.name) + '}</code>'
      + '<span class="tpl-var-kind">'
      + (v.column ? '📊 столбец: ' + escapeHtml(v.column) : '📝 статичный текст')
      + '</span>'
      + '<span class="tpl-var-actions">'
      + '<button type="button" class="template-more" data-vact="edit" title="Редактировать" aria-label="Редактировать">' + TEMPLATE_ICONS.edit + '</button>'
      + '<button type="button" class="template-more danger" data-vact="del" title="Удалить" aria-label="Удалить">' + TEMPLATE_ICONS.del + '</button>'
      + '</span></div>'
      + (v.description ? '<div class="tpl-var-desc">' + escapeHtml(v.description) + '</div>' : '')
      + '<div class="tpl-var-val">'
      + (v.column ? 'Значение — из столбца «' + escapeHtml(v.column) + '» строки компании.'
                  : '«' + escapeHtml(String(v.value || '').slice(0, 120)) + ((v.value || '').length > 120 ? '…' : '') + '»')
      + '</div></div>').join('');
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
  if (src) src.value = v && v.column ? 'column' : 'text';
  const valEl = document.getElementById('tpl-var-value');
  if (valEl) valEl.value = v && !v.column ? (v.value || '') : '';
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
  const isCol = !!(src && src.value === 'column');
  const tw = document.getElementById('tpl-var-text-wrap');
  const cw = document.getElementById('tpl-var-column-wrap');
  if (tw) tw.hidden = isCol;
  if (cw) cw.hidden = !isCol;
}

function saveVarFromModal() {
  const err = document.getElementById('tpl-var-modal-err');
  const fail = msg => { if (err) { err.textContent = msg; err.hidden = false; } return false; };
  const nameEl = document.getElementById('tpl-var-name');
  const name = (nameEl ? nameEl.value : '').trim();
  const src = document.getElementById('tpl-var-source');
  const isCol = !!(src && src.value === 'column');
  const valEl = document.getElementById('tpl-var-value');
  const colSel = document.getElementById('tpl-var-column');
  const desc = (document.getElementById('tpl-var-desc') || {}).value || '';
  if (!name) return fail('Введите имя переменной');
  if (!_tplEditVarName && !isValidVarName(name)) {
    return fail('Имя: буквы, цифры и подчёркивание; имена встроенных переменных заняты');
  }
  const column = isCol ? ((colSel && colSel.value) || '') : '';
  if (isCol && !column) return fail('Выберите столбец таблицы');
  const value = isCol ? '' : (valEl ? valEl.value : '').trim();
  if (!isCol && !value) return fail('Введите текст, который будет подставляться');
  const list = customVariables || [];
  const existing = list.find(x => x.name.toLowerCase() === name.toLowerCase());
  if (existing && existing.name !== _tplEditVarName) return fail('Переменная с таким именем уже есть');
  if (existing) {
    existing.column = column;
    existing.value = value;
    existing.description = desc.trim();
  } else {
    if (list.length >= TEMPLATE_MAX_CUSTOM_VARS) return fail('Переменных не может быть больше ' + TEMPLATE_MAX_CUSTOM_VARS);
    list.push({
      name, column, value,
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

// ── Интеграция с таблицей ──────────────────────────────────────
// Клик по бейджу соцсети: берём шаблон (в random-режиме — случайный из
// набора, на каждый клик новый выбор), копируем и открываем профиль.
// Нет шаблона — ссылка работает как раньше. В тосте видно, какой шаблон
// использован — при A/B-проверке это сразу видно.
async function onSocialBadgeClick(event, el) {
  const social = el.dataset.social;
  const key = el.dataset.key;
  const rows = (typeof filteredRows !== 'undefined' && filteredRows && filteredRows.length) ? filteredRows : allResults;
  const record = (rows || []).find(r => reviewKey(r) === key);
  const tpl = getTemplateFor(social);
  if (!tpl || !record) return;
  event.preventDefault();
  const text = substituteTemplate(tpl.text, record);
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

// ── Интеграция с «Отправить в VK» ──────────────────────────────
function onSenderRandomChange() {
  const chk = document.getElementById('s-random-tpl');
  const ta = document.getElementById('s-message');
  if (chk && chk.checked && ta) {
    ta.value = '';
    showToast('Текст для каждого сообщения выберется случайно из набора vk', 'info');
  }
}

function fillSenderFromTemplate() {
  const sel = document.getElementById('s-template');
  const t = (sel && messageTemplates.find(x => x.id === sel.value)) || getActiveTemplateFor('vk');
  if (!t) { showToast('Нет шаблонов', 'warning'); return; }
  const ta = document.getElementById('s-message');
  if (ta) ta.value = t.text;
  showToast('Текст шаблона вставлен', 'success');
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
  const _fq = document.getElementById('f-queries');
  if (_fq) _fq.addEventListener('input', () => {
    updateQueriesCounter();
    updateClearAllBtn();
    updateBasicSummary();
  });
  const _fci = document.getElementById('f-city-input');
  if (_fci) _fci.addEventListener('input', () => {
    updateClearAllBtn();
  });

  const _fp = document.getElementById('f-pages');
  if (_fp) _fp.addEventListener('input', updatePagesCapNote);

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
  loadExcelCols();
  initResultsPanel();
  loadReviewed();
  loadColState();
  // Stats tab shows zero cards right away — before any search
  renderDefaultStats();
  // Настройки уведомлений из localStorage + состояние кнопки.
  // Разрешение здесь больше не решает ничего: звук работает и без него,
  // а окна появляются, как только браузер разрешит.
  loadNotifySettings();
  updateNotifyBtn();

  // Sender init
  restoreSenderConfig();
  loadSenderFiles();
  // After files are loaded, restore selected file
  setTimeout(() => {
    const pf = window._senderPendingFile;
    if (pf) {
      const sel = document.getElementById('s-excel-file');
      for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === pf) { sel.selectedIndex = i; break; }
      }
    }
  }, 800);

  // Чёрный список слов («🚫 Исключить по словам»): список и шаблоны — до первого
  // рендера счётчика, чтобы подсказка не мигала пустой строкой.
  fillBlacklistTemplateSelect();
  loadBlacklistWords();

  // Шаблоны сообщений («📝 Шаблоны»): состояние нужно таблице, обходу и
  // рассылке, поэтому читаем сразу, а не при первом заходе на вкладку.
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

  // Check Playwright availability
  fetch('/status').then(r => r.json()).then(s => {
    if (s.playwright_available === false) {
      const el = document.getElementById('playwright-notice');
      if (el) el.style.display = '';
    }
    // A paused run survives a page reload: without this the dock showed
    // «Найти компании» and the only way «продолжить» was gone — users started
    // a fresh search instead and the pause looked like a stop.
    if (s.paused && s.paused.resume) {
      enterPausedState(s.paused.resume);
    }
  }).catch(() => {});

  // Reload files list when switching to sender tab
  const _origShowTab = showTab;
  showTab = function(name) {
    _origShowTab(name);
    if (name === 'sender') loadSenderFiles();
  };
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