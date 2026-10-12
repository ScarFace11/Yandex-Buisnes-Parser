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
        # links and the exported column then looks untrustworthy/broken in Excel.
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
        return url# ── Fetch ─────────────────────────────────────────────────────

def fetch_html(url: str, session=None, biz_id: str = "") -> str:
    """Загрузить страницу карточки реальным браузером (CDP), с дисковым кэшем.

    HTTP-пути больше нет: прямые запросы к Яндекс.Картам ловит антибот
    (p95 до 325 с на страницу, частые заглушки), а сам IP/аккаунт после
    серии таких обращений выглядит подозрительно. Браузер отдаёт ту же
    страницу за секунды и ничем не отличается от обычного пользователя.

    Единственный путь загрузки карточек: и сюда, и в `enrichment.enrich`
    приходят только эти вызовы — значит, кэш здесь работает для всего
    прогона. Кэшируются только здоровые страницы (см. `cache.set_cached`):
    антибот-заглушка на диск не попадает, иначе она пережила бы повторный
    прогон и организация осталась бы без деталей.

    Аргумент `session` оставлен для совместимости вызовов — браузерная
    загрузка сессии не требует. Пустая строка — страницу получить не
    удалось (нет браузера, остановка, ошибка навигации, антибот).
    """
    # Кэш страниц: повторный прогон не ждёт браузер на каждой карточке.
    if biz_id:
        try:
            from .cache import get_cached
            cached = get_cached(biz_id)
            if cached:
                state.syslog(f"cache_hit: biz_id={biz_id}")
                return cached
        except Exception:
            pass

    from . import cdp_client
    text = ""
    try:
        text = cdp_client.fetch_page(url, biz_id=biz_id) or ""
    except Exception as exc:
        state.syslog(f"fetch_html: browser error: {type(exc).__name__}: {exc}")
        return ""

    if not text:
        state.warn("Карточка не открылась в браузере — детали этой организации пропущены.")
        return ""

    lower = text[:4000].lower()
    if any(m in lower for m in _ANTIBOT_MARKERS):
        state.warn("Яндекс вернул anti-bot страницу — детали этой карточки пропущены.")
        return ""

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
            url = _clean_social_url(url)
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
        url = _clean_social_url(url)
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
# response (мешает только ручной разбор контактов); карточка организации
# в Яндекс.Картах отдаёт контакты в том же JSON внутри страницы.
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

    Yandex ships the business card as JSON inside the page; a
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


# ── Сайт организации ─────────────────────────────────────────
# Раньше сайт приходил из API организации вместе с выдачей. Браузерная
# выдача его не показывает, поэтому сайт читается с карточки организации:
# ссылка в блоке контактов («Сайт») или поле url/site/website в данных
# страницы. Так фильтр «только без сайтов» продолжает работать.
_WEBSITE_KEYS = ("url", "site", "website", "siteurl", "domain")
_WEBSITE_LINK_RE = re.compile(
    r'href=["\'](https?://[^"\']+)["\'][^>]*>\s*(?:<[^>]+>)*[^<]{0,40}?Сайт',
    re.I,
)


def _is_own_website(url: str) -> bool:
    """True для сайта самой организации (не соцсеть, не агрегатор, не Яндекс)."""
    if not url or not url.lower().startswith("http"):
        return False
    low = url.lower()
    if EXCLUDE_URLS.search(low) or _is_aggregator(low):
        return False
    for pat in SOCIAL_DOMAINS.values():
        if pat.search(low):
            return False
    return True


def extract_website(html: str) -> str:
    """Сайт организации со страницы карточки — или "" (если сайта нет)."""
    if not html:
        return ""
    text = html[:200_000]

    # 1. Блок контактов: ссылка рядом со словом «Сайт» — самый надёжный сигнал.
    for m in _WEBSITE_LINK_RE.finditer(text):
        cand = m.group(1).strip()
        if _is_own_website(cand):
            return _clean_social_url(cand)

    # 2. Данные страницы: url/site/website с настоящим адресом организации.
    decoder = json.JSONDecoder()
    for m in _JSON_BLOB_RE.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, m.start(1))
        except (ValueError, json.JSONDecodeError):
            continue
        found = _website_from_json(obj)
        if found:
            return found
    return ""


def _website_from_json(value, depth: int = 0) -> str:
    """Первый настоящий сайт под ключом url/site/website в данных страницы."""
    if depth > 12 or value is None:
        return ""
    if isinstance(value, dict):
        for key, sub in value.items():
            if str(key).lower() not in _WEBSITE_KEYS:
                continue
            cand = sub
            if isinstance(cand, dict):
                cand = cand.get("value") or cand.get("text") or cand.get("url") or ""
            if isinstance(cand, (list, tuple)):
                cand = next((x for x in cand if isinstance(x, str)), "")
            if isinstance(cand, str) and _is_own_website(cand.strip()):
                return _clean_social_url(cand.strip())
        for sub in value.values():
            found = _website_from_json(sub, depth + 1)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for sub in value:
            found = _website_from_json(sub, depth + 1)
            if found:
                return found
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


