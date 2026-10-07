from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.services.notifications import format_notification
from integrations.http import RemoteError
from models.telegram import LeadChannel, Notification
from tests.test_telegram_integration import AUTH, integrated, submission
from workers.notifications import run_once


class FakeTelegram:
    def __init__(self, error=None):
        self.error, self.sent = error, []

    def send_message(self, chat_id, text, **kwargs):
        if self.error:
            raise self.error
        self.sent.append((chat_id, text))
        return {'message_id': len(self.sent)}


def queue_two(app, lead_data):
    client = app.test_client()
    lead_id = client.post('/integrations/telegram/leads', headers=AUTH, json=submission(lead_data)).json['id']
    for status in ('in_progress', 'closed'):
        client.patch(f'/lead/{lead_id}/status', json={'status': status})
    return app.extensions['db_session_factory']


def test_retry_after_preserves_order_and_event_time(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    now = datetime(2030, 1, 1)
    telegram = FakeTelegram(RemoteError(429, 120))
    assert run_once(factory, telegram, now=now)
    assert not run_once(factory, telegram, now=now + timedelta(seconds=119))
    telegram.error = None
    assert run_once(factory, telegram, now=now + timedelta(seconds=120))
    assert run_once(factory, telegram, now=now + timedelta(seconds=120))
    assert 'В работе' in telegram.sent[0][1] and 'Закрыта' in telegram.sent[1][1]
    assert '2030' not in telegram.sent[0][1]
    with factory() as session:
        items = list(session.scalars(select(Notification).order_by(Notification.id)))
        assert [item.attempts for item in items] == [2, 1]
        assert all(item.state == 'sent' and item.telegram_message_id for item in items)


def test_network_backoff_and_lease_recovery(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    now = datetime(2030, 1, 1)
    assert run_once(factory, FakeTelegram(RemoteError()), now=now)
    assert not run_once(factory, FakeTelegram(), now=now + timedelta(seconds=9))
    with factory.begin() as session:
        item = session.scalar(select(Notification).order_by(Notification.id))
        item.state, item.lease_until = 'processing', now + timedelta(seconds=60)
    assert not run_once(factory, FakeTelegram(), now=now + timedelta(seconds=59))
    sender = FakeTelegram()
    assert run_once(factory, sender, now=now + timedelta(seconds=61))
    assert len(sender.sent) == 1


def test_blocking_stops_all_chat_retries(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    assert run_once(factory, FakeTelegram(RemoteError(403)), now=datetime(2030, 1, 1))
    assert not run_once(factory, FakeTelegram(), now=datetime(2031, 1, 1))
    with factory() as session:
        assert session.scalar(select(LeadChannel)).subscription == 'blocked'
        assert all(item.state == 'blocked' for item in session.scalars(select(Notification)))
    integrated.test_client().patch('/lead/1/status', json={'status': 'new'})
    with factory() as session:
        assert len(list(session.scalars(select(Notification)))) == 2


def test_format_timezone_and_unknown_old_time():
    event = SimpleNamespace(lead_id=42, kind='transition', status='in_progress', event_at=datetime(2026, 10, 7, 13, 35))
    assert 'Взята в работу: 07.10.2026, 16:35 МСК' in format_notification(event, 'Europe/Moscow')
    assert '13:35 UTC (UTC+0000)' in format_notification(event, 'UTC')
    event.kind, event.event_at = 'snapshot', None
    text = format_notification(event, 'Europe/Moscow')
    assert 'Текущий статус' in text and 'не зафиксировано' in text


def test_worker_network_is_outside_transaction(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    class Sender(FakeTelegram):
        def send_message(self, *args, **kwargs):
            with factory.begin() as session:
                from database.repositories.leads import lock_writes
                lock_writes(session)
            return super().send_message(*args, **kwargs)
    assert run_once(factory, Sender(), now=datetime(2030, 1, 1))


def test_html_reports_delivery_result(integrated, lead_data):
    factory = queue_two(integrated, lead_data)
    client = integrated.test_client()
    assert 'Доставка: ожидает' in client.get('/').get_data(as_text=True)
    sender = FakeTelegram()
    assert run_once(factory, sender, now=datetime(2030, 1, 1))
    sender.error = RemoteError(500)
    assert run_once(factory, sender, now=datetime(2030, 1, 1))
    assert 'ошибка, повтор ожидает' in client.get('/').get_data(as_text=True)
    sender.error = None
    assert run_once(factory, sender, now=datetime(2031, 1, 1))
    assert 'Доставка: отправлено' in client.get('/').get_data(as_text=True)


def test_binding_sends_current_status_without_old_history(integrated, lead_data):
    client = integrated.test_client()
    created = client.post('/lead', json=lead_data).json
    for status in ('in_progress', 'closed'):
        assert client.patch(f'/lead/{created["id"]}/status', json={'status': status}).status_code == 200
    result = client.post('/integrations/telegram/bind', headers=AUTH, json={
        'code': created['telegram_subscription_url'].split('start=')[1],
        'request_id': 'snapshot-12345678901234', 'telegram_user_id': 123, 'telegram_chat_id': 123,
    })
    assert result.status_code == 200
    sender = FakeTelegram()
    factory = integrated.extensions['db_session_factory']
    assert run_once(factory, sender, now=datetime(2030, 1, 1))
    assert not run_once(factory, sender, now=datetime(2030, 1, 1))
    assert 'Текущий статус: Закрыта' in sender.sent[0][1]
    assert 'Время изменения:' in sender.sent[0][1]
