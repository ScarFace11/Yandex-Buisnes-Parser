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

SOCIAL_DOMAINS: dict[str, re.Pattern] = {
    "vk":        re.compile(r"vk\.com", re.I),
    "telegram":  re.compile(r"t\.me|telegram\.me", re.I),
    "instagram": re.compile(r"instagram\.com", re.I),
    "facebook":  re.compile(r"facebook\.com|fb\.com|fb\.me", re.I),
    "youtube":   re.compile(r"youtube\.com|youtu\.be", re.I),
    "tiktok":    re.compile(r"tiktok\.com", re.I),
    "ok":        re.compile(r"ok\.ru|odnoklassniki\.ru", re.I),
    "twitter":   re.compile(r"twitter\.com|x\.com", re.I),
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
    "facebook":  "E7EEFB",
    "youtube":   "FDECEC",
    "tiktok":    "E8ECEC",
    "ok":        "FDEFE2",
    "twitter":   "E8F0FB",
    "whatsapp":  "E8F5E9",
}

# Бренд-цвета для HTML-карты
SOCIAL_BADGE_COLORS: dict[str, str] = {
    "vk":        "#4C75A3",
    "telegram":  "#2CA5E0",
    "instagram": "#E1306C",
    "facebook":  "#1877F2",
    "youtube":   "#FF0000",
    "tiktok":    "#010101",
    "ok":        "#EE8208",
    "twitter":   "#1DA1F2",
    "whatsapp":  "#25D366",
}

SOCIAL_LABELS: dict[str, str] = {
    "vk": "VK", "telegram": "TG", "instagram": "IG", "facebook": "FB",
    "youtube": "YT", "tiktok": "TT", "ok": "OK", "twitter": "X", "whatsapp": "WA",
}

# Палитра цветов маркеров для разных запросов
QUERY_COLORS = [
    "blue", "red", "green", "purple", "orange",
    "darkblue", "darkred", "darkgreen", "cadetblue", "lightred",
]

CSV_FIELDS = [
    "reviewed",
    "name", "category", "description", "address", "phone",
    "hours", "rating", "reviews",
    "vk", "instagram", "facebook", "telegram",
    "youtube", "tiktok", "ok", "twitter", "whatsapp",
    "other_socials", "socials_valid",
    "aggregator_url",
    "yandex_maps_url",
    "query", "parsed_at",
]

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
    "description":   "Описание",
    "address":       "Адрес",
    "phone":         "Телефон",
    "hours":         "Часы работы",
    "rating":        "Рейтинг",
    "reviews":       "Отзывов",
    "vk":            "ВКонтакте",
    "instagram":     "Instagram",
    "facebook":      "Facebook",
    "telegram":      "Telegram",
    "youtube":       "YouTube",
    "tiktok":        "TikTok",
    "ok":            "Одноклассники",
    "twitter":       "Twitter / X",
    "whatsapp":      "WhatsApp",
    "other_socials": "Другие соцсети",
    "socials_valid": "Соцсети активны",
    "aggregator_url": "Taplink / Linktree",
    "yandex_maps_url": "Яндекс.Карты",
    "query":         "Запрос",
    "parsed_at":     "Дата сбора",
}

COL_WIDTHS = {
    "reviewed": 13, "name": 28, "category": 22, "description": 40,
    "address": 32, "phone": 18, "hours": 22, "rating": 9, "reviews": 9,
    "vk": 30, "instagram": 30, "facebook": 30, "telegram": 30,
    "youtube": 30, "tiktok": 28, "ok": 28, "twitter": 28, "whatsapp": 28,
    "other_socials": 28, "socials_valid": 20, "aggregator_url": 32,
    "yandex_maps_url": 36, "query": 14, "parsed_at": 18,
}
