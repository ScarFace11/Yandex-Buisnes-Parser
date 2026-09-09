"""Flask application entry point.

All routes are organized in blueprints under routes/.
Run management is in run_manager.py.

Supports running from source (python app.py) and as a frozen PyInstaller
bundle (paths.py resolves templates/static/writable dirs accordingly).
"""
import sys
import multiprocessing

# MUST run before anything else when frozen: without this, a PyInstaller exe
# relaunches the whole application for every multiprocessing child.
multiprocessing.freeze_support()

import os

# Frozen exe: chdir to a writable dir so relative paths (output/, logs/)
# land next to the .exe instead of the read-only extraction dir.
import paths

if paths.is_frozen():
    os.chdir(paths.user_dir())

from flask import Flask

from routes.parser import bp as parser_bp
from routes.sender import bp as sender_bp
from routes.api   import bp as api_bp
from routes.public_api import bp as public_api_bp
from routes.update  import bp as update_bp


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=paths.template_dir(),
        static_folder=paths.static_dir(),
    )
    try:
        from config import APP_VERSION
    except ImportError:
        APP_VERSION = "dev"
    app.config["APP_VERSION"] = APP_VERSION
    app.jinja_env.globals["APP_VERSION"] = APP_VERSION
    app.register_blueprint(parser_bp)
    app.register_blueprint(sender_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(public_api_bp)
    app.register_blueprint(update_bp)
    return app


app = create_app()

# Cleanup old log files on startup
try:
    from run_logger import cleanup_old_logs
    deleted = cleanup_old_logs()
    if deleted:
        print(f"  🧹 Удалено {deleted} старых лог-файлов")
except Exception:
    pass

# Cleanup expired cache files on startup
try:
    from yandex_maps_parser.cache import cleanup_expired as _cache_cleanup
    removed = _cache_cleanup()
    if removed:
        print(f"  🧹 Удалено {removed} устаревших кэш-файлов")
except Exception:
    pass

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
