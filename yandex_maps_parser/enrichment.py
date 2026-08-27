"""
Business-record enrichment: fetch detail pages, extract socials, deduplicate.
"""
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# tqdm is not thread-safe: in CLI mode several search workers update the
# shared search/detail progress bars concurrently, so every mutation is
# guarded by this lock.
_pbar_lock = threading.Lock()


def enrich(candidates: list[dict], pbar: tqdm, pool: ThreadPoolExecutor | None = None) -> list[dict]:
    """Fetch detail pages in parallel and attach social links to each record.

    `pool` is the run-level executor; reusing it across grid points keeps the
    worker threads (and their per-thread HTTP sessions / TLS connections)
    alive instead of rebuilding 20 threads per point.
    """
    results: list[dict] = []

    def process(record: dict) -> dict | None:
        biz_id  = record.pop("_biz_id", "")
        raw     = record.pop("_raw_feature", {})
        agg_url = record.pop("_aggregator_url", "")

        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None

        socials: dict[str, str] = {}
        raw_json = json.dumps(raw, ensure_ascii=False)

        # The Search API payload sometimes already includes real social links.
        # Only real URLs count — no fabricated WhatsApp from phone numbers and
        # no Telegram from @mentions in context text.
        socials.update(extract_socials(raw_json))

        # Fetch the detail page unless the raw payload already gives a solid
        # picture (>= 2 platforms). A single raw platform is often partial or
        # a false positive — the heavier detail page usually has the full set
        # (e.g. VK was missed because a TG link appeared first in raw JSON).
        # Detail-page socials MERGE into the raw ones instead of replacing them.
        if state.FETCH_DETAIL and biz_id and len(socials) < 2:
            html = fetch_html(f"https://yandex.ru/maps/org/{biz_id}")
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

        # Fallback: try aggregator page
        if agg_url and len(socials) < 2:
            agg_html = fetch_html(agg_url)
            if agg_html:
                for k, v in extract_socials(agg_html).items():
                    socials.setdefault(k, v)

        with _pbar_lock:
            pbar.update(1)

        if not socials:
            return None

        state._inc_found()
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

        record["socials_valid"] = validate_socials(socials) if state.VALIDATE_SOCIALS else ""
        record["parsed_at"]     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state._emit_result(record)
        return record

    owns_pool = pool is None
    if owns_pool:
        pool = ThreadPoolExecutor(max_workers=state.MAX_WORKERS)
    try:
        futures = {pool.submit(process, r): r for r in candidates}
        for fut in as_completed(futures):
            try:
                res = fut.result(timeout=60)
                if res is not None:
                    results.append(res)
            except Exception:
                with _pbar_lock:
                    pbar.update(1)
    finally:
        if owns_pool:
            pool.shutdown(wait=True)

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
        features, found = search_page(
            query, city, lat, lon, page * 50, session=search_session
        )
        if found is not None and found_total is None:
            found_total = found
        if not features:
            break

        new_this_page = 0
        for feat in features:
            rec = parse_feature(feat, query)
            if rec is None:
                continue
            uid = (
                rec.get("_biz_id")
                or rec.get("yandex_maps_url")
                or record_key(rec)
            ).strip()
            if seen_lock:
                with seen_lock:
                    if not uid or uid in seen_urls:
                        continue
                    seen_urls.add(uid)
            else:
                if not uid or uid in seen_urls:
                    continue
                seen_urls.add(uid)
            candidates.append(rec)
            new_this_page += 1
        new_total += new_this_page

        with _pbar_lock:
            pbar_search.update(len(features))
            pbar_search.set_postfix({"без сайта": len(candidates)})
        if state._LOG_FN:
            state.info(
                f"  Стр. {page + 1}: {len(features)} орг. на карте, "
                f"{new_this_page} новых кандидатов (всего без сайта: {len(candidates)})"
            )

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

    if state._LOG_FN and candidates:
        state.info(f"  ⚙ Загружаю детали {len(candidates)} орг. «{query}»…")
    elif state._LOG_FN and not candidates:
        state.info(f"  — «{query}»: кандидатов без сайта не найдено")

    with _pbar_lock:
        pbar_detail.total = (pbar_detail.total or 0) + len(candidates)
        pbar_detail.refresh()
    return candidates, found_total, new_total
