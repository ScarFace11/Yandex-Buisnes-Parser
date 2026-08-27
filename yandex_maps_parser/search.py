"""
Yandex Maps Search API: page fetching and feature parsing.
"""
from .constants import KNOWN_PLATFORMS
from .http_client import _get
from . import state


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
        state.warn("Нет ответа от Search API — проверьте сеть или прокси.")
        return [], None
    if r.status_code == 403:
        state.warn(
            "Search API вернул 403 — ключ недействителен или лимит исчерпан. "
            "Проверьте YANDEX_API_KEY в config.py и квоты в кабинете разработчика."
        )
        return [], None
    if r.status_code != 200:
        state.warn(f"Search API вернул {r.status_code}: {r.text[:200]}")
        return [], None
    try:
        data = r.json()
        if "error" in data:
            state.warn(f"Search API ошибка: {data['error']} — {data.get('message', '')}")
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
    Returns None if the business should be skipped (has a real website, or
    does not meet quality filters).
    """
    from .extractors import _is_aggregator

    props = feature.get("properties", {})
    meta  = props.get("CompanyMetaData", {})

    name = meta.get("name", "").strip()
    if not name:
        return None

    raw_url    = meta.get("url", "").strip()
    aggregator = ""

    if raw_url:
        if _is_aggregator(raw_url):
            aggregator = raw_url
        else:
            return None  # real website → skip

    rating_obj  = meta.get("rating") or {}
    rating_val  = float(rating_obj.get("score", 0) or 0) if isinstance(rating_obj, dict) else 0.0
    reviews_val = int(rating_obj.get("count", 0) or 0)   if isinstance(rating_obj, dict) else 0

    if state.MIN_RATING  > 0 and rating_val  < state.MIN_RATING:  return None
    if state.MIN_REVIEWS > 0 and reviews_val < state.MIN_REVIEWS: return None

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
        "description":   "",
        "address":       meta.get("address", ""),
        "phone":         phones,
        "hours":         meta.get("Hours", {}).get("text", ""),
        # Keep the review count numeric all the way to Excel.  A string value
        # makes Excel sort it lexicographically ("9" before "100") instead of
        # by the actual number of reviews.
        "rating":        str(rating_val) if rating_val else "",
        "reviews":       reviews_val,
        "aggregator_url": aggregator,
        "lat":           coords[1] if len(coords) > 1 else "",
        "lon":           coords[0] if len(coords) > 1 else "",
        "yandex_maps_url": f"https://yandex.ru/maps/org/{biz_id}" if biz_id else "",
        "query":         query,
    }
