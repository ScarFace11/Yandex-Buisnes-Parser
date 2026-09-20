"""
HTML / text extraction: social links, emails, descriptions, reviews.
"""
import json
import re

from .constants import (
    LINK_AGGREGATORS,
    SOCIAL_DOMAINS,
    EXCLUDE_URLS,
)
from .http_client import _worker_client, _get
from . import state

# ── Compiled patterns ─────────────────────────────────────────

_UTM_RE = re.compile(
    r'[?&](utm_\w+|ref|from|fbclid|gclid|yclid|si|igshid)=[^&]*', re.I
)
_TRAILING_RE = re.compile(r'[?&]$')

_VK_NON_PROFILE = re.compile(
    r'vk\.com/(wall|photo|video|album|doc|club(?=[?#])|app|feed|away|share|'
    r'login|join|invite|oauth|im|search|explore|fave|bookmarks)\b',
    re.I,
)
_IG_NON_PROFILE = re.compile(
    r'instagram\.com/(p|reel|tv|stories|explore|accounts|'
    r'ar|challenge|static|_n|sharer)\b',
    re.I,
)
_FB_NON_PROFILE = re.compile(
    r'facebook\.com/(permalink|share|dialog|plugins|login|photo|video|'
    r'events|groups(?=/[0-9])|pages/create|sharer|tr\b|ads\b|pixel|'
    r'watch|gaming|marketplace|policies|privacy|business|settings|recover|reg)\b',
    re.I,
)
_YOUTUBE_NON_PROFILE = re.compile(
    r'youtube\.com/(embed|watch|playlist|live|attribution_link|redirect|'
    r'howyoutubeworks|about|press|creators)\b',
    re.I,
)
_TIKTOK_NON_PROFILE = re.compile(
    r'tiktok\.com/(embed|discover|explore|trending|music|tag|share|upload|search)\b',
    re.I,
)
_OK_NON_PROFILE = re.compile(
    r'ok\.ru/(video|live|search|market|app|mail|feed|groups|sticker|emoji|dk)\b',
    re.I,
)
_TWITTER_NON_PROFILE = re.compile(
    r'(?:twitter|x\.com)/(intent|share|search|home|hashtag|explore|settings|'
    r'notifications|messages|compose|status|i/)\b',
    re.I,
)

_JSON_BLOB_RE = re.compile(
    r'(?:window\.(?:__)?(?:NUXT|INITIAL_STATE|SERVER_STATE|PRELOADED_STATE|'
    r'APP_STATE|REDUX_STATE|DATA|STATE)(?:__)?'
    r'|window\.serverState'
    # NOTE: whitespace is allowed on BOTH sides of the «=» — pages are not
    # always minified (`window.__INITIAL_STATE__ = {` used to match nothing,
    # so both the socials and the rating/reviews of such a page were lost).
    r'|<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
    r'|<script[^>]+type=["\']application/json["\'][^>]*>)\s*[=]*\s*(\{)',
    re.I,
)

_ANTIBOT_MARKERS = (
    "showcaptcha", "robot", "captcha", "i-am-not-robot",
    "access denied", "too many requests",
)

# Fast pre-check: does this string look like it could contain social URLs?
_HTTP_LIKE = re.compile(r'https?://[^\s"\'<>\\\\,}{]+', re.I)

# 2GIS wraps every outbound link in its own redirect:
#     http://link.2gis.ru/1.2/<token>/…/null/<hash>?https://vk.com/club1
# The wrapper URL matches no social pattern, but its TARGET does — and the
# normalized result used to be the wrapper itself (a dead 2GIS link shown
# in the ВКонтакте/Telegram columns). The host list also covers the mirror
# domains (2gis.by/2gis.kz) seen in exported files.
_OUTBOUND_WRAPPER = re.compile(
    r"^https?://(?:[\w.-]+\.)?(?:link\.)?2gis\.(?:ru|com|kz|by|uz)/", re.I
)


