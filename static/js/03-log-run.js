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
  // Активная вкладка — единственная в порядке табуляции, и только у неё
  // aria-selected="true". Раньше класс .active переезжал, а aria-selected
  // оставался на прежней вкладке: скринридер сообщал о выбранной не той
  // вкладке, а Tab обходил все шесть кнопок подряд.
  document.querySelectorAll('.tab-btn').forEach(b => {
    const on = b.id === 't-' + name;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
    b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('t-' + name).classList.add('active');
  document.getElementById('p-' + name).classList.add('active');
  if (name === 'map' && allResults.length && !mapInited) ensureMapReady();
  if (name === 'map' && leafMap) setTimeout(() => leafMap.invalidateSize(), 50);
  // Results tab: refresh city tabs + bulk counters (cheap, data may be stale)
  if (name === 'table') {
    // Первое открытие: грузим срез результатов (raw/processed по _resultsView).
    // Повторные открытия не перезапрашивают — таблица уже содержит данные.
    // ВО ВРЕМЯ ПРОГОНА не грузим: живой поток SSE уже наполняет таблицу, а
    // подгрузка с диска заменяла накопленные записи пустым/частичным срезом
    // (таблица «пропадала» до следующих результатов) и смешивала
    // отфильтрованный срез с нефильтрованными live-записями.
    if (!_resultsLoadedOnce && !isRunActive()) setResultsView(_resultsView);
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
  // '' не годится: в CSS у обоих display:none, а снятие инлайна лишь
  // возвращает к нему — прогресс-бар так и не показывался.
  pw.style.display = pct >= 0 ? 'block' : 'none';
  pl.style.display = pct >= 0 ? 'block' : 'none';
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
      meta: [],         // per-line {noise,err,tech,sum} — counters + trimming
      stats: {total: 0, noise: 0, err: 0, tech: 0, sum: 0},
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
      if (meta.sum)   S.stats.sum--;
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
// Итоги прогона: строки-результаты и карточка «Статистика». Это ЕДИНСТВЕННОЕ
// содержимое вкладки «Важные» (ошибки живут во «Ошибках», механика — в
// «Технических» и «Все»), поэтому класс .sum — ровно у этих строк.
// 📅 — журнал источников (дата и время сбора): одна строка на прогон,
// но именно она отвечает «на какую дату актуальны данные».
const LOG_SUMMARY_RE = /✅|📦\s*Raw|🎯\s*Processed|💾 Карта|⏪|⏭|⏹|⏸|📊|📅/;
function _logIsSummary(lvl, text) {
  if (LOG_SUMMARY_RE.test(text)) return true;
  // Явные «ok»-строки без признаков механики тоже итоги (пропуск города,
  // успешные сохранения от обработчиков, которые шлют текст без эмодзи).
  return lvl === 'ok' && !LOG_NOISE_RE.test(text);
}
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
  const sum = _logIsSummary(lvl, clean);
  const isCity = _logIsCity(clean);
  // «🚨» → красная плашка, «⚠» + «израсходовано/лимит» → янтарная.
  let extraCls = '';
  if (/🚨/.test(clean) || (/⚠/.test(clean) && /израсходовано|квота|лимит .*запросов/i.test(clean))) {
    extraCls = /🚨/.test(clean) ? 'quota-critical' : 'quota-warn';
  }
  // A city header opens a new foldable block; every later line joins it.
  let blk = -1;
  if (isCity) S.block += 1;
  blk = S.block;
  let cls = lvl + (noise ? ' noise' : '') + (sum ? ' sum' : '') + (_logIndent(clean) ? ' ind-1' : '');
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
  S.meta.push({noise, err, tech, sum});
  S.stats.total++;
  if (noise) S.stats.noise++;
  if (err)   S.stats.err++;
  if (tech)  S.stats.tech++;
  if (sum)   S.stats.sum++;
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
  // «Важные» — только итоги: зелёные строки-результаты и карточка «Статистика».
  important: () => ({ok: _ls().stats.sum > 0,
                     msg: 'Итогов пока нет — включите «Все»'}),
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
  auto:        '<svg class="ico" aria-hidden="true"><use href="#i-auto"/></svg>',
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
  star:        '<svg class="ico" aria-hidden="true"><use href="#i-star"/></svg>',
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
  S.stats = {total: 0, noise: 0, err: 0, tech: 0, sum: 0};
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

    // Update live stats strip. Число растёт рывками, поэтому смена значения
    // отмечается короткой пульсацией: без неё счётчик читается как статичная
    // цифра, а не как «идёт прямо сейчас».
    const lsFound = document.getElementById('ls-found-num');
    if (lsFound) {
      const next = String(found);
      if (lsFound.textContent !== next) {
        lsFound.textContent = next;
        lsFound.classList.remove('pop');
        void lsFound.offsetWidth;          // перезапуск анимации
        lsFound.classList.add('pop');
      }
    }
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
    // Пусто — сервер возьмёт сохранённый выбор или первый найденный браузер.
    browser_path:    (document.getElementById('f-browser') || {}).value || '',
    output_excel:    document.getElementById('f-excel').checked,
    output_json:     document.getElementById('f-json').checked,
    output_csv:      document.getElementById('f-csv').checked,
    output_map:      document.getElementById('f-map').checked,
    max_pages:       +document.getElementById('f-pages').value   || 1,
    max_workers:     +document.getElementById('f-workers').value || 20,
    query_workers:   +document.getElementById('f-query-workers').value || 2,
    max_candidates:  getMaxCandidates(),
    parse_mode:      parseMode,
    excel_columns:   getExcelCols(),
    use_grid:        _gridMode === 'manual',
    grid_radius:     +document.getElementById('f-grad').value  || 20,
    grid_step:       +document.getElementById('f-gstep').value || 5,    // Карточку организации грузим, если в «Что парсить» отмечено хотя бы одно
    // «карточное» поле (соцсети, телефон, рейтинг, сайт): только на ней они и
    // есть. Раньше флаг повторял один «Соцсети», и без них терялся телефон.
    fetch_detail:    detailFetchEnabled(),
    collapse_chains: document.getElementById('f-collapse-chains').checked,
    chain_key:       (document.getElementById('f-chain-key') || {}).value || 'name_city',
    // Two-stage pipeline: the web app always collects raw (stage 1);
    // parse_mode is applied afterwards (stage 2).
    pipeline:        'raw',
    raw_mode:        (document.getElementById('f-raw-mode') || {}).value || 'keep',
    continue_cities: document.getElementById('f-continue')?.checked || false,
    continue_limit:  parseInt((document.getElementById('f-continue-limit')||{}).value, 10) || 0,    // Соцсети выключены — фильтр по соцсетям и обязательные сети бессмысленны.    social_mode:     socialsEnabled() ? socialMode : 'all',    required_socials: socialsEnabled() ? [...requiredSocials] : [],
    // Stage-2 lead scoring / VK activity (accordion «Фильтрация результата»).
    vk_check:         socialsEnabled() && vkTokenReady && !!(document.getElementById('f-vk-check')||{}).checked,
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
  // Live-clear ошибок навешено один раз в init() — здесь только сбрасываем
  // прежнюю рамку. Раньше слушатели добавлялись на каждый запуск и копились.
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
        // Версия ниже минимально допустимой: показываем то же окно, что и
        // при старте — чтобы было видно, куда обновляться (routes/update.py).
        if (data && data.blocked) showVersionGate(data);
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
            if (s.active_run === _queuedRunId) {
              // Our run is now active — connect SSE
              clearInterval(_pollInterval);
              startTime = Date.now();
              _runEnd = null;
              startSSE();
            } else if (!s.queued) {
              // Очередь сняли/отменили, но наш запрос так и не стал активным:
              // без этой ветки UI навсегда застревал в «В очереди…».
              clearInterval(_pollInterval);
              appendLog('warn', '  [!] Поиск убран из очереди, не дождавшись запуска. Запустите его снова.');
              resetBtn(); setStatus('stopped', 'Снят с очереди'); hideProgress();
              showToast('Поиск убран из очереди — запустите заново', 'warning');
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
      modalA11y(overlay);
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
//  Клавиатура в полосе вкладок (шаблон ARIA tablist)
//
//  Стрелки ← → листают вкладки, Home/End — к первой и последней. Без этого
//  полоса из шести вкладок вела себя как шесть отдельных кнопок: Tab шёл по
//  каждой из них, а между вкладками приходилось ходить только мышью.
(function initTabListKeyboard() {
  if (typeof document === 'undefined' || !document.querySelector) return;
  const list = document.querySelector('.tab-bar');
  if (!list) return;
  const items = () => [...list.querySelectorAll('.tab-btn')];

  // Начальное состояние: в порядке табуляции — только активная вкладка
  // (highlighted в разметке), остальные доступны стрелками.
  items().forEach(b => {
    b.tabIndex = b.getAttribute('aria-selected') === 'true' ? 0 : -1;
  });

  list.addEventListener('keydown', e => {
    const cur = e.target && e.target.closest ? e.target.closest('.tab-btn') : null;
    if (!cur) return;
    const all = items();
    const i = all.indexOf(cur);
    if (i < 0) return;
    let next = null;
    if (e.key === 'ArrowRight')     next = all[(i + 1) % all.length];
    else if (e.key === 'ArrowLeft') next = all[(i - 1 + all.length) % all.length];
    else if (e.key === 'Home')      next = all[0];
    else if (e.key === 'End')       next = all[all.length - 1];
    if (!next || next === cur) return;
    e.preventDefault();
    next.focus();
    // Автоматическое переключение по стрелкам: у вкладок нет отдельного
    // «подтверждения», как у кнопок, и ожидание Enter читалось бы как поломка.
    showTab(next.id.replace(/^t-/, ''));
  });
})();

// ═══════════════════════════════════════════
//  Live per-city stats (multi-city runs)
