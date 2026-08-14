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
from .http_client import _head, _worker_session, _get
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
    r'(?:twitter|x)\.com/(intent|share|search|home|hashtag|explore|settings|'
    r'notifications|messages|compose|status|i/)\b',
    re.I,
)

# Matches the marker followed by the opening brace of an embedded JSON object.
# We deliberately do NOT match a bounded "{...}" body: nested objects would be
# truncated by a non-greedy match, so we only grab the start position and let
# json.JSONDecoder.raw_decode parse the complete (nested) value from there.
_JSON_BLOB_RE = re.compile(
    r'(?:window\.__(?:NUXT|INITIAL_STATE|SERVER_STATE|DATA|STATE)__'
    r'|window\.serverState'
    r'|<script[^>]+type=["\']application/json["\'][^>]*>)\s*[=\s]*(\{)',
    re.I,
)

_ANTIBOT_MARKERS = (
    "showcaptcha", "robot", "captcha", "i-am-not-robot",
    "access denied", "too many requests",
)


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

def fetch_html(url: str, session=None) -> str:
    # Sleep OUTSIDE the semaphore so the concurrency slot isn't held during the delay.
    # Each thread still waits its own random interval (rate-limiting per thread),
    # but slots are free for other threads to acquire immediately.
    time.sleep(random.uniform(state.DELAY_MIN, state.DELAY_MAX))
    with state._detail_semaphore:
        r = _get(url, session=session or _worker_session(), timeout=(8, 15))
    if not r or r.status_code != 200:
        return ""
    text = r.text
    lower = text[:4000].lower()
    if any(m in lower for m in _ANTIBOT_MARKERS):
        state.warn("Яндекс вернул anti-bot страницу — детали этой карточки пропущены.")
        return ""
    return text


# ── Extractors ────────────────────────────────────────────────

def _collect_url_strings(obj, depth: int = 0, limit: int = 200) -> list[str]:
    """Recursively collect string values that look like URLs from a decoded object."""
    out: list[str] = []

    def walk(o, d: int) -> None:
        if len(out) >= limit or d > 8:
            return
        if isinstance(o, str):
            if "http" in o and re.search(r'https?://', o):
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
    (the old regex approach truncated at the first closing brace) and escaped
    URLs like "https:\/\/vk.com\/club1" come back unescaped.
    """
    result: dict[str, str] = {}
    decoder = json.JSONDecoder()
    for m in _JSON_BLOB_RE.finditer(html):
        start = m.start(1)
        try:
            obj, _ = decoder.raw_decode(html, start)
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
    for url in re.findall(r'https?://[^\s"\'<>\\,\}\{]+', text):
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
    # Bounded span (<= 200 chars) so "count" can't latch onto a "rating"
    # key hundreds of characters away (the old .*? overshot badly).
    for pat in [
        re.compile(r'"reviewCount"\s*:\s*(\d+)'),
        re.compile(r'"count"\s*:\s*(\d+).{0,200}?"rating"', re.DOTALL),
    ]:
        m = pat.search(html)
        if m:
            return m.group(1)
    return ""


def validate_socials(socials: dict[str, str]) -> str:
    """HEAD-check each social URL; return comma-separated list of live platforms."""
    valid: list[str] = []
    with ThreadPoolExecutor(max_workers=min(len(socials), 5)) as pool:
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
    return ", ".join(p for p in KNOWN_PLATFORMS if p in valid)
