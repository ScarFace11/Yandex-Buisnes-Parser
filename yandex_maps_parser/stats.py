"""
Console statistics summary.
"""
from collections import Counter

from .constants import KNOWN_PLATFORMS
from . import state


def print_limit_stats() -> None:
    """Print browser usage from the shared counters (сколько страниц открыто)."""
    _print_prefilter_stats()
    from .http_client import get_stats
    s = get_stats()
    if not s["requests"]:
        return
    state.ok(f"\n  Открыто страниц: {s['requests']}")
    # Human-readable page kinds — raw kinds go to the developer file only.
    kind_labels = {
        "search":   "Выдачи поиска",
        "geocode":  "Координаты городов",
        "detail":   "Карточки организаций",
        "other":    "Прочие страницы",
    }
    for kind, label in kind_labels.items():
        n = s["by_kind"].get(kind, 0)
        # «Прочие запросы: 55» right under «Запросы: 55» says nothing new —
        # skip the redundant line when «other» is the only kind.
        if n and not (kind == "other" and n >= s["requests"]):
            state.info(f"    {label}: {n}")
        if n:
            state.syslog(f"  by_kind[{kind}] = {n}")
    if s["rate_limits"]:
        state.warn(
            f"    429 (лимит): {s['rate_limits']} · паузы ≈{s['cooldown_seconds']:.0f} сек"
        )
    if s["retries"]:
        state.info(f"    сетевых ретраев: {s['retries']}")
    # Browser stats (та же воронка, что в бою: один браузер на прогон)
    try:
        from .http_client import browser_stats
        from .cache import cache_stats
        bs = browser_stats()
        total_browser = int(bs.get("pages_fetched") or 0)
        # Попадания в кэш страниц: при повторном прогоне браузер не открывает
        # карточку вообще, так что без этой цифры выигрыш не видно.
        try:
            hits = int(cache_stats().get("hits") or 0)
        except Exception:
            hits = 0
        if total_browser > 0 or hits:
            state.info(f"    браузер: {bs.get('pages_fetched', 0)} стр. "
                       f"кэш: {hits} ошибок: {bs.get('pages_error', 0)}")
    except Exception:
        pass


def _print_prefilter_stats() -> None:
    """Сколько записей отбросил предфильтр сбора и почему.

    Сбор выкидывает то, что всё равно сняли бы фильтры (чёрный список,
    «только без сайтов», соцсети), поэтому эти записи не появляются в живой
    таблице и не попадают в raw. Печатаем дельту с прошлого вызова — строка
    попадает в лог конца каждого города, а не только в итог за прогон.
    """
    try:
        delta = state.crawl_skip_take_delta()
    except Exception:
        return
    if not delta.get("total"):
        return
    state.info(f"    🚫 предфильтр: пропущено {delta['total']} ({state.crawl_skip_text(delta)})")
    state.syslog(f"  crawl_skip: total={delta['total']} "
                 f"({state.crawl_skip_text(state.crawl_skip_summary())})")


_PLATFORM_LABELS = {
    "vk": "ВКонтакте", "instagram": "Instagram", "facebook": "Facebook",
    "telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok",
    "ok": "Одноклассники", "twitter": "Twitter/X", "whatsapp": "WhatsApp",
}


def _stats_payload(records: list[dict]) -> dict:
    """Structured form of the summary for the web UI (rows + bars)."""
    q_counts = Counter(r.get("query", "") for r in records)
    by_query = ([{"label": q or "без запроса", "count": c} for q, c in q_counts.most_common()]
                if len(q_counts) > 1 else [])
    by_social = [
        {"label": _PLATFORM_LABELS.get(p, p), "count": cnt}
        for p in KNOWN_PLATFORMS
        if (cnt := sum(1 for r in records if r.get(p)))
    ]
    cats: Counter = Counter()
    for r in records:
        for cat in r.get("category", "").split(","):
            if c2 := cat.strip():
                cats[c2] += 1
    return {
        "total": len(records),
        "by_query": by_query,
        "by_social": by_social,
        "top_categories": [{"label": c, "count": n} for c, n in cats.most_common(5)],
    }


def print_stats(records: list[dict]) -> None:
    if not records:
        return
    if state._LOG_FN:
        # Web UI: one structured event → a real card with bars and spacing.
        payload = _stats_payload(records)
        state.stats_event(payload)
        # Keep a compact record in the run file (the payload itself is UI-only).
        state.syslog(
            "stats: total={t} socials={s} top={c}".format(
                t=payload["total"],
                s=", ".join(f"{x['label']}={x['count']}" for x in payload["by_social"]) or "-",
                c=", ".join(f"{x['label']}={x['count']}" for x in payload["top_categories"]) or "-",
            )
        )
        return
    state.ok(f"\n{'═' * 58}")
    state.ok(f"  📊 СТАТИСТИКА  ({len(records)} записей)")
    state.ok(f"{'═' * 58}")

    q_counts = Counter(r.get("query", "") for r in records)
    if len(q_counts) > 1:
        state.info("  По запросам:")
        for q, c in q_counts.most_common():
            state.info(f"    {q:<30} {c} шт.")

    labels = {
        "vk": "ВКонтакте", "instagram": "Instagram", "facebook": "Facebook",
        "telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok",
        "ok": "Одноклассники", "twitter": "Twitter/X", "whatsapp": "WhatsApp",
    }
    state.info("  По соцсетям:")
    for p in KNOWN_PLATFORMS:
        cnt = sum(1 for r in records if r.get(p))
        if cnt:
            state.info(f"    {labels.get(p, p):<18} {'█' * min(cnt, 30)} {cnt}")

    cats: Counter = Counter()
    for r in records:
        for cat in r.get("category", "").split(","):
            if c2 := cat.strip():
                cats[c2] += 1
    if cats:
        state.info("  Топ категорий:")
        for cat, cnt in cats.most_common(5):
            state.info(f"    {cat:<30} {cnt} шт.")

    state.ok(f"{'═' * 58}\n")
