from zoneinfo import ZoneInfo

from flask import Flask

from api.leads import blueprint as leads_blueprint
from api.telegram import blueprint as telegram_blueprint
from app.cache.statistics import StatisticsCache
from app.config import PROJECT_ROOT, load_config
from app.errors import register_error_handlers
from app.health import blueprint as health_blueprint
from app.views import blueprint as views_blueprint
from database.session import init_app


def create_app(config: dict | None = None) -> Flask:
    app = Flask(
        __name__, template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config.from_mapping(load_config())
    if config is not None:
        app.config.update(config)
    app.json.ensure_ascii = False
    app.extensions["ui_timezone"] = ZoneInfo(app.config["UI_TIMEZONE"])
    app.extensions["statistics_cache"] = StatisticsCache()
    init_app(app)
    app.register_blueprint(leads_blueprint)
    app.register_blueprint(telegram_blueprint)
    app.register_blueprint(views_blueprint)
    app.register_blueprint(health_blueprint)
    register_error_handlers(app)
    return app