def unwrap_outbound(url: str, _depth: int = 0) -> str:
    """Return the real target behind a 2GIS outbound link wrapper.

    `link.2gis.ru/…?https://vk.com/profile` → `https://vk.com/profile`.
    Anything else (including a wrapper without a target, which leads
    nowhere) is returned unchanged; a wrapper that can't be resolved
    resolves to "" so it never lands in a social column.
    """
    u = (url or "").strip()
    if not u or not _OUTBOUND_WRAPPER.match(u) or _depth > 3:
        return u
    _, sep, tail = u.partition("?")
    if not sep:
        return ""                      # wrapper with no target — dead link
    from urllib.parse import unquote
    tail = unquote(tail).strip()
    if not tail.lower().startswith("http"):
        return ""
    return unwrap_outbound(tail, _depth + 1)


# ── URL helpers ───────────────────────────────────────────────

def _is_aggregator(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == agg or host.endswith("." + agg) for agg in LINK_AGGREGATORS)
    except Exception:
        return False


def _clean_social_url(url: str) -> str:
    """Remove UTM / tracking parameters from a social URL."""
    url = _UTM_RE.sub("", url)
    url = _TRAILING_RE.sub("", url)
    return url.rstrip("/.,);\"'")


def _normalize_social_url(platform: str, url: str) -> str | None:
    """Return a canonical profile URL, or None if the URL is not a profile."""
    from urllib.parse import urlparse, urlunparse
    try:
        parsed = urlparse(url)
        # Social pages are served over https; pages hand out plain http://
        # links (2GIS firm pages do) and the exported column then looks
        # untrustworthy/broken in Excel.
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
        if platform == "vk":
            if _VK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "instagram":
            if _IG_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "facebook":
            if _FB_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "youtube":
            if _YOUTUBE_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "tiktok":
            if _TIKTOK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "ok":
            if _OK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "twitter":
            if _TWITTER_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "telegram":
            return urlunparse(parsed._replace(query="", fragment=""))
        return urlunparse(parsed._replace(fragment=""))
    except Exception:
        return url


# ── Fetch ─────────────────────────────────────────────────────
# NOTE: No sleep here — the token bucket in http_client._get() already
# paces requests globally. The old per-thread sleep was redundant and
# doubled the wall-clock time of the detail-fetch phase.

def fetch_html(url: str, session=None, biz_id: str = "") -> str:
    """Fetch a detail page, with disk cache support.

    If biz_id is provided, checks the disk cache first.  On cache hit,
    returns the cached HTML without making an HTTP request.
    """
    # Try cache first
    if biz_id:
        try:
            from .cache import get_cached
            cached = get_cached(biz_id)
            if cached:
                state.syslog(f"cache_hit: biz_id={biz_id}")
                return cached
        except Exception:
            pass

    # (connect, read, total): the read timeout is per-chunk, so a page that
    # drips bytes can stay under it for minutes. The 60s TOTAL is a hard
    # wall-clock deadline — Yandex throttles plain HTTP hard (p95 was
    # 187-325s per page), and we'd rather skip a page than burn 5 minutes.
    # retries=2 (not the global 3): a second 60s-deadline attempt rarely
    # beats the first, and the third costs another minute per throttled page.
    with state._detail_semaphore:
        r = _get(url, session=session or _worker_client(), timeout=(8, 15, 60), retries=2)
    if not r or r.status_code != 200:
        return ""
    text = r.text
    lower = text[:4000].lower()
    if any(m in lower for m in _ANTIBOT_MARKERS):
        state.warn("Яндекс вернул anti-bot страницу — детали этой карточки пропущены.")
        # Trigger adaptive backoff in http_client
        try:
            from .http_client import _anti_bot_detected
            _anti_bot_detected()
        except Exception:
            pass
        return ""
    # Store in cache
    if biz_id:
        try:
            from .cache import set_cached
            set_cached(biz_id, text)
        except Exception:
            pass
    return text


# ── Extractors ────────────────────────────────────────────────

