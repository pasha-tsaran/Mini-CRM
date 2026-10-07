import pytest

from app.main import create_app


@pytest.fixture(autouse=True)
def isolate_local_secrets(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "DATABASE_PATH": tmp_path / "crm.sqlite3"})
    yield application
    application.extensions["database_engine"].dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def lead_data():
    return {"name": "Иван", "phone": "+79991234567", "message": "Хочу консультацию"}
