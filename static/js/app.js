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
let notificationsEnabled = false;  // toggle state
let requiredSocials = new Set();   // AND filter: must have ALL selected socials
let _lastCompletedCityIdx = 0;     // track last completed city for notification

// ═══════════════════════════════════════════
//  Checkbox styling
// ═══════════════════════════════════════════
document.querySelectorAll('.chk input').forEach(cb => {
  cb.addEventListener('change', () => cb.closest('.chk').classList.toggle('on', cb.checked));
});

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
  // Show/hide social network filter checkboxes
  const netFilter = document.getElementById('social-network-filter');
  if (netFilter) netFilter.style.display = mode === 'with_socials' ? '' : 'none';
  if (mode !== 'with_socials') requiredSocials.clear();
  // Re-filter table if results exist
  if (allResults.length) filterTable();
}

// ═══════════════════════════════════════════
//  Social network checkboxes (AND filter)
// ═══════════════════════════════════════════
function initSocialNetCheckboxes() {
  const grid = document.getElementById('social-net-chk-grid');
  if (!grid) return;
  grid.innerHTML = Object.entries(SLABELS).map(([key, label]) =>
    `<label class="chk"><input type="checkbox" value="${key}" onchange="toggleRequiredSocial('${key}', this.checked)">${label}</label>`
  ).join('');
}

function toggleRequiredSocial(key, checked) {
  if (checked) requiredSocials.add(key);
  else requiredSocials.delete(key);
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
    alert('Уведомления запрещены браузером. Разрешите их в настройках браузера.');
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
  // Re-render stats when switching to stats tab (fixes empty stats panel)
  if (name === 'stats' && allResults.length) {
    const elapsed = (Date.now() - startTime) / 1000;
    renderStats(allResults, elapsed);
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
function appendLog(level, msg) {
  const ph = document.getElementById('log-ph');
  if (ph) ph.remove();
  const d = document.createElement('div');
  d.className = 'll ' + level;
  d.textContent = msg.replace(/\x1b\[[0-9;]*m/g, '');
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}
function clearLog() { logEl.innerHTML = ''; }

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
    min_rating:      +document.getElementById('f-rating').value  || 0,
    min_reviews:     +document.getElementById('f-reviews').value || 0,
    use_grid:        document.getElementById('f-grid').checked,
    grid_radius:     +document.getElementById('f-grad').value  || 20,
    grid_step:       +document.getElementById('f-gstep').value || 5,
    validate_socials:document.getElementById('f-validate').checked,
    api_key:         document.getElementById('f-apikey').value.trim(),
    social_mode:     socialMode,
    required_socials: [...requiredSocials],
  };
}

function startRun() {
  const params = getParams();
  if (!params.queries.length) { alert('Введите хотя бы один запрос'); return; }
  if (!params.cities.length)  { alert('Введите хотя бы один город'); return; }

  clearLog();
  allResults = []; filteredRows = [];
  if (_liveRenderTimer) { clearTimeout(_liveRenderTimer); _liveRenderTimer = null; }
  _resetTableBadge();
  document.getElementById('tbl-body').innerHTML =
    '<tr><td colspan="9" class="no-data">Ожидание результатов…</td></tr>';
  document.getElementById('stats-body').innerHTML =
    '<div class="no-data">Ожидание результатов…</div>';
  document.getElementById('dl-section').style.display = 'none';
  mapInited = false; if (leafMap) { leafMap.remove(); leafMap = null; }
  document.getElementById('map-container').innerHTML = '';

  _lastCompletedCityIdx = 0;
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
        resetBtn(); setStatus('error','✖ Ошибка'); hideProgress();
        return;
      }
      if (data && data.queued) {
        appendLog('info', `  ⏳ Поиск поставлен в очередь (позиция: ${data.position}). Текущий поиск завершится автоматически.`);
        setStatus('queued', '⏳ В очереди');
        document.getElementById('btn-txt').textContent = 'В очереди…';
        setProgress(0, `Очередь: позиция ${data.position}`);
        // Poll /status and start SSE when our queued run becomes active
        const _queuedRunId = data.run_id;
        const _pollInterval = setInterval(() => {
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
    // Play sound for city completion
    if (notificationsEnabled && Notification && Notification.permission === 'granted') {
      playCityDoneSound(name, idx, total);
    }
  }
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

    // Update count label
    document.getElementById('tbl-count').textContent =
      filteredRows.length ? `${filteredRows.length} записей` : '';

    // Re-render only if results tab is active
    if (document.getElementById('p-table').classList.contains('active')) {
      renderPage();
    }
  }, 250);
}

