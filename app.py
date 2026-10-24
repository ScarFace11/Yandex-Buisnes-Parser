"""Flask application entry point."""
import sys
import multiprocessing

# MUST run before anything else when frozen: without this, a PyInstaller exe relaunches the whole application for every multiprocessing child.
multiprocessing.freeze_support()

import os

# Frozen exe: chdir to a writable dir so relative paths (output/, logs/) land next to the .exe instead of the read-only extraction dir.
import paths

# Вывод в UTF-8 и без падений — одно место на все точки входа (см. console_io).
from console_io import enable_utf8, say


def _ensure_streams(max_log_bytes: int = 2 * 1024 * 1024) -> None:
    """Ставит stdout/stderr, если их нет (macOS .app запускается без консоли)."""
    # Перенаправленный вывод (лог-файл, пайп) — в UTF-8: системная кодировка русской Windows (cp1251/cp866) роняла приложение на первом же сообщении.
    enable_utf8()

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
    # Из исходников шаблоны читаются заново на каждый запрос: во время работы над интерфейсом правка templates/index.html должна быть видна после обновления страницы, а не после перезапуска сервера (Jinja кеширует скомпилированные шаблоны при debug=False).
    if not getattr(sys, "frozen", False):
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True
    # Сборка разработчика: в шапке горит метка DEV (другой exe, другой порт, без авто-обновления — см. config.is_dev_build).
    app.config["DEV_BUILD"] = bool(is_dev_build())
    app.jinja_env.globals["APP_VERSION"] = APP_VERSION
    app.jinja_env.globals["DEV_BUILD"] = bool(is_dev_build())
    app.register_blueprint(parser_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(public_api_bp)
    app.register_blueprint(update_bp)
    # «🩺 Диагностика» — самопроверка по кнопке (только localhost-интерфейс).
    app.register_blueprint(diagnostics_bp)

    @app.after_request
    def _no_stale_ui(resp):
        """Интерфейс не должен отдаваться из кеша браузера."""
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            resp.headers["Cache-Control"] = "no-store"
        elif any(k in ctype for k in ("text/css", "javascript", "text/javascript")):
            resp.headers.setdefault("Cache-Control", "no-cache, must-revalidate")
        return resp

    return app


app = create_app()

# Cleanup old log files on startup
try:
    from run_logger import cleanup_old_logs
    deleted = cleanup_old_logs()
    if deleted:
        say(f"  [cleanup] Удалено {deleted} старых лог-файлов")
except Exception:
    pass

# Cleanup expired cache files on startup
try:
    from yandex_maps_parser.cache import cleanup_expired as _cache_cleanup
    removed = _cache_cleanup()
    if removed:
        say(f"  [cleanup] Удалено {removed} устаревших кэш-файлов")
except Exception:
    pass

# Хранение результатов: автоудаление файлов старше N дней (7/14/30/своё).
try:
    import retention
    _removed = retention.cleanup_old_results()
    if _removed:
        say(f"  [cleanup] Удалено {_removed} устаревших файлов результатов "
            f"(хранение {retention.get_retention_days()} дн.)")
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
    """Свободен ли порт на loopback."""
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
    """Возвращает занятый порт или следующий свободный."""
    if _port_is_free(preferred):
        return preferred
    for p in range(preferred + 1, min(preferred + tries, 65536)):
        if _port_is_free(p):
            print(f"  [!] Порт {preferred} занят — использую {p}")
            return p
    return preferred   # нечего было выбрать — пусть Flask скажет свою ошибку


def _should_open_browser() -> bool:
    """Открывать ли интерфейс при старте в браузере по умолчанию."""
    if os.getenv("YP_OPEN_BROWSER", "").strip().lower() in ("0", "false", "no"):
        return False
    return True


def _open_default_browser(url: str) -> bool:
    """Открывает URL в системном браузере по умолчанию (macOS → Safari)."""
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
    """Показывает интерфейс пользователю при старте."""
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


def _maybe_run_selfcheck() -> None:
    """`--check`: самопроверка без запуска интерфейса (см. selfcheck.py)."""
    if "--check" not in sys.argv:
        return
    try:
        import selfcheck
    except Exception as exc:
        print(f"Самопроверка недоступна: {type(exc).__name__}")
        sys.exit(2)
    args = [a for a in sys.argv[1:] if a != "--check"]
    sys.exit(selfcheck.main(args))


def _maybe_run_headless() -> None:
    """`--run`: сбор по сохранённому пресету без интерфейса (см. headless.py)."""
    if "--run" not in sys.argv:
        return
    try:
        import headless
    except Exception as exc:
        print(f"Сбор из консоли недоступен: {type(exc).__name__}")
        sys.exit(2)
    args = [a for a in sys.argv[1:] if a != "--run"]
    sys.exit(headless.main(args))


def _maybe_run_browser_probe() -> bool:
    """Probe-режим для проверки браузера внутри .exe (YP_BROWSER_PROBE=1)."""
    if os.environ.get("YP_BROWSER_PROBE", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    try:
        from yandex_maps_parser import cdp_client
        ok = cdp_client.init_browser(pool_size=1, visible=False)
        cdp_client.close_browser()
        sys.exit(0 if ok else 1)
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)


def _should_open_cdp_window() -> bool:
    """Открывать ли при старте отдельное окно Chrome с CDP."""
    return os.getenv("YP_DEBUG_WINDOW", "0").strip().lower() in ("1", "true", "yes", "on")


def _open_cdp_window_later(url: str, delay: float = 0.5) -> None:
    """Открывает отладочное окно Chrome в фоне (не блокирует app.run)."""
    import atexit
    import threading

    def _go():
        try:
            from yandex_maps_parser import cdp_client
            atexit.register(cdp_client.close_debug_window)
            port = cdp_client.open_debug_window(start_url=url)
            # print — отдельно: на cp1251-консоли эмодзи падает, а окно уже открыто; главное, чтобы сам процесс запустился.
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


def _set_windows_console_icon() -> None:
    """Фирменная иконка окну консоли: .exe в проводнике уже с ней, а
    запущенное окно в панели задач иначе показывает питоновский значок.
    Только Windows и только когда .ico есть рядом; ошибки не мешают старту."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ico = os.path.join(paths.static_dir(), "icon.ico")
        if not os.path.exists(ico):
            return
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                      ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_uint]
        user32.GetConsoleWindow.restype = ctypes.c_void_p
        hwnd = user32.GetConsoleWindow()
        if not hwnd:
            return
        image_icon, load_from_file, wm_seticon = 1, 0x10, 0x80
        for size, kind in ((16, 0), (32, 1)):
            handle = user32.LoadImageW(None, ico, image_icon, size, size,
                                       load_from_file)
            if handle:
                user32.SendMessageW(ctypes.c_void_p(hwnd), wm_seticon, kind, handle)
    except Exception:
        pass


if __name__ == "__main__":
    # Probe-режим: молча проверить Chromium и выйти (используется .exe-сборкой для сабпроцесс-теста — см. _maybe_run_browser_probe в этом файле).
    _maybe_run_browser_probe()
    # --check: те же проверки, что и в окне «Диагностика», но без сервера.
    _maybe_run_selfcheck()
    # --run: сбор по сохранённому пресету без интерфейса.
    _maybe_run_headless()
    _set_windows_console_icon()
    _port = _available_port(_startup_port())
    try:
        from config import APP_VERSION, is_dev_build
        if is_dev_build():
            print("═" * 62)
            print(f"  DEV-СБОРКА {APP_VERSION} — только для разработки")
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
