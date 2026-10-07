from datetime import datetime

import pytest
from sqlalchemy import event, select

from app.main import create_app
from models.telegram import BindingCode, LeadChannel, Notification, StatusEvent


@pytest.fixture
def integrated(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE_PATH': tmp_path / 'crm.sqlite3',
                      'CRM_BOT_API_TOKEN': 'test-secret', 'TELEGRAM_BOT_USERNAME': 'example_test_bot'})
    yield app
    app.extensions['database_engine'].dispose()


AUTH = {'Authorization': 'Bearer test-secret'}


def submission(lead_data, **changes):
    return {**lead_data, 'submission_id': 'draft-1234567890123456',
            'telegram_user_id': 123, 'telegram_chat_id': 123, **changes}


def test_integration_requires_auth_before_json(integrated):
    client = integrated.test_client()
    for headers in ({}, {'Authorization': 'Bearer wrong'}):
        assert client.post('/integrations/telegram/leads', data='{', headers=headers).status_code == 401


def test_idempotency_cache_and_conflict(integrated, lead_data):
    client = integrated.test_client()
    assert client.get('/stats').json['total'] == 0
    data = submission(lead_data)
    first = client.post('/integrations/telegram/leads', json=data, headers=AUTH)
    assert first.status_code == 201
    again = client.post('/integrations/telegram/leads', json=data, headers=AUTH)
    assert again.status_code == 201
    assert again.json == first.json
    assert client.get('/stats').json['total'] == 1
    conflict = client.post('/integrations/telegram/leads', json={**data, 'message': 'Другое'}, headers=AUTH)
    assert conflict.status_code == 409
    assert client.post('/lead', json=data).status_code == 422
    with integrated.extensions['db_session_factory']() as session:
        channel = session.get(LeadChannel, first.json['id'])
        assert channel.source == 'telegram' and channel.chat_id == 123


def test_one_time_binding_and_no_token_in_list(integrated, lead_data):
    client = integrated.test_client()
    created = client.post('/lead', json=lead_data).json
    url = created['telegram_subscription_url']
    token = url.split('start=')[1]
    assert len(token) <= 64
    assert token not in client.get('/leads').get_data(as_text=True)
    with integrated.extensions['db_session_factory']() as session:
        assert session.scalar(select(BindingCode)).token_hash != token
    data = {'code': token, 'telegram_user_id': 123, 'telegram_chat_id': 123,
            'request_id': 'binding-1234567890123456'}
    result = client.post('/integrations/telegram/bind', json=data, headers=AUTH)
    assert result.status_code == 200
    assert result.json['id'] == created['id']
    assert client.post('/integrations/telegram/bind', json=data, headers=AUTH).json == result.json
    assert client.post('/integrations/telegram/bind', json={**data, 'request_id': 'other-1234567890123456'}, headers=AUTH).status_code == 409
    assert client.post('/integrations/telegram/bind', json={**data, 'telegram_user_id': 456, 'telegram_chat_id': 456}, headers=AUTH).status_code == 409
    with integrated.extensions['db_session_factory']() as session:
        assert len(list(session.scalars(select(Notification)))) == 1


def test_expired_and_unknown_binding(integrated, lead_data):
    client = integrated.test_client()
    token = client.post('/lead', json=lead_data).json['telegram_subscription_url'].split('start=')[1]
    with integrated.extensions['db_session_factory'].begin() as session:
        session.scalar(select(BindingCode)).expires_at = datetime(2000, 1, 1)
    for code in (token, 'x' * 43):
        assert client.post('/integrations/telegram/bind', headers=AUTH, json={
            'code': code, 'request_id': 'binding-1234567890123456',
            'telegram_user_id': 123, 'telegram_chat_id': 123,
        }).status_code == 409


def test_status_event_atomic_and_noop(integrated, lead_data):
    client = integrated.test_client()
    lead_id = client.post('/integrations/telegram/leads', json=submission(lead_data), headers=AUTH).json['id']
    for status in ('new', 'in_progress', 'in_progress', 'new', 'in_progress'):
        assert client.patch(f'/lead/{lead_id}/status', json={'status': status}).status_code == 200
    with integrated.extensions['db_session_factory']() as session:
        events = list(session.scalars(select(StatusEvent).order_by(StatusEvent.id)))
        notifications = list(session.scalars(select(Notification)))
        assert [(e.old_status, e.new_status) for e in events] == [('new', 'in_progress'), ('in_progress', 'new'), ('new', 'in_progress')]
        assert len(notifications) == 3
        assert notifications[0].event_at == events[0].changed_at
    def fail(session):
        raise RuntimeError('failed commit')
    factory = integrated.extensions['db_session_factory']
    event.listen(factory.class_, 'before_commit', fail)
    try:
        assert client.patch(f'/lead/{lead_id}/status', json={'status': 'closed'}).status_code == 500
    finally:
        event.remove(factory.class_, 'before_commit', fail)
    with factory() as session:
        assert len(list(session.scalars(select(StatusEvent)))) == 3
        assert len(list(session.scalars(select(Notification)))) == 3
