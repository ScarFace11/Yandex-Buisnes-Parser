"""Нормализация ссылок на соцсети и телефонов (качество экспортных данных)."""
import re
from html import unescape as _html_unescape


# ── Телефоны ──────────────────────────────────────────────────

_PHONE_DIGITS_RE = re.compile(r"\D")


def _phone_digits(raw: str) -> str:
    """Только цифры из произвольной строки с номером."""
    return _PHONE_DIGITS_RE.sub("", raw or "")


def normalize_ru_phone(raw: str) -> str:
    """Один номер → «E.164 без плюса» (11 цифр, ведущая 7), или ""."""
    digits = _phone_digits(raw)
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78":
        return ""
    digits = "7" + digits[1:]
    if digits[1:4] == "800":
        return ""
    return digits


def split_phones(phone_field: str) -> list[str]:
    """Разбить поле phone (несколько номеров через «,»/«;») на части."""
    field = (phone_field or "").strip()
    if not field:
        return []
    return [p.strip() for p in re.split(r"[;,]", field) if p.strip()]


def dedupe_phones(phone_field: str) -> str:
    """Убрать дубли номеров в поле, сохранить порядок первого появления."""
    seen: set[str] = set()
    out: list[str] = []
    for part in split_phones(phone_field):
        digits = _phone_digits(part)
        key = normalize_ru_phone(part) or digits
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(part)
    return ", ".join(out)


# ── WhatsApp ──────────────────────────────────────────────────

_WA_HOST_RE = re.compile(r"^(?:www\.)?(?:wa\.me|api\.whatsapp\.com)$", re.I)
_WA_QUERY_NUM_RE = re.compile(r"[?&]phone=(\d+)", re.I)


def normalize_whatsapp_url(url: str) -> str | None:
    """wa.me/<номер> → канонический вид с валидным номером, или None. wa.me принимает только международный номер цифрами (без «+», «-», скобок, ведущей «8» для РФ/КР)."""
    if not url:
        return None
    m = re.match(r"^https?://([^/?#]+)(/[^?#]*)?(\?[^#]*)?", url.strip(), re.I)
    if not m or not _WA_HOST_RE.match(m.group(1) or ""):
        return None
    path = (m.group(2) or "").lstrip("/")
    query = m.group(3) or ""
    raw = path
    qm = _WA_QUERY_NUM_RE.search(query)
    if qm:
        raw = qm.group(1)
    digits = _phone_digits(raw)
    # Стратегия: не угадывать страну, а опираться на то, что wa.me всегда ждёт полный международный номер ЦИФРАМИ.
    if len(digits) >= 11 and digits[0] == "8":
        digits = digits[1:]
    if len(digits) == 10 and digits[0] != "7" and not digits.startswith("996"):
        digits = "7" + digits        # РФ: 9376… → 7937… (КР 996… не трогаем)
    if len(digits) < 10 or len(digits) > 15:
        return None
    return f"https://wa.me/{digits}"


# ── VK ────────────────────────────────────────────────────────

_VK_HOST_RE = re.compile(r"^(?:m\.|www\.)?(?:vk\.ru|vk\.com|vkontakte\.ru)$", re.I)


def normalize_vk_url(url: str) -> str | None:
    """vk.ru/… и vk.com/… → https://vk.com/… (один канонический формат)."""
    if not url:
        return None
    url = _html_unescape(url.strip())
    m = re.match(r"^https?://([^/?#]+)(/.*)?(\?.*)?(#.*)?$", url, re.I)
    if not m or not _VK_HOST_RE.match(m.group(1) or ""):
        return None
    path = (m.group(2) or "").split("?", 1)[0].split("&", 1)[0]
    return f"https://vk.com{path}"


# ── Схема сайта ───────────────────────────────────────────────

def ensure_https(url: str) -> str:
    """http:// → https:// для пользовательских сайтов (крупные площадки давно на TLS; «http://taplink.cc/...» выглядит и валидируется хуже)."""
    u = (url or "").strip()
    if u.lower().startswith("http://"):
        return "https://" + u[7:]
    return u


# ── Запись целиком ───────────────────────────────────────────

def normalize_record(rec: dict) -> dict:
    """Канонические значения полей одной записи для файла экспорта."""
    out = dict(rec)
    if out.get("phone"):
        out["phone"] = dedupe_phones(out["phone"])
    wa = out.get("whatsapp")
    if wa:
        # Колонка whatsapp заполняется только ссылкой wa.me/api.whatsapp.com (фильтр в constants.SOCIAL_PATTERNS): не распознанная ссылка нерабочая — вычищаем, чтобы в файл не попадал мусор.
        out["whatsapp"] = normalize_whatsapp_url(wa) or ""
    vk = out.get("vk")
    if vk:
        # Не-URL (легаси-ручные значения) оставляем как есть.
        out["vk"] = normalize_vk_url(vk) or vk
    if out.get("website"):
        out["website"] = ensure_https(out["website"])
    # Единая колонка «Сайт / Таплинк»: обычный сайт организации показываем там же, где раньше был только taplink/linktree.
    if out.get("website") and not out.get("aggregator_url"):
        out["aggregator_url"] = out["website"]
    return out
