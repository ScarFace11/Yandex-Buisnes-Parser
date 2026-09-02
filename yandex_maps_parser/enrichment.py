"""
Business-record enrichment: fetch detail pages, extract socials, deduplicate.
"""
import json
import random
import threading
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed, wait as _future_wait
from datetime import datetime

from tqdm import tqdm

from .constants import KNOWN_PLATFORMS
from .extractors import (
    fetch_html,
    extract_socials,
    extract_description,
    extract_reviews_count,
    validate_socials,
    _extract_from_json_blob,
)
from .exporters import record_key
from . import state
from . import browser_client
from . import cdp_client

# tqdm is not thread-safe: in CLI mode several search workers update the
# shared search/detail progress bars concurrently, so every mutation is
# guarded by this lock.
_pbar_lock = threading.Lock()

# Government institutions almost never have social media.
# Skip detail fetch for these to save 30-120s per organization.
# NOTE: Only check NAME — category can contain "поликлиника" for private clinics
# (e.g. "Смайл" with category "Стоматологическая поликлиника" is PRIVATE).
_GOV_NAME_KEYWORDS = (
    "поликлиника", "больница", "госпиталь",
    "муниципальн", "государств", "федеральн",
    "стоматологическое отделение",
)

def _is_government_institution(record: dict) -> bool:
    """Check if a record is likely a government institution (no socials).

    Only checks the NAME — a private clinic named "Смайл" with category
    "Стоматологическая поликлиника" should NOT be skipped.
    """
    name = record.get("name", "").lower()
    return any(kw in name for kw in _GOV_NAME_KEYWORDS)

# Adaptive concurrency semaphore: starts at MAX_WORKERS, dynamically reduced
# when p95 latency is high to prevent the "death spiral" of all workers waiting.
_concurrency_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()
_effective_workers: int = 0


