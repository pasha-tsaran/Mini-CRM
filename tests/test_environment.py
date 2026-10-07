from app import config
from bot.config import require_settings


def test_dotenv_is_loaded_from_project_and_preserves_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CRM_BOT_API_TOKEN", raising=False)
    monkeypatch.setenv("UI_TIMEZONE", "UTC")
    (tmp_path / ".env").write_text(
        "CRM_BOT_API_TOKEN=test-only-secret\nUI_TIMEZONE=Europe/Moscow\n",
        encoding="utf-8-sig",
    )
    values = config.load_config()
    assert values["CRM_BOT_API_TOKEN"] == "test-only-secret"
    assert values["UI_TIMEZONE"] == "UTC"
    assert require_settings(("CRM_BOT_API_TOKEN",))["CRM_BOT_API_TOKEN"] == "test-only-secret"


def test_missing_dotenv_is_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("CRM_BOT_API_TOKEN", raising=False)
    assert config.load_config()["CRM_BOT_API_TOKEN"] == ""
