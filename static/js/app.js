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
  // Re-filter table if results exist
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
//  Tabs
// ═══════════════════════════════════════════
function showTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('t-' + name).classList.add('active');
  document.getElementById('p-' + name).classList.add('active');
  if (name === 'map' && allResults.length && !mapInited) initMap();
  if (name === 'map' && leafMap) setTimeout(() => leafMap.invalidateSize(), 50);
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
  // City transition event: city/idx/total/name
  if (parts[0] === 'city' && parts.length >= 4) {
    const idx   = parseInt(parts[1]);
    const total = parseInt(parts[2]);
    const name  = parts.slice(3).join('/');  // city name may contain /
    const label = `🏙  Город ${idx}/${total}: ${name}`;
    setProgress(-1, label);
    appendLog('info', label);
    // Update live stats
    const lsStage = document.getElementById('ls-stage');
    if (lsStage) lsStage.textContent = name;
    // Play city completion sound when notifications enabled (idx > 1 = previous city done)
    if (idx > 1 && Notification && Notification.permission === 'granted') {
      playCityDoneSound(name, idx, total);
    }
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
    cities:          document.getElementById('f-city').value.split('\n').map(s=>s.trim()).filter(Boolean),
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

  setStatus('running', '⏳ Выполняется');
  setProgress(0, 'Запуск…');
  document.getElementById('btn-run').disabled = true;
  document.getElementById('btn-icon').innerHTML = '<span class="spin"></span>';
  document.getElementById('btn-txt').textContent = 'Выполняется…';
  document.getElementById('btn-stop').style.display = 'inline-block';
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
  fetch('/stop', {method:'POST'}).catch(()=>{});
  appendLog('warn', '  [!] Остановка запрошена…');
}

function startSSE(runId) {
  const url = runId ? `/logs?run_id=${runId}` : '/logs';
  evtSource = new EventSource(url);
  evtSource.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'ping') return;
    if (msg.type === 'log') {
      if (msg.level === 'progress') { handleProgress(msg.msg); return; }
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
  setStatus(stopped ? 'stopped' : 'done', stopped ? '⏹ Остановлено' : '✔ Готово');
  document.title = 'Яндекс.Карты — Парсер бизнесов';
  resetBtn();
  hideProgress();
  showDownloads(msg.files || [], msg.formats || []);
  // Reload from canonical JSON file (authoritative ordered list)
  const jf = (msg.files || []).find(f => f.endsWith('.json'));
  if (jf) {
    fetch('/results/' + encodeURIComponent(jf))
      .then(r => r.json())
      .then(data => {
        allResults = Array.isArray(data) ? data : [];
        _resetTableBadge();
        loadReviewed();
        renderTable(allResults);
        renderStats(allResults, (Date.now() - startTime) / 1000);
        if (allResults.length) showTab('table');
      });
  } else {
    _resetTableBadge();
  }
  // Play completion sound when notifications are enabled
  if (!stopped && Notification && Notification.permission === 'granted') {
    playDoneSound();
    sendNotification('Поиск завершён',
      allResults.length ? `Найдено ${allResults.length} компаний` : 'Поиск завершён', '🗺');
  }
}

function resetBtn() {
  document.getElementById('btn-run').disabled = false;
  document.getElementById('btn-icon').textContent = '🚀';
  document.getElementById('btn-txt').textContent = 'Запустить';
  document.getElementById('btn-stop').style.display = 'none';
}

// ═══════════════════════════════════════════
//  Downloads
// ═══════════════════════════════════════════
const ICONS = {xlsx:'📊', json:'📋', csv:'📄', html:'🗺'};
function fileIcon(n) { for (const [ext,ic] of Object.entries(ICONS)) if (n.endsWith('.'+ext)) return ic; return '📁'; }

