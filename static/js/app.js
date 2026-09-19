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
let notificationsEnabled = false;  // toggle state
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
  err.textContent = '⚠ ' + msg;
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
  toast.innerHTML = `<span class="t-ico">${ok ? '✓' : '✕'}</span><span>${escapeHtml(message)}</span>`;
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
  const line1 = `<span class="hint-state">${tone === 'ok' ? '✅ ' : tone === 'sparse' ? '⚠️ ' : 'ℹ️ '}${stateTxt}</span>`
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
  clr.textContent = '✕';
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
    `<span class="city-tag">${c}<span class="city-tag-x" onclick="removeCity(${i})">✕</span></span>`
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
  if (icon) icon.textContent = '⏸';
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
    if (txt) txt.textContent = '⏳ Завершаем город…';
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
  const stopBtn = document.getElementById('btn-stop');
  if (stopBtn) stopBtn.hidden = true;
  const icon = document.getElementById('btn-icon');
  if (icon) icon.textContent = '▶';
  const txt = document.getElementById('btn-txt');
  if (txt) txt.textContent = 'Продолжить поиск';
  setRunIndicator(false);
  setStatus('paused', '⏸ Пауза');
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
//  Tabs
// ═══════════════════════════════════════════
// ═══════════════════════════════════════════
//  Notification toggle
// ═══════════════════════════════════════════
function toggleNotifications() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'denied') {
    showToast('Уведомления запрещены браузером. Разрешите их в настройках браузера.', 'error');
    return;
  }
  if (notificationsEnabled) {
    notificationsEnabled = false;
    updateNotifyBtn();
    return;
  }
  if (Notification.permission === 'default') {
    Notification.requestPermission().then(perm => {
      notificationsEnabled = (perm === 'granted');
      updateNotifyBtn();
    });
  } else {
    notificationsEnabled = true;
    updateNotifyBtn();
  }
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
  if (name === 'map' && allResults.length && !mapInited) initMap();
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
  // Re-render stats when switching to the stats tab. During an active run
  // only finished cities are shown (stable numbers); after the run ends the
  // full result set is rendered.
  if (name === 'stats' && allResults.length) {
    const recs = isRunActive() ? completedCityRecords() : allResults;
    if (!recs.length) return;
    renderStats(recs, _runElapsed(), _lastSkippedCities);
  }
}

