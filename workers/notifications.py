import time
from datetime import timedelta

from app.services.notifications import format_notification
from app.services.telegram import utcnow
from database.repositories import outbox
from integrations.http import RemoteError
from integrations.telegram import TelegramClient


def run_once(factory, telegram, zone='Europe/Moscow', now=None) -> bool:
    now = now or utcnow()
    with factory.begin() as session:
        item = outbox.claim(session, now)
    if item is None:
        return False
    failure = None
    message_id = None
    try:
        message_id = telegram.send_message(item.chat_id, format_notification(item, zone))['message_id']
    except RemoteError as error:
        failure = error
    # Ни один сетевой запрос не выполняется под блокировкой SQLite.
    with factory.begin() as session:
        current = outbox.finish(session, item.id, item.attempts)
        if current is None:
            return True
        current.lease_until = None
        if failure is None:
            current.state, current.sent_at = 'sent', now
            current.telegram_message_id = message_id
            current.error_code = None
        elif failure.code == 403:
            outbox.block_chat(session, item.chat_id)
        elif failure.code in (400, 401, 404):
            current.state, current.error_code = 'failed', f'telegram_{failure.code}'
        else:
            delay = max(failure.retry_after, min(3600, 5 * 2 ** min(item.attempts, 10)))
            current.state, current.error_code = 'retry', f'telegram_{failure.code or "network"}'
            current.next_attempt_at = now + timedelta(seconds=delay)
    return True


def main():
    from app.main import create_app
    from bot.config import require_settings

    settings = require_settings(('TELEGRAM_BOT_TOKEN',))
    app = create_app()
    client = TelegramClient(settings['TELEGRAM_BOT_TOKEN'])
    print('Обработчик уведомлений запущен. Остановка: Ctrl+C.')
    try:
        while True:
            if not run_once(app.extensions['db_session_factory'], client, app.config['UI_TIMEZONE']):
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit('Обработчик остановлен из-за внутренней ошибки. Очередь сохранена; проверьте доступность БД и перезапустите процесс.') from None
    finally:
        app.extensions['database_engine'].dispose()


if __name__ == '__main__':
    main()
