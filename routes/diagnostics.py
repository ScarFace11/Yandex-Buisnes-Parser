"""🩺 Диагностика: самопроверка приложения без чтения логов."""
import io
import json
import os
import re
import shutil
import time

from flask import Blueprint, Response, jsonify, request

from .json_body import json_body

bp = Blueprint("diagnostics", __name__)

# Группы проверок: раздельно, потому что «ключи» стоят квоту и время, а «файлы/данные/окружение» — бесплатны и мгновенны.
GROUPS = ("keys", "files", "data", "runs", "env", "engines")

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
    """Ключи, которыми реально пользуется запуск."""
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
    """Короткое описание сбоя БЕЗ текста исключения."""
    return type(exc).__name__


def _http_get(url: str, params: dict) -> tuple[int, str, dict | None, str]:
    """GET → (код, тело, json|None, примечание)."""
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
    """Текст ошибки сервиса человеческим языком — и без лишнего мусора."""
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

    # Новые колонки: без них фильтры «🎯 Тип компании» работают частично — филиалы досчитываются по сбору, а дату появления карточки взять негде.
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


# ── Группа «runs»: что было в прошлых запусках ───────────────

def _fmt_when(ts) -> str:
    """«17.10.2026 14:32» из unix-time; мусор — прочерк, а не исключение."""
    try:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(float(ts)))
    except Exception:
        return "—"


def _fmt_span(seconds) -> str:
    """Длительность словами: «48 с», «2 мин 10 с», «1 ч 05 мин»."""
    try:
        total = int(float(seconds))
    except Exception:
        return ""
    if total <= 0:
        return ""
    if total < 60:
        return f"{total} с"
    if total < 3600:
        return f"{total // 60} мин {total % 60:02d} с" if total % 60 else f"{total // 60} мин"
    return f"{total // 3600} ч {total % 3600 // 60:02d} мин"


def check_runs() -> list[dict]:
    """Что было в прошлых прогонах: когда, где и чем закончилось."""
    out: list[dict] = []
    try:
        import search_history
        runs = search_history.get_history(5)
    except Exception as exc:
        return [_res("runs", "runs", "warn", "История прогонов не читается",
                     _exception_note(exc),
                     "На сбор это не влияет — история нужна только для списка "
                     "прогонов и подписей сфер.")]

    if not runs:
        out.append(_res("runs_recent", "runs", "warn", "Прогонов ещё не было",
                        "История пуста: приложение ещё ни разу не запускало сбор.",
                        "Запустите поиск — здесь появятся дата, города и число "
                        "найденных организаций."))
    else:
        last = runs[0] or {}
        cities = [c for c in (last.get("cities") or []) if c]
        where = ", ".join(cities[:3])
        if len(cities) > 3:
            where += f" +{len(cities) - 3}"
        found = int(last.get("results_count") or 0)
        span = _fmt_span(last.get("elapsed_sec"))
        detail = (f"{_fmt_when(last.get('timestamp'))}: {where or 'города не записаны'}"
                  f" · {found} организаций" + (f" · заняло {span}" if span else ""))
        out.append(_res("runs_recent", "runs", "ok", "Последний прогон", detail,
                        "Если дата давняя, данные в выгрузке устарели — соберите заново."))

        failed = [r for r in runs
                  if str(r.get("status") or "").lower() in ("failed", "error", "interrupted")]
        if failed:
            out.append(_res("runs_errors", "runs", "warn",
                            "В истории есть незавершённые прогоны",
                            f"{len(failed)} из последних {len(runs)} закончились не штатно.",
                            "Откройте «Логи запусков»: там причина каждого сбора, "
                            "а повторный запуск продолжит с места остановки."))
        else:
            out.append(_res("runs_errors", "runs", "ok", "История прогонов без сбоев",
                            f"Последние {len(runs)} запусков завершились штатно." if len(runs) > 1
                            else "Единственный запуск завершился штатно."))

    # Кэш карточек: страницы организаций живут сутки и заметно ускоряют повторный сбор.
    try:
        import paths
        cache_dir = os.path.join(paths.output_dir(), ".cache")
        files, size = _dir_size(cache_dir, "")
        if files:
            out.append(_res("page_cache", "runs", "ok", "Кэш карточек",
                            f"{files} файл(ов), {_fmt_bytes(size)} — повторный сбор "
                            "по тем же городам пойдёт быстрее."))
        else:
            out.append(_res("page_cache", "runs", "ok", "Кэш карточек пуст",
                            "Это нормально до первого сбора: карточки организаций "
                            "кэшируются на сутки."))
    except Exception as exc:
        out.append(_res("page_cache", "runs", "warn", "Кэш карточек не проверен",
                        _exception_note(exc)))
    return out


