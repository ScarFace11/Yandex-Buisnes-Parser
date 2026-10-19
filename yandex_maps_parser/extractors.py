"""
HTML / text extraction: social links, emails, descriptions, reviews.
"""
import json
import re
from html import unescape as _html_unescape

from .constants import (
    LINK_AGGREGATORS,
    SOCIAL_DOMAINS,
    EXCLUDE_URLS,
)
from . import state

# ── Compiled patterns ─────────────────────────────────────────

# Метки, которые площадки и Яндекс вешают на исходящие ссылки. `trackcode` —
# собственная метка Яндекс.Карт: без неё ссылка из карточки приходит вида
# «https://vk.ru/club?trackcode=4433fd7c…» и в выгрузке выглядит мусором.
_UTM_RE = re.compile(
    r'[?&](utm_\w+|ref|from|fbclid|gclid|yclid|ysclid|trackcode|erid|si|igshid)=[^&]*',
    re.I,
)
_TRAILING_RE = re.compile(r'[?&]$')

_VK_NON_PROFILE = re.compile(
    r'vk\.com/(wall|photo|video|album|doc|club(?=[?#])|app|feed|away|share|'
    r'login|join|invite|oauth|im|search|explore|fave|bookmarks)\b',
    re.I,
)
_IG_NON_PROFILE = re.compile(
    r'instagram\.com/(p|reel|tv|stories|explore|accounts|'
    r'ar|challenge|static|_n|sharer)\b',
    re.I,
)
_FB_NON_PROFILE = re.compile(
    r'facebook\.com/(permalink|share|dialog|plugins|login|photo|video|'
    r'events|groups(?=/[0-9])|pages/create|sharer|tr\b|ads\b|pixel|'
    r'watch|gaming|marketplace|policies|privacy|business|settings|recover|reg)\b',
    re.I,
)
_YOUTUBE_NON_PROFILE = re.compile(
    r'youtube\.com/(embed|watch|playlist|live|attribution_link|redirect|'
    r'howyoutubeworks|about|press|creators)\b',
    re.I,
)
_TIKTOK_NON_PROFILE = re.compile(
    r'tiktok\.com/(embed|discover|explore|trending|music|tag|share|upload|search)\b',
    re.I,
)
_OK_NON_PROFILE = re.compile(
    r'ok\.ru/(video|live|search|market|app|mail|feed|groups|sticker|emoji|dk)\b',
    re.I,
)
_TWITTER_NON_PROFILE = re.compile(
    r'(?:twitter|x\.com)/(intent|share|search|home|hashtag|explore|settings|'
    r'notifications|messages|compose|status|i/)\b',
    re.I,
)

# ── Блок контактов самой организации ──────────────────────────
# Страница карточки — это НЕ только данные организации: в state-JSON лежит
# блок «похожие организации» (ключ `competitor`), подборки и соседние
# карточки, у каждой свои ссылки и телефон. Раньше они подмешивались к
# записи. Контакты самой организации живут в секции «Контакты»
# (заголовок card-section-header__title) — разбор и ограничиваем ею.
_CONTACTS_SEC_RE = re.compile(
    r'<h[23][^>]*class="[^"]*card-section-header__title[^"]*"[^>]*>\s*Контакты\s*</h[23]>'
    r'.*?'
    # Конец секции: следующий заголовок раздела, скрипт (state страницы) или
    # конец документа — дальше на странице уже чужие данные.
    r'(?=<h[23][^>]*class="[^"]*card-section-header__title|<script|</body>|$)',
    re.S,
)

# Ключи встроенных данных, которые описывают ЧУЖИЕ организации:
# `competitor` — блок «похожие организации», `relatedAdverts`/`relatedPlaces`
# — подборки и соседние карточки. Их контакты и оценки никогда не
# принадлежат разбираемой карточке, поэтому ветка пропускается целиком.
_FOREIGN_JSON_KEYS = frozenset({
    "competitor", "relatedadverts", "relatedplaces",
    "nearbyonmap", "nearbyoncard",
})


def _is_foreign_key(key) -> bool:
    return str(key).lower() in _FOREIGN_JSON_KEYS


