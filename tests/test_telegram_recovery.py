import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from bot.handlers import DialogHandler
from bot.main import send_reply
from bot.state import StateStore
from integrations.http import RemoteError
from models.telegram import Notification, StatusEvent
from tests.test_bot import LocalCRM, deliver, fill_draft, update
from tests.test_telegram_integration import AUTH, integrated, submission
from tests.test_telegram_worker import FakeTelegram, queue_two
from workers.notifications import run_once


def test_existing_database_backup_and_repeat_upgrade(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE leads (id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL, created_at DATETIME NOT NULL)')
        connection.execute("INSERT INTO leads VALUES (42, 'Иван', '+79991234567', 'Старая заявка', 'in_progress', '2026-01-01 12:00:00')")
    config = {'TESTING': True, 'DATABASE_PATH': path, 'CRM_BOT_API_TOKEN': '', 'TELEGRAM_BOT_USERNAME': ''}
    for _ in range(2):
        app = create_app(config)
        try:
            data = app.test_client().get('/leads').json
            assert data['total'] == 1 and data['items'][0]['id'] == 42
            with app.extensions['db_session_factory']() as session:
                assert list(session.scalars(select(StatusEvent))) == []
                assert list(session.scalars(select(Notification))) == []
        finally:
            app.extensions['database_engine'].dispose()
    backups = list((tmp_path / 'backups').glob('*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute('SELECT message FROM leads').fetchone()[0] == 'Старая заявка'
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE name='notification_outbox'").fetchone()[0] == 0


def test_simultaneous_submission_creates_one_lead(integrated, lead_data):
    payload = submission(lead_data)
    def submit(_):
        with integrated.test_client() as client:
            result = client.post('/integrations/telegram/leads', json=payload, headers=AUTH)
            return result.status_code, result.json['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert results == [(201, 1)] * 4
    assert integrated.test_client().get('/leads').json['total'] == 1


def test_binding_request_id_cannot_be_reused_for_another_lead(integrated, lead_data):
    client = integrated.test_client()
    codes = [client.post('/lead', json=lead_data).json['telegram_subscription_url'].split('start=')[1] for _ in range(2)]
    payload = {'code': codes[0], 'request_id': 'same-binding-123456789', 'telegram_user_id': 123, 'telegram_chat_id': 123}
    assert client.post('/integrations/telegram/bind', json=payload, headers=AUTH).status_code == 200
    assert client.post('/integrations/telegram/bind', json={**payload, 'code': codes[1]}, headers=AUTH).status_code == 409


def test_queue_survives_app_restart_and_event_key_is_unique(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    with factory() as session:
        item = session.scalar(select(Notification))
        duplicate = {key: getattr(item, key) for key in ('event_key', 'lead_id', 'chat_id', 'status', 'event_at', 'next_attempt_at')}
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Notification(**duplicate))
    integrated.extensions['database_engine'].dispose()
    restored = create_app(dict(integrated.config))
    sender = FakeTelegram()
    try:
        factory = restored.extensions['db_session_factory']
        assert run_once(factory, sender, now=datetime(2030, 1, 1))
        assert run_once(factory, sender, now=datetime(2030, 1, 1))
        assert not run_once(factory, sender, now=datetime(2030, 1, 1))
        assert len(sender.sent) == 2
    finally:
        restored.extensions['database_engine'].dispose()


def test_crash_after_crm_commit_before_inbox_completion(integrated, tmp_path, monkeypatch):
    path = tmp_path / 'bot.sqlite3'
    store = StateStore(path)
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    fill_draft(store, handler)
    store.receive([update(6, 'Отправить')])
    def crash(*args, **kwargs):
        raise RuntimeError('simulated process crash')
    monkeypatch.setattr(store, 'complete', crash)
    with pytest.raises(RuntimeError):
        handler.process_next()
    assert integrated.test_client().get('/leads').json['total'] == 1
    restored = StateStore(path)
    assert DialogHandler(restored, LocalCRM(integrated), 'example_test_bot').process_next()
    assert restored.dialog(123)['step'] == 'done'
    assert integrated.test_client().get('/leads').json['total'] == 1


def test_unavailable_crm_keeps_draft_without_success(integrated, tmp_path):
    class OfflineCRM:
        def create_lead(self, data):
            raise RemoteError()
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, OfflineCRM(), 'example_test_bot')
    fill_draft(store, handler)
    deliver(store, handler, 6, 'Отправить')
    assert integrated.test_client().get('/leads').json['total'] == 0
    assert store.dialog(123)['message'] == 'Нужна консультация'
    sender = FakeTelegram()
    while send_reply(store, sender, now=100):
        pass
    assert not any('зарегистрирована' in text for _, text in sender.sent)
    handler.crm = LocalCRM(integrated)
    deliver(store, handler, 7, 'Повторить отправку')
    assert store.dialog(123)['step'] == 'done'


def test_bot_reply_retry_restart_and_order(tmp_path):
    path = tmp_path / 'bot.sqlite3'
    store = StateStore(path)
    for number in (1, 2):
        store.complete(number, chat_id=123, reply={'text': f'Ответ {number}'})
    assert send_reply(store, FakeTelegram(RemoteError(429, 90)), now=100)
    restored = StateStore(path)
    sender = FakeTelegram()
    assert not send_reply(restored, sender, now=189)
    assert send_reply(restored, sender, now=190)
    assert send_reply(restored, sender, now=190)
    assert [text for _, text in sender.sent] == ['Ответ 1', 'Ответ 2']


def test_bot_cannot_look_up_leads_or_forge_recipient(integrated, lead_data):
    client = integrated.test_client()
    client.post('/lead', json=lead_data)
    for route in ('/integrations/telegram/leads/1', '/integrations/telegram/leads?phone=+79991234567', '/integrations/telegram/bind/1'):
        assert client.get(route, headers=AUTH).status_code in (404, 405)
    for extra in ({'telegram_chat_id': 123}, {'telegram_user_id': 123}, {'source': 'telegram'}):
        assert client.post('/lead', json={**lead_data, **extra}).status_code == 422
    assert client.post('/integrations/telegram/leads', json=submission(lead_data, telegram_chat_id=456), headers=AUTH).status_code == 422
    assert client.get('/leads').json['total'] == 1
