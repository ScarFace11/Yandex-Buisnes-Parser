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
        "template_modes": {"vk": "single", "telegram": "random", ...},
        "random_template_ids": {"vk": ["tpl_1", "tpl_2"], ...},
        "avoid_repeats": false,
        "custom_variables": [{name, value, column, description, created_at}],
        "templates": [{id, category, name, text, is_default, created_at}],
    }

Пользовательские переменные: `value` — статичный текст (одинаковый во всех
сообщениях); вместо него можно задать `column` — тогда значение берётся из
поля записи (столбца таблицы результатов) для каждой компании своё.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

try:  # в тестах модуль импортируется без Flask и без paths
    import paths as _paths
except Exception:  # pragma: no cover
    _paths = None

TEMPLATES_KEY = "message_templates"
CURRENT_TEMPLATE_VERSION = 2
MAX_TEXT = 4096
MAX_NAME = 120
MAX_TEMPLATES = 200

# Пользовательские переменные («Переменные» во вкладке «📝 Шаблоны»).
MAX_VAR_NAME = 60
MAX_VAR_VALUE = 1000
MAX_VAR_DESC = 200
MAX_VAR_COLUMN = 60
MAX_CUSTOM_VARS = 100

CATEGORIES = ("vk", "telegram", "whatsapp", "instagram")
CATEGORY_LABELS = {
    "vk": "ВКонтакте",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "instagram": "Instagram",
}

# Режим выбора шаблона: один выбранный или случайный из набора.
PICK_MODES = ("single", "random")

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

# Встроенные имена заняты: свою переменную так назвать нельзя.
RESERVED_VAR_NAMES = frozenset(VARIABLE_ALIASES) | {key for key, _label, _f in VARIABLES}

# Имя пользовательской переменной: буквы/цифры/подчёркивание, кириллица —
# тот же алфавит, что у подстановки \{...\} в тексте шаблона.
_VAR_NAME_RE = re.compile(r"^[A-Za-z0-9_а-яА-ЯёЁ]+$")

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


# ── Пользовательские переменные ───────────────────────────────

def normalize_custom_variables(raw) -> list:
    """Привести список своих переменных к безопасному виду.

    Имя — непустое, по _VAR_NAME_RE, без коллизий со встроенными переменными
    и алиасами и без дублей (регистр не важен). Задан столбец — значение
    берётся из записи, статичный текст не нужен; без столбца нужен текст.
    Не-список и мусор отбрасываются, кап — MAX_CUSTOM_VARS.
    """
    if not isinstance(raw, list):
        return []
    out: list = []
    seen: set = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if (not name or len(name) > MAX_VAR_NAME
                or not _VAR_NAME_RE.match(name)
                or name in RESERVED_VAR_NAMES
                or name.lower() in seen):
            continue
        column = str(item.get("column") or "").strip()[:MAX_VAR_COLUMN]
        value = "" if column else str(item.get("value") or "").strip()[:MAX_VAR_VALUE]
        if not column and not value:
            continue
        seen.add(name.lower())
        out.append({
            "name": name,
            "column": column,
            "value": value,
            "description": str(item.get("description") or "").strip()[:MAX_VAR_DESC],
            "created_at": str(item.get("created_at") or "").strip() or _now(),
        })
        if len(out) >= MAX_CUSTOM_VARS:
            break
    return out


def _migrate_1_to_2(raw: dict) -> dict:
    """v1 → v2: появились свои переменные — у старых хранилищ их нет."""
    if not isinstance(raw.get("custom_variables"), list):
        raw["custom_variables"] = []
    return raw


_MIGRATIONS: dict = {1: _migrate_1_to_2}


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


def normalize_modes(raw) -> dict:
    """Режим выбора по категориям: только single/random, мусор → single."""
    src = raw if isinstance(raw, dict) else {}
    out = {}
    for cat in CATEGORIES:
        val = src.get(cat)
        out[cat] = val if val in PICK_MODES else "single"
    return out