def own_contacts_html(html: str) -> str:
    """Секция «Контакты» карточки — или пустая строка.

    Пустая строка означает «страница не карточка организации» (фрагмент,
    JSON выдачи, чужой сайт) — вызывающий в этом случае разбирает вход как
    раньше, без ограничения.
    """
    if not html:
        return ""
    m = _CONTACTS_SEC_RE.search(html)
    return m.group(0) if m else ""


_JSON_BLOB_RE = re.compile(
    r'(?:window\.(?:__)?(?:NUXT|INITIAL_STATE|SERVER_STATE|PRELOADED_STATE|'
    r'APP_STATE|REDUX_STATE|DATA|STATE)(?:__)?'
    r'|window\.serverState'
    # NOTE: whitespace is allowed on BOTH sides of the «=» — pages are not
    # always minified (`window.__INITIAL_STATE__ = {` used to match nothing,
    # so both the socials and the rating/reviews of such a page were lost).
    r'|<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
    r'|<script[^>]+type=["\']application/json["\'][^>]*>)\s*[=]*\s*(\{)',
    re.I,
)

_ANTIBOT_MARKERS = (
    "showcaptcha", "robot", "captcha", "i-am-not-robot",
    "access denied", "too many requests",
)

# Fast pre-check: does this string look like it could contain social URLs?
_HTTP_LIKE = re.compile(r'https?://[^\s"\'<>\\\\,}{]+', re.I)


# ── URL helpers ───────────────────────────────────────────────

def _is_aggregator(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == agg or host.endswith("." + agg) for agg in LINK_AGGREGATORS)
    except Exception:
        return False


def _clean_social_url(url: str) -> str:
    """Remove UTM / tracking parameters from a social URL.

    В атрибутах HTML «&» приходит как «&amp;», поэтому ссылка сначала
    раскодируется: иначе `?ref=x&amp;trackcode=y` после снятия `ref`
    превращалось в `.../club&amp;trackcode=y` — обрывок запроса вместо адреса
    профиля. Целый запрос (`?v=…` у YouTube, `?phone=…` у WhatsApp) не
    трогается; отрезается только хвост, начинающийся с «&» без «?»:
    это всегда остаток снятого параметра, а не самостоятельный запрос.
    """
    url = _html_unescape(url or "")
    url = _UTM_RE.sub("", url)
    if "?" not in url:
        url = url.split("&", 1)[0]
    url = _TRAILING_RE.sub("", url)
    return url.rstrip("/.,);\"'")


def _normalize_social_url(platform: str, url: str) -> str | None:
    """Return a canonical profile URL, or None if the URL is not a profile."""
    from urllib.parse import urlparse, urlunparse
    try:
        parsed = urlparse(url)
        # Social pages are served over https; pages hand out plain http://
        # links and the exported column then looks untrustworthy/broken in Excel.
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
        if platform == "vk":
            if _VK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "instagram":
            if _IG_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "facebook":
            if _FB_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "youtube":
            if _YOUTUBE_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "tiktok":
            if _TIKTOK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "ok":
            if _OK_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "twitter":
            if _TWITTER_NON_PROFILE.search(url):
                return None
            return urlunparse(parsed._replace(query="", fragment=""))
        if platform == "telegram":
            return urlunparse(parsed._replace(query="", fragment=""))
        return urlunparse(parsed._replace(fragment=""))
    except Exception:
        return url# ── Fetch ─────────────────────────────────────────────────────

