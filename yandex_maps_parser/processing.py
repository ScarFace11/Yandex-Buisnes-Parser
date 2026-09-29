"""
Two-stage pipeline: Сбор (Raw) → Фильтрация (Processed).

Stage 1 (collection, run_web with PIPELINE="raw") parses WITHOUT stage-2
filters and exports every record to output/raw/ as one xlsx per
query × city. Stage 2 (this module) reads those raw files back, applies
the user filters and writes output/processed/{format}/ files.

Benefits: filtering never slows the crawl, raw data survives for
re-processing with different filters, processed output is reproducible.
"""
import os
import re
import shutil
from datetime import datetime, timedelta

from . import state
from .constants import KNOWN_PLATFORMS
from .exporters import (
    _norm_name,
    _records_from_xlsx,
    collapse_chains,
    collapse_chains_chain_keys,
    collapse_chains_name_city,
    dedupe_records,
    save_csv,
    save_excel,
    save_json,
    save_map,
)


# ── Naming ────────────────────────────────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"[^\w]+", "_", (s or "").strip()).strip("_").lower() or "NA"


def raw_filename(query: str, city: str) -> str:
    """raw_YYYY-MM-DD_HH-MM_{query}_{city}.xlsx"""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"raw_{ts}_{_slug(query)}_{_slug(city)}.xlsx"


def raw_path(query: str, city: str) -> str:
    return os.path.join(state.RAW_DIR, raw_filename(query, city))


# ── Raw I/O ───────────────────────────────────────────────────

def raw_files_for(queries, cities) -> list[str]:
    """Raw files (any age) belonging to these query × city pairs.

    Used on «Продолжить»: the slice collected before the pause must join the
    stage-2 input, otherwise the resumed run would export only what it parsed
    after the pause.
    """
    want = {f"_{_slug(q)}_{_slug(c)}.xlsx" for q in (queries or [])
            for c in (cities or [])}
    if not want or not os.path.isdir(state.RAW_DIR):
        return []
    out = []
    for fname in sorted(os.listdir(state.RAW_DIR)):
        if fname.endswith(".xlsx") and any(fname.endswith(sfx) for sfx in want):
            out.append(os.path.join(state.RAW_DIR, fname))
    return out


def export_raw_records(records: list[dict], query: str, city: str,
                       merge_existing: bool = False) -> str:
    """Save the collected records of one query × city as a raw xlsx.

    Raw files carry the website column (INTERNAL_FIELDS) even though it is
    no longer part of the user-facing report — stage 2 re-applies
    «только без сайтов» straight from these files.

    `merge_existing` (used on «Продолжить»): the file name only carries
    minute precision, so the resumed run would otherwise OVERWRITE the slice
    collected before the pause and the earlier organizations would vanish
    from the result. Their records are merged in instead (stage 2 dedupes).
    """
    os.makedirs(state.RAW_DIR, exist_ok=True)
    path = raw_path(query, city)
    payload = list(records)
    if merge_existing:
        try:
            if os.path.isfile(path):
                payload = dedupe_records(load_raw_records(path) + payload)
        except Exception:
            payload = list(records)
    # branch_count / added_at — внутренние поля этапа 2, как website: отчёт
    # их не показывает, но без них фильтры «🎯 Тип компании» не выжили бы
    # до «Применить фильтры заново» (фильтрация идёт по raw-файлам).
    save_excel(payload, path, extra_fields=("website", "branch_count", "added_at"))
    return path


def load_raw_records(path: str) -> list[dict]:
    """Read a raw xlsx back into business records (english keys)."""
    return _records_from_xlsx(path)


def list_raw_files() -> list[str]:
    """All raw xlsx files, oldest first."""
    try:
        return sorted(f for f in os.listdir(state.RAW_DIR) if f.endswith(".xlsx"))
    except OSError:
        return []


