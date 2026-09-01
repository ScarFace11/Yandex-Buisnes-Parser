"""Flask application entry point.

All routes are organized in blueprints under routes/.
Run management is in run_manager.py.
"""
import sys
import multiprocessing

# On Windows, ensure multiprocessing uses the correct Python executable.
if sys.platform == "win32":
    multiprocessing.set_executable(sys.executable)

from flask import Flask

from routes.parser import bp as parser_bp
from routes.sender import bp as sender_bp
from routes.api   import bp as api_bp
from routes.public_api import bp as public_api_bp


def create_app() -> Flask:
    app = Flask(__name__)
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
