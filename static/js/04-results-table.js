// ═══════════════════════════════════════════
function isRunActive() {
  // Во время прогона кнопка НЕ disabled: она превращается в «⏸ Пауза»
  // (класс run-active), а на время graceful-паузы — run-paused. Опираться на
  // disabled нельзя: иначе бейдж статистики и ветка showTab('stats') не
  // срабатывали бы, пока идёт поиск.
  const btn = document.getElementById('btn-run');
  return !!btn && (btn.classList.contains('run-active') ||
                   btn.classList.contains('run-paused'));
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
  // Снять ранее запланированный отложенный проход ДО первого рендера:
  // doRender() обнуляет _liveStatsTimer, поэтому clearTimeout после него уже
  // не срабатывал и при частых city_done «осиротевшие» таймеры копились.
  if (_liveStatsTimer) { clearTimeout(_liveStatsTimer); _liveStatsTimer = null; }
  doRender();
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
    // Тот же набор фильтров, что и в filterTable(): иначе во время живого
    // прогона смена вкладки города, «Только непросмотренные», порог оценки и
    // объединение сетей молча откатывались бы к общему списку.
    let source = allResults;
    const collapseChains = document.getElementById('f-collapse-chains');
    if (collapseChains && collapseChains.checked) source = collapseChainsClient(source);
    filteredRows = _applyRowFilters(source);
    _orderFilteredRows();   // сохраняем выбранный пользователем порядок

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
      if (!r.name && !r.yandex_maps_url) return false;
      const k = r.yandex_maps_url || (r.name + '|' + r.address);
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
  // У сфер появилась новая запись в истории — подписи «когда и по каким
  // городам парсили» должны обновиться, а не ждать пяти минут TTL.
  if (typeof refreshSpheresSoon === 'function') refreshSpheresSoon();
}

// ═══════════════════════════════════════════
//  Downloads
// ═══════════════════════════════════════════
// ═════════════════════════════════════════
//  Results view: raw / processed / all (two-stage pipeline)
// ═════════════════════════════════════════
let _resultsView = 'raw';
// Первое открытие вкладки «Результаты» должно само подтянуть данные с
// сервера — иначе таблица остаётся на плейсхолдере «Запустите парсер».
let _resultsLoadedOnce = false;
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
  // Кнопка «Все» убрана из интерфейса: режим объединял два источника, но по
  // факту показывал обработанные — непонятный дубль. Значение 'all' из
  // старых вызовов/API приводится к «Обработанные», остальное — к сырым.
  if (!['raw', 'processed'].includes(view)) view = view === 'all' ? 'processed' : 'raw';
  _resultsView = view;
  _resultsLoadedOnce = true;   // вкладка больше не «пустая» — запрос ушёл
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

// 📁 «Открыть» — показать папку результатов в файл-менеджере ОС
// (Finder на macOS, проводник на Windows). Путь сервер берёт из настроек
// приложения — открытую папку нельзя подменить запросом.
function openOutputDir() {
  const btn = document.getElementById('btn-output-open');
  if (btn) { btn.disabled = true; btn.innerHTML = UI_ICONS.busy + 'Открываю…'; }
  postJSON('/output/open', {})
    .then(d => {
      if (!(d && d.ok)) showToast((d && d.error) || 'Не удалось открыть папку', 'error');
    })
    .catch(() => showToast('Сервер не ответил — папку открыть не удалось', 'error'))
    .finally(() => { if (btn) { btn.disabled = false; btn.innerHTML = UI_ICONS.folderOpen + 'Открыть'; } });
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
  // Даже один номер оборачиваем в .tbl-phone: голый текст в ячейке с
  // nowrap+max-width обрезался без эллипсиса (см. style.css).
  return `<div class="tbl-phone" title="${escapeHtml(raw)}">`
    + list.map(p => `<span>${escapeHtml(p)}</span>`).join('')
    + '</div>';
}

// Рейтинг и число отзывов с Яндекс.Карт (собираются на карточке организации).
// Пустые значения показываем прочерком, а не «0» — данных просто нет.
function ratingHTML(row) {
  const hasR = row.rating !== undefined && row.rating !== null && String(row.rating).trim() !== '';
  const hasC = row.reviews_count !== undefined && row.reviews_count !== null && String(row.reviews_count).trim() !== '';
  if (!hasR && !hasC) return '—';
  let h = '';
  if (hasR) h += `<span class="rate-val" title="Рейтинг Яндекс.Карт">★ ${escapeHtml(String(row.rating))}</span>`;
  if (hasC) h += `<span class="rate-rev" title="Отзывов на Яндекс.Картах">${escapeHtml(String(row.reviews_count))}</span>`;
  return h;
}