function showDownloads(files, formats) {
  const allowed = new Set(formats || []);
  const filtered = files.filter(f => {
    // Always allow non-standard extensions (map html, etc.)
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
    // Social filter — OR logic: row must have at least one selected network
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

function renderStats(data, elapsed) {
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

  const body = document.getElementById('stats-body');
  body.innerHTML = `
    <div class="stat-cards">${cards.map(c =>
      `<div class="stat-card"><div class="num">${c.num}</div><div class="lbl">${c.lbl}</div></div>`
    ).join('')}</div>

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
}

// ═══════════════════════════════════════════
//  localStorage settings
// ═══════════════════════════════════════════
const SETTINGS_KEY = 'yp_settings_v1';
const PRESETS_KEY  = 'yp_presets_v1';

function getCurrentSettings() {
  return {
    queries:  document.getElementById('f-queries').value,
    city:     document.getElementById('f-city').value,  // kept for backward compat
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
  if (s.city     != null) document.getElementById('f-city').value      = Array.isArray(s.city) ? s.city.join('\n') : s.city;
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
  if (perm === 'granted') {
    btn.className = 'granted';
    icon.textContent = '🔔'; txt.textContent = 'Уведомления вкл.';
    btn.onclick = null; btn.style.cursor = 'default';
  } else if (perm === 'denied') {
    btn.className = 'denied';
    icon.textContent = '🔕'; txt.textContent = 'Уведомления запрещены';
    btn.onclick = null;
  } else {
    btn.className = '';
    icon.textContent = '🔔'; txt.textContent = 'Уведомления';
    btn.onclick = requestNotify;
  }
}

function requestNotify() {
  if (!('Notification' in window)) return;
  Notification.requestPermission().then(() => updateNotifyBtn());
}

function sendNotification(title, body, icon) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    const n = new Notification(title, {body, icon: icon || '🗺'});
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
    sendNotification(`Город ${idx}/${total} завершён`, `${cityName} — готово`, '🏙');
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
//  API key test
// ═══════════════════════════════════════════
function testApiKey() {
  const btn = document.getElementById('btn-test-key');
  const statusEl = document.getElementById('apikey-status');
  const apiKey = document.getElementById('f-apikey').value.trim();

  btn.disabled = true;
  btn.textContent = '…';
  statusEl.className = 'checking';
  statusEl.style.display = '';
  statusEl.textContent = 'Проверяем ключ…';

  fetch('/test-api-key', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({api_key: apiKey})
  })
  .then(r => r.json())
  .then(data => {
    statusEl.className = data.ok ? 'ok' : 'err';
    statusEl.textContent = (data.ok ? '✓ ' : '✗ ') + (data.message || data.error || 'Неизвестный ответ');
  })
  .catch(e => {
    statusEl.className = 'err';
    statusEl.textContent = '✗ Ошибка соединения: ' + e.message;
  })
  .finally(() => {
    btn.disabled = false;
    btn.textContent = 'Проверить';
  });
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

// ═══════════════════════════════════════════
//  City autocomplete
// ═══════════════════════════════════════════
const CITIES = [
  'Москва','Санкт-Петербург','Новосибирск','Екатеринбург','Казань',
  'Нижний Новгород','Челябинск','Самара','Уфа','Ростов-на-Дону',
  'Красноярск','Воронеж','Пермь','Волгоград','Краснодар',
  'Саратов','Тюмень','Тольятти','Ижевск','Барнаул',
  'Ульяновск','Иркутск','Хабаровск','Ярославль','Владивосток',
  'Махачкала','Томск','Оренбург','Кемерово','Новокузнецк',
  'Рязань','Астрахань','Набережные Челны','Пенза','Липецк',
  'Тула','Киров','Чебоксары','Калининград','Брянск',
  'Курск','Иваново','Магнитогорск','Тверь','Ставрополь',
  'Нижний Тагил','Белгород','Архангельск','Владимир','Сочи',
  'Симферополь','Якутск','Улан-Удэ','Мурманск','Чита',
  'Вологда','Череповец','Саранск','Смоленск','Орёл',
  'Калуга','Курган','Тамбов','Кострома','Сургут',
  'Нижневартовск','Новороссийск','Ханты-Мансийск','Нальчик','Владикавказ',
  'Грозный','Майкоп','Черкесск','Элиста','Нарьян-Мар',
  // CIS
  'Минск','Алматы','Ташкент','Баку','Бишкек','Астана','Нур-Султан',
  'Тбилиси','Ереван','Душанбе','Ашхабад','Кишинёв',
];

// City autocomplete removed — textarea now supports multi-city input.

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
//  Init
// ═══════════════════════════════════════════
(function init() {
  // Theme
  const savedTheme = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(savedTheme ? savedTheme === 'dark' : prefersDark);

  try { applySettings(JSON.parse(localStorage.getItem(SETTINGS_KEY))); } catch {}
  // Set initial social mode active state
  setSocialMode(socialMode);
  renderPresets();
  loadReviewed();
  loadColState();
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

  // Reload files list when switching to sender tab
  const _origShowTab = showTab;
  showTab = function(name) {
    document.querySelector('.right-col').classList.add('revealed');
    document.getElementById('onboarding-screen').style.display = 'none';
    _origShowTab(name);
    if (name === 'sender') loadSenderFiles();
  };
})();