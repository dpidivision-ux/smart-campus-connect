import os
import secrets

from flask import Flask

from . import db as dbmod


def create_app(db_path=None):
    app = Flask(__name__)
    app.secret_key = os.environ.get("SCC_SECRET") or secrets.token_hex(32)
    app.config["DB_PATH"] = db_path or os.environ.get(
        "SCC_DB", os.path.join(os.path.dirname(__file__), "..", "campus.db"))
    dbmod.init_db(app.config["DB_PATH"])

    from .routes import bp
    app.register_blueprint(bp)
    return app