def fetch_html(url: str, session=None, biz_id: str = "") -> str:
    """Загрузить страницу карточки реальным браузером (CDP), с дисковым кэшем.

    HTTP-пути больше нет: прямые запросы к Яндекс.Картам ловит антибот
    (p95 до 325 с на страницу, частые заглушки), а сам IP/аккаунт после
    серии таких обращений выглядит подозрительно. Браузер отдаёт ту же
    страницу за секунды и ничем не отличается от обычного пользователя.

    Единственный путь загрузки карточек: и сюда, и в `enrichment.enrich`
    приходят только эти вызовы — значит, кэш здесь работает для всего
    прогона. Кэшируются только здоровые страницы (см. `cache.set_cached`):
    антибот-заглушка на диск не попадает, иначе она пережила бы повторный
    прогон и организация осталась бы без деталей.

    Аргумент `session` оставлен для совместимости вызовов — браузерная
    загрузка сессии не требует. Пустая строка — страницу получить не
    удалось (нет браузера, остановка, ошибка навигации, антибот).
    """
    # Кэш страниц: повторный прогон не ждёт браузер на каждой карточке.
    if biz_id:
        try:
            from .cache import get_cached
            cached = get_cached(biz_id)
            if cached:
                state.syslog(f"cache_hit: biz_id={biz_id}")
                return cached
        except Exception:
            pass

    from . import cdp_client
    text = ""
    try:
        text = cdp_client.fetch_page(url, biz_id=biz_id) or ""
    except Exception as exc:
        state.syslog(f"fetch_html: browser error: {type(exc).__name__}: {exc}")
        return ""

    if not text:
        # Остановка/пропуск города — это не потерянная карточка: считать её
        # в счётчике значило бы показать в итоге «не прочитано N» там, где
        # пользователь сам прервал прогон.
        aborted = bool((state._STOP_EVENT and state._STOP_EVENT.is_set())
                       or state.is_skip_city())
        if aborted:
            return ""
        reason = ""
        try:
            reason = cdp_client.take_failure_reason()
        except Exception:
            reason = ""
        if reason not in state.READ_FAILURE_LABELS:
            reason = "no_page"
        state.warn(f"Карточка не открылась в браузере ({state.READ_FAILURE_LABELS[reason]}) "
                   "— детали этой организации пропущены.")
        # Счётчик потерь: запись всё равно попадёт в выгрузку, и без этой
        # цифры её «пустые контакты» выглядят как «так и есть».
        state.inc_read_failure(reason)
        return ""

    lower = text[:4000].lower()
    if any(m in lower for m in _ANTIBOT_MARKERS):
        state.warn("Яндекс вернул anti-bot страницу — детали этой карточки пропущены.")
        state.inc_read_failure("antibot")
        return ""

    if biz_id:
        try:
            from .cache import set_cached
            set_cached(biz_id, text)
        except Exception:
            pass
    return text


# ── Extractors ────────────────────────────────────────────────

# ── Разобранная страница ──────────────────────────────────────
# Одна карточка разбирается несколькими функциями подряд (соцсети, рейтинг,
# телефон, сайт), и каждая раньше ЗАНОВО искала встроенный JSON и секцию
# контактов: встроенные данные страницы разбирались json до четырёх раз
# на одну и ту же страницу (замер на карточках из кэша: 15.7 мс на страницу,
# из них 13 мс — повторный разбор того же самого). PageView разбирает и то,
# и другое ОДИН раз и отдаёт всем шагам уже готовое.
#
# Поведение при этом не меняется: тот же предел 200 КБ, тот же список
# пропускаемых ветвей чужих организаций, тот же порядок блобов — меняется
# только число повторов. Функции без PageView (`extract_socials(text)` и др.)
# работают как раньше: это их контракт, на нём стоят тесты и внешние вызовы.


class PageView:
    """Страница карточки, разобранная один раз: блобы JSON и секция контактов."""

    JSON_LIMIT = 200_000

    __slots__ = ("html", "head", "_blobs", "_contacts")

    def __init__(self, html: str):
        self.html = html or ""
        self.head = self.html[:self.JSON_LIMIT]
        self._blobs = None
        self._contacts = None

    def blobs(self) -> list:
        """Встроенные данные страницы (state-JSON, ld+json), уже разобранные."""
        if self._blobs is None:
            self._blobs = _blobs_in(self.head)
        return self._blobs

    def contacts(self) -> str:
        """Секция «Контакты» самой организации или пустая строка."""
        if self._contacts is None:
            self._contacts = own_contacts_html(self.html)
        return self._contacts


def view_of(html, view=None) -> "PageView":
    """Готовая PageView или новая — чтобы вызов с одной страницей не менялся."""
    return view if view is not None else PageView(html)


def _blobs_in(text: str) -> list:
    """Разобрать встроенные данные из куска HTML — в порядке появления."""
    objs = []
    if not text:
        return objs
    decoder = json.JSONDecoder()
    for m in _JSON_BLOB_RE.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text, m.start(1))
        except (ValueError, json.JSONDecodeError):
            continue
        objs.append(obj)
    return objs


