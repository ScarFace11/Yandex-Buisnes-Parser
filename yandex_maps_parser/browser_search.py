"""
Поиск организаций через сам Яндекс.Карты (реальный Chrome, CDP).

Зачем: API «Поиск по организациям» (search-maps.yandex.ru) — коммерческий,
а его бесплатная версия прямо запрещает сохранять полученные данные
(https://yandex.ru/dev/commercial/doc/ru/). Приложение собирает выгрузку,
поэтому пользуется тем же публичным интерфейсом карт, что и человек:
открывает страницу поиска в настоящем браузере и читает то, что видит
пользователь.

Никаких HTTP-запросов «мимо браузера»: страницу открывает Chrome, наружу
уходит один готовый JSON карточек. Такой способ и технически надёжнее
(антибот Яндекс.Карт режет именно не-браузерные запросы), и меньше
«подставляет» аккаунт.

Данные берутся из самой страницы, а не из вёрстки:

1. Основной путь — предзагруженное состояние страницы: Яндекс отдаёт выдачу
   вместе с HTML (`<script type="application/json">`, `stack[0].results.items`)
   — там те же организации, что видит пользователь, но уже полями: название,
   адрес, координаты, рубрики, рейтинг и число оценок. Читаем JSON, а не DOM:
   вёрстка перерисовывается и виртуализуется, а состояние приходит целиком —
   это и быстрее, и не зависит от того, догрузился ли список.
   Следующие страницы выдачи (по 25 организаций) запрашиваются из самой
   страницы тем же fetch с реальными cookie — ровно так же, как это делает
   сам Яндекс.Карты при прокрутке списка.
2. Запасной путь — разбор вёрстки с прокруткой списка (см. `_harvest_js`):
   включается, если состояния в странице нет или оно без выдачи (Яндекс
   поменял разметку/отдал другой вариант страницы).
"""
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

from . import cdp_client
from . import city_coords
from . import state

# Селекторы карточки поисковой выдачи Яндекс.Карт (проверены на живой
# странице: data-object="search-list-item" + data-id/data-coordinates).
CARD_SELECTOR = '[data-object="search-list-item"]'

# Сколько карточек максимум забирать с одной точки.
_MAX_CARDS = 250

# Яндекс отдаёт по 25 организаций на страницу выдачи.
_CARDS_PER_PAGE = 25

# Минимальный размер inline-JSON, который считаем состоянием выдачи:
# служебные JSON-скрипты страницы — сотни байт, состояние — сотни килобайт.
_STATE_MIN_BYTES = 50_000

# Признаки страницы-проверки вместо выдачи. На подозрительный запрос Яндекс
# отвечает SmartCaptcha («Вы не робот?», адрес /showcaptcha) с тем же кодом 200,
# и раньше это выглядело как «страница не открылась»: сбор ждал 90 секунд
# состояние, ещё 90 — разбор вёрстки (в живом прогоне 17.10.2026 — 3 минуты на
# город), а в лог уходило «проверьте, что браузер запускается и есть интернет».
# Браузер при этом работал, интернет тоже — врала сама формулировка.
_BLOCK_JS = (
    "(location.href.indexOf('showcaptcha') >= 0"
    " || /(вы не робот|подтвердите, что запросы)/i.test(document.title || '')"
    " || !!document.querySelector('.SmartCaptcha, #captcha-container'))"
)

# Почему выдача не пришла — на прогон, для человеческого объяснения в UI.
_block_lock = threading.Lock()
_last_block = ""


def blocked_reason() -> str:
    """«captcha», если Яндекс в этом прогоне показал проверку вместо выдачи.

    Пустая строка — выдача не блокировалась (пусто может быть и просто потому,
    что организация не нашлась).
    """
    with _block_lock:
        return _last_block


def reset_blocked() -> None:
    """Забыть прошлую проверку: новый прогон — новый отсчёт."""
    global _last_block
    with _block_lock:
        _last_block = ""


def _set_blocked(reason: str) -> None:
    global _last_block
    with _block_lock:
        _last_block = reason


# Бюджет на добирание следующих страниц внутри страницы (секунды):
# страница выдачи — ~1,3 с, десяток страниц — ~15 с, с запасом.
_PAGING_BUDGET_S = 45

_city_cache: dict[str, tuple[float, float] | None] = {}
_city_lock = threading.Lock()

