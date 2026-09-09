"""
2GIS provider: official Catalog API (Places /3.0/items).

The API returns contacts (website, social links, phones) IN the search
response itself when the key has the contact_groups permission — no
detail-page scraping, no anti-bot. One request ≈ 50 organizations in
~0.5-1s, so a city completes in 1-2 minutes instead of ~40.

Key: free demo key from https://dev.2gis.ru (Platform Manager) → .env:
    TWOGIS_API_KEY = "..."
"""
import time

from .constants import LINK_AGGREGATORS, SOCIAL_DOMAINS, KNOWN_PLATFORMS
from .http_client import _get
from . import state

_API_URL = "https://catalog.api.2gis.com/3.0/items"

# API hard limits: page_size must be 1..10 and page must be 1..5 (NOT 50
# pages like Yandex — violating either produces an error INSIDE an HTTP-200
# body: "Length of parameter 'page' should be from 1 to 5"). So one search
# point yields at most 5 x 10 = 50 organizations; use the grid for more.
_PAGE_SIZE = 10
_MAX_PAGE = 5

# contact_groups may require a permission on some keys; fall back to the
# minimal field set (base data only) rather than failing the whole run.
_FIELDS_FULL = (
    "items.point,items.address_name,items.contact_groups,items.url,"
    "items.rating,items.reviews,items.hours,items.name_ex"
)
_FIELDS_MIN = "items.point,items.address_name"

# Module flags (reset at the start of each city/run):
# _fields_min_only — the key rejected the full field set, stay minimal.
# _contacts_available — None until the first successful page; True when the
#   key returns contact_groups (then socials come straight from the API),
#   False when the key strips the field (demo keys) — in that case every
#   record needs a fallback fetch of its 2gis.ru firm page via CDP.
_fields_min_only = False
_contacts_available: bool | None = None


def reset_field_fallback() -> None:
    """Re-enable the full field set (called at the start of each city/run)."""
    global _fields_min_only, _contacts_available
    _fields_min_only = False
    _contacts_available = None


def search_items(
    query: str, city: str, lat: float, lon: float, page: int, session=None
) -> tuple[list[dict], int | None]:
    """
    Fetch one page (up to _PAGE_SIZE orgs) from the 2GIS Catalog API.

    Returns (items, total): total is result.total for the query (or None).
    page is 0-based here; the API is 1-based.

    IMPORTANT: 2GIS returns errors inside an HTTP-200 body as
    meta.error — a 200 status does NOT mean the request succeeded.
    """
    global _fields_min_only

    params: dict = {
        "q": f"{query} {city}".strip(),
        "location": f"{lon},{lat}",
        "page": page + 1,          # 2GIS pages are 1-based
        "page_size": _PAGE_SIZE,   # API max is 10
        "key": state.TWOGIS_API_KEY,
    }
    # Geo-restriction: with the grid on, each search is bound to its cell
    # (radius ~1.5× step so cells overlap slightly and nothing is missed).
    if state.USE_GRID:
        params["point"] = f"{lon},{lat}"
        params["radius"] = max(1000, int(state.GRID_STEP_KM * 1500))

    fields = _FIELDS_MIN if _fields_min_only else _FIELDS_FULL
    r = _get(_API_URL, params={**params, "fields": fields}, session=session)

    if not r:
        state.warn("Нет ответа от 2GIS API — проверьте сеть или ключ.")
        return [], None

    # 2GIS signals errors in the BODY (meta.error) even with HTTP 200.
    try:
        data = r.json()
    except Exception:
        state.warn(f"2GIS API: некорректный ответ (HTTP {r.status_code})")
        return [], None

    meta = data.get("meta") or {}
    err = meta.get("error")
    if err:
        msg  = str(err.get("message") or err)[:160]
        etype = str(err.get("type") or "").lower()
        msg_low = msg.lower()
        # Field/permission problem with the full field set → retry once with
        # the minimal set instead of failing the whole run.
        if (
            not _fields_min_only
            and ("field" in msg_low or "permission" in msg_low or "forbidden" in etype)
        ):
            state.syslog(f"twogis: field set rejected ({msg[:80]}), retrying with minimal fields")
            _fields_min_only = True
            return search_items(query, city, lat, lon, page, session=session)
        state.warn(f"2GIS API ошибка ({meta.get('code')}): {msg}")
        return [], None

    result = data.get("result") or {}
    total = result.get("total")
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = None
    return result.get("items", []) or [], total