def _collect_url_strings(obj, depth: int = 0, limit: int = 200) -> list[str]:
    """Recursively collect string values that look like URLs from a decoded object."""
    out: list[str] = []

    def walk(o, d: int) -> None:
        if len(out) >= limit or d > 8:
            return
        if isinstance(o, str):
            if "http" in o:  # fast pre-check, avoids regex on non-URL strings
                out.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v, d + 1)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v, d + 1)

    walk(obj, depth)
    return out


def _extract_from_json_blob(html: str) -> dict[str, str]:
    r"""Parse embedded JSON blobs in a Yandex Maps page and extract socials.

    Uses JSONDecoder.raw_decode so deeply nested objects are parsed correctly
    and escaped URLs like "https:\/\/vk.com\/club1" come back unescaped.
    Limits parsing to the first 200KB to avoid slow parsing of huge pages.
    """
    result: dict[str, str] = {}
    # Only parse the first 200KB — social links are always near the top
    text = html[:200_000]
    decoder = json.JSONDecoder()
    for m in _JSON_BLOB_RE.finditer(text):
        start = m.start(1)
        try:
            obj, _ = decoder.raw_decode(text, start)
        except (ValueError, json.JSONDecodeError):
            continue
        for url in _collect_url_strings(obj):
            url = _clean_social_url(unwrap_outbound(url))
            if not url or EXCLUDE_URLS.search(url):
                continue
            for platform, pat in SOCIAL_DOMAINS.items():
                if platform not in result and pat.search(url):
                    normalized = _normalize_social_url(platform, url)
                    if normalized:
                        result[platform] = normalized
                    break
        if len(result) >= 3:
            break
    return result


_RATING_KEYS = ("ratingvalue", "rating", "score", "votesscore")
_REVIEWS_KEYS = ("reviewscount", "reviewscountvalue", "reviewcount", "reviews")


