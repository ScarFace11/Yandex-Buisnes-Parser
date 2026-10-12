"""
Поиск организаций в Яндекс.Картах — через настоящий браузер (CDP).

Раньше страница выдачи приходила из коммерческого API «Поиск по
организациям» (search-maps.yandex.ru) по API-ключу. Приложение его больше
не использует: бесплатная версия API запрещает сохранять полученные данные
(https://yandex.ru/dev/commercial/doc/ru/), а платная для задачи не нужна.
Теперь поиск идёт тем же путём, что у обычного пользователя: открывается
страница Яндекс.Карт в реальном Chrome, список прокручивается и читается
из DOM (см. browser_search.py).

Модуль сохраняет прежний контракт `search_page(...)`: наружу выдаются
GeoJSON-подобные «фичи» с CompanyMetaData, чтобы весь остальной конвейер
(парсинг записи, дедупликация, обогащение карточек) не менялся.
"""
import threading

from . import state
from .browser_search import harvest_cards

_PAGE_SIZE = 50           # сколько карточек отдавать за одну «страницу»
_HARVEST_CACHE_MAX = 8    # сколько выдач держать в памяти (query+точка)

_harvest_cache: dict[tuple, list[dict]] = {}
_cache_lock = threading.Lock()


def search_failure_hint() -> str:
    """Человеческое объяснение пустой выдачи (браузер/страница не ответили)."""
    return ("Не удалось открыть выдачу Яндекс.Карт. Проверьте, что браузер "
            "запускается (вкладка «🩺 Диагностика») и есть доступ в интернет.")


def _cache_key(query: str, lat: float, lon: float) -> tuple:
    return (query.strip().lower(), round(float(lat), 3), round(float(lon), 3))


def _remember(key: tuple, cards: list[dict]) -> None:
    with _cache_lock:
        _harvest_cache[key] = cards
        if len(_harvest_cache) > _HARVEST_CACHE_MAX:
            for old in list(_harvest_cache)[:-_HARVEST_CACHE_MAX]:
                _harvest_cache.pop(old, None)


def _harvest(query: str, city: str, lat: float, lon: float) -> list[dict]:
    """Карточки выдачи для (query, точка) — с кэшем на время прогона.

    Одна прокрутка страницы отдаёт до ~50 организаций, поэтому страницы
    MAX_PAGES обслуживаются из одной выдачи: повторных открытий страницы
    нет, лишних обращений к Яндексу тоже (меньше следов — меньше риска).
    """
    key = _cache_key(query, lat, lon)
    with _cache_lock:
        cached = _harvest_cache.get(key)
    if cached is not None:
        return cached

    want = max(_PAGE_SIZE, min(int(getattr(state, "MAX_PAGES", 1) or 1) * _PAGE_SIZE, 250))
    cards = harvest_cards(query, city, lat, lon, max_cards=want)
    _remember(key, cards)
    return cards


def search_page(
    query: str, city: str, lat: float, lon: float, skip: int, session=None
) -> tuple[list[dict], int | None]:
    """Одна «страница» выдачи Яндекс.Карт для (query, точка).

    Возвращает (features, found): features — GeoJSON-подобные карточки,
    found — сколько организаций Яндекс показал по этому запросу (None,
    если счётчик не распознан). `session` оставлен для совместимости
    вызовов: HTTP-сессии больше не используются, страницу открывает браузер.
    """
    if state._STOP_EVENT and state._STOP_EVENT.is_set():
        return [], None
    if state.is_skip_city():
        return [], None

    cards = _harvest(query, city, lat, lon)
    if not cards:
        state.warn(search_failure_hint())
        state.tech("search: браузерная выдача пуста (страница не открылась или карточек нет)")
        return [], None

    chunk = cards[skip:skip + _PAGE_SIZE]
    features = [_card_feature(card) for card in chunk]
    return features, len(cards)


def _card_feature(card: dict) -> dict:
    """Карточка выдачи → GeoJSON-фича в формате прежнего Search API.

    Так вся дальнейшая обработка (parse_feature → дедупликация → enrich)
    работает без изменений, хотя данные пришли из DOM, а не из API.
    """
    lat, lon = card.get("lat") or "", card.get("lon") or ""
    coords: list[float] = []
    try:
        coords = [float(lon), float(lat)]
    except (TypeError, ValueError):
        coords = []

    categories = [{"name": part.strip()} for part in str(card.get("category") or "").split(",") if part.strip()]
    meta = {
        "id": card.get("_biz_id", ""),
        "name": card.get("name", ""),
        "address": card.get("address", ""),
        # Сайт в выдаче не показывается — он выяснится на карточке организации
        # (см. extractors.extract_website и фильтр в enrichment).
        "url": "",
        "rating": card.get("rating", ""),
        "reviews_count": card.get("reviews_count", ""),
        "Categories": categories,
    }
    return {"properties": {"CompanyMetaData": meta}, "geometry": {"coordinates": coords}}


def parse_feature(feature: dict, query: str) -> dict | None:
    """
    Convert a feature (DOM-карточка Яндекс.Карт) into a candidate record.
    Returns None only if the business has no name or fails quality filters.
    """
    from .extractors import _is_aggregator

    props = feature.get("properties", {})
    meta  = props.get("CompanyMetaData", {})

    name = str(meta.get("name", "")).strip()
    if not name:
        return None

    raw_url    = str(meta.get("url", "")).strip()
    aggregator = ""

    if raw_url and _is_aggregator(raw_url):
        aggregator = raw_url

    # Parse mode "without_website": выдача не сообщает сайт, поэтому решение
    # принимается на карточке организации (enrichment → extract_website):
    # запись с сайтом отбрасывается уже после загрузки карточки.
    if state.PARSE_MODE == "without_website" and raw_url and not aggregator:
        return None

    coords = feature.get("geometry", {}).get("coordinates", [])
    phones = ", ".join(
        p.get("formatted") or p.get("number", "")
        for p in meta.get("Phones", [])
        if p.get("formatted") or p.get("number")
    )
    biz_id = str(meta.get("id", ""))

    return {
        "_biz_id":       biz_id,
        "_raw_feature":  feature,
        "_aggregator_url": aggregator,
        # Сайт в выдаче неизвестен → проверить его на карточке организации.
        "_site_unknown": not raw_url,
        "reviewed":      "",
        "name":          name,
        "category":      ", ".join(c.get("name", "") for c in meta.get("Categories", [])),
        "address":       meta.get("address", ""),
        "phone":         phones,
        # Рейтинг и отзывы видны прямо в выдаче (раньше приходили только
        # с карточки — теперь экономим запросы).
        "rating":        meta.get("rating", ""),
        "reviews_count": meta.get("reviews_count", ""),
        "aggregator_url": aggregator,
        "lat":           coords[1] if len(coords) > 1 else "",
        "lon":           coords[0] if len(coords) > 1 else "",
        "yandex_maps_url": f"https://yandex.ru/maps/org/{biz_id}" if biz_id else "",
        "query":         query,
    }