def _socials_from_contacts(contact_groups: list) -> dict[str, str]:
    """Extract social URLs from items.contact_groups.

    A group entry looks like:
        {"contacts": [{"type": "social_network", "url": "https://vk.com/..."}]}
    Returns {platform: url} for KNOWN_PLATFORMS plus "other_socials_list".
    """
    socials: dict[str, str] = {}
    for group in contact_groups or []:
        if not isinstance(group, dict):
            continue
        for c in group.get("contacts", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") not in ("social_network", "messenger", "social"):
                continue
            url = (c.get("url") or c.get("text") or "").strip()
            if not url or not url.startswith("http"):
                continue
            for platform, pattern in SOCIAL_DOMAINS.items():
                if pattern.search(url):
                    socials.setdefault(platform, url)
                    break
            else:
                socials.setdefault("other_socials_list", url)
    return socials


def _phones_from_contacts(contact_groups: list) -> list[str]:
    phones: list[str] = []
    for group in contact_groups or []:
        if not isinstance(group, dict):
            continue
        for c in group.get("contacts", []) or []:
            if isinstance(c, dict) and c.get("type") == "phone":
                ph = (c.get("text") or c.get("url") or "").strip()
                if ph and ph not in phones:
                    phones.append(ph)
    return phones


def _website_from_contacts(contact_groups: list) -> str:
    for group in contact_groups or []:
        if not isinstance(group, dict):
            continue
        for c in group.get("contacts", []) or []:
            if isinstance(c, dict) and c.get("type") in ("website", "site"):
                url = (c.get("url") or c.get("text") or "").strip()
                if url:
                    return url
    return ""


def parse_item(item: dict, query: str) -> dict | None:
    """
    Convert a 2GIS item into a candidate record (same shape as
    search.parse_feature) so enrichment and exports work unchanged.

    Returns None if the org has no name or fails quality filters
    (PARSE_MODE / MIN_RATING / MIN_REVIEWS — same semantics as Yandex).
    """
    from .extractors import _is_aggregator

    name = (item.get("name") or "").strip()
    if not name:
        return None

    groups  = item.get("contact_groups") or []
    website = _website_from_contacts(groups)
    aggregator = ""
    if website and any(agg in website.lower() for agg in LINK_AGGREGATORS):
        aggregator = website
        website = ""

    # «Только без сайтов»: skip orgs with their own website (link
    # aggregators are NOT websites — kept), same as the Yandex path.
    # NOTE: when the key does not return contacts, the website is unknown —
    # every org passes this filter and the fallback firm-page fetch decides
    # socials later (PARSE_MODE cannot be enforced without the data).
    if state.PARSE_MODE == "without_website" and website:
        return None

    rating_obj  = item.get("rating") or {}
    rating_val  = float(rating_obj.get("value", 0) or 0) if isinstance(rating_obj, dict) else 0.0

    # reviews comes in different shapes depending on the key/fields:
    #   {"count": N}  |  {"org_review_count_with_stars": N,
    #                    "general_review_count_with_stars": M}  |  plain N
    reviews_obj = item.get("reviews")
    if isinstance(reviews_obj, dict):
        reviews_val = int(
            reviews_obj.get("count")
            or reviews_obj.get("org_review_count_with_stars")
            or reviews_obj.get("general_review_count_with_stars")
            or 0
        )
    elif isinstance(reviews_obj, (int, float)):
        reviews_val = int(reviews_obj)
    else:
        reviews_val = 0

    point = item.get("point") or {}
    phones = ", ".join(_phones_from_contacts(groups))
    org_id = str(item.get("id") or "")

    if state.MIN_RATING  > 0 and rating_val  < state.MIN_RATING:  return None
    if state.MIN_REVIEWS > 0 and reviews_val < state.MIN_REVIEWS: return None

    hours_obj = item.get("hours") or {}
    hours = hours_obj.get("display_text", "") if isinstance(hours_obj, dict) else ""

    # _skip_detail: True → enrichment trusts the API payload (contacts were
    # in the search response). False → enrichment renders the firm page via
    # CDP to extract socials (demo keys strip contact_groups).
    return {
        "_biz_id":        org_id,
        "_raw_feature":   item,          # enrich() extracts socials from this JSON
        "_aggregator_url": aggregator,
        "_skip_detail":   bool(_contacts_available),
        "_detail_url":    f"https://2gis.ru/firm/{org_id}" if org_id else "",
        "reviewed":       "",
        "name":           name,
        "category":       (item.get("name_ex") or {}).get("primary", "") if isinstance(item.get("name_ex"), dict) else "",
        "description":    "",
        "address":        item.get("address_name") or "",
        "phone":          phones,
        "hours":          hours,
        "rating":         str(rating_val) if rating_val else "",
        "reviews":        reviews_val,
        "aggregator_url": aggregator,
        "website":        website,
        "lat":            point.get("lat", "") if isinstance(point, dict) else "",
        "lon":            point.get("lon", "") if isinstance(point, dict) else "",
        "yandex_maps_url": "",
        "twogis_url":     f"https://2gis.ru/firm/{org_id}" if org_id else "",
        "query":          query,
    }


def collect_candidates_2gis(
    query: str,
    city: str,
    lat: float,
    lon: float,
    seen_urls: set[str],
    pbar_search,
    pbar_detail,
    seen_lock=None,
    search_session=None,
) -> tuple[list[dict], int | None, int]:
    """2GIS search phase — same contract as enrichment.collect_candidates.

    Returns (candidates, found, new_candidates). All contact data comes with
    the search response, so enrichment only merges socials from the raw JSON
    (no page fetching at all).
    """
    global _contacts_available

    candidates: list[dict] = []
    found_total: int | None = None
    new_total: int = 0

    for page in range(max(1, min(state.MAX_PAGES, _MAX_PAGE))):
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            break
        if state.is_skip_city():
            break

        items, total = search_items(query, city, lat, lon, page, session=search_session)
        state.syslog(f"twogis search: query={query}, city={city}, page={page + 1}, items={len(items)}, total={total}")
        if found_total is None and total is not None:
            found_total = total
        if not items:
            break

        # Decide once (first non-empty page) whether the key returns contacts.
        # Without them the search response has no socials at all — every
        # record then needs the CDP firm-page fallback during enrichment.
        if _contacts_available is None:
            _contacts_available = any("contact_groups" in it for it in items)
            state.syslog(f"twogis: contact_groups in response: {_contacts_available}")

        new_this_page = 0
        deduped = 0
        for it in items:
            rec = parse_item(it, query)
            if rec is None:
                continue
            uid = rec.get("_biz_id") or rec.get("twogis_url") or rec.get("name", "").lower()
            if not uid:
                continue
            if seen_lock:
                with seen_lock:
                    if uid in seen_urls:
                        deduped += 1
                        continue
                    seen_urls.add(uid)
            else:
                if uid in seen_urls:
                    deduped += 1
                    continue
                seen_urls.add(uid)
            candidates.append(rec)
            new_this_page += 1
        new_total += new_this_page

        if hasattr(pbar_search, "update"):
            pbar_search.update(len(items))
        state.syslog(f"  twogis page {page + 1}: {len(items)} items, {new_this_page} new, {deduped} deduped")

        max_cand = getattr(state, "MAX_CANDIDATES_PER_CITY", 0)
        if max_cand > 0 and len(candidates) >= max_cand:
            state.syslog(f"  candidate limit reached: {len(candidates)}/{max_cand}")
            break
        if len(items) < _PAGE_SIZE:
            break
        time.sleep(0.3)

    if hasattr(pbar_detail, "total"):
        pbar_detail.total = (pbar_detail.total or 0) + len(candidates)
        pbar_detail.refresh()
    state.syslog(f"twogis collect_candidates: query={query}, city={city}, candidates={len(candidates)}")
    return candidates, found_total, new_total
