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

Usage:
    import paths
    app = Flask(__name__, template_folder=paths.template_dir(), static_folder=paths.static_dir())
    config.OUTPUT_DIR = paths.output_dir()   # ... or import paths wherever a dir is needed
"""
import sys
from pathlib import Path


APP_SLUG = "YandexBusinessParser"


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


def output_dir() -> str:
    p = user_dir() / "output"
    p.mkdir(exist_ok=True)
    return str(p)


def raw_dir() -> str:
    """Stage-1 raw data: output/raw/ — everything collected, unfiltered."""
    p = user_dir() / "output" / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def processed_dir() -> str:
    """Stage-2 output: output/processed/ — filtered data per format."""
    p = user_dir() / "output" / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def archive_dir() -> str:
    """Archive for raw files: output/_archive/YYYY-MM-DD/."""
    from datetime import date
    p = user_dir() / "output" / "_archive" / date.today().isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def logs_dir() -> str:
    p = user_dir() / "logs"
    p.mkdir(exist_ok=True)
    return str(p)


def env_path() -> Path:
    """Location of the .env file (created on demand by the key-save route)."""
    return user_dir() / ".env"


def sender_config_path() -> Path:
    return user_dir() / "sender_config.json"
