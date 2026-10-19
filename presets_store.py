# -*- coding: utf-8 -*-
"""Пресеты поиска: одна копия для интерфейса и для консоли.

Пресеты собираются в браузере и лежат в localStorage — это удобно, но из
консоли их не видно, а запускать прогон в фоне хочется именно по сохранённому
набору: запросы, города, фильтры, форматы. Поэтому интерфейс дублирует список
в settings.json, а `app.py --run --preset «…»` читает его оттуда.

Здесь же — перевод пресета (форма интерфейса: `queries` строкой, `excel`,
`pages`, `blacklist`…) в параметры прогона (`run_web`: `queries` списком,
`output_excel`, `max_pages`, `blacklist_words`…). Один перевод на два входа:
если он разъедется, консольный прогон начнёт собирать не то, что показывает
интерфейс.

Чистка (`clean_presets`) — не бюрократия: в settings.json пишет браузер, и
битый или раздутый пресет иначе ломал бы чтение настроек при запуске.
"""
import json

MAX_PRESETS = 10
MAX_NAME = 60
MAX_STR = 500
MAX_LIST = 60


def _clean_value(value):
    """Только простые значения: строка/число/булево или их короткий список.

    Пресет — это настройки формы, а не хранилище: вложенные словари и
    многотысячные списки здесь не нужны и только раздували бы settings.json.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_STR]
    if isinstance(value, list):
        out = []
        for item in value[:MAX_LIST]:
            if isinstance(item, (str, int, float, bool)):
                out.append(item[:MAX_STR] if isinstance(item, str) else item)
        return out
    return None


def clean_presets(raw) -> list[dict]:
    """Список пресетов к безопасному виду; мусор отбрасывается, не падая."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:MAX_NAME]
        settings = item.get("settings")
        if not name or name.lower() in seen or not isinstance(settings, dict):
            continue
        clean = {}
        for key, value in settings.items():
            if not isinstance(key, str) or not key or len(key) > 40:
                continue
            value = _clean_value(value)
            if value is not None:
                clean[key] = value
        if not clean:
            continue
        seen.add(name.lower())
        out.append({"name": name, "settings": clean})
        if len(out) >= MAX_PRESETS:
            break
    return out


def load_presets() -> list[dict]:
    """Серверная копия пресетов из settings.json (пустой список на сбой)."""
    try:
        import paths
        return clean_presets(paths.load_settings().get("presets"))
    except Exception:
        return []


def save_presets(presets) -> list[dict]:
    """Сохранить серверную копию; возвращает то, что реально записалось."""
    clean = clean_presets(presets)
    try:
        import paths
        paths.save_settings({"presets": clean})
    except Exception:
        # Настройки не записались — пресет всё равно остаётся в браузере.
        pass
    return clean


def find_preset(name: str) -> dict | None:
    """Пресет по имени (без учёта регистра и лишних пробелов)."""
    key = " ".join(str(name or "").split()).lower()
    for preset in load_presets():
        if preset["name"].lower() == key:
            return preset
    return None


# ── Пресет интерфейса → параметры прогона ─────────────────────

def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_list(value) -> list[str]:
    """Строка «кафе, кофейня» / список / переносы строк → список строк."""
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(",", "\n").split("\n")
    elif isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        parts = []
    return [p.strip() for p in parts if p and p.strip()]


