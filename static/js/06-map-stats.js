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
// соцсеть — полное кольцо (окружность целиком, а не 100%-dash). Точные
// значения — только в легенде: подписи внутри секторов сливались с соседней
// дугой и наезжали на край кольца.
function donutHTML(rows, centerLabel) {
  if (!rows || !rows.length) return '';
  const total = rows.reduce((s, r) => s + r.count, 0) || 1;
  const C = 2 * Math.PI * 70;
  let offset = 0;
  const arcs = rows.map(r => {
    const frac = r.count / total;
    const len = Math.max(frac * C, 0.005 * C);
    const dash = `${len} ${C - len}`;
    const el = `<circle class="donut-arc" cx="84" cy="84" r="70"`
      + ` stroke="${r.color}" stroke-dasharray="${dash}"`
      + ` style="--dash-rest:${(C - len).toFixed(1)}"`
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
    + `<circle class="donut-track" cx="84" cy="84" r="70"></circle>${single}</svg>`
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
