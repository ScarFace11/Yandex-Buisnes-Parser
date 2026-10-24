# -*- coding: utf-8 -*-
"""Клавиатура: порядок обхода, видимая рамка фокуса, ловушка Tab в модалках.

Почему настоящие нажатия, а не события из страницы: синтетический
KeyboardEvent фокус не двигает, поэтому порядок обхода, ловушку Tab и возврат
фокуса иначе не проверить. Тесты открывают страницу в браузере пользователя
(tests/_browser.py, через CDP) и жмут Tab/Escape по-настоящему — браузер сам
переводит фокус, как у живого человека.

Что проверяется:

* обход Tab: начинается со ссылки «Перейти к содержимому», проходит по
  видимым и не скрытым от скринридера элементам, доходит до конца (значит,
  фокус нигде не заперт) и не зацикливается;
* рамка фокуса: у каждого элемента, до которого можно дойти с клавиатуры,
  при фокусе меняется хотя бы что-то видимое (WCAG 2.4.7) — проверяет
  tests/a11y_audit.js в режиме keyboard, вместе со статикой (фокусируемое
  внутри aria-hidden, положительный tabindex, role без tabindex);
* модальные окна: имя диалога (role=dialog, aria-modal, aria-labelledby),
  фокус переходит внутрь, Tab и Shift+Tab НЕ выходят за пределы окна,
  Escape закрывает, а фокус возвращается на элемент, который окно открыл;
  имя окна обязано пережить подмену содержимого — у окон со списком (логи)
  тело приезжает запросом и заменяется целиком.

У каждой проверки есть контрольный образец: у канарейки фокус отключён
inline-стилем, и аудит обязан её найти — иначе «нарушений нет» ничего не
доказывает.

Run with: python -m pytest tests/test_a11y_keyboard.py -v
"""
import json
import time
from pathlib import Path

import pytest

from tests._browser import new_tab

ROOT = Path(__file__).resolve().parent.parent
AUDIT_JS = (ROOT / "tests" / "a11y_audit.js").read_text(encoding="utf-8")

# Оверлеи первого входа (соглашение, порог версии) закрывают интерфейс и
# проверяются отдельными случаями ниже — здесь их прячем, чтобы обход Tab
# шёл по самому интерфейсу.
HIDE_OVERLAYS = """
document.querySelectorAll('#terms-overlay, #terms-declined, #version-gate')
  .forEach(el => { el.hidden = true; });
"""

# Форма заполнена как у готового к запуску пользователя: пустая форма держит
# главную кнопку выключенной (disabled), а выключенные кнопки в обход Tab не
# попадают — тогда проверять «достижима ли кнопка запуска» бессмысленно.
FILL_FORM = """
(() => {
  const q = document.getElementById('f-queries');
  if (q) { q.value = 'кафе\\nстоматология'; q.dispatchEvent(new Event('input', {bubbles: true})); }
  if (typeof addCity === 'function') { addCity('Москва'); addCity('Казань'); }
  if (typeof updateRunBtnState === 'function') updateRunBtnState();
})()
"""

# Один шаг обхода: что попало в фокус. Каждому элементу ставится метка, иначе
# одинаковые по разметке элементы (звёздочки городов, кнопки строк) не
# различить и «зациклился» от «прошёл два похожих» не отделить.
WALK_STEP = """
(() => {
  const el = document.activeElement;
  if (!el || el === document.body) return JSON.stringify({ end: true });
  let mark = el.getAttribute('data-a11y-walk');
  if (!mark) {
    window.__a11yWalkSeq = (window.__a11yWalkSeq || 0) + 1;
    mark = 'w' + window.__a11yWalkSeq;
    el.setAttribute('data-a11y-walk', mark);
  }
  const cs = getComputedStyle(el);
  const cls = (typeof el.className === 'string' && el.className.trim())
    ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
  return JSON.stringify({
    mark,
    path: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls,
    text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
    visible: cs.display !== 'none' && cs.visibility !== 'hidden'
             && el.getClientRects().length > 0,
    ariaHidden: !!el.closest('[aria-hidden="true"]'),
    interactive: el.matches('button, a[href], input, select, textarea, summary, [tabindex]'),
  });
})()
"""