# Центр, который Яндекс.Карты ставят, когда НЕ узнали название: с ним поиск
# молча уезжал в Москву, хотя пользователь просил другой город. Точка у
# Яндекса конкретная, поэтому и допуск маленький (~200 м) — так не задеты
# города рядом с Москвой (Химки, Мытищи и т. д.).
_DEFAULT_CENTER = (55.7558, 37.6173)
_DEFAULT_EPS = 0.002


def _looks_like_default_center(city: str, coords: tuple[float, float]) -> bool:
    """Это «Москва по умолчанию» вместо запрошенного города?

    Проверяется только для названий вне таблицы координат: там центр уже
    известен и никаких догадок не нужно.
    """
    if city_coords.lookup(city) is not None:
        return False
    low = str(city or "").strip().lower().replace("ё", "е")
    if low.startswith("москв") or low in ("мск", "moscow"):
        return False
    lat, lon = coords
    return (abs(lat - _DEFAULT_CENTER[0]) < _DEFAULT_EPS
            and abs(lon - _DEFAULT_CENTER[1]) < _DEFAULT_EPS)


def _state_wait_expr() -> str:
    """Готовность страницы: состояние выдачи уже в документе — или это капча.

    Проверка входит в условие ожидания намеренно: на странице-проверке
    состояния не будет никогда, и без неё ожидание гарантированно выжидало
    весь таймаут (90 с) вместо того, чтобы сразу сказать, что случилось.
    """
    return (
        "(Array.prototype.some.call("
        "document.querySelectorAll('script[type=\"application/json\"]'),"
        f"function (s) {{ return (s.textContent || '').length > {_STATE_MIN_BYTES}; }})"
        " || " + _BLOCK_JS + ")"
    )


