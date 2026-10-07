from uuid import uuid4

from pydantic import ValidationError

from app.schemas.lead import LeadCreate
from app.services.notifications import STATUS_LABELS
from integrations.http import RemoteError


def keyboard(*labels):
    return {'keyboard': [[{'text': label}] for label in labels], 'resize_keyboard': True}


HOME = keyboard('Оставить заявку')
CONFIRM = keyboard('Отправить', 'Изменить', 'Отменить')
PHONE = {'keyboard': [[{'text': 'Поделиться номером', 'request_contact': True}],
                      [{'text': 'Отменить'}]], 'resize_keyboard': True}


def reply(text, markup=None):
    return {'text': text, 'reply_markup': markup or {'remove_keyboard': True}}


def field_value(field, value):
    fields = {'name': 'Клиент', 'phone': '+79991234567', 'message': 'Обращение', field: value}
    return getattr(LeadCreate.model_validate(fields), field)


def receipt(result):
    return f'Заявка №{result["id"]} зарегистрирована.\nСтатус: {STATUS_LABELS[result["status"]]}.\nОб изменении статуса сообщим здесь'


class DialogHandler:
    def __init__(self, store, crm, username):
        self.store, self.crm, self.username = store, crm, username

    def process_next(self):
        update = self.store.next_update()
        if update is None:
            return False
        message = update.get('message', {})
        chat = message.get('chat', {})
        user_id = message.get('from', {}).get('id')
        if not chat.get('id') or not user_id:
            self.store.complete(update['update_id'])
            return True
        if chat.get('type') != 'private':
            self.store.complete(update['update_id'], chat_id=chat['id'], reply=reply(
                f'Оформить заявку можно только в личном чате: https://t.me/{self.username}'))
            return True
        if user_id != chat['id'] or message.get('from', {}).get('is_bot'):
            self.store.complete(update['update_id'])
            return True
        state = self.store.dialog(user_id)
        state, answer = self.transition(state, message, user_id)
        self.store.complete(update['update_id'], user_id, state, chat['id'], answer)
        return True

    def transition(self, state, message, user_id):
        text = message.get('text', '')
        step = state['step']
        parts = text.split(maxsplit=1)
        command = parts[0].split('@')[0] if parts else ''
        # После неопределённого исхода нельзя менять содержимое или id отправки.
        if step == 'sending':
            if text in ('Отправить', 'Повторить отправку'):
                return self.send(state, user_id)
            return state, reply('Результат отправки пока неизвестен. Черновик сохранён. Повторите отправку: дубль не создастся.', keyboard('Повторить отправку'))
        if step == 'binding_sending':
            if text in ('Подключить уведомления', 'Повторить подключение'):
                return self.bind(state, user_id)
            return state, reply('Результат подключения пока неизвестен. Повторите подтверждение.', keyboard('Повторить подключение'))
        if command == '/cancel' or text == 'Отменить':
            return {'step': 'idle'}, reply('Действие отменено. Можно оформить новую заявку.', HOME)
        if command == '/start':
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                return {'step': 'binding', 'code': parts[1], 'request_id': uuid4().hex}, reply(
                    'Подключить уведомления по заявке к этому личному чату?', keyboard('Подключить уведомления', 'Отменить'))
            return state, reply('Здравствуйте! Здесь можно оставить заявку и получать сообщения о её статусе. Для отмены используйте /cancel.', HOME)
        if text == 'Оставить заявку':
            return {'step': 'name', 'submission_id': uuid4().hex}, reply('Как к вам обращаться? Введите имя (до 100 символов).')
        if step == 'binding' and text == 'Подключить уведомления':
            return self.bind(state, user_id)
        if command.startswith('/'):
            return state, reply('Неизвестная команда. Используйте /start или /cancel.')
        if step in ('name', 'phone', 'message'):
            value = text
            if step == 'phone' and 'contact' in message:
                contact = message['contact']
                if contact.get('user_id') != user_id:
                    return state, reply('Этот контакт не подтверждает ваш номер. Поделитесь своим контактом или введите номер вручную.', PHONE)
                value = contact.get('phone_number', '')
                if len(value) == 11 and value.startswith('7') and value.isascii() and value.isdigit():
                    value = '+' + value
            try:
                state[step] = field_value(step, value)
            except ValidationError:
                hints = {'name': 'Введите имя от 1 до 100 символов.',
                         'phone': 'Введите номер в формате +7 999 123-45-67 или 8 (999) 123-45-67.',
                         'message': 'Введите описание от 1 до 2000 символов.'}
                return state, reply(hints[step], PHONE if step == 'phone' else None)
            if step == 'name':
                state['step'] = 'phone'
                return state, reply('Поделитесь своим номером кнопкой или введите его вручную.', PHONE)
            if step == 'phone':
                state['step'] = 'message'
                return state, reply('Опишите обращение (до 2000 символов).')
            state['step'] = 'confirm'
            return state, reply(f'Проверьте заявку:\nИмя: {state["name"]}\nТелефон: {state["phone"]}\nОбращение: {state["message"]}', CONFIRM)
        if step == 'confirm':
            if text == 'Изменить':
                return {'step': 'name', 'submission_id': uuid4().hex}, reply('Введите имя заново. Затем проверим телефон и описание.')
            if text == 'Отправить':
                return self.send(state, user_id)
            return state, reply('Выберите «Отправить», «Изменить» или «Отменить».', CONFIRM)
        if step == 'done' and text in ('Отправить', 'Повторить отправку'):
            return state, reply(receipt(state['result']), HOME)
        if step == 'bound' and text in ('Подключить уведомления', 'Повторить подключение'):
            return state, reply('Уведомления уже подключены к этому чату.', HOME)
        return state, reply('Нажмите «Оставить заявку» или используйте /cancel.', HOME)

    def send(self, state, user_id):
        state['step'] = 'sending'
        self.store.save_dialog(user_id, state)
        payload = {key: state[key] for key in ('submission_id', 'name', 'phone', 'message')}
        payload.update(telegram_user_id=user_id, telegram_chat_id=user_id)
        try:
            result = self.crm.create_lead(payload)
        except RemoteError as error:
            if error.code == 422:
                state['step'] = 'confirm'
                return state, reply('CRM отклонила данные. Выберите «Изменить» и проверьте поля.', CONFIRM)
            return state, reply('Не удалось подтвердить сохранение в CRM. Черновик сохранён. Повторите отправку; при повторном конфликте обратитесь к менеджеру.', keyboard('Повторить отправку'))
        # Персональные поля больше не нужны боту после подтверждённого commit CRM.
        result = {'id': result['id'], 'status': result['status']}
        return {'step': 'done', 'result': result}, reply(receipt(result), HOME)

    def bind(self, state, user_id):
        state['step'] = 'binding_sending'
        self.store.save_dialog(user_id, state)
        try:
            result = self.crm.bind({'code': state['code'], 'request_id': state['request_id'],
                                    'telegram_user_id': user_id, 'telegram_chat_id': user_id})
        except RemoteError as error:
            if error.code in (409, 422):
                return {'step': 'idle'}, reply('Ссылка недействительна, истекла или уже использована. Оформите новую заявку или обратитесь к менеджеру.', HOME)
            return state, reply('CRM недоступна. Подтверждение сохранено, попробуйте ещё раз.', keyboard('Повторить подключение'))
        return {'step': 'bound', 'lead_id': result['id']}, reply(f'Уведомления по заявке №{result["id"]} подключены. Текущий статус придёт отдельным сообщением.', HOME)
