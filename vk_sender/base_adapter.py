"""
Базовый абстрактный адаптер для отправки сообщений в соцсети.
Для добавления новой соцсети — унаследуйтесь и реализуйте все методы.
"""
from abc import ABC, abstractmethod
from typing import Optional


class BaseSocialAdapter(ABC):
    """Интерфейс адаптера соцсети."""

    @abstractmethod
    def resolve_peer(self, url: str) -> Optional[str]:
        """
        По URL страницы/сообщества вернуть внутренний идентификатор получателя
        (peer_id или screen_name), либо None если URL нераспознан.
        """

    @abstractmethod
    def has_own_website(self, url: str) -> bool:
        """
        Проверить, есть ли у сообщества собственный внешний сайт
        (не ссылка на другую соцсеть и не пусто).
        Если True — пропустить (бизнесу сайт уже не нужен).
        """

    @abstractmethod
    def already_messaged(self, peer_id: str) -> bool:
        """
        Проверить, было ли ранее отправлено наше сообщение этому получателю.
        """

    @abstractmethod
    def send_message(self, peer_id: str, text: str) -> bool:
        """
        Отправить сообщение. Вернуть True при успехе, False при ошибке.
        """