# ── Группа «env»: с чем работаем ──────────────────────────────

# Пробная страница выдачи: сколько карточек успел отрисовать список и активна ли вкладка.
_SEARCH_PROBE_JS = (
    "JSON.stringify({cards: document.querySelectorAll('%s').length,"
    " visibility: document.visibilityState, focus: document.hasFocus()})"
)


def _search_page_probe(cdp_client, url: str, selector: str) -> dict:
    """Живой замер страницы выдачи: карточки + состояние вкладки."""
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
        # Ответ не объект (например просто число карточек) — читаем как счётчик и оставляем строку о вкладке за кадром: врать о её состоянии нельзя.
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


# Пробный запрос живой выдачи: тот же путь, что у рабочего поиска (состояние страницы → карточки), поэтому проверка ловит и «выдача пуста».
_PROBE_QUERY = ("кофейня", "Уфа")


def _live_search_rows() -> list[dict]:
    """Строка «Поиск нашёл организации» — живой сбор на боевом пути."""
    from yandex_maps_parser.browser_search import harvest_cards
    try:
        cards = harvest_cards(_PROBE_QUERY[0], _PROBE_QUERY[1], None, None, max_cards=25)
    except Exception as exc:
        return [_res("search_live", "engines", "error", "Поиск не выполнился",
                     _exception_note(exc),
                     "Проверьте доступ в интернет и запустите проверку ещё раз.")]
    count = len(cards)
    where = f"запрос «{_PROBE_QUERY[0]}», город {_PROBE_QUERY[1]}"
    try:
        from yandex_maps_parser import browser_search as _bs
        blocked = _bs.blocked_reason()
    except Exception:
        blocked = ""
    if blocked == "captcha":
        # Самая частая причина «пусто всегда» — проверка Яндекса; совет про интернет и «Яндекс изменил страницу» тут только путал.
        return [_res("search_live", "engines", "warn",
                     "Яндекс показал проверку «Вы не робот?»",
                     f"{where}: вместо выдачи — страница проверки, организаций нет.",
                     "Браузер и интернет при этом работают. Повторите проверку "
                     "через несколько минут; если повторяется — обновите приложение.")]
    if count:
        first = str(cards[0].get("name") or "")
        return [_res("search_live", "engines", "ok", "Поиск находит организации",
                     f"{where}: {count} организаций" + (f", первая — «{first}»" if first else "") + ".")]
    return [_res("search_live", "engines", "warn", "Поиск вернул пустую выдачу",
                 f"{where}: ни одной организации.",
                 "Проверьте доступ в интернет и попробуйте ещё раз. Если пусто"
                 " всегда — напишите автору: Яндекс мог изменить страницу выдачи.")]


