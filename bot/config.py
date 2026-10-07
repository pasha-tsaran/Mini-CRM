import os
import re

from app.config import database_path, load_environment


def require_settings(names=('TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_USERNAME', 'CRM_BASE_URL', 'CRM_BOT_API_TOKEN')):
    load_environment()
    values = {key: os.environ.get(key, '').strip() for key in names}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise SystemExit('Не заданы настройки: ' + ', '.join(missing) + '. Задайте их в окружении, не передавайте токены в чат.')
    if 'TELEGRAM_BOT_USERNAME' in values:
        values['TELEGRAM_BOT_USERNAME'] = values['TELEGRAM_BOT_USERNAME'].lstrip('@')
        if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', values['TELEGRAM_BOT_USERNAME']):
            raise SystemExit('Проверьте TELEGRAM_BOT_USERNAME.')
    return values


def state_path():
    return database_path(os.environ.get('BOT_STATE_PATH', 'instance/bot-state.sqlite3'))
