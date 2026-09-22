"""
Path resolution for frozen (PyInstaller) and normal (source) runs.

Three kinds of locations:
- RESOURCE_DIR — read-only files bundled with the app (templates/, static/).
  In a PyInstaller bundle this is the extraction dir (sys._MEIPASS); in a
  source checkout it is the project root.
- USER_DIR — writable location for user data (output/, logs/, .env,
  sender_config.json). When frozen this is the folder containing the .exe
  so data survives between launches; on macOS the .app bundle itself may sit
  in a read-only /Applications, so data moves to
  ~/Library/Application Support/<App> (macOS convention); in a source
  checkout it is the project root (current behaviour, nothing changes).
- CONFIG_PATH — the .env file; same as USER_DIR but resolved before config
  import, so env vars load even in the frozen extraction dir.

Результаты можно держать отдельно от служебных файлов: папка из
settings.json (ключ «results_root») принимает raw/, processed/ и _archive/,
а кэш найденного, чекпоинты, история поиска и отметки «просмотрено» остаются
в USER_DIR/output/. Пустая настройка = прежнее поведение (всё в output/).

Usage:
    import paths
    app = Flask(__name__, template_folder=paths.template_dir(), static_folder=paths.static_dir())
    config.OUTPUT_DIR = paths.output_dir()   # ... or import paths wherever a dir is needed
"""
import json
import os
import sys
from datetime import date
from pathlib import Path


APP_SLUG = "YandexBusinessParser"

# Служебный файл настроек приложения (не в git): папка результатов и
# переопределения по этапам.
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


def resource_dir() -> Path:
    """Read-only bundled resources (templates/, static/)."""
    if not is_frozen():
        return Path(__file__).resolve().parent
    # PyInstaller onefile extracts to _MEIPASS; onedir puts data files next to
    # the executable under _internal/. In a macOS .app bundle the same files
    # may end up under Contents/Frameworks (_MEIPASS) or Contents/Resources,
    # and which one is not worth guessing — the folder that actually holds
    # templates/ wins.
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
            # .app обычно лежит в /Applications (только для чтения) — данные
            # уходят в стандартную папку macOS, как у любого десктоп-приложения.
            return Path.home() / "Library" / "Application Support" / _app_slug()
        return _exe_dir()
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Writable location for user data (output/, logs/, .env, configs).

    The folder is created on first access so first launch of the .exe
    never fails with a missing-directory error.
    """
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
    """Атомарно дописывает ключи в settings.json.

    Файл читают оба процесса (родитель и парсер), поэтому запись идёт через
    временный файл + os.replace — иначе парсер может поймать полуфайл.
    """
    data = load_settings()
    data.update(values or {})
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
    """Папка этапа (raw|processed|archive).

    Без настройки — подпапка внутри корня результатов (raw/, processed/,
    _archive/). Если для этапа задали свою папку (расширенный режим), она
    используется как есть — без лишней вложенности.
    """
    override = str(load_settings().get(STAGE_KEYS.get(stage, "")) or "").strip()
    if override:
        return _expand(override)
    return results_root() / STAGE_SUBDIRS[stage]


def output_dir() -> str:
    """Служебные файлы приложения (кэш найденного, чекпоинты, история).

    Намеренно НЕ следует за папкой результатов: смена папки не должна
    обнулять кэш «уже найдено» или терять точку продолжения.
    """
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
    """Создаёт папку и проверяет, что в неё можно писать. Возвращает ошибку.

    Пустая строка = всё хорошо. Путь к файлу, отсутствие прав, недоступный
    диск — всё это должна внятно увидеть форма, а не упасть при сохранении.
    """
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
    """Перечитать settings.json и раздать новые папки всем модулям.

    config/state/api/run_manager/sender запоминают папки при импорте, а
    настройку можно поменять уже во время поиска — поэтому после сохранения
    (в UI) и на границе каждого города (в парсере) вызывается этот метод.
    """
    import importlib

    dirs = output_dirs()
    targets = {
        "config": {"RESULTS_DIR": dirs["root"], "RAW_DIR": dirs["raw"],
                   "PROCESSED_DIR": dirs["processed"]},
        "yandex_maps_parser.state": {"RESULTS_DIR": dirs["root"], "RAW_DIR": dirs["raw"],
                                    "PROCESSED_DIR": dirs["processed"]},
        "routes.api": {"RESULTS_DIR": dirs["root"]},
        "run_manager": {"RESULTS_DIR": dirs["root"]},
        "routes.sender": {"RESULTS_DIR": dirs["root"]},
    }
    for mod_name, attrs in targets.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
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


def sender_config_path() -> Path:
    return user_dir() / "sender_config.json"
