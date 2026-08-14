"""
Адаптер ВКонтакте.

Использует прямые HTTP-запросы к VK API (v5.131).
Поддерживает:
  - Получение информации о сообществе (сайт, ID)
  - Проверку истории переписки
  - Отправку сообщения сообществу от имени пользователя
"""
import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from .base_adapter import BaseSocialAdapter

logger = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"
VK_VERSION = "5.131"

# Домены, которые считаются «соцсетью» (не собственным сайтом)
_SOCIAL_HOSTS: set[str] = {
    "vk.com", "vkontakte.ru",
    "instagram.com", "instagr.am",
    "facebook.com", "fb.com", "fb.me",
    "t.me", "telegram.me", "telegram.org",
    "youtube.com", "youtu.be",
    "tiktok.com",
    "ok.ru", "odnoklassniki.ru",
    "twitter.com", "x.com",
    "whatsapp.com", "wa.me",
    "taplink.cc", "linktr.ee", "linktree.com",
    "bio.link", "beacons.ai", "solo.to", "lnk.bio",
    "campsite.bio", "carrd.co", "milkshake.app",
}

# Паттерн для извлечения screen_name из URL ВК
_VK_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?vk\.com/(?P<screen>[a-zA-Z0-9._\-]+)",
    re.I,
)


def _strip_www(host: str) -> str:
    return host.lstrip("www.").lstrip("m.")


def _is_social_or_aggregator(url: str) -> bool:
    """True если url ведёт на соцсеть/агрегатор ссылок (или пустой)."""
    if not url or not url.strip():
        return True
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
        host = _strip_www(parsed.netloc.lower())
        return any(host == d or host.endswith("." + d) for d in _SOCIAL_HOSTS)
    except Exception:
        return True


class VKAdapter(BaseSocialAdapter):
    """
    Адаптер для ВКонтакте.

    :param access_token: user access_token с правами messages, offline
    :param retry_count:  количество повторных попыток при ошибке
    :param retry_delay:  базовая задержка между попытками (сек)
    :param session:      опционально — внешний requests.Session
    """

    def __init__(
        self,
        access_token: str,
        retry_count: int = 3,
        retry_delay: float = 5.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not access_token:
            raise ValueError("VK access_token обязателен")
        self.token = access_token
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self._session = session or requests.Session()

    # ── Низкоуровневый запрос к API ───────────────────────────

    def _call(self, method: str, **params) -> dict:
        """
        Выполнить запрос к VK API с автоматическим retry.
        Бросает RuntimeError при исчерпании попыток.
        """
        params.update({"access_token": self.token, "v": VK_VERSION})
        url = f"{VK_API}/{method}"

        for attempt in range(1, self.retry_count + 1):
            try:
                resp = self._session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    code = data["error"].get("error_code", 0)
                    msg  = data["error"].get("error_msg", "")
                    # Флуд-контроль
                    if code == 9:
                        wait = self.retry_delay * attempt
                        logger.warning("VK flood control, жду %.1f с…", wait)
                        time.sleep(wait)
                        continue
                    # Капча
                    if code == 14:
                        raise RuntimeError(f"VK требует капчу (14): {msg}")
                    # Сообщения закрыты
                    if code == 901:
                        raise PermissionError(f"Сообщество закрыло личные сообщения (901)")
                    raise RuntimeError(f"VK API ошибка {code}: {msg}")

                return data.get("response", {})

            except (requests.RequestException, ValueError) as exc:
                if attempt == self.retry_count:
                    raise RuntimeError(f"Ошибка запроса VK API ({method}): {exc}") from exc
                time.sleep(self.retry_delay * attempt)

        raise RuntimeError(f"Исчерпаны попытки для {method}")

    # ── Извлечение screen_name из URL ──────────────────────────

    @staticmethod
    def extract_screen_name(url: str) -> Optional[str]:
        """Вернуть screen_name из ссылки вида https://vk.com/screen_name."""
        if not url:
            return None
        m = _VK_URL_RE.search(url)
        if not m:
            return None
        sn = m.group("screen").lower()
        # Игнорируем технические страницы
        if sn in ("away.php", "feed", "notifications", "im", "video", "music", "market"):
            return None
        return sn

    # ── Получение group_id по screen_name ─────────────────────

    def _get_group_id(self, screen_name: str) -> Optional[int]:
        """Вернуть числовой ID группы или None если не найдена/не группа."""
        try:
            resp = self._call("groups.getById", group_id=screen_name, fields="site")
        except RuntimeError:
            return None
        groups = resp if isinstance(resp, list) else resp.get("groups", [])
        if not groups:
            return None
        return groups[0].get("id")

    # ── BaseSocialAdapter interface ────────────────────────────

    def resolve_peer(self, url: str) -> Optional[str]:
        """Вернуть screen_name или None."""
        return self.extract_screen_name(url)

    def has_own_website(self, url: str) -> bool:
        """
        True если у сообщества есть реальный внешний сайт.
        Проверяет поля: site, links (массив ссылок сообщества).
        Возвращает False (→ можно писать) если внешнего сайта нет.
        """
        screen_name = self.extract_screen_name(url)
        if not screen_name:
            return False  # нераспознанная ссылка — всё же пишем
        try:
            resp = self._call(
                "groups.getById",
                group_id=screen_name,
                fields="site,links,contacts",
            )
        except RuntimeError as exc:
            logger.warning("Не удалось получить инфо о группе %s: %s", screen_name, exc)
            return False

        groups = resp if isinstance(resp, list) else resp.get("groups", [])
        if not groups:
            return False

        group = groups[0]

        # 1. Поле «site» в профиле сообщества
        site = (group.get("site") or "").strip()
        if site and not _is_social_or_aggregator(site):
            return True

        # 2. Массив «links» — дополнительные ссылки сообщества
        for link_obj in (group.get("links") or []):
            link_url = (link_obj.get("url") or "").strip()
            if link_url and not _is_social_or_aggregator(link_url):
                return True

        return False

    def already_messaged(self, peer_id: str) -> bool:
        """
        True если в диалоге с сообществом уже есть наше исходящее сообщение.
        peer_id — строка вида «-12345» (отрицательный group_id).

        Пропагирует исключения наружу — вызывающий код должен перехватить их
        и применить fail-safe логику (пропустить запись без отправки).
        """
        resp = self._call(
            "messages.getHistory",
            peer_id=peer_id,
            count=20,
            rev=0,
        )
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return any(msg.get("out") == 1 for msg in items)

    def send_message(self, peer_id: str, text: str) -> bool:
        """
        Отправить сообщение сообществу.
        peer_id — строка вида «-12345».
        Вернуть True при успехе.
        """
        try:
            result = self._call(
                "messages.send",
                peer_id=peer_id,
                message=text,
                random_id=random.randint(1, 2**31),
            )
            return bool(result)
        except PermissionError:
            raise
        except RuntimeError:
            raise

    # ── Вспомогательный метод ─────────────────────────────────

    def build_peer_id(self, vk_url: str) -> Optional[str]:
        """
        По URL ВК-сообщества вернуть строку peer_id вида «-12345»
        (или None если URL нераспознан или не является группой).
        """
        screen_name = self.extract_screen_name(vk_url)
        if not screen_name:
            return None
        group_id = self._get_group_id(screen_name)
        if not group_id:
            return None
        return str(-group_id)
