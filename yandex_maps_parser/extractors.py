"""
HTML / text extraction: social links, emails, descriptions, reviews.
"""
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .constants import (
    LINK_AGGREGATORS,
    SOCIAL_DOMAINS,
    KNOWN_PLATFORMS,
    EXCLUDE_URLS,
)
from .http_client import _head, _worker_client, _get
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
    r'events|groups(?=/[0-9])|pages/create|sharer)\b',
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
    r'(?:window\.__(?:NUXT|INITIAL_STATE|SERVER_STATE|DATA|STATE)__'
    r'|window\.serverState'
    r'|<script[^>]+type=["\']application/json["\'][^>]*>)\s*[=]*(\{)',
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

    with state._detail_semaphore:
        r = _get(url, session=session or _worker_client(), timeout=(8, 15))
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


def extract_description(html: str) -> str:
    for pat in [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            desc = m.group(1).strip()
            if desc and "Яндекс" not in desc and len(desc) > 20:
                return desc[:500]
    return ""


def extract_reviews_count(html: str) -> str:
    """Extract the numeric review count from a Yandex Maps detail page."""
    for pat in _REVIEW_COUNT_PATS:
        m = pat.search(html)
        if m:
            return re.sub(r"\D", "", m.group(1))
    return ""


_REVIEW_COUNT_PATS = [
    re.compile(r'"reviewCount"\s*:\s*(\d+)'),
    re.compile(r'"reviewsCount"\s*:\s*(\d+)'),
    re.compile(r'"review_count"\s*:\s*(\d+)'),
    re.compile(r'"count"\s*:\s*(\d+).{0,200}?"rating"', re.DOTALL),
    re.compile(r'(?<!\w)(\d[\d\s\xa0]*)\s+(?:отзыв(?:а|ов)?|reviews?)\b', re.I),
]


def validate_socials(socials: dict[str, str], pool: ThreadPoolExecutor | None = None) -> str:
    """HEAD-check each social URL; return comma-separated list of live platforms.

    Reuses the caller's thread pool when provided to avoid creating
    a new ThreadPoolExecutor per record (which was a major perf bottleneck).
    """
    valid: list[str] = []
    owns_pool = pool is None
    if owns_pool:
        pool = ThreadPoolExecutor(max_workers=min(len(socials), 5))
    try:
        future_to_platform = {
            pool.submit(_head, url): platform
            for platform, url in socials.items() if url
        }
        for fut in as_completed(future_to_platform):
            platform = future_to_platform[fut]
            try:
                status = fut.result()
                if 200 <= status < 400:
                    valid.append(platform)
            except Exception:
                pass
    finally:
        if owns_pool:
            pool.shutdown(wait=False)
    return ", ".join(p for p in KNOWN_PLATFORMS if p in valid)
