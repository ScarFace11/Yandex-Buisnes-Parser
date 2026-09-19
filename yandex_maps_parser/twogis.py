"""
2GIS provider: official Catalog API (Places /3.0/items).

The API returns contacts (website, social links, phones) IN the search
response itself when the key has the contact_groups permission — no
detail-page scraping, no anti-bot. One request ≈ 50 organizations in
~0.5-1s, so a city completes in 1-2 minutes instead of ~40.

Key: free demo key from https://dev.2gis.ru (Platform Manager) → .env:
    TWOGIS_API_KEY = "..."
"""
import threading
import time

from .constants import LINK_AGGREGATORS, SOCIAL_DOMAINS, KNOWN_PLATFORMS
from .extractors import unwrap_outbound
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
#
# name_ex is what the user reads as the org name: {primary: "Шашлыкоff",
# extension: "гриль-бар"}. The plain `name` field is the display string
# "primary, extension" — never use it as the short name.
# items.reviews carries the rating and the review count (both feed the lead
# score). Unlike contact_groups it needs no extra permission on the key.
_FIELDS_FULL = (
    "items.point,items.address_name,items.contact_groups,items.url,"
    "items.name_ex,items.rubrics,items.reviews"
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

# ── Places API quota tracking ──────────────────────────────────
# 2GIS bills 1 token per successful Places request (meta.code 200/204);
# the free tier has a cap of 1,000 requests per CALENDAR MONTH per key.
# 2GIS does NOT expose a live-balance endpoint (Platform Manager shows
# per-day statistics with ~1 day delay), so we count billed requests
# ourselves and PERSIST the counter per month — the number then survives
# app restarts and is the best available estimate of what remains.
_quota_lock = threading.Lock()
_quota_used = 0                     # billed Places requests this process
_quota_base = 0                     # persisted total from previous sessions (this month)
_QUOTA_DEMO_CAP = 1000              # free-tier monthly limit
_QUOTA_WARN_SOFT = 850              # first visual warning
_QUOTA_WARN_HARD = 950              # near-exhausted warning
_quota_soft_warned = False
_quota_hard_warned = False
_quota_stop_fired = False           # «лимит исчерпан — поиск остановлен» (once per run)
_api_limit_stop_fired = False       # 429/limit from the API → warn once + stop
_pages_cap_warned = False           # «2GIS отдаёт максимум 5 страниц» (once per run)
_quota_file_loaded = False


def _quota_file():
    """Path of the persisted monthly counter (output/.2gis_quota.json)."""
    import paths
    return paths.user_dir() / "output" / ".2gis_quota.json"


def _quota_load_locked() -> None:
    """Load the persisted month bucket into _quota_base (caller holds the lock).

    A bucket from a previous month is discarded — the free-tier limit
    resets at the start of each calendar month.
    """
    global _quota_base, _quota_file_loaded
    _quota_file_loaded = True
    try:
        import json
        raw = json.loads(_quota_file().read_text(encoding="utf-8"))
        _quota_base = int(raw.get("used", 0)) if raw.get("month") == time.strftime("%Y-%m") else 0
    except Exception:
        _quota_base = 0


def _quota_save_locked(used: int) -> None:
    """Persist the current month bucket (caller holds the lock)."""
    try:
        import json
        _quota_file().write_text(
            json.dumps({"month": time.strftime("%Y-%m"), "used": int(used)}),
            encoding="utf-8",
        )
    except Exception:
        pass


def quota_used() -> int:
    """Billed Places API requests this month: persisted + this process."""
    with _quota_lock:
        if not _quota_file_loaded:
            _quota_load_locked()
        return _quota_base + _quota_used


def quota_reset_for_new_key() -> None:
    """A NEW 2GIS key was saved: its free-tier quota starts from zero.

    The persisted counter (output/.2gis_quota.json) tracks the SPENT budget
    of the OLD key, so keeping it would show a new key as exhausted. Both
    the persisted file and the in-process counters are wiped; the next
    _quota_count() re-creates the file for the current month.
    """
    global _quota_used, _quota_base, _quota_file_loaded
    global _quota_soft_warned, _quota_hard_warned, _quota_stop_fired
    global _api_limit_stop_fired
    with _quota_lock:
        _quota_used = 0
        _quota_base = 0
        _quota_file_loaded = True
        _quota_soft_warned = False
        _quota_hard_warned = False
        _quota_stop_fired = False
        _api_limit_stop_fired = False
        _quota_save_locked(0)


def quota_spent_this_run() -> int:
    """Billed Places requests spent by THIS process (i.e. this run)."""
    with _quota_lock:
        return _quota_used


def quota_cap() -> int:
    """Free-tier monthly limit (for computing remaining quota in UI)."""
    return _QUOTA_DEMO_CAP


def quota_reset() -> None:
    """Re-arm warning thresholds at the start of a run.

    The 1,000-request free-tier cap is cumulative per key for the whole
    month, so the persisted total is deliberately NOT reset here. If the
    total is already over a threshold when a run starts, warn immediately —
    otherwise the user would burn time on a key that 2GIS has already
    suspended until the next month.
    """
    global _quota_soft_warned, _quota_hard_warned, _quota_stop_fired
    global _api_limit_stop_fired, _pages_cap_warned
    warn_msg = None
    with _quota_lock:
        if not _quota_file_loaded:
            _quota_load_locked()
        total = _quota_base + _quota_used
        _quota_soft_warned = total >= _QUOTA_WARN_SOFT
        _quota_hard_warned = total >= _QUOTA_WARN_HARD
        _quota_stop_fired = False
        _api_limit_stop_fired = False
        _pages_cap_warned = False
        if _quota_hard_warned:
            warn_msg = (
                f"🚨 2GIS Places API: в этом месяце уже израсходовано ~{total}/{_QUOTA_DEMO_CAP} "
                "запросов бесплатного тарифа — лимит исчерпан, ключ приостановлен 2GIS "
                "до следующего месяца. Подключите платный ключ или ждите сброса квоты."
            )
        elif _quota_soft_warned:
            warn_msg = (
                f"⚠ 2GIS Places API: в этом месяце уже израсходовано ~{total}/{_QUOTA_DEMO_CAP} "
                f"запросов бесплатного тарифа — осталось {_QUOTA_DEMO_CAP - total}."
            )
    if warn_msg:
        state.warn(warn_msg)


def _quota_count(n: int = 1) -> None:
    """Record n billed Places requests; warn at the soft/hard thresholds.

    When the monthly cap is reached the run is stopped gracefully: 2GIS
    suspends an exhausted key, so continuing would only produce 429 errors.
    The stop warning fires ONCE per run.
    """
    global _quota_used, _quota_soft_warned, _quota_hard_warned, _quota_stop_fired
    with _quota_lock:
        if not _quota_file_loaded:
            _quota_load_locked()
        _quota_used += n
        used = _quota_base + _quota_used
        _quota_save_locked(used)
        fire_soft = used >= _QUOTA_WARN_SOFT and not _quota_soft_warned
        fire_hard = used >= _QUOTA_WARN_HARD and not _quota_hard_warned
        fire_stop = used >= _QUOTA_DEMO_CAP and not _quota_stop_fired
        if fire_soft:
            _quota_soft_warned = True
        if fire_hard:
            _quota_hard_warned = True
        if fire_stop:
            _quota_stop_fired = True
    # Log outside the lock
    if fire_stop:
        state.warn(
            f"🚨 2GIS Places API: месячный лимит бесплатного тарифа исчерпан "
            f"(~{used}/{_QUOTA_DEMO_CAP}) — поиск остановлен. "
            "Ключ приостанавливается 2GIS до следующего месяца; "
            "подключите платный ключ, чтобы продолжить."
        )
        state.request_stop()
    elif fire_hard:
        state.warn(
            f"🚨 2GIS Places API: израсходовано ~{used}/{_QUOTA_DEMO_CAP} запросов "
            f"бесплатного тарифа за месяц — осталось менее {_QUOTA_DEMO_CAP - used}. "
            "Следующий поиск может не состояться: остановите или подключите платный ключ."
        )
    elif fire_soft:
        state.warn(
            f"⚠ 2GIS Places API: израсходовано ~{used}/{_QUOTA_DEMO_CAP} запросов "
            f"бесплатного тарифа за месяц ({_QUOTA_DEMO_CAP - used} осталось). "
            "Каждый запрос ≈ 10 организаций."
        )


def reset_field_fallback() -> None:
    """Re-enable the full field set (called at the start of each city/run)."""
    global _fields_min_only, _contacts_available
    _fields_min_only = False
    _contacts_available = None


def _human_api_error(code, msg: str, etype: str, query: str, city: str) -> str:
    """Translate a raw 2GIS meta.error into a plain-language warning.

    The raw code/message still reaches developers via state.tech() and the
    run file — the browser log shows only the human version.
    """
    code = int(code or 0)
    msg_low = msg.lower()
    if code == 404 or "not found" in msg_low or etype in ("notfound", "not_found"):
        return (f"В {city or 'городе'} по запросу «{query}» ничего не найдено — "
                "попробуйте другой запрос или уменьшите радиус сетки.")
    if code in (401, 403) or "invalid key" in msg_low or "access denied" in msg_low:
        return ("Ключ 2GIS недействителен или не имеет доступа к этому методу — "
                "проверьте ключ на dev.2gis.ru (Platform Manager).")
    if code == 429 or "limit" in msg_low or "quota" in msg_low:
        return ("Превышен лимит запросов 2GIS — подождите несколько минут "
                "или подключите платный ключ.")
    return (f"Сервис 2GIS временно вернул ошибку (код {code}) — "
            f"поиск по запросу «{query}» пропущен, остальные продолжатся.")


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
    global _fields_min_only, _api_limit_stop_fired

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
    # Quota: only meta.code 200/204 is billed by 2GIS.
    if int(meta.get("code", r.status_code) or 0) in (200, 204):
        _quota_count(1)
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
        # Raw details go to the hidden tech channel + file log; the browser
        # sees a plain-language warning instead of "2GIS API ошибка (404)".
        state.tech(f"2GIS API error: code={meta.get('code')} type={err.get('type')} "
                   f"message={msg!r} query={query!r} city={city!r}")
        human = _human_api_error(meta.get("code"), msg, etype, query, city)
        # Rate/quota limit (429, «limit», «quota»): 2GIS keeps rejecting every
        # next request, so warning per page would spam the log. Warn ONCE,
        # then stop the run gracefully — the key needs a new month or a
        # higher tariff anyway.
        code_i = int(meta.get("code") or 0)
        is_limit_err = (code_i == 429 or "limit" in msg_low or "quota" in msg_low)
        if is_limit_err and not _api_limit_stop_fired:
            # First limit error: warn once in plain language and stop the run
            # gracefully — 2GIS keeps rejecting, so retrying is futile.
            _api_limit_stop_fired = True
            state.warn("🚨 Превышен лимит запросов 2GIS — поиск остановлен. "
                       "Подождите несколько минут или подключите платный ключ.")
            state.request_stop()
        elif not is_limit_err:
            state.warn(human)
        # Limit errors after the first stay silent in the browser log — the
        # raw details are still visible via the tech channel and the file log.
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
    Returns {platform: url} for the four tracked platforms (vk, telegram,
    instagram, whatsapp); URLs of other networks are ignored.

    2GIS may hand out its own outbound wrapper (link.2gis.ru/…?<real-url>)
    instead of the profile URL — unwrap it first, otherwise the export gets
    a 2GIS redirect link that leads nowhere.
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
            url = unwrap_outbound((c.get("url") or c.get("text") or "").strip())
            if not url or not url.startswith("http"):
                continue
            for platform, pattern in SOCIAL_DOMAINS.items():
                if pattern.search(url):
                    socials.setdefault(platform, url)
                    break

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
                url = unwrap_outbound((c.get("url") or c.get("text") or "").strip())
                if url:
                    return url
    return ""


def _rating_reviews(item: dict) -> tuple[object, object]:
    """(rating, reviews_count) from a 2GIS item, or ("", "").

    What the Places API 3.0 actually sends (verified against the live API):

        item.reviews = {
            "general_rating": 5, "general_review_count": 180,   # вся сеть
            "org_rating": 4.7,     "org_review_count": 180,     # ЭТОТ филиал
            "general_review_count_with_stars": 571, …
        }

    The `org_*` pair describes the branch we export, so it wins; `general_*`
    is the network-wide figure and is only a fallback. The generic keys are
    kept for older/other 2GIS responses and for byid payloads.
    """
    def _pick(obj, keys):
        if not isinstance(obj, dict):
            return None
        for k in keys:
            v = obj.get(k)
            if v not in (None, ""):
                return v
        return None

    rev = item.get("reviews")
    rating = _pick(rev, ("org_rating", "general_rating",
                         "rating", "value", "rating_value"))
    reviews = _pick(rev, ("org_review_count", "general_review_count",
                          "review_count", "count", "reviews_count"))
    if rating is None:
        rating = _pick(item.get("rating"), ("value", "rating"))
    if reviews is None:
        reviews = item.get("reviews_count") or None
    return (rating if rating is not None else "",
            reviews if reviews is not None else "")


def _name_and_category(item: dict) -> tuple[str, str]:
    """Split a 2GIS item into (short name, category).

    The API returns three overlapping strings:
        name           = "Шашлыкоff, гриль-бар"   (primary + ", " + extension)
        name_ex.primary   = "Шашлыкоff"            (the brand — NOT a category)
        name_ex.extension = "гриль-бар"            (what the place is)
        rubrics[]         = [{"kind": "primary", "name": "Бары"}, …]

    The export used to put `primary` into the category column, so every row
    read «Название: Шашлыкоff, гриль-бар / Категория: Шашлыкоff». Now the
    name is the brand and the category is the business type: extension
    first (что именно за место), then the primary rubric from 2GIS.
    """
    ex = item.get("name_ex") if isinstance(item.get("name_ex"), dict) else {}
    primary = str(ex.get("primary") or "").strip()
    ext = str(ex.get("extension") or "").strip()

    full = str(item.get("name") or "").strip()
    name = primary or full

    category = ext
    if not category and ", " in full:
        # No name_ex: the display name is "brand, type" — the type part
        # is the category.
        category = full.rsplit(", ", 1)[1].strip()
    if not category:
        for rub in item.get("rubrics") or []:
            if isinstance(rub, dict) and str(rub.get("kind") or "").lower() == "primary":
                category = str(rub.get("name") or "").strip()
                break

    # Drop the ", <тип>" tail from the name when it is still there.
    if category and name.endswith(f", {category}"):
        name = name[: -len(f", {category}")].strip()
    return name, category


def parse_item(item: dict, query: str) -> dict | None:
    """
    Convert a 2GIS item into a candidate record (same shape as
    search.parse_feature) so enrichment and exports work unchanged.

    Returns None if the org has no name or fails the PARSE_MODE filter
    (same semantics as the Yandex path).
    """
    from .extractors import _is_aggregator

    name, category = _name_and_category(item)
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

    point = item.get("point") or {}
    phones = ", ".join(_phones_from_contacts(groups))
    org_id = str(item.get("id") or "")

    # Rating/reviews come free with the search response (items.reviews) — the
    # lead score needs the real numbers. Several shapes are accepted because
    # the API wraps them differently per version (and older exports/tests use
    # {"rating": {"value": …}} / {"reviews": {"count": …}}).
    # Missing data stays empty — never a fake 0.0.
    rating, reviews_count = _rating_reviews(item)


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
        "category":       category,
        "address":        item.get("address_name") or "",
        "phone":          phones,
        "rating":         rating if rating not in (None, "") else "",
        "reviews_count":  reviews_count if reviews_count not in (None, "") else "",
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
    global _contacts_available, _pages_cap_warned

    candidates: list[dict] = []
    found_total: int | None = None
    new_total: int = 0

    # Honesty guard: the 2GIS Catalog API never returns more than 5 pages
    # (5 × 10 = 50 organizations per search point). If the user asked for
    # more, say so once per run instead of silently ignoring the setting.
    if state.MAX_PAGES > _MAX_PAGE and not _pages_cap_warned:
        _pages_cap_warned = True
        state.warn(
            f"ℹ 2GIS отдаёт максимум {_MAX_PAGE} страниц ({_MAX_PAGE * _PAGE_SIZE} организаций с одной точки) — "
            f"настройка «Страниц: {state.MAX_PAGES}» будет ограничена до {_MAX_PAGE}. "
            "Чтобы собрать больше, включите сетку («Покрытие города») — каждая точка получает свой лимит."
        )

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
