"""Business-record enrichment: fetch detail pages, extract socials, deduplicate."""
import json
import random
import threading
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, wait as _future_wait
from datetime import datetime

from tqdm import tqdm

from .constants import KNOWN_PLATFORMS
from .extractors import (
    extract_page,
    fetch_html,
    extract_socials,
    _ANTIBOT_MARKERS,
)
from .exporters import record_key
from .processing import crawl_skip_reason
from . import state
from . import cdp_client

def _looks_like_antiblock(html) -> bool:
    """True when a fetched page is an anti-bot stub / too short to be real."""
    if not html:
        return True
    if len(html) < 800:
        return True
    lower = html[:4000].lower()
    return any(m in lower for m in _ANTIBOT_MARKERS)


def _stop_requested() -> bool:
    """True when stop or skip-city was requested."""
    return bool(
        (state._STOP_EVENT and state._STOP_EVENT.is_set())
        or state.is_skip_city()
    )


# tqdm is not thread-safe: in CLI mode several search workers update the shared search/detail progress bars concurrently, so every mutation is guarded by this lock.
_pbar_lock = threading.Lock()

# Government institutions almost never have social media.
_GOV_NAME_KEYWORDS = (
    "поликлиник", "больниц", "госпитал",
    "муниципальн", "государств", "федеральн",
    "стоматологическое отделение",
)

def _is_government_institution(record: dict) -> bool:
    """Check if a record is likely a government institution (no socials)."""
    name = record.get("name", "").lower()
    return any(kw in name for kw in _GOV_NAME_KEYWORDS)

# Adaptive concurrency semaphore: starts at MAX_WORKERS, dynamically reduced when p95 latency is high to prevent the "death spiral" of all workers waiting.
_concurrency_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()
_effective_workers: int = 0


def _poll_semaphore_acquire(semaphore, timeout: float) -> bool:
    """Acquire a semaphore, polling stop/skip every 0.5s."""
    deadline = time.monotonic() + timeout
    while True:
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return False
        if state.is_skip_city():
            return False
        if semaphore.acquire(blocking=False):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.5, remaining))


