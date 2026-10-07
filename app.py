"""Flask application entry point.

All routes are organized in blueprints under routes/.
Run management is in run_manager.py.

Supports running from source (python app.py) and as a frozen PyInstaller
bundle (paths.py resolves templates/static/writable dirs accordingly).
"""
import sys
import multiprocessing

# MUST run before anything else when frozen: without this, a PyInstaller exe
# relaunches the whole application for every multiprocessing child.
multiprocessing.freeze_support()

import os

# Frozen exe: chdir to a writable dir so relative paths (output/, logs/)
# land next to the .exe instead of the read-only extraction dir.
import paths


def _ensure_streams(max_log_bytes: int = 2 * 1024 * 1024) -> None:
    """Ставит stdout/stderr, если их нет (macOS .app запускается без консоли).

    В оконном режиме PyInstaller оставляет `sys.stdout is None`: обычный
    print() это терпит, но любая запись в поток или падение с трейсбеком
    никуда не попадает. Перенаправляем вывод в app.log рядом с данными
    (output/, logs/) — там же, где всё остальное. Файл обрезается, чтобы
    не расти бесконечно.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    try:
        path = paths.user_dir() / "app.log"
        if path.exists() and path.stat().st_size > max_log_bytes:
            path.write_text("", encoding="utf-8")   # прошлый запуск — в архив истории
        stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        try:
            stream = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    print(f"[app] вывод перенаправлен (console=False): {getattr(stream, 'name', '—')}")


_ensure_streams()

if paths.is_frozen():
    os.chdir(paths.user_dir())

from flask import Flask

from routes.parser import bp as parser_bp
from routes.sender import bp as sender_bp
from routes.api   import bp as api_bp
from routes.public_api import bp as public_api_bp
from routes.update  import bp as update_bp
from routes.diagnostics import bp as diagnostics_bp


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=paths.template_dir(),
        static_folder=paths.static_dir(),
    )
    try:
        from config import APP_VERSION, is_dev_build
    except ImportError:
        APP_VERSION = "dev"
        is_dev_build = lambda: True
    app.config["APP_VERSION"] = APP_VERSION
    # Сборка разработчика: в шапке горит метка DEV (другой exe, другой порт,
    # без авто-обновления — см. config.is_dev_build).
    app.config["DEV_BUILD"] = bool(is_dev_build())
    app.jinja_env.globals["APP_VERSION"] = APP_VERSION
    app.jinja_env.globals["DEV_BUILD"] = bool(is_dev_build())
    app.register_blueprint(parser_bp)
    app.register_blueprint(sender_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(public_api_bp)
    app.register_blueprint(update_bp)
    # «🩺 Диагностика» — самопроверка по кнопке (только localhost-интерфейс).
    app.register_blueprint(diagnostics_bp)
    return app


app = create_app()

# Cleanup old log files on startup
try:
    from run_logger import cleanup_old_logs
    deleted = cleanup_old_logs()
    if deleted:
        print(f"  🧹 Удалено {deleted} старых лог-файлов")
except Exception:
    pass

# Cleanup expired cache files on startup
try:
    from yandex_maps_parser.cache import cleanup_expired as _cache_cleanup
    removed = _cache_cleanup()
    if removed:
        print(f"  🧹 Удалено {removed} устаревших кэш-файлов")
except Exception:
    pass

def _startup_port() -> int:
    """Порт: YP_PORT → dev 5010 → 5000 (см. config.app_port)."""
    try:
        from config import app_port
        return app_port()
    except Exception:
        return 5000


def _port_is_free(port: int) -> bool:
    """Свободен ли порт на loopback.

    Проверка идёт двумя способами: сначала пробуем подключиться — если кто-то
    принимает соединение, порт занят (на Windows SO_REUSEADDR разрешает
    занять уже слушающий порт, и один только bind соврал бы). Затем пробуем
    сам bind — так ловятся порты, зарезервированные системой.
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        try:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return False
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _available_port(preferred: int, tries: int = 20) -> int:
    """Возвращает занятый порт или следующий свободный.

    Порт 5000 на macOS занимает системный AirPlay Receiver, а на любой
    системе он может быть занят другой программой. Раньше приложение просто
    падало с «address already in use» — вместо этого берём следующий порт и
    печатаем его в лог (на macOS он же откроется в браузере).
    """
    if _port_is_free(preferred):
        return preferred
    for p in range(preferred + 1, min(preferred + tries, 65536)):
        if _port_is_free(p):
            print(f"  [!] Порт {preferred} занят — использую {p}")
            return p
    return preferred   # нечего было выбрать — пусть Flask скажет свою ошибку


def _should_open_browser() -> bool:
    """Открывать ли интерфейс при старте в браузере по умолчанию.

    Раньше интерфейс открывался в окне Chrome (CDP-окно): у пользователей
    без Chrome окно не появлялось вовсе. Теперь стартовая страница всегда
    открывается в системном браузере по умолчанию — Windows берёт
    ассоциацию ОС (Edge/Opera/Chrome…), macOS открывает Safari.
    YP_OPEN_BROWSER=0 отключает автозапуск (нужно автотестам сборки и
    тому, кто держит свою вкладку).
    """
    if os.getenv("YP_OPEN_BROWSER", "").strip().lower() in ("0", "false", "no"):
        return False
    return True


