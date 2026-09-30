"""🩺 Диагностика: самопроверка приложения без чтения логов.

Зачем это нужно. Приложение — десктопное: у пользователя нет консоли перед
глазами, и почти все обращения «ничего не работает» сводятся к четырём
причинам: ключ не тот или исчерпан, нет прав на папку результатов, сбор
сделан старой версией (в raw нет новых колонок) или на машине нет браузера
для докачки соцсетей с карточек. Панель отвечает на это одним нажатием.

Правила, по которым она сделана:

* **Ничего не трогает в рабочем состоянии.** Живые проверки ключей идут
  отдельным клиентом httpx — без ретраев и общего rate-limiter, поэтому
  диагностика не может ни ускорить, ни остановить идущий поиск (общий
  `http_client._get` умеет `state.request_stop()`).
* **Ключи наружу не отдаются.** В ответе только булевы признаки и словами
  описанный результат; текст исключений целиком не пересказывается — в нём
  мог бы оказаться ключ из URL запроса.
* **Квота не тратится молча.** Проверка 2ГИС — это 1–2 запроса из месячного
  лимита: кнопка про это предупреждает, а ответ говорит, сколько уже ушло.
* **Ошибки не роняют панель.** Любое падение отдельной проверки становится
  строкой «ошибка» с человеческим объяснением, а не 500.

Эндпоинт один: POST /diagnostics/run {"groups": ["keys", "files", "data", "env"]}.

Запустить его может только сам интерфейс: проверка ключей тратит запросы
2ГИС, а окно приложения слушает 127.0.0.1 — значит чужая страница в браузере
не должна уметь нажать эту кнопку за пользователя (см. `_only_from_our_ui`).
"""
import os
import re
import shutil
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("diagnostics", __name__)