def enrich(candidates: list[dict], pbar: tqdm, pool: ThreadPoolExecutor | None = None) -> list[dict]:
    """Fetch detail pages in parallel and attach social links to each record. `pool` is the run-level executor; reusing it across grid points keeps the worker threads (and their per-thread HTTP sessions / TLS connections) alive instead of rebuilding 20 threads per point."""
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
        detail_url_override = record.pop("_detail_url", "")
        # Выдача Яндекс.Карт не показывает сайт организации (в API он был), поэтому «только без сайтов» добивает запись уже после карточки.
        record.pop("_site_unknown", None)
        biz_name = record.get("name", "?")

        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None
        if state.is_skip_city():
            return None

        # Чёрный список известен уже из выдачи (название/категория, иногда описание) — такую запись не показываем и НЕ грузим ей карточку.
        if crawl_skip_reason(record, words=state.BLACKLIST_WORDS) == "blacklist":
            state.inc_crawl_skip("blacklist")
            state.syslog(f"skip_prefilter[blacklist]: {biz_name}")
            with _pbar_lock:
                pbar.update(1)
            return None

        socials: dict[str, str] = {}
        raw_json = json.dumps(raw, ensure_ascii=False)

        # Adaptive throttling: when p95 latency is very high, add a small delay before each detail fetch to reduce concurrent load on Yandex.
        try:
            from .http_client import _get_latency_stats
            _, _, p95 = _get_latency_stats()
            if p95 > 60.0:
                time.sleep(min(3.0, (p95 - 30) / 30))
        except Exception:
            pass

        # The Search API payload sometimes already includes real social links.
        socials.update(extract_socials(raw_json))

        # Fetch the detail page unless the raw payload already gives a solid picture (>= 2 platforms).
        _raw_missing_required = bool(state.REQUIRED_SOCIALS) and not all(
            socials.get(p) for p in state.REQUIRED_SOCIALS
        )
        should_fetch = (
            state.FETCH_DETAIL and biz_id
            and (len(socials) < 2 or _raw_missing_required)
            and not record.pop("_skip_detail", False)
        )
        # Skip government institutions in with_socials mode — they never have socials
        if should_fetch and state.SOCIAL_MODE == "with_socials" and _is_government_institution(record):
            state.syslog(f"skip_gov: {biz_name} (government institution)")
            should_fetch = False

        # Adaptive concurrency: sleep when latency is very high This naturally reduces throughput without broken semaphore manipulation.
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
            # Acquire concurrency slot with timeout so stop can interrupt.
            _sem_acquired = False
            if _concurrency_semaphore:
                acquired = _poll_semaphore_acquire(_concurrency_semaphore, 5.0)
                if not acquired:
                    if state._STOP_EVENT and state._STOP_EVENT.is_set():
                        return None
                    if state.is_skip_city():
                        return None
                    # Retry once more (still no stop — just slow pool)
                    acquired = _poll_semaphore_acquire(_concurrency_semaphore, 5.0)
                    if not acquired:
                        # Failed again: either stop was set mid-retry (in which case abort) or the pool stayed saturated — proceed without a slot only if no stop/skip was requested.
                        if state._STOP_EVENT and state._STOP_EVENT.is_set():
                            return None
                        if state.is_skip_city():
                            return None
                _sem_acquired = acquired
            state.syslog(f"fetch_detail: biz_id={biz_id}, name={biz_name}, raw_socials={len(socials)}")
            detail_url = detail_url_override or f"https://yandex.ru/maps/org/{biz_id}"
            # Try browser first (fast, no throttling), fallback to httpx Priority: CDP > Playwright > httpx — the pool that is up is usually CDP (runner initializes it first; Playwright is only a fallback for sources on Python < 3.14).
            html = None
            _fetch_source = "none"
            _fetch_t0 = time.monotonic()
            # Единственный способ — реальный браузер (Chrome/Chromium через CDP).
            if state.USE_BROWSER and cdp_client.is_available():
                html = fetch_html(detail_url, biz_id=biz_id)
                _fetch_source = "cdp"

            # Anti-bot stub from the browser?
            if (not _stop_requested() and _looks_like_antiblock(html)
                    and state.USE_BROWSER and cdp_client.is_available()):
                state.syslog(f"fetch_detail: anti-bot stub for {biz_name}, retrying on a fresh tab...")
                html = fetch_html(detail_url, biz_id=biz_id)
                _fetch_source = "cdp"

            # Резервный путь без браузера больше не используется: если пул вкладок не поднялся, запись уходит без соцсетей — это честнее, чем долбить Яндекс HTTP-запросами.
            _fetch_elapsed = time.monotonic() - _fetch_t0
            # Extractors run on a complex JSON blob / HTML and can raise; if they did, the slot was never released and the pool silently lost a worker for the rest of the batch.
            try:
                if html:
                    # Одним разбором страницы: встроенные данные и секция контактов разбираются один раз, а не на каждый шаг (замер: 15.7 мс на карточку против 5–6 мс).
                    need_rating = (not record.get("rating")
                                   or not record.get("reviews_count"))
                    need_phone = not str(record.get("phone") or "").strip()
                    need_site = not str(record.get("website") or "").strip()
                    need_agg = not str(record.get("aggregator_url") or "").strip()
                    page = extract_page(html, rating=need_rating,
                                        phone=need_phone, website=need_site,
                                        aggregator=need_agg)
                    # Порядок приоритета: выдача → встроенные данные → секция контактов карточки.
                    for k, v in page["socials_json"].items():
                        socials.setdefault(k, v)
                    for k, v in page["socials_contacts"].items():
                        socials.setdefault(k, v)
                    # Rating/reviews live in the same blob as the socials, so this is free.
                    if need_rating:
                        if page["rating"] and not record.get("rating"):
                            record["rating"] = page["rating"]
                        if page["reviews"] and not record.get("reviews_count"):
                            record["reviews_count"] = page["reviews"]
                    # Телефон: выдача Яндекс.Карт его не показывает — на карточке организации он есть как ссылка tel:, а страница уже загружена.
                    if need_phone and page["phone"]:
                        record["phone"] = page["phone"]
                        state.syslog(f"phone_from_page: {biz_name} → {page['phone']}")
                    # Сайт организации: раньше его отдавал API вместе с выдачей, теперь — блок контактов карточки (см. extract_website).
                    site = page["website"] if need_site else ""
                    if site:
                        record["website"] = site
                        state.syslog(f"website_from_page: {biz_name} → {site[:80]}")
                    # Ссылка-витрина (taplink/linktree): Яндекс показывает её как «Сайт», но отдельным полем.
                    if need_agg and page["aggregator"]:
                        record["aggregator_url"] = page["aggregator"]
                        state.syslog(f"aggregator_from_page: {biz_name} → {page['aggregator'][:80]}")
                    # Зеркало social_normalize.normalize_record: обычный сайт виден в колонке «Сайт / Таплинк» и в ЖИВОЙ таблице, а не только в файлах, которые пишет этап сохранения.
                    if record.get("website") and not record.get("aggregator_url"):
                        record["aggregator_url"] = record["website"]
                state.syslog(f"fetch_detail done: {biz_name}, socials_after={list(socials.keys())}, source={_fetch_source}, time={_fetch_elapsed:.1f}s")
            finally:
                # Release concurrency slot (only if acquired)
                if _sem_acquired and _concurrency_semaphore:
                    try:
                        _concurrency_semaphore.release()
                    except Exception:
                        pass

        # Fallback: try aggregator page (with shorter timeout)
        if not _stop_requested() and agg_url and len(socials) < 2:
            state.syslog(f"fetch_aggregator: {biz_name}, url={agg_url}")
            try:
                # Страница-агрегатор открывается тем же браузером — прямые HTTP-запросы к чужим сайтам приложение больше не делает.
                agg_html = cdp_client.fetch_page(agg_url)
                if agg_html:
                    for k, v in extract_socials(agg_html).items():
                        socials.setdefault(k, v)
            except Exception:
                pass  # aggregator is best-effort, don't block

        with _pbar_lock:
            pbar.update(1)

        # Post-fetch guard: stop/skip may have been requested while the detail page was loading.
        if state._STOP_EVENT and state._STOP_EVENT.is_set():
            return None
        if state.is_skip_city():
            return None

        # Соцсети переносим в запись ДО решения о фильтрах: и режим «с/без соцсетей», и обязательные сети читаются по самой записи.
        for platform in KNOWN_PLATFORMS:
            record[platform] = socials.get(platform, "")

        # Предфильтр сбора: запись, которую всё равно снимут фильтры (чёрный список, «только без сайтов», соцсети), не попадает ни в живой поток — им наполняется таблица результатов, — ни в output/raw/.
        _reason = crawl_skip_reason(
            record,
            words=state.BLACKLIST_WORDS,
            parse_mode=state.PARSE_MODE,
            social_mode=state.SOCIAL_MODE,
            required_socials=state.REQUIRED_SOCIALS,
            min_lead_score=getattr(state, "MIN_LEAD_SCORE", 0),
            only_single_branch=getattr(state, "ONLY_SINGLE_BRANCH", False),
            only_new_months=getattr(state, "ONLY_NEW_MONTHS", None),
            vk_check=getattr(state, "VK_CHECK", False),
        )
        if _reason:
            state.inc_crawl_skip(_reason)
            _site = (record.get("website") or record.get("aggregator_url") or "").strip()
            state.syslog(f"skip_prefilter[{_reason}]: {biz_name}"
                         + (f" — {_site[:60]}" if _site else ""))
            return None

        state._inc_found()
        social_list = [f"{p}:{socials[p][:30]}" for p in KNOWN_PLATFORMS if socials.get(p)]
        # File-only: detailed trace per business
        state.syslog(f"enrich_ok: {biz_name} | socials={social_list or ['none']}")

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
            # 1s granularity: stop/skip is noticed within ~1s even when all in-flight detail fetches are slow to finish (they also abort early on stop via the CDP/httpx stop checks).
            done, pending = _future_wait(pending, timeout=1,
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
    """Search-phase only: gather candidate records for one (query, point)."""
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