def enrich(candidates: list[dict], pbar: tqdm, pool: ThreadPoolExecutor | None = None) -> list[dict]:
    """Fetch detail pages in parallel and attach social links to each record.

    `pool` is the run-level executor; reusing it across grid points keeps the
    worker threads (and their per-thread HTTP sessions / TLS connections)
    alive instead of rebuilding 20 threads per point.
    """
    results: list[dict] = []

    # Initialize adaptive concurrency semaphore
    global _concurrency_semaphore, _effective_workers
    with _semaphore_lock:
        _effective_workers = state.MAX_WORKERS
        _concurrency_semaphore = threading.Semaphore(state.MAX_WORKERS)

    # Register candidate count for progress tracking
    if candidates:
        state._add_candidates(len(candidates))

    def process(record: dict) -> dict | None:
        biz_id  = record.pop("_biz_id", "")
        raw     = record.pop("_raw_feature", {})
        agg_url = record.pop("_aggregator_url", "")
        biz_name = record.get("name", "?")

        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None
        if state.is_skip_city():
            return None

        socials: dict[str, str] = {}
        raw_json = json.dumps(raw, ensure_ascii=False)

        # Adaptive throttling: when p95 latency is very high, add a small
        # delay before each detail fetch to reduce concurrent load on Yandex.
        # This prevents the "death spiral" where all 10 workers wait 100s+ each.
        try:
            from .http_client import _get_latency_stats
            _, _, p95 = _get_latency_stats()
            if p95 > 60.0:
                time.sleep(min(3.0, (p95 - 30) / 30))
        except Exception:
            pass

        # The Search API payload sometimes already includes real social links.
        # Only real URLs count — no fabricated WhatsApp from phone numbers and
        # no Telegram from @mentions in context text.
        socials.update(extract_socials(raw_json))

        # Fetch the detail page unless the raw payload already gives a solid
        # picture (>= 2 platforms). A single raw platform is often partial or
        # a false positive — the heavier detail page usually has the full set
        # (e.g. VK was missed because a TG link appeared first in raw JSON).
        # Detail-page socials MERGE into the raw ones instead of replacing them.
        # NOTE: Yandex Search API almost NEVER includes social links in raw
        # data — they are only on the detail page. So we must always fetch
        # the detail page even when raw_socials=0.
        #
        # OPTIMIZATION: If social_mode is "with_socials" and the raw feature
        # already has >= 2 social platforms, skip the expensive detail fetch.
        # This avoids downloading 200KB HTML pages for businesses that already
        # clearly have social media — saving ~50% of enrichment time.
        should_fetch = state.FETCH_DETAIL and biz_id and len(socials) < 2
        # Skip government institutions in with_socials mode — they never have socials
        if should_fetch and state.SOCIAL_MODE == "with_socials" and _is_government_institution(record):
            state.syslog(f"skip_gov: {biz_name} (government institution)")
            should_fetch = False

        # Adaptive concurrency: sleep when latency is very high
        # This naturally reduces throughput without broken semaphore manipulation.
        if should_fetch and _concurrency_semaphore:
            try:
                from .http_client import _get_latency_stats
                _, _, p95 = _get_latency_stats()
                if p95 > 60.0:
                    delay = min(5.0, (p95 - 30) / 20)
                    time.sleep(delay)
                    state.syslog(f"throttle: sleep {delay:.1f}s (p95={p95:.0f}s)")
            except Exception:
                pass

        if should_fetch:
            # Check stop before blocking on semaphore
            if state._STOP_EVENT and state._STOP_EVENT.is_set():
                return None
            if state.is_skip_city():
                return None
            # Acquire concurrency slot with timeout so stop can interrupt
            if _concurrency_semaphore:
                acquired = _concurrency_semaphore.acquire(timeout=5)
                if not acquired:
                    # Retry once with stop check
                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        return None
                    _concurrency_semaphore.acquire(timeout=5)
            state.syslog(f"fetch_detail: biz_id={biz_id}, name={biz_name}, raw_socials={len(socials)}")
            detail_url = f"https://yandex.ru/maps/org/{biz_id}"
            # Try browser first (fast, no throttling), fallback to httpx
            # Priority: Playwright > CDP > httpx
            html = None
            _fetch_source = "none"
            _fetch_t0 = time.monotonic()
            if state.USE_BROWSER:
                if browser_client.is_available():
                    html = browser_client.fetch_page(detail_url, biz_id=biz_id)
                    _fetch_source = "playwright"
                elif cdp_client.is_available():
                    html = cdp_client.fetch_page(detail_url, biz_id=biz_id)
                    _fetch_source = "cdp"
            if html is None:
                html = fetch_html(detail_url, biz_id=biz_id)
                _fetch_source = "httpx"
            _fetch_elapsed = time.monotonic() - _fetch_t0
            if html:
                for k, v in _extract_from_json_blob(html).items():
                    socials.setdefault(k, v)
                for k, v in extract_socials(html).items():
                    socials.setdefault(k, v)
                record["description"] = extract_description(html)
                if not record.get("reviews"):
                    review_count = extract_reviews_count(html)
                    if review_count:
                        record["reviews"] = int(review_count)
            state.syslog(f"fetch_detail done: {biz_name}, socials_after={list(socials.keys())}, source={_fetch_source}, time={_fetch_elapsed:.1f}s")
            # Release concurrency slot
            if _concurrency_semaphore:
                try:
                    _concurrency_semaphore.release()
                except Exception:
                    pass

        # Fallback: try aggregator page (with shorter timeout)
        if agg_url and len(socials) < 2:
            state.syslog(f"fetch_aggregator: {biz_name}, url={agg_url}")
            try:
                from .http_client import _worker_client as _agg_client
                from .extractors import _get as _agg_get
                agg_r = _agg_get(
                    agg_url,
                    session=_agg_client(),
                    timeout=(5, 10),  # shorter timeout for third-party aggregators
                    allow_redirects=True,
                )
                if agg_r and agg_r.status_code == 200:
                    for k, v in extract_socials(agg_r.text).items():
                        socials.setdefault(k, v)
            except Exception:
                pass  # aggregator is best-effort, don't block

        with _pbar_lock:
            pbar.update(1)

        # Backend social mode filtering:
        # "with_socials" — skip businesses that have NO social media at all
        # "without_socials" — skip businesses that HAVE social media
        # "all" — include everything (default)
        has_any_social = any(socials.get(p) for p in KNOWN_PLATFORMS) or bool(socials.get("other_socials"))
        if state.SOCIAL_MODE == "with_socials" and not has_any_social:
            return None  # skip — no social media found
        if state.SOCIAL_MODE == "without_socials" and has_any_social:
            return None  # skip — has social media, user wants only those without

        state._inc_found()
        social_list = [f"{p}:{socials[p][:30]}" for p in KNOWN_PLATFORMS if socials.get(p)]
        # File-only: detailed trace per business
        state.syslog(f"enrich_ok: {biz_name} | socials={social_list or ['none']}")
        for platform in KNOWN_PLATFORMS:
            record[platform] = socials.get(platform, "")

        # Deduplicate "other" socials by domain
        other_seen: set[str] = set()
        other: list[str] = []
        for k, v in socials.items():
            if k not in KNOWN_PLATFORMS and v not in other_seen:
                other_seen.add(v)
                other.append(v)
        record["other_socials"] = ", ".join(other)

        record["socials_valid"] = validate_socials(socials, pool) if state.VALIDATE_SOCIALS else ""
        record["parsed_at"]     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state._emit_result(record)
        state.inc_city_record()
        return record

    owns_pool = pool is None
    if owns_pool:
        pool = ThreadPoolExecutor(max_workers=state.MAX_WORKERS)
    try:
        futures = {pool.submit(process, r): r for r in candidates}
        pending = set(futures.keys())
        while pending:
            # Check stop every iteration
            if state.is_skip_city() or (state._STOP_EVENT and state._STOP_EVENT.is_set()):
                for f in pending:
                    f.cancel()
                break
            # Use short timeout so stop checks happen frequently
            done, pending = _future_wait(pending, timeout=5,
                                          return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                try:
                    res = fut.result(timeout=0)
                    if res is not None:
                        results.append(res)
                except Exception:
                    with _pbar_lock:
                        pbar.update(1)
    finally:
        if owns_pool:
            pool.shutdown(wait=False)

    state.syslog(f"enrich_done: candidates={len(candidates)}, results={len(results)}, rate={len(results)/max(len(candidates),1)*100:.0f}%")
    return results


def collect_candidates(
    query: str,
    city: str,
    lat: float,
    lon: float,
    seen_urls: set[str],
    pbar_search: tqdm,
    pbar_detail: tqdm,
    seen_lock=None,
    search_session=None,
) -> tuple[list[dict], int | None, int]:
    """Search-phase only: gather candidate records for one (query, point).

    Returns (candidates, found, new_candidates). The detail-fetch phase is
    run separately by the runner (enrich()) so the next point's search can
    overlap the current point's detail loading (producer/consumer pipeline).
    `found` is the total count reported by the Search API (None if unknown —
    e.g. on network error); `new_candidates` counts deduped new records.
    """
    from .search import search_page, parse_feature

    candidates: list[dict] = []
    consecutive_empty = 0
    found_total: int | None = None
    new_total: int = 0

    for page in range(state.MAX_PAGES):
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            break
        if state.is_skip_city():
            break
        features, found = search_page(
            query, city, lat, lon, page * 50, session=search_session
        )
        state.syslog(f"search_page: query={query}, city={city}, page={page + 1}, features={len(features)}, found={found}")
        if found is not None and found_total is None:
            found_total = found
        if not features:
            break

        new_this_page = 0
        filtered_websites = 0
        deduped = 0
        for feat in features:
            rec = parse_feature(feat, query)
            if rec is None:
                filtered_websites += 1
                continue
            uid = (
                rec.get("_biz_id")
                or rec.get("yandex_maps_url")
                or record_key(rec)
            ).strip()
            if seen_lock:
                with seen_lock:
                    if not uid or uid in seen_urls:
                        deduped += 1
                        continue
                    seen_urls.add(uid)
            else:
                if not uid or uid in seen_urls:
                    deduped += 1
                    continue
                seen_urls.add(uid)
            candidates.append(rec)
            new_this_page += 1
        new_total += new_this_page

        with _pbar_lock:
            pbar_search.update(len(features))
            pbar_search.set_postfix({"без сайта": len(candidates)})
        state.syslog(f"  page {page + 1}: {len(features)} features, {new_this_page} new, {filtered_websites} had_website, {deduped} deduped, total={len(candidates)}")

        # Stop collecting if we hit the per-city candidate limit
        max_cand = getattr(state, 'MAX_CANDIDATES_PER_CITY', 0)
        if max_cand > 0 and len(candidates) >= max_cand:
            state.syslog(f"  candidate limit reached: {len(candidates)}/{max_cand}, stopping search")
            break

        if len(features) < 50:
            break

        if new_this_page == 0:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
        else:
            consecutive_empty = 0

        delay = (
            random.uniform(0.5, 1.0) if new_this_page > 0
            else random.uniform(1.0, 2.0)
        )
        time.sleep(delay)

    if candidates:
        state.syslog(f"collect_candidates: query={query}, city={city}, candidates={len(candidates)}")
    else:
        state.syslog(f"collect_candidates: query={query}, city={city}, no candidates found")

    with _pbar_lock:
        pbar_detail.total = (pbar_detail.total or 0) + len(candidates)
        pbar_detail.refresh()
    return candidates, found_total, new_total
