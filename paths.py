"""
Path resolution for frozen (PyInstaller) and normal (source) runs.

Three kinds of locations:
- RESOURCE_DIR — read-only files bundled with the app (templates/, static/).
  In a PyInstaller bundle this is the extraction dir (sys._MEIPASS); in a
  source checkout it is the project root.
- USER_DIR — writable location for user data (output/, logs/, .env,
  sender_config.json). When frozen this is the folder containing the .exe
  so data survives between launches; in a source checkout it is the project
  root (current behaviour, nothing changes).
- CONFIG_PATH — the .env file; same as USER_DIR but resolved before config
  import, so env vars load even in the frozen extraction dir.

Usage:
    import paths
    app = Flask(__name__, template_folder=paths.template_dir(), static_folder=paths.static_dir())
    config.OUTPUT_DIR = paths.output_dir()   # ... or import paths wherever a dir is needed
"""
import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _exe_dir() -> Path:
    """Folder containing the .exe (or the onedir bundle's _internal parent)."""
    return Path(sys.executable).resolve().parent


def resource_dir() -> Path:
    """Read-only bundled resources (templates/, static/)."""
    if is_frozen():
        # PyInstaller onefile extracts to _MEIPASS; onedir puts data files
        # next to the executable under _internal/.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return _exe_dir() / "_internal"
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Writable location for user data (output/, logs/, .env, configs).

    The folder is created on first access so first launch of the .exe
    never fails with a missing-directory error.
    """
    d = _exe_dir() if is_frozen() else Path(__file__).resolve().parent
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


def logs_dir() -> str:
    p = user_dir() / "logs"
    p.mkdir(exist_ok=True)
    return str(p)


def env_path() -> Path:
    """Location of the .env file (created on demand by the key-save route)."""
    return user_dir() / ".env"


def sender_config_path() -> Path:
    return user_dir() / "sender_config.json"
