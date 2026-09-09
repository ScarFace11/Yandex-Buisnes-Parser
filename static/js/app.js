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
let activeSocialFilters = new Set();
let socialMode = 'all';  // 'all' | 'with_socials' | 'without_socials'
let parseMode = 'without_website';  // 'without_website' | 'all' — тип организаций
let dataSource = 'yandex';  // 'yandex' | '2gis' — источник данных
let notificationsEnabled = false;  // toggle state
let requiredSocials = new Set();   // AND filter: must have ALL selected socials
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
  list.innerHTML = entries.map(([name, data]) => {
    const statusIcon = data.status === 'done' ? '✅' : data.status === 'skipped' ? '⏭' : '⏳';
    const barColor = data.status === 'done' ? '#4caf50' : data.status === 'skipped' ? '#ff9800' : '#2196f3';
    return `<div style="display:flex;align-items:center;gap:6px;min-width:180px">
      <span style="font-size:12px">${statusIcon}</span>
      <span style="font-weight:600;color:#333;font-size:11px;min-width:80px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${name}">${name}</span>
      <div style="flex:1;height:6px;background:#e0e0e0;border-radius:3px;min-width:60px;max-width:120px">
        <div style="height:100%;width:${data.pct}%;background:${barColor};border-radius:3px;transition:width 0.3s"></div>
      </div>
      <span style="font-size:10px;color:#666;min-width:30px;text-align:right">${data.found > 0 ? data.found + ' найд.' : data.pct + '%'}</span>
    </div>`;
  }).join('');
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
function uiConfirm(message, title = 'Подтвердите действие', okLabel = 'Удалить') {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'ui-modal-overlay';
    overlay.innerHTML = `
      <div class="ui-modal">
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
        <div class="ui-modal-btns">
          <button type="button" class="m-cancel">Отмена</button>
          <button type="button" class="m-ok">${escapeHtml(okLabel)}</button>
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
  const hint = document.getElementById('social-mode-hint');
  if (hint) {
    const hints = { all: 'Показывать все найденные бизнесы', with_socials: 'Только бизнесы с найденными соцсетями', without_socials: 'Только бизнесы без соцсетей (быстрее — без загрузки деталей)' };
    hint.textContent = hints[mode] || '';
  }
  // Smoothly reveal the social network tiles only for «С соцсетями»
  const netFilter = document.getElementById('social-network-filter');
  if (netFilter) netFilter.classList.toggle('open', mode === 'with_socials');
  if (mode !== 'with_socials') {
    requiredSocials.clear();
    // Clear the tile visuals too — otherwise stale checks re-appear when
    // the user switches back to «С соцсетями».
    document.querySelectorAll('#social-net-chk-grid .soc-tile.on').forEach(t => {
      t.classList.remove('on');
      const cb = t.querySelector('input[type=checkbox]');
      if (cb) cb.checked = false;
    });
  }
  // Re-filter table if results exist
  if (allResults.length) filterTable();
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
      ? `2GIS: официальный API (быстрый поиск). Ключ без доступа к контактам — соцсети добираются с карточек 2ГИС через Chrome<br>${keySpan}`
      : 'Яндекс.Карты: поиск через Search API, соцсети собираются с карточек организаций (медленнее)';
  }
  if (src === '2gis') refreshSourceKeyState();
}

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
  if (allResults.length) filterTable();
}

// ═══════════════════════════════════════════
//  Grid toggle
// ═══════════════════════════════════════════
function toggleGrid() {
  document.getElementById('grid-opts').style.display =
    document.getElementById('f-grid').checked ? 'grid' : 'none';
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
  const dd = document.createElement('div');
  dd.className = 'city-dropdown'; dd.id = 'city-dropdown';
  box.appendChild(dd);

  // ── Events (attached once) ──
  inp.addEventListener('input', e => {
    citySearchText = e.target.value;
    clr.classList.toggle('visible', citySearchText.length > 0);
    updateCityDropdown();
  });
  inp.addEventListener('focus', () => { updateCityDropdown(); });
  inp.addEventListener('blur', () => {
    setTimeout(() => {
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

function renderCityTags() {
  const tagsRow = document.getElementById('city-tags-row');
  if (!tagsRow) return;
  tagsRow.innerHTML = selectedCities.map((c, i) =>
    `<span class="city-tag">${c}<span class="city-tag-x" onclick="removeCity(${i})">✕</span></span>`
  ).join('');
  // Update placeholder
  const inp = document.getElementById('f-city-input');
  if (inp) inp.placeholder = selectedCities.length ? 'Добавить город…' : 'Начните вводить название города…';
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
    const barColor = `hsl(${hue}, 65%, 42%)`;
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

function showTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('t-' + name).classList.add('active');
  document.getElementById('p-' + name).classList.add('active');
  if (name === 'map' && allResults.length && !mapInited) initMap();
  if (name === 'map' && leafMap) setTimeout(() => leafMap.invalidateSize(), 50);
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
    const elapsed = (Date.now() - startTime) / 1000;
    renderStats(recs, elapsed, _lastSkippedCities);
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

// ═══════════════════════════════════════════
//  Log output
// ═══════════════════════════════════════════
const logEl = document.getElementById('log-output');
// Long runs emit thousands of lines; without a cap the DOM grows unbounded
// and scrolling/layout gets janky. Keep the newest MAX_LOG_LINES.
const MAX_LOG_LINES = 1200;
function _trimLog(el) {
  while (el.children.length > MAX_LOG_LINES) el.removeChild(el.firstChild);
}
function appendLog(level, msg) {
  const ph = document.getElementById('log-ph');
  if (ph) ph.remove();
  // Remove the «Как это работает» onboarding card once real log lines arrive.
  const ob = document.getElementById('onboarding-screen');
  if (ob) ob.remove();
  // Drop the skeleton loaders — real data has arrived
  const skel = document.getElementById('log-skeleton');
  if (skel) skel.remove();
  // 'sys' → default quiet-grey terminal styling; unknown levels → grey too
  const cls = (level === 'info' || level === 'ok' || level === 'warn' || level === 'error') ? level : 'sys';
  const d = document.createElement('div');
  d.className = 'll ' + cls;
  d.textContent = msg.replace(/\x1b\[[0-9;]*m/g, '');
  logEl.appendChild(d);
  _trimLog(logEl);
  logEl.scrollTop = logEl.scrollHeight;
}
function clearLog() {
  logEl.innerHTML = '';
  const lbl = document.getElementById('term-log-lbl');
  if (lbl) lbl.textContent = 'Лог очищен — здесь появится ход поиска';
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
    min_rating:      +document.getElementById('f-rating').value  || 0,
    min_reviews:     +document.getElementById('f-reviews').value || 0,
    use_grid:        document.getElementById('f-grid').checked,
    grid_radius:     +document.getElementById('f-grad').value  || 20,
    grid_step:       +document.getElementById('f-gstep').value || 5,
    validate_socials:document.getElementById('f-validate').checked,
    resume:          document.getElementById('f-resume').checked,
    collapse_chains: document.getElementById('f-collapse-chains').checked,
    min_contact:     document.getElementById('f-min-contact').checked,
    api_key:         document.getElementById('f-apikey').value.trim(),
    twogis_api_key:  (document.getElementById('f-2gis-key') || {}).value?.trim() || '',
    social_mode:     socialMode,
    required_socials: [...requiredSocials],
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
  updateStatsBadge();
}

function startRun() {
  const params = getParams();
  clearFieldError(document.getElementById('fw-city'));
  const queriesBox = document.getElementById('f-queries').closest('div');
  clearFieldError(queriesBox);
  // Live-clear: errors disappear as soon as the user edits the field again
  document.getElementById('f-queries').addEventListener('input', () => clearFieldError(queriesBox), { once: true });
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

  resetRunUI();
  requiredSocials.clear();
  initSocialNetCheckboxes();
  setStatus('running', '⏳ Выполняется');
  setProgress(0, 'Запуск…');
  document.getElementById('btn-run').disabled = true;
  document.getElementById('btn-icon').innerHTML = '<span class="spin"></span>';
  document.getElementById('btn-txt').textContent = 'Выполняется…';
  document.getElementById('btn-stop').style.display = 'inline-block';
  if (params.cities.length > 1) {
    document.getElementById('btn-skip').style.display = 'inline-block';
  }
  startTime = Date.now();
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
    renderStats(recs, (Date.now() - startTime) / 1000, _lastSkippedCities);
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
    document.getElementById('btn-dedup').classList.add('visible');
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
        const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
        if (!hasAny) return false;
      } else if (socialMode === 'without_socials') {
        const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
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
  setStatus(stopped ? 'stopped' : 'done', stopped ? '⏹ Остановлено' : '✔ Готово');
  document.title = 'Яндекс.Карты — Парсер бизнесов';
  resetBtn();
  hideProgress();
  showDownloads(msg.files || [], msg.formats || []);
  const elapsed = (Date.now() - startTime) / 1000;

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
      // Completed with nothing found — replace the "waiting…" placeholder
      document.getElementById('stats-body').innerHTML =
        '<div class="no-data">Результатов не найдено. Измените запросы, города или фильтры.</div>';
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
  document.getElementById('btn-run').disabled = false;
  document.getElementById('btn-icon').textContent = '🚀';
  document.getElementById('btn-txt').textContent = 'Запустить';
  document.getElementById('btn-stop').style.display = 'none';
  document.getElementById('btn-skip').style.display = 'none';
  updateStatsBadge();
}

// ═══════════════════════════════════════════
//  Downloads
// ═══════════════════════════════════════════
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
const SOCIALS = {vk:'#4C75A3',instagram:'#C13584',facebook:'#1877F2',telegram:'#2CA5E0',
  youtube:'#FF0000',tiktok:'#010101',ok:'#EE8208',twitter:'#14171A',whatsapp:'#25D366'};
const SLABELS = {vk:'VK',instagram:'IG',facebook:'FB',telegram:'TG',
  youtube:'YT',tiktok:'TT',ok:'OK',twitter:'TW',whatsapp:'WA'};
const SNAMES = {vk:'ВКонтакте',instagram:'Instagram',facebook:'Facebook',telegram:'Telegram',
  youtube:'YouTube',tiktok:'TikTok',ok:'Одноклассники',twitter:'Twitter / X',whatsapp:'WhatsApp'};

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
  if (row.other_socials) row.other_socials.split(',').forEach(u => {
    u = u.trim();
    if (u) h += `<a class="social-badge" style="background:#9C27B0" href="${escapeHtml(safeUrl(u))}" target="_blank" rel="noopener noreferrer">…</a>`;
  });
  return h || '—';
}

function renderTable(data) {
  activeSocialFilters.clear();
  document.querySelectorAll('.sf-tag').forEach(b => b.classList.remove('active'));
  document.getElementById('sf-clear-btn').classList.remove('visible');
  filteredRows = [...data];
  curPage = 1; sortCol = -1;
  document.getElementById('tbl-search').value = '';
  document.querySelectorAll('#results-table th').forEach(th => th.className = '');
  // Show social filter row + dedup button only when there are results
  document.getElementById('social-filter-row').style.display = data.length ? '' : 'none';
  document.getElementById('btn-dedup').classList.toggle('visible', data.length > 0);
  // Re-derive through filterTable so the optional quality filters
  // (collapse chains / min contact) apply to the final view too.
  filterTable();
}

// Client-side mirror of the server's optional output filters
// ("Объединять филиалы сетей" / "Только с телефоном или соцсетями"),
// so the live table matches what gets written to files.
function hasAnySocial(r) {
  return Object.keys(SOCIALS).some(k => r[k]) || !!r.other_socials;
}

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
    // Min-contact filter: hide rows with no phone and no socials
    const minContact = document.getElementById('f-min-contact');
    if (minContact && minContact.checked && !r.phone && !hasAnySocial(r)) return false;
    // Search every visible/data field
    const searchable = Object.values(r).some(value =>
      String(value ?? '').toLocaleLowerCase('ru-RU').includes(q)
    );
    if (q && !searchable) return false;
    // Social mode filter (form-level toggle)
    if (socialMode === 'with_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
      if (!hasAny) return false;
    } else if (socialMode === 'without_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
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
    return true;
  });
  curPage = 1;
  renderPage();
}

function sortTable(col) {
  const th = document.querySelectorAll('#results-table th')[col];
  if (sortCol === col) { sortAsc = !sortAsc; }
  else { sortCol = col; sortAsc = true; }
  document.querySelectorAll('#results-table th').forEach(t => t.className = '');
  th.className = sortAsc ? 'asc' : 'desc';
  // col 0 = ✓ (not sortable), col 1 = #, col 2 = name, ...
  const keys = ['', '_idx', 'name', 'category', 'address', 'phone', 'rating', 'reviews'];
  const key = keys[col];
  filteredRows.sort((a, b) => {
    let va = col === 1 ? filteredRows.indexOf(a) : (a[key] || '');
    let vb = col === 1 ? filteredRows.indexOf(b) : (b[key] || '');
    if (col === 6) { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
    if (col === 7) { va = parseInt(va, 10) || 0; vb = parseInt(vb, 10) || 0; }
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

  document.getElementById('tbl-count').textContent = total ? `${total} записей` : '';
  const exportWrap = document.getElementById('export-sel-wrap');
  if (exportWrap) exportWrap.style.display = total ? 'flex' : 'none';

  const tbody = document.getElementById('tbl-body');
  if (!total) {
    tbody.innerHTML = '<tr><td colspan="9" class="no-data">Ничего не найдено</td></tr>';
    document.getElementById('pager').style.display = 'none';
    return;
  }

  tbody.innerHTML = slice.map((r, i) => {
    const rawReviewUrl = r.yandex_maps_url || r.twogis_url || '';
    const reviewUrl = escapeHtml(rawReviewUrl);
    const isRev = rawReviewUrl && reviewedState[rawReviewUrl];
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
      <td>${r.rating ? '★ ' + escapeHtml(r.rating) : '—'}</td>
      <td>${r.reviews !== undefined && r.reviews !== null && r.reviews !== '' ? escapeHtml(r.reviews) : '0'}</td>
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
  }).catch(() => {});
}

function toggleReviewed(url, cb) {
  if (!url) return;
  const checked = cb.checked;
  reviewedState[url] = checked;
  const row = cb.closest('tr');
  if (row) row.classList.toggle('is-reviewed', checked);
  fetch('/reviewed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, reviewed: checked})
  }).catch(() => {});
}

// ═══════════════════════════════════════════
//  Export filtered rows
// ═══════════════════════════════════════════
function exportFiltered(fmt) {
  if (!filteredRows.length) return;
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
         ${r.rating   ? `<div style="color:#f5a623">★ ${escapeHtml(r.rating)}${r.reviews ? ' · '+escapeHtml(r.reviews)+' отз.' : ''}</div>` : ''}
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
      <div class="stat-card"><div class="num">0</div><div class="lbl">Через taplink</div></div>
      <div class="stat-card"><div class="num">0</div><div class="lbl">С рейтингом</div></div>
      <div class="stat-card"><div class="num">—</div><div class="lbl">Время</div></div>
    </div>
    <div class="stat-section">
      <h3>По соцсетям</h3>
      <div class="no-data" style="padding:18px 12px">Данные появятся после запуска поиска</div>
    </div>
    <div class="stat-section">
      <h3>Топ категорий</h3>
      <div class="no-data" style="padding:18px 12px">Данные появятся после запуска поиска</div>
    </div>`;
}

