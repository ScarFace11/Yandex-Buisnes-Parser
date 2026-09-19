"""
Immutable constants shared across all parser modules.
"""
import re

# ── Агрегаторы ссылок — считаются «без сайта» ────────────────
LINK_AGGREGATORS: set[str] = {
    "taplink.cc", "linktr.ee", "vk.cc", "bio.link", "beacons.ai",
    "linkinbio.at", "solo.to", "lnk.bio", "campsite.bio", "carrd.co",
    "milkshake.app", "shorby.com", "mypage.bio", "linkpop.com",
    "bento.me", "lit.link", "snipfeed.co", "koji.to", "allmylinks.com",
    "withkoji.com", "wlo.link", "heylink.me", "direct.me", "me.page",
    "tap.bio", "joy.link", "instapage.com", "flowpage.com", "contact.page",
    "mtr.bio", "shor.by", "linkin.bio", "seemehigh.com", "4.bio",
}

# Only the four client-facing networks are collected (user decision 2026-09);
# every other platform found on a page is ignored, not stored.
SOCIAL_DOMAINS: dict[str, re.Pattern] = {
    "vk":        re.compile(r"vk\.com|vk\.ru", re.I),
    "telegram":  re.compile(r"t\.me|telegram\.me", re.I),
    "instagram": re.compile(r"instagram\.com", re.I),
    "whatsapp":  re.compile(r"wa\.me|whatsapp\.com", re.I),
}

KNOWN_PLATFORMS: list[str] = list(SOCIAL_DOMAINS.keys())

EXCLUDE_URLS = re.compile(
    r"yandex\.(ru|com|maps)|mapsyandex|/yandex\.|vk\.com/yandexmaps"
    r"|t\.me/mapsyandex|instagram\.com/yandex",
    re.I,
)

# Цвета соцсетей для Excel (светлые оттенки бренд-цветов)
SOCIAL_COLORS: dict[str, str] = {
    "vk":        "D6E4F0",
    "telegram":  "D6EEF8",
    "instagram": "FDE7F1",
    "whatsapp":  "E8F5E9",
}

# Бренд-цвета для HTML-карты
SOCIAL_BADGE_COLORS: dict[str, str] = {
    "vk":        "#4C75A3",
    "telegram":  "#2CA5E0",
    "instagram": "#E1306C",
    "whatsapp":  "#25D366",
}

SOCIAL_LABELS: dict[str, str] = {
    "vk": "VK", "telegram": "TG", "instagram": "IG", "whatsapp": "WA",
}

# Палитра цветов маркеров для разных запросов
QUERY_COLORS = [
    "blue", "red", "green", "purple", "orange",
    "darkblue", "darkred", "darkgreen", "cadetblue", "lightred",
]

CSV_FIELDS = [
    "reviewed",
    # Lead score is computed at stage 2 — first column after the mark so a
    # «hot» contact is visible without scrolling.
    "lead_score",
    "name", "category", "address", "phone",
    # Restored: the score needs real rating/reviews values, not guesses.
    "rating", "reviews_count",
    "vk", "instagram", "telegram", "whatsapp",
    # VK activity (stage 2, official API — empty when no token is set).
    "vk_activity", "vk_followers", "vk_last_post_days",
    "aggregator_url",
    "yandex_maps_url",
    "query", "parsed_at",
    # Two-stage pipeline: raw files must carry the city so stage 2 can group
    # by «Название + Город» without a new crawl.
    # NOTE: "website" is deliberately NOT a report column any more — for 2GIS
    # runs it never held a real site (the scraper picked a page-wide analytics
    # script, see enrichment.py) and the user asked for a map link instead.
    # Raw files still carry it (exporters.save_excel(extra_fields=("website",)))
    # so the «только без сайтов» filter keeps working in stage 2.
    "city",
]

# Lead Score: категории, за услуги которым платят выше среднего.
# Сравнение идёт по подстроке в поле category (регистр не важен).
EXPENSIVE_CATEGORY_KEYWORDS = (
    "стоматолог", "dent", "клиник", "медицин", "косметолог",
    "недвижим", "агентств недвижим", "застройщик", "риелтор",
    "автосервис", "автосалон", "автомойк", "шиномонтаж", "автошкол",
    "строитель", "ремонт квартир", "отделк", "кровл", "окн", "натяжн",
    "юрист", "юридическ", "адвокат", "бухгалтер", "аудит",
    "мебел", "кухн", "шкаф",
    "туризм", "турагентств", "отел", "гостиниц",
    "банкетн", "ресторан", "свадебн", "event",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Excel column labels
HEADER_LABELS = {
    "reviewed":      "✓ Просмотрено",
    "name":          "Название",
    "category":      "Категория",
    "address":       "Адрес",
    "phone":         "Телефон",
    "lead_score":    "Оценка лида",
    "rating":        "Рейтинг",
    "reviews_count": "Отзывов",
    "vk_activity":   "Активность ВК",
    "vk_followers":  "Подписчики ВК",
    "vk_last_post_days": "Последний пост (дней)",
    "vk":            "ВКонтакте",
    "instagram":     "Instagram",
    "facebook":      "Facebook",
    "telegram":      "Telegram",
    "youtube":       "YouTube",
    "tiktok":        "TikTok",
    "ok":            "Одноклассники",
    "twitter":       "Twitter / X",
    "whatsapp":      "WhatsApp",
    "aggregator_url": "Taplink / Linktree",
    "yandex_maps_url": "Яндекс.Карты",
    "query":         "Запрос",
    "parsed_at":     "Дата сбора",
    "city":          "Город",
    "website":       "Сайт",
    # 2GIS URL column is appended to CSV_FIELDS by exporters; the label lives
    # here so older files with a «2ГИС» header still load back correctly.
    "twogis_url":    "2ГИС",
}

COL_WIDTHS = {
    "reviewed": 13, "name": 28, "category": 22,
    "lead_score": 13, "rating": 10, "reviews_count": 11,
    "vk_activity": 15, "vk_followers": 13, "vk_last_post_days": 16,
    "address": 32, "phone": 18,
    "vk": 30, "instagram": 30, "facebook": 30, "telegram": 30,
    "youtube": 30, "tiktok": 28, "ok": 28, "twitter": 28, "whatsapp": 28,
    "aggregator_url": 32,
    "yandex_maps_url": 36, "query": 14, "parsed_at": 18,
    "city": 18, "website": 26,
}