def _collect_url_strings(obj, depth: int = 0, limit: int = 200) -> list[str]:
    """Recursively collect string values that look like URLs from a decoded object.

    Ветки чужих организаций (competitor и подборки) пропускаются: ссылки оттуда
    никогда не являются контактами этой карточки.
    """
    out: list[str] = []

    def walk(o, d: int) -> None:
        if len(out) >= limit or d > 8:
            return
        if isinstance(o, str):
            if "http" in o:  # fast pre-check, avoids regex on non-URL strings
                out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if _is_foreign_key(k):
                    continue
                walk(v, d + 1)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v, d + 1)

    walk(obj, depth)
    return out


def _extract_from_json_blob(html: str = "", view=None) -> dict[str, str]:
    r"""Parse embedded JSON blobs in a Yandex Maps page and extract socials.

    Uses JSONDecoder.raw_decode so deeply nested objects are parsed correctly
    and escaped URLs like "https:\/\/vk.com\/club1" come back unescaped.
    Limits parsing to the first 200KB to avoid slow parsing of huge pages.
    """
    result: dict[str, str] = {}
    # Only the first 200KB, and only once per page — social links are always
    # near the top (см. PageView: тот же предел делят все шаги разбора).
    for obj in view_of(html, view).blobs():
        for url in _collect_url_strings(obj):
            url = _clean_social_url(url)
            if not url or EXCLUDE_URLS.search(url):
                continue
            for platform, pat in SOCIAL_DOMAINS.items():
                if platform not in result and pat.search(url):
                    normalized = _normalize_social_url(platform, url)
                    if normalized:
                        result[platform] = normalized
                    break
        if len(result) >= 3:
            break
    return result


_RATING_KEYS = ("ratingvalue", "rating", "score", "votesscore")
_REVIEWS_KEYS = ("reviewscount", "reviewscountvalue", "reviewcount", "reviews")


