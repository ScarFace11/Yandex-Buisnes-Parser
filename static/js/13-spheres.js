// ═══════════════════════════════════════════
//  Сферы бизнеса: готовые запросы + история по сферам
//
//  Зачем: думать сферой («стоматология») проще, чем словами для поиска, а
//  Яндекс.Карты на «стоматология» и «зубной врач» отдают разные карточки.
//  Каталог приходит с сервера (/spheres), история — оттуда же: она собрана
//  из общей истории поиска, поэтому очистка «Истории» очищает и подписи.
//
//  Список открывается при фокусе в поле «Кого будем искать?» и по кнопке
//  «Сферы». Показываем сразу: когда сферу парсили и по каким городам —
//  чтобы не гонять один и тот же город дважды.
// ═══════════════════════════════════════════

let _spheresCatalog = null;      // [{id, name, icon, queries}] — null, ещё не грузили
let _spheresHistory = {};        // id → {last_ts, cities, runs, results}
let _spheresPromise = null;
let _spheresLoadedAt = 0;

// 5 минут: история меняется только после прогона, чаще запрашивать незачем.
const SPHERES_TTL_MS = 5 * 60 * 1000;

function loadSpheres(force = false) {
  const fresh = _spheresCatalog && (Date.now() - _spheresLoadedAt < SPHERES_TTL_MS);
  if (fresh && !force) return Promise.resolve(_spheresCatalog);
  if (_spheresPromise) return _spheresPromise;
  _spheresPromise = fetch('/spheres')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data || !data.ok) return _spheresCatalog || [];
      _spheresCatalog = Array.isArray(data.spheres) ? data.spheres : [];
      _spheresHistory = {};
      for (const h of (data.history || [])) {
        if (h && h.id) _spheresHistory[h.id] = h;
      }
      _spheresLoadedAt = Date.now();
      return _spheresCatalog;
    })
    .catch(() => _spheresCatalog || [])
    .finally(() => { _spheresPromise = null; });
  return _spheresPromise;
}

// 41 запуск / 2 запуска / 5 запусков — иначе подпись читается как опечатка.
function _runsWord(n) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return 'запуск';
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'запуска';
  return 'запусков';
}

// «🕒 17.10.2026 · Москва, Казань · 3 запуска» либо «ещё не парсили».
function sphereHistoryLine(id) {
  const h = _spheresHistory[id];
  if (!h || !h.last_ts) return 'ещё не парсили';
  const d = new Date(h.last_ts * 1000).toLocaleDateString('ru-RU');
  const cities = (h.cities || []).filter(Boolean);
  const more = (h.cities_total || 0) > cities.length ? ` +${h.cities_total - cities.length}` : '';
  const where = cities.length ? cities.join(', ') + more : 'города не записаны';
  const runs = h.runs > 1 ? ` · ${h.runs} ${_runsWord(h.runs)}` : '';
  return `🕒 ${d} · ${where}${runs}`;
}

function _sphereSortKey(s) {
  const h = _spheresHistory[s.id];
  // Сначала недавно парсенные, затем ни разу не тронутые по алфавиту:
  // так повторный прогон по знакомой сфере виден сразу.
  return h && h.last_ts ? -h.last_ts : Number.MAX_SAFE_INTEGER;
}

function renderSphereDropdown() {
  const dd = document.getElementById('sphere-dropdown');
  if (!dd) return;
  const list = (_spheresCatalog || []).slice().sort((a, b) => {
    if (a.id === b.id) return 0;
    const ka = _sphereSortKey(a), kb = _sphereSortKey(b);
    if (ka !== kb) return ka - kb;
    return a.name.localeCompare(b.name, 'ru');
  });
  if (!list.length) {
    dd.innerHTML = '<div class="sphere-empty">Сферы не загрузились — проверьте соединение с приложением</div>';
    return;
  }
  dd.innerHTML = list.map(s => {
    const hist = sphereHistoryLine(s.id);
    const title = `${s.name}: ${(s.queries || []).join(', ')} · ${hist}`;
    return `<div class="city-option sphere-option" role="option" tabindex="0"
      data-sphere="${escapeHtml(s.id)}" title="${escapeHtml(title)}"
      onclick="applySphere('${s.id}')"
      onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();applySphere('${s.id}');}">
        <div class="city-option-top">
          <span class="city-option-name">${s.icon || '•'} ${escapeHtml(s.name)}</span>
          <span class="city-option-pop">${(s.queries || []).length} ${(s.queries || []).length === 1 ? 'слово' : 'слова'}</span>
        </div>
        <div class="city-option-hist">${escapeHtml(hist)}</div>
      </div>`;
  }).join('');
}

