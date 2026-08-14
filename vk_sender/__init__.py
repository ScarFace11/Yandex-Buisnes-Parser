"""
VK Sender — модуль автоматической рассылки сообщений через ВКонтакте.

Public API:
    run_send(params, log_fn, stop_event) -> dict
"""
from .runner import run_send

__all__ = ["run_send"]