def _num(value):
    """Coerce a JSON value to float/int, or None when it is not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    return None


def _find_numbers(obj, keys, depth: int = 0):
    """Depth-first search for the first numeric value under any of `keys`.

    Yandex embeds the business card as a JSON blob whose exact nesting differs
    between page builds, so we look up by key name instead of by path.
    """
    if depth > 10 or obj is None:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _is_foreign_key(key):
                continue          # рейтинг похожей/соседней организации — чужой
            if str(key).lower() in keys:
                num = _num(value)
                if num is not None:
                    return num
                # `"rating": {"value": 4.5}` and `"reviews": {"count": 7}`
                if isinstance(value, dict):
                    for sub in ("value", "count", "countValue", "ratingValue"):
                        num = _num(value.get(sub))
                        if num is not None:
                            return num
        for key, value in obj.items():
            if _is_foreign_key(key):
                continue
            num = _find_numbers(value, keys, depth + 1)
            if num is not None:
                return num
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            num = _find_numbers(value, keys, depth + 1)
            if num is not None:
                return num
    return None


def extract_rating_reviews(html: str, view=None) -> tuple[object, object]:
    """Pull (rating, reviews_count) out of a Yandex Maps page, or ("", "").

    Reads the same embedded JSON blob that socials come from, so it costs no
    extra request. Returns empty strings when the page has no such data —
    callers must not turn that into 0.0/0.
    """
    if not html:
        return "", ""
    rating = reviews = None
    for obj in view_of(html, view).blobs():
        if rating is None:
            rating = _find_numbers(obj, _RATING_KEYS)
        if reviews is None:
            reviews = _find_numbers(obj, _REVIEWS_KEYS)
        if rating is not None and reviews is not None:
            break
    # Ratings arrive on a 5-point scale, but some page builds embed a ×10
    # value (4.7 → 47). Normalize those (same rule as lead_score.compute_score)
    # instead of dropping them; anything else is not a rating (a vote count,
    # a year…) and is discarded rather than guessed.
    if rating is not None:
        if 5 < rating <= 50:
            rating = rating / 10
        if not 0 <= rating <= 5:
            rating = None
    rating_out = round(rating, 1) if rating else ""
    reviews_out = int(reviews) if reviews else ""
    return rating_out, reviews_out


def extract_socials(text: str, view=None) -> dict[str, str]:
    """Extract real social-profile links (URLs only — no fabrication from
    phone numbers or @mentions in arbitrary text).

    На странице карточки разбор ограничивается секцией «Контакты»: ссылки из
    блока «похожие организации» (и вообще всё, что лежит в state-JSON чужих
    карточек) в запись не попадают. На обычном тексте/JSON поведение прежнее.
    """
    text = (view.contacts() if view is not None else own_contacts_html(text)) or text
    result: dict[str, str] = {}
    for url in _HTTP_LIKE.findall(text):
        url = _clean_social_url(url)
        if not url or EXCLUDE_URLS.search(url):
            continue
        for platform, pat in SOCIAL_DOMAINS.items():
            if platform not in result and pat.search(url):
                normalized = _normalize_social_url(platform, url)
                if normalized:
                    result[platform] = normalized
                break
    return result


# ── Телефон из карточки ──────────────────────────────────
# Used as a fallback when the source did not hand out a phone in its API
# response (мешает только ручной разбор контактов); карточка организации
# в Яндекс.Картах отдаёт контакты в том же JSON внутри страницы.
# does not always include Phones). Card pages render the contact phone as a
# `tel:` link, so that link is by far the most reliable signal.
_TEL_LINK_RE = re.compile(r'href=["\']tel:([+\d\s()\-]{7,25})["\']', re.I)
# Номер, как его рендерит блок контактов самой организации
# (<span dir="ltr" itemprop="telephone">+7 (913) 714-24-24</span>).
_TEL_ITEMPROP_RE = re.compile(r'itemprop=["\']telephone["\'][^>]*>([^<]{7,25})<', re.I)
# Scripts/styles are cut out before the loose text pass: otherwise any
# 11-digit number in the page state (a view counter, an id) reads as a phone.
_SCRIPT_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_PHONE_TEXT_RE = re.compile(
    r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
)


def _phone_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _format_phone(digits: str) -> str:
    """10/11 digits → «+7 XXX XXX-XX-XX»; anything else is not a phone.

    8-800-X… hotlines («+7 800 …») are rejected: they are support lines of
    the platform or of a franchise head office, never the number to call the
    owner about a website.
    """
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78":
        return ""
    digits = "7" + digits[1:]
    if digits[1:4] == "800":
        return ""
    return f"+{digits[0]} {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:]}"


# Keys under which embedded page data carries a phone number.
_PHONE_KEYS = ("phone", "phonenumber", "phone_number", "telephone", "contactphone")


def _phone_from_json(value, depth: int = 0) -> str:
    """First phone-shaped value stored under a phone-ish key in embedded data.

    Yandex ships the business card as JSON inside the page; a
    phone that the UI hides behind «Показать телефон» is usually already in
    that data. Only explicitly phone-named keys count — this never scrapes a
    random number out of unrelated state.
    """
    if depth > 12 or value is None:
        return ""
    if isinstance(value, dict):
        for key, sub in value.items():
            if _is_foreign_key(key):
                continue          # телефон «похожей» организации — чужой
            if str(key).lower() not in _PHONE_KEYS:
                continue
            cand = sub
            if isinstance(cand, dict):
                cand = cand.get("value") or cand.get("text") or cand.get("number") or ""
            if isinstance(cand, (list, tuple)):
                cand = next((x for x in cand if isinstance(x, str)), "")
            if isinstance(cand, (int, float)):
                cand = str(cand)
            if isinstance(cand, str):
                phone = _format_phone(_phone_digits(cand))
                if phone:
                    return phone
        for key, sub in value.items():
            if _is_foreign_key(key):
                continue
            phone = _phone_from_json(sub, depth + 1)
            if phone:
                return phone
    elif isinstance(value, (list, tuple)):
        for sub in value:
            phone = _phone_from_json(sub, depth + 1)
            if phone:
                return phone
    return ""


# ── Сайт организации ─────────────────────────────────────────
# Раньше сайт приходил из API организации вместе с выдачей. Браузерная
# выдача его не показывает, поэтому сайт читается с карточки организации:
# ссылка в блоке контактов («Сайт») или поле url/site/website в данных
# страницы. Так фильтр «только без сайтов» продолжает работать.
#
# Ссылка «Сайт» ищется по ВСЕМУ HTML карточки, а не по усечённому началу
# страницы: замер по 168 закэшированным карточкам — каждая ~900 КБ, кнопка
# «Сайт» живёт в шапке собственной карточки на отметке ~670 КБ, а head
# ограничен 200 КБ. По старой схеме сайт не находился НИ РАЗУ на всех 168
# карточках, хотя в HTML он был у трёх из них. Секция «Контакты» не
# подходит: она начинается ПОСЛЕ кнопки «Сайт». У экстракции телефона
# секция «Контакты» остаётся — у неё свой контракт (см. extract_phone).
_WEBSITE_KEYS = ("url", "site", "website", "siteurl", "domain")
_WEBSITE_LINK_RE = re.compile(
    r'href=["\'](https?://[^"\']+)["\'][^>]*>\s*(?:<[^>]+>)*[^<]{0,40}?Сайт',
    re.I,
)


def _is_own_website(url: str) -> bool:
    """True для сайта самой организации (не соцсеть, не агрегатор, не Яндекс)."""
    if not url or not url.lower().startswith("http"):
        return False
    low = url.lower()
    if EXCLUDE_URLS.search(low) or _is_aggregator(low):
        return False
    for pat in SOCIAL_DOMAINS.values():
        if pat.search(low):
            return False
    return True


def _site_link_in_page(html: str, view, accept) -> str:
    """Первая ссылка «Сайт» на странице карточки, проходящая фильтр ``accept``.

    Ссылка лежит в кнопочной строке СОБСТВЕННОЙ карточки (~670 КБ от начала
    страницы — замер по 168 закэшированным карточкам), далеко за прежним
    пределом 200 КБ, поэтому сканируется весь HTML. На каждой карточке такая
    ссылка ровно одна и принадлежит этой организации: кнопку «Сайт» чужие
    карточки («похожие организации») не разворачивают. Секция «Контакты»
    при этом НЕ используется: она начинается ПОСЛЕ кнопочной строки, и
    ограничивать ею — не находить ссылку вовсе (так и было на всех 168
    карточках). Всё, что не проходит accept (соцсети, Яндекс, агрегаторы
    вместо сайта), отбрасывается как раньше.
    """
    v = view_of(html, view)
    text = v.html or v.head
    for m in _WEBSITE_LINK_RE.finditer(text):
        cand = m.group(1).strip()
        if accept(cand):
            return _clean_social_url(cand)
    return ""


def _site_key_from_json(value, accept, depth: int = 0) -> str:
    """Первый URL под ключом url/site/website в данных страницы, проходящий accept."""
    if depth > 12 or value is None:
        return ""
    if isinstance(value, dict):
        for key, sub in value.items():
            if _is_foreign_key(key):
                continue
            if str(key).lower() not in _WEBSITE_KEYS:
                continue
            cand = sub
            if isinstance(cand, dict):
                cand = cand.get("value") or cand.get("text") or cand.get("url") or ""
            if isinstance(cand, (list, tuple)):
                cand = next((x for x in cand if isinstance(x, str)), "")
            if isinstance(cand, str) and accept(cand.strip()):
                return _clean_social_url(cand.strip())
        for key, sub in value.items():
            if _is_foreign_key(key):
                continue
            found = _site_key_from_json(sub, accept, depth + 1)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for sub in value:
            found = _site_key_from_json(sub, accept, depth + 1)
            if found:
                return found
    return ""


def extract_website(html: str, view=None) -> str:
    """Сайт организации со страницы карточки — или "" (если сайта нет)."""
    if not html:
        return ""
    # 1. Блок контактов: ссылка рядом со словом «Сайт» — самый надёжный сигнал.
    found = _site_link_in_page(html, view, _is_own_website)
    if found:
        return found

    # 2. Данные страницы: url/site/website с настоящим адресом организации.
    for obj in view_of(html, view).blobs():
        found = _site_key_from_json(obj, _is_own_website)
        if found:
            return found
    return ""


def extract_aggregator(html: str, view=None) -> str:
    """Ссылка-витрина (taplink/linktree) из карточки — или "".

    Яндекс показывает такую ссылку как «Сайт» организации, но сайтом она не
    считается (см. _is_own_website / LINK_AGGREGATORS): раньше карточка её не
    читала вовсе, и колонка «Сайт / Таплинк» оставалась пустой, даже когда
    витрина была. Порядок тот же, что у extract_website: секция «Контакты»
    целиком → данные страницы.
    """
    if not html:
        return ""
    found = _site_link_in_page(html, view, _is_aggregator)
    if found:
        return found
    for obj in view_of(html, view).blobs():
        found = _site_key_from_json(obj, _is_aggregator)
        if found:
            return found
    return ""


def extract_phone(html: str, view=None) -> str:
    """Первый настоящий телефон со страницы карточки — или "".

    Порядок по надёжности: itemprop="telephone" в секции «Контакты» самой
    организации → ссылка tel: → телефон в данных страницы под ключом
    phone/tel → телефон в тексте. Служебные 8-800 и короткие номера
    отбраковываются.

    На карточке разбор ограничивается секцией «Контакты»: телефоны из блока
    «похожие организации» чужие, а секция лежит глубже 200 КБ — прежнему
    усечению их не хватало, и номер с карточки не находился вовсе.
    """
    if not html:
        return ""
    section = view.contacts() if view is not None else own_contacts_html(html)
    text = section if section else (view.head if view is not None else html[:200_000])
    for m in _TEL_ITEMPROP_RE.finditer(text):
        phone = _format_phone(_phone_digits(m.group(1)))
        if phone:
            return phone
    for m in _TEL_LINK_RE.finditer(text):
        phone = _format_phone(_phone_digits(m.group(1)))
        if phone:
            return phone
    # Данные страницы: в секции контактов своего JSON нет (она кончается на
    # `<script`), поэтому берётся либо своя секция, либо начало страницы —
    # ровно как раньше, только разобранное один раз.
    for obj in (_blobs_in(section) if section else view_of(html, view).blobs()):
        phone = _phone_from_json(obj)
        if phone:
            return phone
    for m in _PHONE_TEXT_RE.finditer(_SCRIPT_BLOCK_RE.sub(" ", text)):
        phone = _format_phone(_phone_digits(m.group(0)))
        if phone:
            return phone
    return ""


# ── Всё, что нужно от страницы, за один разбор ─────────────────

def extract_page(html: str, *, socials: bool = True, rating: bool = True,
                 phone: bool = True, website: bool = True,
                 aggregator: bool = True) -> dict:
    """Собрать с карточки всё сразу, разобрав страницу ОДИН раз.

    Тот же результат, что у пяти отдельных вызовов, но встроенные данные и
    секция контактов разбираются однажды: замер на карточках из кэша — 15.7 мс
    на страницу против 5–6 мс. На прогоне в тысячи организаций это минуты
    процессорного времени сборщика (и столько же ожидания в рабочем потоке).

    Возвращает словарь с ключами:

    * ``socials_json`` — соцсети из встроенных данных страницы;
    * ``socials_contacts`` — соцсети из секции «Контакты» самой организации;
    * ``rating``, ``reviews`` — оценка и число отзывов;
    * ``phone`` — телефон, ``website`` — сайт организации;
    * ``aggregator`` — ссылка-витрина (taplink/linktree), та же колонка
      отчёта «Сайт / Таплинк», но поле отдельное — сайт она не заменяет.

    Соцсети отдаются ДВУМЯ словарями, а не одним: у вызывающего уже есть
    соцсети из выдачи поиска, и порядок приоритета (выдача → встроенные
    данные → секция контактов) задаётся им, а не разбором. Пустая строка
    значит «данных нет» — вызывающий не должен делать из неё ноль.
    """
    view = PageView(html)
    out: dict = {"socials_json": {}, "socials_contacts": {},
                 "rating": "", "reviews": "", "phone": "", "website": "",
                 "aggregator": ""}
    if not html:
        return out
    if socials:
        out["socials_json"] = _extract_from_json_blob(view=view)
        out["socials_contacts"] = extract_socials(html, view=view)
    if rating:
        out["rating"], out["reviews"] = extract_rating_reviews(html, view=view)
    if phone:
        out["phone"] = extract_phone(html, view=view)
    if website:
        out["website"] = extract_website(html, view=view)
    if aggregator:
        out["aggregator"] = extract_aggregator(html, view=view)
    return out