def preset_to_params(settings: dict, overrides: dict | None = None) -> dict:
    """Параметры для runner.run_web из настроек пресета.

    *overrides* — то, что явно передали в командной строке: оно сильнее
    пресета (флаг `--pages 3` должен победить сохранённое значение).
    """
    s = settings or {}
    o = overrides or {}

    def _pick(key, *names, default=None):
        # Флаг, которого нет в командной строке, приходит как None — он не
        # должен перебивать значение из пресета (иначе --pages необязательный
        # молча превращал бы сохранённые 2 страницы в 1).
        for name in names:
            if name in o and o[name] not in (None, ""):
                return o[name]
        return s.get(key, default)

    formats = o.get("formats")
    if formats:
        names = {str(f).strip().lower() for f in formats}
        excel = "excel" in names or "xlsx" in names
        as_json = "json" in names
        csv = "csv" in names
        as_map = "map" in names or "html" in names
    else:
        excel = bool(s.get("excel", True))
        as_json = bool(s.get("json", True))
        csv = bool(s.get("csv", False))
        as_map = bool(s.get("map", False))

    params = {
        "queries": _as_list(_pick("queries", "queries")),
        "cities": _as_list(_pick("cities", "cities")),
        "output_excel": excel,
        "output_json": as_json,
        "output_csv": csv,
        "output_map": as_map,
        "max_pages": max(1, _as_int(_pick("pages", "pages", default=1), 1)),
        "max_workers": max(1, _as_int(_pick("workers", "workers", default=20), 20)),
        "query_workers": max(1, min(5, _as_int(_pick("queryWorkers", "query_workers", default=2), 2))),
        "max_candidates": max(0, _as_int(_pick("maxCandidates", "max_candidates", default=200), 200)),
        "use_grid": bool(_pick("grid", "use_grid", default=False)),
        "grid_radius": max(1, _as_int(_pick("grad", "grid_radius", default=20), 20)),
        "grid_step": max(1, _as_int(_pick("gstep", "grid_step", default=5), 5)),
        # Двухэтапный сбор — как в интерфейсе: сначала raw, потом фильтры.
        "pipeline": "raw",
        "raw_mode": str(_pick("rawMode", "raw_mode", default="keep") or "keep"),
        "parse_mode": str(s.get("parseMode") or "without_website"),
        "collapse_chains": bool(s.get("collapseChains", False)),
        "chain_key": str(s.get("chainKey") or "name_city"),
        "social_mode": str(s.get("socialMode") or "all"),
        "required_socials": _as_list(s.get("requiredSocials") or []),
        "vk_check": bool(s.get("vkCheck", False)),
        "min_lead_score": max(0, _as_int(s.get("minScore", 0), 0)),
        "blacklist_words": _as_list(s.get("blacklist") or []),
        "only_single_branch": bool(s.get("onlySingle", False)),
        "only_new_months": (s.get("onlyNewPeriod") if s.get("onlyNew") else None),
        "continue_cities": bool(s.get("continueMode", False)),
        "continue_limit": max(0, _as_int(s.get("continueLimit", 5), 5)),
        "fetch_detail": True,
    }

    # Флаги командной строки поверх пресета.
    if "pages" in o and o["pages"] is not None:
        params["max_pages"] = max(1, _as_int(o["pages"], 1))
    if "workers" in o and o["workers"] is not None:
        params["max_workers"] = max(1, _as_int(o["workers"], 20))
    if "max" in o and o["max"] is not None:
        params["max_candidates"] = max(0, _as_int(o["max"], 200))
    if o.get("no_continue"):
        params["continue_cities"] = False

    return params


def load_preset_source(spec: str) -> dict:
    """Пресет по имени из settings.json или из JSON-файла.

    Файл — это либо сам пресет ({"name":…, "settings": {…}}), либо просто
    настройки формы ({queries: …}), либо список пресетов из экспорта.
    """
    import os

    if spec and os.path.isfile(spec):
        with open(spec, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("settings"), dict):
            return {"name": str(data.get("name") or os.path.basename(spec)),
                    "settings": data["settings"]}
        if isinstance(data, dict):
            return {"name": os.path.basename(spec), "settings": data}
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and isinstance(first.get("settings"), dict):
                return first
        raise ValueError("в файле нет настроек пресета")

    preset = find_preset(spec)
    if preset is None:
        names = [p["name"] for p in load_presets()]
        hint = (f"Сохранённые пресеты: {', '.join(names)}." if names
                else "Сохранённых пресетов нет: сохраните пресет в интерфейсе "
                     "или передайте путь к JSON-файлу.")
        raise KeyError(f"пресет «{spec}» не найден. {hint}")
    return preset
