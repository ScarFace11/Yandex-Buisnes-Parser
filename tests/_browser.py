# -*- coding: utf-8 -*-
"""Живой браузер и живое приложение для сквозных тестов интерфейса.

Зачем отдельный модуль: аудиту доступности нужен не только снимок страницы
(одно вычисление выражения через CDP), но и НАСТОЯЩИЕ нажатия клавиш — порядок
фокуса, ловушку Tab в модалках и возврат фокуса нельзя проверить из страницы,
потому что синтетический KeyboardEvent фокус не двигает. Здесь живёт одна
CDP-сессия вкладки с методами navigate/evaluate/press, приложение на свободном
порту и запуск браузера под управлением yandex_maps_parser.cdp_client — того
же кода, которым пользуется сам поиск, поэтому интерфейс проверяется в том
браузере, который у пользователя.

Модуль приватный (`_browser.py`) — pytest не собирает его как тесты.
"""
import importlib.machinery
import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── Настоящий websocket-client ──────────────────────────────────
def load_real_websocket():
    """Настоящий websocket-client с диска, мимо sys.modules.

    Другие тест-файлы (tests/test_cdp_timeout.py) кладут в sys.modules["websocket"]
    минимальную заглушку, когда настоящий модуль ещё не импортирован. Для
    юнит-тестов это верно, но cdp_client берёт websocket из sys.modules — с
    заглушкой невозможно даже открыть вкладку, и сквозные тесты молча
    пропускались бы. Поэтому модуль загружается напрямую по пути.
    """
    current = sys.modules.get("websocket")
    if current is not None and getattr(current, "__file__", None) \
            and callable(getattr(current, "create_connection", None)):
        return current                      # настоящий уже загружен
    spec = importlib.machinery.PathFinder().find_spec("websocket")
    if spec is None or not spec.origin:
        return None
    real = importlib.util.module_from_spec(spec)
    sys.modules["websocket"] = real         # до exec: подмодули ищут родителя тут
    try:
        spec.loader.exec_module(real)
    except Exception:                       # noqa: BLE001 — битый/несовместимый пакет
        if current is not None:
            sys.modules["websocket"] = current
        else:
            sys.modules.pop("websocket", None)
        return None
    return real