def _tab_activity_rows(probe: dict, cards: int) -> list[dict]:
    """Строка о вкладке браузера: видна ли она и в фокусе ли."""
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
    """Проверка браузера — единственного способа загрузки страниц в приложении. deep=False — мгновенно (есть ли бинарник): для панели «Диагностика». deep=True — пробная загрузка карточки организации и страницы поиска."""
    out: list[dict] = []
    # Пробная страница: реальная карточка организации на Яндекс.Картах — та же геометрия ответа, что у боевых fetch_detail.
    probe_url = "https://yandex.ru/maps/org/galateya/1025935617/"
    search_url = "https://yandex.ru/maps/?text=%D0%BA%D0%BE%D1%84%D0%B5%20%D0%A3%D1%84%D0%B0"
    from yandex_maps_parser.browser_search import CARD_SELECTOR

    try:
        from yandex_maps_parser import cdp_client
        binfo = cdp_client.browser_info()
        chrome = binfo["path"]
        _browser_name = binfo["name"] or "браузер на Chromium"
        if not chrome:
            # Прямо говорим, что подойдёт: под Chrome тут понимается любой Chromium-браузер, и Яндекс Браузер с Firefox уже могут стоять.
            _unsupported = binfo.get("unsupported") or []
            out.append(_res(
                "engine_cdp", "engines", "error", "Браузер на Chromium не найден",
                "Не найдены Chrome, Chromium, Edge, Яндекс Браузер, Brave и"
                " другие Chromium-браузеры."
                + (f" Найдены {', '.join(_unsupported)} — они не умеют Chrome"
                   " DevTools Protocol, которым приложение открывает страницы."
                   if _unsupported else ""),
                "Поставьте Яндекс Браузер, Google Chrome, Microsoft Edge, Brave"
                " или Chromium: страницы открывает настоящий браузер — прямые"
                " HTTP-запросы к Яндекс.Картам убраны из-за антибота."))
        elif deep:
            # Идёт прогон — браузер уже поднят: свою пробу делаем в нём же, но чужой браузер не закрываем ни при каких условиях.
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
                            f"{_browser_name} (Chromium CDP): "
                            + ("работает" if status == "ok" else "с проблемой"),
                            detail, hint))
            out.extend(_tab_activity_rows(probe, cards))
            out.extend(live_rows)
        else:
            out.append(_res("engine_cdp", "engines", "ok",
                            f"Браузер найден: {_browser_name}", chrome))
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

    # Браузер — основной инструмент приложения: из него берутся и выдача поиска, и координаты города, и карточки организаций.
    browser = ""
    browser_name = ""
    unsupported: list[str] = []
    try:
        from yandex_maps_parser import cdp_client
        _bi = cdp_client.browser_info()
        browser = _bi["path"]
        browser_name = _bi["name"]
        unsupported = _bi.get("unsupported") or []
    except Exception:
        browser = ""
    if browser:
        out.append(_res("browser", "env", "ok",
                        f"Браузер для сбора найден: {browser_name}", browser))
    else:
        out.append(_res("browser", "env", "error", "Браузер на Chromium не найден",
                        "Не найдены Chrome, Chromium, Edge, Яндекс Браузер, Brave."
                        + (f" Найдены {', '.join(unsupported)} — они не умеют CDP."
                           if unsupported else ""),
                        "Поставьте Яндекс Браузер, Chrome, Edge, Brave или"
                        " Chromium: без такого браузера приложение не может читать"
                        " Яндекс.Карты — других способов загрузки нет."))

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
    """Пускаем только запрос из самого приложения."""
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
    """Отчёт по выбранным группам."""
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
    if "runs" in wanted:
        _safe("runs", "runs", check_runs)
    if "env" in wanted:
        _safe("env", "env", check_environment)
    if "engines" in wanted:
        _safe("engines", "engines", probe_engines, bool(deep))

    order = {"error": 0, "warn": 1, "ok": 2}
    return sorted(results, key=lambda r: order.get(r["status"], 3))