# Почему обход Tab мог не начаться: видно из самой страницы.
WALK_DIAG = """
(() => {
  const el = document.activeElement;
  return JSON.stringify({
    active: el ? el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') : null,
    hasFocus: document.hasFocus(),
    visibility: document.visibilityState,
    viewport: [window.innerWidth, window.innerHeight],
    bodyStart: !!el && el === document.body,
  });
})()
"""

# Состояние модального окна: роль, имя, живой ли фокус внутри.
MODAL_REPORT = """
(sel => {
  const box = document.querySelector(sel);
  if (!box) return JSON.stringify({ open: false });
  const ref = box.getAttribute('aria-labelledby');
  const named = ref ? (document.getElementById(ref) || {}).textContent
                    : box.getAttribute('aria-label');
  return JSON.stringify({
    open: true,
    role: box.getAttribute('role'),
    ariaModal: box.getAttribute('aria-modal'),
    name: (named || '').replace(/\\s+/g, ' ').trim(),
    focusInside: box.contains(document.activeElement),
    active: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
  });
})(%s)
"""

# Случаи: имя, чем открыть, чем проверить что окно на экране.
# Селектор окна — с :not([hidden]): в разметке страницы есть постоянные
# оверлеи (соглашение, порог версии), и без этого поиск нашёл бы первым именно
# их — скрытыми.
DYNAMIC_BOX = ".ui-modal-overlay:not([hidden]) .ui-modal"

MODALS = (
    dict(name="confirm", js="uiConfirm('Проверка клавиатуры', 'Проверка', 'Понятно', false)",
         box=DYNAMIC_BOX),
    dict(name="preset-save", js="openPresetModal()", box=".preset-modal"),
    # Список слов должен быть непустым: пустой список окно не открывает,
    # а показывает подсказку — это его работа, а не наша проверка.
    dict(name="blacklist-list",
         js="addBlacklistWords('тест'); openBlacklistSaveModal()", box=DYNAMIC_BOX),
    dict(name="diagnostics", js="showDiagnostics()", box=".diag-modal"),
    dict(name="links",
         js="showLinksModal([{url: 'https://vk.com/test', key: 'k1'}], 'ВКонтакте')",
         box=".links-modal"),
    dict(name="copy-text", js="showCopyTextModal('текст для отправки')", box=".links-modal"),
    dict(name="choose",
         js="uiChoose('Что делать?', 'Выбор', [{value: 'a', label: 'Первый'}], {})",
         box=DYNAMIC_BOX),
    # Шаблоны догружаются запросом: открываем из .then, иначе окно ждёт данных.
    # Окна шаблонов лежат внутри своей вкладки: без неё они не отрисовываются
    # и rects = 0 — открывать их надо на живой вкладке, а не из другой.
    dict(name="template-edit", pre="showTab('templates')",
         js="loadTemplates().then(() => openTemplateModal(null))",
         box="#tpl-modal:not([hidden]) .tpl-modal"),
    dict(name="template-vars", pre="showTab('templates')",
         js="loadTemplates().then(() => openVarModal(null))",
         box="#tpl-var-modal:not([hidden]) .tpl-modal"),
    dict(name="logs", js="showLogsModal()", box=".logs-modal"),
    dict(name="terms", js="showOverlay('terms-overlay')",
         box="#terms-overlay:not([hidden]) .ui-modal"),
    # Экран «версия ниже минимальной» намеренно НЕ закрывается: на такой сборке
    # работать нельзя, поэтому у него нет кнопки отмены (Escape не проверяем).
    dict(name="version-gate", js="showOverlay('version-gate')",
         box="#version-gate:not([hidden]) .ui-modal", escape=False),
)


def open_page(tab, url: str, fill_form: bool = True) -> None:
    # Размер окна здесь НЕ подменяем: страница должна оставаться той же,
    # что у человека, и клавиатура тоже. Фиксированное окно нужно аудиту
    # раскладки (tests/test_a11y_browser.py), а здесь на первом месте —
    # настоящее поведение браузера при нажатиях.
    tab.open(url, wait_expr="document.getElementById('setup-summary')")
    tab.evaluate(HIDE_OVERLAYS)
    if fill_form:
        tab.evaluate(FILL_FORM)


