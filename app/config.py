import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    """Читать локальные настройки, сохраняя приоритет окружения процесса."""
    load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")


def database_path(value: str | Path) -> Path:
    """Относительные пути всегда отсчитываются от корня проекта."""
    path = Path(value).expanduser()
    return (PROJECT_ROOT / path).resolve()


def load_config() -> dict:
    load_environment()
    return {
        "DATABASE_PATH": os.environ.get("DATABASE_PATH", "instance/crm.sqlite3"),
        "UI_TIMEZONE": os.environ.get("UI_TIMEZONE", "Europe/Moscow"),
        "TELEGRAM_BOT_USERNAME": os.environ.get("TELEGRAM_BOT_USERNAME", "").lstrip('@'),
        "CRM_BOT_API_TOKEN": os.environ.get("CRM_BOT_API_TOKEN", ""),
    }
