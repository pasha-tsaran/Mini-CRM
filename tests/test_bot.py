from bot.handlers import DialogHandler
from bot.main import send_reply
from bot.state import StateStore
from integrations.http import RemoteError
from tests.test_telegram_integration import AUTH, integrated
from tests.test_telegram_worker import FakeTelegram


class LocalCRM:
    def __init__(self, app):
        self.client = app.test_client()
        self.lose_response = False

    def create_lead(self, data):
        result = self.client.post('/integrations/telegram/leads', json=data, headers=AUTH)
        if result.status_code >= 400:
            raise RemoteError(result.status_code)
        if self.lose_response:
            self.lose_response = False
            raise RemoteError()
        return result.json

    def bind(self, data):
        result = self.client.post('/integrations/telegram/bind', json=data, headers=AUTH)
        if result.status_code >= 400:
            raise RemoteError(result.status_code)
        return result.json


def update(number, text=None, user=123, **message):
    return {'update_id': number, 'message': {'from': {'id': user}, 'chat': {'id': user, 'type': 'private'},
                                          **({'text': text} if text is not None else {}), **message}}


def deliver(store, handler, number, text=None, user=123, **message):
    store.receive([update(number, text, user, **message)])
    assert handler.process_next()


def fill_draft(store, handler):
    for number, text in enumerate(('/start', 'Оставить заявку', 'Иван', '8 (999) 123-45-67', 'Нужна консультация'), 1):
        deliver(store, handler, number, text)


def test_full_dialog_and_duplicate_event(integrated, tmp_path):
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    fill_draft(store, handler)
    assert store.dialog(123)['step'] == 'confirm'
    deliver(store, handler, 6, 'Отправить')
    deliver(store, handler, 7, 'Отправить')
    store.receive([update(6, 'Отправить')])
    assert not handler.process_next()
    assert integrated.test_client().get('/leads').json['total'] == 1
    assert store.dialog(123)['result']['id'] == 1
    assert store.offset() == 8
    sender = FakeTelegram()
    while send_reply(store, sender, now=100):
        pass
    assert any('Заявка №1 зарегистрирована.' in text for _, text in sender.sent)


def test_lost_response_restart_and_retry_no_duplicate(integrated, tmp_path):
    path = tmp_path / 'bot.sqlite3'
    store, crm = StateStore(path), LocalCRM(integrated)
    handler = DialogHandler(store, crm, 'example_test_bot')
    fill_draft(store, handler)
    request_id = store.dialog(123)['submission_id']
    crm.lose_response = True
    deliver(store, handler, 6, 'Отправить')
    assert store.dialog(123)['step'] == 'sending'
    store = StateStore(path)
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    assert store.dialog(123)['submission_id'] == request_id
    deliver(store, handler, 7, '/cancel')
    assert store.dialog(123)['step'] == 'sending'
    deliver(store, handler, 8, 'Повторить отправку')
    assert store.dialog(123)['step'] == 'done'
    assert integrated.test_client().get('/leads').json['total'] == 1


def test_contacts_cancel_and_independent_users(integrated, tmp_path):
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    deliver(store, handler, 1, 'Оставить заявку')
    deliver(store, handler, 2, 'Оставить заявку', user=456)
    deliver(store, handler, 3, ' ')
    assert store.dialog(123)['step'] == 'name'
    deliver(store, handler, 4, 'Иван')
    for number, contact in enumerate(({'phone_number': '79991234567'}, {'user_id': 456, 'phone_number': '79991234567'}), 5):
        deliver(store, handler, number, contact=contact)
        assert store.dialog(123)['step'] == 'phone'
    deliver(store, handler, 7, contact={'user_id': 123, 'phone_number': '79991234567'})
    assert store.dialog(123)['phone'] == '+79991234567'
    assert store.dialog(456)['step'] == 'name'
    deliver(store, handler, 8, '/cancel', user=456)
    assert store.dialog(456)['step'] == 'idle'
    assert store.dialog(123)['step'] == 'message'


def test_group_does_not_collect_personal_data(integrated, tmp_path):
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    store.receive([update(1, 'Секретное сообщение', chat={'type': 'group', 'id': -1})])
    with store.connect() as connection:
        assert 'Секретное' not in connection.execute('SELECT payload FROM inbox').fetchone()[0]
    assert handler.process_next()
    assert store.dialog(123) == {'step': 'idle'}
    sender = FakeTelegram()
    send_reply(store, sender, now=100)
    assert 'https://t.me/example_test_bot' in sender.sent[0][1]


def test_binding_dialog_stores_only_hash_and_confirms(integrated, lead_data, tmp_path):
    created = integrated.test_client().post('/lead', json=lead_data).json
    code = created['telegram_subscription_url'].split('start=')[1]
    path = tmp_path / 'bot.sqlite3'
    store = StateStore(path)
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    deliver(store, handler, 1, '/start ' + code)
    assert code not in path.read_bytes().decode(errors='ignore')
    assert store.dialog(123)['step'] == 'binding'
    with store.connect() as connection:
        answer = connection.execute('SELECT payload FROM replies').fetchone()[0]
        assert lead_data['name'] not in answer and lead_data['message'] not in answer
    deliver(store, handler, 2, 'Подключить уведомления')
    assert store.dialog(123)['step'] == 'bound'


def test_inbox_survives_restart_before_processing(integrated, tmp_path):
    path = tmp_path / 'bot.sqlite3'
    store = StateStore(path)
    store.receive([update(9, 'Оставить заявку')])
    assert store.offset() == 10
    restored = StateStore(path)
    assert DialogHandler(restored, LocalCRM(integrated), 'example_test_bot').process_next()
    assert restored.dialog(123)['step'] == 'name'


def test_edit_unexpected_input_and_cancel(integrated, tmp_path):
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    fill_draft(store, handler)
    first_id = store.dialog(123)['submission_id']
    deliver(store, handler, 6, '/unknown')
    assert store.dialog(123)['step'] == 'confirm'
    deliver(store, handler, 7, 'Изменить')
    assert store.dialog(123)['step'] == 'name'
    assert store.dialog(123)['submission_id'] != first_id
    deliver(store, handler, 8, 'Отменить')
    assert store.dialog(123) == {'step': 'idle'}
    assert integrated.test_client().get('/leads').json['total'] == 0


def test_invalid_binding_has_actionable_reply(integrated, tmp_path):
    store = StateStore(tmp_path / 'bot.sqlite3')
    handler = DialogHandler(store, LocalCRM(integrated), 'example_test_bot')
    deliver(store, handler, 1, '/start ' + 'x' * 43)
    deliver(store, handler, 2, 'Подключить уведомления')
    assert store.dialog(123)['step'] == 'idle'
    sender = FakeTelegram()
    while send_reply(store, sender, now=100):
        pass
    assert 'менеджеру' in sender.sent[-1][1]
