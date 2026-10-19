"""Единый источник текста фронтенд-скриптов для pytest.

static/js/app.js разделён на последовательные модули (01-…11-…): тесты
читают их склейку в исходном порядке — текст байт-в-байт совпадает со
старым единым файлом, поэтому все строковые assert'ы работают без изменений.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Порядок обязан совпадать с порядком подключения в templates/index.html.
JS_MODULES = [
    "01-core-state.js",
    "02-app-shell.js",
    "03-log-run.js",
    "04-results-table.js",
    "05-results-bulk.js",
    "06-map-stats.js",
    "07-stats-daily.js",
    "08-presets-notify.js",
    "09-ui-extras.js",
    "10-templates.js",
    "11-app-init.js",
    "12-setup-summary.js",
]


def read_app_js() -> str:
    """Конкатенация всех JS-модулей в порядке подключения = старый app.js."""
    return "".join(
        (ROOT / "static" / "js" / name).read_text(encoding="utf-8")
        for name in JS_MODULES
    )
