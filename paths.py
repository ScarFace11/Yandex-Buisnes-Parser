"""Path resolution for frozen (PyInstaller) and normal (source) runs.

Три вида мест:
- RESOURCE_DIR — только для чтения, файлы в комплекте (templates/, static/):
  в бандле PyInstaller это папка распаковки (sys._MEIPASS), в исходниках —
  корень проекта.
- USER_DIR — куда можно писать (output/, logs/, .env, settings.json).
  Во frozen-сборке это папка с .exe, чтобы данные жили между запусками;
  на macOS сам .app обычно лежит в read-only /Applications, поэтому данные
  уходят в ~/Library/Application Support/<App>; в исходниках — корень проекта.
- CONFIG_PATH — файл .env; та же USER_DIR, но вычисляется до импорта config,
  чтобы переменные окружения читались и в распакованной папке сборки.

Результаты можно держать отдельно от служебных файлов: папка из settings.json
(ключ «results_root») принимает raw/, processed/ и _archive/, а кэш найденного,
чекпоинты, история поиска и отметки «просмотрено» остаются в USER_DIR/output/.
Пустая настройка = прежнее поведение (всё в output/).
"""
import json
import os
import sys
from datetime import date
from pathlib import Path


APP_SLUG = "YandexBusinessParser"

# Служебный файл настроек приложения (не в git): папка результатов и переопределения по этапам.
SETTINGS_FILE = "settings.json"
RESULTS_ROOT_KEY = "results_root"
STAGE_KEYS = {"raw": "raw_dir", "processed": "processed_dir", "archive": "archive_dir"}
STAGE_SUBDIRS = {"raw": "raw", "processed": "processed", "archive": "_archive"}


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _is_macos() -> bool:
    """True on macOS (checked through a helper so tests can patch it)."""
    return sys.platform == "darwin"


def _exe_dir() -> Path:
    """Folder containing the .exe (or the onedir bundle's _internal parent)."""
    return Path(sys.executable).resolve().parent


def _app_slug() -> str:
    """Имя папки данных: у сборки разработчика — своё, рядом с публичным."""
    if is_frozen() and Path(sys.executable).stem.lower().endswith("dev"):
        return APP_SLUG + "Dev"
    return APP_SLUG


# Метка локальной сборки: её создают build.bat / build-mac.sh и workflow build-manual.yml.
LOCAL_BUILD_MARKER = ".local-build"


def local_build_marker() -> Path:
    """Путь к метке локальной сборки."""
    d = _exe_dir()
    if _is_macos():
        # .app: Contents/MacOS/<bin> → .app/Contents → корень бандла
        d = d.parent.parent
    return d / LOCAL_BUILD_MARKER


def resource_dir() -> Path:
    """Read-only bundled resources (templates/, static/)."""
    if not is_frozen():
        return Path(__file__).resolve().parent
    # PyInstaller onefile extracts to _MEIPASS; onedir puts data files next to the executable under _internal/.
    exe = _exe_dir()
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass))
    candidates += [exe / "_internal", exe.parent / "Resources", exe / "Resources"]
    for c in candidates:
        if (c / "templates").is_dir():
            return c
    return candidates[0]


def data_dir() -> Path:
    """Корень пользовательских данных (output/, logs/, .env, configs)."""
    if is_frozen():
        if _is_macos():
            # .app обычно лежит в /Applications (только для чтения) — данные уходят в стандартную папку macOS, как у любого десктоп-приложения.
            return Path.home() / "Library" / "Application Support" / _app_slug()
        return _exe_dir()
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Writable location for user data (output/, logs/, .env, configs)."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_dir() -> str:
    return str(resource_dir() / "templates")


def static_dir() -> str:
    return str(resource_dir() / "static")


# ── Настройки приложения (settings.json) ─────────────────────
def settings_path() -> Path:
    """settings.json рядом с данными приложения (не внутри output/)."""
    return user_dir() / SETTINGS_FILE