@bp.route("/engines/status", methods=["GET"])
def engines_status():
    """Мгновенная доступность браузера для бейджа в форме."""
    chrome_path = ""
    browser_name = ""
    unsupported: list[str] = []
    _bi: dict = {}
    try:
        from yandex_maps_parser import cdp_client
        _bi = cdp_client.browser_info()
        chrome_path = _bi["path"]
        browser_name = _bi["name"]
        unsupported = _bi.get("unsupported") or []
    except Exception:
        chrome_path = ""
    try:
        import sys as _sys
        frozen = bool(getattr(_sys, "frozen", False))
    except Exception:
        frozen = False
    return jsonify({"ok": True, "chrome": bool(chrome_path),
                    "chrome_path": chrome_path, "frozen": frozen,
                    # Под «Chrome» бейдж понимает любой Chromium-браузер: имя видно пользователю, а unsupported объясняет, почему установленный Firefox/Safari поиску не помогает.
                    "browser_name": browser_name,
                    "unsupported": unsupported,
                    # Выбор браузера для сбора: список найденных и текущий выбор.
                    "browsers": _bi.get("browsers") or [] if chrome_path else [],
                    "selected": _bi.get("selected") or ""})


@bp.route("/browser/select", methods=["POST"])
def browser_select():
    """Сохранить выбранный браузер для сбора."""
    from flask import current_app
    try:
        from yandex_maps_parser import cdp_client
        index = {b["path"].lower(): b for b in cdp_client.available_browsers()}
    except Exception:
        index = {}

    data = json_body()
    path = str(data.get("path") or "").strip()
    if path and path.lower() not in index:
        return jsonify({"ok": False,
                        "error": "Этот браузер не найден на диске — обновите список",
                        "browsers": list(index.values())}), 400

    try:
        import paths as _paths
        _paths.save_settings({"browser_path": path})
    except Exception as exc:
        current_app.logger.warning("browser/select: настройка не сохранилась: %s", exc)

    try:
        cdp_client.set_browser(path)
        info = cdp_client.browser_info()
    except Exception:
        info = {"name": "", "path": path}
    return jsonify({"ok": True, "selected": path,
                    "name": (index.get(path.lower()) or {}).get("name", "") if path else "",
                    "active": info.get("name") or "",
                    "browsers": list(index.values())})


@bp.route("/diagnostics/run", methods=["POST"])
def diagnostics_run():
    """Самопроверка по кнопке."""
    data = json_body()
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


# ═══════════════════════════════════════════════════════════════
#  Сообщить о проблеме: контекст для issue на GitHub

_REPORT_LOG_LINES = 25          # хвост лога в контекст issue


def _report_log_tail() -> str:
    """Последние строки последнего лога — или объяснение, почему их нет."""
    try:
        import run_logger
        logs = run_logger.list_logs()
        if not logs:
            return "(логов пока нет)"
        path = os.path.join(run_logger.LOGS_DIR, logs[0]["name"])
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        tail = [ln.rstrip() for ln in lines[-_REPORT_LOG_LINES:]]
        return "\n".join(tail) or "(лог пуст)"
    except Exception as exc:
        return f"(хвост лога не прочитан: {_exception_note(exc)})"


@bp.route("/report/context", methods=["GET"])
def report_context():
    """Контекст для issue: версия, система, браузер, прогоны, хвост лога."""
    parts: list[str] = []
    try:
        rows = run_checks(["env", "runs"])
        for group, title in (("env", "Версия, система и браузер"),
                             ("runs", "Прогоны и кэш")):
            lines = [f"## {title}"]
            for r in rows:
                if r.get("group") != group:
                    continue
                mark = {"ok": "✔", "warn": "⚠", "error": "✖"}.get(r.get("status"), "·")
                line = f"{mark} {r.get('title') or ''}"
                if r.get("detail"):
                    line += f" — {r['detail']}"
                lines.append(line)
            parts.append("\n".join(lines))
    except Exception as exc:
        parts.append(f"## Проверки\r\n(не выполнились: {_exception_note(exc)})")

    # Пресеты — только имена: содержимое пресета может содержать личные формулировки запросов, а issue бывает публичным.
    try:
        import paths
        presets = paths.load_settings().get("presets") or []
        names = [str(p.get("name") or "").strip() for p in presets
                 if isinstance(p, dict)]
        names = [n for n in names if n]
        parts.append("## Сохранённые пресеты\r\n"
                     + ("\n".join(f"- {n}" for n in names) if names else "(пресетов нет)"))
    except Exception:
        parts.append("## Сохранённые пресеты\r\n(не прочитаны)")

    parts.append("## Последние строки лога\r\n```\r\n" + _report_log_tail() + "\r\n```")
    # Признаки булевы, токен в ответ не попадает никогда. can_device — есть ли в сборке client_id: без него окно не показывает кнопку входа, чтобы пользователю не предлагали создавать OAuth-приложение.
    return jsonify({"ok": True, "context": "\n\n".join(parts),
                    "has_token": bool(github_token()),
                    "can_device": bool(github_oauth_client_id()),
                    "ts": int(time.time())})


