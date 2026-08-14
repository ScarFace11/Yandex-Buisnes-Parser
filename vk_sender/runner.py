"""
Основной цикл рассылки.

run_send(params, log_fn, stop_event) — точка входа для Flask-интерфейса.

params (dict):
    social       str   — соцсеть для рассылки (пока только "vk")
    excel_file   str   — имя файла в output/ (без пути)
    access_token str   — VK user access_token
    message_tpl  str   — шаблон сообщения с {название_бизнеса}
    limit        int   — 0 = все, иначе N записей
    delay_min    float — мин. пауза между отправками (сек)
    delay_max    float — макс. пауза
    retry_count  int   — попыток при сетевой ошибке
    retry_delay  float — базовая задержка между попытками
    output_dir   str   — папка с Excel-файлами (по умолчанию "output")
"""
import os
import random
import threading
import time
import logging
from typing import Callable, Optional

from .vk_adapter import VKAdapter
from . import excel_manager as xm

logger = logging.getLogger(__name__)


def _make_log(log_fn: Callable, prefix: str = ""):
    """Возвращает удобные функции логирования."""
    def info(msg):  log_fn("info",  f"{prefix}{msg}")
    def ok(msg):    log_fn("ok",    f"{prefix}{msg}")
    def warn(msg):  log_fn("warn",  f"{prefix}{msg}")
    return info, ok, warn


def run_send(
    params: dict,
    log_fn: Callable[[str, str], None],
    stop_event: threading.Event,
) -> dict:
    """
    Основной цикл рассылки.

    log_fn(level, msg) — колбэк для логирования (уровни: info, ok, warn)
    stop_event         — Event для запроса остановки

    Возвращает dict со статистикой:
        sent, skipped, errors, stopped
    """
    info, ok, warn = _make_log(log_fn, "  ")

    social       = params.get("social", "vk").lower()
    excel_file   = params.get("excel_file", "")
    access_token = params.get("access_token", "").strip()
    message_tpl  = params.get("message_tpl", "").strip()
    limit        = int(params.get("limit", 0))
    delay_min    = float(params.get("delay_min", 1.5))
    delay_max    = float(params.get("delay_max", 3.0))
    retry_count  = int(params.get("retry_count", 3))
    retry_delay  = float(params.get("retry_delay", 5.0))
    output_dir   = params.get("output_dir", "output")

    stats = {"sent": 0, "skipped": 0, "errors": 0, "stopped": False}

    # ── Валидация параметров ───────────────────────────────────

    if not excel_file:
        warn("Excel-файл не выбран. Прерываем.")
        return stats

    excel_path = os.path.join(output_dir, excel_file)
    if not os.path.isfile(excel_path):
        warn(f"Файл не найден: {excel_path}")
        return stats

    if social != "vk":
        warn(f"Соцсеть «{social}» пока не поддерживается. Выберите vk.")
        return stats

    if not access_token:
        warn("VK access_token не задан. Прерываем.")
        return stats

    if not message_tpl:
        warn("Шаблон сообщения пустой. Прерываем.")
        return stats

    # ── Инициализация адаптера ────────────────────────────────

    try:
        adapter = VKAdapter(
            access_token=access_token,
            retry_count=retry_count,
            retry_delay=retry_delay,
        )
    except ValueError as exc:
        warn(f"Ошибка конфигурации VK: {exc}")
        return stats

    info(f"Файл: {excel_file}")
    info(f"Лимит: {'все записи' if not limit else f'до {limit} отправленных'}")
    info(f"Задержка: {delay_min}–{delay_max} сек")
    info("─" * 50)

    # ── Итерация по получателям ───────────────────────────────
    # Лимит применяется ПОСЛЕ проверок сайта и истории, чтобы N означало
    # N фактически отправленных сообщений, а не N прочитанных строк Excel.

    recipients = list(xm.iter_recipients(excel_path, social=social))

    if not recipients:
        info("Подходящих получателей не найдено (все уже отмечены или нет ссылок VK).")
        return stats

    info(f"Кандидатов из файла: {len(recipients)}")
    info("")

    for i, rec in enumerate(recipients, 1):
        if stop_event.is_set():
            stats["stopped"] = True
            warn("Остановлено пользователем.")
            break

        # Проверяем лимит отправленных ДО обработки новой записи
        if limit and stats["sent"] >= limit:
            info(f"Достигнут лимит {limit} отправленных сообщений. Завершаем.")
            break

        name    = rec["name"]
        vk_url  = rec["vk_url"]
        row_num = rec["row_num"]

        info(f"[{i}/{len(recipients)}] {name}")
        info(f"  ↳ {vk_url}")

        # 1. Получить peer_id
        try:
            peer_id = adapter.build_peer_id(vk_url)
        except Exception as exc:
            warn(f"  ✗ Ошибка получения ID группы: {exc}")
            stats["errors"] += 1
            continue

        if not peer_id:
            warn("  ⊘ Пропуск: не удалось получить ID группы (не VK-ссылка?)")
            stats["skipped"] += 1
            xm.mark_sent(excel_path, row_num, "⊘ не VK")
            continue

        # 2. Проверить: есть ли у бизнеса собственный сайт?
        try:
            has_site = adapter.has_own_website(vk_url)
        except Exception as exc:
            warn(f"  ! Не удалось проверить сайт, продолжаем: {exc}")
            has_site = False

        if has_site:
            info("  ⊘ Пропуск: у бизнеса уже есть собственный сайт.")
            stats["skipped"] += 1
            xm.mark_sent(excel_path, row_num, "⊘ есть сайт")
            continue

        # 3. Проверить историю переписки
        # Если проверить не удалось — пропускаем (fail-safe), чтобы не отправить дубль.
        try:
            messaged = adapter.already_messaged(peer_id)
        except Exception as exc:
            warn(f"  ⊘ Пропуск: не удалось проверить историю переписки ({exc}).")
            stats["skipped"] += 1
            continue

        if messaged:
            info("  ⊘ Пропуск: сообщение уже было отправлено ранее.")
            stats["skipped"] += 1
            xm.mark_sent(excel_path, row_num, "+")
            continue

        # 4. Отправить сообщение
        text = message_tpl.replace("{название_бизнеса}", name)

        try:
            adapter.send_message(peer_id, text)
            ok(f"  ✓ Отправлено!")
            stats["sent"] += 1
            xm.mark_sent(excel_path, row_num, "+")
        except PermissionError as exc:
            warn(f"  ⊘ Пропуск: {exc}")
            stats["skipped"] += 1
            xm.mark_sent(excel_path, row_num, "⊘ закрыты")
        except RuntimeError as exc:
            warn(f"  ✗ Ошибка отправки: {exc}")
            stats["errors"] += 1

        # 5. Пауза между отправками
        if i < len(recipients) and not stop_event.is_set():
            delay = random.uniform(delay_min, delay_max)
            time.sleep(delay)

    info("")
    info("─" * 50)
    info(
        f"Итого — Отправлено: {stats['sent']}  "
        f"Пропущено: {stats['skipped']}  "
        f"Ошибок: {stats['errors']}"
    )

    return stats