function onRunDone(msg) {
  const stopped = msg.stopped;
  const skippedCities = msg.skipped_cities || [];
  setStatus(stopped ? 'stopped' : 'done', stopped ? '⏹ Остановлено' : '✔ Готово');
  document.title = 'Яндекс.Карты — Парсер бизнесов';
  resetBtn();
  hideProgress();
  showDownloads(msg.files || [], msg.formats || []);
  const elapsed = (Date.now() - startTime) / 1000;
  // Load results: prefer internal frontend file, then combined, then any JSON
  const jf = (msg.files || []).find(f => f === '_results_for_frontend.json')
    || (msg.files || []).find(f => f.endsWith('.json') && !f.startsWith('_'));
  const cityFiles = (msg.files || []).filter(f => f.endsWith('.json') && !f.startsWith('_'));
  // Always render stats from live-streamed data as immediate fallback
  if (allResults.length) {
    renderStats(allResults, elapsed, undefined, skippedCities);
  }
  if (jf) {
    fetch('/results/' + encodeURIComponent(jf))
      .then(r => r.json())
      .then(data => {
        // Only overwrite if server returned actual data; keep live-streamed otherwise
        if (Array.isArray(data) && data.length > 0) {
          allResults = data;
        }
        _resetTableBadge();
        loadReviewed();
        renderTable(allResults);
        // Re-render stats with server-side data (may include all cities)
        if (cityFiles.length > 1) {
          _loadCityStats(cityFiles, elapsed, skippedCities);
        } else {
          renderStats(allResults, elapsed, undefined, skippedCities);
        }
        if (allResults.length) showTab('table');
      })
      .catch(() => {
        // JSON fetch failed — use live-streamed results
        _resetTableBadge();
        renderTable(allResults);
        renderStats(allResults, elapsed, undefined, skippedCities);
        if (allResults.length) showTab('table');
      });
  } else {
    _resetTableBadge();
    // No JSON file — render stats from live-streamed results
    if (allResults.length) {
      renderStats(allResults, elapsed, undefined, skippedCities);
      showTab('table');
    }
  }
  // Compute filtered count for notification
  const SOCIAL_KEYS = Object.keys(SOCIALS);
  const filteredCount = allResults.filter(r => {
    if (socialMode === 'with_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
      if (!hasAny) return false;
    } else if (socialMode === 'without_socials') {
      const hasAny = SOCIAL_KEYS.some(k => r[k]) || r.other_socials;
      if (hasAny) return false;
    }
    if (requiredSocials.size > 0) {
      if (![...requiredSocials].every(key => r[key])) return false;
    }
    return true;
  }).length;
  // Play completion sound + notification when enabled
  if (!stopped && notificationsEnabled && Notification && Notification.permission === 'granted') {
    playDoneSound();
    // Note: per-city notifications are handled by handleCityDone()
    const total = allResults.length;
    const notifText = filteredCount === total
      ? `Найдено ${total} компаний`
      : `${filteredCount}/${total} компаний прошли фильтр`;
    sendNotification('Поиск завершён', notifText);
  }
}

// Load stats from individual city JSON files for per-city breakdown
function _loadCityStats(cityFiles, elapsed, skippedCities) {
  const cityResults = [];
  let loaded = 0;
  cityFiles.forEach(f => {
    fetch('/results/' + encodeURIComponent(f))
      .then(r => r.json())
      .then(data => {
        cityResults.push({file: f, data: Array.isArray(data) ? data : []});
      })
      .catch(() => cityResults.push({file: f, data: []}))
      .finally(() => {
        loaded++;
        if (loaded >= cityFiles.length) {
          renderStats(allResults, elapsed, cityResults, skippedCities);
        }
      });
  });
}

function resetBtn() {
  document.getElementById('btn-run').disabled = false;
  document.getElementById('btn-icon').textContent = '🚀';
  document.getElementById('btn-txt').textContent = 'Запустить';
  document.getElementById('btn-stop').style.display = 'none';
  document.getElementById('btn-skip').style.display = 'none';
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
  renderPage();
}

