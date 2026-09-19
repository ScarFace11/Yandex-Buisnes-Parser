"""
VK activity stats (subscribers, days since the last wall post).

Used by stage 2 (фильтрация) to score leads: an active VK community means
the owner actually reads messages, so a website pitch lands on live eyes.

Uses the official VK API with a user/service token (the same one the bulk
sender needs). Results are cached on disk for a week so «Применить фильтры
заново» does not hammer the API for the same communities.

No token → no requests: `activity_available()` returns False and callers
skip the step with a warning instead of writing fake zeros.
"""
import json
import os
import re
import threading
import time

import requests

from . import state

VK_API = "https://api.vk.com/method"
VK_VERSION = "5.131"

# A community is «active» when something was posted recently enough that the
# owner still opens it; semi-active still gets a bump in the lead score.
ACTIVE_MAX_DAYS = 30
SEMI_MAX_DAYS = 180

_CACHE_TTL = 7 * 24 * 3600
_CACHE_FILE = os.path.join(state.OUTPUT_DIR, ".cache", "vk_stats.json")
_cache_lock = threading.Lock()

# VK throttles user tokens to ~3 requests/sec — one shared pace for all workers.
_MIN_INTERVAL = 0.34
_pace_lock = threading.Lock()
_last_call = [0.0]

_VK_URL_RE = re.compile(r"vk\.com/(?P<screen>[A-Za-z0-9._\-]+)", re.I)

# Non-profile VK paths that can never resolve to a community.
_NON_PROFILE = {
    "wall", "photo", "video", "album", "doc", "app", "feed", "away",
    "share", "login", "join", "invite", "oauth", "im", "search", "explore",
    "fave", "bookmarks", "club", "public", "topic", "note", "market",
}


def activity_available() -> bool:
    """True when a VK token is configured (env `VK_TOKEN` / config.VK_TOKEN)."""
    return bool(_token())


def _token() -> str:
    try:
        import config
        return (getattr(config, "VK_TOKEN", "") or os.getenv("VK_TOKEN", "")).strip()
    except Exception:
        return (os.getenv("VK_TOKEN", "") or "").strip()


def screen_name(url: str) -> str:
    """`https://vk.com/pivmilya` → `pivmilya`; empty for unusable links.

    A bare screen name is also accepted, so batch callers can feed the
    extracted value back in without double-parsing it into nothing.
    """
    raw = (url or "").strip().lstrip("@")
    m = _VK_URL_RE.search(raw)
    if m:
        screen = m.group("screen").strip()
    elif raw and "/" not in raw and " " not in raw and raw.lower() not in ("vk", "vk.com", "vkontakte.ru"):
        screen = raw
    else:
        return ""
    # «wall-1_2», «photo-3_4» are service paths, not communities. A screen
    # name like «club123» is a real id, so only the segment before the first
    # separator is checked against the reserved words.
    head = re.split(r"[-_.]", screen, maxsplit=1)[0].lower()
    if head in _NON_PROFILE or screen.lower() in _NON_PROFILE:
        return ""
    return screen


# ── Disk cache ────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
        os.replace(tmp, _CACHE_FILE)
    except OSError:
        pass  # cache is best-effort


def _cache_get(screen: str):
    entry = _load_cache().get(screen)
    if isinstance(entry, dict) and time.time() - entry.get("ts", 0) < _CACHE_TTL:
        return {k: v for k, v in entry.items() if k != "ts"}
    return None


def _cache_put(screen: str, stats: dict) -> None:
    with _cache_lock:
        cache = _load_cache()
        cache[screen] = {**stats, "ts": time.time()}
        _save_cache(cache)


# ── API ───────────────────────────────────────────────────────

def _api(method: str, params: dict, token: str) -> dict | None:
    """One VK API call with pacing + a couple of retries; None on failure."""
    params = {**params, "access_token": token, "v": VK_VERSION}
    for attempt in range(3):
        with _pace_lock:
            wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.monotonic()
        try:
            r = requests.get(f"{VK_API}/{method}", params=params, timeout=(5, 15))
            if r.status_code != 200:
                time.sleep(1 + attempt)
                continue
            payload = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1 + attempt)
            continue
        if "error" in payload:
            # error 30 «Too many requests per second» / 6 «too many» — retry.
            code = (payload.get("error") or {}).get("error_code")
            if code in (6, 29, 30):
                time.sleep(1 + attempt)
                continue
            return None
        response = payload.get("response")
        return response if isinstance(response, dict) else None
    return None