def collect_raw_files(since_mtime: float) -> list[str]:
    """Absolute paths of raw xlsx files created at/after since_mtime.

    Used to attribute raw files to one specific run (file names carry
    only minute precision, mtime is exact).
    """
    out: list[str] = []
    if os.path.isdir(state.RAW_DIR):
        for fname in sorted(os.listdir(state.RAW_DIR)):
            fp = os.path.join(state.RAW_DIR, fname)
            if os.path.isfile(fp) and fname.endswith(".xlsx") and os.path.getmtime(fp) >= since_mtime:
                out.append(fp)
    return out


# ── Stage 2: filtering ────────────────────────────────────────

def _int_or_zero(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


# ── Blacklist («🚫 Исключить по словам») ──────────────────────
# Ограничения держим на сервере, а не только в интерфейсе: список приезжает
# ещё и из пресета/настроек и по сети, а этап 2 не должен падать или
# тормозить на списке из тысячи слов.
BLACKLIST_MAX_WORDS = 100   # больше — уже не «исключения», а второй поиск
BLACKLIST_MAX_LEN = 50      # слово длиннее — опечатка или вставленный абзац
# Поля, по которым ищем подстроку: название, категория и (если есть) описание.
BLACKLIST_FIELDS = ("name", "category", "description")


def parse_blacklist_words(value) -> list[str]:
    """«Франшиза, VIP; сеть\nдубль» → ['франшиза', 'vip', 'сеть', 'дубль'].

    Сплит по запятой, точке с запятой и переводу строки; trim; lowercase;
    пустые выброшены; дубликаты убраны; слова длиннее `BLACKLIST_MAX_LEN`
    отброшены (это не слово, а вставленный текст); список обрезан до
    `BLACKLIST_MAX_WORDS`. Идемпотентно: повторный прогон ничего не меняет,
    поэтому результат можно спокойно сохранять.
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        for part in re.split(r"[,;\n]+", str(item)):
            word = part.strip().lower()
            if not word or len(word) > BLACKLIST_MAX_LEN or word in seen:
                continue
            seen.add(word)
            out.append(word)
            if len(out) >= BLACKLIST_MAX_WORDS:
                return out
    return out


def blacklist_matcher(words):
    """Регистронезависимый поиск подстрок — или None, если список пуст.

    Сила blacklist в том, что он побеждает остальные фильтры: слово
    снимает запись до проверок по сайтам, соцсетям и оценке. Спецсимволы
    (`C++`, `[акция]`) экранируются: ищется ровно то, что ввёл пользователь,
    а не регулярка, которую он не писал.
    """
    words = [w for w in (words or []) if w]
    if not words:
        return None
    pattern = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)

    def _hit(rec: dict) -> bool:
        return any(pattern.search(str(rec.get(f) or "")) for f in BLACKLIST_FIELDS)

    return _hit


# ── «🎯 Тип компании»: одиночки и новые ──────────────────────
# Одиночки — сеть из одного филиала: решение принимает владелец.
# Новые — карточка недавно появилась в 2ГИС: бюджет на запуск уже есть.
# Оба фильтра консервативны: нет данных — запись НЕ отсеивается. «Неизвестно»
# не значит «не подходит», а выдуманная дата хуже отсутствия фильтра.

COMPANY_TYPE_MONTHS = (1, 3, 6, 12, 24)   # варианты периода в интерфейсе
NEW_COMPANY_DEFAULT_MONTHS = 6            # дефолт селекта «за последние … мес.»
_DAYS_PER_MONTH = 30                      # «месяц» ≈ 30 дней: календарь не нужен


def _int_or_none(value):
    """Целое из чего угодно — или None. Пустое/мусор не становятся нулём."""
    if isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def normalize_only_new_months(value):
    """Период «новых» в месяцах: 1/3/6/12/24, иначе 6; 0/None/мусор → выкл.

    Значение приезжает из браузера, пресета и настроек, поэтому проверяем его
    на сервере: произвольное число не должно превращаться в «за всё время».
    """
    if value in (None, "", False):
        return None
    n = _int_or_none(value)
    if n is None:
        return NEW_COMPANY_DEFAULT_MONTHS
    if n <= 0:
        return None
    return n if n in COMPANY_TYPE_MONTHS else NEW_COMPANY_DEFAULT_MONTHS


def annotate_branch_counts(records: list[dict]) -> None:
    """Проставить branch_count всем записям — включая сборы без этого поля.

    2ГИС отдаёт число филиалов сети в items.org.branch_count, но демо-ключи и
    файлы, собранные до этой версии, поля не знают. Тогда филиалы считаем сами:
    записи с одинаковым нормализованным названием в одном городе — ветки одной
    сети (том же ключом работает «Объединять филиалы сетей»). Значение из API
    важнее нашего: сбор ограничен точками поиска и может недосчитать сеть.

    0 из API — валидное «филиалов нет»; у кого данных нет вообще, поле
    остаётся пустым, и фильтр такую запись пропускает.
    """
    found: dict[tuple, int] = {}
    api_max: dict[tuple, int] = {}
    for r in records:
        name = _norm_name(r.get("name"))
        if not name:
            continue
        key = ((r.get("city") or "").strip().lower(), name)
        found[key] = found.get(key, 0) + 1
        api = _int_or_none(r.get("branch_count"))
        if api is not None and api > api_max.get(key, -1):
            api_max[key] = api

    for r in records:
        name = _norm_name(r.get("name"))
        key = ((r.get("city") or "").strip().lower(), name) if name else None
        ours = found.get(key, 0) if key else 0
        # Число из API знает всю сеть только у одной из веток — отдаём его
        # всей группе, иначе «Ваша кофейня» с 7 филиалами выглядела бы
        # одиночкой только потому, что значение пришло на другой строке.
        api = api_max.get(key) if key else None
        if ours or api is not None:
            r["branch_count"] = max(ours, api or 0)


def is_single_branch(rec: dict) -> bool:
    """Подходит ли запись под «только одиночки».

    Пустое/нечисловое значение → True (пропускаем): компания без данных о
    филиалах не должна выкидываться из отчёта. 0 и 1 — одиночка, 2+ — сеть.
    """
    n = _int_or_none(rec.get("branch_count"))
    return n is None or n <= 1


def is_new_company(rec: dict, months) -> bool:
    """Подходит ли запись под «только новые» (карточка появилась недавно).

    Дата — added_at из items.dates 2ГИС. Даты нет (источник Яндекс, старый
    сбор, демо-ключ) или она битая — пропускаем: фильтр не выдумывает дату.
    """
    if not months:
        return True
    raw = str(rec.get("added_at") or "").strip()
    if len(raw) < 10:
        return True
    try:
        added = datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return added >= (datetime.now().date() - timedelta(days=int(months) * _DAYS_PER_MONTH))


def company_type_breakdown(records: list[dict], only_new_months=None) -> dict:
    """Сколько компаний подойдёт под фильтры «типа компании» (для счётчика).

    Логика общая с apply_filters — цифра в подсказке не может разойтись с
    результатом «Применить фильтры заново». `both` — пересечение (фильтры
    работают по И), `with_date` — у скольких вообще есть дата добавления:
    без этого непонятно, почему «только новые» ничего не отсеял.
    """
    months = normalize_only_new_months(only_new_months)
    single = new = both = with_date = 0
    for r in records:
        s, n = is_single_branch(r), is_new_company(r, months)
        single += 1 if s else 0
        new += 1 if n else 0
        both += 1 if (s and n) else 0
        with_date += 1 if str(r.get("added_at") or "").strip() else 0
    return {"total": len(records), "single": single, "new": new, "both": both,
            "with_date": with_date, "months": months}


def _has_own_website(rec: dict) -> bool:
    # Aggregators (taplink/linktree) are link pages, not a website —
    # same rule as the live PARSE_MODE filter during collection.
    site = (rec.get("website") or rec.get("aggregator_url") or "").strip()
    if not site:
        return False
    return not re.search(r"taplink|linktree|linktr\.ee|becons\.ai|illions\.app", site, re.I)


def apply_filters(raw_files: list[str], filters: dict, log_fn=None) -> dict:
    """Read raw files, merge chains and apply the stage-2 filters.

    Order (edge case 1): merge chains FIRST («Название + Город»), then
    the record filters — merging before filtering keeps the merged
    contacts of branches that a filter would drop.

    filters:
        collapse_chains  — merge chain branches into one row
        chain_key        — merge strategy: "name_city" | "name" | "phone" | "email"
        parse_mode       — "without_website" | "all"
        social_mode      — "all" | "with_socials" | "without_socials"
        required_socials — list of platforms the business must ALL have
        vk_check         — query VK activity (needs a VK token)
        vk_mode          — "all" | "active" | "active_semi"
        vk_max_post_days — drop communities idle for longer (0 = off)
        vk_min_followers — drop smaller communities (0 = off)
        min_lead_score   — drop leads below this score (0 = off)
        sort_by_score    — order by lead_score, hottest first
        blacklist_words  — слова-исключения (название/категория/описание)
        only_single_branch — оставить компании с 1 филиалом (владелец решает сам)
        only_new_months  — оставить карточки, появившиеся в 2ГИС за N месяцев
                           (1/3/6/12/24; None/0 — выключено)
    Returns {"groups": {query: {city: [records]}}, "count": int}.
    Empty result → {"groups": {}, "count": 0, "empty": True}.

    Blacklist применяется ПОСЛЕ объединения филиалов и ДО остальных фильтров:
    если слово исключает компанию, она не вернётся ни соцсетями, ни оценкой
    лида — иначе «исключено» зависело бы от остальных галочек.

    Socials live here (not at collection time) so that output/raw/ always
    keeps every organization found and a different social slice can be
    produced later with «Применить фильтры заново» — no re-crawling.
    """
    records: list[dict] = []
    for rf in raw_files:
        if os.path.isfile(rf):
            records.extend(load_raw_records(rf))
    if not records:
        return {"groups": {}, "count": 0, "empty": True,
                "blacklist_words": [], "blacklist_excluded": 0,
                "company_type_excluded": 0, "single_excluded": 0, "new_excluded": 0}

    log = log_fn or (lambda *_: None)

    # «🎯 Тип компании»: число филиалов нужно и фильтру, и объединению сетей —
    # считаем ДО merge, иначе ветки сети уже схлопнуты в одну строку и сеть
    # выглядела бы одиночкой. Заодно досчитываем старые сборы без поля.
    annotate_branch_counts(records)

    collapse = bool(filters.get("collapse_chains"))

    if collapse:
        # Strategy comes from the UI dropdown («Объединять филиалы сетей»):
        # name_city (default) | name | phone | email. Unknown values fall
        # back to the documented default instead of crashing stage 2.
        # «name_city» keeps the strict stage-2 semantics (every same-named
        # business in a city merges — acceptance criterion); the contact
        # strategies go through the generic collapse_chains.
        chain_key = str(filters.get("chain_key") or "name_city")
        if chain_key not in collapse_chains_chain_keys():
            chain_key = "name_city"
        if chain_key == "name_city":
            records = collapse_chains_name_city(records)
        else:
            records = collapse_chains(records, chain_key)

    # ── VK activity + lead score ──────────────────────────────
    # Order: merge chains first (fewer communities to query), then activity,
    # then the score (it reads the activity), then the record filters.
    if filters.get("vk_check"):
        try:
            from .vk_stats import annotate_records as _vk_annotate
            _vk_annotate(records, log_fn=log_fn)
        except Exception as exc:  # a dead VK API must not kill stage 2
            log("warn", f"  [!] Активность ВК недоступна: {exc}")

    try:
        from .lead_score import annotate_records as _score_annotate
        _score_annotate(records)
    except Exception:
        pass

    blacklist_words = parse_blacklist_words(filters.get("blacklist_words"))
    blacklist_hit = blacklist_matcher(blacklist_words)
    blacklist_excluded = 0

    vk_mode = filters.get("vk_mode") or "all"
    vk_max_days = _int_or_zero(filters.get("vk_max_post_days"))
    vk_min_followers = _int_or_zero(filters.get("vk_min_followers"))
    min_score = _int_or_zero(filters.get("min_lead_score"))
    # «🎯 Тип компании»: одиночки и новые (AND с остальными фильтрами).
    only_single = bool(filters.get("only_single_branch"))
    only_new_months = normalize_only_new_months(filters.get("only_new_months"))
    single_excluded = 0
    new_excluded = 0

    def _vk_dropped(r: dict) -> bool:
        """False when the record passes the VK-activity block.

        Records without VK data pass: we only drop what we have measured,
        so a missing token never empties the report.
        """
        activity = (r.get("vk_activity") or "").lower()
        if not activity or activity == "unknown":
            return False
        if vk_mode == "active" and activity != "active":
            return True
        if vk_mode == "active_semi" and activity not in ("active", "semi"):
            return True
        days = r.get("vk_last_post_days")
        if vk_max_days and days not in (None, ""):
            try:
                if int(days) > vk_max_days:
                    return True
            except (TypeError, ValueError):
                pass
        followers = r.get("vk_followers")
        if vk_min_followers and followers not in (None, ""):
            try:
                if int(followers) < vk_min_followers:
                    return True
            except (TypeError, ValueError):
                pass
        return False

    parse_mode = filters.get("parse_mode") or "all"
    social_mode = filters.get("social_mode") or "all"
    required = {str(p) for p in (filters.get("required_socials") or []) if str(p) in KNOWN_PLATFORMS}
    out: list[dict] = []
    for r in records:
        # Blacklist побеждает другие фильтры — проверяем его первым.
        if blacklist_hit and blacklist_hit(r):
            blacklist_excluded += 1
            continue
        if parse_mode == "without_website" and _has_own_website(r):
            continue
        has_any_social = any(r.get(p) for p in KNOWN_PLATFORMS)
        if social_mode == "with_socials" and not has_any_social:
            continue
        if social_mode == "without_socials":
            # Networks cannot be required from a record that must have none.
            if has_any_social:
                continue
        # Selected networks are an AND filter: the business must have ALL of them.
        elif required and not all(r.get(p) for p in required):
            continue
        if min_score and _int_or_zero(r.get("lead_score")) < min_score:
            continue
        if only_single and not is_single_branch(r):
            single_excluded += 1
            continue
        if only_new_months and not is_new_company(r, only_new_months):
            new_excluded += 1
            continue
        if filters.get("vk_check") and _vk_dropped(r):
            continue
        out.append(r)

    if blacklist_words:
        log("info", f"  🚫 Blacklist: исключено {blacklist_excluded} компаний")

    if only_single or only_new_months:
        _ct_total = single_excluded + new_excluded
        if _ct_total:
            log("info", f"  🎯 Тип компании: исключено {_ct_total} "
                        f"(одиночки {single_excluded}, новые {new_excluded})")

    out = dedupe_records(out)
    if filters.get("sort_by_score"):
        out.sort(key=lambda r: _int_or_zero(r.get("lead_score")), reverse=True)

    groups: dict[str, dict[str, list[dict]]] = {}
    for r in out:
        q = r.get("query") or "прочее"
        c = r.get("city") or "прочее"
        groups.setdefault(q, {}).setdefault(c, []).append(r)

    blacklist_info = {"blacklist_words": blacklist_words,
                      "blacklist_excluded": blacklist_excluded,
                      # Счётчики «типа компании»: у рефильтра нет потоковых
                      # логов сервера, фронтенд пишет строку по этому числу.
                      "company_type_excluded": single_excluded + new_excluded,
                      "single_excluded": single_excluded,
                      "new_excluded": new_excluded}
    if not out:
        return {"groups": {}, "count": 0, "empty": True, **blacklist_info}
    return {"groups": groups, "count": len(out), **blacklist_info}


# ── Stage 2 output ────────────────────────────────────────────

_FMT_DIR = {"excel": "excel", "xlsx": "excel", "json": "json", "csv": "csv", "html": "html", "map": "html"}


def _fmt_dir(fmt: str) -> str:
    d = os.path.join(state.PROCESSED_DIR, _FMT_DIR.get(fmt, fmt))
    os.makedirs(d, exist_ok=True)
    return d


def processed_filename(fmt: str, query: str, city: str) -> str:
    stem = f"{_slug(query)}_{_slug(city)}_filtered"
    if fmt in ("excel", "xlsx"):
        return f"{stem}.xlsx"
    if fmt == "json":
        return f"{stem}.json"
    if fmt == "csv":
        return f"{stem}.csv"
    return f"{stem}_map.html"


def save_processed(data: list[dict], fmt: str, query: str, city: str) -> str:
    """Save filtered records to output/processed/{format}/ (edge case 4:
    one filter pass, export to every requested format)."""
    path = os.path.join(_fmt_dir(fmt), processed_filename(fmt, query, city))
    if fmt in ("excel", "xlsx"):
        save_excel(data, path)
    elif fmt == "json":
        save_json(data, path, append=False)
    elif fmt == "csv":
        save_csv(data, path, append=False)
    elif fmt in ("html", "map"):
        lat = next((float(r["lat"]) for r in data if r.get("lat")), 55.7558)
        lon = next((float(r["lon"]) for r in data if r.get("lon")), 37.6173)
        save_map(data, path, lat, lon)
    return path


# ── Raw cleanup ───────────────────────────────────────────────

def cleanup_raw(raw_files: list[str], mode: str) -> None:
    """keep → no-op; delete → remove; archive → output/_archive/YYYY-MM-DD/."""
    if mode == "delete":
        for f in raw_files:
            try:
                if os.path.isfile(f):
                    os.remove(f)
            except OSError:
                pass
    elif mode == "archive":
        import paths  # project-root paths module (same import style as config)
        target = paths.archive_dir()
        for f in raw_files:
            try:
                if os.path.isfile(f):
                    shutil.move(f, os.path.join(target, os.path.basename(f)))
            except OSError:
                pass


# ── Orchestration ─────────────────────────────────────────────

def process_all(
    raw_files: list[str],
    filters: dict,
    formats: list[str],
    log_fn=None,
    cleanup_mode: str = "keep",
) -> dict:
    """Stage 2 + cleanup: filter raw files and export to every format."""
    log = log_fn or (lambda *_: None)

    log("info", "  🧪 Этап 2: применяю фильтры к сырым данным…")
    res = apply_filters(raw_files, filters, log_fn=log)

    if res.get("empty"):
        # Edge case 2: nothing survived the filters.
        log("warn", "  ⚠ Ничего не найдено по заданным фильтрам. Измените настройки.")
        return res

    formats = [f for f in formats if f]
    written: list[str] = []
    for q, cities in res["groups"].items():
        for c, recs in cities.items():
            for fmt in formats:
                try:
                    written.append(save_processed(recs, fmt, q, c))
                except Exception as exc:  # one bad group must not stop the rest
                    log("warn", f"  [!] Ошибка экспорта {fmt}: {q} / {c}: {exc}")

    # Полный путь: папка результатов может быть пользовательской.
    log("info", f"  📦 Processed: {res['count']} организаций → {len(written)} файлов в {state.PROCESSED_DIR}")
    cleanup_raw(raw_files, cleanup_mode)
    res["files"] = written
    return res
