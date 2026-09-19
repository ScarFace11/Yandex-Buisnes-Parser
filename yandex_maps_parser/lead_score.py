"""
Lead Score — 0..90 «насколько это горячий клиент для продажи сайта».

Computed at stage 2 (после объединения филиалов и проверки активности ВК, до
фильтров), so the numbers it needs are already in the record.

Breakdown (each item is reported so the UI can explain the number):

    нет сайта            +30   главный сигнал: сайта нет вообще
    активный ВК          +20   владелец читает сообщения (полуактивный +10)
    рейтинг >= 4.5       +15   бизнес нравится людям
    отзывов >= 50        +15   есть поток клиентов
    есть телефон          +5   можно позвонить сегодня
    дорогая категория     +5   за сайт платят выше среднего

Maximum is 90: «новый бизнес (< 6 мес)» из ТЗ is not counted because neither
Yandex nor 2GIS exposes a registration date. Missing data never adds points
and never subtracts them — it simply does not count.
"""
from .constants import EXPENSIVE_CATEGORY_KEYWORDS

# Bonus values, kept together so a test can assert the table.
NO_WEBSITE = 30
VK_ACTIVE = 20
VK_SEMI = 10
RATING_GOOD = 15
REVIEWS_MANY = 15
HAS_PHONE = 5
EXPENSIVE_CATEGORY = 5

MAX_SCORE = NO_WEBSITE + VK_ACTIVE + RATING_GOOD + REVIEWS_MANY + HAS_PHONE + EXPENSIVE_CATEGORY

_AGGREGATORS = r"taplink|linktree|linktr\.ee|becons\.ai|illions\.app"


def has_own_website(record: dict) -> bool:
    """A link page (taplink) does not count as a website — same rule as the
    collection-time filter, so the score agrees with «Только без сайтов»."""
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

    activity = (record.get("vk_activity") or "").lower()
    if activity == "active":
        score += VK_ACTIVE
        reasons.append(f"активный ВК +{VK_ACTIVE}")
    elif activity == "semi":
        score += VK_SEMI
        reasons.append(f"полуактивный ВК +{VK_SEMI}")

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

    return score, reasons


def annotate_records(records: list[dict]) -> None:
    """Fill `lead_score` (and `lead_score_why`) in place."""
    for record in records:
        try:
            score, reasons = compute_score(record)
        except Exception:
            score, reasons = 0, []
        record["lead_score"] = score
        record["lead_score_why"] = ", ".join(reasons)