def _open_default_browser(url: str) -> bool:
    """Открывает URL в системном браузере по умолчанию (macOS → Safari).

    Windows: os.startfile использует ассоциацию ОС — откроется тот браузер,
    что выбран в системе по умолчанию (Edge, Opera, Chrome, Firefox…),
    без требования установленного Chrome. macOS: сначала явно Safari
    (браузер ОС по умолчанию), при неудаче — общий webbrowser.open.
    Возвращает True, если открытие удалось.
    """
    import webbrowser
    try:
        if sys.platform == "darwin":
            try:
                return bool(webbrowser.get("safari").open(url))
            except webbrowser.Error:
                pass  # Safari недоступен — общий путь ниже
            return bool(webbrowser.open(url))
        if sys.platform == "win32":
            try:
                os.startfile(url)
                return True
            except OSError:
                pass  # нет ассоциации — webbrowser.open ниже
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _open_startup_url(url: str) -> None:
    """Показывает интерфейс пользователю при старте.

    Сначала — браузер по умолчанию (macOS: Safari). Если открыть его не
    удалось (нет ассоциации, headless-окружение) — прежнее видимое окно
    Chrome с CDP, если Chrome установлен. Иначе остаётся консоль/лог
    с адресом.
    """
    if _open_default_browser(url):
        return
    try:
        import atexit
        from yandex_maps_parser import cdp_client
        atexit.register(cdp_client.close_debug_window)
        cdp_client.open_debug_window(start_url=url)
    except Exception:
        pass  # адрес уже напечатан в консоли/логе


def _open_browser_later(url: str, delay: float = 1.5) -> None:
    """Открывает вкладку после старта сервера (не блокирует app.run)."""
    import threading

    def _go():
        try:
            _open_startup_url(url)
        except Exception:
            pass

    threading.Timer(delay, _go).start()


def _maybe_run_browser_probe() -> bool:
    """Probe-режим для проверки Chromium внутри .exe (YP_BROWSER_PROBE=1).

    В frozen-сборке `sys.executable` — это сам exe, поэтому обычный
    сабпроцесс-тест «python -c …» из browser_client там не работает.
    Вместо него родитель запускает СВОЙ exe с YP_BROWSER_PROBE=1: процесс
    молча стартует Playwright+Chromium и выходит с кодом 0/1 — так же,
    как делал бы python -c. Позволяет отловить крэш 0xC0000005 и другие
    проблемы запуска ДО боевого прогона.

    Returns True, если процесс работал в probe-режиме (и надо выйти).
    """
    if os.environ.get("YP_BROWSER_PROBE", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)


def _should_open_cdp_window() -> bool:
    """Открывать ли при старте отдельное окно Chrome с CDP.

    По умолчанию НЕТ: интерфейс теперь открывается в браузере по умолчанию,
    а для парсинга runner сам запускает свой headless Chrome — стартовое
    окно Chrome не нужно (у пользователей без Chrome оно и раньше не
    открывалось). YP_DEBUG_WINDOW=1 включает окно для отладки: видимый
    Chrome на временном профиле с CDP-портом, работает и при сломанном
    системном Chrome.
    """
    return os.getenv("YP_DEBUG_WINDOW", "0").strip().lower() in ("1", "true", "yes", "on")


def _open_cdp_window_later(url: str, delay: float = 0.5) -> None:
    """Открывает отладочное окно Chrome в фоне (не блокирует app.run).

    В окне сразу открывается интерфейс приложения (url), чтобы не
    набирать адрес вручную. Окно живёт до выхода из приложения
    (close_debug_window в atexit).
    """
    import atexit
    import threading

    def _go():
        try:
            from yandex_maps_parser import cdp_client
            atexit.register(cdp_client.close_debug_window)
            port = cdp_client.open_debug_window(start_url=url)
            # print — отдельно: на cp1251-консоли эмодзи падает, а окно
            # уже открыто; главное, чтобы сам процесс запустился.
            try:
                if port:
                    print(f"  [CDP] окно Chrome открыто, CDP-порт {port}")
                else:
                    print("  [CDP] окно Chrome не открылось (см. лог)")
            except Exception:
                pass
        except Exception as e:
            try:
                print(f"  [CDP] окно Chrome: {e}")
            except Exception:
                pass

    threading.Timer(delay, _go).start()


if __name__ == "__main__":
    # Probe-режим: молча проверить Chromium и выйти (используется .exe-сборкой
    # для сабпроцесс-теста — см. _maybe_run_browser_probe в этом файле).
    _maybe_run_browser_probe()
    _port = _available_port(_startup_port())
    try:
        from config import APP_VERSION, is_dev_build
        if is_dev_build():
            print("═" * 62)
            print(f"  ⚙ DEV-СБОРКА {APP_VERSION} — только для разработки")
            print("  Авто-обновление выключено, чтобы публичный релиз не затёр")
            print("  локальные изменения. Приложение: "
                  f"http://127.0.0.1:{_port}")
            print("═" * 62)
    except Exception:
        pass
    if _should_open_browser():
        _open_browser_later(f"http://127.0.0.1:{_port}/")
    if _should_open_cdp_window():
        _open_cdp_window_later(f"http://127.0.0.1:{_port}/")
    app.run(host="127.0.0.1", port=_port, debug=False)
