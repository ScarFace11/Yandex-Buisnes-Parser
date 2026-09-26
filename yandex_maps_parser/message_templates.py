"""Шаблоны сообщений для ВК/TG/WA/IG («📝 Шаблоны»).

Хранятся в settings.json (общие для команды), а не в localStorage: цель —
единый tone of voice. Правила подстановки описаны здесь один раз и
переиспользуются сервером (рассылка VK и /bulk/urls); в app.js живёт
зеркало для клика по таблице и превью — держать их надо синхронно.

Схема хранения::

    "message_templates": {
        "version": 1,
        "updated_at": "2026-09-26T12:00:00+00:00",
        "active_template_ids": {"vk": "tpl_vk_intro", "telegram": null, ...},
        "show_missing_as_var": false,
        "templates": [{id, category, name, text, is_default, created_at}],
    }
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

try:  # в тестах модуль импортируется без Flask и без paths
    import paths as _paths
except Exception:  # pragma: no cover
    _paths = None

TEMPLATES_KEY = "message_templates"
CURRENT_TEMPLATE_VERSION = 1
MAX_TEXT = 4096
MAX_NAME = 120
MAX_TEMPLATES = 200

CATEGORIES = ("vk", "telegram", "whatsapp", "instagram")
CATEGORY_LABELS = {
    "vk": "ВКонтакте",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
}

SOCIAL_KEYS = ("vk", "telegram", "whatsapp", "instagram")
SOCIAL_LABELS = {"vk": "VK", "telegram": "TG", "whatsapp": "WA", "instagram": "IG"}

# Реестр переменных: ключ → (подпись для UI, поле записи).
# `socials` собирается отдельно (пустое поле — маркер).
VARIABLES = (
    ("name", "название компании", "name"),
    ("city", "город", "city"),
    ("category", "категория", "category"),
    ("rating", "рейтинг", "rating"),
    ("reviews", "количество отзывов", "reviews_count"),
    ("address", "адрес", "address"),
    ("phone", "телефон", "phone"),
    ("lead_score", "оценка лида", "lead_score"),
    ("website", "сайт", "website"),
    ("socials", "список соцсетей", ""),
)

# Алиасы: старые и альтернативные имена переменных.
# `название_бизнеса` — синтаксис прежней «Отправить в VK», его поддерживаем.
VARIABLE_ALIASES = {
    "название_бизнеса": "name",
    "reviews_count": "reviews",
}

_VAR_FIELD = {key: field for key, _label, field in VARIABLES}

# Пять стандартных шаблонов — сеются при первом запуске и возвращаются
# кнопкой «Сброс к стандартным».
DEFAULT_TEMPLATES = [
    {
        "id": "tpl_vk_intro",
        "category": "vk",
        "name": "Первое знакомство",
        "text": "Здравствуйте! Увидел, что у вас {category} в {city}. "
                "У меня есть 2-3 примера сайтов для такой ниши. Показать?",
        "is_default": True,
    },
    {
        "id": "tpl_vk_benefit",
        "category": "vk",
        "name": "С акцентом на выгоду",
        "text": "{name}, добрый день! Заметил, у вас нет сайта, но есть активный профиль. "
                "Хотите, покажу, как сайт увеличит заявки?",
        "is_default": True,
    },
    {
        "id": "tpl_vk_compliment",
        "category": "vk",
        "name": "С комплиментом",
        "text": "{name}, добрый день! Вижу рейтинг {rating} и {reviews} отзывов — "
                "серьёзный результат. Помогу сделать так, чтобы клиенты находили вас и в поиске.",
        "is_default": True,
    },
    {
        "id": "tpl_tg_short",
        "category": "telegram",
        "name": "Короткое",
        "text": "Здравствуйте! {name} — {category}. "
                "Есть пара идей, как привлечь больше клиентов. Рассказать?",
        "is_default": True,
    },
    {
        "id": "tpl_wa_official",
        "category": "whatsapp",
        "name": "Официальное",
        "text": "Здравствуйте! Компания «{name}», {category}, {city}. "
                "Предлагаем размещение и продвижение. Ответить вам с деталями?",
        "is_default": True,
    },
]

_VAR_RE = re.compile(r"\{(\w+)\}")

# Зарезервировано под будущие шаги: {1: функция_миграции_с_1_на_2}.
_MIGRATIONS: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_templates(raw) -> list:
    """Привести список шаблонов к безопасному виду.

    Мусор и пустые имя/текст отбрасываются, id уникализируется, категория
    вне набора → «vk», имя и текст обрезаются по лимитам. Список — не список
    (None, строка, мусор) → пустой список.
    """
    if not isinstance(raw, list):
        return []
    out: list = []
    seen: set = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:MAX_NAME]
        text = str(item.get("text") or "").strip()[:MAX_TEXT]
        if not name or not text:
            continue
        tid = str(item.get("id") or "").strip()
        if not tid or tid in seen:
            n = i + 1
            tid = f"tpl_{n}"
            while tid in seen:
                n += 1
                tid = f"tpl_{n}"
        seen.add(tid)
        cat = str(item.get("category") or "").strip().lower()
        if cat not in CATEGORIES:
            cat = "vk"
        created = str(item.get("created_at") or "").strip() or _now()
        out.append({
            "id": tid,
            "category": cat,
            "name": name,
            "text": text,
            "is_default": bool(item.get("is_default")),
            "created_at": created,
        })
        if len(out) >= MAX_TEMPLATES:
            break
    return out


def normalize_active_ids(raw, templates) -> dict:
    """Активный шаблон по каждой категории: только существующие id, иначе None."""
    ids = {t["id"] for t in templates}
    src = raw if isinstance(raw, dict) else {}
    out = {}
    for cat in CATEGORIES:
        val = src.get(cat)
        val = str(val).strip() if val is not None else ""
        out[cat] = val if val in ids else None
    return out


def migrate_templates(raw) -> tuple:
    """Привести хранилище к текущей версии. Возвращает (данные, предупреждения).

    Файл из более новой сборки не разрушаем: сохраняем как есть, только
    предупреждаем. Битый/отсутствующий version трактуем как 1.
    """
    warnings: list = []
    if not isinstance(raw, dict):
        raw = {}
    version = raw.get("version")
    if not isinstance(version, int):
        version = CURRENT_TEMPLATE_VERSION
    if version > CURRENT_TEMPLATE_VERSION:
        warnings.append(
            f"Файл шаблонов новее этой сборки (version={version}); "
            "данные сохранены без изменений."
        )
    elif version < 1:
        version = 1
    else:
        for v in range(version, CURRENT_TEMPLATE_VERSION):
            fn = _MIGRATIONS.get(v)
            if fn:
                raw = fn(raw)
    return raw, warnings


def normalize_state(raw) -> tuple:
    """(state, warnings) — полное состояние шаблонов из произвольного словаря."""
    migrated, warnings = migrate_templates(raw)
    templates = normalize_templates(migrated.get("templates"))
    state = {
        "version": CURRENT_TEMPLATE_VERSION,
        "updated_at": str(migrated.get("updated_at") or "").strip() or _now(),
        "active_template_ids": normalize_active_ids(
            migrated.get("active_template_ids"), templates),
        "show_missing_as_var": bool(migrated.get("show_missing_as_var", False)),
        "templates": templates,
    }
    return state, warnings


def default_state() -> dict:
    """Стандартные пресеты, без выбранных активных шаблонов (берётся первый)."""
    return {
        "version": CURRENT_TEMPLATE_VERSION,
        "updated_at": _now(),
        "active_template_ids": {cat: None for cat in CATEGORIES},
        "show_missing_as_var": False,
        "templates": normalize_templates(DEFAULT_TEMPLATES),
    }


def load_templates() -> dict:
    """Состояние из settings.json; ключа нет — сеем пресеты и сохраняем."""
    raw = None
    if _paths is not None:
        raw = _paths.load_settings().get(TEMPLATES_KEY)
    if not isinstance(raw, dict):
        return save_templates(default_state())
    state, _warnings = normalize_state(raw)
    return state


def save_templates(state: dict) -> dict:
    """Сохранить состояние (с нормализацией и свежими version/updated_at)."""
    clean, _warnings = normalize_state(state)
    clean["version"] = CURRENT_TEMPLATE_VERSION
    clean["updated_at"] = _now()
    if _paths is not None:
        _paths.save_settings({TEMPLATES_KEY: clean})
    return clean


def _socials_text(record: dict) -> str:
    names = [
        SOCIAL_LABELS[key]
        for key in SOCIAL_KEYS
        if str((record or {}).get(key) or "").strip()
    ]
    return ", ".join(names)


def substitute(text: str, record: dict, show_missing_as_var: bool = False) -> str:
    """Подставить {переменные} значениями записи.

    Известная, но пустая переменная → «—» (или остаётся {var} при
    show_missing_as_var). Неизвестная переменная остаётся как есть — так её
    видно и можно поправить шаблон.
    """
    record = record or {}

    def repl(match: re.Match) -> str:
        key = match.group(1)
        canonical = VARIABLE_ALIASES.get(key, key)
        if canonical not in _VAR_FIELD:
            return match.group(0)
        if canonical == "socials":
            value = _socials_text(record)
        else:
            value = record.get(_VAR_FIELD[canonical])
        if value is None or str(value).strip() == "":
            return match.group(0) if show_missing_as_var else "—"
        return str(value)

    return _VAR_RE.sub(repl, str(text or ""))