function renderStats(data, elapsed, skippedCities) {
  if (!data.length) return;
  const total  = data.length;
  const withSo = data.filter(r => Object.keys(SOCIALS).some(p => r[p])).length;
  const taplink= data.filter(r => r.aggregator_url).length;
  const rated  = data.filter(r => r.rating).length;
  const dur    = elapsed ? (elapsed < 60 ? elapsed.toFixed(0)+'с' : (elapsed/60).toFixed(1)+'м') : '—';

  const cards = [
    {num: total,   lbl: 'Всего найдено'},
    {num: withSo,  lbl: 'С соцсетями'},
    {num: taplink, lbl: 'Через taplink'},
    {num: rated,   lbl: 'С рейтингом'},
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
  const maxC = cats[0]?.[1] || 1;

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
  // Fetch live analytics + cache stats
  Promise.all([
    fetch('/analytics').then(r=>r.json()).catch(()=>({})),
    fetch('/cache/stats').then(r=>r.json()).catch(()=>({}))
  ]).then(([a, c]) => {
    const analyticsHtml = (a && a.total_requests) || (c && c.total) ? `
    <div class="stat-section">
      <h3>⚡ Аналитика</h3>
      <div class="stat-cards">
        ${a.total_requests ? `
        <div class="stat-card"><div class="num">${a.rps_actual}</div><div class="lbl">RPS (факт.)</div></div>
        <div class="stat-card"><div class="num">${a.rps_target}</div><div class="lbl">RPS (цель)</div></div>
        <div class="stat-card"><div class="num">${a.avg_latency}с</div><div class="lbl">Среднее</div></div>
        <div class="stat-card"><div class="num">${a.p50_latency}с</div><div class="lbl">P50</div></div>
        <div class="stat-card"><div class="num">${a.p95_latency}с</div><div class="lbl">P95</div></div>
        <div class="stat-card"><div class="num">${a.total_requests}</div><div class="lbl">Запросов</div></div>
        <div class="stat-card"><div class="num">${a.errors}</div><div class="lbl">Ошибок</div></div>
        <div class="stat-card"><div class="num">${a.rate_limits}</div><div class="lbl">429</div></div>
        ` : ''}
        ${c.valid ? `
        <div class="stat-card"><div class="num">${c.valid}</div><div class="lbl">Кэш (активных)</div></div>
        <div class="stat-card"><div class="num">${c.expired}</div><div class="lbl">Кэш (устаревших)</div></div>
        ` : ''}
      </div>
    </div>` : '';
    body.innerHTML = `
    <div class="stat-cards">${cards.map(c =>
      `<div class="stat-card"><div class="num">${c.num}</div><div class="lbl">${c.lbl}</div></div>`
    ).join('')}</div>

    ${analyticsHtml}

    ${cityCardsHtml}

    ${skippedHtml}

    ${socialCounts.length ? `
    <div class="stat-section">
      <h3>По соцсетям</h3>
      ${socialCounts.map(s => `
        <div class="bar-row">
          <div class="bar-lbl">${s.name}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.round(s.count/total*100)}%;background:${s.color}"></div></div>
          <div class="bar-val">${s.count}</div>
        </div>`).join('')}
    </div>` : ''}

    ${cats.length ? `
    <div class="stat-section">
      <h3>Топ категорий</h3>
      ${cats.map(([name, cnt], i) => `
        <div class="bar-row">
          <div class="bar-lbl" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.round(cnt/maxC*100)}%;background:${CAT_COLORS[i%CAT_COLORS.length]}"></div></div>
          <div class="bar-val">${cnt}</div>
        </div>`).join('')}
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
    // city intentionally NOT saved to localStorage — start fresh each time
    excel:    document.getElementById('f-excel').checked,
    json:     document.getElementById('f-json').checked,
    csv:      document.getElementById('f-csv').checked,
    map:      document.getElementById('f-map').checked,
    pages:    document.getElementById('f-pages').value,
    workers:  document.getElementById('f-workers').value,
    queryWorkers: document.getElementById('f-query-workers').value,
    maxCandidates: document.getElementById('f-max-candidates').value,
    rating:   document.getElementById('f-rating').value,
    reviews:  document.getElementById('f-reviews').value,
    grid:     document.getElementById('f-grid').checked,
    grad:     document.getElementById('f-grad').value,
    gstep:    document.getElementById('f-gstep').value,
    validate: document.getElementById('f-validate').checked,
    resume:   document.getElementById('f-resume').checked,
    collapseChains: document.getElementById('f-collapse-chains').checked,
    minContact:     document.getElementById('f-min-contact').checked,
    socialMode: socialMode,
    parseMode: parseMode,
     // API keys are entered for the current run only and are never persisted.
  };
}

function applySettings(s) {
  if (!s) return;
  if (s.queries  != null) document.getElementById('f-queries').value   = s.queries;
  // Cities are intentionally NOT restored from localStorage.
  // User should select them fresh each time.
  // (renderCityTags is called by initCitySelect on page load)
  if (s.excel    != null) { document.getElementById('f-excel').checked = s.excel;   document.getElementById('f-excel').closest('.chk').classList.toggle('on', s.excel); }
  if (s.json     != null) { document.getElementById('f-json').checked  = s.json;    document.getElementById('f-json').closest('.chk').classList.toggle('on', s.json); }
  if (s.csv      != null) { document.getElementById('f-csv').checked   = s.csv;     document.getElementById('f-csv').closest('.chk').classList.toggle('on', s.csv); }
  if (s.map      != null) { document.getElementById('f-map').checked   = s.map;     document.getElementById('f-map').closest('.chk').classList.toggle('on', s.map); }
  if (s.pages    != null) document.getElementById('f-pages').value    = s.pages;
  if (s.workers  != null) document.getElementById('f-workers').value  = s.workers;
  if (s.queryWorkers != null) document.getElementById('f-query-workers').value = s.queryWorkers;
  if (s.maxCandidates != null) document.getElementById('f-max-candidates').value = s.maxCandidates;
  if (s.rating   != null) document.getElementById('f-rating').value   = s.rating;
  if (s.reviews  != null) document.getElementById('f-reviews').value  = s.reviews;
  if (s.grid     != null) { document.getElementById('f-grid').checked = s.grid; toggleGrid(); document.getElementById('grid-lbl').classList.toggle('on', s.grid); }
  if (s.grad     != null) document.getElementById('f-grad').value    = s.grad;
  if (s.gstep    != null) document.getElementById('f-gstep').value   = s.gstep;
  if (s.validate != null) { document.getElementById('f-validate').checked = s.validate; document.getElementById('f-validate').closest('.chk').classList.toggle('on', s.validate); }
  if (s.resume != null) { document.getElementById('f-resume').checked = s.resume; document.getElementById('f-resume').closest('.chk').classList.toggle('on', s.resume); }
  if (s.collapseChains != null) { document.getElementById('f-collapse-chains').checked = s.collapseChains; document.getElementById('f-collapse-chains').closest('.chk').classList.toggle('on', s.collapseChains); }
  if (s.minContact != null) { document.getElementById('f-min-contact').checked = s.minContact; document.getElementById('f-min-contact').closest('.chk').classList.toggle('on', s.minContact); }
  if (s.socialMode) setSocialMode(s.socialMode);
  if (s.parseMode) setParseMode(s.parseMode);
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
  const bar    = document.getElementById('preset-bar');
  const presets = getPresets();
  // Keep the save button, rebuild chips
  bar.innerHTML = `<button class="btn-sm" onclick="savePreset()">💾 Сохранить</button>`;
  presets.forEach((p, i) => {
    const chip = document.createElement('span');
    chip.className = 'preset-chip';
    chip.innerHTML = `${p.name}<span class="del" onclick="event.stopPropagation();deletePreset(${i})">✕</span>`;
    chip.onclick = () => loadPreset(i);
    bar.appendChild(chip);
  });
}

function savePreset() {
  const name = prompt('Название пресета:');
  if (!name) return;
  const presets = getPresets();
  presets.unshift({name, settings: getCurrentSettings()});
  savePresets(presets.slice(0, 10));
  renderPresets();
}

function loadPreset(i) {
  const p = getPresets()[i];
  if (p) applySettings(p.settings);
}

function deletePreset(i) {
  const p = getPresets();
  p.splice(i, 1);
  savePresets(p);
  renderPresets();
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

// ═══════════════════════════════════════════
//  Deduplication
// ═══════════════════════════════════════════
function deduplicateResults() {
  const before = allResults.length;
  const seen = new Set();
  allResults = allResults.filter(r => {
    const key = r.yandex_maps_url || r.twogis_url || (r.name + '|' + r.address);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const removed = before - allResults.length;
  if (removed === 0) {
    appendLog('info', '  Дублей не найдено.');
  } else {
    appendLog('ok', `  Удалено ${removed} дубл${removed === 1 ? 'ь' : removed < 5 ? 'я' : 'ей'}. Осталось ${allResults.length}.`);
    showTab('log');
    setTimeout(() => showTab('table'), 800);
  }
  renderTable(allResults);
}

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
  { idx: 7, key: 'rating',   label: 'Рейтинг' },
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
  { f: 'name',           l: 'Название' },
  { f: 'category',       l: 'Категория' },
  { f: 'description',    l: 'Описание' },
  { f: 'address',        l: 'Адрес' },
  { f: 'phone',          l: 'Телефон' },
  { f: 'hours',          l: 'Часы работы' },
  { f: 'rating',         l: 'Рейтинг' },
  { f: 'reviews',        l: 'Отзывов' },
  { f: 'vk',             l: 'ВКонтакте' },
  { f: 'instagram',      l: 'Instagram' },
  { f: 'facebook',       l: 'Facebook' },
  { f: 'telegram',       l: 'Telegram' },
  { f: 'youtube',        l: 'YouTube' },
  { f: 'tiktok',         l: 'TikTok' },
  { f: 'ok',             l: 'Одноклассники' },
  { f: 'twitter',        l: 'Twitter / X' },
  { f: 'whatsapp',       l: 'WhatsApp' },
  { f: 'other_socials',  l: 'Другие соцсети' },
  { f: 'socials_valid',  l: 'Соцсети активны' },
  { f: 'aggregator_url', l: 'Taplink / Linktree' },
  { f: 'yandex_maps_url',l: 'Яндекс.Карты' },
  { f: 'twogis_url',     l: '2ГИС' },
  { f: 'query',          l: 'Запрос' },
  { f: 'parsed_at',      l: 'Дата сбора' },
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
function saveApiKeys() {
  const btn = document.getElementById('btn-save-key');
  const yandexKey = document.getElementById('f-apikey').value.trim();
  const twogisKey = (document.getElementById('f-2gis-key') || {}).value?.trim() || '';
  const status = document.getElementById('apikey-status');

  if (!yandexKey && !twogisKey) {
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
    body: JSON.stringify({yandex_api_key: yandexKey, twogis_api_key: twogisKey})
  })
  .then(r => r.json().then(d => ({ok: r.ok, data: d})))
  .then(({ok, data}) => {
    if (ok && data.ok) {
      showToast(data.message || 'Ключи сохранены в .env', 'success');
      show(true, data.message || 'Ключи сохранены в .env');
      // Empty fields = «использовать сохранённое в .env» — reflect it
      if (yandexKey) document.getElementById('f-apikey').value = '';
      if (twogisKey) { document.getElementById('f-2gis-key').value = ''; refreshSourceKeyState(); }
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

function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.getElementById('btn-theme').textContent = dark ? '☀️' : '🌙';
}

function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const next = !isDark;
  applyTheme(next);
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

function checkForUpdates(silent) {
  // Frozen build: /update/status also reports latest version + whether the
  // in-app updater is available. Source runs fall back to /check-version.
  return fetch('/update/status')
    .then(r => r.json())
    .then(data => {
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
      if (res.error) showToast('Не удалось связаться с GitHub — проверьте интернет', 'error');
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

// Periodic background check (silent — banner only, no toasts)
setInterval(() => checkForUpdates(true), UPDATE_CHECK_INTERVAL);

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

  const banner = document.createElement('div');
  banner.id = 'update-banner';
  banner.innerHTML = `
    <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + escapeHtml(changelog) : ''}</span>
    <button class="ub-btn" id="ub-changelog" onclick="showChangelog()" title="Подробнее об изменениях в новой версии">📄 Что нового</button>
    <button class="ub-btn" id="ub-self-update" onclick="selfUpdate()" title="Скачать и установить прямо из приложения">⬆ Обновить сейчас</button>
    <a class="ub-btn" href="${url}" target="_blank" rel="noopener noreferrer" title="Страница релизов на GitHub">GitHub ↗</a>
    <button class="ub-close" onclick="this.parentElement.remove()">✕</button>
  `;
  document.body.prepend(banner);
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

  // Initialize city combobox — start empty, user picks cities fresh each time
  selectedCities = [];
  initCitySelect();
  loadCityHistoryMeta();

  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    // Restore non-city settings only
    if (saved) delete saved.city;
    applySettings(saved);
  } catch {}
  // Set initial social mode active state + social net checkboxes
  initSocialNetCheckboxes();
  setSocialMode(socialMode);
  setParseMode(parseMode);
  renderPresets();
  loadExcelCols();
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

  // Check Playwright availability
  fetch('/status').then(r => r.json()).then(s => {
    if (s.playwright_available === false) {
      const el = document.getElementById('playwright-notice');
      if (el) el.style.display = '';
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