function filterTable() {
  const q = document.getElementById('tbl-search').value.trim().toLocaleLowerCase('ru-RU');
  const SOCIAL_KEYS = Object.keys(SOCIALS);
  filteredRows = allResults.filter(r => {
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
    const rawReviewUrl = r.yandex_maps_url || '';
    const reviewUrl = escapeHtml(rawReviewUrl);
    const isRev = rawReviewUrl && reviewedState[rawReviewUrl];
    return `
    <tr class="${isRev ? 'is-reviewed' : ''}">
      <td style="text-align:center"><input type="checkbox" class="rev-cb"
        ${isRev ? 'checked' : ''} ${!rawReviewUrl ? 'disabled' : ''}
        data-review-url="${reviewUrl}"
        onchange="toggleReviewed(this.dataset.reviewUrl, this)"></td>
      <td>${start + i + 1}</td>
      <td><a href="${escapeHtml(safeUrl(r.yandex_maps_url))}" target="_blank" rel="noopener noreferrer" style="color:var(--g);font-weight:600;text-decoration:none">${escapeHtml(r.name || '—')}</a></td>
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
  .catch(e => alert('Ошибка экспорта: ' + e.message));
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
        ${socials    ? `<div style="margin-top:5px">${socials}</div>`       : ''}
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

function renderStats(data, elapsed, cityResults, skippedCities) {
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

  // Socials breakdown
  const socialCounts = Object.keys(SOCIALS).map(p => ({
    name: SLABELS[p], count: data.filter(r => r[p]).length, color: SOCIALS[p]
  })).filter(s => s.count > 0).sort((a,b) => b.count - a.count);

  // Categories
  const catMap = {};
  data.forEach(r => (r.category||'').split(',').forEach(c => {
    const t = c.trim(); if (t) catMap[t] = (catMap[t]||0) + 1;
  }));
  const cats = Object.entries(catMap).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const maxC = cats[0]?.[1] || 1;

  // Per-city breakdown
  let cityCardsHtml = '';
  if (cityResults && cityResults.length > 1) {
    // Sort by count desc
    const sorted = cityResults.sort((a,b) => b.data.length - a.data.length);
    const maxCityCount = sorted[0]?.data.length || 1;
    cityCardsHtml = `<div class="stat-section"><h3>По городам</h3><div class="stat-city-grid">`;
    sorted.forEach(cr => {
      const cd = cr.data;
      const cityTotal = cd.length;
      const cityWithSo = cd.filter(r => Object.keys(SOCIALS).some(p => r[p])).length;
      // Try to extract city name from filename: slug_YYYYMMDD_HHMMSS.json
      const parts = cr.file.replace('.json', '').split('_');
      // Remove timestamp (last 2 parts: date_time)
      const nameParts = parts.slice(0, -2);
      let cityName = nameParts.join(' ').replace(/_/g, ' ');
      // Capitalize first letter of each word
      cityName = cityName.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
      const pct = Math.round(cityTotal / maxCityCount * 100);
      cityCardsHtml += `<div class="stat-city-card">
        <h4>${escapeHtml(cityName)}</h4>
        <div class="bar-row" style="margin-bottom:8px"><div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:var(--c)"></div></div><div class="bar-val">${cityTotal}</div></div>
        <div class="stat-mini-row"><span>Всего</span><span>${cityTotal}</span></div>
        <div class="stat-mini-row"><span>С соцсетями</span><span>${cityWithSo}</span></div>
        <div class="stat-mini-row"><span>Без соцсетей</span><span>${cityTotal - cityWithSo}</span></div>
      </div>`;
    });
    cityCardsHtml += `</div></div>`;
  }

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
    rating:   document.getElementById('f-rating').value,
    reviews:  document.getElementById('f-reviews').value,
    grid:     document.getElementById('f-grid').checked,
    grad:     document.getElementById('f-grad').value,
    gstep:    document.getElementById('f-gstep').value,
    validate: document.getElementById('f-validate').checked,
    socialMode: socialMode,
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
  if (s.rating   != null) document.getElementById('f-rating').value   = s.rating;
  if (s.reviews  != null) document.getElementById('f-reviews').value  = s.reviews;
  if (s.grid     != null) { document.getElementById('f-grid').checked = s.grid; toggleGrid(); document.getElementById('grid-lbl').classList.toggle('on', s.grid); }
  if (s.grad     != null) document.getElementById('f-grad').value    = s.grad;
  if (s.gstep    != null) document.getElementById('f-gstep').value   = s.gstep;
  if (s.validate != null) { document.getElementById('f-validate').checked = s.validate; document.getElementById('f-validate').closest('.chk').classList.toggle('on', s.validate); }
  if (s.socialMode) setSocialMode(s.socialMode);
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
    const key = r.yandex_maps_url || (r.name + '|' + r.address);
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

document.addEventListener('click', e => {
  const wrap = document.querySelector('.col-toggle-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('col-dropdown')?.classList.remove('open');
  }
});

// ═══════════════════════════════════════════
//  API key save to .env
// ═══════════════════════════════════════════
function saveApiKey() {
  const btn = document.getElementById('btn-save-key');
  const apiKey = document.getElementById('f-apikey').value.trim();

  if (!apiKey) { showToast('Введите ключ API', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '⏳';

  fetch('/save-api-key', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({api_key: apiKey})
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      showToast(data.message || 'Ключ сохранён', 'success');
    } else {
      showToast(data.error || 'Ошибка сохранения', 'error');
    }
  })
  .catch(e => {
    showToast('Ошибка соединения: ' + e.message, 'error');
  })
  .finally(() => {
    btn.disabled = false;
    btn.textContent = '💾 Сохранить';
  });
}

// ── Toast notification (slides from top) ──
let _toastTimer = null;
function showToast(message, type) {
  // Remove existing toast and clear its timer
  const old = document.querySelector('.toast');
  if (old) {
    clearTimeout(old._autoHide);
    old.remove();
  }
  clearTimeout(_toastTimer);

  const toast = document.createElement('div');
  toast.className = 'toast ' + (type || 'success');
  const icon = type === 'error' ? '✕' : '✓';
  toast.innerHTML = `<span style="font-size:16px;font-weight:800">${icon}</span> ${message}`;
  document.body.appendChild(toast);

  // Slide in
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      toast.classList.add('show');
    });
  });

  // Auto-hide after 3 seconds
  toast._autoHide = setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 400);
  }, 3000);
  _toastTimer = toast._autoHide;
}

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

  if (!file)    { alert('Выберите Excel-файл с результатами'); return; }
  if (!token)   { alert('Введите VK access_token'); return; }
  if (!message) { alert('Шаблон сообщения не может быть пустым'); return; }

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
function checkForUpdates() {
  fetch('/check-version')
    .then(r => r.json())
    .then(data => {
      if (data.newer) {
        showUpdateBanner(data.remote, data.changelog || '', data.download_url || '');
      }
    })
    .catch(() => {});
}

function showUpdateBanner(newVer, changelog, url) {
  // Remove existing banner if any
  const existing = document.getElementById('update-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'update-banner';
  banner.innerHTML = `
    <span class="ub-text">🔄 Доступна новая версия <b>v${newVer}</b>${changelog ? ' — ' + changelog : ''}</span>
    <a class="ub-btn" href="${url}" target="_blank" rel="noopener noreferrer">Скачать обновление</a>
    <button class="ub-close" onclick="this.parentElement.remove()">✕</button>
  `;
  document.body.prepend(banner);
}
(function init() {
  // Theme
  const savedTheme = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(savedTheme ? savedTheme === 'dark' : prefersDark);

  // Initialize city combobox — start empty, user picks cities fresh each time
  selectedCities = [];
  initCitySelect();

  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    // Restore non-city settings only
    if (saved) delete saved.city;
    applySettings(saved);
  } catch {}
  // Set initial social mode active state + social net checkboxes
  initSocialNetCheckboxes();
  setSocialMode(socialMode);
  renderPresets();
  loadReviewed();
  loadColState();
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

  // Reload files list when switching to sender tab
  const _origShowTab = showTab;
  showTab = function(name) {
    document.querySelector('.right-col').classList.add('revealed');
    document.getElementById('onboarding-screen').style.display = 'none';
    _origShowTab(name);
    if (name === 'sender') loadSenderFiles();
  };
})();