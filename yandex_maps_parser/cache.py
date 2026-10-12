"""Дисковый кэш HTML детальных карточек Яндекс.Карт (CDP).

Одна и та же организация не перекачивается дважды: страница карточки,
которую браузер отдал целиком, лежит в `output/.cache/pages/` и живёт
`TTL` часов. Выигрыш считанный: загрузка карточки через CDP — это навигация
Chrome с ожиданием рендера (секунды на организацию, при антиботе и до
десятков секунд), а попадание в кэш — чтение файла (доли миллисекунды).
Повторный прогон по тем же городам (второй проход, «Применить фильтры»,
дозапуск после стопа) не ждёт браузер на каждой организации и не дёргает
Яндекс лишний раз.

Что попадает на диск: только «здоровые» страницы (см.
`extractors.fetch_html`). Антибот-заглушка, пустой ответ и ошибка навигации
не кэшируются — иначе заглушка жила бы сутки, и организация навсегда
осталась бы без деталей.

Управление (переменные окружения):

* `YP_PAGE_CACHE=0` — выключить кэш целиком (по умолчанию включён);
* `YP_PAGE_CACHE_TTL` — время жизни страницы в часах (по умолчанию 24);
* `YP_PAGE_CACHE_MB` — лимит объёма папки кэша в МиБ (по умолчанию 150):
  при переполнении удаляются самые старые страницы.

`cleanup_expired()` вызывается при старте приложения (см. `app.py`),
`cache_stats()` отдаётся в `/cache/stats` и в сводку прогона.
"""
import os
import re
import threading
import time

from . import state


def _env_off(name: str, default: bool = False) -> bool:
    """True, когда переменная окружения задана как 0/false/no/off."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


_CACHE_DIR = os.path.join(state.OUTPUT_DIR, ".cache", "pages")
_TTL_SECONDS = _env_int("YP_PAGE_CACHE_TTL", 24) * 3600
_MAX_BYTES = _env_int("YP_PAGE_CACHE_MB", 150) * 1024 * 1024
# Порог «настоящей» страницы: короче — заглушка/ошибка (тот же 800-байтовый
# порог, что в enrichment._looks_like_antiblock и в сборе выдачи).
_MIN_BYTES = 800

_lock = threading.RLock()
_stats = {"hits": 0, "misses": 0, "stores": 0, "expired": 0, "evicted": 0}


def is_enabled() -> bool:
    """Кэш включён, если не выставлен YP_PAGE_CACHE=0."""
    return not _env_off("YP_PAGE_CACHE")


def reset_stats() -> None:
    """Сбросить счётчики попаданий/промахов в начале прогона.

    Вызывается рядом с http_client.reset_stats(): иначе в сводке стояли бы
    цифры прошлых прогонов (сервер живёт одним процессом весь день).
    """
    with _lock:
        for key in _stats:
            _stats[key] = 0


def _bump(key: str, n: int = 1) -> None:
    with _lock:
        _stats[key] = _stats.get(key, 0) + n


def _path_for(biz_id: str) -> str:
    """Путь файла страницы. Ключ — id организации; чистим под имя файла."""
    key = re.sub(r"[^0-9A-Za-z_.-]", "_", str(biz_id))[:80] or "unknown"
    return os.path.join(_CACHE_DIR, key + ".html")


def _ensure_cache_dir() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _page_files() -> list[tuple[str, float, int]]:
    """(path, mtime, size) по всем страницам кэша; битые записи пропускаем."""
    out: list[tuple[str, float, int]] = []
    try:
        with os.scandir(_CACHE_DIR) as it:
            for entry in it:
                if not entry.name.endswith(".html"):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                out.append((entry.path, st.st_mtime, st.st_size))
    except OSError:
        return []
    return out


def _enforce_limit() -> None:
    """Держим папку кэша в пределах _MAX_BYTES, удаляя самые старые файлы."""
    files = _page_files()
    total = sum(size for _, _, size in files)
    if total <= _MAX_BYTES:
        return
    files.sort(key=lambda item: item[1])          # от старых к новым
    for path, _, size in files:
        if total <= _MAX_BYTES:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        _bump("evicted")


def get_cached(biz_id: str) -> str | None:
    """Вернуть HTML карточки из кэша или None (нет файла / TTL истёк)."""
    if not is_enabled() or not biz_id:
        return None
    path = _path_for(biz_id)
    try:
        st = os.stat(path)
    except OSError:
        _bump("misses")
        return None
    if time.time() - st.st_mtime > _TTL_SECONDS:
        try:
            os.remove(path)
        except OSError:
            pass
        _bump("expired")
        _bump("misses")
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            html = fh.read()
    except OSError:
        _bump("misses")
        return None
    if len(html) < _MIN_BYTES:
        # Обрезанный/битый файл — это не карточка: убираем и идём качать.
        try:
            os.remove(path)
        except OSError:
            pass
        _bump("misses")
        return None
    _bump("hits")
    return html


def set_cached(biz_id: str, html: str) -> None:
    """Сохранить страницу карточки. Заглушки и пустое не сохраняем."""
    if not is_enabled() or not biz_id or not html:
        return
    if len(html) < _MIN_BYTES:
        return
    try:
        _ensure_cache_dir()
        path = _path_for(biz_id)
        # Пишем во временный файл и переименовываем: читатель (другой поток
        # или следующий прогон) никогда не увидит половину страницы.
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(html)
        os.replace(tmp, path)
    except OSError:
        return
    _bump("stores")
    with _lock:
        _enforce_limit()


def cache_stats() -> dict:
    """Статистика кэша для `/cache/stats` и сводки прогона."""
    files = _page_files()
    total = len(files)
    now = time.time()
    valid = sum(1 for _, mtime, _ in files if now - mtime <= _TTL_SECONDS)
    with _lock:
        counters = dict(_stats)
    return {
        "enabled": is_enabled(),
        "dir": _CACHE_DIR,
        "ttl_hours": _TTL_SECONDS // 3600,
        "total": total,
        "valid": valid,
        "expired": total - valid,
        "bytes": sum(size for _, _, size in files),
        "max_bytes": _MAX_BYTES,
        **counters,
    }


def cleanup_expired() -> int:
    """Удалить страницы старше TTL. Возвращает число удалённых файлов."""
    if not is_enabled():
        return 0
    removed = 0
    now = time.time()
    for path, mtime, _ in _page_files():
        if now - mtime <= _TTL_SECONDS:
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1
    if removed:
        _bump("expired", removed)
    return removed