# Группы проверок: раздельно, потому что «ключи» стоят квоту и время, а
# «файлы/данные/окружение» — бесплатны и мгновенны.
GROUPS = ("keys", "files", "data", "env")

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

    Порядок как у /api-keys/status: сначала config (.env), затем ручной ввод
    в форме этого запуска (state) — иначе панель показывала бы «ключ не задан»
    человеку, который только что вставил его в поле.
    """
    keys = {"yandex": "", "twogis": "", "vk": ""}
    try:
        from config import TWOGIS_API_KEY, VK_TOKEN, YANDEX_API_KEY
        keys = {"yandex": (YANDEX_API_KEY or "").strip(),
                "twogis": (TWOGIS_API_KEY or "").strip(),
                "vk": (VK_TOKEN or "").strip()}
    except Exception:
        pass
    try:
        from yandex_maps_parser import state as pstate
        keys["yandex"] = keys["yandex"] or (getattr(pstate, "YANDEX_API_KEY", "") or "").strip()
        keys["twogis"] = keys["twogis"] or (getattr(pstate, "TWOGIS_API_KEY", "") or "").strip()
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
    вмешиваться в идущий поиск (общий `http_client._get` умеет остановить прогон).
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

def check_yandex_key(key: str) -> dict:
    """Один пробный запрос к Яндекс.Картам: работает ли ключ."""
    if not key:
        return _res("yandex_key", "keys", "warn", "Ключ Яндекс.Карт не задан",
                    "Без него поиск по Яндекс.Картам не запустится.",
                    "Вставьте ключ в блоке «API-ключи» и сохраните.")
    status, text, data, note = _http_get("https://search-maps.yandex.ru/v1/", {
        "text": "кофе", "ll": "37.6173,55.7558", "type": "biz", "results": 1,
        "lang": "ru_RU", "apikey": key,
    })
    if not status:
        return _res("yandex_key", "keys", "error", "Яндекс.Карты не ответили",
                    f"Сбой соединения ({note}).",
                    "Проверьте интернет, VPN или прокси и повторите проверку.")
    if status == 403:
        # Яндекс сам говорит, что именно не так: «Invalid api key» — один
        # случай, «Quota exceeded» — совсем другой, и советы у них разные.
        message = _error_message(text, data)
        low = message.lower()
        if any(word in low for word in ("invalid", "not found", "unknown", "не найден")):
            return _res("yandex_key", "keys", "error", "Ключ Яндекс.Карт недействителен",
                        f"Яндекс ответил: {message}.",
                        "Проверьте ключ в кабинете разработчика: он мог быть отозван "
                        "или скопирован с лишними символами.")
        if any(word in low for word in ("limit", "quota", "exceed", "лимит")):
            return _res("yandex_key", "keys", "error", "Лимит запросов Яндекс.Карт исчерпан",
                        f"Яндекс ответил: {message}.",
                        "Суточный лимит Search API сбрасывается раз в сутки — "
                        "подождите или подключите другой ключ.")
        return _res("yandex_key", "keys", "error", "Ключ Яндекс.Карт отклонён",
                    (f"Яндекс ответил: {message}." if message else "Яндекс вернул «доступ запрещён»."),
                    "Проверьте ключ и квоты в кабинете разработчика Яндекса.")
    if status != 200:
        return _res("yandex_key", "keys", "error",
                    f"Яндекс.Карты вернули код {status}",
                    "Ответ получен, но запрос не выполнен.",
                    "Повторите позже: чаще всего это временный сбой сервиса.")
    found = None
    try:
        found = data["properties"]["responseMetaData"]["SearchResponse"]["found"]
    except Exception:
        found = None
    detail = ("Ключ работает: API ответил на пробный запрос."
              + (f" Рядом с Москвой нашлось {found} организаций." if found else ""))
    return _res("yandex_key", "keys", "ok", "Ключ Яндекс.Карт работает", detail)


def check_twogis_key(key: str) -> dict:
    """Пробный запрос к каталогу 2ГИС: работает ли ключ и что он отдаёт.

    Проверка отвечает не только «ключ жив», но и на самый частый вопрос по
    2ГИС: отдаёт ли ключ контакты (соцсети/сайт) и новые поля — число
    филиалов (`items.org`) и дату появления карточки (`items.dates`), на
    которых держатся фильтры «только одиночки» и «только новые».
    """
    if not key:
        return _res("twogis_key", "keys", "warn", "Ключ 2ГИС не задан",
                    "Поиск по 2ГИС не запустится, а счётчик его квоты останется пустым.",
                    "Получите бесплатный ключ на dev.2gis.ru и сохраните его в «API-ключи».")

    from yandex_maps_parser import twogis

    quota_left = ""
    try:
        used, cap = twogis.quota_used(), twogis.quota_cap()
        quota_left = (f" В этом месяце израсходовано ~{used} из {cap} запросов "
                      f"бесплатного тарифа.")
    except Exception:
        pass

    def _probe(fields: str):
        return _http_json(twogis._API_URL, {
            "q": "кофе Уфа", "page": 1, "page_size": 1, "key": key,
            "fields": fields, "locale": "ru_RU",
        })

    status, data, note = _probe(twogis._FIELDS_FULL)
    fields_ok = True
    if not status:
        return _res("twogis_key", "keys", "error", "2ГИС не ответил",
                    f"Сбой соединения ({note}).",
                    "Проверьте интернет, VPN или прокси и повторите проверку.")
    meta = (data or {}).get("meta") or {}
    error = meta.get("error")
    # Отказ именно по полям: повторяем с набором без новых полей — так мы
    # узнаём не только «ключ живой», но и то, каких полей у него нет.
    if error:
        message = str(error.get("message") or error)
        etype = str(error.get("type") or "")
        if any(word in message.lower() for word in ("field", "permission")) or \
                "forbidden" in etype.lower():
            fields_ok = False
            status, data, note = _probe(twogis._FIELDS_CONTACTS)
            meta = (data or {}).get("meta") or {}
            error = meta.get("error")
    if error:
        human = twogis._human_api_error(meta.get("code"), str(error.get("message") or error),
                                        str(error.get("type") or ""), "кофе", "Уфа")
        return _res("twogis_key", "keys", "error", "Ключ 2ГИС отклонён",
                    human, "Проверьте ключ на dev.2gis.ru (Platform Manager).")

    items = ((data or {}).get("result") or {}).get("items") or []
    item = items[0] if items else {}
    has_contacts = "contact_groups" in item
    org = item.get("org") if isinstance(item.get("org"), dict) else {}
    dates = item.get("dates") if isinstance(item.get("dates"), dict) else {}
    branches = org.get("branch_count")
    added = dates.get("created_at") or dates.get("added_at") or ""

    parts = [f"контакты: {'да' if has_contacts else 'нет'}"]
    parts.append(f"число филиалов: {branches}" if branches not in (None, "")
                 else "число филиалов: нет")
    parts.append(f"дата появления карточки: {str(added)[:10]}" if added
                 else "дата появления карточки: нет")
    detail = "Ключ работает. В ответе — " + ", ".join(parts) + "." + quota_left

    advice = []
    if not fields_ok:
        advice.append("ключ не принимает items.org/items.dates: фильтр «только новые» "
                      "не сможет отсеивать по дате (нужен ключ с этими полями)")
    if not has_contacts:
        advice.append("ключ без права contact_groups — соцсети будут докачиваться "
                      "с карточек организации, это заметно медленнее")
    if branches in (None, ""):
        advice.append("число филиалов придёт только из нашего счёта по сбору")
    status_word = "warn" if advice else "ok"
    return _res("twogis_key", "keys", status_word,
                "Ключ 2ГИС работает" + (" (с ограничениями)" if advice else ""),
                detail, ". ".join(a.capitalize() for a in advice) + ("." if advice else ""))


def check_vk_token(token: str) -> dict:
    """Пробный users.get: действителен ли токен ВКонтакте."""
    if not token:
        return _res("vk_token", "keys", "warn", "Токен ВКонтакте не задан",
                    "Проверка активности ВК и рассылка сообщений работать не будут.",
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
                            "фильтры одиночек и новых работают по данным 2ГИС."))
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

    # Браузер нужен там, где ключ 2ГИС не отдаёт контакты, и для карточек
    # Яндекс.Карт: без него соцсети не докачиваются.
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
        out.append(_res("browser", "env", "warn", "Браузер не найден",
                        "Chrome, Chromium и Edge не обнаружены на этой машине.",
                        "Установите Google Chrome — иначе соцсети с карточек "
                        "организаций собираться не будут."))

    # severity: core — приложение без этого не работает вообще;
    # browser — работает, но хуже: карточки организаций придётся тянуть
    # запасным способом (или соцсети вовсе не соберутся).
    for module, label, severity, hint, advice in (
        ("httpx", "httpx", "error",
         "Без него не работают запросы к API Яндекс.Карт и 2ГИС.",
         "Переустановите приложение: зависимости ставятся вместе с ним."),
        ("openpyxl", "openpyxl", "error",
         "Без него не читаются и не сохраняются Excel-файлы, а этап 2 работает именно с ними.",
         "Переустановите приложение: зависимости ставятся вместе с ним."),
        ("playwright", "Playwright", "warn",
         "Без него карточки организаций читаются только запасным путём через Chrome DevTools.",
         "Это часть установки приложения — переустановите его, если соцсети не собираются."),
        ("websocket", "websocket-client", "warn",
         "Без него не работает запасной путь через Chrome DevTools — а когда ключ 2ГИС "
         "не отдаёт контакты, соцсети собираются именно с карточек.",
         "Установите зависимость проекта: pip install -r requirements.txt"),
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
    запросом (обычная HTML-форма — без CORS-preflight) и молча израсходовать
    бесплатную квоту 2ГИС. Поэтому требуем тело в JSON: такой запрос чужая
    страница без preflight отправить не может, а preflight мы не разрешаем
    (ответных CORS-заголовков у сервиса нет).
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

def run_checks(groups=None) -> list[dict]:
    """Отчёт по выбранным группам. Падение одной проверки — строка «ошибка»."""
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
        _safe("yandex_key", "keys", check_yandex_key, keys["yandex"])
        _safe("twogis_key", "keys", check_twogis_key, keys["twogis"])
        _safe("vk_token", "keys", check_vk_token, keys["vk"])
    if "files" in wanted:
        _safe("storage", "files", check_storage)
    if "data" in wanted:
        _safe("data", "data", check_data)
    if "env" in wanted:
        _safe("env", "env", check_environment)

    order = {"error": 0, "warn": 1, "ok": 2}
    return sorted(results, key=lambda r: order.get(r["status"], 3))


@bp.route("/diagnostics/run", methods=["POST"])
def diagnostics_run():
    """Самопроверка по кнопке.

    Body: {"groups": ["keys", "files", "data", "env"]} — по умолчанию все.
    Reply: {ok, results: [{id, group, status, title, detail, hint}], ts}

    Ответ не содержит ключей: только булевы признаки и объяснения словами.
    """
    data = request.get_json(silent=True) or {}
    groups = data.get("groups")
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, list):
        groups = None
    try:
        results = run_checks(groups)
    except Exception as exc:            # аварийный случай: панель всё равно отвечает
        return jsonify({"ok": False, "error": f"Диагностика не смогла выполниться: {_exception_note(exc)}",
                        "results": []}), 200
    return jsonify({"ok": True, "results": results, "ts": int(time.time())})
