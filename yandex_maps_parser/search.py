"""
Yandex Maps Search API: page fetching and feature parsing.
"""
from .constants import KNOWN_PLATFORMS
from .http_client import _get
from . import state


def _human_search_error(status: int, query: str, city: str, body: str = "") -> str:
    """Plain-language version of a Search API failure (details → tech channel)."""
    if status == 403:
        return ("API-ключ Яндекса отклонён или лимит исчерпан — проверьте ключ "
                "и квоты в кабинете разработчика Яндекса.")
    if status == 404:
        return (f"В {city or 'городе'} по запросу «{query}» ничего не найдено — "
                "попробуйте другой запрос.")
    return (f"Сервис Яндекс.Карт временно вернул ошибку (код {status}) — "
            "поиск продолжится.")


def search_page(
    query: str, city: str, lat: float, lon: float, skip: int, session=None
) -> tuple[list[dict], int | None]:
    """
    Fetch one page (up to 50 results) from the Yandex Maps Search API.

    Returns (features, found): found is the API's total count of businesses
    matching the query near (lat, lon), or None if the response didn't carry
    it / the request failed. The caller uses `found` for adaptive grid logic.
    """
    r = _get(
        "https://search-maps.yandex.ru/v1/",
        session=session,
        params={
            "text":    f"{query} {city}",
            "lang":    "ru_RU",
            "ll":      f"{lon},{lat}",
            "type":    "biz",
            "results": 50,
            "skip":    skip,
            "apikey":  state.YANDEX_API_KEY,
        },
    )
    if not r:
        state.warn("Нет ответа от сервиса поиска — проверьте подключение к интернету.")
        state.tech("search: empty response from Search API")
        return [], None
    if r.status_code == 403:
        state.tech(f"search: HTTP 403, body={r.text[:300]!r}")
        state.warn(_human_search_error(403, query, city))
        return [], None
    if r.status_code != 200:
        state.tech(f"search: HTTP {r.status_code}, body={r.text[:300]!r}")
        state.warn(_human_search_error(r.status_code, query, city, r.text[:200]))
        return [], None
    try:
        data = r.json()
        if "error" in data:
            state.tech(f"search: API error payload: {str(data)[:300]!r}")
            state.warn(_human_search_error(
                int(data.get("statusCode", 0) or 0), query, city,
                str(data.get("message", ""))))
            return [], None
        found = None
        try:
            found = int(
                data["properties"]["responseMetaData"]["SearchResponse"]["found"]
            )
        except (KeyError, TypeError, ValueError):
            found = None
        return data.get("features", []), found
    except Exception:
        return [], None


def parse_feature(feature: dict, query: str) -> dict | None:
    """
    Convert a GeoJSON feature from the Search API into a candidate record.
    Returns None only if the business has no name or fails quality filters.
    Websites are no longer filtered — social links are checked post-enrichment
    on the Yandex Maps detail page.
    """
    from .extractors import _is_aggregator

    props = feature.get("properties", {})
    meta  = props.get("CompanyMetaData", {})

    name = meta.get("name", "").strip()
    if not name:
        return None

    raw_url    = meta.get("url", "").strip()
    aggregator = ""

    if raw_url and _is_aggregator(raw_url):
        aggregator = raw_url

    # Parse mode "without_website": skip businesses that have their own
    # website. Link aggregators (taplink/linktree) are NOT websites — they
    # are link pages — so they are kept (they count as «без сайта»).
    # The web-form toggle switches this to "all" to parse everything.
    if state.PARSE_MODE == "without_website" and raw_url and not aggregator:
        return None



    coords = feature.get("geometry", {}).get("coordinates", [])
    phones = ", ".join(
        p.get("formatted") or p.get("number", "")
        for p in meta.get("Phones", [])
        if p.get("formatted") or p.get("number")
    )
    biz_id = meta.get("id", "")

    return {
        "_biz_id":       biz_id,
        "_raw_feature":  feature,
        "_aggregator_url": aggregator,
        "reviewed":      "",
        "name":          name,
        "category":      ", ".join(c.get("name", "") for c in meta.get("Categories", [])),
        "address":       meta.get("address", ""),
        "phone":         phones,
        # Rating/reviews are not in the Search API payload — enrich() fills
        # them from the detail page JSON when cards are being fetched.
        "rating":        "",
        "reviews_count": "",
        "aggregator_url": aggregator,
        "lat":           coords[1] if len(coords) > 1 else "",
        "lon":           coords[0] if len(coords) > 1 else "",
        "yandex_maps_url": f"https://yandex.ru/maps/org/{biz_id}" if biz_id else "",
        "query":         query,
    }
