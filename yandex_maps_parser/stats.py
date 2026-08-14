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
    state.ok(f"\n  Запросы: {s['requests']}")
    for kind in ("search", "geocode", "detail", "validate", "other"):
        n = s["by_kind"].get(kind, 0)
        if n:
            state.info(f"    {kind:<9} {n}")
    if s["rate_limits"]:
        state.warn(
            f"    429 (лимит): {s['rate_limits']} · паузы ≈{s['cooldown_seconds']:.0f} сек"
        )
    if s["retries"]:
        state.info(f"    сетевых ретраев: {s['retries']}")


def print_stats(records: list[dict]) -> None:
    if not records:
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

    agg = sum(1 for r in records if r.get("aggregator_url"))
    if agg:
        state.info(f"  Через taplink/linktree : {agg}")

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
