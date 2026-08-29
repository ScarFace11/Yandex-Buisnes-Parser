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


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(parser_bp)
    app.register_blueprint(sender_bp)
    app.register_blueprint(api_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
