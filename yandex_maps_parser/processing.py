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
from datetime import datetime

from . import state
from .constants import KNOWN_PLATFORMS
from .exporters import (
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
    save_excel(payload, path, extra_fields=("website",))
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
    Returns {"groups": {query: {city: [records]}}, "count": int}.
    Empty result → {"groups": {}, "count": 0, "empty": True}.

    Socials live here (not at collection time) so that output/raw/ always
    keeps every organization found and a different social slice can be
    produced later with «Применить фильтры заново» — no re-crawling.
    """
    records: list[dict] = []
    for rf in raw_files:
        if os.path.isfile(rf):
            records.extend(load_raw_records(rf))
    if not records:
        return {"groups": {}, "count": 0, "empty": True}

    log = log_fn or (lambda *_: None)
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

    vk_mode = filters.get("vk_mode") or "all"
    vk_max_days = _int_or_zero(filters.get("vk_max_post_days"))
    vk_min_followers = _int_or_zero(filters.get("vk_min_followers"))
    min_score = _int_or_zero(filters.get("min_lead_score"))

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
        if filters.get("vk_check") and _vk_dropped(r):
            continue
        out.append(r)

    out = dedupe_records(out)
    if filters.get("sort_by_score"):
        out.sort(key=lambda r: _int_or_zero(r.get("lead_score")), reverse=True)

    groups: dict[str, dict[str, list[dict]]] = {}
    for r in out:
        q = r.get("query") or "прочее"
        c = r.get("city") or "прочее"
        groups.setdefault(q, {}).setdefault(c, []).append(r)

    if not out:
        return {"groups": {}, "count": 0, "empty": True}
    return {"groups": groups, "count": len(out)}


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

    log("info", f"  📦 Processed: {res['count']} организаций → {len(written)} файлов в output/processed/")
    cleanup_raw(raw_files, cleanup_mode)
    res["files"] = written
    return res