def classify(last_post_days) -> str:
    """«active» / «semi» / «inactive» / «unknown» from the post age."""
    if last_post_days is None:
        return "unknown"
    if last_post_days <= ACTIVE_MAX_DAYS:
        return "active"
    if last_post_days <= SEMI_MAX_DAYS:
        return "semi"
    return "inactive"


def fetch_stats(vk_url: str, token: str = "", cache: dict | None = None) -> dict:
    """Return {activity, followers, last_post_days} for one VK link.

    Empty dict when the link is unusable or the API refused. Groups and
    personal pages are both handled; «followers» is -1 when the community
    hides its member list.

    `cache` lets a batch caller keep the whole cache in memory instead of
    re-reading the JSON file per community (see annotate_records).
    """
    screen = screen_name(vk_url)
    if not screen:
        return {}
    if cache is None:
        cached = _cache_get(screen)
    else:
        entry = cache.get(screen)
        cached = ({k: v for k, v in entry.items() if k != "ts"}
                  if isinstance(entry, dict) and time.time() - entry.get("ts", 0) < _CACHE_TTL
                  else None)
    if cached is not None:
        return cached

    token = token or _token()
    if not token:
        return {}

    resolved = _api("utils.resolveScreenName", {"screen_name": screen}, token)
    if not resolved:
        return {}
    owner_type = resolved.get("type")
    owner_id = resolved.get("object_id")

    followers = None
    if owner_type == "group":
        info = _api("groups.getById", {
            "group_id": str(owner_id),
            "fields": "members_count,is_closed",
        }, token)
        # v5.131 returns {"groups": [...]} for the new-style call.
        groups = (info or {}).get("groups") or [info] if info else []
        if groups and isinstance(groups[0], dict):
            count = groups[0].get("members_count")
            followers = int(count) if isinstance(count, (int, float)) else None
    elif owner_type == "user":
        info = _api("users.get", {
            "user_ids": str(owner_id),
            "fields": "followers_count",
        }, token)
        items = (info or {}).get("items") or [info] if info else []
        if items and isinstance(items[0], dict):
            count = items[0].get("followers_count")
            followers = int(count) if isinstance(count, (int, float)) else None

    wall = _api("wall.get", {
        "owner_id": ("-" if owner_type == "group" else "") + str(owner_id),
        "count": 1,
        "filter": "owner",
    }, token)
    last_post_days = None
    items = (wall or {}).get("items") or []
    if items and isinstance(items[0], dict) and items[0].get("date"):
        last_post_days = max(0, int((time.time() - items[0]["date"]) // 86400))

    stats = {
        "activity": classify(last_post_days),
        "followers": followers if followers is not None else -1,
        "last_post_days": last_post_days if last_post_days is not None else -1,
    }
    if cache is None:
        _cache_put(screen, stats)
    else:
        cache[screen] = {**stats, "ts": time.time()}
    return stats


def annotate_records(records: list[dict], log_fn=None) -> int:
    """Fill vk_activity / vk_followers / vk_last_post_days in place.

    Returns the number of records that got real data. Records without a VK
    link keep empty values (they are not «inactive» — they are unknown).
    """
    log = log_fn or (lambda *_: None)
    token = _token()
    if not token:
        log("warn", "  ⚠ VK_TOKEN не задан — активность ВКонтакте не проверена "
                    "(добавьте ключ в «API-ключи»). Остальные фильтры работают.")
        return 0

    targets = [(r, screen_name(r.get("vk") or "")) for r in records]
    targets = [(r, s) for r, s in targets if s]
    if not targets:
        return 0

    # One file read + one write for the whole batch: the cache used to be
    # re-read and re-written for every community (O(n²) disk I/O).
    cache = _load_cache()
    done = 0
    # VK's rate limit is per token, so extra threads only add contention;
    # the requests are paced centrally anyway.
    for record, screen in targets:
        stats = fetch_stats(screen, token, cache=cache)
        if not stats:
            continue
        record["vk_activity"] = stats.get("activity", "")
        followers = stats.get("followers", -1)
        days = stats.get("last_post_days", -1)
        record["vk_followers"] = followers if followers and followers > 0 else ""
        record["vk_last_post_days"] = days if days is not None and days >= 0 else ""
        done += 1
    with _cache_lock:
        _save_cache(cache)
    log("info", f"  👥 Активность ВК: проверено {done} из {len(targets)} сообществ")
    return done