# Настройки, которые сбрасываются «до стандартных». Ценное НЕ трогаем:
_SETTINGS_RESET_KEYS = ("results_root", "raw_dir", "processed_dir",
                        "archive_dir", "browser_path", "retention_days")


@bp.route("/settings/reset", methods=["POST"])
def settings_reset():
    """Сброс настроек до стандартных: папки результатов, браузер, хранение."""
    try:
        import paths
        data = paths.load_settings()
        dropped = [k for k in _SETTINGS_RESET_KEYS if k in data]
        kept = sorted(set(data) - set(dropped))
        for key in _SETTINGS_RESET_KEYS:
            data.pop(key, None)
        paths.replace_settings(data)
        paths.refresh_output_dirs()
    except Exception as exc:
        return jsonify({"ok": False,
                        "error": f"Сброс не выполнился: {_exception_note(exc)}"}), 500
    return jsonify({"ok": True, "reset": dropped, "kept": kept})


# ═══════════════════════════════════════════════════════════
#  Отправка issue через GitHub API (необязательный токен)

_ISSUE_TIMEOUT = 20.0                 # GitHub отвечает за секунды
ISSUE_TITLE_MAX = 256
ISSUE_BODY_MAX = 60000                # лимит GitHub — 65536
ISSUE_LABELS_MAX = 10


def github_token() -> str:
    """Токен GitHub из окружения (.env); пустая строка — токена нет."""
    return (os.environ.get("GITHUB_TOKEN") or "").strip()


def _github_create_issue(title: str, labels: list, body: str,
                         token: str) -> tuple[int, dict | None, str]:
    """Создать issue → (код, json|None, примечание о сбое сети)."""
    import httpx
    try:
        from routes.api import GITHUB_REPO
        repo = GITHUB_REPO
    except Exception:
        repo = "ScarFace11/Yandex-Buisnes-Parser"
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        r = httpx.post(f"https://api.github.com/repos/{repo}/issues",
                       json=payload, headers=headers, timeout=_ISSUE_TIMEOUT)
    except Exception as exc:
        return 0, None, _exception_note(exc)
    try:
        data = r.json()
    except Exception:
        data = None
    return r.status_code, (data if isinstance(data, dict) else None), ""


def _remember_github_token(token: str) -> tuple[bool, str]:
    """Сохранить токен в .env (GITHUB_TOKEN) — туда же, куда ключи API."""
    try:
        from routes.api import _write_env_keys
        resp = _write_env_keys({"GITHUB_TOKEN": token})
        if isinstance(resp, tuple):        # jsonify(…), 400
            resp = resp[0]
        data = resp.get_json() or {}
    except Exception as exc:
        return False, type(exc).__name__
    if data.get("ok"):
        return True, ""
    return False, str(data.get("error") or "")