def load_settings() -> dict:
    """Содержимое settings.json; пустой словарь на любой сбой."""
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(values: dict) -> None:
    """Атомарно дописывает ключи в settings.json."""
    data = load_settings()
    data.update(values or {})
    replace_settings(data)


def replace_settings(data: dict) -> None:
    """Атомарно ЗАМЕНИТЬ settings.json целиком."""
    path = settings_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── Папки результатов ────────────────────────────────────────
def _expand(value: str) -> Path:
    """Пользовательский путь: ~, %VAR%/$VAR и относительный путь от данных."""
    return Path(os.path.expanduser(os.path.expandvars(str(value).strip())))


def default_results_root() -> Path:
    """По умолчанию — output/ там же, где остальные данные приложения."""
    return user_dir() / "output"


def results_root() -> Path:
    """Корень результатов: настройка «Папка для сохранения» или output/."""
    custom = str(load_settings().get(RESULTS_ROOT_KEY) or "").strip()
    return _expand(custom) if custom else default_results_root()


def stage_dir(stage: str) -> Path:
    """Папка этапа (raw|processed|archive)."""
    override = str(load_settings().get(STAGE_KEYS.get(stage, "")) or "").strip()
    if override:
        return _expand(override)
    return results_root() / STAGE_SUBDIRS[stage]


def output_dir() -> str:
    """Служебные файлы приложения (кэш найденного, чекпоинты, история)."""
    p = user_dir() / "output"
    p.mkdir(exist_ok=True)
    return str(p)


def raw_dir() -> str:
    """Stage-1 raw data: <папка результатов>/raw/ — всё собранное без фильтров."""
    p = stage_dir("raw")
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def processed_dir() -> str:
    """Stage-2 output: <папка результатов>/processed/ — по форматам."""
    p = stage_dir("processed")
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def archive_root() -> str:
    """<папка результатов>/_archive/ — корень всех датированных архивов."""
    return str(stage_dir("archive"))


def archive_dir() -> str:
    """Архив: <папка результатов>/_archive/YYYY-MM-DD/."""
    p = stage_dir("archive") / date.today().isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def output_dirs() -> dict:
    """Все три папки результатов сразу (для API, логов и проверок)."""
    return {
        "root": str(results_root()),
        "raw": raw_dir(),
        "processed": processed_dir(),
        "archive": archive_root(),
    }


def check_dir(path: str) -> str:
    """Создаёт папку и проверяет, что в неё можно писать."""
    try:
        p = _expand(path)
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return f"{exc}"
    return ""


def refresh_output_dirs() -> dict:
    """Перечитать settings.json и раздать новые папки всем модулям. config/state/api/run_manager запоминают папки при импорте, а настройку можно поменять уже во время поиска — поэтому после сохранения (в UI) и на границе каждого города (в парсере) вызывается этот метод."""
    import sys

    dirs = output_dirs()
    targets = {
        "config": {"RESULTS_DIR": dirs["root"], "RAW_DIR": dirs["raw"],
                   "PROCESSED_DIR": dirs["processed"]},
        "yandex_maps_parser.state": {"RESULTS_DIR": dirs["root"], "RAW_DIR": dirs["raw"],
                                    "PROCESSED_DIR": dirs["processed"]},
        "routes.api": {"RESULTS_DIR": dirs["root"]},
        "run_manager": {"RESULTS_DIR": dirs["root"]},
    }
    for mod_name, attrs in targets.items():
        # sys.modules.get, НЕ import_module: в дочернем процессе парсера routes.api ещё не загружен, и import_module тянул бы в child весь Flask-стек ради одного RESULT_DIR.
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr, value in attrs.items():
            if hasattr(mod, attr):
                setattr(mod, attr, value)
    return dirs


def logs_dir() -> str:
    p = user_dir() / "logs"
    p.mkdir(exist_ok=True)
    return str(p)


def env_path() -> Path:
    """Location of the .env file (created on demand by the key-save route)."""
    return user_dir() / ".env"