function positionSphereDropdown() {
  const inp = document.getElementById('f-queries');
  const dd = document.getElementById('sphere-dropdown');
  if (!inp || !dd || !dd.classList.contains('open')) return;
  const r = inp.getBoundingClientRect();
  dd.style.position = 'fixed';
  dd.style.top = (r.bottom + 4) + 'px';
  dd.style.left = r.left + 'px';
  dd.style.width = r.width + 'px';
  dd.style.maxHeight = Math.max(160, Math.min(340, window.innerHeight - r.bottom - 16)) + 'px';
  dd.style.zIndex = '9999';
}

function openSphereDropdown() {
  const dd = document.getElementById('sphere-dropdown');
  const btn = document.getElementById('spheres-btn');
  if (!dd) return;
  renderSphereDropdown();
  dd.classList.add('open');
  positionSphereDropdown();
  if (btn) btn.setAttribute('aria-expanded', 'true');
}

function closeSphereDropdown() {
  const dd = document.getElementById('sphere-dropdown');
  const btn = document.getElementById('spheres-btn');
  if (!dd) return;
  dd.classList.remove('open');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function toggleSphereDropdown() {
  const dd = document.getElementById('sphere-dropdown');
  if (!dd) return;
  if (dd.classList.contains('open')) closeSphereDropdown();
  else openSphereDropdown();
}

// Выбор сферы: заменяем запросы её набором. Дальше обычный input-евент —
// счётчик запросов, сводка настройки и кнопка запуска обновляются сами.
function applySphere(id) {
  const sphere = (_spheresCatalog || []).find(s => s.id === id);
  const ta = document.getElementById('f-queries');
  if (!sphere || !ta) return;
  ta.value = (sphere.queries || []).join('\n');
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  closeSphereDropdown();
  ta.focus();
  if (typeof saveSettings === 'function') saveSettings();
}

function initSpheres() {
  const ta = document.getElementById('f-queries');
  if (!ta || ta.dataset.spheresInit) return;
  ta.dataset.spheresInit = '1';

  // Элемент есть в разметке (на него ссылается aria-controls у кнопки),
  // но переносим его в <body> и позиционируем fixed — аккордеон обрезает
  // вложенные списки, как было и с городами.
  const dd = document.getElementById('sphere-dropdown');
  if (!dd) return;
  document.body.appendChild(dd);

  // Грузим не при открытии страницы, а при первом фокусе/клике: лишний
  // запрос на старте не нужен, а список всё равно открывается после ответа.
  ta.addEventListener('focus', () => {
    loadSpheres().then(() => openSphereDropdown());
  });
  ta.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSphereDropdown();
  });

  const btn = document.getElementById('spheres-btn');
  if (btn) {
    btn.addEventListener('mousedown', e => e.preventDefault());  // не уводим фокус
    btn.addEventListener('click', e => {
      e.preventDefault();
      loadSpheres().then(() => toggleSphereDropdown());
    });
  }

  document.addEventListener('mousedown', e => {
    if (!dd.classList.contains('open')) return;
    if (dd.contains(e.target) || e.target === ta || e.target === btn) return;
    closeSphereDropdown();
  });
  window.addEventListener('scroll', positionSphereDropdown, true);
  window.addEventListener('resize', positionSphereDropdown);
}

// Запускаемся после загрузки DOM: модуль подключается последним, а ранняя
// инициализация в 11-app-init.js выполняется раньше этого файла и не видит
// initSpheres (именно из-за этого список не открывался).
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSpheres);
} else {
  initSpheres();
}

// После прогона история изменилась — подписи должны обновиться, но не
// настолько часто, чтобы тянуть /spheres на каждую строку лога.
function refreshSpheresSoon() {
  if (!_spheresCatalog) return;
  _spheresLoadedAt = 0;
  loadSpheres(true).then(() => {
    const dd = document.getElementById('sphere-dropdown');
    if (dd && dd.classList.contains('open')) renderSphereDropdown();
  });
}