def _num(value):
    """Coerce a JSON value to float/int, or None when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None


def _find_numbers(obj, keys, depth: int = 0):
    """Depth-first search for the first numeric value under any of `keys`.

    Yandex embeds the business card as a JSON blob whose exact nesting differs
    between page builds, so we look up by key name instead of by path.
    """
    if depth > 10 or obj is None:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in keys:
                num = _num(value)
                if num is not None:
                    return num
                # `"rating": {"value": 4.5}` and `"reviews": {"count": 7}`
                if isinstance(value, dict):
                    for sub in ("value", "count", "countValue", "ratingValue"):
                        num = _num(value.get(sub))
                        if num is not None:
                            return num
        for value in obj.values():
            num = _find_numbers(value, keys, depth + 1)
            if num is not None:
                return num
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            num = _find_numbers(value, keys, depth + 1)
            if num is not None:
                return num
    return None


def extract_rating_reviews(html: str) -> tuple[object, object]:
    """Pull (rating, reviews_count) out of a Yandex Maps page, or ("", "").

    Reads the same embedded JSON blob that socials come from, so it costs no
    extra request. Returns empty strings when the page has no such data —
    callers must not turn that into 0.0/0.
    """
    if not html:
        return "", ""
    text = html[:200_000]
    decoder = json.JSONDecoder()
    rating = reviews = None
    for m in _JSON_BLOB_RE.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, m.start(1))
        except (ValueError, json.JSONDecodeError):
            continue
        if rating is None:
            rating = _find_numbers(obj, _RATING_KEYS)
        if reviews is None:
            reviews = _find_numbers(obj, _REVIEWS_KEYS)
        if rating is not None and reviews is not None:
            break
    # Ratings arrive on a 5-point scale, but some page builds embed a ×10
    # value (4.7 → 47). Normalize those (same rule as lead_score.compute_score)
    # instead of dropping them; anything else is not a rating (a vote count,
    # a year…) and is discarded rather than guessed.
    if rating is not None:
        if 5 < rating <= 50:
            rating = rating / 10
        if not 0 <= rating <= 5:
            rating = None
    rating_out = round(rating, 1) if rating else ""
    reviews_out = int(reviews) if reviews else ""
    return rating_out, reviews_out


def extract_socials(text: str) -> dict[str, str]:
    """Extract real social-profile links (URLs only — no fabrication from
    phone numbers or @mentions in arbitrary text)."""
    result: dict[str, str] = {}
    for url in _HTTP_LIKE.findall(text):
        url = _clean_social_url(unwrap_outbound(url))
        if not url or EXCLUDE_URLS.search(url):
            continue
        for platform, pat in SOCIAL_DOMAINS.items():
            if platform not in result and pat.search(url):
                normalized = _normalize_social_url(platform, url)
                if normalized:
                    result[platform] = normalized
                break
    return result


# ── Телефон из карточки ──────────────────────────────────
# Used as a fallback when the source did not hand out a phone in its API
# response (2GIS strips contact_groups for demo keys; the Yandex Search API
# does not always include Phones). Card pages render the contact phone as a
# `tel:` link, so that link is by far the most reliable signal.
_TEL_LINK_RE = re.compile(r'href=["\']tel:([+\d\s()\-]{7,25})["\']', re.I)
# Scripts/styles are cut out before the loose text pass: otherwise any
# 11-digit number in the page state (a view counter, an id) reads as a phone.
_SCRIPT_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_PHONE_TEXT_RE = re.compile(
    r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
)


def _phone_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _format_phone(digits: str) -> str:
    """10/11 digits → «+7 XXX XXX-XX-XX»; anything else is not a phone.

    8-800-X… hotlines («+7 800 …») are rejected: they are support lines of
    the platform or of a franchise head office, never the number to call the
    owner about a website.
    """
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78":
        return ""
    digits = "7" + digits[1:]
    if digits[1:4] == "800":
        return ""
    return f"+{digits[0]} {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:]}"


# Keys under which embedded page data carries a phone number.
_PHONE_KEYS = ("phone", "phonenumber", "phone_number", "telephone", "contactphone")


def _phone_from_json(value, depth: int = 0) -> str:
    """First phone-shaped value stored under a phone-ish key in embedded data.

    Yandex and 2GIS both ship the business card as JSON inside the page; a
    phone that the UI hides behind «Показать телефон» is usually already in
    that data. Only explicitly phone-named keys count — this never scrapes a
    random number out of unrelated state.
    """
    if depth > 12 or value is None:
        return ""
    if isinstance(value, dict):
        for key, sub in value.items():
            if str(key).lower() not in _PHONE_KEYS:
                continue
            cand = sub
            if isinstance(cand, dict):
                cand = cand.get("value") or cand.get("text") or cand.get("number") or ""
            if isinstance(cand, (list, tuple)):
                cand = next((x for x in cand if isinstance(x, str)), "")
            if isinstance(cand, (int, float)):
                cand = str(cand)
            if isinstance(cand, str):
                phone = _format_phone(_phone_digits(cand))
                if phone:
                    return phone
        for sub in value.values():
            phone = _phone_from_json(sub, depth + 1)
            if phone:
                return phone
    elif isinstance(value, (list, tuple)):
        for sub in value:
            phone = _phone_from_json(sub, depth + 1)
            if phone:
                return phone
    return ""


def extract_phone(html: str) -> str:
    """Первый настоящий телефон со страницы карточки — или "".

    Порядок по надёжности: ссылка tel: (её рендерят для контактов самой
    организации) → телефон в данных страницы под ключом phone/tel →
    телефон в тексте. Служебные 8-800 и короткие номера отбраковываются.
    """
    if not html:
        return ""
    text = html[:200_000]
    for m in _TEL_LINK_RE.finditer(text):
        phone = _format_phone(_phone_digits(m.group(1)))
        if phone:
            return phone
    decoder = json.JSONDecoder()
    for m in _JSON_BLOB_RE.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, m.start(1))
        except (ValueError, json.JSONDecodeError):
            continue
        phone = _phone_from_json(obj)
        if phone:
            return phone
    for m in _PHONE_TEXT_RE.finditer(_SCRIPT_BLOCK_RE.sub(" ", text)):
        phone = _format_phone(_phone_digits(m.group(0)))
        if phone:
            return phone
    return ""