def normalize_random_ids(raw, templates) -> dict:
    """Наборы для случайного выбора по категориям.

    Только существующие id СВОЕЙ категории (шаблон удалён или переехал в
    другую категорию — из набора выпадает автоматически), дедуп, порядок
    сохраняется, кап — MAX_TEMPLATES. Не-список → пустой набор.
    """
    by_cat = {cat: set() for cat in CATEGORIES}
    for t in templates:
        by_cat.setdefault(t["category"], set()).add(t["id"])
    src = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for cat in CATEGORIES:
        items = src.get(cat)
        seen: set = set()
        ids: list = []
        for item in items if isinstance(items, list) else []:
            tid = str(item or "").strip()
            if tid and tid not in seen and tid in by_cat.get(cat, set()):
                seen.add(tid)
                ids.append(tid)
                if len(ids) >= MAX_TEMPLATES:
                    break
        out[cat] = ids
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
        "template_modes": normalize_modes(migrated.get("template_modes")),
        "random_template_ids": normalize_random_ids(
            migrated.get("random_template_ids"), templates),
        "avoid_repeats": bool(migrated.get("avoid_repeats", False)),
        "custom_variables": normalize_custom_variables(
            migrated.get("custom_variables")),
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
        "template_modes": {cat: "single" for cat in CATEGORIES},
        "random_template_ids": {cat: [] for cat in CATEGORIES},
        "avoid_repeats": False,
        "custom_variables": [],
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


def substitute(text: str, record: dict, show_missing_as_var: bool = False,
               custom_variables=None) -> str:
    """Подставить {переменные} значениями записи.

    Свои переменные (custom_variables) приоритетнее встроенных: задан
    столбец — значение из записи, иначе статичный текст. Известная, но
    пустая переменная → «—» (или остаётся {var} при show_missing_as_var).
    Неизвестная переменная остаётся как есть — так её видно и можно
    поправить шаблон.
    """
    record = record or {}
    custom = {
        str(v.get("name")): v
        for v in (custom_variables or [])
        if isinstance(v, dict) and v.get("name")
    }

    def repl(match: re.Match) -> str:
        key = match.group(1)
        cv = custom.get(key)
        if cv is not None:
            if cv.get("column"):
                value = record.get(str(cv["column"]))
            else:
                value = cv.get("value")
            if value is None or str(value).strip() == "":
                return match.group(0) if show_missing_as_var else "—"
            return str(value)
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


# ── Случайный выбор шаблонов ──────────────────────────────────

def pick_random_text(texts: list, last_text: str | None = None, avoid_repeats: bool = False) -> str | None:
    """Случайный текст из набора; с avoid_repeats — не повторять последний.

    Исключение последнего опустошило набор (был один шаблон) — выбор из
    полного набора: один шаблон всегда даёт один и тот же текст, и это
    корректно. Пустой набор → None.
    """
    pool = [t for t in (texts or []) if isinstance(t, str) and t.strip()]
    if not pool:
        return None
    if avoid_repeats and len(pool) > 1 and last_text is not None:
        reduced = [t for t in pool if t != last_text]
        if reduced:
            pool = reduced
    return random.choice(pool)


def resolve_pick_state(social: str, state: dict) -> dict:
    """Данные выбора для категории: {(texts, names, mode, avoid)}.

    В random-режиме берутся тексты из набора random_template_ids; набор
    пуст — значит, случайный выбор не настроен (клиент решает, что делать:
    обычно fallback на активный шаблон).
    """
    state = state or {}
    modes = state.get("template_modes") if isinstance(state.get("template_modes"), dict) else {}
    mode = modes.get(social) if modes.get(social) in PICK_MODES else "single"
    by_id = {t["id"]: t for t in state.get("templates") or []}
    random_ids = state.get("random_template_ids") if isinstance(state.get("random_template_ids"), dict) else {}
    picked = [by_id[tid] for tid in (random_ids.get(social) or []) if tid in by_id]
    return {
        "texts": [t["text"] for t in picked],
        "names": [t["name"] for t in picked],
        "mode": mode,
        "avoid": bool(state.get("avoid_repeats", False)),
    }
