"""Дисковый кэш HTML детальных карточек Яндекс.Карт (CDP)."""
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
# Порог «настоящей» страницы: короче — заглушка/ошибка (тот же 800-байтовый порог, что в enrichment._looks_like_antiblock и в сборе выдачи).
_MIN_BYTES = 800

_lock = threading.RLock()
_stats = {"hits": 0, "misses": 0, "stores": 0, "expired": 0, "evicted": 0}

# Приблизительный объём папки: (каталог, байты, когда проверяли по-настоящему).
# Без него каждый set_cached перебирал бы весь каталог — с сотнями страниц это
# заметная плата за каждую карточку. Точный пересчёт — раз в минуту и при
# выходе за лимит.
_approx: tuple[str, int, float] | None = None
_RESCAN_SECONDS = 60.0


def is_enabled() -> bool:
    """Кэш включён, если не выставлен YP_PAGE_CACHE=0."""
    return not _env_off("YP_PAGE_CACHE")


def reset_stats() -> None:
    """Сбросить счётчики попаданий/промахов в начале прогона."""
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


def _approx_size() -> int | None:
    """Размер папки из памяти — None, если для текущего каталога его ещё нет."""
    if _approx is None or _approx[0] != _CACHE_DIR:
        return None
    return _approx[1]


def _add_size(delta: int) -> None:
    """Учесть изменение размера, не заглядывая в каталог.

    Читают и пишут _approx несколько потоков (пул вкладок), поэтому
    read-modify-write идёт под замком: иначе параллельные удаления теряют
    поправки и счётчик уезжает от реальных байт.
    """
    global _approx
    with _lock:
        current = _approx_size()
        if current is not None and _approx is not None:
            _approx = (_approx[0], max(0, current + delta), _approx[2])


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
        else:
            _add_size(-st.st_size)
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
        else:
            _add_size(-st.st_size)
        _bump("misses")
        return None
    _bump("hits")
    return html


def _enforce_limit() -> None:
    """Держим папку кэша в пределах _MAX_BYTES, удаляя самые старые файлы."""
    global _approx
    now = time.time()
    known = _approx_size()
    if (known is not None and _approx is not None
            and now - _approx[2] < _RESCAN_SECONDS and known <= _MAX_BYTES):
        return                      # объём заведомо в норме — каталог не трогаем
    files = _page_files()
    total = sum(size for _, _, size in files)
    if total > _MAX_BYTES:
        files.sort(key=lambda item: item[1])      # от старых к новым
        for path, _, size in files:
            if total <= _MAX_BYTES:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            total -= size
            _bump("evicted")
    _approx = (_CACHE_DIR, total, now)


def set_cached(biz_id: str, html: str) -> None:
    """Сохранить страницу карточки. Заглушки и пустое не сохраняем."""
    if not is_enabled() or not biz_id or not html:
        return
    if len(html) < _MIN_BYTES:
        return
    try:
        _ensure_cache_dir()
        path = _path_for(biz_id)
        blob = html.encode("utf-8")
        # Пишем во временный файл и переименовываем: читатель (другой поток или следующий прогон) никогда не увидит половину страницы.
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(blob)
            os.replace(tmp, path)
        except OSError:
            # Неудачная запись не должна оставлять .tmp на диске навсегда
            # (на Windows файл мог быть занят читателем).
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
    except OSError:
        return
    _bump("stores")
    with _lock:
        _add_size(len(blob))
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
    for path, mtime, size in _page_files():
        if now - mtime <= _TTL_SECONDS:
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        _add_size(-size)
        removed += 1
    if removed:
        _bump("expired", removed)
    return removed
