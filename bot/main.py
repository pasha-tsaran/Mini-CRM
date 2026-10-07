import json
import time

from bot.config import require_settings, state_path
from bot.handlers import DialogHandler
from bot.state import StateStore
from integrations.crm import CRMClient
from integrations.http import RemoteError
from integrations.telegram import TelegramClient


def send_reply(store, telegram, now=None):
    now = time.time() if now is None else now
    row = store.claim_reply(now)
    if row is None:
        return False
    try:
        message = telegram.send_message(row['chat_id'], **json.loads(row['payload']))
    except RemoteError as error:
        store.finish_reply(row, now, error=error)
    else:
        store.finish_reply(row, now, message_id=message['message_id'])
    return True


def main():
    settings = require_settings()
    try:
        crm = CRMClient(settings['CRM_BASE_URL'], settings['CRM_BOT_API_TOKEN'])
    except ValueError:
        raise SystemExit('Проверьте локальный CRM_BASE_URL.') from None
    telegram = TelegramClient(settings['TELEGRAM_BOT_TOKEN'])
    store = StateStore(state_path())
    handler = DialogHandler(store, crm, settings['TELEGRAM_BOT_USERNAME'])
    print('Polling-бот запущен. Только личные чаты. Остановка: Ctrl+C.')
    failures = 0
    try:
        while True:
            # Сначала восстанавливаем события и ответы, устойчиво записанные до сбоя.
            for _ in range(100):
                if not handler.process_next():
                    break
            for _ in range(100):
                if not send_reply(store, telegram):
                    break
            try:
                updates = telegram.get_updates(store.offset())
                store.receive(updates)
                failures = 0
            except RemoteError as error:
                if error.code in (401, 409):
                    raise SystemExit('Проверьте токен, отсутствие webhook и другого polling-процесса.') from None
                failures += 1
                # Тексты исключений и URL Bot API никогда не печатаются.
                print('Telegram временно недоступен. Сохранённые события не потеряны.')
                time.sleep(max(error.retry_after, min(60, 2 ** min(failures, 6))))
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit('Бот остановлен из-за внутренней ошибки. Состояние сохранено; проверьте доступность БД и перезапустите процесс.') from None


if __name__ == '__main__':
    main()
