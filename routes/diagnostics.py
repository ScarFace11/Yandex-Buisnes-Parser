"""🩺 Диагностика: самопроверка приложения без чтения логов.

Зачем это нужно. Приложение — десктопное: у пользователя нет консоли перед
глазами, и почти все обращения «ничего не работает» сводятся к четырём
причинам: ключ не тот или исчерпан, нет прав на папку результатов, сбор
сделан старой версией (в raw нет новых колонок) или на машине нет браузера
для докачки соцсетей с карточек. Панель отвечает на это одним нажатием.

Правила, по которым она сделана:

* **Ничего не трогает в рабочем состоянии.** Живые проверки две: токен
  ВКонтакте (отдельный клиент httpx, без ретраев и общего rate-limiter) и
  проба браузера — она открывает свой Chrome приложением и закрывает его
  сразу после проверки, поэтому идущий поиск не ускорить и не остановить.
* **Секреты наружу не отдаются.** В ответе только булевы признаки и словами
  описанный результат; текст исключений целиком не пересказывается — в нём
  мог бы оказаться токен из URL запроса.
* **Токен проверяется только по нажатию.** Живая проверка — сетевой запрос,
  поэтому она отделена от локальных и запускается осознанно.
* **Ошибки не роняют панель.** Любое падение отдельной проверки становится
  строкой «ошибка» с человеческим объяснением, а не 500.

Эндпоинт один: POST /diagnostics/run {"groups": ["keys", "files", "data", "env"]}.

Запустить его может только сам интерфейс: проверка токена обращается к
внешнему сервису от имени пользователя, а окно приложения слушает 127.0.0.1 —
значит чужая страница в браузере не должна уметь нажать эту кнопку за него
(см. `_only_from_our_ui`).
"""
import os
import re
import shutil
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("diagnostics", __name__)

# Группы проверок: раздельно, потому что «ключи» стоят квоту и время, а
# «файлы/данные/окружение» — бесплатны и мгновенны.
GROUPS = ("keys", "files", "data", "env", "engines")

_HTTP_TIMEOUT = 8.0                     # живые проверки не должны «висеть»
_USER_AGENT = "YandexBusinessParser-diagnostics"
_MIN_FREE_BYTES = 1024 ** 3             # меньше гигабайта — предупреждаем
_GB = 1024 ** 3

# Коды ошибок VK, которые реально встречаются при работе с токеном.
_VK_ERRORS = {
    5: "токен недействителен или отозван",
    6: "слишком много запросов — подождите минуту и повторите",
    15: "доступ запрещён (токен без нужных прав)",
    27: "ключ доступа группы недействителен",
    28: "срок действия токена истёк",
}


# ── Общие помощники ───────────────────────────────────────────

def _res(cid: str, group: str, status: str, title: str,
         detail: str = "", hint: str = "") -> dict:
    """Одна строка отчёта. status: ok | warn | error."""
    return {"id": cid, "group": group, "status": status,
            "title": title, "detail": detail, "hint": hint}


def effective_keys() -> dict:
    """Ключи, которыми реально пользуется запуск.

    Единственный ключ — токен ВКонтакте (проверка активности сообществ).
    Яндекс.Карты читаются браузером, поэтому ключа Яндекса в приложении нет:
    и API организаций, и геокодер платные, а их бесплатные версии запрещают
    сохранять данные.
    """
    keys = {"vk": ""}
    try:
        from config import VK_TOKEN
        keys = {"vk": (VK_TOKEN or "").strip()}
    except Exception:
        pass
    try:
        from yandex_maps_parser.vk_stats import _token as _vk_token
        keys["vk"] = keys["vk"] or (_vk_token() or "").strip()
    except Exception:
        pass
    return keys


def _exception_note(exc: Exception) -> str:
    """Короткое описание сбоя БЕЗ текста исключения.

    Тексты httpx иногда содержат полный URL запроса — то есть ключ. Наружу
    уходит только класс ошибки: этого достаточно, чтобы отличить «нет сети»
    от «сертификат» и при этом не показать секрет.
    """
    return type(exc).__name__


def _http_get(url: str, params: dict) -> tuple[int, str, dict | None, str]:
    """GET → (код, тело, json|None, примечание).

    Свой клиент, без ретраев и общего лимитера: диагностика не должна
    вмешиваться в идущий поиск.
    """
    try:
        import httpx
        r = httpx.get(url, params=params, timeout=_HTTP_TIMEOUT,
                      headers={"User-Agent": _USER_AGENT})
    except Exception as exc:
        return 0, "", None, _exception_note(exc)
    text = r.text or ""
    try:
        return r.status_code, text, r.json(), ""
    except Exception:
        return r.status_code, text, None, "ответ сервиса не является JSON"


