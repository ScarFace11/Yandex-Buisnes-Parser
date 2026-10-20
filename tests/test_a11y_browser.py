# -*- coding: utf-8 -*-
"""Сквозной аудит доступности и контраста — в НАСТОЯЩЕМ браузере.

Зачем: tests/test_theme_contrast.py проверяет токены и правила по тексту CSS,
но итоговый цвет надписи складывается из наследования, перекрытий и наложения
полупрозрачных слоёв — увидеть его можно только на отрисованной странице. Здесь
приложение поднимается на свободном порту (tests/conftest.py), страница
открывается браузером пользователя (тот же Chrome DevTools Protocol, что и при
поиске), и в ней выполняется tests/a11y_audit.js.

Проверяется то, что человек действительно видит и трогает:

* контраст текста к его фактическому фону (WCAG AA: 4.5:1, 3:1 для крупного);
* доступные имена кнопок, ссылок, полей и переключателей;
* подписи у полей ввода;
* ARIA-связи (aria-controls/aria-labelledby указывают на существующие узлы)
  и состояния (aria-expanded, aria-selected, aria-checked у role=switch);
* отсутствие горизонтального скролла страницы.

Матрица состояний: обе темы × (раскрытый сайдбар, свёрнутый сайдбар, попап
уведомлений, блок API-ключей, тосты, каждая вкладка, таблица с записями,
статистика).

Клавиатура (порядок фокуса, видимая рамка, ловушка Tab в модалках) проверяется
отдельно — там нужны НАСТОЯЩИЕ нажатия клавиш, см. tests/test_a11y_keyboard.py.

Отдельный тест-канарейка доказывает, что аудит вообще что-то находит: в
страницу подкладывается белая надпись на светлом фоне и кнопка без имени, и
аудит обязан про них сообщить. Без этого «нуль находок» ничего не значит.

Браузера на Chromium может не быть (CI-раннер без Chrome, чужой ноутбук) —
тогда тест СКИПАЕТСЯ с явной причиной, а не падает: отсутствие браузера не
делает интерфейс недоступным.

Run with: python -m pytest tests/test_a11y_browser.py -v
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AUDIT_JS = (ROOT / "tests" / "a11y_audit.js").read_text(encoding="utf-8")

TABS = ("log", "table", "map", "stats", "history", "templates")

# Состояния страницы, которые проверяются в обеих темах.
STATE_SPECS = (
    ("collapsed-sidebar", {"fillForm": True}),
    ("open-sidebar", {"fillForm": True, "expandAccordions": True}),
    ("notify-popover", {"fillForm": True, "openNotify": True}),
    ("api-keys", {"fillForm": True, "openApiKeys": True}),
    ("toasts", {"fillForm": True, "toasts": True}),
    ("table-with-rows", {"fillForm": True, "tab": "table", "seedRows": True}),
    ("stats-with-rows", {"fillForm": True, "tab": "stats", "seedRows": True, "seedStats": True}),
    *[(f"tab-{t}", {"fillForm": True, "expandAccordions": True, "tab": t}) for t in TABS],
)

CONTRAST_FLOOR = 4.5

# Размер окна проверки — один на всех машинах и системах. Без него раскладка
# зависит от того, каким окном запустился браузер на раннере: на широком окне
# горизонтального скролла нет, на узком (980px на macOS-раннере) та же
# страница скроллилась вбок, и тест «падал только на macOS».
# 1024×800 — самое узкое из обычных окон ноутбука: интерфейс обязан в него
# влезать.
VIEWPORT = (1024, 800)


def run_audit(cdp, url: str, state: dict) -> dict:
    """Открыть страницу в браузере, применить состояние и выполнить аудит."""
    ws_url = cdp._create_tab()
    assert ws_url, "не удалось создать вкладку в браузере"
    expression = f"window.__A11Y_STATE = {json.dumps(state, ensure_ascii=False)};\n{AUDIT_JS}"
    try:
        raw = cdp._cdp_eval_page(
            ws_url, url, expression,
            wait_expr="document.getElementById('setup-summary')",
            timeout_s=90,
            viewport=VIEWPORT,
        )
    finally:
        # Вкладка живёт один аудит: без закрытия за прогон их набираются
        # десятки, каждый держит процесс-рендерер, и проверка начинает
        # ловить таймауты вместо находок (замер: один тест — 6 с, а в общем
        # прогоне после восьми аудитов уже сотня секунд).
        cdp._close_dead_tab(ws_url)
    assert raw, f"аудит не вернул результат (состояние {state})"
    return json.loads(raw)


def format_findings(findings: list) -> str:
    return "\n".join(
        f"  [{f['check']}] {f['sel']}: {f['detail']}" for f in findings
    )


# ── Матрица: обе темы во всех состояниях страницы ───────────────
@pytest.mark.parametrize("theme", ("light", "dark"))
@pytest.mark.parametrize("name,extra", STATE_SPECS, ids=[s[0] for s in STATE_SPECS])
def test_interface_passes_audit(browser_cdp, live_app_url, theme, name, extra):
    state = {"theme": theme, **extra}
    result = run_audit(browser_cdp, live_app_url, state)
    assert result["stats"]["scanned"] > 50, (
        f"аудит осмотрел слишком мало элементов ({result['stats']}) — "
        "похоже, страница не отрисовалась"
    )
    findings = result["findings"]
    assert findings == [], (
        f"{theme} тема, состояние «{name}»: {len(findings)} нарушений\n"
        + format_findings(findings)
    )


# ── Канарейка: аудит обязан находить подложенные нарушения ──────
def test_audit_detects_broken_markup(browser_cdp, live_app_url):
    """Без этой проверки «нуль находок» ничего не доказывает.

    В страницу кладётся белая надпись на светлом фоне (2.27:1) и кнопка без
    доступного имени — обе обязаны попасть в отчёт.
    """
    result = run_audit(browser_cdp, live_app_url, {"theme": "light", "canary": True})
    findings = result["findings"]
    contrast = [f for f in findings if f["check"] == "contrast" and "canary" in f["sel"]]
    names = [f for f in findings if f["check"] == "name" and "canary" in f["sel"]]
    assert contrast, f"контраст-проверка не сработала:\n{format_findings(findings)}"
    assert names, f"проверка доступных имён не сработала:\n{format_findings(findings)}"
    assert float(contrast[0]["detail"].split(":1")[0]) < CONTRAST_FLOOR


# ── Тумблеры и попап уведомлений: тема переключается на живом интерфейсе ──
def test_theme_switch_keeps_the_notify_popover_readable(browser_cdp, live_app_url):
    """Один и тот же попап проверяется в двух темах — переключение на месте.

    Переключение темы не перерисовывает страницу заново: цвета в попапе
    (тумблеры, селекты звуков, ползунок громкости) меняются на месте, без
    перезагрузки — раньше именно здесь терялся контраст.
    """
    light = run_audit(browser_cdp, live_app_url, {"theme": "light", "openNotify": True})
    dark = run_audit(browser_cdp, live_app_url, {"theme": "dark", "openNotify": True})
    assert light["findings"] == [], format_findings(light["findings"])
    assert dark["findings"] == [], format_findings(dark["findings"])