# ── Приложение на свободном порту ───────────────────────────────
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class LiveApp:
    """Flask-приложение в потоке: настоящий HTTP, настоящие файлы, без сети."""

    def __init__(self, ready_timeout: float = 20.0):
        from werkzeug.serving import make_server

        from app import create_app

        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        self._server = make_server("127.0.0.1", self.port, create_app(), threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._wait_ready(ready_timeout)

    def _wait_ready(self, timeout: float) -> None:
        """Готовность — по настоящему ответу HTTP, а не «порт открылся»."""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(self.url, timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception as exc:        # noqa: BLE001 — ждём любой готовности
                last = exc
                time.sleep(0.2)
        self.close()
        raise AssertionError(f"приложение не поднялось за {timeout} с: {last}")

    def close(self) -> None:
        try:
            self._server.shutdown()
        except Exception:                   # noqa: BLE001 — уже остановлен
            pass
        self._thread.join(timeout=5)


# ── CDP-сессия вкладки ──────────────────────────────────────────
# Ключи: код + скан-код (Chromium по ним понимает, что за клавиша).
KEYS = {
    "Tab":     (9, "Tab", 9),
    "Escape":  (27, "Escape", 27),
    "Enter":   (13, "Enter", 13),
    " ":       (32, " ", 32),
    "ArrowDown": (40, "ArrowDown", 40),
    "ArrowRight": (39, "ArrowRight", 39),
}


class Tab:
    """Вкладка браузера: навигация, вычисление выражений и настоящие клавиши.

    Каждый вызов — один WebSocket к странице, ответы сопоставляются по id,
    события (у них id нет) пропускаются. Ошибка в вычисляемом выражении
    поднимается как исключение: молча вернуть None и «пройти тест» хуже, чем
    упасть.
    """

    def __init__(self, ws_url: str, timeout: float = 30.0):
        import websocket

        self._ws = websocket.create_connection(ws_url, timeout=timeout)
        self._timeout = timeout
        self._next_id = 0
        self.closed = False

    # — транспорт —
    def call(self, method: str, params: dict | None = None):
        """CDP-команда с ожиданием своего ответа (события пропускаются)."""
        self._next_id += 1
        want = self._next_id
        self._ws.send(json.dumps({"id": want, "method": method, "params": params or {}}))
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                self._ws.settimeout(max(0.5, deadline - time.monotonic()))
                data = json.loads(self._ws.recv())
            except Exception as exc:        # noqa: BLE001 — таймаут чтения = ждём ещё
                if "timed out" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
                    continue
                raise
            if data.get("id") != want:
                continue                    # событие страницы, не наш ответ
            if "error" in data:
                raise RuntimeError(f"{method} → {data['error']}")
            return data.get("result", {})
        raise TimeoutError(f"{method}: ответа нет за {self._timeout} с")

    # — измерения —
    def evaluate(self, expression: str, await_promise: bool = False):
        res = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": bool(await_promise),
        })
        if res.get("exceptionDetails"):
            desc = (res["exceptionDetails"].get("exception") or {}).get("description")
            raise RuntimeError(desc or json.dumps(res["exceptionDetails"], ensure_ascii=False))
        return res.get("result", {}).get("value")

    def active_element(self) -> str:
        """Короткий путь активного элемента — что видит пользователь по Tab."""
        return self.evaluate(
            "(() => { const el = document.activeElement || document.body;"
            " const path = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')"
            " + ((typeof el.className === 'string' && el.className.trim())"
            "    ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');"
            " return path; })()"
        )

    # — взаимодействие —
    def press(self, key: str, times: int = 1, shift: bool = False) -> None:
        """Настоящее нажатие клавиши: фокус двигает сам браузер, не скрипт.

        shift=True — Shift+клавиша (нужен для Shift+Tab: обход назад идёт
        по другому порядку и ловушку надо проверять с обеих сторон).
        """
        if key not in KEYS:
            raise KeyError(f"нет такого ключа в KEYS: {key}")
        vk, code, native = KEYS[key]
        for _ in range(times):
            base = {
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": native,
                "key": key, "code": code,
                "modifiers": 8 if shift else 0,
            }
            self.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", **base})
            # Enter и пробел шлют еще и текст: без него не сработают
            # onclick-обработчики, которые ждут настоящую активацию кнопки.
            if key in ("Enter", " "):
                self.call("Input.dispatchKeyEvent", {
                    "type": "char", "text": "\r" if key == "Enter" else " ", **base,
                })
            self.call("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    def click(self, selector: str) -> bool:
        """Настоящий клик по элементу (мышь не нужна — координаты центра)."""
        box = self.evaluate(
            "(() => { const el = document.querySelector(%s); if (!el) return null;"
            " const r = el.getBoundingClientRect();"
            " return [r.left + r.width / 2, r.top + r.height / 2]; })()"
            % json.dumps(selector)
        )
        if not box:
            return False
        x, y = box
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                               "button": "left", "clickCount": 1})
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                               "button": "left", "clickCount": 1})
        return True

    # — навигация —
    def open(self, url: str, wait_expr: str = "document.readyState === 'complete'",
             timeout: float = 60.0) -> None:
        """Перейти на страницу и дождаться не только загрузки, но и готовности узла."""
        self.call("Page.enable")
        self.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        self.call("Page.navigate", {"url": url})
        # Делаем вкладку активной: на головном Chromium CI-раннера фоновая
        # вкладка не всегда обрабатывает нажатия Tab (Input.dispatchKeyEvent
        # уходит, но фокус не двигается — обход пуст). bringToFront ставит
        # вкладку на передний план, и клавиатура ведёт себя как у пользователя.
        self.call("Page.bringToFront")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.evaluate(f"document.readyState === 'complete' && !!({wait_expr})"):
                    return
            except Exception:               # noqa: BLE001 — страница ещё меняется
                pass
            time.sleep(0.2)
        raise TimeoutError(f"страница {url} не готова за {timeout} с (ждём {wait_expr})")

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self._ws.close()
            except Exception:               # noqa: BLE001 — закрывать нечего
                pass


def new_tab(cdp_client, timeout: float = 30.0) -> Tab:
    """Новая вкладка в запущенном браузере (пул поиска не трогаем)."""
    ws_url = cdp_client._create_tab()
    if not ws_url:
        raise AssertionError("не удалось создать вкладку в браузере")
    return Tab(ws_url, timeout=timeout)