def _http_json(url: str, params: dict) -> tuple[int, dict | None, str]:
    """То же, но только JSON — для 2ГИС и VK."""
    status, _text, data, note = _http_get(url, params)
    return status, data, note


def _error_message(text: str, data: dict | None) -> str:
    """Текст ошибки сервиса человеческим языком — и без лишнего мусора.

    Яндекс отдаёт ошибки XML-ом (`<message>Invalid api key</message>`),
    остальные — готовым JSON. Обрезаем и убираем переводы строк: строка
    уходит прямо в интерфейс.
    """
    candidates = []
    if text:
        found = re.search(r"<message>(.*?)</message>", text, re.S)
        if found:
            candidates.append(found.group(1))
    if isinstance(data, dict):
        for key in ("message", "error", "error_msg"):
            value = data.get(key)
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, dict) and isinstance(value.get("message"), str):
                candidates.append(value["message"])
    for candidate in candidates:
        clean = " ".join(str(candidate).split())[:160]
        if clean:
            return clean
    return ""


def _fmt_bytes(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def _dir_size(path: str, suffix: str = "") -> tuple[int, int]:
    """(число файлов, суммарный размер). Молча 0 — диагностика не падает."""
    files = size = 0
    try:
        for name in os.listdir(path):
            if suffix and not name.lower().endswith(suffix):
                continue
            full = os.path.join(path, name)
            if os.path.isfile(full):
                files += 1
                size += os.path.getsize(full)
    except OSError:
        pass
    return files, size


# ── Группа «keys»: живые проверки ─────────────────────────────

def check_vk_token(token: str) -> dict:
    """Пробный users.get: действителен ли токен ВКонтакте."""
    if not token:
        return _res("vk_token", "keys", "warn", "Токен ВКонтакте не задан",
                    "Проверка активности сообществ ВК работать не будет.",
                    "Вставьте токен в блоке «API-ключи» и сохраните.")
    status, data, note = _http_json("https://api.vk.com/method/users.get", {
        "access_token": token, "v": "5.199",
    })
    if not status:
        return _res("vk_token", "keys", "error", "ВКонтакте не ответил",
                    f"Сбой соединения ({note}).",
                    "Проверьте интернет, VPN или прокси и повторите проверку.")
    payload = data or {}
    error = payload.get("error")
    if error:
        code = error.get("error_code")
        human = _VK_ERRORS.get(code) or str(error.get("error_msg") or "неизвестная ошибка")
        return _res("vk_token", "keys", "error", "Токен ВКонтакте отклонён",
                    f"ВКонтакте ответил: {human}.",
                    "Возьмите новый токен в vkhost.github.io или в настройках приложения VK.")
    response = payload.get("response") or []
    who = ""
    if response and isinstance(response[0], dict):
        who = " ".join(str(response[0].get(k) or "") for k in ("first_name", "last_name")).strip()
    detail = "Токен работает: API принял запрос." + (f" Токен принадлежит: {who}." if who else "")
    return _res("vk_token", "keys", "ok", "Токен ВКонтакте работает", detail)


# ── Группа «files»: куда пишем ────────────────────────────────

def check_storage() -> list[dict]:
    """Папка результатов и настройки: доступны ли на запись и чтение."""
    out: list[dict] = []
    try:
        import paths
    except Exception as exc:
        return [_res("storage", "files", "error", "Не удалось определить папки приложения",
                     _exception_note(exc), "Переустановите приложение.")]

    results_dir = str(paths.results_root())
    probe = os.path.join(results_dir, ".diag-write-test")
    try:
        os.makedirs(results_dir, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        out.append(_res("results_dir", "files", "ok",
                        "Папка результатов доступна для записи", results_dir))
    except Exception as exc:
        out.append(_res("results_dir", "files", "error",
                        "В папку результатов нельзя писать",
                        f"{results_dir} — {_exception_note(exc)}",
                        "Смените папку в «Форматы вывода» → «Папка результатов» "
                        "или выдайте права на запись."))

    try:
        usage = shutil.disk_usage(results_dir)
        free = usage.free
        if free < _MIN_FREE_BYTES:
            out.append(_res("disk_free", "files", "warn", "Мало свободного места",
                            f"Свободно {_fmt_bytes(free)}.",
                            "Освободите диск: отчёты и сырые файлы занимают больше всего."))
        else:
            out.append(_res("disk_free", "files", "ok", "Свободное место",
                            f"{_fmt_bytes(free)} доступно."))
    except Exception as exc:
        out.append(_res("disk_free", "files", "warn", "Не удалось оценить свободное место",
                        _exception_note(exc)))

    try:
        settings_file = paths.settings_path()
        if not settings_file.exists():
            out.append(_res("settings", "files", "ok", "Настройки ещё не сохранены",
                            "Приложение работает на значениях по умолчанию."))
        else:
            import json
            json.loads(settings_file.read_text(encoding="utf-8"))
            out.append(_res("settings", "files", "ok", "Файл настроек читается",
                            str(settings_file)))
    except Exception as exc:
        out.append(_res("settings", "files", "warn", "Файл настроек повреждён",
                        f"settings.json не читается ({_exception_note(exc)}).",
                        "Приложение работает на значениях по умолчанию; "
                        "пресеты и шаблоны, сохранённые в файле, не подхватятся."))
    return out


# ── Группа «data»: что уже собрано ────────────────────────────

def _raw_header(path: str) -> list[str]:
    """Заголовки raw-файла (одна строка, read_only — быстро даже на больших)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            ws = wb.active
            return [str(c or "").strip() for c in next(ws.iter_rows(values_only=True))]
        finally:
            wb.close()
    except Exception:
        return []


def check_data() -> list[dict]:
    """Сколько данных собрано и понимает ли их текущая версия."""
    out: list[dict] = []
    try:
        import paths
        raw_dir = paths.raw_dir()
        proc_dir = paths.processed_dir()
    except Exception as exc:
        return [_res("data", "data", "warn", "Не удалось прочитать папки данных",
                     _exception_note(exc))]

    raw_files, raw_size = _dir_size(raw_dir, ".xlsx")
    if not raw_files:
        out.append(_res("raw_present", "data", "warn", "Сырых данных нет",
                        "Папка output/raw пуста — сначала запустите сбор.",
                        "Фильтры этапа 2 работают по сырым данным: без сбора "
                        "«Применить фильтры заново» фильтровать нечего."))
        return out

    out.append(_res("raw_present", "data", "ok", "Сырые данные на месте",
                    f"{raw_files} файл(ов), {_fmt_bytes(raw_size)}."))

    # Новые колонки: без них фильтры «🎯 Тип компании» работают частично —
    # филиалы досчитываются по сбору, а дату появления карточки взять негде.
    newest = max((os.path.join(raw_dir, f) for f in os.listdir(raw_dir)
                  if f.lower().endswith(".xlsx")),
                 key=lambda p: os.path.getmtime(p), default="")
    header = _raw_header(newest) if newest else []
    if header:
        has_branch = "Филиалов" in header
        has_added = "Добавлено" in header
        if has_branch and has_added:
            out.append(_res("raw_columns", "data", "ok", "Сбор понимает «тип компании»",
                            "В сырых файлах есть колонки «Филиалов» и «Добавлено» — "
                            "фильтры одиночек и новых работают по этим данным."))
        else:
            missing = [name for name, ok in (("Филиалов", has_branch),
                                             ("Добавлено", has_added)) if not ok]
            out.append(_res("raw_columns", "data", "warn",
                            "Сбор сделан прежней версией",
                            "В сырых файлах нет колонок: " + ", ".join(missing) + ".",
                            "Число филиалов программа досчитает сама, а даты появления "
                            "карточек появятся только после нового сбора."))

    # Готовые отчёты лежат по подпапкам форматов — считаем все вместе.
    proc_files_all = 0
    proc_size_all = 0
    for sub in ("excel", "csv", "json", "html"):
        got_files, got_size = _dir_size(os.path.join(proc_dir, sub), "")
        proc_files_all += got_files
        proc_size_all += got_size
    out.append(_res("processed", "data", "ok", "Готовые отчёты",
                    f"{proc_files_all} файл(ов), {_fmt_bytes(proc_size_all)}."))
    return out


# ── Группа «env»: с чем работаем ──────────────────────────────

# Пробная страница выдачи: сколько карточек успел отрисовать список и
# активна ли вкладка. Фоновая вкладка — частая причина «мало организаций»:
# Chrome отдаёт ей visibilityState="hidden", и виртуализованный список
# Яндекс.Карт не догружает продолжение (см. cdp_client.init_browser).
_SEARCH_PROBE_JS = (
    "JSON.stringify({cards: document.querySelectorAll('%s').length,"
    " visibility: document.visibilityState, focus: document.hasFocus()})"
)


def _search_page_probe(cdp_client, url: str, selector: str) -> dict:
    """Живой замер страницы выдачи: карточки + состояние вкладки.

    Пустой словарь — страница не ответила. Разбор вёрстки и чтение
    состояния выдачи требуют активной вкладки, поэтому её состояние —
    часть отчёта.
    """
    import json as _json
    raw = cdp_client.eval_in_page(
        url,
        _SEARCH_PROBE_JS % selector,
        wait_expr=f"document.querySelectorAll('{selector}').length > 0",
        timeout_s=60.0,
    )
    if not raw:
        return {}
    try:
        data = _json.loads(raw)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        # Ответ не объект (например просто число карточек) — читаем как счётчик
        # и оставляем строку о вкладке за кадром: врать о её состоянии нельзя.
        try:
            return {"cards": int(raw)}
        except (TypeError, ValueError):
            return {}
    try:
        cards = int(data.get("cards") or 0)
    except (TypeError, ValueError):
        cards = 0
    return {"cards": cards,
            "visibility": str(data.get("visibility") or ""),
            "focus": bool(data.get("focus"))}


# Пробный запрос живой выдачи: тот же путь, что у рабочего поиска
# (состояние страницы → карточки), поэтому проверка ловит и «выдача пуста».
_PROBE_QUERY = ("кофейня", "Уфа")


def _live_search_rows() -> list[dict]:
    """Строка «Поиск нашёл организации» — живой сбор на боевом пути.

    Координаты не задаются: страницу поиска открывает сам Яндекс.Карты
    и показывает ближайшие к городу организации. Проверяем главное —
    выдача возвращается и парсится.
    """
    from yandex_maps_parser.browser_search import harvest_cards
    try:
        cards = harvest_cards(_PROBE_QUERY[0], _PROBE_QUERY[1], None, None, max_cards=25)
    except Exception as exc:
        return [_res("search_live", "engines", "error", "Поиск не выполнился",
                     _exception_note(exc),
                     "Проверьте доступ в интернет и запустите проверку ещё раз.")]
    count = len(cards)
    where = f"запрос «{_PROBE_QUERY[0]}», город {_PROBE_QUERY[1]}"
    if count:
        first = str(cards[0].get("name") or "")
        return [_res("search_live", "engines", "ok", "Поиск находит организации",
                     f"{where}: {count} организаций" + (f", первая — «{first}»" if first else "") + ".")]
    return [_res("search_live", "engines", "warn", "Поиск вернул пустую выдачу",
                 f"{where}: ни одной организации.",
                 "Проверьте доступ в интернет и попробуйте ещё раз. Если пусто"
                 " всегда — напишите автору: Яндекс мог изменить страницу выдачи.")]


def _tab_activity_rows(probe: dict, cards: int) -> list[dict]:
    """Строка о вкладке браузера: видна ли она и в фокусе ли.

    Пустой список — состояние вкладки прочитать не удалось: тогда лучше
    промолчать, чем показать выдуманное «всё хорошо».
    """
    visibility = str(probe.get("visibility") or "")
    if not visibility:
        return []
    active = visibility == "visible" and bool(probe.get("focus"))
    if active:
        return [_res("tab_active", "engines", "ok", "Вкладка браузера активна",
                     f"visibilityState={visibility}, фокус есть; карточек в выдаче: {cards}.")]
    return [_res("tab_active", "engines", "warn", "Вкладка браузера считается фоновой",
                 f"visibilityState={visibility}, фокуса нет; карточек в выдаче: {cards}.",
                 "Список организаций в такой вкладке не догружается: Яндекс отдаёт"
                 " только первые карточки. Обновите приложение — в текущей сборке"
                 " вкладке включается эмуляция активной страницы.")]


def probe_engines(deep: bool = False) -> list[dict]:
    """Проверка браузера — единственного способа загрузки страниц в приложении.

    deep=False — мгновенно (есть ли бинарник): для панели «Диагностика».
    deep=True  — пробная загрузка карточки организации и страницы поиска.

    Отчёт — те же _res-строки: {id, status: ok|warn|error, title, detail}.
    """
    out: list[dict] = []
    # Пробная страница: реальная карточка организации на Яндекс.Картах —
    # та же геометрия ответа, что у боевых fetch_detail.
    probe_url = "https://yandex.ru/maps/org/galateya/1025935617/"
    search_url = "https://yandex.ru/maps/?text=%D0%BA%D0%BE%D1%84%D0%B5%20%D0%A3%D1%84%D0%B0"
    from yandex_maps_parser.browser_search import CARD_SELECTOR

    try:
        from yandex_maps_parser import cdp_client
        chrome = cdp_client._find_chrome()
        if not chrome:
            out.append(_res(
                "engine_cdp", "engines", "error", "Браузер не найден",
                "Chrome, Chromium и Edge не обнаружены на этой машине.",
                "Установите Google Chrome: приложение работает только через"
                " настоящий браузер — прямые HTTP-запросы к Яндекс.Картам"
                " убраны из-за антибота."))
        elif deep:
            # Идёт прогон — браузер уже поднят: свою пробу делаем в нём же,
            # но чужой браузер не закрываем ни при каких условиях.
            already_running = cdp_client.is_available()
            ok = cdp_client.init_browser(pool_size=1, visible=False)
            card = cdp_client.fetch_page(probe_url) if ok else None
            card_ok = bool(card) and len(card) >= 800
            probe = _search_page_probe(cdp_client, search_url, CARD_SELECTOR) if ok else {}
            # Живой сбор идёт последним: он ходит на страницу выдачи сам.
            live_rows = _live_search_rows() if ok else []
            if not already_running:
                cdp_client.close_browser()
            cards = int(probe.get("cards") or 0)
            status = "ok" if (card_ok and cards > 0) else "warn"
            detail = (chrome + f"; карточка {len(card or '')} байт, карточек в выдаче: {cards}.")
            if status == "warn":
                hint = ("Браузер есть, но страницу не отдал: проверьте интернет и"
                        " попробуйте ещё раз." if card_ok else
                        "Браузер есть, но карточку не загрузил — проверьте доступ в интернет.")
            else:
                hint = ""
            out.append(_res("engine_cdp", "engines", status,
                            "Браузер (Chrome CDP): " + ("работает" if status == "ok" else "с проблемой"),
                            detail, hint))
            out.extend(_tab_activity_rows(probe, cards))
            out.extend(live_rows)
        else:
            out.append(_res("engine_cdp", "engines", "ok",
                            "Браузер (Chrome CDP) найден", chrome))
    except Exception as exc:
        out.append(_res("engine_cdp", "engines", "error",
                        "Браузер (Chrome CDP): сбой проверки", _exception_note(exc)))
    return out


def check_environment() -> list[dict]:
    """Версия, окружение и браузер для докачки соцсетей с карточек."""
    out: list[dict] = []
    import sys

    version = "неизвестна"
    frozen = False
    try:
        from config import APP_VERSION, is_dev_build
        version = APP_VERSION
        frozen = not is_dev_build()
    except Exception:
        pass
    mode = "сборка для пользователя" if frozen else "запуск из исходников"
    out.append(_res("app_version", "env", "ok", f"Версия {version}",
                    f"{mode}, Python {sys.version.split()[0]}."))

    # Браузер — основной инструмент приложения: из него берутся и выдача
    # поиска, и координаты города, и карточки организаций.
    browser = ""
    try:
        from yandex_maps_parser import cdp_client
        browser = cdp_client._find_chrome() or ""
    except Exception:
        browser = ""
    if browser:
        out.append(_res("browser", "env", "ok", "Браузер для докачки соцсетей найден",
                        browser))
    else:
        out.append(_res("browser", "env", "error", "Браузер не найден",
                        "Chrome, Chromium и Edge не обнаружены на этой машине.",
                        "Установите Google Chrome: без него приложение не может"
                        " читать Яндекс.Карты — других способов загрузки нет."))

    # severity: core — без этого приложение не работает вообще.
    for module, label, severity, hint, advice in (
        ("websocket", "websocket-client", "error",
         "Без него не работает управление браузером (Chrome DevTools Protocol) —"
         " значит, не работают ни поиск, ни карточки организаций.",
         "Установите зависимость проекта: pip install -r requirements.txt"),
        ("openpyxl", "openpyxl", "error",
         "Без него не читаются и не сохраняются Excel-файлы, а этап 2 работает именно с ними.",
         "Переустановите приложение: зависимости ставятся вместе с ним."),
        ("httpx", "httpx", "warn",
         "Без него не работает панель «Диагностика» (проверка токена ВК).",
         "Переустановите приложение: зависимости ставятся вместе с ним."),
    ):
        try:
            import importlib.util
            found = importlib.util.find_spec(module) is not None
        except Exception:
            found = False
        if not found:
            out.append(_res(f"dep_{module}", "env", severity,
                            f"Не найден модуль {label}", hint, advice))
    return out


# ── Доступ: панель запускает только сам интерфейс ─────────────

def _is_local_origin(origin: str) -> bool:
    """Origin нашего же интерфейса: localhost/127.0.0.1/[::1] на любом порту."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


@bp.before_request
def _only_from_our_ui():
    """Пускаем только запрос из самого приложения.

    Приложение слушает 127.0.0.1, но привязкой к адресу ограничиться нельзя:
    любой сайт в браузере может отправить POST на localhost «простым»
    запросом (обычная HTML-форма — без CORS-preflight) и запустить проверку
    или иные действия от имени пользователя. Поэтому требуем тело в JSON:
    такой запрос чужая страница без preflight отправить не может, а preflight
    мы не разрешаем (ответных CORS-заголовков у сервиса нет).
    """
    if request.method != "POST":
        return None
    origin = request.headers.get("Origin")
    if origin and not _is_local_origin(origin):
        return jsonify({"ok": False, "results": [],
                        "error": "Запрос пришёл с другого сайта — проверка не запущена."}), 403
    if not request.is_json:
        return jsonify({"ok": False, "results": [],
                        "error": "Диагностика принимает только JSON-запрос из самого приложения."}), 415
    return None


# ── Сборка отчёта ─────────────────────────────────────────────

def run_checks(groups=None, deep: bool = False) -> list[dict]:
    """Отчёт по выбранным группам. Падение одной проверки — строка «ошибка».

    deep=True включает живую пробу браузера (группа «engines»): она открывает
    настоящий Chrome и грузит страницу выдачи, поэтому запускается отдельной
    кнопкой, а не вместе с мгновенными проверками.
    """
    wanted = [g for g in (groups or GROUPS) if g in GROUPS] or list(GROUPS)
    results: list[dict] = []

    def _safe(cid: str, group: str, fn, *args) -> None:
        try:
            got = fn(*args)
        except Exception as exc:  # одна сломанная проверка не рушит отчёт
            results.append(_res(cid, group, "error", "Проверка не выполнилась",
                                _exception_note(exc)))
            return
        results.extend(got if isinstance(got, list) else [got])

    if "keys" in wanted:
        keys = effective_keys()
        _safe("vk_token", "keys", check_vk_token, keys["vk"])
    if "files" in wanted:
        _safe("storage", "files", check_storage)
    if "data" in wanted:
        _safe("data", "data", check_data)
    if "env" in wanted:
        _safe("env", "env", check_environment)
    if "engines" in wanted:
        _safe("engines", "engines", probe_engines, bool(deep))

    order = {"error": 0, "warn": 1, "ok": 2}
    return sorted(results, key=lambda r: order.get(r["status"], 3))


@bp.route("/engines/status", methods=["GET"])
def engines_status():
    """Мгновенная доступность браузера для бейджа в форме.

    Без сетевых запросов: только поиск бинарника Chrome/Chromium.
    Reply: {ok, chrome: bool, chrome_path: str, frozen: bool}
    """
    chrome_path = ""
    try:
        from yandex_maps_parser import cdp_client
        chrome_path = cdp_client._find_chrome() or ""
    except Exception:
        chrome_path = ""
    try:
        import sys as _sys
        frozen = bool(getattr(_sys, "frozen", False))
    except Exception:
        frozen = False
    return jsonify({"ok": True, "chrome": bool(chrome_path),
                    "chrome_path": chrome_path, "frozen": frozen})


@bp.route("/diagnostics/run", methods=["POST"])
def diagnostics_run():
    """Самопроверка по кнопке.

    Body: {"groups": ["keys", "files", "data", "env"]} — по умолчанию все.
    "deep": true — живая проба браузера (открывает Chrome, грузит страницу
    выдачи и проверяет, что вкладка активна и список организаций виден).
    Reply: {ok, results: [{id, group, status, title, detail, hint}], ts}

    Ответ не содержит ключей: только булевы признаки и объяснения словами.
    """
    data = request.get_json(silent=True) or {}
    groups = data.get("groups")
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, list):
        groups = None
    deep = bool(data.get("deep"))
    try:
        results = run_checks(groups, deep=deep)
    except Exception as exc:            # аварийный случай: панель всё равно отвечает
        return jsonify({"ok": False, "error": f"Диагностика не смогла выполниться: {_exception_note(exc)}",
                        "results": []}), 200
    return jsonify({"ok": True, "results": results, "ts": int(time.time())})
