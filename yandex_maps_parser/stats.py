"""
Console statistics summary.
"""
from collections import Counter

from .constants import KNOWN_PLATFORMS, SOCIAL_COLORS
from . import state


def print_limit_stats() -> None:
    """Print request/rate-limit usage from the shared HTTP counters."""
    from .http_client import get_stats
    s = get_stats()
    if not s["requests"]:
        return
    # «Запросов к API» — без слова API строка читалась как количество запросов
    # поиска (которых может быть 3, а HTTP-запросов — 43).
    state.ok(f"\n  Запросов к API: {s['requests']}")
    # Human-readable request kinds — raw kinds go to the developer file only.
    kind_labels = {
        "search":   "Поисковые запросы",
        "geocode":  "Геокодирование",
        "detail":   "Загрузка карточек",
        "validate": "Проверка соцсетей",
        "other":    "Прочие запросы",
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
    # Browser stats
    try:
        from .browser_client import get_stats as _bs
        bs = _bs()
        total_browser = bs["pages_fetched"] + bs["cache_hits"]
        if total_browser > 0:
            state.info(f"    браузер: {bs['pages_fetched']} стр. ({bs['avg_time']:.1f}с/стр.) кэш: {bs['cache_hits']} ошибок: {bs['pages_error']} рестартов: {bs['restarts']}")
    except Exception:
        pass


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
