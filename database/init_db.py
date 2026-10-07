from sqlalchemy import Engine

from database.base import Base
from models.lead import Lead  # noqa: F401 — регистрирует таблицу в metadata
from models import telegram  # noqa: F401 — новые таблицы интеграции
from database.migrations import upgrade


def init_db(engine: Engine) -> None:
    """Создать недостающие таблицы без удаления существующих данных."""
    upgrade(engine)
