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

  // Задержка анимации grows по колонкам (--d): столбики вырастают волной слева
  // направо. Переменная наследуется в .dyn-bar/.dyn-vlab.
  const cols = series.map((d, i) => {
    const {wd, dm} = _dailyDayLabel(d.date);
    const pct = d.found ? Math.round(d.reviewed / d.found * 100) : 0;
    return `<div class="dyn-col${d.date === todayIso ? ' is-today' : ''}" style="--d:${Math.min(i * 22, 660)}ms"`
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
// helpers. Отличия — в подписях (колонка «14» вместо «ср 30.09»). Рисуем
// все 24 часа: окно «от первого до последнего часа с данными» обрезало
// утро/вечер и скрывало, что в другое время поиск не шёл. «Просмотрено»
// раскладывается по часам сервером (по времени отметки в _reviewed.json).
function dailyHoursChartHTML(payload) {
  const hours = payload.hours || [];
  const totals = payload.totals || {found: 0, reviewed: 0};
  const shown = hours.length ? hours : [];

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

  const cols = shown.map((h, i) => {
    const lbl = String(h.hour).padStart(2, '0');
    const rev = h.reviewed || 0;
    return `<div class="dyn-col" style="--d:${Math.min(i * 22, 660)}ms" data-wd="Час" data-dm="${lbl}:00"`
      + ` data-found="${h.found}" data-review="${rev}" data-files="${h.files || 0}" data-pct="0">`
      + `<div class="dyn-stack">${series_('dyn-found', h.found)}${series_('dyn-review', rev)}</div>`
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
  if (s.excel    != null) { document.getElementById('f-excel').checked = s.excel;   document.getElementById('f-excel').closest('.chk').classList.toggle('on', s.excel); }
  if (s.json     != null) { document.getElementById('f-json').checked  = s.json;    document.getElementById('f-json').closest('.chk').classList.toggle('on', s.json); }
  if (s.csv      != null) { document.getElementById('f-csv').checked   = s.csv;     document.getElementById('f-csv').closest('.chk').classList.toggle('on', s.csv); }
  if (s.map      != null) { document.getElementById('f-map').checked   = s.map;     document.getElementById('f-map').closest('.chk').classList.toggle('on', s.map); }
  if (s.pages    != null) document.getElementById('f-pages').value    = s.pages;
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
