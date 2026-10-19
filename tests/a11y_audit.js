// Сквозной аудит доступности и контраста в НАСТОЯЩЕМ браузере.
//
// Зачем отдельный файл: CSS можно проверить по тексту (tests/test_theme_contrast.py),
// но правила складываются, наследуются и перекрывают друг друга — итоговый цвет
// надписи и её фона виден только на отрисованной странице. Здесь проверяется
// именно то, что увидит человек: вычисленные стили, доступные имена и ARIA-связи.
//
// Контракт: это JS-ВЫРАЖЕНИЕ, которое вычисляется через CDP
// (cdp_client._cdp_eval_page, awaitPromise=true) и возвращает JSON-СТРОКУ:
//
//     {"findings": [{"check": "...", "sel": "...", "detail": "..."}],
//      "stats":    {"scanned": N, "checks": [...]}}
//
// Состояние страницы задаётся снаружи через window.__A11Y_STATE — каждый вызов
// CDP заново делает навигацию, поэтому тема, вкладка и раскрытые аккордеоны
// настраиваются здесь же, внутри замера:
//
//     {theme, tab, expandAccordions, openNotify, fillForm, canary, terms}
//
// Пустой "findings" означает «нарушений нет». Каждая находка несёт короткий
// путь к элементу (тег#id.класс) и текст — чтобы в отчёте было видно, ЧТО
// именно ломает норму, а не «есть проблемы на странице».
(async () => {
  const st = window.__A11Y_STATE || {};
  const findings = [];
  const add = (check, el, detail) => findings.push({ check, sel: path(el), detail });
  const stats = { scanned: 0, checks: [], theme: st.theme || null };

  // ── Подготовка состояния ────────────────────────────────────
  if (st.theme) document.documentElement.setAttribute('data-theme', st.theme);
  // Первый вход: оверлеи соглашения/порога версии закрывают интерфейс —
  // в самом приложении их видно только один раз, и они не часть страницы,
  // которую мы проверяем.
  document.querySelectorAll('#terms-overlay, #terms-declined, #version-gate')
    .forEach(el => { el.style.display = 'none'; el.setAttribute('hidden', ''); });

  if (st.fillForm) {
    // Заполняем форму как пользователь — тогда в кадре настоящие чипы городов,
    // сводка с объёмом и активная кнопка запуска, а не пустая заготовка.
    try {
      const q = document.getElementById('f-queries');
      if (q) { q.value = 'кафе\nстоматология'; q.dispatchEvent(new Event('input', { bubbles: true })); }
      if (typeof addCity === 'function') { addCity('Москва'); addCity('Казань'); }
      if (typeof setGridMode === 'function') setGridMode('manual');
      if (typeof renderSetupSummary === 'function') renderSetupSummary();
    } catch (e) { /* форма может быть ещё не готова — это не Finding */ }
  }

  if (st.expandAccordions) {
    // Раскрываем через настоящий toggleAccordion: так проверяется и открытое
    // состояние раздела, и (в другом проходе) свёрнутое.
    document.querySelectorAll('.acc').forEach(sec => {
      const hdr = sec.querySelector('.acc-hdr');
      if (hdr && !sec.classList.contains('open') && typeof toggleAccordion === 'function') {
        toggleAccordion(hdr);
      }
    });
  }

  if (st.openNotify && typeof openNotifyPopover === 'function') openNotifyPopover();
  if (st.openApiKeys && typeof toggleApiKeys === 'function') toggleApiKeys();

  // Пустая таблица проверяет только заготовку. Настоящие строки — с бейджами
  // оценки, соцсетями и итоговой строкой — это тоже часть интерфейса, поэтому
  // в части прогонов кладём в таблицу образцы записей и считаем их статистику.
  if (st.seedRows && typeof renderTable === 'function') {
    const rows = [
      { name: 'Кафе «Ромашка»', category: 'Кафе, Кофейня', city: 'Москва', address: 'ул. Ленина, 1',
        phone: '+7 999 123-45-67', site: 'https://romashka.ru', vk: 'https://vk.com/romashka',
        telegram: '', instagram: '', whatsapp: '', rating: 4.6, reviews_count: 128,
        lead_score: 72, query: 'кафе', yandex_maps_url: 'https://yandex.ru/maps/org/1',
        without_site: false, reviewed: false, note: '' },
      { name: 'Стоматология «Улыбка»', category: 'Стоматология', city: 'Казань',
        address: 'ул. Баумана, 12', phone: '', site: '', vk: '', telegram: 'https://t.me/smile',
        instagram: '', whatsapp: '', rating: 4.1, reviews_count: 8, lead_score: 31,
        query: 'стоматология', yandex_maps_url: 'https://yandex.ru/maps/org/2',
        without_site: true, reviewed: true, note: 'перезвонить' },
      { name: 'Салон «Лилия»', category: '', city: 'Москва', address: '', phone: '+7 495 000-11-22',
        site: '', vk: '', telegram: '', instagram: '', whatsapp: '', rating: null,
        reviews_count: 0, lead_score: null, query: 'салон', yandex_maps_url: '',
        without_site: true, reviewed: false, note: '' },
    ];
    try { renderTable(rows); window.__A11Y_ROWS = rows; } catch (e) { /* нет данных — не находка */ }
  }
  if (st.seedStats && typeof renderStats === 'function') {
    try { renderStats(window.__A11Y_ROWS || [], 125, 0); } catch (e) { /* см. выше */ }
  }
  if (st.seedLog && typeof appendLog === 'function') {
    try {
      appendLog('city', '🏙 Москва');
      appendLog('info', 'Найдено 42 организации');
      appendLog('ok', 'Сохранено: results_moscow.xlsx');
      appendLog('warn', '⚠ Израсходовано 7 из 10 запросов');
      appendLog('error', 'Не удалось загрузить страницу — повтор');
      appendLog('tech', 'cdp_client: initialized with 4 tabs');
    } catch (e) { /* см. выше */ }
  }

  // Тост живёт 3.5 с и в замер может не попасть: показываем его сами.
  // Это единственное место, где белый текст лежит на семантическом фоне
  // (--grn-btn/--red-btn) — проверять его надо обязательно.
  if (st.toasts && typeof showToast === 'function') {
    try {
      showToast('Настройки сохранены', 'success');
      showToast('Не удалось сохранить файл', 'error');
    } catch (e) { /* см. выше */ }
  }

  if (st.tab && typeof showTab === 'function') showTab(st.tab);

  if (st.canary) {
    // Контрольный образец: белая надпись на светлом фоне и кнопка без имени.
    // Если аудит их не находит, значит он ничего не проверяет.
    const c = document.createElement('div');
    c.id = 'a11y-canary';
    c.style.cssText = 'color:#9BAEC4;background:#ffffff;font-size:13px;padding:4px';
    c.textContent = 'canary';
    const b = document.createElement('button');
    b.id = 'a11y-canary-btn';
    b.type = 'button';
    b.textContent = '';
    document.body.append(c, b);
  }

  // Даём кадру осесть: переход темы (.25s), анимация панели и раскрытие
  // аккордеона (.26s) — иначе замер попадёт в середину отрисовки.
  await new Promise(r => setTimeout(r, st.settleMs || 400));
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

  // ── Цветовые утилиты ────────────────────────────────────────
  const parseColor = css => {
    const m = String(css || '').match(/[\d.]+/g);
    if (!m) return null;
    const v = m.map(Number);
    return { r: v[0], g: v[1], b: v[2], a: v[3] === undefined ? 1 : v[3] };
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  const lum = c => {
    const ch = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * ch(c.r) + 0.7152 * ch(c.g) + 0.0722 * ch(c.b);
  };
  const contrast = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  // Фон элемента: идём вверх по родителям и накладываем полупрозрачные слои
  // (у --acc-soft, --row-hover, статус-бейджей и т. п. фон именно такой).
  // Возможные ФОНЫ элемента. Их может быть несколько: градиентная кнопка
  // светлеет к другому краю, и текст обязан читаться на каждом участке, а
  // полупрозрачные слои (--acc-soft, --row-hover, бейджи) накладываются на
  // фон родителя — без этого «вычисленный фон» был бы не тем, что видно.
  const bgsOf = el => {
    let node = el, stack = [];
    while (node) {
      const cs = getComputedStyle(node);
      const img = cs.backgroundImage || '';
      let stops = [];
      if (img.indexOf('gradient') !== -1) {
        stops = (img.match(/rgba?\([^)]+\)/g) || []).map(parseColor).filter(Boolean);
      }
      const c = parseColor(cs.backgroundColor);
      if (stops.length) {
        // Градиент перекрывает всё, что за ним, — дальше вверх не идём.
        return stops.map(s => {
          let base = s.a >= 1 ? s : over(s, { r: 255, g: 255, b: 255, a: 1 });
          while (stack.length) base = over(stack.pop(), base);
          return base;
        });
      }
      if (c && c.a > 0) {
        if (c.a >= 1) {
          let base = c;
          while (stack.length) base = over(stack.pop(), base);
          return [base];
        }
        stack.push(c);
      }
      node = node.parentElement;
    }
    let base = parseColor(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
    while (stack.length) base = over(stack.pop(), base);
    return [base];
  };

  const path = el => {
    if (!el || !el.tagName) return '?';
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean);
    if (cls.length) s += '.' + cls.slice(0, 2).join('.');
    return s;
  };
  const textOf = el => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (Number(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  // Элементы внутри aria-hidden и в служебном спрайте не участвуют в проверках.
  const hiddenFromAT = el => !!el.closest('[aria-hidden="true"], #icon-sprite');
  const isDecorative = el => el.closest('#icon-sprite, svg[aria-hidden="true"]') !== null;

  // ── 1. Контраст текста ──────────────────────────────────────
  // Норма WCAG AA: 4.5:1 для обычного текста, 3:1 для крупного
  // (≥24px или ≥18.66px при жирном начертании).
  const contrastChecked = [];
  document.querySelectorAll('body *').forEach(el => {
    if (!visible(el) || isDecorative(el)) return;
    // Только элементы со СВОИМ текстом: у контейнера цвет может быть «на будущее».
    const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) return;
    const cs = getComputedStyle(el);
    const fg = parseColor(cs.color);
    if (!fg || fg.a === 0) return;
    const size = parseFloat(cs.fontSize) || 0;
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3.0 : 4.5;
    // По каждому возможному фону считаем свой контраст и берём худший: на
    // градиенте текст должен читаться на всех его участках.
    let worst = null, worstBg = null;
    bgsOf(el).forEach(bg => {
      const fgOn = fg.a < 1 ? over(fg, bg) : fg;
      const got = contrast(fgOn, bg);
      if (worst === null || got < worst) { worst = got; worstBg = bg; }
    });
    contrastChecked.push(1);
    if (worst < need) {
      add('contrast', el, `${worst.toFixed(2)}:1 < ${need}:1 `
        + `(текст ${cs.color} на rgb(${Math.round(worstBg.r)},${Math.round(worstBg.g)},${Math.round(worstBg.b)}), `
        + `${size}px/${weight}) «${textOf(el).slice(0, 30)}»`);
    }
  });
  stats.checks.push(`contrast:${contrastChecked.length}`);

  // ── 2. Доступные имена интерактивных элементов ──────────────
  // Кнопка без текста и без aria-label не читается скринридером и не находится
  // голосовым вводом — это самая частая потеря в плотном интерфейсе.
  const interactive = el => el.matches(
    'button, a[href], select, textarea, input:not([type="hidden"]), ' +
    '[role="button"], [role="tab"], [role="switch"], [role="checkbox"], [role="link"]');
  const nameOf = el => {
    const labelledby = el.getAttribute('aria-labelledby');
    if (labelledby) {
      const txt = labelledby.split(/\s+/)
        .map(id => { const t = document.getElementById(id); return t ? textOf(t) : ''; })
        .join(' ').trim();
      if (txt) return txt;
    }
    const aria = (el.getAttribute('aria-label') || '').trim();
    if (aria) return aria;
    let txt = '';
    el.querySelectorAll('svg, use').forEach(n => { /* иконки имя не дают */ });
    const clone = el.cloneNode(true);
    clone.querySelectorAll('svg, [aria-hidden="true"]').forEach(n => n.remove());
    txt = textOf(clone);
    if (txt) return txt;
    if (el.tagName === 'INPUT') {
      if (['submit', 'button', 'reset'].includes((el.type || '').toLowerCase())) {
        return (el.value || '').trim() || 'submit';
      }
      const lab = el.labels && el.labels.length ? textOf(el.labels[0]) : '';
      if (lab) return lab;
    }
    return (el.getAttribute('title') || '').trim();
  };
  const interactiveChecked = [];
  document.querySelectorAll('body *').forEach(el => {
    if (!interactive(el) || hiddenFromAT(el) || !visible(el)) return;
    // Скрытые визуально, но оставленные для скринридера поля (radio внутри
    // плиток-переключателей) имеют подпись на обёртке — их name считаем по label.
    interactiveChecked.push(1);
    const name = nameOf(el);
    if (!name) {
      add('name', el, `интерактивный элемент без доступного имени «${textOf(el).slice(0, 30)}»`);
    }
  });
  stats.checks.push(`names:${interactiveChecked.length}`);

  // ── 3. Подписи у полей ввода ────────────────────────────────
  const fieldsChecked = [];
  document.querySelectorAll('input:not([type="hidden"]), select, textarea').forEach(el => {
    if (!visible(el) || hiddenFromAT(el) || el.disabled) return;
    if (['radio', 'checkbox'].includes((el.type || '').toLowerCase())) {
      // У радио/чекбоксов подпись — текст обёртки <label>.
      if (el.closest('label')) { fieldsChecked.push(1); return; }
    }
    fieldsChecked.push(1);
    const hasLabel = (el.labels && el.labels.length > 0)
      || el.getAttribute('aria-label')
      || el.getAttribute('aria-labelledby')
      || el.getAttribute('title');
    if (!hasLabel) add('label', el, 'поле без подписи (label/aria-label)');
  });
  stats.checks.push(`labels:${fieldsChecked.length}`);

  // ── 4. ARIA-связи и состояния ───────────────────────────────
  const idRefs = ['aria-labelledby', 'aria-describedby', 'aria-controls'];
  document.querySelectorAll('body *').forEach(el => {
    if (!visible(el)) return;
    idRefs.forEach(attr => {
      const raw = el.getAttribute(attr);
      if (!raw) return;
      raw.split(/\s+/).filter(Boolean).forEach(id => {
        if (!document.getElementById(id)) {
          add('aria', el, `${attr}="${id}" — такого элемента нет в документе`);
        }
      });
    });
    if (el.hasAttribute('aria-expanded')) {
      const v = el.getAttribute('aria-expanded');
      if (v !== 'true' && v !== 'false') add('aria', el, `aria-expanded="${v}" — ожидалось true/false`);
    }
    if (el.getAttribute('role') === 'switch') {
      const v = el.getAttribute('aria-checked');
      if (v !== 'true' && v !== 'false') add('aria', el, `роль switch без aria-checked`);
    }
  });

  document.querySelectorAll('[role="tablist"]').forEach(list => {
    const tabs = list.querySelectorAll('[role="tab"]');
    const selected = list.querySelectorAll('[role="tab"][aria-selected="true"]');
    if (tabs.length && selected.length !== 1) {
      add('aria', list, `в полосе вкладок выбрано ${selected.length} вкладок (должна быть одна)`);
    }
  });
  document.querySelectorAll('[role="tab"]').forEach(t => {
    if (!t.hasAttribute('aria-selected')) add('aria', t, 'вкладка без aria-selected');
    const controls = t.getAttribute('aria-controls');
    if (controls && !document.getElementById(controls)) {
      add('aria', t, `aria-controls="${controls}" — панели нет`);
    }
  });

  // ── 5. Страница не должна скроллиться вбок ──────────────────
  const de = document.documentElement;
  if (de.scrollWidth > window.innerWidth + 1) {
    findings.push({
      check: 'overflow',
      sel: 'html',
      detail: `страница шире окна: ${de.scrollWidth} > ${window.innerWidth} — горизонтальный скролл`,
    });
  }

  // ── 6. Клавиатура ───────────────────────────────────────────
  // Порядок фокуса, ловушку Tab и возврат фокуса проверяет тест настоящими
  // нажатиями (tests/test_a11y_keyboard.py) — синтетическое событие фокус не
  // двигает. Здесь — то, что видно из самой страницы. Запускается только при
  // st.keyboard: модальность ввода «клавиатура» создаёт настоящий Tab, без
  // него :focus-visible у кнопок не срабатывает и проверка рамки врала бы.
  if (st.keyboard) {
    // Контрольный образец: элемент, у которого фокус НИКАК не отмечен
    // (inline !important перебивает общее правило :focus-visible). Без него
    // «рамки в порядке» ничего не значит: проверка может просто никого не
    // находить.
    if (st.keyboardCanary) {
      const c = document.createElement('span');
      c.id = 'a11y-canary-focus';
      c.tabIndex = 0;
      c.textContent = 'canary';
      c.style.setProperty('outline', 'none', 'important');
      c.style.setProperty('box-shadow', 'none', 'important');
      c.style.setProperty('background', 'none', 'important');
      c.style.setProperty('color', 'inherit', 'important');
      c.style.setProperty('border', 'none', 'important');
      document.body.appendChild(c);
    }
    const focusStop = el => el.matches(
      'button, a[href], input:not([type="hidden"]), select, textarea, summary, iframe, [tabindex]');
    const tabbable = el => focusStop(el) && !el.disabled
      && el.getAttribute('tabindex') !== '-1'
      && !el.closest('[inert]') && !el.closest('[aria-hidden="true"]');

    // 6a. Фокусируемое внутри aria-hidden: клавиатура уходит туда, где для
    // скринридера ничего нет — Tab «исчезает» из интерфейса.
    const ariaHiddenStops = document.querySelectorAll('[aria-hidden="true"]');
    ariaHiddenStops.forEach(box => {
      if (box.id === 'icon-sprite') return;          // спрайт иконок — не интерфейс
      box.querySelectorAll('*').forEach(el => {
        if (!visible(el) || el.closest('#icon-sprite')) return;
        if (tabbable(el)) {
          add('keyboard', el, 'фокусируемый элемент внутри aria-hidden="true"');
        }
      });
    });

    // 6b. Положительный tabindex: порядок обхода перестаёт совпадать с
    // видимым порядком — самые «дорогие» ошибки клавиатуры в формах.
    document.querySelectorAll('[tabindex]').forEach(el => {
      const v = parseInt(el.getAttribute('tabindex'), 10);
      if (v > 0) add('keyboard', el, `tabindex="${v}">0 — порядок обхода станет непредсказуемым`);
    });

    // 6c. Роль обещает кликабельность, а в обход она не попадает.
    document.querySelectorAll('[role="button"], [role="link"], [role="option"], [role="checkbox"], [role="switch"], [role="tab"]').forEach(el => {
      const role = el.getAttribute('role');
      if (hiddenFromAT(el) || !visible(el) || tabbable(el)) return;
      // Явный tabindex="-1" — это УПРАВЛЯЕМЫЙ порядок (перемещаемый фокус
      // в полосе вкладок, списке, меню): так и должно быть, а достижимость
      // обеспечивает сам виджет. Смотрим только тех, у кого tabindex нет.
      if (el.hasAttribute('tabindex')) return;
      if (el.querySelector('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])')) return;
      add('keyboard', el, `role="${role}" без tabindex — с клавиатуры недостижим`);
    });

    // 6d. Видимая рамка фокуса (WCAG 2.4.7). Сравнивается стиль БЕЗ фокуса со
    // стилем В фокусе — по элементу и его родителям (кольцо часто рисует
    // обёртка через :focus-within/:has()).
    const ringSig = node => {
      const cs = getComputedStyle(node);
      return [cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow,
              cs.borderTopColor, cs.borderTopWidth, cs.borderLeftColor,
              cs.backgroundColor, cs.color, cs.opacity, cs.textDecorationLine].join('|');
    };
    const chainSig = el => {
      const parts = [];
      let node = el;
      for (let i = 0; node && node !== document.body && i < 4; i++, node = node.parentElement) {
        parts.push(ringSig(node));
      }
      return parts.join('||');
    };
    const shown = document.activeElement;
    if (shown && shown.blur) shown.blur();
    let ringChecked = 0;
    document.querySelectorAll('body *').forEach(el => {
      if (!tabbable(el) || hiddenFromAT(el) || !visible(el)) return;
      // Снимаем фокус с предыдущего элемента: иначе его кольцо попадёт в
      // базовый стиль общего родителя, и разница не найдётся.
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      const before = chainSig(el);
      let focused = false;
      try { el.focus({ preventScroll: true }); focused = document.activeElement === el; }
      catch (e) { focused = false; }
      if (!focused) return;                       // сюда обход всё равно не придёт
      const after = chainSig(el);
      ringChecked++;
      if (before === after) {
        add('focus', el, 'фокус не видно: ни рамка, ни фон, ни кольцо не меняются');
      }
    });
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    stats.checks.push(`focus-ring:${ringChecked}`);
  }

  stats.scanned = document.querySelectorAll('body *').length;
  return JSON.stringify({ findings, stats });
})()