def _issue_error(status: int, data: dict | None, note: str) -> str:
    """Причина отказа GitHub человеческим языком — без технического мусора."""
    detail = _error_message("", data)
    tail = f": {detail}" if detail else ""
    if status == 0:
        return f"Сеть недоступна ({note or 'соединение не установлено'})"
    if status == 401:
        return ("GitHub отклонил токен (401) — войдите в GitHub заново "
                "или проверьте GITHUB_TOKEN в .env")
    if status == 403:
        if "rate limit" in detail.lower():
            return ("GitHub отклонил запрос (403): превышен лимит анонимных "
                    "запросов — 60 в час, нужен токен")
        return f"GitHub отклонил запрос (403) — у токена нет прав на issue{tail}"
    if status == 404:
        return "GitHub не нашёл репозиторий или у токена нет к нему доступа (404)"
    if status == 422:
        return f"GitHub не принял данные (422){tail}"
    return f"GitHub ответил {status}{tail}"


@bp.route("/report/issue", methods=["POST"])
def report_issue():
    """Создать issue на GitHub через API — кнопка «Создать issue»."""
    data = json_body()
    title = str(data.get("title") or "").strip() or "Сообщение из приложения"
    title = title[:ISSUE_TITLE_MAX]
    body = str(data.get("body") or "")[:ISSUE_BODY_MAX]
    raw_labels = data.get("labels")
    labels = [str(x).strip() for x in (raw_labels if isinstance(raw_labels, list) else [])
              if isinstance(x, str) and x.strip()][:ISSUE_LABELS_MAX]

    sent = str(data.get("token") or "").strip()
    token = sent or github_token()
    saved = False
    save_note = ""
    if sent and data.get("remember"):
        saved, save_note = _remember_github_token(sent)

    if not token:
        # Поле токена в окне больше нет: если вход по коду в этой сборке возможен — предлагаем его, иначе сразу заполненную форму.
        how = ("войдите в GitHub по коду или "
               if github_oauth_client_id() else "")
        return jsonify({
            "ok": False, "code": "no_token", "status": 0,
            "error": "Токен GitHub не задан, а через API issue не создаётся "
                     "(GitHub требует аутентификацию) — " + how
                     + "откройте заполненную форму",
        })

    status, payload, net_note = _github_create_issue(title, labels, body, token)
    if status == 201 and payload:
        out = {"ok": True, "url": str(payload.get("html_url") or ""),
               "number": payload.get("number"), "saved": saved}
        if save_note:
            out["save_warning"] = save_note
        return jsonify(out)
    return jsonify({"ok": False, "code": "github", "status": status,
                    "error": _issue_error(status, payload, net_note)})


# ── Вход в GitHub без ручного ввода токена: device flow ─────

GH_DEVICE_CODE_URL = "https://github.com/login/device/code"
GH_DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"
GH_DEVICE_AUTH_URL = "https://github.com/login/device"
# public_repo — минимум прав для создания issue в публичном репозитории; полный «repo» просить у пользователя непропорционально.
GH_DEVICE_SCOPE = "public_repo"

# client_id OAuth-приложения проекта — зашивается в релизную сборку (одна строка, которую владелец заполняет при выпуске).
GH_DEVICE_CLIENT_ID_DEFAULT = "Ov23lik2gXnfcFfKtRf0"


def github_oauth_client_id() -> str:
    """client_id OAuth-приложения: окружение (.env) → зашитое значение."""
    env = (os.environ.get("GITHUB_OAUTH_CLIENT_ID") or "").strip()
    return env or str(GH_DEVICE_CLIENT_ID_DEFAULT or "").strip()


def _gh_form_post(url: str, data: dict) -> tuple[int, dict | None, str]:
    """POST form → (код, json|None, примечание о сбое сети)."""
    import httpx
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    try:
        r = httpx.post(url, data=data, headers=headers, timeout=_ISSUE_TIMEOUT)
    except Exception as exc:
        return 0, None, _exception_note(exc)
    try:
        payload = r.json()
    except Exception:
        payload = None
    return r.status_code, (payload if isinstance(payload, dict) else None), ""