def _state_harvest_js(want: int) -> str:
    """JS: прочитать выдачу из состояния страницы и добрать следующие страницы.

    Возвращает JSON {total, cards} либо пустую строку — тогда вызывающий
    уходит на запасной разбор вёрстки.
    """
    want = max(1, min(int(want), _MAX_CARDS))
    max_page = max(1, min(_MAX_CARDS // _CARDS_PER_PAGE,
                          -(-want // _CARDS_PER_PAGE)))
    return _STATE_JS.replace("$WANT$", str(int(want))) \
                   .replace("$MAXPAGE$", str(int(max_page))) \
                   .replace("$BUDGET$", str(int(_PAGING_BUDGET_S * 1000))) \
                   .replace("$BLOCK$", _BLOCK_JS)


# Шаблон JS (подстановки — $WANT$/$MAXPAGE$/$BUDGET$). Значений для формата
# `%` здесь нет намеренно: в JS слишком много знаков процента (width/height,
# encodeURIComponent), и `%`-форматирование на нём легко ломается.
_STATE_JS = """
(async () => {
  const want = $WANT$;
  const maxPage = $MAXPAGE$;
  const budgetMs = $BUDGET$;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // Проверка «Вы не робот?» — не выдача: сообщаем наверх сразу и не ждём
  // состояние, которого на такой странице не появится.
  if ($BLOCK$) return JSON.stringify({blocked: 'captcha'});

  // Состояние выдачи — самый большой inline-JSON документа.
  const readState = (doc) => {
    let best = null;
    for (const s of doc.querySelectorAll('script[type="application/json"]')) {
      const t = s.textContent || '';
      if (!best || t.length > best.length) best = t;
    }
    if (!best) return null;
    try {
      const root = JSON.parse(best);
      return (root && root.stack && root.stack[0] && root.stack[0].results) || null;
    } catch (e) {
      return null;
    }
  };

  // Организация состояния → карточка. Координаты Яндекс отдаёт как
  // [широта, долгота], наружу уходят как "долгота,широта" — этот порядок
  // ждёт остальной конвейер (см. _card_feature).
  const norm = (it) => {
    const id = (it && it.id !== undefined && it.id !== null) ? String(it.id) : '';
    const name = String((it && (it.title || it.shortTitle || it.name)) || '').trim();
    if (!id || !name) return null;              // рекламные врезки без организации
    const rd = it.ratingData || {};
    const value = Number(rd.ratingValue);
    const rating = isFinite(value) ? value.toFixed(1) : '';
    const count = Number(rd.ratingCount || rd.reviewCount || 0);
    const coords = it.coordinates || it.displayCoordinates || [];
    return {
      id: id,
      name: name,
      category: (it.categories || []).map(c => c && c.name).filter(Boolean).join(', '),
      address: String(it.address || it.fullAddress || '').trim(),
      rating: rating,
      reviews: count > 0 ? String(count) : '',
      coords: coords.length > 1 ? (String(coords[1]) + ',' + String(coords[0])) : ''
    };
  };

  let st = null;
  for (let i = 0; i < 40; i++) {
    st = readState(document);
    if (st && (st.items || []).length) break;
    await sleep(500);
  }
  if (!st || !(st.items || []).length) return '';   // нет состояния → DOM-фолбэк

  const out = new Map();
  const add = (items) => {
    for (const it of (items || [])) {
      const card = norm(it);
      if (card && !out.has(card.id)) out.set(card.id, card);
    }
  };
  add(st.items);

  const total = Number(st.totalResultCount || 0) || 0;
  const startedAt = Date.now();
  for (let page = 2; page <= maxPage && out.size < want; page++) {
    if (Date.now() - startedAt > budgetMs) break;
    if (total && out.size >= total) break;
    let html = '';
    try {
      // Тот же запрос, что делает сам Яндекс.Карты при прокрутке списка:
      // из страницы, с её cookie и заголовками.
      const pageUrl = location.origin + location.pathname + location.search
                      + (location.search ? '&' : '?') + 'page=' + page;
      const resp = await fetch(pageUrl, {credentials: 'include'});
      if (!resp.ok) break;
      html = await resp.text();
    } catch (e) {
      break;
    }
    const next = readState(new DOMParser().parseFromString(html, 'text/html'));
    if (!next || !(next.items || []).length) break;
    const before = out.size;
    add(next.items);
    if (out.size === before) break;               // страница не дала новых организаций
  }
  return JSON.stringify({total: total, cards: [...out.values()]});
})()
"""


def _harvest_js(want: int) -> str:
    """Запасной путь: дождаться выдачи, прокрутить список, вернуть карточки."""
    return """
(async () => {
  const want = %d;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  if ($BLOCK$) return JSON.stringify({blocked: 'captcha'});
  const cards = () => [...document.querySelectorAll('%s')];
  // Ждём первую отрисовку списка (SPA подгружает его после загрузки страницы).
  for (let i = 0; i < 40 && cards().length === 0; i++) await sleep(500);
  // Прокручиваем МАЛЕНЬКИМИ шагами, как человек колесом. Список выдачи
  // виртуализован: прыжок сразу в самый низ (`scrollTop = scrollHeight`)
  // не догружает продолжение — список остаётся на первой горстке карточек
  // (в живом тесте 5–8 вместо 25+). Пока замера не совпадает с размером
  // списка, шагаем дальше.
  // Контейнер перезапрашиваем каждый шаг: SPA может подменить его
  // (в живых замерах первый найденный .scroll__container иногда оказывался
  // пустой заготовкой — scrollHeight 0).
  let prev = -1, still = 0, noScroll = 0;
  const startedAt = Date.now();
  for (let i = 0; i < 120 && cards().length < want; i++) {
    const box = document.querySelector('.scroll__container') || document.scrollingElement;
    const scrollable = !!box && box.scrollHeight > box.clientHeight + 8;
    const before = scrollable ? box.scrollTop : 0;
    if (scrollable) {
      box.scrollTop = Math.min(before + 300, box.scrollHeight);
      box.dispatchEvent(new WheelEvent('wheel', {bubbles: true, deltaY: 300}));
    }
    await sleep(400);
    const n = cards().length;
    // Низ списка: прокрутка дальше не идёт и карточки прибывать перестали.
    const atBottom = scrollable && box.scrollTop <= before + 1
      && box.scrollTop + box.clientHeight >= box.scrollHeight - 8;
    if (n === prev && atBottom) { if (++still >= 3) break; } else { still = 0; }
    // Список не прокручивается вообще — ждать нечего (карточки уже все).
    if (scrollable) { noScroll = 0; } else if (++noScroll >= 8) { break; }
    prev = n;
    if (Date.now() - startedAt > 25000) break;
  }
  const txt = (el, sel) => { const n = el.querySelector(sel); return n ? (n.textContent || '').trim() : ''; };
  const out = cards().map(el => {
    const a = el.querySelector('a[href*="/maps/org/"]');
    const badge = el.querySelector('[class*="rating-badge"]');
    return {
      id: el.getAttribute('data-id') || '',
      coords: el.getAttribute('data-coordinates') || '',
      name: txt(el, '.search-business-snippet-view__title') || (a ? (a.getAttribute('aria-label') || '') : ''),
      category: txt(el, '.search-business-snippet-view__category'),
      address: txt(el, '.search-business-snippet-view__address'),
      rating: txt(el, '.business-rating-badge-view__rating-text'),
      reviews: txt(el, '.business-rating-badge-view__rating-count') || (badge ? (badge.textContent || '') : '')
    };
  });
  let total = 0;
  const head = document.querySelector('.search-list-view__title, .search-heading-title, h1');
  if (head) { const m = (head.textContent || '').match(/(\\d[\\d\\s]*)/); if (m) total = parseInt(m[1].replace(/\\s/g, ''), 10) || 0; }  return JSON.stringify({cards: out, url: location.href, total: total});
})()
""".replace("$BLOCK$", _BLOCK_JS) % (int(want), CARD_SELECTOR)


def _search_url(query: str, city: str, lat: float | None, lon: float | None) -> str:
    """URL страницы поиска: текст запроса + город, при точке — её центр.

    Без координат (город не опознан) центр в адрес не добавляем: тогда
    Яндекс разрешает город сам по тексту «запрос + город», а не по точке,
    вокруг которой иначе построилась бы сетка непонятно где.
    """
    text = f"{query} {city}".strip()
    url = "https://yandex.ru/maps/?text=" + quote(text)
    if lat is not None and lon is not None:
        url += f"&ll={lon:.6f}%2C{lat:.6f}&z=15&sll={lon:.6f}%2C{lat:.6f}"
    return url


def _num(raw: str) -> str:
    """«4,9» → «4.9», «(1 490 оценок)» → «1490», пустое остаётся пустым."""
    text = re.sub(r"[^\d,.]", "", str(raw or "").replace("\u00a0", " ").replace(" ", ""))
    return text.replace(",", ".").strip(".")


def _reviews(raw: str) -> str:
    m = re.search(r"(\d[\d\s\u00a0]*)", str(raw or ""))
    return m.group(1).replace(" ", "").replace("\u00a0", "") if m else ""


def _items_to_cards(items: list) -> list[dict]:
    """Карточки из состояния страницы → тот же формат, что отдаёт разбор вёрстки."""
    cards: list[dict] = []
    seen: set[str] = set()
    for card in items or []:
        biz_id = str(card.get("id") or "").strip()
        name = str(card.get("name") or "").strip()
        if not biz_id or not name or biz_id in seen:
            continue
        seen.add(biz_id)
        coords = [p.strip() for p in str(card.get("coords") or "").split(",")]
        clat = coords[1] if len(coords) == 2 else ""
        clon = coords[0] if len(coords) == 2 else ""
        cards.append({
            "_biz_id": biz_id,
            "name": name,
            "category": str(card.get("category") or "").strip(),
            "address": str(card.get("address") or "").strip(),
            "rating": _num(card.get("rating")),
            "reviews_count": _reviews(card.get("reviews")),
            "lat": clat,
            "lon": clon,
        })
    return cards


def _harvest_from_state(url: str, want: int) -> list[dict]:
    """Основной путь: выдача из предзагруженного состояния страницы."""
    raw = cdp_client.eval_in_page(
        url,
        _state_harvest_js(want),
        wait_expr=_state_wait_expr(),
        timeout_s=90.0,
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        state.syslog(f"browser_search: не разобрал состояние выдачи ({str(raw)[:120]!r})")
        return []
    if data.get("blocked"):
        _set_blocked(str(data.get("blocked")))
        state.syslog("browser_search: вместо выдачи Яндекс показал проверку «Вы не робот?»")
        return []
    cards = _items_to_cards(data.get("cards") or [])
    if cards:
        state.syslog(f"browser_search: cards={len(cards)} из {data.get('total') or '?'} "
                     f"(состояние страницы)")
    return cards


def _harvest_from_dom(url: str, want: int) -> list[dict]:
    """Запасной путь: разбор вёрстки выдачи с прокруткой списка."""
    raw = cdp_client.eval_in_page(
        url,
        _harvest_js(want),
        wait_expr=(f"(document.querySelectorAll('{CARD_SELECTOR}').length > 0"
                   f" || {_BLOCK_JS})"),
        timeout_s=90.0,
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        state.syslog(f"browser_search: не разобрал JSON выдачи ({str(raw)[:120]!r})")
        return []
    if data.get("blocked"):
        _set_blocked(str(data.get("blocked")))
        return []
    return _items_to_cards(data.get("cards") or [])


def harvest_cards(query: str, city: str, lat: float | None, lon: float | None,
                  max_cards: int = 50) -> list[dict]:
    """Карточки выдачи Яндекс.Карт по запросу (без API-ключей).

    Возвращает список словарей: id, name, category, address, rating,
    reviews_count, lat/lon. Пустой список — выдача не загрузилась (нет
    браузера, остановка, блок-страница).

    Сначала читаем состояние страницы (JSON), при неудаче — разбираем
    вёрстку с прокруткой: у состояния тот же набор организаций, но
    он приходит целиком и не зависит от догрузки виртуального списка.
    """
    want = max(1, min(int(max_cards or 50), _MAX_CARDS))
    url = _search_url(query, city, lat, lon)
    state.syslog(f"browser_search: {url}")
    cards = _harvest_from_state(url, want)
    if not cards and not blocked_reason():
        state.syslog("browser_search: состояния с выдачей нет — разбираю вёрстку")
        cards = _harvest_from_dom(url, want)
        if cards:
            state.syslog(f"browser_search: cards={len(cards)} (вёрстка)")
    state.syslog(f"browser_search: cards={len(cards)} (запрошено до {want}), запрос={query!r}")
    return cards


def city_center(city: str) -> tuple[float, float] | None:
    """Координаты центра города: таблица → кэш → карта (без геокодера-API).

    Порядок важен:

    1. Города каталога приложения берутся из таблицы `city_coords` — мгновенно,
       без сети и без браузера, и всегда верные (раньше на каждый город
       тратилась навигация).
    2. Кэш на диске — для городов вне каталога, но только «здоровые»
       значения: центр по умолчанию (Москва), осевший в кэше от прошлых
       версий, отбрасывается и ищется заново.
    3. Карта: несколько формулировок запроса и проверка результата — если
       Яндекс не узнал название, он вернёт Москву, и это надо заметить, а не
       отдать дальше (иначе прогон молча идёт по Москве).

    None означает «город не опознан»: вызывающий ищет по тексту запроса без
    сетки точек, а не подставляет Москву.
    """
    key = (city or "").strip().lower()
    if not key:
        return None
    with _city_lock:
        if key in _city_cache:
            return _city_cache[key]

    coords = city_coords.lookup(city)

    if coords is None:
        coords = _center_from_disk(key)
        if coords is not None and _looks_like_default_center(city, coords):
            # Мусор в кэше: когда-то город не опознался и туда лёг центр Москвы.
            state.syslog(f"browser_search: в кэше координат «{city}» лежит центр "
                         "по умолчанию — ищу заново")
            coords = None

    if coords is None:
        coords = _center_from_browser(city)
        if coords is not None:
            _center_to_disk(key, coords)

    with _city_lock:
        _city_cache[key] = coords
    return coords


def _center_from_browser(city: str) -> tuple[float, float] | None:
    """Центр города с карты: варианты запроса + отбраковка «Москвы по умолчанию».

    Одного захода `?text=<city>` мало: если Яндекс не узнал название, он
    отдаёт центр по умолчанию, и раньше это принималось за ответ. Поэтому
    пробуем несколько формулировок и берём только осмысленный результат.
    """
    for query in (city, f"{city}, Россия", f"город {city}"):
        raw = cdp_client.eval_in_page(
            "https://yandex.ru/maps/?text=" + quote(query),
            "location.href",
            timeout_s=45.0,
        )
        coords = _parse_center(raw or "")
        if coords is None:
            continue
        if _looks_like_default_center(city, coords):
            state.syslog(f"browser_search: «{query}» не распознан — Яндекс вернул "
                         "центр по умолчанию, пробую иначе")
            continue
        state.syslog(f"browser_search: центр «{city}» с карты: "
                     f"{coords[0]:.4f}, {coords[1]:.4f}")
        return coords
    state.syslog(f"browser_search: координаты «{city}» не получены — "
                 "поиск пойдёт по тексту без сетки точек")
    return None


# Accept both the usual %2C and a raw comma: the mobile page / live JS
# rewrites can leave ll=37.6,55.7 unencoded, and then _parse_center used to
# return None and the city silently fell back to the Moscow default.
_CENTER_RE = re.compile(r"[?&](?:ll|sll)=(-?\d+\.\d+)(?:%2C|,)(-?\d+\.\d+)")


def _parse_center(url: str) -> tuple[float, float] | None:
    m = _CENTER_RE.search(url or "")
    if not m:
        return None
    try:
        lon, lat = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return (lat, lon)


def _cache_path() -> Path:
    return Path(state.OUTPUT_DIR) / ".cache" / "city_centers.json"


def _center_from_disk(key: str) -> tuple[float, float] | None:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        item = data.get(key)
        if isinstance(item, list) and len(item) == 2:
            return (float(item[0]), float(item[1]))
    except Exception:
        pass
    return None


def _center_to_disk(key: str, coords: tuple[float, float]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[key] = [coords[0], coords[1]]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