// ═══════════════════════════════════════════
//  Status + progress
// ═══════════════════════════════════════════
function setStatus(cls, text) {
  const b = document.getElementById('status-badge');
  b.className = cls; b.textContent = text;
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
  // One mini bar per city: the aggregate bar can't explain a stalled run.
  const chips = document.getElementById('tp-cities');
  if (chips) {
    chips.innerHTML = entries.map(([name, d]) => {
      const pct = (d.status === 'done' || d.status === 'skipped') ? 100 : (d.pct || 0);
      const cls = d.status === 'running' ? 'tp-chip running' : (d.status === 'queued' ? 'tp-chip queued' : 'tp-chip');
      const tip = `${name}: ${pct}%` + (d.found ? ` · ${d.found} ${pluralRecords(d.found)}` : '');
      return `<span class="${cls}" title="${escapeHtml(tip)}">`
        + `<span class="tp-chip-name">${escapeHtml(name)}</span>`
        + `<span class="tp-chip-track"><span class="tp-chip-fill" style="width:${pct}%"></span></span>`
        + `</span>`;
    }).join('');
  }
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
// Механика, которая интересна только при отладке: геокодинг, сырые
// координаты, старт запросов («── Запрос …: начало поиска»), страницы и
// HTTP-детали, внутренние трейсы клиентов (cdp/browser/http).
// РЕЗУЛЬТАТЫ при этом остаются видимыми: «🔍 Поиск в», «🗺 Источник»,
// «✅ …: N записей», «📦 Raw», «🎯 Processed», файлы, ошибки.
const LOG_NOISE_RE = /геокодирую|→ координаты|запрос начат|начало поиска\s*$|───\s*Запрос|page \d+\/\d+|HTTP \d{3}|api_hits|\[SYS\]|http_client|rate_limit|cdp_client|browser_client|checkpoint/i;
function _logIsNoise(lvl, text) {
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

// Show/hide developer-detail lines collected behind the toggle.
function toggleTechDetails() {
  _showTechDetails = !_showTechDetails;
  const btn = document.getElementById('btn-tech-details');
  if (btn) {
    btn.textContent = _showTechDetails ? '🙈 Скрыть детали' : '🔧 Технические детали';
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
  setStatus('running', '⏳ Выполняется');
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
        resetBtn(); setStatus('error','✖ Ошибка'); hideProgress();
        return;
      }
      if (data && data.queued) {
        appendLog('info', `  ⏳ Поиск поставлен в очередь (позиция: ${data.position}). Текущий поиск завершится автоматически.`);
        setStatus('queued', '⏳ В очереди');
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
            resetBtn(); setStatus('stopped', '⏹ Тапмаут очереди'); hideProgress();
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
    .catch(err => { appendLog('warn', '  [!] ' + err.message); resetBtn(); setStatus('error','✖ Ошибка'); hideProgress(); });
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
    // Play sound for city completion
    if (notificationsEnabled && Notification && Notification.permission === 'granted') {
      playCityDoneSound(name, idx, total);
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
    setStatus('error','✖ Соединение прервано');
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
    document.getElementById('social-filter-row').style.display = '';
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
  setStatus(stopped ? 'stopped' : 'done', stopped ? '⏹ Остановлено' : '✔ Готово');
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
    if (!stopped && notificationsEnabled && Notification && Notification.permission === 'granted') {
      playDoneSound();
      sendNotification('Поиск завершён', `Найдено ${allResults.length} компаний`);
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
  document.getElementById('btn-icon').textContent = '🚀';
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
  b.textContent = (on ? '☑' : '☐') + ' Все поиски';
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

// 🔄 Re-run stage 2 (filtering) on the saved raw data — no new crawling.
function refilterNow() {
  const btn = document.getElementById('btn-refilter');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Обработка…'; }
  const formats = [];
  if (document.getElementById('f-excel')?.checked) formats.push('excel');
  if (document.getElementById('f-json')?.checked)  formats.push('json');
  if (document.getElementById('f-csv')?.checked)   formats.push('csv');
  if (document.getElementById('f-map')?.checked)   formats.push('html');
  if (!formats.length) formats.push('excel');
  const body = {
    formats,
    collapse_chains: document.getElementById('f-collapse-chains')?.checked || false,
    chain_key:       (document.getElementById('f-chain-key') || {}).value || 'name_city',
    parse_mode:      parseMode || 'all',
    social_mode:     socialMode || 'all',
    required_socials:[...requiredSocials],
    raw_mode:        (document.getElementById('f-raw-mode')||{}).value || 'keep',
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
      showToast(`Готово: ${data.count} организаций → ${data.files.length} файлов`, 'success');
      appendLog('ok', `  📦 Обработано: ${data.count} организаций → ${data.files.length} файлов в output/processed/`);
      setResultsView(_resultsView === 'raw' ? 'processed' : _resultsView);
    })
    .catch(() => showToast('Ошибка обработки', 'error'))
    .finally(() => {
      if (btn) { btn.disabled = false; btn.textContent = '🔄 Применить фильтры заново'; }
    });
}

const ICONS = {xlsx:'📊', json:'📋', csv:'📄', html:'🗺'};
function fileIcon(n) { for (const [ext,ic] of Object.entries(ICONS)) if (n.endsWith('.'+ext)) return ic; return '📁'; }

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

function socialsHTML(row) {
  let h = '';
  for (const [p, color] of Object.entries(SOCIALS)) {
    const url = row[p];
    if (url) h += `<a class="social-badge" style="background:${color}" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${SLABELS[p]}</a>`;
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
  document.getElementById('social-filter-row').style.display = data.length ? '' : 'none';
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
  curPage = 1;
  renderPage();
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
      <td><a href="${escapeHtml(safeUrl(r.yandex_maps_url || r.twogis_url))}" target="_blank" rel="noopener noreferrer" style="color:var(--g);font-weight:600;text-decoration:none">${escapeHtml(r.name || '—')}</a></td>
      <td style="color:var(--muted)">${escapeHtml(r.category || '—')}</td>
      <td>${escapeHtml(r.address || '—')}</td>
      <td>${escapeHtml(r.phone || '—')}</td>
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
let bulkState = { social: 'vk', opened: 0, blocked: 0, keys: new Set(), copied: new Set() };
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
    b.textContent = (unviewedOnly ? '☑' : '☐') + ' Непросмотренные';
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

  const btn = document.getElementById('bulk-open-btn');
  if (btn) {
    const openable = stats.by_social[social] || 0;
    const willOpen = Math.min(count, openable, BULK_MAX_TABS);
    if (bulkBusy) {
      btn.disabled = true;
      btn.textContent = '⏳ Открываем…';
    } else if (!openable) {
      // Обход закончен: непросмотренных с этой соцсетью больше нет.
      btn.disabled = true;
      btn.textContent = '✅ Все просмотрены';
    } else {
      // Кнопка обещает ровно то, что откроется этим кликом.
      btn.disabled = false;
      btn.textContent = `🚀 Открыть ${willOpen} ${pluralProfiles(willOpen)}`;
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
  bulkState = { social: bulkState.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set() };
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

function bulkParams() {
  const sel = document.getElementById('bulk-social');
  return {
    view: _resultsView,
    scope: _resultsScope,       // обход идёт по тому же срезу, что и таблица
    file: currentFile,          // обход идёт по открытому файлу, если он открыт
    city: activeCity,
    social: (sel && sel.value) || 'vk',
    skip_viewed: !!(document.getElementById('bulk-skip-viewed') || {}).checked,
    mark_viewed: !!(document.getElementById('bulk-mark-viewed') || {}).checked,
  };
}

async function bulkOpenBatch() {
  if (bulkBusy) return;
  const p = bulkParams();
  const inp = document.getElementById('bulk-count');
  const requested = clampInt(inp ? inp.value : 5, 1, BULK_MAX_TABS);

  // Другая соцсеть — начинаем сессию обхода заново.
  if (bulkState.social !== p.social) {
    bulkState = { social: p.social, opened: 0, blocked: 0, keys: new Set(), copied: new Set() };
    hideBulkWarn();
  }

  // Пустые вкладки открываются СИНХРОННО, до запроса к серверу: после await
  // браузер уже не считает их частью клика и блокирует всё, кроме первой.
  const wanted = Math.min(requested, BULK_MAX_TABS);
  const tabs = openBlankTabs(wanted);

  bulkBusy = true;
  updateBulkStats();
  try {
    const data = await postJSON('/bulk/urls', {
      view: p.view, scope: p.scope, file: p.file, city: p.city, social: p.social,
      count: wanted, skip_viewed: p.skip_viewed, exclude_keys: [...bulkState.keys],
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
        <button type="button" class="m-mark">✓ Пометить просмотренными (${keys.length})</button>
        <button type="button" class="m-ok neutral">📋 Скопировать все</button>
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
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Записываю…'; }
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
    if (btn) { btn.disabled = false; btn.textContent = '💾 Сохранить сейчас'; }
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

function fileCardHTML(section, it) {
  const meta = it.error
    ? `⚠ ${it.error}`
    : `${it.records} ${pluralRecords(it.records)} • ${fmtBytes(it.size)} • ${it.modified}`;
  const icon = ICONS[it.ext] || '📁';
  // Архивные файлы не архивируем повторно, но даём вернуть на место.
  const archiveBtn = section === 'archive'
    ? `<button class="file-btn" data-act="restore" data-path="${escapeHtml(it.path)}" title="Вернуть файл в рабочую папку">↩</button>`
    : `<button class="file-btn" data-act="archive" data-path="${escapeHtml(it.path)}" title="Убрать в архив (файл можно вернуть)">📦</button>`;
  return `
    <div class="file-card">
      <div class="file-info">
        <input type="checkbox" class="file-cb" data-path="${escapeHtml(it.path)}"
          ${_selectedFiles.has(it.path) ? 'checked' : ''}
          onchange="onFileSelect(this)" title="Выбрать для массового удаления">
        <span class="file-icon">${icon}</span>
        <div class="file-text">
          <div class="file-name" title="${escapeHtml(it.path)}">${escapeHtml(it.name)}</div>
          <div class="file-meta">${escapeHtml(meta)}</div>
        </div>
      </div>
      <div class="file-actions">
        <button class="file-btn" data-act="open" data-path="${escapeHtml(it.path)}" title="Открыть в таблице">📊</button>
        <button class="file-btn" data-act="download" data-path="${escapeHtml(it.path)}" title="Скачать">📥</button>
        ${archiveBtn}
        <button class="file-btn danger" data-act="delete" data-path="${escapeHtml(it.path)}" title="Удалить навсегда">🗑</button>
      </div>
    </div>`;
}

// ── Bulk selection («Удалить выбранные») ─────────────────────
let _selectedFiles = new Set();

function onFileSelect(cb) {
  if (cb.checked) _selectedFiles.add(cb.dataset.path);
  else _selectedFiles.delete(cb.dataset.path);
  updateBulkDeleteBtn();
}

function updateBulkDeleteBtn() {
  const btn = document.getElementById('btn-files-bulk-delete');
  const n = document.getElementById('files-bulk-n');
  if (n) n.textContent = _selectedFiles.size;
  if (btn) btn.hidden = _selectedFiles.size === 0;
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
    const socials = Object.entries(SOCIALS)
      .filter(([p]) => r[p])
         .map(([p,c]) => `<a href="${escapeHtml(safeUrl(r[p]))}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:2px 6px;margin:1px;background:${c};color:#fff;border-radius:3px;font-size:10px;font-weight:700;text-decoration:none">${SLABELS[p]}</a>`)
      .join('');
    const popup = `
      <div style="min-width:180px;max-width:240px;font-family:sans-serif">
         <b style="font-size:13px">${escapeHtml(r.name||'')}</b>
         ${r.category ? `<div style="color:#888;font-size:11px">${escapeHtml(r.category)}</div>` : ''}
         ${r.address  ? `<div style="font-size:11px">📍 ${escapeHtml(r.address)}</div>` : ''}
         ${r.phone    ? `<div style="font-size:11px">📞 ${escapeHtml(r.phone)}</div>`   : ''}
        ${socials    ? `<div style="margin-top:5px">${socials}</div>`       : ''}          ${r.twogis_url ? `<div style="margin-top:6px"><a href="${escapeHtml(safeUrl(r.twogis_url))}" target="_blank" rel="noopener noreferrer" style="font-size:11px;color:#0d7d4d">Открыть в 2ГИС ↗</a></div>` : ''}
          ${r.yandex_maps_url ? `<div style="margin-top:6px"><a href="${escapeHtml(safeUrl(r.yandex_maps_url))}" target="_blank" rel="noopener noreferrer" style="font-size:11px;color:#c0392b">Открыть на Я.Картах ↗</a></div>` : ''}
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
  const orgs = tq * 10;
  const left = Math.max(0, cap - tq);
  return `
  <div class="stat-section">
    <div class="stat-city-card quota-card ${cls}" style="max-width:420px">
      <h4>🧮 Токены 2GIS Places API</h4>
      <div class="stat-mini-row"><span>Израсходовано за месяц</span><span><b>${tq}</b> / ${cap}</span></div>
      <div class="quota-track"><div class="quota-fill" style="width:${pct}%"></div></div>
      <div class="stat-mini-row"><span>Осталось до конца месяца</span><span style="font-weight:700">${left} запросов (≈ ${(left * 10).toLocaleString('ru-RU')} организаций)</span></div>
      <div class="quota-sub">Счётчик приложения: ≈ ${orgs.toLocaleString('ru-RU')} организаций · 1 запрос ≈ 10 организаций · 2GIS не показывает точный остаток — платный лимит видно только в Platform Manager (dev.2gis.ru) с задержкой ~1 день</div>
    </div>
  </div>`;
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
      <h3>⚡ Аналитика</h3>
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

    ${socialCounts.length ? `
    <div class="stat-section">
      <h3>По соцсетям</h3>
      ${barRows(socialCounts.map(s => ({label: s.name, count: s.count, color: s.color})))}
    </div>` : ''}

    ${cats.length ? `
    <div class="stat-section">
      <h3>Топ категорий</h3>
      ${barRows(cats.map(([name, cnt], i) => ({label: name, count: cnt, color: CAT_COLORS[i%CAT_COLORS.length]})))}
    </div>` : ''}
  `;
  }).catch(()=>{});
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
      + '<button type="button" class="preset-dd-edit" title="Перезаписать пресет текущими настройками формы" aria-label="Редактировать пресет" data-edit="' + i + '">✎</button>'
      + '<button type="button" class="preset-dd-del" title="Удалить пресет" aria-label="Удалить пресет" data-del="' + i + '">✕</button>'
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
        <button type="button" class="m-ok">💾 Сохранить</button>
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
function updateNotifyBtn() {
  const btn  = document.getElementById('btn-notify');
  const icon = document.getElementById('notify-icon');
  const txt  = document.getElementById('notify-txt');
  if (!('Notification' in window)) {
    btn.style.display = 'none'; return;
  }
  const perm = Notification.permission;
  if (perm === 'denied') {
    btn.className = 'denied';
    icon.textContent = '🔕'; txt.textContent = 'Уведомления запрещены';
  } else if (notificationsEnabled) {
    btn.className = 'granted';
    icon.textContent = '🔔'; txt.textContent = 'Уведомления вкл.';
  } else {
    btn.className = '';
    icon.textContent = '🔔'; txt.textContent = 'Уведомления';
  }
}

function sendNotification(title, body, icon) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (!notificationsEnabled) return;
  try {
    const n = new Notification(title, {body});
    n.onclick = () => { window.focus(); n.close(); };
  } catch (e) { /* некоторые браузеры блокируют без service worker */ }
}

// ── Completion sound (Web Audio API chime) ──
function playCityDoneSound(cityName, idx, total) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    // Two-tone chime: E5 → G5 (lighter than full done sound)
    [659, 784].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.15;
      gain.gain.setValueAtTime(0.22, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
      osc.start(t);
      osc.stop(t + 0.35);
    });
    // Browser notification
    sendNotification(`Город ${idx}/${total} завершён`, `${cityName} — готово`);
  } catch (e) { /* Web Audio unavailable */ }
}

function playDoneSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
    // Ascending three-tone chime: C5 → E5 → G5
    [523, 659, 784].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.18;
      gain.gain.setValueAtTime(0.28, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.45);
      osc.start(t);
      osc.stop(t + 0.45);
    });
  } catch (e) { /* Web Audio unavailable */ }
}

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
  // Update button badge
  const btn = document.getElementById('btn-cols');
  if (btn) {
    const n = hiddenCols.size;
    btn.classList.toggle('active', n > 0);
    btn.innerHTML = n > 0 ? `⚙ Столбцы <span style="background:var(--g);color:#fff;border-radius:10px;padding:1px 6px;font-size:10px">${COLS.length - n}/${COLS.length}</span>` : '⚙ Столбцы';
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
    cls = 'ok'; txt = `✅ Готово ${have}/${total}`;
    title = 'Все API-ключи настроены: Яндекс, 2GIS, VK';
  } else if (have > 0) {
    cls = 'warn'; txt = `⚠️ ${have}/${total} ключей`;
    title = 'Настроены не все API-ключи — часть функций (соцсети, активность ВК, 2GIS) будет недоступна';
  } else {
    cls = 'err'; txt = `❌ 0/${total} ключей`;
    title = 'API-ключи не найдены — поиск может не работать';
  }
  badge.className = 'api-badge ' + cls;
  badge.textContent = txt;
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
  btn.textContent = '⏳ Сохраняю…';

  const show = (ok, msg) => {
    if (!status) return;
    status.style.display = 'block';
    status.className = ok ? 'ok' : 'err';
    status.textContent = (ok ? '✓ ' : '✕ ') + msg;
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
  document.getElementById('btn-theme').textContent = dark ? '☀️' : '🌙';
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
  const cfg = {
    message:  document.getElementById('s-message').value,
    delayMin: document.getElementById('s-delay-min').value,
    delayMax: document.getElementById('s-delay-max').value,
    limitType:document.getElementById('s-limit-type').value,
    limitN:   document.getElementById('s-limit-n').value,
    file:     document.getElementById('s-excel-file').value,
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
  if (!message) {
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
  document.getElementById('send-btn-icon').textContent = '📨';
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
    <h3>📜 Логи запусков</h3>
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
        modal.innerHTML = `<h3>📜 Логи запусков</h3><div class="logs-empty">Логов пока нет. Запустите поиск чтобы создать лог.</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
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
      modal.innerHTML = `<h3>📜 Логи запусков</h3>
        <ul class="logs-list">${listHtml}</ul>
        <div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
    })
    .catch(() => {
      overlay.querySelector('.logs-modal').innerHTML = `<h3>📜 Логи запусков</h3><div class="logs-empty">Ошибка загрузки</div><div style="text-align:right;margin-top:12px"><button class="skip-cancel" onclick="this.closest('.logs-modal-overlay').remove()">Закрыть</button></div>`;
    });
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
        setUpdateDot(false);
        return { newer: false, dev: true, version: data.current };
      }
      if (data.newer) {
        showUpdateBanner(data.latest, data.changelog || '',
          data.download_url || 'https://github.com/ScarFace11/Yandex-Buisnes-Parser/releases/latest');
        setUpdateDot(true, data.latest);
        return { newer: true, version: data.latest };
      }
      setUpdateDot(false);
      return { newer: false, version: data.latest || data.current };
    })
    .catch(() => {
      // /update/status unavailable — legacy /check-version fallback
      return fetch('/check-version')
        .then(r => r.json())
        .then(data => {
          if (data.dev) {
            _devBuild = true;
            setUpdateDot(false);
            return { newer: false, dev: true, version: data.current };
          }
          if (data.newer) {
            showUpdateBanner(data.remote, data.changelog || '', data.download_url || '');
            setUpdateDot(true, data.remote);
            return { newer: true, version: data.remote };
          }
          setUpdateDot(false);
          return { newer: false, version: data.current };
        })
        .catch(() => ({ newer: false, error: true }));
    })
    .then(res => {
      if (silent) return res;
      if (res.dev) showToast('DEV-сборка — авто-обновление отключено (только для разработки)', 'info');
      else if (res.error) showToast('Не удалось связаться с GitHub — проверьте интернет', 'error');
      else if (res.newer) showToast(`Новая версия v${res.version} — обновите через баннер сверху`, 'success');
      else showToast('Вы на последней версии ✓', 'success');
      return res;
    });
}

// Header button: manual re-check with visual feedback
function manualUpdateCheck(btn) {
  if (!btn || btn.dataset.busy) return;
  btn.dataset.busy = '1';
  const orig = btn.innerHTML;
  btn.innerHTML = '<span class="spin" style="width:11px;height:11px;border-width:1.5px"></span> Проверяю…';
  checkForUpdates(false)
    .catch(() => {})
    .finally(() => {
      delete btn.dataset.busy;
      btn.innerHTML = orig;
    });
}

// Periodic background check (silent — banner only, no toasts).
// DEV-сборку не проверяем вовсе: узнав про dev:true, выходим из цикла.
setInterval(() => { if (!_devBuild) checkForUpdates(true); }, UPDATE_CHECK_INTERVAL);

// ── «Update available» dot on the header button ──
// Orange dot + pulse while a newer version exists; hidden once the user
// updates or the check reports up-to-date.
function setUpdateDot(on, version) {
  const btn = document.getElementById('btn-updates');
  if (!btn) return;
  let dot = document.getElementById('update-dot');
  if (on) {
    if (!dot) {
      dot = document.createElement('span');
      dot.id = 'update-dot';
      dot.title = 'Доступно обновление';
      btn.appendChild(dot);
    }
    dot.dataset.version = version || '';
    dot.classList.add('on');
  } else if (dot) {
    dot.classList.remove('on');
  }
}

function showUpdateBanner(newVer, changelog, url) {
  // Remove existing banner if any
  const existing = document.getElementById('update-banner');
  if (existing) existing.remove();

  // Frozen build: «Обновить сейчас» is the PRIMARY action — it downloads,
  // installs and restarts inside the app (no GitHub visit needed).
  // Source run: no in-app updater, so GitHub becomes the primary action.
  fetch('/update/status').then(r => r.json()).then(st => {
    // Сам обновляет файлы только Windows-сборка; macOS-бандл и исходники
    // получают ссылку на релиз (auto_apply=false приходит с сервера).
    const frozen = !!st.frozen && st.auto_apply !== false;
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <button class="ub-btn" id="ub-changelog" onclick="showChangelog()" title="Подробнее об изменениях в новой версии">📄 Что нового</button>
      ${frozen
        ? `<button class="ub-btn ub-primary" id="ub-self-update" onclick="selfUpdate()" title="Скачать и установить прямо из приложения — после установки просто обновите страницу">⬆ Обновить сейчас</button>
           <a class="ub-btn" href="${url}" target="_blank" rel="noopener noreferrer" title="Страница релизов на GitHub">GitHub ↗</a>`
        : `<a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer" title="Скачайте сборку для своей системы на странице релизов">Скачать v${newVer} ↗</a>`}
      <button class="ub-close" onclick="this.parentElement.remove()">✕</button>
    `;
    document.body.prepend(banner);
  }).catch(() => {
    // /update/status is dead — render the source-mode banner (GitHub primary)
    const banner = document.createElement('div');
    banner.id = 'update-banner';
    banner.innerHTML = `
      <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
      <a class="ub-btn ub-primary" href="${url}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
      <button class="ub-close" onclick="this.parentElement.remove()">✕</button>
    `;
    document.body.prepend(banner);
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
        <h3>📄 Что нового</h3>
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
  // Initialize notifications toggle state from browser permission
  notificationsEnabled = Notification && Notification.permission === 'granted';
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
            <button class="hist-btn blue" data-run="${escapeHtml(entry.run_id || '')}" onclick="rerunSearch(this.dataset.run)">🔄 Повторить поиск</button>
            <button class="hist-btn red" data-run="${escapeHtml(entry.run_id || '')}" onclick="deleteHistory(this.dataset.run)">🗑 Удалить</button>
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
        el.innerHTML = `📦 В кэше <b>${data.count}</b> бизнесов${date ? ' (обновлено: ' + date + ')' : ''}. Повторные запуски по тем же городам пропустят уже найденные.`;
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