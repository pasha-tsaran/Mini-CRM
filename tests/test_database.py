from datetime import datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, database_path
from app.main import create_app
from app.schemas.lead import LeadCreate, LeadStatusUpdate
from app.services import leads as service
from models.lead import Lead


@pytest.mark.parametrize("field,value", [
    ("name", None), ("phone", None), ("message", None),
    ("status", None), ("created_at", None),
    ("name", ""), ("name", "   "), ("name", "x" * 101),
    ("message", ""), ("message", "   "), ("message", "x" * 2001),
    ("phone", "89991234567"), ("phone", "+7abcdefghij"),
    ("phone", "+799912345678"), ("status", "unknown"),
])
def test_database_rejects_invalid_direct_writes(app, lead_data, field, value):
    values = {**lead_data, "status": "new", "created_at": datetime(2026, 1, 1), field: value}
    with app.extensions["db_session_factory"]() as session:
        with pytest.raises(IntegrityError), session.begin():
            session.execute(insert(Lead).values(**values))
        assert session.scalar(select(Lead)) is None


def test_database_defaults(app, lead_data):
    with app.extensions["database_engine"].begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO leads (name, phone, message) VALUES (?, ?, ?)",
            tuple(lead_data.values()),
        )
    with app.extensions["db_session_factory"]() as session:
        lead = session.scalar(select(Lead))
        assert lead.status == "new"
        assert isinstance(lead.created_at, datetime)


def test_file_persists_after_app_recreation(app, client, lead_data):
    created = client.post("/lead", json=lead_data).json
    app.extensions["database_engine"].dispose()
    reopened = create_app({"TESTING": True, "DATABASE_PATH": app.config["DATABASE_PATH"]})
    try:
        assert reopened.test_client().get("/leads").json["items"] == [created]
    finally:
        reopened.extensions["database_engine"].dispose()


def test_relative_path_is_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert database_path("instance/crm.sqlite3") == PROJECT_ROOT / "instance" / "crm.sqlite3"
    assert database_path(tmp_path / "absolute.sqlite3") == tmp_path / "absolute.sqlite3"


def test_config_reads_environment_at_factory_call(tmp_path, monkeypatch):
    path = tmp_path / "from-environment.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    app = create_app({"TESTING": True})
    try:
        assert path.is_file()
        assert app.test_client().get("/leads").json["total"] == 0
    finally:
        app.extensions["database_engine"].dispose()


@pytest.mark.parametrize("operation", ["create", "status"])
def test_commit_failure_rolls_back_and_allows_session_reuse(app, lead_data, operation):
    with app.extensions["db_session_factory"]() as session:
        created = service.create_lead(session, LeadCreate(**lead_data))
        rolled_back = Mock()
        event.listen(session, "after_rollback", rolled_back)

        def fail_commit(session):
            raise RuntimeError("simulated commit failure")

        event.listen(session, "before_commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            if operation == "create":
                service.create_lead(session, LeadCreate(**lead_data))
            else:
                service.update_status(session, created.id, LeadStatusUpdate(status="closed"))
        assert rolled_back.call_count == 1
        assert not session.in_transaction()
        event.remove(session, "before_commit", fail_commit)
        with app.extensions["db_session_factory"]() as observer:
            saved = list(observer.scalars(select(Lead)))
            assert len(saved) == 1
            assert saved[0].status == "new"
        assert service.create_lead(session, LeadCreate(**lead_data)).id > created.id


def test_flush_failure_rolls_back(app, lead_data, monkeypatch):
    from database.repositories import leads as repository

    original_add = repository.add

    def invalid_add(session, **data):
        return original_add(session, **{**data, "name": "x" * 101})

    monkeypatch.setattr(repository, "add", invalid_add)
    with app.extensions["db_session_factory"]() as session:
        with pytest.raises(IntegrityError):
            service.create_lead(session, LeadCreate(**lead_data))
        assert not session.in_transaction()
        assert session.scalar(select(Lead)) is None


def test_failed_http_write_returns_safe_500_and_keeps_database_empty(client, lead_data):
    def fail_commit(session):
        raise RuntimeError("SECRET SQL INSERT INTO leads /private/database.sqlite3")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post("/lead", json=lead_data)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 500
    assert response.json == {"error": {"code": "internal_error", "message": "Внутренняя ошибка сервера."}}
    assert client.get("/leads").json["total"] == 0


def test_separate_session_for_every_request_and_guaranteed_close(app, lead_data):
    sessions = []

    class TrackingSession(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed = False
            sessions.append(self)

        def close(self):
            super().close()
            self.closed = True

    # Existing factory is captured by the request hook; configure its session type.
    factory = app.extensions["db_session_factory"]
    factory.class_ = TrackingSession
    client = app.test_client()
    assert client.post("/lead", json=lead_data).status_code == 201
    assert client.post("/lead", json={}).status_code == 422
    assert client.post("/lead", data="{", content_type="application/json").status_code == 400
    assert client.patch("/lead/99/status", json={"status": "closed"}).status_code == 404
    assert client.get("/leads").status_code == 200
    assert client.get("/missing").status_code == 404
    assert len(sessions) == 6
    assert len({id(session) for session in sessions}) == 6
    assert all(session.closed for session in sessions)