@bp.route("/report/github/device/start", methods=["POST"])
def github_device_start():
    """Начать device flow: выдать код пользователю."""
    client_id = github_oauth_client_id()
    if not client_id:
        return jsonify({
            "ok": False, "code": "no_client_id", "status": 0,
            "error": "Вход по коду не настроен: в этой сборке не указан "
                     "client_id проекта (GITHUB_OAUTH_CLIENT_ID или "
                     "GH_DEVICE_CLIENT_ID_DEFAULT в routes/diagnostics.py). "
                     "Сообщение можно отправить заполненной формой.",
        })
    status, data, note = _gh_form_post(GH_DEVICE_CODE_URL, {
        "client_id": client_id,
        "scope": GH_DEVICE_SCOPE,
    })
    if status != 200 or not data or not data.get("device_code"):
        return jsonify({"ok": False, "code": "network" if status == 0 else "github",
                        "status": status,
                        "error": note or _issue_error(status, data, note)})
    return jsonify({
        "ok": True,
        "device_code": str(data.get("device_code") or ""),
        "user_code": str(data.get("user_code") or ""),
        "verification_uri": str(data.get("verification_uri") or GH_DEVICE_AUTH_URL),
        "interval": max(1, int(data.get("interval") or 5)),
        "expires_in": max(60, int(data.get("expires_in") or 900)),
    })


@bp.route("/report/github/device/poll", methods=["POST"])
def github_device_poll():
    """Проверить, подтвердил ли пользователь код на GitHub."""
    data = json_body()
    client_id = github_oauth_client_id()
    device_code = str(data.get("device_code") or "")
    if not client_id or not device_code:
        return jsonify({"ok": False, "code": "bad_request",
                        "error": "Нет client_id или device_code — начните вход заново."})
    status, out, note = _gh_form_post(GH_DEVICE_TOKEN_URL, {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    })
    if status == 0:
        return jsonify({"ok": False, "code": "network",
                        "error": f"Сеть недоступна ({note or 'соединение не установлено'})"})
    if not out:
        return jsonify({"ok": False, "code": "github", "status": status,
                        "error": _issue_error(status, None, note)})
    err = str(out.get("error") or "")
    if err == "authorization_pending":
        return jsonify({"ok": False, "pending": True})
    if err == "slow_down":
        return jsonify({"ok": False, "pending": True, "slow_down": True})
    if err == "expired_token":
        return jsonify({"ok": False, "code": "expired_token",
                        "error": "Время кода вышло — начните вход заново."})
    if err == "access_denied":
        return jsonify({"ok": False, "code": "access_denied",
                        "error": "Доступ отклонён на странице GitHub."})
    token = str(out.get("access_token") or "")
    if not token:
        return jsonify({"ok": False, "code": "github", "status": status,
                        "error": _issue_error(status, out, note)})
    saved, save_note = _remember_github_token(token)
    # Токен уже живёт в .env и в окружении процесса (_write_env_keys перезагружает его без перезапуска) — «Создать issue» работает сразу.
    out = {"ok": True, "saved": saved}
    if save_note:
        out["save_warning"] = save_note
    return jsonify(out)


# ── Экспорт настроек (перенос на другую машину) ─────────────

BROWSER_SETTINGS_MAX = 500
BROWSER_VALUE_MAX = 1_000_000


def clean_browser_settings(raw) -> dict:
    """Снимок localStorage → только {yp_*: str} в разумных пределах."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key, value in raw.items():
        if len(out) >= BROWSER_SETTINGS_MAX:
            break
        k = str(key)
        if not k.startswith("yp_") or not isinstance(value, str):
            continue
        out[k] = value[:BROWSER_VALUE_MAX]
    return out


@bp.route("/settings/export", methods=["POST"])
def settings_export():
    """Zip со всеми настройками — перенос на другую машину до сброса."""
    data = json_body()
    browser = clean_browser_settings(data.get("browser"))
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        try:
            from paths import settings_path
            sp = settings_path()
            if sp.exists():
                zf.write(str(sp), "settings.json")
        except Exception:
            pass
        if browser:
            zf.writestr("browser.json", json.dumps(browser, ensure_ascii=False))
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition":
                             "attachment; filename=parser-settings-export.zip"})
