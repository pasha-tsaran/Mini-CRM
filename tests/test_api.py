from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from models.lead import Lead


def test_create_is_committed_and_has_server_fields(client, app, lead_data):
    response = client.post("/lead", json=lead_data)
    assert response.status_code == 201
    result = response.get_json()
    assert {key: result[key] for key in lead_data} == lead_data
    assert result["status"] == "new"
    assert isinstance(result["id"], int)
    assert datetime.fromisoformat(result["created_at"]).utcoffset() == timedelta(0)
    with app.extensions["db_session_factory"]() as session:
        saved = session.get(Lead, result["id"])
        assert saved.name == lead_data["name"]
        assert saved.phone == lead_data["phone"]
        assert saved.message == lead_data["message"]


@pytest.mark.parametrize("phone", ["+79991234567", "89991234567", "+7 999 123-45-67", "8 (999) 123-45-67"])
def test_normalizes_phone_and_trims_text(client, lead_data, phone):
    response = client.post("/lead", json={**lead_data, "phone": phone, "name": "  Иван\t", "message": "\nПривет  "})
    assert response.status_code == 201
    assert response.json["phone"] == "+79991234567"
    assert response.json["name"] == "Иван"
    assert response.json["message"] == "Привет"


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", " \t\n"), ("name", "я" * 101),
    ("message", ""), ("message", " \n"), ("message", "я" * 2001),
    ("phone", "+7abc9991234567"), ("phone", "+79991234567 доб.1"),
    ("phone", "+19991234567"), ("phone", "79991234567"),
    ("phone", "+7999123456"), ("phone", "+799912345678"),
    ("phone", "+7(9991234567"), ("phone", "+7９９９１２３４５６７"),
    ("phone", "+7 999 123/45/67"), ("phone", ""),
] + [(field, value) for field in ("name", "phone", "message") for value in (None, 123, True, [], {})])
def test_rejects_invalid_fields_without_writing(client, lead_data, field, value):
    response = client.post("/lead", json={**lead_data, field: value})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert response.json["error"]["details"][0]["field"] == field
    assert client.get("/leads").json["total"] == 0


@pytest.mark.parametrize("field", ["name", "phone", "message"])
def test_required_fields(client, lead_data, field):
    del lead_data[field]
    response = client.post("/lead", json=lead_data)
    assert response.status_code == 422
    assert response.json["error"]["details"][0]["code"] == "missing"


@pytest.mark.parametrize("field,value", [("id", 1), ("status", "closed"), ("created_at", "2026-01-01"), ("extra", "x")])
def test_forbids_unknown_and_server_fields(client, lead_data, field, value):
    assert client.post("/lead", json={**lead_data, field: value}).status_code == 422


@pytest.mark.parametrize("payload", ["null", "[]", '"text"', "12"])
def test_requires_json_object(client, payload):
    assert client.post("/lead", data=payload, content_type="application/json").status_code == 422


def test_accepts_length_boundaries_and_duplicate_phones(client, lead_data):
    for length in (1, 100):
        assert client.post("/lead", json={**lead_data, "name": "я" * length, "message": "я" * (20 * length)}).status_code == 201
    assert client.get("/leads").json["total"] == 2


@pytest.mark.parametrize("path,method", [("/lead", "post"), ("/lead/1/status", "patch")])
def test_json_and_content_type_errors(client, path, method):
    send = getattr(client, method)
    assert send(path, data="{", content_type="application/json").status_code == 400
    assert send(path, data="", content_type="application/json").status_code == 400
    response = send(path, data="{}", content_type="text/plain")
    assert response.status_code == 415
    assert response.json["error"]["code"] == "unsupported_media_type"
    assert send(path, data="{}").status_code == 415


def test_list_defaults(client):
    assert client.get("/leads").json == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_pagination_and_deterministic_sort(client, app, lead_data):
    ids = [client.post("/lead", json=lead_data).json["id"] for _ in range(3)]
    with app.extensions["db_session_factory"].begin() as session:
        for lead in session.scalars(select(Lead)):
            lead.created_at = datetime(2026, 1, 1)
        session.get(Lead, ids[0]).created_at = datetime(2026, 1, 2)
    assert [item["id"] for item in client.get("/leads").json["items"]] == [ids[0], ids[2], ids[1]]
    page = client.get("/leads?limit=1&offset=1").json
    assert page == {"items": [client.get("/leads").json["items"][1]], "total": 3, "limit": 1, "offset": 1}
    assert client.get("/leads?offset=999999999999999999999999").json["items"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x", "limit=1.0", "limit=", "offset=-1", "offset=1.5", "offset=x", "offset=", "limit=1&limit=2", "unknown=1"])
def test_invalid_pagination(client, query):
    assert client.get("/leads?" + query).status_code == 422


def test_pagination_boundaries(client):
    assert client.get("/leads?limit=100&offset=0").status_code == 200


def test_all_statuses_persist(client, lead_data):
    created = client.post("/lead", json=lead_data).json
    for status in ("in_progress", "closed", "rejected", "new", "new"):
        response = client.patch(f"/lead/{created['id']}/status", json={"status": status})
        assert response.status_code == 200
        assert response.json == {**created, "status": status}
        assert client.get("/leads").json["items"][0]["status"] == status


@pytest.mark.parametrize("payload", [{}, {"status": "other"}, {"status": None}, {"status": 1}, {"status": "closed", "name": "Другой"}])
def test_invalid_status_does_not_change_lead(client, lead_data, payload):
    created = client.post("/lead", json=lead_data).json
    assert client.patch(f"/lead/{created['id']}/status", json=payload).status_code == 422
    assert client.get("/leads").json["items"] == [created]


@pytest.mark.parametrize("lead_id", ["1", "0", "999999999999999999999999"])
def test_unknown_lead(client, lead_id):
    response = client.patch(f"/lead/{lead_id}/status", json={"status": "closed"})
    assert response.status_code == 404
    assert response.json["error"]["code"] == "lead_not_found"


def test_unknown_route_and_method(client):
    assert client.get("/missing").json["error"]["code"] == "not_found"
    response = client.delete("/lead")
    assert response.status_code == 405
    assert "POST" in response.headers["Allow"]