def wait_for(tab, selector: str, timeout: float = 10.0) -> bool:
    """Дождаться, пока элемент появится и станет видимым."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tab.evaluate(
            f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
            " return !!el && el.getClientRects().length > 0; })()"
        ):
            return True
        time.sleep(0.1)
    return False


def wait_focus_inside(tab, box: str, timeout: float = 5.0) -> bool:
    """Дождаться, пока фокус окажется внутри окна.

    Содержимое части окон подъезжает запросом (список логов): в момент
    открытия внутри ещё нечего фокусировать, и проверка сразу после открытия
    была бы гонкой, а не проверкой.
    """
    inside = (f"(() => {{ const box = document.querySelector({json.dumps(box)});"
              " return !!box && box.contains(document.activeElement); })()")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tab.evaluate(inside):
            return True
        time.sleep(0.1)
    return False


def walk(tab, max_presses: int = 3000):
    """Пройти вперёд по Tab и собрать все остановки фокуса.

    Возвращает (stops, ended, cycled):
      * ended — фокус дошёл до конца документа (значит, нигде не заперт);
      * cycled — тот же элемент встретился второй раз: фокус ходит по кругу.

    Число нажатий не задано константой: страница догружает списки на ходу
    (история файлов, сферы, пресеты), и сколько их — зависит от данных
    пользователя. Верхняя граница одна на всех: на случай, если фокус заперт
    и конца не будет вовсе.
    """
    stops = []
    seen = set()
    for _ in range(max_presses):
        # tab_step, а не press: на macOS системный Tab не переводит фокус на
        # ссылки и кнопки (так устроена настройка ОС), шаг делается командой
        # браузера — см. tests/_browser.py.
        tab.tab_step()
        step = json.loads(tab.evaluate(WALK_STEP))
        if step.get("end"):
            return stops, True, False
        mark = step.get("mark")
        if mark in seen:
            return stops, False, True
        seen.add(mark)
        stops.append(step)
    return stops, False, False


# Сколько на странице элементов, в которые вообще можно уйти с клавиатуры.
# Их число зависит от данных пользователя: в истории файлов каждая строка —
# своя звёздочка, и их бывает и полторы сотни. Поэтому лимит обхода считаем
# от этой величины, а не от константы: иначе проверка зависит от того, сколько
# файлов лежит в output/ на этой машине.
FOCUSABLE_COUNT = """
(() => {
  const sel = 'a[href], button, input, select, textarea, summary, [tabindex]';
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (!el.getClientRects().length) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    n++;
  }
  return n;
})()
"""


def focusable_count(tab) -> int:
    return int(tab.evaluate(FOCUSABLE_COUNT))


def wait_settled(tab, timeout: float = 15.0, stable: int = 3, interval: float = 0.3) -> int:
    """Дождаться, пока страница перестанет меняться, и вернуть число элементов.

    Списки (история файлов, сферы, пресеты) приезжают запросами, и обход Tab,
    начатый раньше, мерил бы разные страницы: то упирался в лимит нажатий,
    то проходил мимо подгрузившегося списка. Ждём, пока число фокусируемых
    элементов перестанет меняться.
    """
    deadline = time.monotonic() + timeout
    last = -1
    same = 0
    while time.monotonic() < deadline:
        count = focusable_count(tab)
        if count == last:
            same += 1
            if same >= stable:
                return count
        else:
            same = 0
            last = count
        time.sleep(interval)
    return focusable_count(tab)


def format_stops(stops) -> str:
    return "\n".join(f"  {s['mark']} {s['path']} «{s['text']}»" for s in stops[:40])


# ── 1. Обход Tab ────────────────────────────────────────────────
def test_tab_walk_starts_at_skip_link_and_finishes(browser_cdp, live_app_url):
    """Обход начинается со ссылки «Перейти к содержимому» и не застревает.

    Дошли до конца документа — значит, фокуса не заперли ни в модалке, ни в
    блоке интерфейса; вернулись на первом же элементе — значит, где-то ловушка.
    """
    tab = new_tab(browser_cdp)
    try:
        open_page(tab, live_app_url)
        # Страница должна догрузить списки ДО обхода: иначе обход меряет
        # промежуточное состояние (см. wait_settled).
        wait_settled(tab)
        # Оверлей (соглашение, порог версии) мог приехать вместе со списками —
        # прячем его ещё раз, иначе он замкнёт фокус в себе.
        tab.evaluate(HIDE_OVERLAYS)
        stops, ended, cycled = walk(tab)
        if not stops:
            # «Фокус не двигается» — это либо настройка браузера/системы, либо
            # страница не на переднем плане. Без этих данных диагноз не поставить.
            diag = json.loads(tab.evaluate(WALK_DIAG))
            pytest.fail(f"Tab не перевёл фокус ни на один элемент: {diag}")
        assert stops[0]["path"].startswith("a.skip-link"), (
            f"первым по Tab должно быть «Перейти к содержимому», а не {stops[0]['path']}"
        )
        assert not cycled, (
            "фокус ходит по кругу — обход вернулся к уже пройденному элементу:\n"
            + format_stops(stops[-20:])
        )
        assert ended, (
            "обход Tab не дошёл до конца документа — фокус заперт в интерфейсе:\n"
            + format_stops(stops[-40:])
        )

        invisible = [s for s in stops if not s["visible"]]
        assert not invisible, "Tab уходит на невидимые элементы:\n" + format_stops(invisible)
        unknown = [s for s in stops if not s["interactive"]]
        assert not unknown, "Tab уходит на неинтерактивные элементы:\n" + format_stops(unknown)
        hidden = [s for s in stops if s["ariaHidden"]]
        assert not hidden, (
            "Tab заходит в элементы, скрытые от скринридера (aria-hidden):\n"
            + format_stops(hidden)
        )

        marks = [s["mark"] for s in stops]
        repeats = sorted({m for m in marks if marks.count(m) > 1})
        assert not repeats, (
            "один и тот же элемент обходится дважды — фокус ходит по кругу:\n"
            + format_stops([s for s in stops if s["mark"] in repeats])
        )

        assert any("btn-run" in s["path"] for s in stops), "главная кнопка не достижима по Tab"
        assert len(stops) >= 25, f"подозрительное число остановок: {len(stops)}"
    finally:
        tab.close()


def test_modal_keeps_its_name_when_content_arrives_later(browser_cdp, live_app_url):
    """С окном логов: имя диалога обязано пережить подмену содержимого.

    Список логов приезжает запросом и заменяет внутренности окна целиком.
    Пока заголовок лежал внутри заменяемого тела, вместе с ним исчезал и
    aria-labelledby — открытый диалог оставался без имени, а скринридер
    читал просто «диалог». Заметно это было через раз: тест успевал замерить
    и до, и после подмены.
    """
    tab = new_tab(browser_cdp)
    try:
        open_page(tab, live_app_url)
        tab.evaluate("document.getElementById('btn-run').focus(); showLogsModal(); void 0")
        assert wait_for(tab, ".logs-modal"), "окно логов не открылось"
        # Кнопка «Закрыть» появляется только с загруженным телом: по ней и
        # видно, что подмена уже произошла.
        assert wait_for(tab, ".logs-modal .skip-cancel"), "тело окна так и не обновилось"
        report = json.loads(tab.evaluate(MODAL_REPORT % json.dumps(".logs-modal")))
        assert report["role"] == "dialog", report
        assert report["name"], "после загрузки списка у окна пропало имя"
        assert "Логи" in report["name"], f"имя диалога: {report['name']!r}"
        assert wait_focus_inside(tab, ".logs-modal"), (
            "после подмены тела фокус улетел из окна"
        )
        tab.press("Escape")
        assert not json.loads(
            tab.evaluate(MODAL_REPORT % json.dumps(".logs-modal")))["open"], \
            "Escape не закрыл окно логов"
    finally:
        tab.close()


# ── 2. Видимая рамка фокуса и статика клавиатуры (обе темы) ──────
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_keyboard_scan_finds_no_problems(browser_cdp, live_app_url, theme):
    tab = new_tab(browser_cdp)
    try:
        open_page(tab, live_app_url)
        # Настоящий Tab до замера: он включает модальность «клавиатура», иначе
        # :focus-visible у кнопок не срабатывает и рамка «не найдётся».
        tab.press("Tab")
        state = {"theme": theme, "keyboard": True, "fillForm": True, "expandAccordions": True}
        raw = tab.evaluate(
            f"window.__A11Y_STATE = {json.dumps(state, ensure_ascii=False)};\n{AUDIT_JS}",
            await_promise=True,
        )
        assert raw, "аудит не вернул результат"
        result = json.loads(raw)
        rings = [c for c in result["stats"].get("checks", []) if c.startswith("focus-ring:")]
        assert rings and int(rings[0].split(":")[1]) >= 25, (
            f"проверка рамки фокуса осмотрела слишком мало элементов: {result['stats']}"
        )
        findings = result["findings"]
        assert findings == [], (
            f"{theme} тема: {len(findings)} нарушений клавиатуры\n"
            + "\n".join(f"  [{f['check']}] {f['sel']}: {f['detail']}" for f in findings)
        )
    finally:
        tab.close()




def test_keyboard_scan_detects_invisible_focus(browser_cdp, live_app_url):
    """Канарейка: элемент с отключённой рамкой обязан попасть в отчёт."""
    tab = new_tab(browser_cdp)
    try:
        open_page(tab, live_app_url)
        tab.press("Tab")
        state = {"theme": "light", "keyboard": True, "keyboardCanary": True}
        raw = tab.evaluate(
            f"window.__A11Y_STATE = {json.dumps(state, ensure_ascii=False)};\n{AUDIT_JS}",
            await_promise=True,
        )
        findings = json.loads(raw)["findings"]
        canary = [f for f in findings if f["check"] == "focus" and "canary" in f["sel"]]
        assert canary, (
            "аудит не увидел элемент без рамки фокуса — проверка ничего не значит:\n"
            + "\n".join(f"  [{f['check']}] {f['sel']}: {f['detail']}" for f in findings)
        )
    finally:
        tab.close()




# ── 3. Модальные окна ───────────────────────────────────────────
@pytest.mark.parametrize("case", MODALS, ids=[m["name"] for m in MODALS])
def test_modal_holds_focus_and_returns_it(browser_cdp, live_app_url, case):
    """Окно называет себя, держит фокус внутри и возвращает его после Escape."""
    name, opener, box = case["name"], case["js"], case["box"]
    closes = case.get("escape", True)
    tab = new_tab(browser_cdp)
    try:
        open_page(tab, live_app_url)
        if case.get("pre"):
            tab.evaluate(case["pre"])
        # Фокус и открытие — одним вызовом: между двумя вызовами приложение
        # успевает перерисовать панель, и «открывателем» оказалось бы body.
        tab.evaluate(
            "document.getElementById('btn-run').focus();"
            f" {opener}; void 0"
        )
        assert wait_for(tab, box), f"окно «{name}» не открылось ({box})"

        report = json.loads(tab.evaluate(MODAL_REPORT % json.dumps(box)))
        assert report["role"] == "dialog", f"«{name}»: role={report['role']} вместо dialog"
        assert report["ariaModal"] == "true", f"«{name}»: нет aria-modal=true"
        assert report["name"], f"«{name}»: у окна нет доступного имени"
        assert wait_focus_inside(tab, box), (
            f"«{name}»: фокус не перешёл внутрь (активный элемент — {report['active']})"
        )

        inside = (f"(() => {{ const box = document.querySelector({json.dumps(box)});"
                  " return !!box && box.contains(document.activeElement); })()")
        for _ in range(3):
            tab.press("Tab")
            assert tab.evaluate(inside), f"«{name}»: Tab вышел за пределы окна"
        for _ in range(2):
            tab.press("Tab", shift=True)
            assert tab.evaluate(inside), f"«{name}»: Shift+Tab вышел за пределы окна"

        if not closes:
            return                       # окно-блокировка: Esc у него нет по замыслу
        tab.press("Escape")
        closed = json.loads(tab.evaluate(MODAL_REPORT % json.dumps(box)))
        assert not closed["open"], f"«{name}»: Escape не закрыл окно"
        assert tab.evaluate("document.activeElement && document.activeElement.id === 'btn-run'"), (
            f"«{name}»: после закрытия фокус не вернулся на кнопку, которая открыла окно"
        )
    finally:
        tab.close()
