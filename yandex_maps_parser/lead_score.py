"""Lead Score — 0..100 «насколько это горячий клиент для продажи сайта».

Базовые сигналы складываются ровно в 100: столько наберёт идеальный лид даже
без ключа ВК. Активность сообщества — бонус сверху, который добирает баллы до
100, но не растягивает шкалу: ВК проверяется только при заданном ключе, и
делать 90 потолком «потому что нет токена» нечестно.
"""
from datetime import date, datetime, timedelta

from .constants import EXPENSIVE_CATEGORY_KEYWORDS

# Веса подобраны под вопрос «кому нужен сайт и кто за него заплатит».
NO_WEBSITE = 30          # главный сигнал: своего сайта нет
RATING_GOOD = 15         # бизнес реальный, клиенты им довольны
REVIEWS_MANY = 15        # есть поток клиентов
HAS_PHONE = 10           # до него можно дозвониться
EXPENSIVE_CATEGORY = 10  # услуги дорогие — бюджет на сайт есть
SOCIALS_PRESENT = 10     # уже ведёт маркетинг, просто не на своём сайте
NEW_BUSINESS = 10        # недавно появился на Картах — сайт нужен сейчас

VK_ACTIVE = 10           # бонус: сообщество живо
VK_SEMI = 5              # бонус: сообщество ещё подаёт признаки жизни

BASE_MAX = (NO_WEBSITE + RATING_GOOD + REVIEWS_MANY + HAS_PHONE
            + EXPENSIVE_CATEGORY + SOCIALS_PRESENT + NEW_BUSINESS)
MAX_SCORE = 100
NEW_BUSINESS_MONTHS = 12

SOCIAL_FIELDS = ("vk", "telegram", "instagram", "whatsapp")

_AGGREGATORS = r"taplink|linktree|linktr\.ee|becons\.ai|illions\.app"


def has_own_website(record: dict) -> bool:
    """A link page (taplink) does not count as a website — same rule as the collection-time filter, so the score agrees with «Только без сайтов»."""
    import re
    site = (record.get("website") or record.get("aggregator_url") or "").strip()
    if not site:
        return False
    return not re.search(_AGGREGATORS, site, re.I)


def _num(value, default=0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _has_socials(record: dict) -> bool:
    return any(str(record.get(field) or "").strip() for field in SOCIAL_FIELDS)


def is_new_business(record: dict, months: int = NEW_BUSINESS_MONTHS) -> bool:
    """«Добавлено» на Картах недавно. Пустая или битая дата баллов не даёт —
    в отличие от фильтра «Только новые», где неизвестная дата не отсеивает
    запись, здесь неизвестное не должно превращаться в плюс."""
    raw = str(record.get("added_at") or "").strip()
    if len(raw) < 10:
        return False
    try:
        added = datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return added >= (date.today() - timedelta(days=int(months) * 30))


def is_expensive_category(category: str) -> bool:
    low = (category or "").lower()
    return any(word in low for word in EXPENSIVE_CATEGORY_KEYWORDS)


def compute_score(record: dict) -> tuple[int, list[str]]:
    """Return (score, reasons) for one record."""
    score = 0
    reasons: list[str] = []

    if not has_own_website(record):
        score += NO_WEBSITE
        reasons.append(f"нет сайта +{NO_WEBSITE}")

    # Rating is stored on a 5-point scale; some sources return 0..50.
    rating = _num(record.get("rating"))
    if rating > 5:
        rating = rating / 10
    if rating >= 4.5:
        score += RATING_GOOD
        reasons.append(f"рейтинг {rating:g} +{RATING_GOOD}")

    reviews = _num(record.get("reviews_count"))
    if reviews >= 50:
        score += REVIEWS_MANY
        reasons.append(f"отзывов {int(reviews)} +{REVIEWS_MANY}")

    if (record.get("phone") or "").strip():
        score += HAS_PHONE
        reasons.append(f"есть телефон +{HAS_PHONE}")

    if is_expensive_category(record.get("category") or ""):
        score += EXPENSIVE_CATEGORY
        reasons.append(f"дорогая категория +{EXPENSIVE_CATEGORY}")

    if _has_socials(record):
        score += SOCIALS_PRESENT
        reasons.append(f"есть соцсети +{SOCIALS_PRESENT}")

    if is_new_business(record):
        score += NEW_BUSINESS
        reasons.append(f"недавно на Картах +{NEW_BUSINESS}")

    # ВК — бонус: без ключа vk_activity пуст, и вклад просто не появляется.
    activity = (record.get("vk_activity") or "").lower()
    if activity == "active":
        score += VK_ACTIVE
        reasons.append(f"активный ВК +{VK_ACTIVE} (бонус)")
    elif activity == "semi":
        score += VK_SEMI
        reasons.append(f"полуактивный ВК +{VK_SEMI} (бонус)")

    return min(MAX_SCORE, score), reasons


def annotate_records(records: list[dict]) -> None:
    """Fill `lead_score` (and `lead_score_why`) in place."""
    for record in records:
        try:
            score, reasons = compute_score(record)
        except Exception:
            score, reasons = 0, []
        record["lead_score"] = score
        record["lead_score_why"] = ", ".join(reasons)