// Бейджи соцсетей строки. Каждая сеть может быть открыта отдельно —
// просмотренная гаснет (`social-opened`), не помечая всю организацию.
// Метки-галочки «просмотрено» рядом с бейджами убраны: они дублировали
// затемнение и читались как лишние символы в ячейке.
function socialsHTML(row, rowKey, rowIsRev) {
  let h = '';
  const key = escapeHtml(reviewKey(row));
  const checkOpened = typeof isSocialViewed === 'function';
  for (const [p, color] of Object.entries(SOCIALS)) {
    const url = row[p];
    if (!url) continue;
    const opened = checkOpened && isSocialViewed(row, p);
    h += `<a class="social-badge${opened ? ' social-opened' : ''}" style="background:${color}" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener noreferrer"`
      + ` title="${escapeHtml(SNAMES[p] || SLABELS[p])}" data-social="${p}" data-key="${key}" onclick="onSocialBadgeClick(event, this)">${SLABELS[p]}</a>`;
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
  // Столбцы, спрятанные кнопкой «Скрыть пустые», возвращаем, если новый
  // набор данных их заполнил — иначе таблица после нового поиска оставалась
  // без столбцов до нажатия «Показать все».
  if (typeof syncAutoHiddenCols === 'function') syncAutoHiddenCols(filteredRows);
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

// Единый предикат строки: и filterTable(), и живой scheduleLiveRender() обязаны
// применять ОДНИ И ТЕ ЖЕ фильтры — иначе во время прогона смена вкладки города,
// «Только непросмотренные», порог оценки и объединение сетей молча откатывалась
// бы к общему списку.
function _applyRowFilters(source) {
  const q = document.getElementById('tbl-search').value.trim().toLocaleLowerCase('ru-RU');
  const SOCIAL_KEYS = Object.keys(SOCIALS);
  return source.filter(r => {
    // City tab ('' = все города)
    if (activeCity && cityOf(r) !== activeCity) return false;
    // Показ по отметке «Просмотрено» (клик по заголовку колонки ✓):
    // только непросмотренные / только просмотренные / всё.
    if (reviewedFilter === 'unviewed' && isReviewed(r)) return false;
    if (reviewedFilter === 'viewed' && !isReviewed(r)) return false;
    // Search every visible/data field
    const searchable = Object.values(r).some(value =>
      String(value ?? '').toLocaleLowerCase('ru-RU').includes(q)
    );
    if (q && !searchable) return false;
    // Social mode filter (form-level toggle)
    if (socialMode === 'with_socials') {
      if (!SOCIAL_KEYS.some(k => r[k])) return false;
    } else if (socialMode === 'without_socials') {
      if (SOCIAL_KEYS.some(k => r[k])) return false;
    }
    // Required socials (AND filter): must have ALL checked socials
    if (requiredSocials.size > 0 && ![...requiredSocials].every(key => r[key])) return false;
    // Social filter buttons in table — OR logic: row must have at least one
    if (activeSocialFilters.size > 0 && ![...activeSocialFilters].some(key => r[key])) return false;
    // Lead-score threshold (mirror of the server-side stage-2 filter)
    if (minScoreThreshold() && (+r.lead_score || 0) < minScoreThreshold()) return false;
    return true;
  });
}

// Порядок строк: клик по колонке важнее чекбокса «Сначала горячие», иначе —
// порядок файла. Живой рендер вызывает это после перефильтрации, чтобы
// сортировка по заголовку не пропадала во время прогона.
function _orderFilteredRows() {
  if (sortCol === 6) {
    filteredRows.sort((a, b) => {
      const va = +a.lead_score || 0, vb = +b.lead_score || 0;
      return sortAsc ? va - vb : vb - va;
    });
    return;
  }
  // «Рейтинг» (7 — оценка, 8 — число отзывов): числовой порядок, пустые в конце.
  if (sortCol === 7 || sortCol === 8) {
    _sortRatingRows();
    return;
  }
  if (sortCol >= 2) {
    const key = ['', '', 'name', 'category', 'address', 'phone', 'lead_score'][sortCol];
    filteredRows.sort((a, b) => {
      const va = a[key] || '', vb = b[key] || '';
      return sortAsc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
    });
    return;
  }
  const sortCb = document.getElementById('f-sort-score');
  if (sortCb && sortCb.checked && filteredRows.some(r => r.lead_score != null && r.lead_score !== '')) {
    filteredRows = filteredRows.slice().sort((a, b) => (+b.lead_score || 0) - (+a.lead_score || 0));
  }
}

function filterTable() {
  let source = allResults;
  // Optional quality filters (mirror of the server-side ones)
  const collapseChains = document.getElementById('f-collapse-chains');
  if (collapseChains && collapseChains.checked) source = collapseChainsClient(source);
  filteredRows = _applyRowFilters(source);
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

// Ключ колонки → старый числовой индекс сортировки (2..8). Числа — часть
// контракта: те же индексы уходят на сервер (`sort_col`) для «Массового
// обхода», поэтому визуальный порядок столбцов на них не влияет.
// Телефон в контракте остался (сервер умеет), но в шапке не кликается:
// в ячейке несколько номеров, и порядок им не задаётся.
// 7/8 — «Рейтинг»: колонка одна, а смысла два (оценка и число отзывов).
const COL_SORT_INDEX = { rev: null, num: null, name: 2, category: 3, address: 4, phone: null, score: 6, socials: null, rating: 7 };
const SORT_INDEX_COL = { 2: 'name', 3: 'category', 4: 'address', 5: 'phone', 6: 'score', 7: 'rating' };

// Заголовок берём по data-col, а не по позиции в строке: столбцы можно
// переставлять («Столбцы» → перетаскивание), а сортировка должна оставаться
// привязанной к самому столбцу.
function _thByCol(key) {
  return document.querySelector(`#results-table th[data-col="${key}"]`);
}

function sortTableByKey(key) {
  if (key === 'rating') { cycleRatingSort(); return; }
  const idx = COL_SORT_INDEX[key];
  if (!idx) return;                 // «Просмотрено», «#», «Соцсети», «Телефон» не сортируются
  sortTable(idx);
}

// Перерисовка стирает классы заголовков — «#» должен остаться без стрелок.
// Скрытые столбцы (col-hidden) и nosort не трогаем: их ставит не сортировка.
function resetSortHeaders() {
  document.querySelectorAll('#results-table th').forEach(t => {
    t.classList.remove('asc');
    t.classList.remove('desc');
  });
  _clearRatingSortLabel();          // метка «по отзывам» живёт только при сортировке
  const num = _thByCol('num');
  if (num) num.classList.add('nosort');
}

// ── «Рейтинг»: одна колонка — два смысла ─────────────────────────
// Клики идут по кругу: рейтинг ↓ → рейтинг ↑ → отзывы ↓ → отзывы ↑ → снова.
// Пустые значения (нет данных) всегда в конце, как бы ни шла сортировка:
// «нет рейтинга» не должно оказываться первым при сортировке по убыванию.
const RATING_SORT_CYCLE = [
  { col: 7, asc: false }, { col: 7, asc: true },
  { col: 8, asc: false }, { col: 8, asc: true },
];

function _numSortVal(v) {
  if (v === undefined || v === null || String(v).trim() === '') return null;
  const f = parseFloat(String(v).replace(',', '.'));
  return isFinite(f) ? f : null;
}

// Метка в заголовке («рейтинг» / «отзывы») — иначе по одной стрелке
// непонятно, чем именно отсортирована колонка.
let _ratingSortLabel = null;

function _clearRatingSortLabel() {
  if (_ratingSortLabel && typeof _ratingSortLabel.remove === 'function') _ratingSortLabel.remove();
  _ratingSortLabel = null;
}

function _sortRatingRows() {
  const key = sortCol === 8 ? 'reviews_count' : 'rating';
  const present = [], missing = [];
  (filteredRows || []).forEach(r => (_numSortVal(r[key]) === null ? missing : present).push(r));
  present.sort((a, b) => {
    const va = _numSortVal(a[key]), vb = _numSortVal(b[key]);
    return sortAsc ? va - vb : vb - va;
  });
  filteredRows = present.concat(missing);
}

function cycleRatingSort() {
  const i = RATING_SORT_CYCLE.findIndex(s => s.col === sortCol && s.asc === sortAsc);
  const next = RATING_SORT_CYCLE[(i + 1) % RATING_SORT_CYCLE.length];   // -1 → первый
  sortCol = next.col;
  sortAsc = next.asc;
  resetSortHeaders();
  const th = _thByCol('rating');
  if (th) {
    th.classList.add(sortAsc ? 'asc' : 'desc');
    const label = document.createElement('span');
    label.className = 'sort-mode';
    label.textContent = sortCol === 8 ? 'отзывы' : 'рейтинг';
    th.appendChild(label);
    _ratingSortLabel = label;
  }
  _sortRatingRows();
  renderPage();
}

function sortTable(col) {
  if (NOSORT_COLS.has(col)) return;
  if (col === 7 || col === 8) { cycleRatingSort(); return; }   // «Рейтинг» живёт своим циклом
  const th = _thByCol(SORT_INDEX_COL[col]);
  if (!th) return;
  if (sortCol === col) { sortAsc = !sortAsc; }
  else { sortCol = col; sortAsc = true; }
  // Score is a number — compare it as one, not as a string.
  if (col === 6) {
    resetSortHeaders();
    th.classList.add(sortAsc ? 'asc' : 'desc');
    filteredRows.sort((a, b) => {
      const va = +a.lead_score || 0, vb = +b.lead_score || 0;
      return sortAsc ? va - vb : vb - va;
    });
    renderPage();
    return;
  }
  resetSortHeaders();
  th.classList.add(sortAsc ? 'asc' : 'desc');
  // col 0 = ✓ и col 1 = # — не сортируются, col 2 = name, ...
  const keys = ['', '', 'name', 'category', 'address', 'phone', 'lead_score'];
  const key = keys[col];
  filteredRows.sort((a, b) => {
    const va = a[key] || '', vb = b[key] || '';
    return sortAsc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
  });
  renderPage();
}

// Сколько ячеек захватывает полоса города. Берём число столбцов в шапке:
// пользователь может скрывать столбцы, и фиксированная «9» выглядела бы
// неверно. В тестовом DOM шапки нет — там остается запасное значение.
function _tableColspan() {
  try {
    const ths = document.querySelectorAll('#results-table thead th');
    if (ths && ths.length) return ths.length;
  } catch (e) {}
  return 9;
}

// Полоса-заголовок группы города в таблице «Все». Со звёздочкой: город можно
// закрепить сверху прямо из таблицы. Город берём из data-city, а не из
// JS-строки в разметке (кавычки в названии больше не ломают onclick).
function _cityGroupHtml(g) {
  const fav = isFavoriteCity(g.city);
  const hint = fav ? 'Убрать город из избранного' : 'В избранное — город закрепится сверху';
  return `<tr class="city-group${fav ? ' fav' : ''}" data-city="${escapeHtml(g.city)}">`
    + `<td colspan="${_tableColspan()}">`
    + `<span class="fav-star${fav ? ' on' : ''}" role="button" tabindex="0" title="${hint}"`
    + ` aria-label="${hint}" onclick="toggleFavoriteCity(favStarCity(this), event)"`
    + ` onkeydown="onFavStarKey(event, this)">`
    + `${UI_ICONS.star}</span>`
    + `<span class="city-group-name">${escapeHtml(g.city)}</span>`
    + reviewProgressHtml(g.rows.filter(r => isReviewed(r)).length, g.rows.length, 'city-group-done')
    + `<span class="city-group-count">${g.rows.length}</span>`
    + '</td></tr>';
}

// Строки → группы по городу. Порядок городов: избранные сверху, дальше — в
// порядке первого появления в списке; порядок строк ВНУТРИ группы остаётся
// тем же, что задан сортировкой таблицы.
function _groupRowsByCity(rows) {
  const map = new Map();
  (rows || []).forEach(r => {
    const c = cityOf(r);
    if (!map.has(c)) map.set(c, []);
    map.get(c).push(r);
  });
  const fav = [], rest = [];
  map.forEach((list, city) => {
    (isFavoriteCity(city) ? fav : rest).push({ city, rows: list });
  });
  return fav.concat(rest);
}

// Одна строка организации. Вынесено из renderPage: при группировке по городам
// строки идут между полосами городов, а нумерация («#») — сквозная по таблице.
function _resultRowHtml(r, n) {
  // Same key as the backend _review_key(): card URL, else name|city|address.
  const rawReviewUrl = reviewKey(r);
  const reviewUrl = escapeHtml(rawReviewUrl);
  const isRev = isReviewed(r);
  // Ключ, по которому хранится отметка «просмотрено» — тот же, что у checkbox,
  // чтобы метка напротив соцсети и свой checkbox синхронизировались.
  const rowKey = reviewKey(r);
  const rowIsRev = isRev;
  // data-col у каждой ячейки: по нему применяется пользовательский порядок
  // столбцов и скрытие («Столбцы» → перетаскивание) — позиция в разметке
  // больше ничего не значит.
  return `
    <tr class="${rowIsRev ? 'is-reviewed' : ''}">
      <td data-col="rev" style="text-align:center"><input type="checkbox" class="rev-cb"
        aria-label="${escapeHtml((rowIsRev ? 'Снять отметку «просмотрено»: ' : 'Отметить «просмотрено»: ') + (r.name || r.address || 'организация'))}"
        ${rowIsRev ? 'checked' : ''} ${!rawReviewUrl ? 'disabled' : ''}
        data-review-url="${reviewUrl}"
        onchange="toggleReviewed(this.dataset.reviewUrl, this)"></td>
      <td data-col="num">${n}</td>
      <td data-col="name"><a class="tbl-link" href="${escapeHtml(safeUrl(r.yandex_maps_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.name || '—')}</a></td>
      <td data-col="category" class="tbl-cat">${escapeHtml(r.category || '—')}</td>
      <td data-col="address">${escapeHtml(r.address || '—')}</td>
      <td data-col="phone">${phoneHTML(r)}</td>
      <td data-col="score">${scoreHTML(r)}</td>
      <td data-col="socials">${socialsHTML(r, rowKey, rowIsRev)}</td>
      <td data-col="rating">${ratingHTML(r)}</td>
    </tr>`;
}

function renderPage() {
  // Без пагинации: показываем ВСЕ записи. Скроллится по вертикали внутри
  // .tbl-wrap (ширина таблицы = ширина блока), строк не скрывается.
  const total = filteredRows.length;
  const slice = filteredRows;

  document.getElementById('tbl-count').textContent = total
    ? `${total} записей${currentFileNote}${reviewedFilterNote()}` : '';
  const exportWrap = document.getElementById('export-sel-wrap');
  if (exportWrap) exportWrap.style.display = total ? 'flex' : 'none';

  const tbody = document.getElementById('tbl-body');
  if (!total) {
    tbody.innerHTML = '<tr><td colspan="9" class="no-data">Ничего не найдено</td></tr>';   // плейсхолдер: столбцов у него нет

    document.getElementById('pager').style.display = 'none';
    return;
  }

  // В режиме «Все» строки идут группами по городам: сначала полоса с названием
  // города и числом организаций, затем сами организации этого города. Внутри
  // выбранного города группировка не нужна — там один город по определению.
  // Группа из одного города тоже не нужна: заголовок к одной и той же строке
  // ничего не добавляет.
  const groups = activeCity ? null : _groupRowsByCity(slice);
  const grouped = (groups && groups.length > 1) ? groups : null;
  const html = [];
  let rowNo = 0;
  if (grouped) {
    grouped.forEach(g => {
      html.push(_cityGroupHtml(g));
      g.rows.forEach(r => { rowNo += 1; html.push(_resultRowHtml(r, rowNo)); });
    });
  } else {
    slice.forEach(r => { rowNo += 1; html.push(_resultRowHtml(r, rowNo)); });
  }
  tbody.innerHTML = html.join('');

  // Новые строки — в пользовательском порядке столбцов (если он задан).
  applyColOrder();

  // Пагинация больше не нужна — таблицы нет. Счётчик записей остаётся.
  const pager = document.getElementById('pager');
  pager.style.display = 'none';
  document.getElementById('pg-info').textContent = '';
  document.getElementById('pg-prev').disabled = true;
  document.getElementById('pg-next').disabled = true;
}

function changePage(d) { curPage += d; renderPage(); }

// ═══════════════════════════════════════════
//  Reviewed state
