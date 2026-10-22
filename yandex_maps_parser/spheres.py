# -*- coding: utf-8 -*-
"""Сферы бизнеса: готовые наборы запросов к Яндекс.Картам."""

# Каждый набор — слова, с которыми Яндекс.Карты находят организации этой сферы.
SPHERES: tuple[dict, ...] = (
    {"id": "cafe", "name": "Кафе и кофейни", "icon": "☕",
     "queries": ("кафе", "кофейня")},
    {"id": "restaurant", "name": "Рестораны", "icon": "🍽",
     "queries": ("ресторан",)},
    {"id": "bar", "name": "Бары и пабы", "icon": "🍺",
     "queries": ("бар", "паб")},
    {"id": "pizza", "name": "Пиццерии", "icon": "🍕",
     "queries": ("пиццерия", "пицца")},
    {"id": "sushi", "name": "Суши и роллы", "icon": "🍣",
     "queries": ("суши", "роллы")},
    {"id": "bakery", "name": "Пекарни", "icon": "🥖",
     "queries": ("пекарня", "хлеб")},
    {"id": "cake", "name": "Кондитерские", "icon": "🎂",
     "queries": ("кондитерская", "торты")},
    {"id": "hookah", "name": "Кальянные", "icon": "💨",
     "queries": ("кальянная",)},
    {"id": "delivery", "name": "Доставка еды", "icon": "🛵",
     "queries": ("доставка еды",)},
    {"id": "hair", "name": "Парикмахерские", "icon": "✂️",
     "queries": ("парикмахерская", "барбершоп")},
    {"id": "beauty", "name": "Салоны красоты", "icon": "💅",
     "queries": ("салон красоты", "маникюр", "ногтевая студия")},
    {"id": "massage", "name": "Массаж и спа", "icon": "💆",
     "queries": ("массаж", "спа")},
    {"id": "dental", "name": "Стоматология", "icon": "🦷",
     "queries": ("стоматология", "зубной врач")},
    {"id": "clinic", "name": "Медицинские центры", "icon": "🏥",
     "queries": ("медицинский центр", "клиника")},
    {"id": "auto", "name": "Автосервисы", "icon": "🔧",
     "queries": ("автосервис", "шиномонтаж")},
    {"id": "carwash", "name": "Автомойки", "icon": "🚿",
     "queries": ("автомойка",)},
    {"id": "fitness", "name": "Фитнес-клубы", "icon": "🏋️",
     "queries": ("фитнес", "тренажёрный зал")},
    {"id": "yoga", "name": "Йога и растяжка", "icon": "🧘",
     "queries": ("йога",)},
    {"id": "vet", "name": "Ветеринарные клиники", "icon": "🐾",
     "queries": ("ветклиника", "ветеринарная клиника")},
    {"id": "hotel", "name": "Гостиницы и отели", "icon": "🏨",
     "queries": ("гостиница", "отель", "хостел")},
    {"id": "flowers", "name": "Цветочные магазины", "icon": "💐",
     "queries": ("цветочный магазин", "цветы")},
    {"id": "furniture", "name": "Мебель", "icon": "🛋",
     "queries": ("мебель", "мебельный магазин")},
    {"id": "building", "name": "Стройматериалы", "icon": "🧱",
     "queries": ("стройматериалы",)},
    {"id": "renovation", "name": "Ремонт квартир", "icon": "🛠",
     "queries": ("ремонт квартир",)},
    {"id": "legal", "name": "Юридические услуги", "icon": "⚖️",
     "queries": ("юрист", "юридическая консультация")},
    {"id": "accounting", "name": "Бухгалтерские услуги", "icon": "📊",
     "queries": ("бухгалтерские услуги", "бухгалтер")},
    {"id": "estate", "name": "Недвижимость", "icon": "🏠",
     "queries": ("агентство недвижимости",)},
    {"id": "photo", "name": "Фотостудии", "icon": "📷",
     "queries": ("фотостудия", "фотограф")},
    {"id": "kids", "name": "Детские центры", "icon": "🧸",
     "queries": ("детский центр", "детский сад")},
    {"id": "tutors", "name": "Репетиторы", "icon": "📚",
     "queries": ("репетитор",)},
)


def _norm(text: str) -> str:
    """Запрос к виду для сравнения: регистр, «ё», лишние пробелы."""
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def catalog() -> list[dict]:
    """Сферы для интерфейса: копии со списками (JSON-сериализуемыми)."""
    return [
        {"id": s["id"], "name": s["name"], "icon": s["icon"],
         "queries": list(s["queries"])}
        for s in SPHERES
    ]


def sphere_for_queries(queries) -> dict | None:
    """Какая сфера описывает этот набор запросов (None — не наша сфера)."""
    wanted = {_norm(q) for q in (queries or []) if _norm(q)}
    if not wanted:
        return None
    best = None
    best_score = 0
    for sphere in SPHERES:
        score = len(wanted & {_norm(q) for q in sphere["queries"]})
        if score > best_score:
            best, best_score = sphere, score
    return best


def match_text(queries) -> str:
    """Подпись сферы для запроса истории — пустая строка, если сфера не наша."""
    sphere = sphere_for_queries(queries)
    return sphere["name"] if sphere else ""


def history_summary(entries) -> list[dict]:
    """Сводка истории по сферам: когда, где и сколько раз парсили. *entries* — то, что отдаёт search_history.get_history() (сначала новые)."""
    by_id: dict[str, dict] = {}
    all_cities: dict[str, set[str]] = {}
    for entry in entries or []:
        sphere = sphere_for_queries(entry.get("queries") or [])
        if sphere is None:
            continue
        item = by_id.setdefault(sphere["id"], {
            "id": sphere["id"],
            "last_ts": 0,
            "cities": [],
            "cities_total": 0,
            "runs": 0,
            "results": 0,
            "queries": [],
        })
        seen = all_cities.setdefault(sphere["id"], set())
        ts = float(entry.get("timestamp") or 0)
        item["runs"] += 1
        item["results"] += int(entry.get("results_count") or 0)
        # История уже отсортирована: первый раз, когда сфера встретилась, — её последний запуск.
        if not item["last_ts"]:
            item["last_ts"] = ts
            item["queries"] = [q for q in (entry.get("queries") or []) if str(q).strip()]
        for city in entry.get("cities") or []:
            name = str(city or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            if len(item["cities"]) < 5:
                item["cities"].append(name)
    for sphere_id, item in by_id.items():
        # Полное число городов: список обрезан для читаемости, но "+N" должен быть честным, а не терять остальные города молча.
        item["cities_total"] = len(all_cities.get(sphere_id) or ())
    return list(by_id.values())
