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
  // Where the search stopped → tooltip + toast.
  const pos = (resume && resume.position) || {};
  let posTxt = '';
  if (pos.city) {
    posTxt = 'Остановились: ' + pos.city;
    if (pos.cities_total) posTxt += ' (город ' + (pos.city_idx || '?') + ' из ' + pos.cities_total + ')';
    if (pos.query) posTxt += ' • запрос «' + pos.query + '»';
    if (pos.points_total) posTxt += ' • точка ' + (pos.point || '?') + '/' + pos.points_total;
    if (pos.records) posTxt += ' • найдено ' + pos.records;
  }
  const title = posTxt
    ? 'Продолжить поиск с места паузы. ' + posTxt
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
    appendLog('info', '  📍 ' + posTxt);
  }
  showToast(posTxt ? '⏸ ' + posTxt : 'Поиск на паузе — прогресс сохранён', 'info');
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
// «Кого ищем: кафе, ресторан, парикмахерская • Городов: 3».
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
  el.textContent = `${qPart} • ${cPart}`;
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
